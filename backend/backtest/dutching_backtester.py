"""
Dutching Backtester — chronological backtesting for Dutching (Correct Score) strategies.

Validates whether the theoretical edge reported by the live Dutching scanner
materializes into real profit when tested against historical data.

Architecture:
- Streams through matches chronologically (no look-ahead)
- Builds form state incrementally (goals, SOT, xG, HT, Elo)
- Uses ProbabilityPipeline.compute_all() directly with persistent EloTracker
- Estimates CS odds from historical O/U 2.5 via estimate_bookmaker_odds()
- Constructs Dutching combinations via build_dynamic_dutch()
- Tracks bankroll, drawdown, and P&L per strategy
- Compiles summary with edge calibration metrics
"""

import math
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from collections import defaultdict
from typing import List, Optional, Dict, Tuple

logger = logging.getLogger(__name__)

from ..data_loader import load_league_data, auto_detect_data_source
from ..models import estimate_bookmaker_odds
from ..probability_pipeline import (
    ProbabilityPipeline, MODEL_POISSON, MODEL_NEGATIVE_BINOMIAL,
    build_form_state_from_df,
)
from ..dutching_scanner import (
    build_dynamic_dutch, resolve_strategy, classify_game_profile,
    bootstrap_dutching_edge, dutching_quality_score,
)
from ..elo_model import EloTracker, build_elo_tracker_from_history
from ..constants import (
    ELO_K_FACTOR, ELO_HOME_ADVANTAGE,
    NB_ALPHA_HOME, NB_ALPHA_AWAY,
    SHRINKAGE_FT, RATING_CAP_LOW, RATING_CAP_HIGH,
    LAMBDA_CAP_LOW, LAMBDA_CAP_HIGH,
    MAX_GOALS, RHO_FALLBACK,
)
from .form_tracker import update_form
from .helpers import get_league_weighted_decay

# ── Constants ──────────────────────────────────────────────────────────
STRATEGY_LABELS = {
    'auto_ia': 'IA Auto (Perfil)',
    'dynamic': 'Dinamico (Top Probs)',
    'home_fav': 'Favorito Mandante',
    'away_fav': 'Favorito Visitante',
    'draw': 'Empate',
    'under': 'Under / Jogo Truncado',
    'over': 'Over / Goleada',
}


class DutchingBacktester:
    """Chronological backtester for Dutching (Correct Score) strategies.

    Follows the same walk-forward, no-look-ahead pattern as
    ChronologicalBacktester but focused exclusively on Dutching.

    For each match in the backtest window:
    1. Computes match probabilities via ProbabilityPipeline (Poisson or NB)
    2. Reconstructs CS odds from historical O/U 2.5 market odds
    3. Builds Dutching combinations per strategy
    4. Evaluates if the actual score was covered, computes P&L
    5. Updates form state and Elo AFTER the bet decision
    """

    def __init__(self, model_type: str = MODEL_NEGATIVE_BINOMIAL):
        self.model_type = model_type

    # ── Public API ─────────────────────────────────────────────────────

    def run(
        self,
        leagues: List[str],
        start_date: str,
        end_date: str,
        strategies: List[str] = None,
        initial_bankroll: float = 10000.0,
        stake_value: float = 100.0,
        staking_rule: str = 'fixed',
        min_edge: float = 0.0,
        max_overround: float = 0.92,
        max_legs: int = 8,
        min_selections: int = 3,
        data_source: str = 'auto',
        futpython_api_key: str = '',
    ) -> dict:
        """Run Dutching backtest across selected leagues and strategies.

        Args:
            leagues: List of league codes (e.g. ['BRAZIL_SERIE_A'])
            start_date: 'YYYY-MM-DD'
            end_date: 'YYYY-MM-DD'
            strategies: List of strategy keys. Default: ['auto_ia']
            initial_bankroll: Starting bankroll per strategy
            stake_value: Fixed stake amount or Kelly fraction
            staking_rule: 'fixed' or 'kelly_quarter'
            min_edge: Minimum predicted edge to place a bet (0.0 = any positive)
            max_overround: Maximum overround for Dutching (default 0.92)
            max_legs: Maximum number of score selections per Dutch
            min_selections: Minimum selections required to place a bet
            data_source: 'auto', 'footballdata', 'futpython'
            futpython_api_key: API key for FutPython data source

        Returns:
            Dict with summary, bets, equity_curves, strategy_breakdown
        """
        if strategies is None:
            strategies = ['auto_ia']

        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)

        # ── 1. Load data ──────────────────────────────────────────
        all_matches = []
        for lc in leagues:
            ds = data_source if data_source != 'auto' else auto_detect_data_source(lc)
            df = load_league_data(lc, start_date='2020-08-01', data_source=ds, api_key=futpython_api_key)
            if not df.empty:
                all_matches.append(df)

        if not all_matches:
            return {"error": "Nenhum dado encontrado para as ligas selecionadas."}

        combined_df = pd.concat(all_matches, ignore_index=True)
        combined_df = combined_df.sort_values(by=['Date', 'Time']).reset_index(drop=True)

        # Pre-compute league-average xG for fallback
        _league_xg_fallback = {}
        for _lc in leagues:
            _ldf = combined_df[combined_df['LeagueCode'] == _lc]
            _hxg = _ldf['HomeXG'].dropna()
            _axg = _ldf['AwayXG'].dropna()
            _league_xg_fallback[_lc] = {
                'home': float(_hxg.mean()) if len(_hxg) > 10 else 1.45,
                'away': float(_axg.mean()) if len(_axg) > 10 else 1.15,
            }

        # ── 2. State trackers ─────────────────────────────────────
        team_home_scored = defaultdict(list)
        team_home_conceded = defaultdict(list)
        team_away_scored = defaultdict(list)
        team_away_conceded = defaultdict(list)

        team_home_sot = defaultdict(list)
        team_home_sot_conceded = defaultdict(list)
        team_away_sot = defaultdict(list)
        team_away_sot_conceded = defaultdict(list)

        team_home_xg = defaultdict(list)
        team_home_xg_conceded = defaultdict(list)
        team_away_xg = defaultdict(list)
        team_away_xg_conceded = defaultdict(list)

        team_home_scored_ht = defaultdict(list)
        team_home_conceded_ht = defaultdict(list)
        team_away_scored_ht = defaultdict(list)
        team_away_conceded_ht = defaultdict(list)

        league_home_goals = defaultdict(list)
        league_away_goals = defaultdict(list)
        league_home_sot = defaultdict(list)
        league_away_sot = defaultdict(list)
        league_home_xg = defaultdict(list)
        league_away_xg = defaultdict(list)
        league_home_goals_ht = defaultdict(list)
        league_away_goals_ht = defaultdict(list)

        # ── 3. Warm-up: build Elo from matches before start_date ──
        warmup_df = combined_df[combined_df['Date'] < start_dt].copy()
        elo_tracker = build_elo_tracker_from_history(warmup_df, 'all')

        # ── 4. Warm-up: build form state from matches before start_date ──
        form_state = build_form_state_from_df(combined_df, start_dt)
        team_home_scored = form_state['team_h_scored']
        team_home_conceded = form_state['team_h_conceded']
        team_away_scored = form_state['team_a_scored']
        team_away_conceded = form_state['team_a_conceded']
        team_home_sot = form_state['team_h_sot']
        team_home_sot_conceded = form_state['team_h_sot_conc']
        team_away_sot = form_state['team_a_sot']
        team_away_sot_conceded = form_state['team_a_sot_conc']
        team_home_xg = form_state['team_h_xg']
        team_home_xg_conceded = form_state['team_h_xg_conc']
        team_away_xg = form_state['team_a_xg']
        team_away_xg_conceded = form_state['team_a_xg_conc']
        team_home_scored_ht = form_state['team_h_scored_ht']
        team_home_conceded_ht = form_state['team_h_conceded_ht']
        team_away_scored_ht = form_state['team_a_scored_ht']
        team_away_conceded_ht = form_state['team_a_conceded_ht']
        league_home_goals = form_state['lge_h_goals']
        league_away_goals = form_state['lge_a_goals']
        league_home_sot = form_state['lge_h_sot']
        league_away_sot = form_state['lge_a_sot']
        league_home_xg = form_state['lge_h_xg']
        league_away_xg = form_state['lge_a_xg']
        league_home_goals_ht = form_state['lge_h_goals_ht']
        league_away_goals_ht = form_state['lge_a_goals_ht']

        # ── 5. Initialize per-strategy tracking ───────────────────
        pipeline = ProbabilityPipeline(model_type=self.model_type)
        league_rho_cache = {}
        league_goals_for_rho = defaultdict(lambda: {'h': [], 'a': [], 'lh': [], 'la': []})

        bankrolls = {s: initial_bankroll for s in strategies}
        peak_bankrolls = {s: initial_bankroll for s in strategies}
        max_drawdowns = {s: 0.0 for s in strategies}
        current_dds = {s: 0.0 for s in strategies}
        total_bets = {s: 0 for s in strategies}
        total_wins = {s: 0 for s in strategies}
        total_profit = {s: 0.0 for s in strategies}
        total_staked = {s: 0.0 for s in strategies}
        equity_curves = {s: [{'date': start_date, 'bankroll': round(initial_bankroll, 2)}]
                         for s in strategies}
        all_bets = []

        # Strategy hit/miss tracking per score
        score_hits = defaultdict(lambda: defaultdict(int))   # strategy -> score -> hits
        score_misses = defaultdict(lambda: defaultdict(int))  # strategy -> score -> missed (score predicted but wrong)

        # Per-date tracking for daily returns
        prev_date = None
        day_start_bankrolls = {s: initial_bankroll for s in strategies}
        daily_pnl = {s: defaultdict(float) for s in strategies}
        all_daily_returns = {s: [] for s in strategies}

        matches_total = 0
        matches_skipped_no_odds = 0
        matches_in_window = 0

        last_match_date = {}

        # ── 6. Chronological iteration ────────────────────────────
        for row in combined_df.to_dict('records'):
            match_date = row['Date']
            date_str = match_date.strftime('%Y-%m-%d')

            # Day boundary: record daily return
            if prev_date is not None and date_str != prev_date:
                for s in strategies:
                    if day_start_bankrolls[s] > 0 and prev_date in daily_pnl[s]:
                        daily_ret = daily_pnl[s][prev_date] / day_start_bankrolls[s]
                        all_daily_returns[s].append(daily_ret)
                    day_start_bankrolls[s] = bankrolls[s]
            elif prev_date is None:
                prev_date = date_str

            league_code = row['LeagueCode']
            if league_code not in leagues:
                continue

            _decay = get_league_weighted_decay(league_code)
            home_team = row['HomeTeam']
            away_team = row['AwayTeam']
            fthg = row.get('FTHG')
            ftag = row.get('FTAG')

            # Skip unplayed matches
            if pd.isna(fthg) or pd.isna(ftag):
                continue

            matches_total += 1
            fthg = int(fthg)
            ftag = int(ftag)
            actual_score = f"{fthg}-{ftag}"
            total_goals = fthg + ftag

            # Extract goals data
            hthg = row.get('HTHG')
            htag = row.get('HTAG')
            hst = row.get('HST')
            ast = row.get('AST')
            hxg = row.get('HomeXG')
            axg = row.get('AwayXG')

            # xG fallback (same as ChronologicalBacktester)
            if pd.isna(hxg) or hxg == 0:
                hxg = (hst * 0.33) if (not pd.isna(hst) and hst > 0) else \
                    _league_xg_fallback.get(league_code, {}).get('home', 1.45)
            if pd.isna(axg) or axg == 0:
                axg = (ast * 0.33) if (not pd.isna(ast) and ast > 0) else \
                    _league_xg_fallback.get(league_code, {}).get('away', 1.15)

            # Only compute probabilities and bet within [start_date, end_date]
            in_window = start_dt <= match_date <= end_dt

            # ── Compute match probabilities (always, for form tracking) ──
            try:
                # Compute rho
                if league_code in league_rho_cache:
                    rho = league_rho_cache[league_code]
                else:
                    rh = league_goals_for_rho[league_code]['h']
                    ra = league_goals_for_rho[league_code]['a']
                    if len(rh) >= 50:
                        from ..elo_model import estimate_dynamic_rho
                        rho = estimate_dynamic_rho(
                            rh[-200:], ra[-200:],
                            league_goals_for_rho[league_code]['lh'][-200:],
                            league_goals_for_rho[league_code]['la'][-200:],
                        )
                        league_rho_cache[league_code] = rho
                    else:
                        rho = RHO_FALLBACK

                bundle = pipeline.compute_all(
                    team_home_scored, team_home_conceded,
                    team_away_scored, team_away_conceded,
                    league_home_goals, league_away_goals,
                    team_home_sot, team_home_sot_conceded,
                    team_away_sot, team_away_sot_conceded,
                    league_home_sot, league_away_sot,
                    team_home_xg, team_home_xg_conceded,
                    team_away_xg, team_away_xg_conceded,
                    league_home_xg, league_away_xg,
                    team_home_scored_ht, team_home_conceded_ht,
                    team_away_scored_ht, team_away_conceded_ht,
                    league_home_goals_ht, league_away_goals_ht,
                    home_team, away_team, league_code, _decay,
                    league_rho_cache, league_goals_for_rho, elo_tracker,
                )
                pred = bundle.to_dict()

                # Also give pred direct access to bundle attrs for CS access
                pred['prob_matrix'] = bundle.prob_matrix
            except Exception:
                # If prediction fails, still update form but skip betting
                _update_form_trackers(
                    team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                    league_home_goals, league_away_goals, league_code,
                    home_team, away_team, fthg, ftag,
                    team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                    league_home_sot, league_away_sot, hst, ast,
                    team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                    league_home_xg, league_away_xg, hxg, axg,
                    team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                    league_home_goals_ht, league_away_goals_ht, hthg, htag,
                )
                rho_data = league_goals_for_rho[league_code]
                rho_data['h'].append(fthg)
                rho_data['a'].append(ftag)
                rho_data['lh'].append(1.3)
                rho_data['la'].append(1.0)
                elo_tracker.update(home_team, away_team, fthg, ftag)
                last_match_date[home_team] = match_date
                last_match_date[away_team] = match_date
                continue

            # ── Only evaluate bets within the backtest window ──
            if in_window:
                matches_in_window += 1

                # Extract historical O/U 2.5 odds (handle both CSV formats)
                odds_over25 = _extract_odds(row, ['B365>2.5', 'Over_FT_2_5', 'B365_Over_FT_2_5'])
                odds_under25 = _extract_odds(row, ['B365<2.5', 'Under_FT_2_5', 'B365_Under_FT_2_5'])

                if pd.isna(odds_over25) or pd.isna(odds_under25) or \
                   odds_over25 <= 1.0 or odds_under25 <= 1.0:
                    matches_skipped_no_odds += 1
                else:
                    # Reconstruct CS odds from O/U 2.5
                    try:
                        est_odds = estimate_bookmaker_odds(
                            odds_over25, odds_under25,
                            pred['lambda_home'], pred['lambda_away'],
                            pred.get('rho'), bookmaker='Bet365',
                        )
                    except Exception:
                        est_odds = None

                    if est_odds:
                        # Determine if home is favorite (for auto_ia strategy)
                        is_home_fav = pred.get('prob_h', 0.37) > pred.get('prob_a', 0.37)

                        for strategy in strategies:
                            # Resolve strategy using fuzzy classifier
                            current_strat = resolve_strategy(strategy, pred, is_home_fav)
                            game_profile = classify_game_profile(pred, is_home_fav)

                            # Build Dutching combination
                            (outcomes, sel_probs, sel_odds, sel_keys, market_label,
                             cum_prob, dutching_odd, edge) = build_dynamic_dutch(
                                pred, est_odds, strategy=current_strat,
                                max_legs=max_legs, max_overround=max_overround,
                                min_selections=min_selections,
                            )

                            if outcomes is None or edge < min_edge:
                                continue

                            # Bootstrap confidence for edge
                            edge_confidence = bootstrap_dutching_edge(
                                pred, est_odds, strategy=current_strat,
                                max_legs=max_legs, max_overround=max_overround,
                                min_selections=min_selections,
                                n_bootstrap=150, is_home_fav=is_home_fav,
                            )

                            # Quality score
                            quality = dutching_quality_score(
                                edge=edge,
                                edge_ci_95=edge_confidence.get('edge_ci_95'),
                                profile_confidence=game_profile['confidence'],
                                dutching_odd=dutching_odd,
                                n_selections=len(outcomes),
                                market_divergence=game_profile.get('market_divergence', 0),
                                edge_prob_positive=edge_confidence.get('prob_positive'),
                            )

                            # Calculate stake
                            if staking_rule == 'kelly_quarter':
                                # Kelly Criterion: f* = edge / (odds - 1), quarter Kelly
                                kelly_fraction = edge / (dutching_odd - 1.0) if dutching_odd > 1.01 else 0.0
                                stake = bankrolls[strategy] * kelly_fraction * 0.25
                                stake = max(5.0, min(stake, bankrolls[strategy] * 0.05))
                            else:
                                stake = stake_value

                            if stake > bankrolls[strategy]:
                                stake = bankrolls[strategy]
                            if stake <= 0:
                                continue

                            # Evaluate result
                            covered = actual_score in outcomes
                            if covered:
                                idx = outcomes.index(actual_score)
                                winning_odd = sel_odds[idx]
                                # Dutching profit: stake allocated to winning leg * its odd - total_stake
                                overround = sum(1.0 / o for o in sel_odds)
                                stake_on_winner = stake * (1.0 / winning_odd) / overround
                                profit = stake_on_winner * winning_odd - stake
                            else:
                                winning_odd = 0.0
                                profit = -stake

                            # Update state
                            bankrolls[strategy] += profit
                            bankrolls[strategy] = max(0.01, bankrolls[strategy])  # no negative bankroll
                            total_bets[strategy] += 1
                            total_profit[strategy] += profit
                            total_staked[strategy] += stake
                            if covered:
                                total_wins[strategy] += 1

                            # Track drawdown
                            if bankrolls[strategy] > peak_bankrolls[strategy]:
                                peak_bankrolls[strategy] = bankrolls[strategy]
                                current_dds[strategy] = 0.0
                            else:
                                current_dd = 1.0 - bankrolls[strategy] / peak_bankrolls[strategy] \
                                    if peak_bankrolls[strategy] > 0 else 0.0
                                max_drawdowns[strategy] = max(max_drawdowns[strategy], current_dd)

                            # Daily P&L
                            daily_pnl[strategy][date_str] += profit

                            # Coverage analysis
                            if covered:
                                score_hits[strategy][actual_score] += 1
                            for sel in outcomes:
                                if sel != actual_score:
                                    score_misses[strategy][sel] += 1

                            # Record bet
                            all_bets.append({
                                'date': date_str,
                                'league': league_code,
                                'home_team': home_team,
                                'away_team': away_team,
                                'actual_score': actual_score,
                                'total_goals': total_goals,
                                'strategy': strategy,
                                'resolved_strategy': current_strat,
                                'game_profile': game_profile['best_profile'],
                                'profile_confidence': game_profile['confidence'],
                                'market_label': f"{'IA ' if strategy == 'auto_ia' else ''}{market_label}",
                                'dutching_odd': round(dutching_odd, 2),
                                'model_prob': round(cum_prob, 4),
                                'predicted_edge': round(edge, 4),
                                'edge_ci_95_low': edge_confidence.get('edge_ci_95', (None, None))[0],
                                'edge_ci_95_high': edge_confidence.get('edge_ci_95', (None, None))[1],
                                'edge_prob_positive': edge_confidence.get('prob_positive'),
                                'edge_std': edge_confidence.get('edge_std'),
                                'quality_score': quality['score'],
                                'quality_verdict': quality['verdict'],
                                'quality_verdict_label': quality['verdict_label'],
                                'quality_verdict_color': quality['verdict_color'],
                                'quality_breakdown': quality['breakdown'],
                                'selections': outcomes,
                                'selection_odds': [round(o, 2) for o in sel_odds],
                                'selection_probs': [round(p, 4) for p in sel_probs],
                                'total_stake': round(stake, 2),
                                'covered': covered,
                                'winning_score': actual_score if covered else None,
                                'winning_odd': round(winning_odd, 2) if covered else None,
                                'profit': round(profit, 2),
                                'bankroll': round(bankrolls[strategy], 2),
                                'won': covered,
                                'lambda_home': round(pred.get('lambda_home', 0), 2),
                                'lambda_away': round(pred.get('lambda_away', 0), 2),
                                'lambda_total': round(pred.get('lambda_home', 0) + pred.get('lambda_away', 0), 2),
                                'prob_h': round(pred.get('prob_h', 0), 4),
                                'prob_d': round(pred.get('prob_d', 0), 4),
                                'prob_a': round(pred.get('prob_a', 0), 4),
                                'prob_over25': round(pred.get('prob_over_25', 0), 4),
                                'prob_under25': round(pred.get('prob_under_25', 0), 4),
                            })

                            # Update equity curve (record after each bet)
                            equity_curves[strategy].append({
                                'date': date_str,
                                'bankroll': round(bankrolls[strategy], 2),
                            })

            # ── 7. Update form AFTER bet decision (prevents look-ahead) ──
            _update_form_trackers(
                team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                league_home_goals, league_away_goals, league_code,
                home_team, away_team, fthg, ftag,
                team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                league_home_sot, league_away_sot, hst, ast,
                team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                league_home_xg, league_away_xg, hxg, axg,
                team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                league_home_goals_ht, league_away_goals_ht, hthg, htag,
            )

            # Update rho data
            rho_data = league_goals_for_rho[league_code]
            rho_data['h'].append(fthg)
            rho_data['a'].append(ftag)
            rho_data['lh'].append(pred.get('lambda_home', 1.3))
            rho_data['la'].append(pred.get('lambda_away', 1.0))

            # Update Elo
            elo_tracker.update(home_team, away_team, fthg, ftag)

            # Track last match date for rest-day calculation
            last_match_date[home_team] = match_date
            last_match_date[away_team] = match_date

        # ── 8. Compile summary ────────────────────────────────────
        summary = _compile_dutching_summary(
            strategies, all_bets, bankrolls, initial_bankroll,
            total_bets, total_wins, total_profit, total_staked,
            max_drawdowns, equity_curves, all_daily_returns,
            score_hits, score_misses,
            matches_total, matches_in_window, matches_skipped_no_odds,
            start_date, end_date, leagues,
        )

        return summary


# ── Helpers ────────────────────────────────────────────────────────────

def _update_form_trackers(
    team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
    league_home_goals, league_away_goals, league_code,
    home_team, away_team, fthg, ftag,
    team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
    league_home_sot, league_away_sot, hst, ast,
    team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
    league_home_xg, league_away_xg, hxg, axg,
    team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
    league_home_goals_ht, league_away_goals_ht, hthg, htag,
):
    """Update rolling form trackers with match result (AFTER bet evaluation)."""
    update_form(
        team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
        league_home_goals, league_away_goals, league_code,
        home_team, away_team, fthg, ftag,
        team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
        league_home_sot, league_away_sot, hst, ast,
        team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
        league_home_xg, league_away_xg, hxg, axg,
        team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
        league_home_goals_ht, league_away_goals_ht, hthg, htag,
    )


def _extract_odds(row: dict, candidates: List[str]) -> float:
    """Extract odds value from row, trying multiple column name candidates."""
    for col in candidates:
        val = row.get(col)
        if val is not None and not pd.isna(val):
            try:
                v = float(val)
                if v > 1.0:
                    return v
            except (ValueError, TypeError):
                continue
    return np.nan


def _compile_dutching_summary(
    strategies, all_bets, bankrolls, initial_bankroll,
    total_bets, total_wins, total_profit, total_staked,
    max_drawdowns, equity_curves, all_daily_returns,
    score_hits, score_misses,
    matches_total, matches_in_window, matches_skipped_no_odds,
    start_date, end_date, leagues,
) -> dict:
    """Compile comprehensive backtest summary."""
    strategy_breakdown = {}
    overall_bets = []

    for s in strategies:
        s_bets = [b for b in all_bets if b['strategy'] == s]
        overall_bets.extend(s_bets)

        n_bets = total_bets[s]
        n_wins = total_wins[s]
        profit = total_profit[s]
        staked = total_staked[s]
        final_br = bankrolls[s]

        roi = (profit / staked) if staked > 0 else 0.0
        win_rate = (n_wins / n_bets) if n_bets > 0 else 0.0
        avg_edge_pred = np.mean([b['predicted_edge'] for b in s_bets]) if s_bets else 0.0
        avg_edge_real = roi

        # Edge calibration: realized/predicted (1.0 = perfect)
        edge_cal = (avg_edge_real / avg_edge_pred) if avg_edge_pred > 0.001 else None

        # Sharpe ratio (from daily returns)
        daily_ret = all_daily_returns.get(s, [])
        if len(daily_ret) > 1:
            sharpe = (np.mean(daily_ret) / np.std(daily_ret)) * math.sqrt(156) if np.std(daily_ret) > 0 else 0.0
        else:
            sharpe = 0.0

        # Coverage analysis: top hit/miss scores
        most_hit = sorted(score_hits[s].items(), key=lambda x: x[1], reverse=True)[:10]
        most_missed = sorted(score_misses[s].items(), key=lambda x: x[1], reverse=True)[:10]

        # Monthly breakdown
        monthly = defaultdict(lambda: {'bets': 0, 'wins': 0, 'profit': 0.0, 'staked': 0.0})
        for b in s_bets:
            month_key = b['date'][:7]
            monthly[month_key]['bets'] += 1
            if b['won']:
                monthly[month_key]['wins'] += 1
            monthly[month_key]['profit'] += b['profit']
            monthly[month_key]['staked'] += b['total_stake']

        monthly_breakdown = []
        for mk in sorted(monthly.keys()):
            md = monthly[mk]
            monthly_breakdown.append({
                'month': mk,
                'bets': md['bets'],
                'wins': md['wins'],
                'win_rate': round(md['wins'] / md['bets'] * 100, 1) if md['bets'] > 0 else 0,
                'profit': round(md['profit'], 2),
                'roi': round(md['profit'] / md['staked'] * 100, 1) if md['staked'] > 0 else 0,
            })

        # League breakdown
        league_stats = defaultdict(lambda: {'bets': 0, 'wins': 0, 'profit': 0.0, 'staked': 0.0})
        for b in s_bets:
            lc = b['league']
            league_stats[lc]['bets'] += 1
            if b['won']:
                league_stats[lc]['wins'] += 1
            league_stats[lc]['profit'] += b['profit']
            league_stats[lc]['staked'] += b['total_stake']

        league_breakdown = []
        for lc in sorted(league_stats.keys()):
            ls = league_stats[lc]
            league_breakdown.append({
                'league': lc,
                'bets': ls['bets'],
                'wins': ls['wins'],
                'win_rate': round(ls['wins'] / ls['bets'] * 100, 1) if ls['bets'] > 0 else 0,
                'profit': round(ls['profit'], 2),
                'roi': round(ls['profit'] / ls['staked'] * 100, 1) if ls['staked'] > 0 else 0,
            })

        # Odds range breakdown
        odds_ranges = [
            (0, 1.5, '1.00-1.50'),
            (1.5, 2.0, '1.50-2.00'),
            (2.0, 3.0, '2.00-3.00'),
            (3.0, 5.0, '3.00-5.00'),
            (5.0, 99.0, '5.00+'),
        ]
        odds_range_stats = []
        for lo, hi, label in odds_ranges:
            range_bets = [b for b in s_bets if lo <= b['dutching_odd'] < hi]
            n = len(range_bets)
            w = sum(1 for b in range_bets if b['won'])
            p = sum(b['profit'] for b in range_bets)
            s_staked = sum(b['total_stake'] for b in range_bets)
            odds_range_stats.append({
                'range': label,
                'bets': n,
                'wins': w,
                'win_rate': round(w / n * 100, 1) if n > 0 else 0,
                'profit': round(p, 2),
                'roi': round(p / s_staked * 100, 1) if s_staked > 0 else 0,
            })

        strategy_breakdown[s] = {
            'label': STRATEGY_LABELS.get(s, s),
            'total_bets': n_bets,
            'wins': n_wins,
            'win_rate': round(win_rate * 100, 1),
            'net_profit': round(profit, 2),
            'roi': round(roi * 100, 2),
            'initial_bankroll': initial_bankroll,
            'final_bankroll': round(final_br, 2),
            'max_drawdown': round(max_drawdowns[s] * 100, 1),
            'sharpe_ratio': round(sharpe, 2),
            'avg_edge_predicted': round(avg_edge_pred * 100, 2),
            'avg_edge_realized': round(avg_edge_real * 100, 2),
            'edge_calibration': round(edge_cal, 2) if edge_cal is not None else None,
            'total_staked': round(staked, 2),
            'equity_curve': equity_curves.get(s, []),
            'monthly_breakdown': monthly_breakdown,
            'league_breakdown': league_breakdown,
            'odds_range_breakdown': odds_range_stats,
            'coverage_analysis': {
                'most_hit_scores': [{'score': sc, 'hits': h} for sc, h in most_hit],
                'most_missed_scores': [{'score': sc, 'misses': m} for sc, m in most_missed],
            },
        }

    # Aggregate overall summary (from all strategies combined)
    total_all_bets = sum(total_bets.values())
    total_all_wins = sum(total_wins.values())
    total_all_profit = sum(total_profit.values())
    total_all_staked = sum(total_staked.values())

    return {
        'status': 'success',
        'config': {
            'leagues': leagues,
            'start_date': start_date,
            'end_date': end_date,
            'strategies': strategies,
            'initial_bankroll': initial_bankroll,
            'matches_total_in_file': matches_total,
            'matches_in_window': matches_in_window,
            'matches_skipped_no_odds': matches_skipped_no_odds,
        },
        'summary': {
            'total_bets': total_all_bets,
            'total_wins': total_all_wins,
            'win_rate': round(total_all_wins / total_all_bets * 100, 1) if total_all_bets > 0 else 0,
            'net_profit': round(total_all_profit, 2),
            'roi': round(total_all_profit / total_all_staked * 100, 2) if total_all_staked > 0 else 0,
            'total_staked': round(total_all_staked, 2),
        },
        'strategy_breakdown': strategy_breakdown,
        'bets': sorted(all_bets, key=lambda b: (b['date'], b['home_team'])),
        'equity_curves': {s: equity_curves.get(s, []) for s in strategies},
    }
