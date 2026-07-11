import pandas as pd
import numpy as np
import math
import logging
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)
from ..data_loader import load_league_data, get_all_available_leagues
from ..ai_predictor import (predict_strategy_sustainability, compute_brier_score, 
                           compute_bootstrap_ci, compute_power_analysis, compute_rolling_roi, 
                           compute_pvalue_binomial, compute_edge_quality_score)
from ..calibration import IsotonicCalibrator
from ..ml_ensemble import MLEnsemble, StackingMetaLearner
from ..elo_model import EloTracker, estimate_dynamic_rho
from ..models import estimate_bookmaker_odds, calculate_ah_probabilities, get_fair_ah_odds
from ..probability_pipeline import ProbabilityPipeline, MODEL_POISSON, MODEL_NEGATIVE_BINOMIAL
from ..constants import ELO_K_FACTOR, ELO_HOME_ADVANTAGE, RHO_CACHE_INVALIDATION_MATCHES
from .helpers import weighted_mean, solve_kelly_multi, compute_slippage_factor, compute_corners_probs, get_league_weighted_decay, compute_drawdown_multiplier, compute_edge_scaled_cap, get_liquidity_max_stake, compute_dynamic_kelly_fraction
from .form_tracker import update_form, calculate_xg_ratings, calculate_motivation
from .metrics import compile_backtest_summary, compile_parallel_scan_summary

_FACTORIALS = [math.factorial(i) for i in range(16)]

def get_futpython_ah_odd(row, line, side="Home"):
    if pd.isna(line):
        return np.nan
    sign = "neg" if line < 0 else "pos"
    abs_line = abs(line)
    if abs_line == int(abs_line):
        line_str = str(int(abs_line))
    else:
        line_str = str(abs_line).replace('.', '_')
    col_name = f"AH_{side}_{sign}_{line_str}"
    
    val = row.get(col_name)
    if val is not None and not pd.isna(val):
        try:
            v = float(str(val).replace(',', '.'))
            if v > 1.0:
                return v
        except Exception:
            pass
    return np.nan

class ChronologicalBacktester:
    def __init__(self, rolling_games=15):
        self.rolling_games = rolling_games
        self.calibrators = {}
        self.calibration_history = defaultdict(lambda: {'probs': [], 'outcomes': []})
        self.matches_since_calibration = 0
        
        self.ml_ensembles = {}
        self.ml_history = defaultdict(lambda: {'X': [], 'y': []})
        self.matches_since_ml_fit = 0

        self.stacking_learners = {}
        self.stacking_history = defaultdict(lambda: {'poisson': [], 'xgb': [], 'outcomes': []})
        self.matches_since_stacking_fit = 0

    def export_state(self):
        """Export engine state for walk-forward continuity between folds."""
        import copy
        return {
            'calibrators': copy.deepcopy(self.calibrators),
            'calibration_history': copy.deepcopy(dict(self.calibration_history)),
            'ml_ensembles': copy.deepcopy(self.ml_ensembles),
            'ml_history': copy.deepcopy(dict(self.ml_history)),
            'stacking_learners': copy.deepcopy(self.stacking_learners),
            'stacking_history': copy.deepcopy(dict(self.stacking_history)),
            'matches_since_calibration': self.matches_since_calibration,
            'matches_since_ml_fit': self.matches_since_ml_fit,
            'matches_since_stacking_fit': self.matches_since_stacking_fit,
        }

    def transfer_state(self, state):
        """Transfer engine state from a previous walk-forward fold."""
        if state is None:
            return
        self.calibrators = state.get('calibrators', {})
        self.calibration_history = defaultdict(
            lambda: {'probs': [], 'outcomes': []},
            {k: dict(v) for k, v in state.get('calibration_history', {}).items()}
        )
        self.ml_ensembles = state.get('ml_ensembles', {})
        self.ml_history = defaultdict(
            lambda: {'X': [], 'y': []},
            {k: dict(v) for k, v in state.get('ml_history', {}).items()}
        )
        self.stacking_learners = state.get('stacking_learners', {})
        self.stacking_history = defaultdict(
            lambda: {'poisson': [], 'xgb': [], 'outcomes': []},
            {k: dict(v) for k, v in state.get('stacking_history', {}).items()}
        )
        self.matches_since_calibration = state.get('matches_since_calibration', 0)
        self.matches_since_ml_fit = state.get('matches_since_ml_fit', 0)
        self.matches_since_stacking_fit = state.get('matches_since_stacking_fit', 0)

    def run(self, leagues, start_date, end_date, market, value_threshold, initial_bankroll, staking_rule, stake_value, odds_source='B365', odds_timing='closing', run_monte_carlo=True, min_odds=1.0, max_odds=2.50, exchange_commission=0.0, use_ml=False, data_source='football-data', futpython_api_key='', min_odds_h=None, max_odds_h=None, min_odds_d=None, max_odds_d=None, min_odds_a=None, max_odds_a=None, min_odds_over25=None, max_odds_over25=None, min_odds_under25=None, max_odds_under25=None, slippage=None, oos_split_pct=20.0, oos_date_cutoff=None, model_type=MODEL_POISSON):
        """
        Runs a chronological backtest across selected leagues.
        
        leagues: list of league codes
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
        market: 'home', 'away', 'draw', 'over15', 'under25', 'over25', 'btts_yes', 'btts_no'
        value_threshold: float, e.g., 1.05 (bet when Model_Prob * Bookie_Odds > threshold)
        initial_bankroll: float, e.g., 1000.0
        staking_rule: 'fixed', 'proportional', 'kelly'
        stake_value: float (fixed amount, % of bankroll, or kelly multiplier)
        odds_source: 'B365' or 'Avg' or 'Max'
        """
        # Normalize odds_source (frontend sends lowercase like 'bet365')
        if odds_source:
            _os = odds_source.lower()
            if _os in ('b365', 'bet365'):
                odds_source = 'B365'
            elif _os in ('avg', 'average', 'market_average', 'market'):
                odds_source = 'Avg'
            elif _os in ('max', 'pinnacle', 'maximum'):
                odds_source = 'Max'

        # 1. Load data for all selected leagues
        all_matches = []
        for league_code in leagues:
            df = load_league_data(league_code, start_date='2020-08-01', data_source=data_source, api_key=futpython_api_key) # Load from 2020 to populate form
            if not df.empty:
                all_matches.append(df)
                
        if not all_matches:
            return {"error": "Nenhum dado encontrado para as ligas selecionadas."}
            
        # Combine all matches and sort chronologically
        combined_df = pd.concat(all_matches, ignore_index=True)
        combined_df = combined_df.sort_values(by=['Date', 'Time']).reset_index(drop=True)

        # Pre-compute league-average xG for fallback when match xG is missing
        _league_xg_fallback = {}
        for _lc in leagues:
            _ldf = combined_df[combined_df['LeagueCode'] == _lc]
            _hxg = _ldf['HomeXG'].dropna()
            _axg = _ldf['AwayXG'].dropna()
            _league_xg_fallback[_lc] = {
                'home': float(_hxg.mean()) if len(_hxg) > 10 else 1.45,
                'away': float(_axg.mean()) if len(_axg) > 10 else 1.15,
            }

        # 2. Setup state trackers for rolling form (Chronological O(M) simulation)
        # We track goals scored and conceded for home and away separately
        team_home_scored = defaultdict(list)
        team_home_conceded = defaultdict(list)
        team_away_scored = defaultdict(list)
        team_away_conceded = defaultdict(list)
        
        # Track HT goals
        team_home_scored_ht = defaultdict(list)
        team_home_conceded_ht = defaultdict(list)
        team_away_scored_ht = defaultdict(list)
        team_away_conceded_ht = defaultdict(list)
        league_home_goals_ht = defaultdict(list)
        league_away_goals_ht = defaultdict(list)
        
        # Track Shots on Target (SOT) for home and away separately
        team_home_sot = defaultdict(list)
        team_home_sot_conceded = defaultdict(list)
        team_away_sot = defaultdict(list)
        team_away_sot_conceded = defaultdict(list)
        
        # Track Expected Goals (xG)
        team_home_xg = defaultdict(list)
        team_home_xg_conceded = defaultdict(list)
        team_away_xg = defaultdict(list)
        team_away_xg_conceded = defaultdict(list)
        
        # Track league-wide goals and SOT
        team_home_xg = defaultdict(list)
        team_home_xg_conceded = defaultdict(list)
        team_away_xg = defaultdict(list)
        team_away_xg_conceded = defaultdict(list)
        
        league_home_goals = defaultdict(list)
        league_away_goals = defaultdict(list)
        league_home_sot = defaultdict(list)
        league_away_sot = defaultdict(list)
        league_home_xg = defaultdict(list)
        league_away_xg = defaultdict(list)
        league_home_xg = defaultdict(list)
        league_away_xg = defaultdict(list)

        # Corners tracking for corners model
        team_home_corners_for = defaultdict(list)
        team_home_corners_against = defaultdict(list)
        team_away_corners_for = defaultdict(list)
        team_away_corners_against = defaultdict(list)
        league_home_corners = defaultdict(list)
        league_away_corners = defaultdict(list)

        # Setup markets list
        markets_list = [market] if isinstance(market, str) else market

        # Backtest statistics
        bankroll = initial_bankroll
        peak_bankroll = initial_bankroll
        max_drawdown = 0.0
        
        # Parallel bankrolls for multigestão comparison
        bankroll_fixed = initial_bankroll
        bankroll_proportional = initial_bankroll
        bankroll_kelly = initial_bankroll
        
        equity_curve_fixed = [{'date': start_date, 'bankroll': round(initial_bankroll, 2)}]
        equity_curve_proportional = [{'date': start_date, 'bankroll': round(initial_bankroll, 2)}]
        equity_curve_kelly = [{'date': start_date, 'bankroll': round(initial_bankroll, 2)}]
        
        # Track statistics for each staking method to return alternative summaries
        peak_fixed = initial_bankroll
        max_dd_fixed = 0.0
        current_dd_duration_fixed = 0
        max_dd_duration_fixed = 0
        bets_fixed = 0
        wins_fixed = 0
        staked_fixed = 0.0
        
        peak_prop = initial_bankroll
        max_dd_prop = 0.0
        current_dd_duration_prop = 0
        max_dd_duration_prop = 0
        bets_prop = 0
        wins_prop = 0
        staked_prop = 0.0
        
        peak_kelly = initial_bankroll
        max_dd_kelly = 0.0
        current_dd_duration_kelly = 0
        max_dd_duration_kelly = 0
        bets_kelly = 0
        wins_kelly = 0
        staked_kelly = 0.0
        
        bets_record = []
        cumulative_profit = 0.0
        total_staked = 0.0
        
        # Date boundaries
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        oos_cutoff_dt = pd.to_datetime(oos_date_cutoff) if oos_date_cutoff else None
        models_frozen = False

        self.probability_pipeline = ProbabilityPipeline(model_type=model_type)
        elo_tracker = EloTracker(k_factor=ELO_K_FACTOR, home_advantage=ELO_HOME_ADVANTAGE)
        league_rho_cache = {}  # Cache rho per league
        league_goals_for_rho = defaultdict(lambda: {'h': [], 'a': [], 'lh': [], 'la': []})
        daily_exposure = defaultdict(float)  # Track daily total stake exposure
        daily_bet_count = defaultdict(int)  # Track number of bets per day
        daily_match_exposure = defaultdict(lambda: defaultdict(float))  # date -> match_key -> per-match stake
        daily_match_count = defaultdict(lambda: defaultdict(int))       # date -> match_key -> num bets
        daily_pnl = defaultdict(float)      # Track daily profit/loss for EWMA volatility
        all_daily_returns = []              # Sequential daily returns for regime detection
        prev_date = None                    # Track previous match date to detect day boundaries
        day_start_bankroll = initial_bankroll  # Bankroll at start of current day for return calc

        last_match_date = {}
        season_points = defaultdict(lambda: defaultdict(int))
        season_games = defaultdict(lambda: defaultdict(int))
        
        # 3. Chronological iteration
        # Exclusion tracking — makes selection bias visible
        matches_total_in_file = len(combined_df)
        # Extract seasons analyzed
        season_col = combined_df['Season'].dropna().unique() if 'Season' in combined_df.columns else []
        if len(season_col) == 1 and season_col[0] == 'All':
            seasons_sorted = [int(y) for y in sorted(combined_df['Date'].dt.year.unique())]
        else:
            seasons_sorted = sorted(set(str(s) for s in season_col if s != 'All'))
        seasons_analyzed = seasons_sorted if seasons_sorted else ['?']
        matches_skipped_unplayed = 0
        matches_skipped_no_1x2 = 0
        markets_evaluated_total = 0
        markets_skipped_nan = 0
        markets_skipped_ht_no_data = 0
        markets_skipped_filter = 0
        markets_skipped_ev = 0
        bets_placed = 0

        # Parametric slippage: base percentage (user override or default)
        if slippage is not None:
            slippage_base_pct = float(slippage)
        else:
            slippage_base_pct = 1.0 if odds_timing == 'closing' else 0.0

        for row in combined_df.to_dict('records'):
            match_date = row['Date']
            date_str_check = match_date.strftime('%Y-%m-%d')

            # Detect day boundary: compute daily return for previous day
            if prev_date is not None and date_str_check != prev_date:
                if day_start_bankroll > 0:
                    daily_ret = daily_pnl.get(prev_date, 0.0) / day_start_bankroll
                    all_daily_returns.append(daily_ret)
                day_start_bankroll = bankroll
                prev_date = date_str_check
            elif prev_date is None:
                prev_date = date_str_check

            league_code = row['LeagueCode']
            _decay = get_league_weighted_decay(league_code)
            home_team = row['HomeTeam']
            away_team = row['AwayTeam']
            fthg = row['FTHG']
            ftag = row['FTAG']
            ftr = row['FTR']

            # Skip matches that haven't been played yet (missing scores)
            if pd.isna(fthg) or pd.isna(ftag):
                matches_skipped_unplayed += 1
                continue
                
            # Precompute booleans once per row (avoids repeated string comparisons in bet evaluation)
            is_home_win = (ftr == 'H')
            is_away_win = (ftr == 'A')
            is_draw = (ftr == 'D')
            total_goals = int(fthg) + int(ftag)
            
            hthg = row.get('HTHG')
            htag = row.get('HTAG')
                
            # Warm up ratings only (skip heavy model calculations) if match is before backtest window
            hst = row.get('HST')
            ast = row.get('AST')
            hxg = row.get('HomeXG')
            axg = row.get('AwayXG')
            
            # xG Fallback: use SOT*0.33 first, then league-average xG (NOT actual goals)
            if pd.isna(hxg) or hxg == 0:
                hxg = (hst * 0.33) if (not pd.isna(hst) and hst > 0) else _league_xg_fallback.get(league_code, {}).get('home', 1.45)
            if pd.isna(axg) or axg == 0:
                axg = (ast * 0.33) if (not pd.isna(ast) and ast > 0) else _league_xg_fallback.get(league_code, {}).get('away', 1.15)
                
            # Calculate rest days (fatigue)
            current_dt = pd.to_datetime(match_date)
            home_last = last_match_date.get(home_team)
            away_last = last_match_date.get(away_team)
            rest_days_home = min(15, (current_dt - home_last).days) if home_last else 10
            rest_days_away = min(15, (current_dt - away_last).days) if away_last else 10
            
            # Save/update last match date
            last_match_date[home_team] = current_dt
            last_match_date[away_team] = current_dt
            
            # Calculate motivation/urgency based on standings
            season_key = (league_code, row.get('Season', 'All'))
            motivation_home = self._calculate_motivation(season_points[season_key], home_team, season_games[season_key])
            motivation_away = self._calculate_motivation(season_points[season_key], away_team, season_games[season_key])
            
            # Update points and games in standings (for future matches)
            if home_team not in season_points[season_key]:
                season_points[season_key][home_team] = 0
                season_games[season_key][home_team] = 0
            if away_team not in season_points[season_key]:
                season_points[season_key][away_team] = 0
                season_games[season_key][away_team] = 0
                
            season_games[season_key][home_team] += 1
            season_games[season_key][away_team] += 1
            
            if is_home_win:
                season_points[season_key][home_team] += 3
            elif is_away_win:
                season_points[season_key][away_team] += 3
            elif is_draw:
                season_points[season_key][home_team] += 1
                season_points[season_key][away_team] += 1
                
            if match_date < start_dt:
                self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                                  league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                                  team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                                  league_home_sot, league_away_sot, hst, ast,
                                  team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                                  league_home_xg, league_away_xg, hxg, axg,
                                  team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                                  league_home_goals_ht, league_away_goals_ht, hthg, htag)
                self._update_corners_form(team_home_corners_for, team_home_corners_against,
                                          team_away_corners_for, team_away_corners_against,
                                          league_home_corners, league_away_corners,
                                          league_code, home_team, away_team,
                                          row.get('HC'), row.get('AC'))
                continue
                
            # Map odds columns based on source and timing (Phase 3 Structural Fix)
            if odds_source == 'B365':
                if odds_timing == 'closing':
                    odds_h = row.get('B365CH', row.get('B365H'))
                    odds_d = row.get('B365CD', row.get('B365D'))
                    odds_a = row.get('B365CA', row.get('B365A'))
                    odds_over25 = row.get('B365C>2.5', row.get('B365>2.5'))
                    odds_under25 = row.get('B365C<2.5', row.get('B365<2.5'))
                else:
                    odds_h = row.get('B365H')
                    odds_d = row.get('B365D')
                    odds_a = row.get('B365A')
                    odds_over25 = row.get('B365>2.5')
                    odds_under25 = row.get('B365<2.5')
                
                odds_over05_ht = row.get('Over_HT_0_5', row.get('B365>0.5HT'))
                odds_under05_ht = row.get('Under_HT_0_5', row.get('B365<0.5HT'))
                odds_over15_ht = row.get('Over_HT_1_5', row.get('B365>1.5HT'))
                odds_under15_ht = row.get('Under_HT_1_5', row.get('B365<1.5HT'))
                
                # Extended FutPythonTrader odds
                odds_h_ht = row.get('Odd_1_HT')
                odds_d_ht = row.get('Odd_X_HT')
                odds_a_ht = row.get('Odd_2_HT')
                odds_btts_yes = row.get('BTTS_Yes')
                odds_btts_no = row.get('BTTS_No')
                odds_over15 = row.get('Over_FT_1_5')
                odds_under15 = row.get('Under_FT_1_5')
                odds_over35 = row.get('Over_FT_3_5')
                odds_under35 = row.get('Under_FT_3_5')
                odds_over45 = row.get('Over_FT_4_5')
                odds_under45 = row.get('Under_FT_4_5')
                # Real Double Chance odds from FutPythonTrader
                odds_dc_x2 = row.get('DC_X2')
                odds_dc_1x = row.get('DC_1X')
                odds_dc_12 = row.get('DC_12')
                odds_over05 = row.get('Over_FT_0_5')
                odds_under05 = row.get('Under_FT_0_5')
                odds_win_to_nil_h = row.get('odds_win_to_nil_1')
                odds_win_to_nil_a = row.get('odds_win_to_nil_2')
                
                # Corners
                odds_corners_h = row.get('odds_corners_1')
                odds_corners_d = row.get('odds_corners_x')
                odds_corners_a = row.get('odds_corners_2')
                odds_corners_over_75 = row.get('odds_corners_over_75')
                odds_corners_over_85 = row.get('odds_corners_over_85')
                odds_corners_over_95 = row.get('odds_corners_over_95')
                odds_corners_over_105 = row.get('odds_corners_over_105')
                odds_corners_over_115 = row.get('odds_corners_over_115')
                odds_corners_under_75 = row.get('odds_corners_under_75')
                odds_corners_under_85 = row.get('odds_corners_under_85')
                odds_corners_under_95 = row.get('odds_corners_under_95')
                odds_corners_under_105 = row.get('odds_corners_under_105')
                odds_corners_under_115 = row.get('odds_corners_under_115')
 
                # HT Goals extra
                odds_over25_ht = row.get('Over_HT_2_5')
                odds_under25_ht = row.get('Under_HT_2_5')
                odds_over35_ht = row.get('Over_HT_3_5')
                odds_under35_ht = row.get('Under_HT_3_5')
 
                # 2H Goals
                odds_over05_2h = row.get('Over_2H_0_5')
                odds_under05_2h = row.get('Under_2H_0_5')
                odds_over15_2h = row.get('Over_2H_1_5')
                odds_under15_2h = row.get('Under_2H_1_5')
                odds_over25_2h = row.get('Over_2H_2_5')
                odds_under25_2h = row.get('Under_2H_2_5')
                odds_over35_2h = row.get('Over_2H_3_5')
                odds_under35_2h = row.get('Under_2H_3_5')
 
                # 2H Result
                odds_h_2h = row.get('Odd_1_2H')
                odds_d_2h = row.get('Odd_X_2H')
                odds_a_2h = row.get('Odd_2_2H')
            elif odds_source == 'Avg':
                if odds_timing == 'closing':
                    odds_h = row.get('AvgCH', row.get('AvgH'))
                    odds_d = row.get('AvgCD', row.get('AvgD'))
                    odds_a = row.get('AvgCA', row.get('AvgA'))
                    odds_over25 = row.get('AvgC>2.5', row.get('Avg>2.5'))
                    odds_under25 = row.get('AvgC<2.5', row.get('Avg<2.5'))
                else:
                    odds_h = row.get('AvgH')
                    odds_d = row.get('AvgD')
                    odds_a = row.get('AvgA')
                    odds_over25 = row.get('Avg>2.5')
                    odds_under25 = row.get('Avg<2.5')
                odds_over05_ht = row.get('Over_HT_0_5', row.get('B365>0.5HT'))
                odds_under05_ht = row.get('Under_HT_0_5', row.get('B365<0.5HT'))
                odds_over15_ht = row.get('Over_HT_1_5', row.get('B365>1.5HT'))
                odds_under15_ht = row.get('Under_HT_1_5', row.get('B365<1.5HT'))
            else: # Max
                if odds_timing == 'closing':
                    odds_h = row.get('MaxCH', row.get('MaxH'))
                    odds_d = row.get('MaxCD', row.get('MaxD'))
                    odds_a = row.get('MaxCA', row.get('MaxA'))
                    odds_over25 = row.get('MaxC>2.5', row.get('Max>2.5'))
                    odds_under25 = row.get('MaxC<2.5', row.get('Max<2.5'))
                else:
                    odds_h = row.get('MaxH')
                    odds_d = row.get('MaxD')
                    odds_a = row.get('MaxA')
                    odds_over25 = row.get('Max>2.5')
                    odds_under25 = row.get('Max<2.5')

                odds_over05_ht = row.get('Over_HT_0_5', row.get('B365>0.5HT'))
                odds_under05_ht = row.get('Under_HT_0_5', row.get('B365<0.5HT'))
                odds_over15_ht = row.get('Over_HT_1_5', row.get('B365>1.5HT'))
                odds_under15_ht = row.get('Under_HT_1_5', row.get('B365<1.5HT'))

            # Pinnacle closing line odds for CLV calculation
            closing_odds_h = row.get('PSCH', row.get('PSH', row.get('MaxCH')))
            closing_odds_d = row.get('PSCD', row.get('PSD', row.get('MaxCD')))
            closing_odds_a = row.get('PSCA', row.get('PSA', row.get('MaxCA')))
            closing_odds_over25 = row.get('PC>2.5', row.get('MaxC>2.5'))
            closing_odds_under25 = row.get('PC<2.5', row.get('MaxC<2.5'))
            
            # Synthetic closing odds for DNB
            closing_odds_dnb_h = closing_odds_h * (closing_odds_d - 1.0) / closing_odds_d if (closing_odds_h and closing_odds_d and closing_odds_d > 1.0 and not pd.isna(closing_odds_h) and not pd.isna(closing_odds_d)) else np.nan
            closing_odds_dnb_a = closing_odds_a * (closing_odds_d - 1.0) / closing_odds_d if (closing_odds_a and closing_odds_d and closing_odds_d > 1.0 and not pd.isna(closing_odds_a) and not pd.isna(closing_odds_d)) else np.nan
            
            # Closing line for AH
            closing_line = row.get('AHCh', row.get('AHh'))
            if pd.isna(closing_line):
                closing_line = 0.0
            closing_odds_ah_h = row.get('PCAHH', row.get('AvgCAHH'))
            closing_odds_ah_a = row.get('PCAHA', row.get('AvgCAHA'))
            
            # Fallback for closing AH if they are NaN
            if pd.isna(closing_odds_ah_h) or pd.isna(closing_odds_ah_a):
                if closing_line == 0.0:
                    closing_odds_ah_h = closing_odds_dnb_h
                    closing_odds_ah_a = closing_odds_dnb_a
                elif closing_line == -0.5:
                    closing_odds_ah_h = closing_odds_h
                    closing_odds_ah_a = 1.0 / (1.0/closing_odds_d + 1.0/closing_odds_a) if (closing_odds_d and closing_odds_a and closing_odds_d > 1.0 and closing_odds_a > 1.0 and not pd.isna(closing_odds_d) and not pd.isna(closing_odds_a)) else np.nan
                elif closing_line == 0.5:
                    closing_odds_ah_h = 1.0 / (1.0/closing_odds_h + 1.0/closing_odds_d) if (closing_odds_h and closing_odds_d and closing_odds_h > 1.0 and closing_odds_d > 1.0 and not pd.isna(closing_odds_h) and not pd.isna(closing_odds_d)) else np.nan
                    closing_odds_ah_a = closing_odds_a
                else:
                    closing_odds_ah_h = np.nan
                    closing_odds_ah_a = np.nan
            # Shots and xG already fetched above
            
            # If standard odds are missing, we cannot proceed with this match
            if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
                matches_skipped_no_1x2 += 1
                # Still record the match result in team histories to keep form up-to-date!
                self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                                  league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                                  team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                                  league_home_sot, league_away_sot, hst, ast,
                                  team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                                  league_home_xg, league_away_xg, hxg, axg,
                                  team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                                  league_home_goals_ht, league_away_goals_ht, hthg, htag)
                self._update_corners_form(team_home_corners_for, team_home_corners_against,
                                          team_away_corners_for, team_away_corners_against,
                                          league_home_corners, league_away_corners,
                                          league_code, home_team, away_team,
                                          row.get("HC"), row.get("AC"))
                continue
                
            # Compute predictive probabilities via shared pipeline
            bundle = self._compute_match_probabilities(
                team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                league_home_goals, league_away_goals,
                team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                league_home_sot, league_away_sot,
                team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                league_home_xg, league_away_xg,
                team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht,
                team_away_conceded_ht, league_home_goals_ht, league_away_goals_ht,
                home_team, away_team, league_code, _decay,
                league_rho_cache, league_goals_for_rho, elo_tracker
            )
            # Unpack all downstream variables
            lambda_home = bundle['lambda_home']; lambda_away = bundle['lambda_away']
            lambda_goals_home = bundle['lambda_goals_home']; lambda_goals_away = bundle['lambda_goals_away']
            lambda_shots_home = bundle['lambda_shots_home']; lambda_shots_away = bundle['lambda_shots_away']
            lambda_xg_home = bundle['lambda_xg_home']; lambda_xg_away = bundle['lambda_xg_away']
            lambda_home_ht = bundle['lambda_home_ht']; lambda_away_ht = bundle['lambda_away_ht']
            h_att = bundle['h_att']; h_def = bundle['h_def']; a_att = bundle['a_att']; a_def = bundle['a_def']
            h_xg_att = bundle['h_xg_att']; h_xg_def = bundle['h_xg_def']; a_xg_att = bundle['a_xg_att']; a_xg_def = bundle['a_xg_def']
            elo_factor_h = bundle['elo_factor_h']; elo_factor_a = bundle['elo_factor_a']
            prob_matrix = bundle['prob_matrix']
            prob_h = bundle['prob_h']; prob_d = bundle['prob_d']; prob_a = bundle['prob_a']
            prob_over_25 = bundle['prob_over_25']; prob_over_15 = bundle['prob_over_15']
            prob_over_35 = bundle['prob_over_35']; prob_over_45 = bundle['prob_over_45']; prob_over_55 = bundle['prob_over_55']
            prob_btts_yes = bundle['prob_btts_yes']
            prob_matrix_ht = bundle['prob_matrix_ht']
            prob_h_ht = bundle['prob_h_ht']; prob_d_ht = bundle['prob_d_ht']; prob_a_ht = bundle['prob_a_ht']
            prob_over_05_ht = bundle['prob_over_05_ht']; prob_over_15_ht = bundle['prob_over_15_ht']
            rho = bundle['rho']
            avg_h_goals = bundle['avg_h_goals']; avg_a_goals = bundle['avg_a_goals']

            # Lazy loading of estimated odds from the solver
            est_odds = None

            # Compute corners probabilities using league-average rates (Poisson model)
            leg_h_corners = league_home_corners[league_code][-200:]
            leg_a_corners = league_away_corners[league_code][-200:]
            expected_home_corners = np.mean(leg_h_corners) if leg_h_corners else 5.5
            expected_away_corners = np.mean(leg_a_corners) if leg_a_corners else 4.5
            corners_probs = compute_corners_probs(expected_home_corners, expected_away_corners)

            # Evaluate each selected market for this match
            for mkt in markets_list:
                # Decide market to evaluate
                model_prob = 0.0
                bookie_odds = np.nan
                bet_won = False
                market_label = ""
                result_factor = -1.0
                is_synthetic = False
                ml_applied = False
                kelly_probs = None  # populated for multi-outcome markets (DNB, AH)
                kelly_outcomes = None

                if mkt.startswith('ht_') and (pd.isna(hthg) or pd.isna(htag)):
                    markets_skipped_ht_no_data += 1
                    continue

                if mkt in ('home', '1x2_home'):
                    model_prob = prob_h
                    bookie_odds = odds_h
                    bet_won = is_home_win
                    market_label = "1 (Mandante)"
                elif mkt in ('away', '1x2_away'):
                    model_prob = prob_a
                    bookie_odds = odds_a
                    bet_won = is_away_win
                    market_label = "2 (Visitante)"
                elif mkt in ('draw', '1x2_draw'):
                    model_prob = prob_d
                    bookie_odds = odds_d
                    bet_won = is_draw
                    market_label = "X (Empate)"
                elif mkt == 'over25':
                    model_prob = prob_over_25
                    bookie_odds = odds_over25
                    bet_won = (total_goals > 2)
                    market_label = "Over 2.5"
                elif mkt == 'under25':
                    model_prob = 1.0 - prob_over_25
                    bookie_odds = odds_under25
                    bet_won = (total_goals < 3)
                    market_label = "Under 2.5"
                elif mkt == 'ht_home':
                    if odds_h_ht is not None and not pd.isna(odds_h_ht) and odds_h_ht > 1.0: bookie_odds = odds_h_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_h_ht
                    bet_won = (hthg > htag)
                    market_label = "HT Home"
                elif mkt == 'ht_draw':
                    if odds_d_ht is not None and not pd.isna(odds_d_ht) and odds_d_ht > 1.0: bookie_odds = odds_d_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_d_ht
                    bet_won = (hthg == htag)
                    market_label = "HT Draw"
                elif mkt == 'ht_away':
                    if odds_a_ht is not None and not pd.isna(odds_a_ht) and odds_a_ht > 1.0: bookie_odds = odds_a_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_a_ht
                    bet_won = (hthg < htag)
                    market_label = "HT Away"
                elif mkt == 'ht_over05':
                    if odds_over05_ht is not None and not pd.isna(odds_over05_ht) and odds_over05_ht > 1.0:
                        bookie_odds = odds_over05_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_over_05_ht
                    bet_won = (hthg + htag > 0)
                    market_label = "HT Over 0.5"
                elif mkt == 'ht_under05':
                    if odds_under05_ht is not None and not pd.isna(odds_under05_ht) and odds_under05_ht > 1.0:
                        bookie_odds = odds_under05_ht
                    else: bookie_odds = np.nan
                    model_prob = 1.0 - prob_over_05_ht
                    bet_won = (hthg + htag == 0)
                    market_label = "HT Under 0.5"
                elif mkt == 'ht_over15':
                    if odds_over15_ht is not None and not pd.isna(odds_over15_ht) and odds_over15_ht > 1.0:
                        bookie_odds = odds_over15_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_over_15_ht
                    bet_won = (hthg + htag > 1)
                    market_label = "HT Over 1.5"
                elif mkt == 'ht_under15':
                    if odds_under15_ht is not None and not pd.isna(odds_under15_ht) and odds_under15_ht > 1.0:
                        bookie_odds = odds_under15_ht
                    else: bookie_odds = np.nan
                    model_prob = 1.0 - prob_over_15_ht
                    bet_won = (hthg + htag <= 1)
                    market_label = "HT Under 1.5"
                elif mkt == 'over15':
                    if odds_over15 is not None and not pd.isna(odds_over15) and odds_over15 > 1.0: bookie_odds = odds_over15
                    else:
                        if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                        bookie_odds = est_odds['bookie_over_15']
                        is_synthetic = True
                    model_prob = prob_over_15
                    bet_won = (total_goals > 1)
                    market_label = "Over 1.5"
                elif mkt == 'under15':
                    if odds_under15 is not None and not pd.isna(odds_under15) and odds_under15 > 1.0: bookie_odds = odds_under15
                    else:
                        if est_odds is None:
                            est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                        bookie_odds = est_odds['bookie_under_15']
                        is_synthetic = True
                    model_prob = 1.0 - prob_over_15
                    bet_won = (total_goals < 2)
                    market_label = "Under 1.5"
                elif mkt == 'over35':
                    if odds_over35 is not None and not pd.isna(odds_over35) and odds_over35 > 1.0: bookie_odds = odds_over35
                    else:
                        if est_odds is None:
                            est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                        bookie_odds = est_odds['bookie_over_35']
                        is_synthetic = True
                    model_prob = prob_over_35
                    bet_won = (total_goals > 3)
                    market_label = "Over 3.5"
                elif mkt == 'under35':
                    if odds_under35 is not None and not pd.isna(odds_under35) and odds_under35 > 1.0: bookie_odds = odds_under35
                    else:
                        if est_odds is None:
                            est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                        bookie_odds = est_odds['bookie_under_35']
                        is_synthetic = True
                    model_prob = 1.0 - prob_over_35
                    bet_won = (total_goals < 4)
                    market_label = "Under 3.5"
                elif mkt == 'over45':
                    model_prob = prob_over_45
                    try:
                        _o45 = float(str(odds_over45).replace(',', '.')) if odds_over45 is not None and not pd.isna(odds_over45) else np.nan
                        bookie_odds = _o45 if _o45 > 1.0 else (estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho) if est_odds is None else est_odds)['bookie_over_45']
                        if _o45 is None or pd.isna(_o45) or _o45 <= 1.0: is_synthetic = True
                    except Exception:
                        if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                        bookie_odds = est_odds['bookie_over_45']
                        is_synthetic = True
                    bet_won = (total_goals > 4)
                    market_label = "Over 4.5"
                elif mkt == 'under45':
                    model_prob = 1.0 - prob_over_45
                    try:
                        _u45 = float(str(odds_under45).replace(',', '.')) if odds_under45 is not None and not pd.isna(odds_under45) else np.nan
                        bookie_odds = _u45 if _u45 > 1.0 else (estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho) if est_odds is None else est_odds)['bookie_under_45']
                        if _u45 is None or pd.isna(_u45) or _u45 <= 1.0: is_synthetic = True
                    except Exception:
                        if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                        bookie_odds = est_odds['bookie_under_45']
                        is_synthetic = True
                    bet_won = (total_goals < 5)
                    market_label = "Under 4.5"
                elif mkt == 'over55':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                    model_prob = prob_over_55
                    bookie_odds = est_odds['bookie_over_55']
                    is_synthetic = True
                    bet_won = (total_goals > 5)
                    market_label = "Over 5.5"
                elif mkt == 'under55':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                    model_prob = 1.0 - prob_over_55
                    bookie_odds = est_odds['bookie_under_55']
                    is_synthetic = True
                    bet_won = (total_goals < 6)
                    market_label = "Under 5.5"
                elif mkt in ('lay_home', 'lay_home_ex'):
                    model_prob = prob_d + prob_a
                    try:
                        _dc = float(str(odds_dc_x2).replace(',', '.')) if odds_dc_x2 is not None and not pd.isna(odds_dc_x2) else np.nan
                        if pd.isna(_dc) or _dc <= 1.0:
                            _dc = 1.0 / (1.0/odds_d + 1.0/odds_a) if (odds_d > 1.0 and odds_a > 1.0) else np.nan
                        bookie_odds = _dc / (_dc - 1.0) if (_dc > 1.001) else np.nan
                    except Exception:
                        bookie_odds = np.nan
                    bet_won = not is_home_win
                    market_label = "Lay Mandante (X2)" if mkt.endswith('_ex') else "Contra Mandante (X2)"
                # lay_home / lay_home_ex, lay_away / lay_away_ex, lay_draw / lay_draw_ex
                # are identical market pairs (PT vs EN label). Merged to avoid duplicate bets.
                elif mkt in ('lay_away', 'lay_away_ex'):
                    model_prob = prob_h + prob_d
                    try:
                        _dc = float(str(odds_dc_1x).replace(',', '.')) if odds_dc_1x is not None and not pd.isna(odds_dc_1x) else np.nan
                        if pd.isna(_dc) or _dc <= 1.0:
                            _dc = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan
                        bookie_odds = _dc / (_dc - 1.0) if (_dc > 1.001) else np.nan
                    except Exception:
                        bookie_odds = np.nan
                    bet_won = not is_away_win
                    market_label = "Lay Visitante (1X)" if mkt.endswith('_ex') else "Contra Visitante (1X)"
                elif mkt in ('lay_draw', 'lay_draw_ex'):
                    model_prob = prob_h + prob_a
                    try:
                        _dc = float(str(odds_dc_12).replace(',', '.')) if odds_dc_12 is not None and not pd.isna(odds_dc_12) else np.nan
                        if pd.isna(_dc) or _dc <= 1.0:
                            _dc = 1.0 / (1.0/odds_h + 1.0/odds_a) if (odds_h > 1.0 and odds_a > 1.0) else np.nan
                        bookie_odds = _dc / (_dc - 1.0) if (_dc > 1.001) else np.nan
                    except Exception:
                        bookie_odds = np.nan
                    bet_won = not is_draw
                    market_label = "Lay Empate (12)" if mkt.endswith('_ex') else "Contra Empate (12)"
                elif mkt == 'btts_yes':
                    model_prob = prob_btts_yes
                    try:
                        parsed_odd = float(str(odds_btts_yes).replace(',', '.')) if odds_btts_yes is not None and not pd.isna(odds_btts_yes) else np.nan
                        bookie_odds = parsed_odd if parsed_odd > 1.0 else np.nan
                    except Exception:
                        bookie_odds = np.nan
                    bet_won = (fthg > 0 and ftag > 0)
                    market_label = "BTTS Sim"
                elif mkt == 'btts_no':
                    model_prob = 1.0 - prob_btts_yes
                    try:
                        parsed_odd = float(str(odds_btts_no).replace(',', '.')) if odds_btts_no is not None and not pd.isna(odds_btts_no) else np.nan
                        bookie_odds = parsed_odd if parsed_odd > 1.0 else np.nan
                    except Exception:
                        bookie_odds = np.nan
                    bet_won = (fthg == 0 or ftag == 0)
                    market_label = "BTTS Não"
                elif mkt.startswith('cs_'):
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                    def _get_cs_odd(api_col, fallback_key):
                        """Returns real bookmaker odd from API column, falling back to Poisson estimate."""
                        raw = row.get(api_col)
                        try:
                            v = float(str(raw).replace(',', '.')) if raw is not None and not pd.isna(raw) else np.nan
                            return v if v > 1.0 else est_odds[fallback_key]
                        except Exception:
                            return est_odds[fallback_key]
                    if mkt == 'cs_10':
                        model_prob = float(prob_matrix[1, 0])
                        bookie_odds = _get_cs_odd('CS_1_0', 'bookie_cs_10')
                        bet_won = (fthg == 1 and ftag == 0)
                        market_label = "Placar Exato 1-0"
                    elif mkt == 'cs_20':
                        model_prob = float(prob_matrix[2, 0])
                        bookie_odds = _get_cs_odd('CS_2_0', 'bookie_cs_20')
                        bet_won = (fthg == 2 and ftag == 0)
                        market_label = "Placar Exato 2-0"
                    elif mkt == 'cs_21':
                        model_prob = float(prob_matrix[2, 1])
                        bookie_odds = _get_cs_odd('CS_2_1', 'bookie_cs_21')
                        bet_won = (fthg == 2 and ftag == 1)
                        market_label = "Placar Exato 2-1"
                    elif mkt == 'cs_00':
                        model_prob = float(prob_matrix[0, 0])
                        bookie_odds = _get_cs_odd('CS_0_0', 'bookie_cs_00')
                        bet_won = (fthg == 0 and ftag == 0)
                        market_label = "Placar Exato 0-0"
                    elif mkt == 'cs_11':
                        model_prob = float(prob_matrix[1, 1])
                        bookie_odds = _get_cs_odd('CS_1_1', 'bookie_cs_11')
                        bet_won = (fthg == 1 and ftag == 1)
                        market_label = "Placar Exato 1-1"
                    elif mkt == 'cs_01':
                        model_prob = float(prob_matrix[0, 1])
                        bookie_odds = _get_cs_odd('CS_0_1', 'bookie_cs_01')
                        bet_won = (fthg == 0 and ftag == 1)
                        market_label = "Placar Exato 0-1"
                    elif mkt == 'cs_02':
                        model_prob = float(prob_matrix[0, 2])
                        bookie_odds = _get_cs_odd('CS_0_2', 'bookie_cs_02')
                        bet_won = (fthg == 0 and ftag == 2)
                        market_label = "Placar Exato 0-2"
                    elif mkt == 'cs_12':
                        model_prob = float(prob_matrix[1, 2])
                        bookie_odds = _get_cs_odd('CS_1_2', 'bookie_cs_12')
                        bet_won = (fthg == 1 and ftag == 2)
                        market_label = "Placar Exato 1-2"
                    elif mkt.startswith('lay_cs_'):
                        if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                        cs_code = mkt.replace('lay_', '')
                        
                        if cs_code == 'cs_10':
                            back_prob = float(prob_matrix[1, 0])
                            back_odds = est_odds['bookie_cs_10']
                            is_cs = (fthg == 1 and ftag == 0)
                            market_label = "Lay Placar Exato 1-0"
                        elif cs_code == 'cs_20':
                            back_prob = float(prob_matrix[2, 0])
                            back_odds = est_odds['bookie_cs_20']
                            is_cs = (fthg == 2 and ftag == 0)
                            market_label = "Lay Placar Exato 2-0"
                        elif cs_code == 'cs_21':
                            back_prob = float(prob_matrix[2, 1])
                            back_odds = est_odds['bookie_cs_21']
                            is_cs = (fthg == 2 and ftag == 1)
                            market_label = "Lay Placar Exato 2-1"
                        elif cs_code == 'cs_00':
                            back_prob = float(prob_matrix[0, 0])
                            back_odds = est_odds['bookie_cs_00']
                            is_cs = (fthg == 0 and ftag == 0)
                            market_label = "Lay Placar Exato 0-0"
                        elif cs_code == 'cs_11':
                            back_prob = float(prob_matrix[1, 1])
                            back_odds = est_odds['bookie_cs_11']
                            is_cs = (fthg == 1 and ftag == 1)
                            market_label = "Lay Placar Exato 1-1"
                        elif cs_code == 'cs_01':
                            back_prob = float(prob_matrix[0, 1])
                            back_odds = est_odds['bookie_cs_01']
                            is_cs = (fthg == 0 and ftag == 1)
                            market_label = "Lay Placar Exato 0-1"
                        elif cs_code == 'cs_02':
                            back_prob = float(prob_matrix[0, 2])
                            back_odds = est_odds['bookie_cs_02']
                            is_cs = (fthg == 0 and ftag == 2)
                            market_label = "Lay Placar Exato 0-2"
                        elif cs_code == 'cs_12':
                            back_prob = float(prob_matrix[1, 2])
                            back_odds = est_odds['bookie_cs_12']
                            is_cs = (fthg == 1 and ftag == 2)
                            market_label = "Lay Placar Exato 1-2"
                        
                        model_prob = 1.0 - back_prob
                        bookie_odds = 1.0 / (1.0 - 1.0/back_odds) if (back_odds > 1.0001) else np.nan
                        bet_won = not is_cs
                    elif mkt == 'dnb_h':
                        model_prob = prob_h / (prob_h + prob_a) if (prob_h + prob_a) > 0 else 0.5
                        try:
                            _dnb_h = float(str(row.get('DNB_1')).replace(',', '.')) if row.get('DNB_1') is not None and not pd.isna(row.get('DNB_1')) else np.nan
                            odds_dnb_h_real = _dnb_h if _dnb_h > 1.0 else np.nan
                        except Exception:
                            odds_dnb_h_real = np.nan
                        odds_dnb_h_synth = odds_h * (odds_d - 1.0) / odds_d if (odds_h and odds_d and odds_d > 1.0) else np.nan
                        bookie_odds = odds_dnb_h_real if not pd.isna(odds_dnb_h_real) else odds_dnb_h_synth
                        
                        kelly_probs = [prob_h, prob_d, prob_a]
                        kelly_outcomes = [bookie_odds - 1.0, 0.0, -1.0] if not pd.isna(bookie_odds) else [0.0, 0.0, 0.0]
                        
                        if is_home_win:
                            result_factor = 1.0
                            bet_won = True
                        elif is_draw:
                            result_factor = 0.0
                            bet_won = False
                        else:
                            result_factor = -1.0
                            bet_won = False
                        market_label = "DNB Mandante"
                        
                    elif mkt == 'dnb_a':
                        model_prob = prob_a / (prob_h + prob_a) if (prob_h + prob_a) > 0 else 0.5
                        try:
                            _dnb_a = float(str(row.get('DNB_2')).replace(',', '.')) if row.get('DNB_2') is not None and not pd.isna(row.get('DNB_2')) else np.nan
                            odds_dnb_a_real = _dnb_a if _dnb_a > 1.0 else np.nan
                        except Exception:
                            odds_dnb_a_real = np.nan
                        odds_dnb_a_synth = odds_a * (odds_d - 1.0) / odds_d if (odds_a and odds_d and odds_d > 1.0) else np.nan
                        bookie_odds = odds_dnb_a_real if not pd.isna(odds_dnb_a_real) else odds_dnb_a_synth
                        
                        kelly_probs = [prob_a, prob_d, prob_h]
                        kelly_outcomes = [bookie_odds - 1.0, 0.0, -1.0] if not pd.isna(bookie_odds) else [0.0, 0.0, 0.0]
                        
                        if is_away_win:
                            result_factor = 1.0
                            bet_won = True
                        elif is_draw:
                            result_factor = 0.0
                            bet_won = False
                        else:
                            result_factor = -1.0
                            bet_won = False
                        market_label = "DNB Visitante"
                        
                    elif mkt == 'ah_home':
                        line = row.get('AHh')
                        if pd.isna(line):
                            line = 0.0
                        if odds_source == 'B365':
                            odds_ah_h = row.get('B365AHH')
                            odds_ah_a = row.get('B365AHA')
                            if pd.isna(odds_ah_h) or odds_ah_h <= 1.0:
                                odds_ah_h = get_futpython_ah_odd(row, line, "Home")
                            if pd.isna(odds_ah_a) or odds_ah_a <= 1.0:
                                odds_ah_a = get_futpython_ah_odd(row, -line, "Away")
                        elif odds_source == 'Avg':
                            odds_ah_h = row.get('AvgAHH')
                            odds_ah_a = row.get('AvgAHA')
                        else:
                            odds_ah_h = row.get('MaxAHH')
                            odds_ah_a = row.get('MaxAHA')
                            
                        if pd.isna(odds_ah_h) or pd.isna(odds_ah_a) or odds_ah_h <= 1.0:
                            if line == 0.0:
                                odds_ah_h = odds_h * (odds_d - 1.0) / odds_d if (odds_h and odds_d and odds_d > 1.0) else np.nan
                            elif line == -0.5:
                                odds_ah_h = odds_h
                            elif line == 0.5:
                                odds_ah_h = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h and odds_d and odds_h > 1.0 and odds_d > 1.0) else np.nan
                            else:
                                ah_probs_h = calculate_ah_probabilities(prob_matrix, line)
                                odds_ah_h = get_fair_ah_odds(ah_probs_h) / 1.05
                        bookie_odds = odds_ah_h
                        
                        ah_probs = calculate_ah_probabilities(prob_matrix, line)
                        expected_return_factor = (ah_probs['win'] * bookie_odds + 
                                                  ah_probs['half_win'] * (bookie_odds + 1.0) / 2.0 + 
                                                  ah_probs['push'] * 1.0 + 
                                                  ah_probs['half_loss'] * 0.5) if not pd.isna(bookie_odds) else 0.0
                        model_prob = expected_return_factor / bookie_odds if (not pd.isna(bookie_odds) and bookie_odds > 0.0) else 0.0
                        
                        kelly_probs = [ah_probs['win'], ah_probs['half_win'], ah_probs['push'], ah_probs['half_loss'], ah_probs['loss']]
                        kelly_outcomes = [bookie_odds - 1.0, (bookie_odds - 1.0) / 2.0, 0.0, -0.5, -1.0] if not pd.isna(bookie_odds) else [0.0, 0.0, 0.0, 0.0, 0.0]
                        
                        margin = float(fthg - ftag)
                        score = margin + line
                        score = round(score * 4) / 4
                        
                        if score >= 0.5:
                            result_factor = 1.0
                            bet_won = True
                        elif score == 0.25:
                            result_factor = 0.5
                            bet_won = True
                        elif score == 0.0:
                            result_factor = 0.0
                            bet_won = False
                        elif score == -0.25:
                            result_factor = -0.5
                            bet_won = False
                        else:
                            result_factor = -1.0
                            bet_won = False
                        market_label = f"AH Mandante ({'+' if line > 0 else ''}{line})"
                        
                    elif mkt == 'ah_away':
                        home_line = row.get('AHh')
                        if pd.isna(home_line):
                            line = 0.0
                        else:
                            line = -home_line
                        if odds_source == 'B365':
                            odds_ah_h = row.get('B365AHH')
                            odds_ah_a = row.get('B365AHA')
                            if pd.isna(odds_ah_h) or odds_ah_h <= 1.0:
                                odds_ah_h = get_futpython_ah_odd(row, -line, "Home")
                            if pd.isna(odds_ah_a) or odds_ah_a <= 1.0:
                                odds_ah_a = get_futpython_ah_odd(row, line, "Away")
                        elif odds_source == 'Avg':
                            odds_ah_h = row.get('AvgAHH')
                            odds_ah_a = row.get('AvgAHA')
                        else:
                            odds_ah_h = row.get('MaxAHH')
                            odds_ah_a = row.get('MaxAHA')
                            
                        if pd.isna(odds_ah_h) or pd.isna(odds_ah_a) or odds_ah_a <= 1.0:
                            if line == 0.0:
                                odds_ah_a = odds_a * (odds_d - 1.0) / odds_d if (odds_a and odds_d and odds_d > 1.0) else np.nan
                            elif line == -0.5:
                                odds_ah_a = odds_a
                            elif line == 0.5:
                                odds_ah_a = 1.0 / (1.0/odds_a + 1.0/odds_d) if (odds_a and odds_d and odds_a > 1.0 and odds_d > 1.0) else np.nan
                            else:
                                ah_probs_a = calculate_ah_probabilities(prob_matrix, line)
                                odds_ah_a = get_fair_ah_odds(ah_probs_a) / 1.05
                        bookie_odds = odds_ah_a
                        
                        ah_probs = calculate_ah_probabilities(prob_matrix, line)
                        expected_return_factor = (ah_probs['win'] * bookie_odds + 
                                                  ah_probs['half_win'] * (bookie_odds + 1.0) / 2.0 + 
                                                  ah_probs['push'] * 1.0 + 
                                                  ah_probs['half_loss'] * 0.5) if not pd.isna(bookie_odds) else 0.0
                        model_prob = expected_return_factor / bookie_odds if (not pd.isna(bookie_odds) and bookie_odds > 0.0) else 0.0
                        
                        kelly_probs = [ah_probs['win'], ah_probs['half_win'], ah_probs['push'], ah_probs['half_loss'], ah_probs['loss']]
                        kelly_outcomes = [bookie_odds - 1.0, (bookie_odds - 1.0) / 2.0, 0.0, -0.5, -1.0] if not pd.isna(bookie_odds) else [0.0, 0.0, 0.0, 0.0, 0.0]
                        
                        margin = float(ftag - fthg)
                        score = margin + line
                        score = round(score * 4) / 4
                        
                        if score >= 0.5:
                            result_factor = 1.0
                            bet_won = True
                        elif score == 0.25:
                            result_factor = 0.5
                            bet_won = True
                        elif score == 0.0:
                            result_factor = 0.0
                            bet_won = False
                        elif score == -0.25:
                            result_factor = -0.5
                            bet_won = False
                        else:
                            result_factor = -1.0
                            bet_won = False
                        market_label = f"AH Visitante ({'+' if line > 0 else ''}{line})"
                    elif mkt == 'win_to_nil_home':
                        bookie_odds = odds_win_to_nil_h
                        model_prob = sum(float(prob_matrix[i, 0]) for i in range(1, min(6, max_goals + 1)))
                        bet_won = (fthg > ftag and ftag == 0)
                        market_label = "Vitória sem sofrer gols Casa"
                    elif mkt == 'win_to_nil_away':
                        bookie_odds = odds_win_to_nil_a
                        model_prob = sum(float(prob_matrix[0, j]) for j in range(1, min(6, max_goals + 1)))
                        bet_won = (ftag > fthg and fthg == 0)
                        market_label = "Vitória sem sofrer gols Fora"
                    elif mkt == 'corners_1':
                        bookie_odds = odds_corners_h
                        model_prob = corners_probs['corners_1']
                        bet_won = (row.get('HC', 0) > row.get('AC', 0)) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                        market_label = "Mais Cantos Casa"
                    elif mkt == 'corners_x':
                        bookie_odds = odds_corners_d
                        model_prob = corners_probs['corners_x']
                        bet_won = (row.get('HC', 0) == row.get('AC', 0)) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                        market_label = "Mais Cantos Empate"
                    elif mkt == 'corners_2':
                        bookie_odds = odds_corners_a
                        model_prob = corners_probs['corners_2']
                        bet_won = (row.get('HC', 0) < row.get('AC', 0)) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                        market_label = "Mais Cantos Fora"
                    elif mkt.startswith('corners_over_'):
                        line = float(mkt.replace('corners_over_', '')) / 10.0
                        line_str = mkt.replace('corners_over_', '')
                        bookie_odds = row.get(f'odds_corners_over_{line_str}')
                        model_prob = corners_probs['corners_over'](line)
                        bet_won = (row.get('HC', 0) + row.get('AC', 0) > line) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                        market_label = f"Escanteios Over {line}"
                    elif mkt.startswith('corners_under_'):
                        line = float(mkt.replace('corners_under_', '')) / 10.0
                        line_str = mkt.replace('corners_under_', '')
                        bookie_odds = row.get(f'odds_corners_under_{line_str}')
                        model_prob = corners_probs['corners_under'](line)
                        bet_won = (row.get('HC', 0) + row.get('AC', 0) < line) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                        market_label = f"Escanteios Under {line}"
                    elif mkt in ('sh_home', 'sh_draw', 'sh_away') or mkt.startswith('sh_over_') or mkt.startswith('sh_under_'):
                        lambda_h_2h = lambda_home * 0.55
                        lambda_a_2h = lambda_away * 0.55
                        home_probs_2h = [math.exp(-lambda_h_2h) * (lambda_h_2h**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
                        away_probs_2h = [math.exp(-lambda_a_2h) * (lambda_a_2h**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
                        prob_matrix_2h = np.outer(home_probs_2h, away_probs_2h)
                        tau_00_2h = 1.0 - lambda_h_2h * lambda_a_2h * rho
                        tau_10_2h = 1.0 + lambda_a_2h * rho
                        tau_01_2h = 1.0 + lambda_h_2h * rho
                        tau_11_2h = 1.0 - rho
                        prob_matrix_2h[0, 0] *= max(0.0, tau_00_2h)
                        prob_matrix_2h[1, 0] *= max(0.0, tau_10_2h)
                        prob_matrix_2h[0, 1] *= max(0.0, tau_01_2h)
                        prob_matrix_2h[1, 1] *= max(0.0, tau_11_2h)
                        matrix_sum_2h = np.sum(prob_matrix_2h)
                        if matrix_sum_2h > 0:
                            prob_matrix_2h = prob_matrix_2h / matrix_sum_2h
                            
                        if mkt == 'sh_home':
                            bookie_odds = odds_h_2h
                            model_prob = float(np.sum(np.tril(prob_matrix_2h, -1)))
                            bet_won = (fthg - hthg > ftag - htag)
                            market_label = "2H Mandante"
                        elif mkt == 'sh_draw':
                            bookie_odds = odds_d_2h
                            model_prob = float(np.sum(np.diag(prob_matrix_2h)))
                            bet_won = (fthg - hthg == ftag - htag)
                            market_label = "2H Empate"
                        elif mkt == 'sh_away':
                            bookie_odds = odds_a_2h
                            model_prob = float(np.sum(np.triu(prob_matrix_2h, 1)))
                            bet_won = (fthg - hthg < ftag - htag)
                            market_label = "2H Visitante"
                        elif mkt.startswith('sh_over_'):
                            line = float(mkt.replace('sh_over_', '')) / 10.0
                            line_str = mkt.replace('sh_over_', '')
                            bookie_odds = row.get(f'Over_2H_{line_str[0]}_{line_str[1]}')
                            model_prob = sum(prob_matrix_2h[x, y] for x in range(max_goals + 1) for y in range(max_goals + 1) if x + y > line)
                            bet_won = ((fthg - hthg) + (ftag - htag) > line)
                            market_label = f"2H Over {line}"
                        elif mkt.startswith('sh_under_'):
                            line = float(mkt.replace('sh_under_', '')) / 10.0
                            line_str = mkt.replace('sh_under_', '')
                            bookie_odds = row.get(f'Under_2H_{line_str[0]}_{line_str[1]}')
                            model_prob = sum(prob_matrix_2h[x, y] for x in range(max_goals + 1) for y in range(max_goals + 1) if x + y < line)
                            bet_won = ((fthg - hthg) + (ftag - htag) < line)
                            market_label = f"2H Under {line}"
                    elif mkt.startswith('ht_over') and mkt not in ('ht_over05', 'ht_over15'):
                        line = float(mkt.replace('ht_over', '')) / 10.0
                        line_str = mkt.replace('ht_over', '')
                        bookie_odds = row.get(f'Over_HT_{line_str[0]}_{line_str[1]}')
                        model_prob = sum(prob_matrix_ht[x, y] for x in range(max_goals + 1) for y in range(max_goals + 1) if x + y > line)
                        bet_won = (hthg + htag > line)
                        market_label = f"HT Over {line}"
                    elif mkt.startswith('ht_under') and mkt not in ('ht_under05', 'ht_under15'):
                        line = float(mkt.replace('ht_under', '')) / 10.0
                        line_str = mkt.replace('ht_under', '')
                        bookie_odds = row.get(f'Under_HT_{line_str[0]}_{line_str[1]}')
                        model_prob = sum(prob_matrix_ht[x, y] for x in range(max_goals + 1) for y in range(max_goals + 1) if x + y < line)
                        bet_won = (hthg + htag < line)
                        market_label = f"HT Under {line}"

                if mkt not in ('dnb_h', 'dnb_a', 'ah_home', 'ah_away'):
                    result_factor = 1.0 if bet_won else -1.0

                # Determine if odds were synthetic (Phase 2: per-market detection)
                # est_odds is not None check REMOVED — was too broad (tainted all markets in match)
                if mkt.startswith('lay_cs_'):
                    is_synthetic = True
                elif mkt == 'dnb_h' and ('odds_dnb_h_real' in locals() and pd.isna(odds_dnb_h_real)):
                    is_synthetic = True
                elif mkt == 'dnb_a' and ('odds_dnb_a_real' in locals() and pd.isna(odds_dnb_a_real)):
                    is_synthetic = True
                elif mkt == 'ah_home' and ('odds_ah_h' in locals() and (pd.isna(odds_ah_h) or odds_ah_h <= 1.0)):
                    is_synthetic = True
                elif mkt == 'ah_away' and ('odds_ah_a' in locals() and (pd.isna(odds_ah_a) or odds_ah_a <= 1.0)):
                    is_synthetic = True
                elif mkt in ('lay_home', 'lay_home_ex', 'lay_away', 'lay_away_ex', 'lay_draw', 'lay_draw_ex'):
                    if mkt.startswith('lay_home'):
                        dc_col = 'DC_X2'
                        fallback_ok = (odds_d > 1.0 and odds_a > 1.0)
                    elif mkt.startswith('lay_away'):
                        dc_col = 'DC_1X'
                        fallback_ok = (odds_h > 1.0 and odds_d > 1.0)
                    else:
                        dc_col = 'DC_12'
                        fallback_ok = (odds_h > 1.0 and odds_a > 1.0)
                    _dc_val = row.get(dc_col)
                    if (pd.isna(_dc_val) or float(str(_dc_val).replace(',', '.')) <= 1.0) and not fallback_ok:
                        is_synthetic = True
                elif mkt.startswith('cs_'):
                    api_col_map = {
                        'cs_10': 'CS_1_0', 'cs_20': 'CS_2_0', 'cs_21': 'CS_2_1',
                        'cs_00': 'CS_0_0', 'cs_11': 'CS_1_1', 'cs_01': 'CS_0_1',
                        'cs_02': 'CS_0_2', 'cs_12': 'CS_1_2'
                    }
                    col = api_col_map.get(mkt)
                    if col and (col not in row or pd.isna(row[col]) or float(str(row[col]).replace(',', '.')) <= 1.0):
                        is_synthetic = True

                model_prob = float(model_prob)
                
                # Assemble ML Features
                elo_diff = float(elo_factor_h - elo_factor_a)
                features = [
                    float(lambda_home), float(lambda_away),
                    float(h_att), float(h_def), float(a_att), float(a_def),
                    elo_diff, model_prob,
                    float(h_xg_att), float(h_xg_def), float(a_xg_att), float(a_xg_def),
                    float(rest_days_home), float(rest_days_away),
                    float(motivation_home), float(motivation_away)
                ]
                
                # 1. Ensemble Blending (Stacking or fallback 50/50)
                poisson_prob = model_prob  # saved for stacking history
                ml_prob = None
                if use_ml and mkt in self.ml_ensembles and self.ml_ensembles[mkt].is_fitted:
                    ml_prob = self.ml_ensembles[mkt].predict_proba(features)
                    if ml_prob is not None:
                        if mkt in self.stacking_learners and self.stacking_learners[mkt].fitted:
                            model_prob = self.stacking_learners[mkt].predict(poisson_prob, ml_prob)
                        else:
                            model_prob = (poisson_prob + ml_prob) / 2.0
                        ml_applied = True
                        
                raw_prob = model_prob

                # 2. Apply Platt Calibration
                if mkt in self.calibrators:
                    model_prob = self.calibrators[mkt].calibrate(model_prob)
                    
                # 3. Store ML history (features are pre-game, no leak)
                if use_ml:
                    self.ml_history[mkt]['X'].append(features)
                    self.ml_history[mkt]['y'].append(1 if bet_won else 0)

                # NOTE: calibration_history is appended AFTER betting evaluation
                # to prevent temporal leak (outcome must not train Platt before
                # the calibrator is used to make a bet decision on this match).

                # If match date is within our backtest active window, evaluate betting
                if start_dt <= match_date <= end_dt:
                    markets_evaluated_total += 1

                    is_filtered = False
                    if pd.isna(bookie_odds) or bookie_odds <= 1.0:
                        markets_skipped_nan += 1
                    else:
                        is_filtered = (
                            (min_odds_h is not None and not pd.isna(odds_h) and odds_h < min_odds_h) or
                            (max_odds_h is not None and not pd.isna(odds_h) and odds_h > max_odds_h) or
                            (min_odds_d is not None and not pd.isna(odds_d) and odds_d < min_odds_d) or
                            (max_odds_d is not None and not pd.isna(odds_d) and odds_d > max_odds_d) or
                            (min_odds_a is not None and not pd.isna(odds_a) and odds_a < min_odds_a) or
                            (max_odds_a is not None and not pd.isna(odds_a) and odds_a > max_odds_a) or
                            (min_odds_over25 is not None and not pd.isna(odds_over25) and odds_over25 < min_odds_over25) or
                            (max_odds_over25 is not None and not pd.isna(odds_over25) and odds_over25 > max_odds_over25) or
                            (min_odds_under25 is not None and not pd.isna(odds_under25) and odds_under25 < min_odds_under25) or
                            (max_odds_under25 is not None and not pd.isna(odds_under25) and odds_under25 > max_odds_under25) or
                            (bookie_odds < min_odds or bookie_odds > max_odds)
                        )
                        if is_filtered:
                            markets_skipped_filter += 1

                    # We can place a bet if odds are valid and we have a "+EV" (positive expected value) edge
                    if not pd.isna(bookie_odds) and bookie_odds > 1.0:
                        # Cross-market odds filtering
                        if min_odds_h is not None and not pd.isna(odds_h) and odds_h < min_odds_h: continue
                        if max_odds_h is not None and not pd.isna(odds_h) and odds_h > max_odds_h: continue
                        if min_odds_d is not None and not pd.isna(odds_d) and odds_d < min_odds_d: continue
                        if max_odds_d is not None and not pd.isna(odds_d) and odds_d > max_odds_d: continue
                        if min_odds_a is not None and not pd.isna(odds_a) and odds_a < min_odds_a: continue
                        if max_odds_a is not None and not pd.isna(odds_a) and odds_a > max_odds_a: continue
                        if min_odds_over25 is not None and not pd.isna(odds_over25) and odds_over25 < min_odds_over25: continue
                        if max_odds_over25 is not None and not pd.isna(odds_over25) and odds_over25 > max_odds_over25: continue
                        if min_odds_under25 is not None and not pd.isna(odds_under25) and odds_under25 < min_odds_under25: continue
                        if max_odds_under25 is not None and not pd.isna(odds_under25) and odds_under25 > max_odds_under25: continue

                        # Filter by odds range
                        if bookie_odds < min_odds or bookie_odds > max_odds:
                            continue

                        # Apply parametric slippage (varies by odds, market liquidity, and league)
                        effective_odds = bookie_odds * compute_slippage_factor(bookie_odds, mkt, slippage_base_pct, league_code)
                        expected_value = model_prob * effective_odds

                        if expected_value >= value_threshold:
                            # Intra-day correlation: distinguish same-match vs different-match
                            match_key = f"{home_team}|{away_team}"

                            # Track distinct matches bet today
                            daily_match_count[date_str_check][match_key] += 1
                            n_matches_today = len(daily_match_count[date_str_check])

                            # Determine bet size (Staking)
                            if staking_rule == 'fixed':
                                stake = stake_value
                            elif staking_rule == 'proportional':
                                # e.g., 2% of current bankroll
                                stake = bankroll * (stake_value / 100.0)
                            elif staking_rule == 'kelly':
                                mult_k = stake_value

                                # Dynamic Kelly: smooth adjustment based on EWMA vol vs target
                                if all_daily_returns:
                                    mult_k = compute_dynamic_kelly_fraction(mult_k, all_daily_returns)

                                if effective_odds > 1.0:
                                    if kelly_probs is not None and kelly_outcomes is not None and len(kelly_probs) > 1:
                                        f_star = solve_kelly_multi(kelly_probs, kelly_outcomes, max_f=0.20)
                                    elif mkt.startswith('lay_'):
                                        f_star = model_prob / (effective_odds - 1.0) - (1.0 - model_prob)
                                    else:
                                        f_star = (model_prob * effective_odds - 1.0) / (effective_odds - 1.0)
                                    f_star = max(0.0, f_star)
                                    stake = bankroll * f_star * mult_k
                                    # Edge-scaled cap
                                    cap_pct = compute_edge_scaled_cap(model_prob, effective_odds, mkt)
                                    stake = min(stake, bankroll * cap_pct / 100.0)
                                    # Liquidity cap (league + market)
                                    liq_cap_pct = get_liquidity_max_stake(league_code, mkt, base_stake_pct=5.0)
                                    stake = min(stake, bankroll * liq_cap_pct / 100.0)
                                else:
                                    stake = 0.0
                            else:
                                stake = 0.0

                            # Apply intra-day correlation correction (only for Kelly/Proportional)
                            if staking_rule != 'fixed':
                                # Layer 1: Cross-match diversification (sqrt across distinct matches)
                                if n_matches_today > 1:
                                    stake = stake / math.sqrt(n_matches_today)

                                # Layer 2: Same-match correlation (cap total exposure per match at 5%)
                                match_exposure = daily_match_exposure[date_str_check][match_key] + stake
                                if match_exposure > bankroll * 0.05:
                                    stake = max(0, bankroll * 0.05 - daily_match_exposure[date_str_check][match_key])
                                daily_match_exposure[date_str_check][match_key] += stake

                                # Layer 3: Cap daily exposure at 10% of bankroll
                                if daily_exposure[date_str_check] + stake > bankroll * 0.10:
                                    stake = max(0, bankroll * 0.10 - daily_exposure[date_str_check])

                            # Apply drawdown circuit breaker (all staking rules)
                            dd_mult = compute_drawdown_multiplier(bankroll, peak_bankroll)
                            if dd_mult < 1.0:
                                stake = stake * dd_mult

                            # Avoid placing bet if stake is tiny or we have no bankroll left
                            if stake > 0.01 and bankroll >= stake:
                                bets_placed += 1
                                total_staked += stake

                                if mkt in ('dnb_h', 'dnb_a', 'ah_home', 'ah_away'):
                                    # result_factor: 1.0=win, 0.5=half_win, 0.0=push, -0.5=half_loss, -1.0=loss
                                    if result_factor > 0:
                                        profit = stake * (effective_odds - 1.0) * result_factor
                                    elif result_factor < 0:
                                        profit = stake * result_factor
                                    else:
                                        profit = 0.0
                                    bankroll += profit
                                elif bet_won:
                                    if mkt.startswith('lay_'):
                                        profit = stake
                                        if exchange_commission > 0:
                                            profit = profit * (1 - exchange_commission / 100)
                                    else:
                                        profit = stake * (effective_odds - 1.0)
                                    bankroll += profit
                                else:
                                    if mkt.startswith('lay_'):
                                        profit = -stake * (effective_odds - 1.0)
                                    else:
                                        profit = -stake
                                    bankroll += profit

                                cumulative_profit += profit
                                daily_exposure[date_str_check] += stake
                                daily_pnl[date_str_check] += profit

                                # Max Drawdown calculation
                                if bankroll > peak_bankroll:
                                    peak_bankroll = bankroll
                                dd = (peak_bankroll - bankroll) / peak_bankroll
                                if dd > max_drawdown:
                                    max_drawdown = dd

                                # --- Parallel Bankroll Simulations ---
                                date_str = match_date.strftime('%Y-%m-%d')

                                # 1. Fixed Stake Simulation ($10 or the active stake value if it is fixed)
                                st_fixed = stake_value if staking_rule == 'fixed' else 10.0
                                if bankroll_fixed >= st_fixed and st_fixed > 0.01:
                                    bets_fixed += 1
                                    staked_fixed += st_fixed
                                    if bet_won:
                                        if mkt.startswith('lay_'):
                                            bankroll_fixed += st_fixed
                                        else:
                                            bankroll_fixed += st_fixed * (effective_odds - 1.0)
                                        wins_fixed += 1
                                    else:
                                        if mkt.startswith('lay_'):
                                            bankroll_fixed -= st_fixed * (effective_odds - 1.0)
                                        else:
                                            bankroll_fixed -= st_fixed

                                    if bankroll_fixed >= peak_fixed:
                                        peak_fixed = bankroll_fixed
                                        current_dd_duration_fixed = 0
                                    else:
                                        current_dd_duration_fixed += 1
                                        if current_dd_duration_fixed > max_dd_duration_fixed:
                                            max_dd_duration_fixed = current_dd_duration_fixed
                                            
                                    dd_fixed = (peak_fixed - bankroll_fixed) / peak_fixed if peak_fixed > 0 else 0
                                    if dd_fixed > max_dd_fixed:
                                        max_dd_fixed = dd_fixed
                                    equity_curve_fixed.append({'date': date_str, 'bankroll': round(bankroll_fixed, 2)})

                                # 2. Proportional Stake Simulation (2% of current bankroll or the active stake value if proportional)
                                pct_prop = stake_value if staking_rule == 'proportional' else 2.0
                                st_prop = bankroll_proportional * (pct_prop / 100.0)
                                if bankroll_proportional >= st_prop and st_prop > 0.01:
                                    bets_prop += 1
                                    staked_prop += st_prop
                                    if bet_won:
                                        if mkt.startswith('lay_'):
                                            bankroll_proportional += st_prop
                                        else:
                                            bankroll_proportional += st_prop * (effective_odds - 1.0)
                                        wins_prop += 1
                                    else:
                                        if mkt.startswith('lay_'):
                                            bankroll_proportional -= st_prop * (effective_odds - 1.0)
                                        else:
                                            bankroll_proportional -= st_prop

                                    if bankroll_proportional >= peak_prop:
                                        peak_prop = bankroll_proportional
                                        current_dd_duration_prop = 0
                                    else:
                                        current_dd_duration_prop += 1
                                        if current_dd_duration_prop > max_dd_duration_prop:
                                            max_dd_duration_prop = current_dd_duration_prop
                                            
                                    dd_prop = (peak_prop - bankroll_proportional) / peak_prop if peak_prop > 0 else 0
                                    if dd_prop > max_dd_prop:
                                        max_dd_prop = dd_prop
                                    equity_curve_proportional.append({'date': date_str, 'bankroll': round(bankroll_proportional, 2)})

                                # 3. Kelly Stake Simulation (1/4 Kelly or active fraction if Kelly)
                                mult_k = 0.25
                                if staking_rule == 'kelly': mult_k = stake_value

                                if effective_odds > 1.0:
                                    if kelly_probs is not None and kelly_outcomes is not None and len(kelly_probs) > 1:
                                        f_star = solve_kelly_multi(kelly_probs, kelly_outcomes, max_f=0.20)
                                    elif mkt.startswith('lay_'):
                                        # Kelly for lay bets: f* = p/(L-1) - (1-p)
                                        f_star = model_prob / (effective_odds - 1.0) - (1.0 - model_prob)
                                    else:
                                        f_star = (model_prob * effective_odds - 1.0) / (effective_odds - 1.0)
                                    f_star = max(0.0, f_star)
                                    st_kelly = bankroll_kelly * f_star * mult_k
                                    st_kelly = min(st_kelly, bankroll_kelly * 0.05)
                                else:
                                    st_kelly = 0.0

                                if bankroll_kelly >= st_kelly and st_kelly > 0.01:
                                    bets_kelly += 1
                                    staked_kelly += st_kelly
                                    if bet_won:
                                        if mkt.startswith('lay_'):
                                            bankroll_kelly += st_kelly
                                        else:
                                            bankroll_kelly += st_kelly * (effective_odds - 1.0)
                                        wins_kelly += 1
                                    else:
                                        if mkt.startswith('lay_'):
                                            bankroll_kelly -= st_kelly * (effective_odds - 1.0)
                                        else:
                                            bankroll_kelly -= st_kelly

                                    if bankroll_kelly >= peak_kelly:
                                        peak_kelly = bankroll_kelly
                                        current_dd_duration_kelly = 0
                                    else:
                                        current_dd_duration_kelly += 1
                                        if current_dd_duration_kelly > max_dd_duration_kelly:
                                            max_dd_duration_kelly = current_dd_duration_kelly
                                            
                                    dd_kelly = (peak_kelly - bankroll_kelly) / peak_kelly if peak_kelly > 0 else 0
                                    if dd_kelly > max_dd_kelly:
                                        max_dd_kelly = dd_kelly
                                    equity_curve_kelly.append({'date': date_str, 'bankroll': round(bankroll_kelly, 2)})

                                # Update daily exposure
                                daily_exposure[date_str_check] += stake

                                # Calculate CLV (Closing Line Value)
                                clv = None
                                closing_odd = None
                                if mkt in ('home', '1x2_home'):
                                    closing_odd = closing_odds_h
                                elif mkt in ('away', '1x2_away'):
                                    closing_odd = closing_odds_a
                                elif mkt in ('draw', '1x2_draw'):
                                    closing_odd = closing_odds_d
                                elif mkt == 'over25':
                                    closing_odd = closing_odds_over25
                                elif mkt == 'under25':
                                    closing_odd = closing_odds_under25
                                
                                if closing_odd and not pd.isna(closing_odd) and closing_odd > 1.0:
                                    clv = (effective_odds / closing_odd - 1.0) * 100  # as percentage

                                bets_record.append({
                                    'date': match_date.strftime('%Y-%m-%d'),
                                    'league': league_code,
                                    'home_team': home_team,
                                    'away_team': away_team,
                                    'score': f"{int(fthg)}-{int(ftag)}",
                                    'market': market_label,
                                    'odds': round(bookie_odds, 2),
                                    'prob': round(model_prob * 100, 1),
                                    'ev': round(expected_value, 2),
                                    'stake': round(stake, 2),
                                    'profit': round(profit, 2),
                                    'bankroll': round(bankroll, 2),
                                    'won': bet_won,
                                    'clv': round(clv, 2) if clv is not None else None,
                                    'odds_h': round(odds_h, 2) if (odds_h and not pd.isna(odds_h)) else None,
                                    'odds_d': round(odds_d, 2) if (odds_d and not pd.isna(odds_d)) else None,
                                    'odds_a': round(odds_a, 2) if (odds_a and not pd.isna(odds_a)) else None,
                                    'odds_over25': round(odds_over25, 2) if (odds_over25 and not pd.isna(odds_over25)) else None,
                                    'odds_under25': round(odds_under25, 2) if (odds_under25 and not pd.isna(odds_under25)) else None,
                                    'is_synthetic': is_synthetic,
                                    'is_oos': (oos_cutoff_dt is not None and match_date >= oos_cutoff_dt),
                                    'ml_applied': ml_applied
                                })

                        else:
                            # Expected value below threshold — counted as skipped
                            markets_skipped_ev += 1

                # 3b. NOW store calibration history (after betting decision)
                self.calibration_history[mkt]['probs'].append(raw_prob)
                self.calibration_history[mkt]['outcomes'].append(1 if bet_won else 0)

                # 3c. Store stacking history (poisson + xgb → outcome)
                if use_ml and ml_prob is not None:
                    self.stacking_history[mkt]['poisson'].append(poisson_prob)
                    self.stacking_history[mkt]['xgb'].append(ml_prob)
                    self.stacking_history[mkt]['outcomes'].append(1 if bet_won else 0)
                            
            # Model freeze for true Out-of-Sample: after the cutoff date, stop refitting
            # calibrators, ML ensembles, and stacking learners so that subsequent bets
            # are made with models that have never seen this data.
            if oos_cutoff_dt is not None and match_date >= oos_cutoff_dt:
                models_frozen = True

            # Fit Calibration Periodically
            # NOTE: threshold raised from 50 → 200 to avoid fitting the Platt
            # scaler on pure noise when sample sizes are small. Below 200 obs
            # the scaler was learning random variance, not a real calibration
            # signal, and could make well-calibrated Poisson probs worse.
            self.matches_since_calibration += 1
            if not models_frozen and self.matches_since_calibration >= 100:
                self.matches_since_calibration = 0
                for c_mkt, hist in self.calibration_history.items():
                    if len(hist['probs']) > 2000:
                        hist['probs'] = hist['probs'][-2000:]
                        hist['outcomes'] = hist['outcomes'][-2000:]
                    if len(hist['probs']) >= 500:  # raised from 200 → 500 to prevent temporal leak on small samples
                        if c_mkt not in self.calibrators:
                            self.calibrators[c_mkt] = IsotonicCalibrator(epochs=200)
                        self.calibrators[c_mkt].fit(hist['probs'], hist['outcomes'])

            # Fit ML Ensemble Periodically
            if use_ml and not models_frozen:
                self.matches_since_ml_fit += 1
            if not models_frozen and self.matches_since_ml_fit >= 300:
                self.matches_since_ml_fit = 0
                for c_mkt, hist in self.ml_history.items():
                    if len(hist['X']) > 3000:
                        hist['X'] = hist['X'][-3000:]
                        hist['y'] = hist['y'][-3000:]
                    if len(hist['X']) >= 200:  # aligned with MLEnsemble.MIN_SAMPLES_TO_FIT
                        if c_mkt not in self.ml_ensembles:
                            self.ml_ensembles[c_mkt] = MLEnsemble(c_mkt)
                        self.ml_ensembles[c_mkt].fit(hist['X'], hist['y'])

            # Fit Stacking Meta-Learner Periodically
            if use_ml and not models_frozen:
                self.matches_since_stacking_fit += 1
            if not models_frozen and self.matches_since_stacking_fit >= 500:
                self.matches_since_stacking_fit = 0
                for s_mkt, s_hist in self.stacking_history.items():
                    if len(s_hist['poisson']) > 4000:
                        s_hist['poisson'] = s_hist['poisson'][-4000:]
                        s_hist['xgb'] = s_hist['xgb'][-4000:]
                        s_hist['outcomes'] = s_hist['outcomes'][-4000:]
                    if len(s_hist['poisson']) >= 200:
                        if s_mkt not in self.stacking_learners:
                            self.stacking_learners[s_mkt] = StackingMetaLearner(s_mkt)
                        self.stacking_learners[s_mkt].history = s_hist
                        self.stacking_learners[s_mkt].fit()

            # 4. Update the rolling form lists with this match result (chronological flow)
            self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                              league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                              team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                              league_home_sot, league_away_sot, hst, ast,
                              team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                              league_home_xg, league_away_xg, hxg, axg,
                              team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                              league_home_goals_ht, league_away_goals_ht, hthg, htag)
            self._update_corners_form(team_home_corners_for, team_home_corners_against,
                                      team_away_corners_for, team_away_corners_against,
                                      league_home_corners, league_away_corners,
                                      league_code, home_team, away_team,
                                      row.get('HC'), row.get('AC'))

            # Elo and rho updates freeze during OOS to prevent data leakage
            if not models_frozen:
                elo_tracker.update(home_team, away_team, int(fthg), int(ftag))
            # Update rho estimation data
            rho_data = league_goals_for_rho[league_code]
            rho_data['h'].append(int(fthg))
            rho_data['a'].append(int(ftag))
            rho_data['lh'].append(lambda_home if 'lambda_home' in dir() else 1.3)
            rho_data['la'].append(lambda_away if 'lambda_away' in dir() else 1.0)
            # Invalidate rho cache for this league every 50 matches
            if len(rho_data['h']) % RHO_CACHE_INVALIDATION_MATCHES == 0:
                league_rho_cache.pop(league_code, None)

        # Append final day's return after loop ends
        if prev_date is not None and day_start_bankroll > 0:
            daily_ret = daily_pnl.get(prev_date, 0.0) / day_start_bankroll
            all_daily_returns.append(daily_ret)

        # Compile performance results
        summary_dict = compile_backtest_summary(
            bets_record, initial_bankroll, bankroll, total_staked, staking_rule, stake_value, value_threshold,
            run_monte_carlo, min_odds, max_odds, start_date, end_date,
            bankroll_fixed, bankroll_proportional, bankroll_kelly,
            staked_fixed, staked_prop, staked_kelly,
            wins_fixed, wins_prop, wins_kelly,
            bets_fixed, bets_prop, bets_kelly,
            max_dd_fixed, max_dd_prop, max_dd_kelly,
            max_dd_duration_fixed, max_dd_duration_prop, max_dd_duration_kelly,
            equity_curve_fixed, equity_curve_proportional, equity_curve_kelly,
            max_drawdown,
            oos_split_pct=oos_split_pct,
            slippage_pct=slippage_base_pct
        )
        
        # Inject exclusion tracking stats
        s = summary_dict['summary']
        s['matches_total_in_file'] = matches_total_in_file
        s['matches_skipped_unplayed'] = matches_skipped_unplayed
        s['matches_skipped_no_1x2'] = matches_skipped_no_1x2
        s['seasons_analyzed'] = seasons_analyzed
        s['markets_evaluated_total'] = markets_evaluated_total
        s['markets_skipped_nan'] = markets_skipped_nan
        s['markets_skipped_ht_no_data'] = markets_skipped_ht_no_data
        s['markets_skipped_filter'] = markets_skipped_filter
        s['markets_skipped_ev'] = markets_skipped_ev
        s['bets_placed'] = bets_placed
        s['nan_skipped_pct'] = round((markets_skipped_nan / markets_evaluated_total * 100) if markets_evaluated_total > 0 else 0.0, 1)
        
        synthetic_bets_count = sum(1 for b in bets_record if b.get('is_synthetic', False))
        summary_dict['summary']['synthetic_bets_count'] = synthetic_bets_count
        summary_dict['summary']['synthetic_bets_pct'] = round((synthetic_bets_count / len(bets_record) * 100) if bets_record else 0.0, 1)
        summary_dict['summary']['slippage_applied'] = odds_timing == 'closing'
        summary_dict['summary']['slippage_pct'] = slippage_base_pct if odds_timing == 'closing' else 0.0

        ml_applied_count = sum(1 for b in bets_record if b.get('ml_applied', False))
        summary_dict['summary']['ml_applied_count'] = ml_applied_count
        summary_dict['summary']['ml_applied_pct'] = round((ml_applied_count / len(bets_record) * 100) if bets_record else 0.0, 1)
        
        # Check if calibration was skipped due to insufficient samples (< 200) - Phase 3 Fix
        cal_samples = 0
        cal_skipped = False
        for m in markets_list:
            cal_history = self.calibration_history.get(m, {'probs': []})
            m_samples = len(cal_history['probs'])
            cal_samples += m_samples
            if m_samples < 500:
                cal_skipped = True
                
        summary_dict['summary']['calibration_samples'] = cal_samples
        summary_dict['summary']['calibration_skipped'] = cal_skipped

        self.last_bets_record = bets_record

        return summary_dict

    def run_walk_forward(self, leagues, start_date, end_date, n_folds=5, market=None,
                         value_threshold=1.02, initial_bankroll=1000,
                         staking_rule='fixed', stake_value=10,
                         odds_source='B365', odds_timing='closing',
                         min_odds=1.0, max_odds=2.50, use_ml=False,
                         data_source='football-data', futpython_api_key='',
                         min_odds_h=None, max_odds_h=None, min_odds_d=None, max_odds_d=None,
                         min_odds_a=None, max_odds_a=None,
                         min_odds_over25=None, max_odds_over25=None,
                         min_odds_under25=None, max_odds_under25=None,
                         exchange_commission=0.0, slippage=None, **kwargs):
        """
        True walk-forward validation with expanding windows and state continuity.

        Divides the total period into n_folds. Each fold trains on all data before its test
        window and tests on its allocated window. Calibrators, ML ensembles, stacking learners,
        and their histories are carried forward from one fold to the next so that early folds'
        fitted models benefit later folds (expanding-window retraining).

        Returns aggregate metrics: per-fold breakdown + cross-fold mean/median/std/min/max ROI.
        """
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        total_days = (end_dt - start_dt).days

        if total_days <= 0:
            return {"error": "end_date must be after start_date"}
        if n_folds < 2:
            return {"error": "Walk-forward requires at least 2 folds"}

        fold_size_days = total_days // n_folds
        all_fold_results = []
        all_oos_bets = []
        prev_state = None  # Carries calibrators, ML ensembles, stacking state across folds

        for fold in range(n_folds):
            # Test window for this fold
            test_start = start_dt + pd.Timedelta(days=int(fold_size_days * fold))
            test_end = start_dt + pd.Timedelta(days=int(fold_size_days * (fold + 1)) - 1)
            if fold == n_folds - 1:
                test_end = end_dt  # Last fold gets remaining days

            train_days = (test_start - start_dt).days
            if train_days < 30:
                continue  # Skip folds with too little training data

            oos_date_cutoff = test_start.strftime('%Y-%m-%d')
            fold_end_str = test_end.strftime('%Y-%m-%d')

            # Create fresh engine for each fold (no cross-fold state leakage)
            fold_engine = ChronologicalBacktester()
            if prev_state is not None:
                fold_engine.transfer_state(prev_state)

            try:
                fold_result = fold_engine.run(
                    leagues=leagues,
                    start_date=start_date,
                    end_date=fold_end_str,
                    market=market if isinstance(market, (list, str)) else [market],
                    value_threshold=value_threshold,
                    initial_bankroll=initial_bankroll,
                    staking_rule=staking_rule,
                    stake_value=stake_value,
                    odds_source=odds_source,
                    odds_timing=odds_timing,
                    min_odds=min_odds,
                    max_odds=max_odds,
                    use_ml=use_ml,
                    data_source=data_source,
                    futpython_api_key=futpython_api_key,
                    min_odds_h=min_odds_h, max_odds_h=max_odds_h,
                    min_odds_d=min_odds_d, max_odds_d=max_odds_d,
                    min_odds_a=min_odds_a, max_odds_a=max_odds_a,
                    min_odds_over25=min_odds_over25, max_odds_over25=max_odds_over25,
                    min_odds_under25=min_odds_under25, max_odds_under25=max_odds_under25,
                    exchange_commission=exchange_commission,
                    slippage=slippage,
                    oos_split_pct=0.0,
                    oos_date_cutoff=oos_date_cutoff,
                    run_monte_carlo=False,
                    model_type=kwargs.get('model_type', MODEL_POISSON)
                )
            except Exception as e:
                logger.warning(f"Walk-forward fold {fold + 1} failed: {e}")
                continue

            if "error" in fold_result:
                continue

            fold_oos_bets = [b for b in fold_engine.last_bets_record if b.get('is_oos', False)]

            if len(fold_oos_bets) < 10:
                continue

            fold_profit = sum(b.get('profit', 0) for b in fold_oos_bets)
            fold_staked = sum(b.get('stake', 0) for b in fold_oos_bets)
            fold_wins = sum(1 for b in fold_oos_bets if b.get('profit', 0) > 0)
            fold_roi = (fold_profit / fold_staked * 100) if fold_staked > 0 else 0
            fold_win_rate = (fold_wins / len(fold_oos_bets) * 100) if fold_oos_bets else 0

            fold_result = {
                'fold': fold + 1,
                'train_start': start_date,
                'train_end': test_start.strftime('%Y-%m-%d'),
                'test_start': test_start.strftime('%Y-%m-%d'),
                'test_end': fold_end_str,
                'train_days': train_days,
                'test_days': (test_end - test_start).days,
                'total_bets': len(fold_oos_bets),
                'wins': fold_wins,
                'losses': len(fold_oos_bets) - fold_wins,
                'net_profit': round(fold_profit, 2),
                'total_staked': round(fold_staked, 2),
                'roi': round(fold_roi, 2),
                'win_rate': round(fold_win_rate, 1),
                'profit_factor': round(fold_profit / max(abs(sum(
                    b.get('profit', 0) for b in fold_oos_bets if b.get('profit', 0) < 0
                )), 0.01), 2),
            }

            # Drawdown from equity curve
            bankroll = initial_bankroll
            peak = initial_bankroll
            max_dd = 0.0
            for b in fold_oos_bets:
                bankroll += b.get('profit', 0)
                if bankroll > peak:
                    peak = bankroll
                dd = (peak - bankroll) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
            fold_result['max_drawdown_pct'] = round(max_dd * 100, 2)

            all_fold_results.append(fold_result)

            # Preserve engine state for next fold (expanding-window continuity)
            prev_state = fold_engine.export_state()

            # Tag bets with fold number for traceability
            for b in fold_oos_bets:
                b['walk_forward_fold'] = fold + 1
            all_oos_bets.extend(fold_oos_bets)

        if not all_fold_results:
            return {"error": "Not enough data for walk-forward validation across any fold."}

        fold_rois = [f['roi'] for f in all_fold_results]
        fold_profits = [f['net_profit'] for f in all_fold_results]
        fold_win_rates = [f['win_rate'] for f in all_fold_results]
        fold_drawdowns = [f['max_drawdown_pct'] for f in all_fold_results]

        # Robustness: proportion of folds with positive ROI
        positive_folds = sum(1 for r in fold_rois if r > 0)

        # Walk-forward score: composite 0-100
        # Rewards consistent positive ROI, penalizes high cross-fold variance
        mean_roi = float(np.mean(fold_rois))
        std_roi = float(np.std(fold_rois, ddof=1)) if len(fold_rois) > 1 else 0.0
        cv_roi = abs(std_roi / mean_roi) if abs(mean_roi) > 0.01 else (10.0 if std_roi > 1 else 5.0)

        # Score components (each 0-25)
        consistency_score = min(25, positive_folds / len(all_fold_results) * 25)
        roi_score = min(25, max(0, mean_roi * 3))  # 8.33% ROI = max score
        stability_score = min(25, max(0, 25 - cv_roi * 5))  # Lower CV = higher score
        drawdown_score = min(25, max(0, 25 - float(np.mean(fold_drawdowns)) * 0.5))  # Lower DD = higher score

        wf_score = round(consistency_score + roi_score + stability_score + drawdown_score, 1)

        aggregate = {
            'method': 'walk_forward',
            'n_folds': len(all_fold_results),
            'n_folds_configured': n_folds,
            'folds_completed': len(all_fold_results),
            'folds_skipped': n_folds - len(all_fold_results),
            'fold_results': all_fold_results,
            'total_oos_bets': sum(f['total_bets'] for f in all_fold_results),
            'mean_roi': round(mean_roi, 2),
            'median_roi': round(float(np.median(fold_rois)), 2),
            'std_roi': round(std_roi, 2),
            'min_roi': round(float(min(fold_rois)), 2),
            'max_roi': round(float(max(fold_rois)), 2),
            'mean_profit': round(float(np.mean(fold_profits)), 2),
            'mean_win_rate': round(float(np.mean(fold_win_rates)), 1),
            'mean_max_drawdown': round(float(np.mean(fold_drawdowns)), 2),
            'positive_folds': positive_folds,
            'positive_folds_pct': round(positive_folds / len(all_fold_results) * 100, 1),
            'cv_roi': round(cv_roi, 2),
            'walk_forward_score': wf_score,
            'verdict': 'STRONG' if wf_score >= 70 else ('MODERATE' if wf_score >= 45 else 'WEAK'),
            'all_oos_bets': all_oos_bets,
        }

        return aggregate

    def run_parallel_scan(self, leagues, start_date, end_date, value_threshold, initial_bankroll, staking_rule, stake_value, odds_source='B365', odds_timing='closing', min_odds=1.0, max_odds=2.50, scan_type='markets', markets_list=None, use_ml=False, data_source='football-data', futpython_api_key='', model_type=MODEL_POISSON):
        """
        Runs a highly optimized parallel scan of either multiple markets or multiple leagues
        in a single chronological pass to avoid duplicate ratings computation.
        """
        # Normalize odds_source (frontend sends lowercase like 'bet365')
        if odds_source:
            _os = odds_source.lower()
            if _os in ('b365', 'bet365'):
                odds_source = 'B365'
            elif _os in ('avg', 'average', 'market_average', 'market'):
                odds_source = 'Avg'
            elif _os in ('max', 'pinnacle', 'maximum'):
                odds_source = 'Max'

        # 1. Load data for all selected leagues
        self.last_scan_diagnostics = {
            "leagues_loaded": {},
            "errors": [],
            "total_combined_matches": 0,
            "total_active_period_matches": 0,
            "total_bets_placed": 0
        }
        all_matches = []
        for league_code in leagues:
            try:
                df = load_league_data(league_code, start_date='2020-08-01', data_source=data_source, api_key=futpython_api_key)
                self.last_scan_diagnostics["leagues_loaded"][league_code] = len(df)
                if not df.empty:
                    all_matches.append(df)
                else:
                    self.last_scan_diagnostics["errors"].append(f"A liga {league_code} retornou dataframe vazio.")
            except Exception as e:
                self.last_scan_diagnostics["errors"].append(f"Erro ao carregar a liga {league_code}: {str(e)}")
                self.last_scan_diagnostics["leagues_loaded"][league_code] = 0
                
        if not all_matches:
            return {}
            
        combined_df = pd.concat(all_matches, ignore_index=True)

        if combined_df.empty:
            return {}

        # Pre-compute league-average xG for fallback when match xG is missing
        _league_xg_fallback = {}
        for _lc in leagues:
            _ldf = combined_df[combined_df['LeagueCode'] == _lc]
            _hxg = _ldf['HomeXG'].dropna()
            _axg = _ldf['AwayXG'].dropna()
            _league_xg_fallback[_lc] = {
                'home': float(_hxg.mean()) if len(_hxg) > 10 else 1.45,
                'away': float(_axg.mean()) if len(_axg) > 10 else 1.15,
            }

        self.last_scan_diagnostics["total_combined_matches"] = len(combined_df)
        self.last_scan_diagnostics["exclusion_stats"] = {
            "matches_total_in_file": len(combined_df),
            "matches_skipped_unplayed": 0,
            "matches_skipped_no_1x2": 0,
            "markets_evaluated_total": 0,
            "markets_skipped_ht_no_data": 0,
            "markets_skipped_nan": 0,
            "markets_skipped_filter": 0,
            "markets_skipped_ev": 0,
            "bets_placed": 0,
        }
        _exstats = self.last_scan_diagnostics["exclusion_stats"]
        active_matches = combined_df[(combined_df['Date'] >= pd.to_datetime(start_date)) & (combined_df['Date'] <= pd.to_datetime(end_date))]
        self.last_scan_diagnostics["total_active_period_matches"] = len(active_matches)
        logger.debug('Total combined_df matches: %d', len(combined_df))
        combined_df.sort_values('Date', inplace=True)
        combined_df = combined_df.sort_values(by=['Date', 'Time']).reset_index(drop=True)
        
        # 2. Setup state trackers for rolling form
        team_home_scored = defaultdict(list)
        team_home_conceded = defaultdict(list)
        team_away_scored = defaultdict(list)
        team_away_conceded = defaultdict(list)
        
        team_home_sot = defaultdict(list)
        team_home_sot_conceded = defaultdict(list)
        team_away_sot = defaultdict(list)
        team_away_sot_conceded = defaultdict(list)
        
        league_home_goals = defaultdict(list)
        league_away_goals = defaultdict(list)
        league_home_sot = defaultdict(list)
        league_away_sot = defaultdict(list)
        
        team_home_xg = defaultdict(list)
        team_home_xg_conceded = defaultdict(list)
        team_away_xg = defaultdict(list)
        team_away_xg_conceded = defaultdict(list)
        
        league_home_xg = defaultdict(list)
        league_away_xg = defaultdict(list)
        
        
        # Corners tracking for corners model
        team_home_corners_for = defaultdict(list)
        team_home_corners_against = defaultdict(list)
        team_away_corners_for = defaultdict(list)
        team_away_corners_against = defaultdict(list)
        league_home_corners = defaultdict(list)
        league_away_corners = defaultdict(list)
        team_home_scored_ht = defaultdict(list)
        team_home_conceded_ht = defaultdict(list)
        team_away_scored_ht = defaultdict(list)
        team_away_conceded_ht = defaultdict(list)
        league_home_goals_ht = defaultdict(list)
        league_away_goals_ht = defaultdict(list)

        elo_tracker = EloTracker(k_factor=ELO_K_FACTOR, home_advantage=ELO_HOME_ADVANTAGE)
        self.probability_pipeline = ProbabilityPipeline(model_type=model_type)
        league_rho_cache = {}
        league_goals_for_rho = defaultdict(lambda: {'h': [], 'a': [], 'lh': [], 'la': []})

        last_match_date = {}
        season_points = defaultdict(lambda: defaultdict(int))
        season_games = defaultdict(lambda: defaultdict(int))
        models_frozen = False

        # 3. Setup independent simulation states
        states = {}
        if scan_type == 'markets':
            for mkt in markets_list:
                states[mkt] = {
                    'bankroll': initial_bankroll,
                    'peak_bankroll': initial_bankroll,
                    'total_staked': 0.0,
                    'total_bets': 0,
                    'wins': 0,
                    'bets_for_ai': [],
                    'daily_exposure': defaultdict(float),
                    'daily_bet_count': defaultdict(int)
                }
        elif scan_type == 'leagues':
            for l_code in leagues:
                states[l_code] = {
                    'bankroll': initial_bankroll,
                    'peak_bankroll': initial_bankroll,
                    'total_staked': 0.0,
                    'total_bets': 0,
                    'wins': 0,
                    'bets_for_ai': [],
                    'daily_exposure': defaultdict(float),
                    'daily_bet_count': defaultdict(int)
                }
        elif scan_type == 'combinations':
            for l in leagues:
                for m in markets_list:
                    states[f"{l}|{m}"] = {
                        'bankroll': initial_bankroll,
                        'peak_bankroll': initial_bankroll,
                        'total_staked': 0.0,
                        'total_bets': 0,
                        'wins': 0,
                        'bets_for_ai': [],
                        'daily_exposure': defaultdict(float),
                        'daily_bet_count': defaultdict(int)
                    }

        elif scan_type == 'staking':
            # Staking rule comparison: each league|market gets 3 parallel sub-states
            STAKING_CONFIGS = {
                'fixed':        {'staking_rule': 'fixed',        'stake_value': 10.0},
                'proportional': {'staking_rule': 'proportional', 'stake_value': 2.0},
                'kelly':        {'staking_rule': 'kelly',        'stake_value': 0.25},
            }
            def _make_substate():
                return {
                    'bankroll': initial_bankroll,
                    'peak_bankroll': initial_bankroll,
                    'total_staked': 0.0,
                    'total_bets': 0,
                    'wins': 0,
                    'bets_for_ai': [],
                    'daily_exposure': defaultdict(float),
                    'daily_bet_count': defaultdict(int)
                }
            for l in leagues:
                for m in markets_list:
                    key = f"{l}|{m}"
                    states[key] = {
                        'fixed':        _make_substate(),
                        'proportional': _make_substate(),
                        'kelly':        _make_substate(),
                    }

        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        # Slippage simulation for closing odds (same as run() method)
        slippage_base_pct = 1.0 if odds_timing == 'closing' else 0.0

        # 4. Simulation loop
        for row in combined_df.to_dict('records'):
            match_date = row['Date']
            league_code = row['LeagueCode']
            _decay = get_league_weighted_decay(league_code)
            home_team = row['HomeTeam']
            away_team = row['AwayTeam']
            fthg = row['FTHG']
            ftag = row['FTAG']
            ftr = row['FTR']
            
            if pd.isna(fthg) or pd.isna(ftag):
                _exstats["matches_skipped_unplayed"] += 1
                continue

            # Precompute booleans once per row (avoids repeated string comparisons in bet evaluation)
            is_home_win = (ftr == 'H')
            is_away_win = (ftr == 'A')
            is_draw = (ftr == 'D')
            total_goals = int(fthg) + int(ftag)
            
            hthg = row.get('HTHG')
            htag = row.get('HTAG')
                
            # Skip heavy calculations for warm-up matches
            hst = row.get('HST')
            ast = row.get('AST')
            hxg = row.get('HomeXG')
            axg = row.get('AwayXG')
            
            # xG Fallback: use SOT*0.33 first, then league-average xG (NOT actual goals)
            if pd.isna(hxg) or hxg == 0:
                hxg = (hst * 0.33) if (not pd.isna(hst) and hst > 0) else _league_xg_fallback.get(league_code, {}).get('home', 1.45)
            if pd.isna(axg) or axg == 0:
                axg = (ast * 0.33) if (not pd.isna(ast) and ast > 0) else _league_xg_fallback.get(league_code, {}).get('away', 1.15)
                
            # Calculate rest days (fatigue)
            current_dt = pd.to_datetime(match_date)
            home_last = last_match_date.get(home_team)
            away_last = last_match_date.get(away_team)
            rest_days_home = min(15, (current_dt - home_last).days) if home_last else 10
            rest_days_away = min(15, (current_dt - away_last).days) if away_last else 10
            
            # Save/update last match date
            last_match_date[home_team] = current_dt
            last_match_date[away_team] = current_dt
            
            # Calculate motivation/urgency based on standings
            season_key = (league_code, row.get('Season', 'All'))
            motivation_home = self._calculate_motivation(season_points[season_key], home_team, season_games[season_key])
            motivation_away = self._calculate_motivation(season_points[season_key], away_team, season_games[season_key])
            
            # Update points and games in standings (for future matches)
            if home_team not in season_points[season_key]:
                season_points[season_key][home_team] = 0
                season_games[season_key][home_team] = 0
            if away_team not in season_points[season_key]:
                season_points[season_key][away_team] = 0
                season_games[season_key][away_team] = 0
                
            season_games[season_key][home_team] += 1
            season_games[season_key][away_team] += 1
            
            if is_home_win:
                season_points[season_key][home_team] += 3
            elif is_away_win:
                season_points[season_key][away_team] += 3
            elif is_draw:
                season_points[season_key][home_team] += 1
                season_points[season_key][away_team] += 1
                
            if match_date < start_dt:
                self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                                  league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                                  team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                                  league_home_sot, league_away_sot, hst, ast,
                                  team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                                  league_home_xg, league_away_xg, hxg, axg,
                                  team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                                  league_home_goals_ht, league_away_goals_ht, hthg, htag)
                self._update_corners_form(team_home_corners_for, team_home_corners_against,
                                          team_away_corners_for, team_away_corners_against,
                                          league_home_corners, league_away_corners,
                                          league_code, home_team, away_team,
                                          row.get('HC'), row.get('AC'))
                continue
                
            if odds_timing == 'closing':
                if odds_source == 'B365':
                    odds_h = row.get('B365CH', row.get('B365H'))
                    odds_d = row.get('B365CD', row.get('B365D'))
                    odds_a = row.get('B365CA', row.get('B365A'))
                    odds_over25 = row.get('B365C>2.5', row.get('B365>2.5'))
                    odds_under25 = row.get('B365C<2.5', row.get('B365<2.5'))
                elif odds_source == 'Avg':
                    odds_h = row.get('AvgCH', row.get('AvgH'))
                    odds_d = row.get('AvgCD', row.get('AvgD'))
                    odds_a = row.get('AvgCA', row.get('AvgA'))
                    odds_over25 = row.get('AvgC>2.5', row.get('Avg>2.5'))
                    odds_under25 = row.get('AvgC<2.5', row.get('Avg<2.5'))
                else:
                    odds_h = row.get('MaxCH', row.get('MaxH'))
                    odds_d = row.get('MaxCD', row.get('MaxD'))
                    odds_a = row.get('MaxCA', row.get('MaxA'))
                    odds_over25 = row.get('MaxC>2.5', row.get('Max>2.5'))
                    odds_under25 = row.get('MaxC<2.5', row.get('Max<2.5'))
            else:
                odds_h = row.get('B365H') if odds_source == 'B365' else (row.get('AvgH') if odds_source == 'Avg' else row.get('MaxH'))
                odds_d = row.get('B365D') if odds_source == 'B365' else (row.get('AvgD') if odds_source == 'Avg' else row.get('MaxD'))
                odds_a = row.get('B365A') if odds_source == 'B365' else (row.get('AvgA') if odds_source == 'Avg' else row.get('MaxA'))
                odds_over25 = row.get('B365>2.5') if odds_source == 'B365' else (row.get('Avg>2.5') if odds_source == 'Avg' else row.get('Max>2.5'))
                odds_under25 = row.get('B365<2.5') if odds_source == 'B365' else (row.get('Avg<2.5') if odds_source == 'Avg' else row.get('Max<2.5'))
            
            odds_over05_ht = row.get('Over_HT_0_5', row.get('B365>0.5HT'))
            odds_under05_ht = row.get('Under_HT_0_5', row.get('B365<0.5HT'))
            odds_over15_ht = row.get('Over_HT_1_5', row.get('B365>1.5HT'))
            odds_under15_ht = row.get('Under_HT_1_5', row.get('B365<1.5HT'))
            
            # Extended FutPythonTrader odds
            odds_h_ht = row.get('Odd_1_HT')
            odds_d_ht = row.get('Odd_X_HT')
            odds_a_ht = row.get('Odd_2_HT')
            odds_btts_yes = row.get('BTTS_Yes')
            odds_btts_no = row.get('BTTS_No')
            odds_over15 = row.get('Over_FT_1_5')
            odds_under15 = row.get('Under_FT_1_5')
            odds_over35 = row.get('Over_FT_3_5')
            odds_under35 = row.get('Under_FT_3_5')
            odds_over45 = row.get('Over_FT_4_5')
            odds_under45 = row.get('Under_FT_4_5')
            # Real Double Chance odds from FutPythonTrader
            odds_dc_x2 = row.get('DC_X2')
            odds_dc_1x = row.get('DC_1X')
            odds_dc_12 = row.get('DC_12')
            odds_over05 = row.get('Over_FT_0_5')
            odds_under05 = row.get('Under_FT_0_5')
            odds_win_to_nil_h = row.get('odds_win_to_nil_1')
            odds_win_to_nil_a = row.get('odds_win_to_nil_2')
            
            # Corners
            odds_corners_h = row.get('odds_corners_1')
            odds_corners_d = row.get('odds_corners_x')
            odds_corners_a = row.get('odds_corners_2')
            odds_corners_over_75 = row.get('odds_corners_over_75')
            odds_corners_over_85 = row.get('odds_corners_over_85')
            odds_corners_over_95 = row.get('odds_corners_over_95')
            odds_corners_over_105 = row.get('odds_corners_over_105')
            odds_corners_over_115 = row.get('odds_corners_over_115')
            odds_corners_under_75 = row.get('odds_corners_under_75')
            odds_corners_under_85 = row.get('odds_corners_under_85')
            odds_corners_under_95 = row.get('odds_corners_under_95')
            odds_corners_under_105 = row.get('odds_corners_under_105')
            odds_corners_under_115 = row.get('odds_corners_under_115')

            # HT Goals extra
            odds_over25_ht = row.get('Over_HT_2_5')
            odds_under25_ht = row.get('Under_HT_2_5')
            odds_over35_ht = row.get('Over_HT_3_5')
            odds_under35_ht = row.get('Under_HT_3_5')

            # 2H Goals
            odds_over05_2h = row.get('Over_2H_0_5')
            odds_under05_2h = row.get('Under_2H_0_5')
            odds_over15_2h = row.get('Over_2H_1_5')
            odds_under15_2h = row.get('Under_2H_1_5')
            odds_over25_2h = row.get('Over_2H_2_5')
            odds_under25_2h = row.get('Under_2H_2_5')
            odds_over35_2h = row.get('Over_2H_3_5')
            odds_under35_2h = row.get('Under_2H_3_5')

            # 2H Result
            odds_h_2h = row.get('Odd_1_2H')
            odds_d_2h = row.get('Odd_X_2H')
            odds_a_2h = row.get('Odd_2_2H')
            
            # Asian Handicap (Main Spread)
            ahh_line = row.get('AHh')
            if odds_source == 'B365':
                odds_ahh = row.get('B365AHH')
                odds_aha = row.get('B365AHA')
                if (odds_ahh is None or pd.isna(odds_ahh)) and ahh_line is not None and not pd.isna(ahh_line):
                    odds_ahh = get_futpython_ah_odd(row, ahh_line, "Home")
                if (odds_aha is None or pd.isna(odds_aha)) and ahh_line is not None and not pd.isna(ahh_line):
                    odds_aha = get_futpython_ah_odd(row, -ahh_line, "Away")
            else:
                odds_ahh = row.get('AvgAHH') if odds_source == 'Avg' else row.get('MaxAHH')
                odds_aha = row.get('AvgAHA') if odds_source == 'Avg' else row.get('MaxAHA')
            
            closing_odds_h = row.get('PSCH', row.get('PSH', row.get('MaxCH')))
            closing_odds_d = row.get('PSCD', row.get('PSD', row.get('MaxCD')))
            closing_odds_a = row.get('PSCA', row.get('PSA', row.get('MaxCA')))
            closing_odds_over25 = row.get('PC>2.5', row.get('MaxC>2.5'))
            closing_odds_under25 = row.get('PC<2.5', row.get('MaxC<2.5'))
            if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
                _exstats["matches_skipped_no_1x2"] += 1
                self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                                  league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                                  team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                                  league_home_sot, league_away_sot, hst, ast,
                                  team_home_scored_ht=team_home_scored_ht, team_home_conceded_ht=team_home_conceded_ht,
                                  team_away_scored_ht=team_away_scored_ht, team_away_conceded_ht=team_away_conceded_ht,
                                  league_home_goals_ht=league_home_goals_ht, league_away_goals_ht=league_away_goals_ht, hthg=hthg, htag=htag)
                self._update_corners_form(team_home_corners_for, team_home_corners_against,
                                          team_away_corners_for, team_away_corners_against,
                                          league_home_corners, league_away_corners,
                                          league_code, home_team, away_team,
                                          row.get("HC"), row.get("AC"))
                continue
                
            # Compute predictive probabilities via shared pipeline
            bundle = self._compute_match_probabilities(
                team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                league_home_goals, league_away_goals,
                team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                league_home_sot, league_away_sot,
                team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                league_home_xg, league_away_xg,
                team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht,
                team_away_conceded_ht, league_home_goals_ht, league_away_goals_ht,
                home_team, away_team, league_code, _decay,
                league_rho_cache, league_goals_for_rho, elo_tracker
            )
            # Unpack all downstream variables
            lambda_home = bundle['lambda_home']; lambda_away = bundle['lambda_away']
            lambda_goals_home = bundle['lambda_goals_home']; lambda_goals_away = bundle['lambda_goals_away']
            lambda_shots_home = bundle['lambda_shots_home']; lambda_shots_away = bundle['lambda_shots_away']
            lambda_xg_home = bundle['lambda_xg_home']; lambda_xg_away = bundle['lambda_xg_away']
            lambda_home_ht = bundle['lambda_home_ht']; lambda_away_ht = bundle['lambda_away_ht']
            h_att = bundle['h_att']; h_def = bundle['h_def']; a_att = bundle['a_att']; a_def = bundle['a_def']
            h_xg_att = bundle['h_xg_att']; h_xg_def = bundle['h_xg_def']; a_xg_att = bundle['a_xg_att']; a_xg_def = bundle['a_xg_def']
            elo_factor_h = bundle['elo_factor_h']; elo_factor_a = bundle['elo_factor_a']
            prob_matrix = bundle['prob_matrix']
            prob_h = bundle['prob_h']; prob_d = bundle['prob_d']; prob_a = bundle['prob_a']
            prob_over_25 = bundle['prob_over_25']; prob_over_15 = bundle['prob_over_15']
            prob_over_35 = bundle['prob_over_35']; prob_over_45 = bundle['prob_over_45']; prob_over_55 = bundle['prob_over_55']
            prob_btts_yes = bundle['prob_btts_yes']
            prob_matrix_ht = bundle['prob_matrix_ht']
            prob_h_ht = bundle['prob_h_ht']; prob_d_ht = bundle['prob_d_ht']; prob_a_ht = bundle['prob_a_ht']
            prob_over_05_ht = bundle['prob_over_05_ht']; prob_over_15_ht = bundle['prob_over_15_ht']
            rho = bundle['rho']
            
            est_odds = None

            # Compute corners probabilities using league-average rates (Poisson model)
            leg_h_corners = league_home_corners[league_code][-200:]
            leg_a_corners = league_away_corners[league_code][-200:]
            expected_home_corners = np.mean(leg_h_corners) if leg_h_corners else 5.5
            expected_away_corners = np.mean(leg_a_corners) if leg_a_corners else 4.5
            corners_probs = compute_corners_probs(expected_home_corners, expected_away_corners)

            def eval_market(mkt):
                nonlocal est_odds
                model_prob = 0.0
                bookie_odds = np.nan
                bet_won = False
                
                # Check for missing HT data for HT markets
                if mkt.startswith('ht_') and (pd.isna(hthg) or pd.isna(htag)):
                    _exstats["markets_skipped_ht_no_data"] += 1
                    return None
                
                if mkt in ('home', '1x2_home'):
                    model_prob = prob_h
                    bookie_odds = odds_h
                    bet_won = is_home_win
                elif mkt in ('away', '1x2_away'):
                    model_prob = prob_a
                    bookie_odds = odds_a
                    bet_won = is_away_win
                elif mkt in ('draw', '1x2_draw'):
                    model_prob = prob_d
                    bookie_odds = odds_d
                    bet_won = is_draw
                elif mkt == 'over25':
                    model_prob = prob_over_25
                    bookie_odds = odds_over25
                    bet_won = (total_goals > 2)
                elif mkt == 'under25':
                    model_prob = 1.0 - prob_over_25
                    bookie_odds = odds_under25
                    bet_won = (total_goals < 3)
                elif mkt == 'ht_home':
                    if odds_h_ht is not None and not pd.isna(odds_h_ht) and odds_h_ht > 1.0: bookie_odds = odds_h_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_h_ht
                    bet_won = (hthg > htag)
                elif mkt == 'ht_draw':
                    if odds_d_ht is not None and not pd.isna(odds_d_ht) and odds_d_ht > 1.0: bookie_odds = odds_d_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_d_ht
                    bet_won = (hthg == htag)
                elif mkt == 'ht_away':
                    if odds_a_ht is not None and not pd.isna(odds_a_ht) and odds_a_ht > 1.0: bookie_odds = odds_a_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_a_ht
                    bet_won = (hthg < htag)
                elif mkt == 'ht_over05':
                    if odds_over05_ht is not None and not pd.isna(odds_over05_ht) and odds_over05_ht > 1.0:
                        bookie_odds = odds_over05_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_over_05_ht
                    bet_won = (hthg + htag > 0)
                elif mkt == 'ht_under05':
                    if odds_under05_ht is not None and not pd.isna(odds_under05_ht) and odds_under05_ht > 1.0:
                        bookie_odds = odds_under05_ht
                    else: bookie_odds = np.nan
                    model_prob = 1.0 - prob_over_05_ht
                    bet_won = (hthg + htag == 0)
                elif mkt == 'ht_over15':
                    if odds_over15_ht is not None and not pd.isna(odds_over15_ht) and odds_over15_ht > 1.0:
                        bookie_odds = odds_over15_ht
                    else: bookie_odds = np.nan
                    model_prob = prob_over_15_ht
                    bet_won = (hthg + htag > 1)
                elif mkt == 'ht_under15':
                    if odds_under15_ht is not None and not pd.isna(odds_under15_ht) and odds_under15_ht > 1.0:
                        bookie_odds = odds_under15_ht
                    else: bookie_odds = np.nan
                    model_prob = 1.0 - prob_over_15_ht
                    bet_won = (hthg + htag <= 1)
                elif mkt == 'ah_home':
                    if ahh_line is None or pd.isna(ahh_line): return None
                    ah_probs = calculate_ah_probabilities(prob_matrix, ahh_line)
                    model_prob = ah_probs['win'] + 0.5 * ah_probs['half_win']
                    bookie_odds = odds_ahh
                    
                    score = (fthg - ftag) + ahh_line
                    if score > 0.24: bet_won = 1.0
                    elif 0.10 < score <= 0.25: bet_won = 0.5
                    elif -0.10 <= score <= 0.10: bet_won = 0.0
                    elif -0.25 <= score < -0.10: bet_won = -0.5
                    else: bet_won = -1.0
                elif mkt == 'ah_away':
                    if ahh_line is None or pd.isna(ahh_line): return None
                    ah_probs = calculate_ah_probabilities(prob_matrix, -ahh_line)
                    model_prob = ah_probs['win'] + 0.5 * ah_probs['half_win']
                    bookie_odds = odds_aha
                    
                    score = (ftag - fthg) - ahh_line
                    if score > 0.24: bet_won = 1.0
                    elif 0.10 < score <= 0.25: bet_won = 0.5
                    elif -0.10 <= score <= 0.10: bet_won = 0.0
                    elif -0.25 <= score < -0.10: bet_won = -0.5
                    else: bet_won = -1.0
                else:
                    if est_odds is None:
                        est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away, rho)
                    
                    if mkt == 'over15':
                        if odds_over15 is not None and not pd.isna(odds_over15) and odds_over15 > 1.0:
                            bookie_odds = odds_over15
                        else:
                            bookie_odds = est_odds['bookie_over_15']
                        model_prob = prob_over_15
                        bet_won = (total_goals > 1)
                    elif mkt == 'over35':
                        if odds_over35 is not None and not pd.isna(odds_over35) and odds_over35 > 1.0:
                            bookie_odds = odds_over35
                        else:
                            bookie_odds = est_odds['bookie_over_35']
                        model_prob = prob_over_35
                        bet_won = (total_goals > 3)
                    elif mkt == 'under35':
                        if odds_under35 is not None and not pd.isna(odds_under35) and odds_under35 > 1.0:
                            bookie_odds = odds_under35
                        else:
                            bookie_odds = est_odds['bookie_under_35']
                        model_prob = 1.0 - prob_over_35
                        bet_won = (total_goals < 4)
                    elif mkt == 'over45':
                        model_prob = prob_over_45
                        try:
                            _o45 = float(str(odds_over45).replace(',', '.')) if odds_over45 is not None and not pd.isna(odds_over45) else np.nan
                            bookie_odds = _o45 if _o45 > 1.0 else est_odds['bookie_over_45']
                        except Exception:
                            bookie_odds = est_odds['bookie_over_45']
                        bet_won = (total_goals > 4)
                    elif mkt == 'under45':
                        model_prob = 1.0 - prob_over_45
                        try:
                            _u45 = float(str(odds_under45).replace(',', '.')) if odds_under45 is not None and not pd.isna(odds_under45) else np.nan
                            bookie_odds = _u45 if _u45 > 1.0 else est_odds['bookie_under_45']
                        except Exception:
                            bookie_odds = est_odds['bookie_under_45']
                        bet_won = (total_goals < 5)
                    elif mkt == 'over55':
                        model_prob = prob_over_55
                        bookie_odds = est_odds['bookie_over_55']
                        bet_won = (total_goals > 5)
                    elif mkt == 'under55':
                        model_prob = 1.0 - prob_over_55
                        bookie_odds = est_odds['bookie_under_55']
                        bet_won = (total_goals < 6)
                    elif mkt in ('lay_home', 'lay_home_ex'):
                        model_prob = prob_d + prob_a
                        try:
                            _dc = float(str(odds_dc_x2).replace(',', '.')) if odds_dc_x2 is not None and not pd.isna(odds_dc_x2) else np.nan
                            if pd.isna(_dc) or _dc <= 1.0:
                                _dc = 1.0 / (1.0/odds_d + 1.0/odds_a) if (odds_d > 1.0 and odds_a > 1.0) else np.nan
                            bookie_odds = _dc / (_dc - 1.0) if (_dc > 1.001) else np.nan
                        except Exception:
                            bookie_odds = np.nan
                        bet_won = not is_home_win
                    elif mkt in ('lay_away', 'lay_away_ex'):
                        model_prob = prob_h + prob_d
                        try:
                            _dc = float(str(odds_dc_1x).replace(',', '.')) if odds_dc_1x is not None and not pd.isna(odds_dc_1x) else np.nan
                            if pd.isna(_dc) or _dc <= 1.0:
                                _dc = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan
                            bookie_odds = _dc / (_dc - 1.0) if (_dc > 1.001) else np.nan
                        except Exception:
                            bookie_odds = np.nan
                        bet_won = not is_away_win
                    elif mkt in ('lay_draw', 'lay_draw_ex'):
                        model_prob = prob_h + prob_a
                        try:
                            _dc = float(str(odds_dc_12).replace(',', '.')) if odds_dc_12 is not None and not pd.isna(odds_dc_12) else np.nan
                            if pd.isna(_dc) or _dc <= 1.0:
                                _dc = 1.0 / (1.0/odds_h + 1.0/odds_a) if (odds_h > 1.0 and odds_a > 1.0) else np.nan
                            bookie_odds = _dc / (_dc - 1.0) if (_dc > 1.001) else np.nan
                        except Exception:
                            bookie_odds = np.nan
                        bet_won = not is_draw
                    elif mkt == 'btts_yes':
                        model_prob = prob_btts_yes
                        try:
                            parsed_odd = float(str(odds_btts_yes).replace(',', '.')) if odds_btts_yes is not None and not pd.isna(odds_btts_yes) else np.nan
                            bookie_odds = parsed_odd if parsed_odd > 1.0 else np.nan
                        except Exception:
                            bookie_odds = np.nan
                        bet_won = (fthg > 0 and ftag > 0)
                    elif mkt == 'btts_no':
                        model_prob = 1.0 - prob_btts_yes
                        try:
                            parsed_odd = float(str(odds_btts_no).replace(',', '.')) if odds_btts_no is not None and not pd.isna(odds_btts_no) else np.nan
                            bookie_odds = parsed_odd if parsed_odd > 1.0 else np.nan
                        except Exception:
                            bookie_odds = np.nan
                        bet_won = (fthg == 0 or ftag == 0)
                    elif mkt.startswith('cs_'):
                        def _get_cs_odd_scan(api_col, fallback_key):
                            """Returns real bookmaker odd from API column, falling back to Poisson estimate."""
                            raw = row.get(api_col)
                            try:
                                v = float(str(raw).replace(',', '.')) if raw is not None and not pd.isna(raw) else np.nan
                                return v if v > 1.0 else est_odds[fallback_key]
                            except Exception:
                                return est_odds[fallback_key]
                        if mkt == 'cs_10':
                            model_prob = float(prob_matrix[1, 0])
                            bookie_odds = _get_cs_odd_scan('CS_1_0', 'bookie_cs_10')
                            bet_won = (fthg == 1 and ftag == 0)
                        elif mkt == 'cs_20':
                            model_prob = float(prob_matrix[2, 0])
                            bookie_odds = _get_cs_odd_scan('CS_2_0', 'bookie_cs_20')
                            bet_won = (fthg == 2 and ftag == 0)
                        elif mkt == 'cs_21':
                            model_prob = float(prob_matrix[2, 1])
                            bookie_odds = _get_cs_odd_scan('CS_2_1', 'bookie_cs_21')
                            bet_won = (fthg == 2 and ftag == 1)
                        elif mkt == 'cs_00':
                            model_prob = float(prob_matrix[0, 0])
                            bookie_odds = _get_cs_odd_scan('CS_0_0', 'bookie_cs_00')
                            bet_won = (fthg == 0 and ftag == 0)
                        elif mkt == 'cs_11':
                            model_prob = float(prob_matrix[1, 1])
                            bookie_odds = _get_cs_odd_scan('CS_1_1', 'bookie_cs_11')
                            bet_won = (fthg == 1 and ftag == 1)
                        elif mkt == 'cs_01':
                            model_prob = float(prob_matrix[0, 1])
                            bookie_odds = _get_cs_odd_scan('CS_0_1', 'bookie_cs_01')
                            bet_won = (fthg == 0 and ftag == 1)
                        elif mkt == 'cs_02':
                            model_prob = float(prob_matrix[0, 2])
                            bookie_odds = _get_cs_odd_scan('CS_0_2', 'bookie_cs_02')
                            bet_won = (fthg == 0 and ftag == 2)
                        elif mkt == 'cs_12':
                            model_prob = float(prob_matrix[1, 2])
                            bookie_odds = _get_cs_odd_scan('CS_1_2', 'bookie_cs_12')
                            bet_won = (fthg == 1 and ftag == 2)
                        elif mkt.startswith('lay_cs_'):
                            cs_code = mkt.replace('lay_', '')
                            if cs_code == 'cs_10':
                                back_prob = float(prob_matrix[1, 0])
                                back_odds = est_odds['bookie_cs_10']
                                is_cs = (fthg == 1 and ftag == 0)
                            elif cs_code == 'cs_20':
                                back_prob = float(prob_matrix[2, 0])
                                back_odds = est_odds['bookie_cs_20']
                                is_cs = (fthg == 2 and ftag == 0)
                            elif cs_code == 'cs_21':
                                back_prob = float(prob_matrix[2, 1])
                                back_odds = est_odds['bookie_cs_21']
                                is_cs = (fthg == 2 and ftag == 1)
                            elif cs_code == 'cs_00':
                                back_prob = float(prob_matrix[0, 0])
                                back_odds = est_odds['bookie_cs_00']
                                is_cs = (fthg == 0 and ftag == 0)
                            elif cs_code == 'cs_11':
                                back_prob = float(prob_matrix[1, 1])
                                back_odds = est_odds['bookie_cs_11']
                                is_cs = (fthg == 1 and ftag == 1)
                            elif cs_code == 'cs_01':
                                back_prob = float(prob_matrix[0, 1])
                                back_odds = est_odds['bookie_cs_01']
                                is_cs = (fthg == 0 and ftag == 1)
                            elif cs_code == 'cs_02':
                                back_prob = float(prob_matrix[0, 2])
                                back_odds = est_odds['bookie_cs_02']
                                is_cs = (fthg == 0 and ftag == 2)
                            elif cs_code == 'cs_12':
                                back_prob = float(prob_matrix[1, 2])
                                back_odds = est_odds['bookie_cs_12']
                                is_cs = (fthg == 1 and ftag == 2)
                            
                            model_prob = 1.0 - back_prob
                            bookie_odds = 1.0 / (1.0 - 1.0/back_odds) if (back_odds > 1.0001) else np.nan
                            bet_won = not is_cs
                    elif mkt == 'win_to_nil_home':
                        bookie_odds = odds_win_to_nil_h
                        model_prob = sum(float(prob_matrix[i, 0]) for i in range(1, min(6, max_goals + 1)))
                        bet_won = (fthg > ftag and ftag == 0)
                    elif mkt == 'win_to_nil_away':
                        bookie_odds = odds_win_to_nil_a
                        model_prob = sum(float(prob_matrix[0, j]) for j in range(1, min(6, max_goals + 1)))
                        bet_won = (ftag > fthg and fthg == 0)
                    elif mkt == 'corners_1':
                        bookie_odds = odds_corners_h
                        model_prob = corners_probs['corners_1']
                        bet_won = (row.get('HC', 0) > row.get('AC', 0)) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                    elif mkt == 'corners_x':
                        bookie_odds = odds_corners_d
                        model_prob = corners_probs['corners_x']
                        bet_won = (row.get('HC', 0) == row.get('AC', 0)) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                    elif mkt == 'corners_2':
                        bookie_odds = odds_corners_a
                        model_prob = corners_probs['corners_2']
                        bet_won = (row.get('HC', 0) < row.get('AC', 0)) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                    elif mkt.startswith('corners_over_'):
                        line = float(mkt.replace('corners_over_', '')) / 10.0
                        line_str = mkt.replace('corners_over_', '')
                        bookie_odds = row.get(f'odds_corners_over_{line_str}')
                        model_prob = corners_probs['corners_over'](line)
                        bet_won = (row.get('HC', 0) + row.get('AC', 0) > line) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                    elif mkt.startswith('corners_under_'):
                        line = float(mkt.replace('corners_under_', '')) / 10.0
                        line_str = mkt.replace('corners_under_', '')
                        bookie_odds = row.get(f'odds_corners_under_{line_str}')
                        model_prob = corners_probs['corners_under'](line)
                        bet_won = (row.get('HC', 0) + row.get('AC', 0) < line) if not pd.isna(row.get('HC')) and not pd.isna(row.get('AC')) else False
                    elif mkt in ('sh_home', 'sh_draw', 'sh_away') or mkt.startswith('sh_over_') or mkt.startswith('sh_under_'):
                        lambda_h_2h = lambda_home * 0.55
                        lambda_a_2h = lambda_away * 0.55
                        home_probs_2h = [math.exp(-lambda_h_2h) * (lambda_h_2h**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
                        away_probs_2h = [math.exp(-lambda_a_2h) * (lambda_a_2h**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
                        prob_matrix_2h = np.outer(home_probs_2h, away_probs_2h)
                        tau_00_2h = 1.0 - lambda_h_2h * lambda_a_2h * rho
                        tau_10_2h = 1.0 + lambda_a_2h * rho
                        tau_01_2h = 1.0 + lambda_h_2h * rho
                        tau_11_2h = 1.0 - rho
                        prob_matrix_2h[0, 0] *= max(0.0, tau_00_2h)
                        prob_matrix_2h[1, 0] *= max(0.0, tau_10_2h)
                        prob_matrix_2h[0, 1] *= max(0.0, tau_01_2h)
                        prob_matrix_2h[1, 1] *= max(0.0, tau_11_2h)
                        matrix_sum_2h = np.sum(prob_matrix_2h)
                        if matrix_sum_2h > 0:
                            prob_matrix_2h = prob_matrix_2h / matrix_sum_2h
                            
                        if mkt == 'sh_home':
                            bookie_odds = odds_h_2h
                            model_prob = float(np.sum(np.tril(prob_matrix_2h, -1)))
                            bet_won = (fthg - hthg > ftag - htag)
                        elif mkt == 'sh_draw':
                            bookie_odds = odds_d_2h
                            model_prob = float(np.sum(np.diag(prob_matrix_2h)))
                            bet_won = (fthg - hthg == ftag - htag)
                        elif mkt == 'sh_away':
                            bookie_odds = odds_a_2h
                            model_prob = float(np.sum(np.triu(prob_matrix_2h, 1)))
                            bet_won = (fthg - hthg < ftag - htag)
                        elif mkt.startswith('sh_over_'):
                            line = float(mkt.replace('sh_over_', '')) / 10.0
                            line_str = mkt.replace('sh_over_', '')
                            bookie_odds = row.get(f'Over_2H_{line_str[0]}_{line_str[1]}')
                            model_prob = sum(prob_matrix_2h[x, y] for x in range(max_goals + 1) for y in range(max_goals + 1) if x + y > line)
                            bet_won = ((fthg - hthg) + (ftag - htag) > line)
                        elif mkt.startswith('sh_under_'):
                            line = float(mkt.replace('sh_under_', '')) / 10.0
                            line_str = mkt.replace('sh_under_', '')
                            bookie_odds = row.get(f'Under_2H_{line_str[0]}_{line_str[1]}')
                            model_prob = sum(prob_matrix_2h[x, y] for x in range(max_goals + 1) for y in range(max_goals + 1) if x + y < line)
                            bet_won = ((fthg - hthg) + (ftag - htag) < line)
                    elif mkt.startswith('ht_over') and mkt not in ('ht_over05', 'ht_over15'):
                        line = float(mkt.replace('ht_over', '')) / 10.0
                        line_str = mkt.replace('ht_over', '')
                        bookie_odds = row.get(f'Over_HT_{line_str[0]}_{line_str[1]}')
                        model_prob = sum(prob_matrix_ht[x, y] for x in range(max_goals + 1) for y in range(max_goals + 1) if x + y > line)
                        bet_won = (hthg + htag > line)
                    elif mkt.startswith('ht_under') and mkt not in ('ht_under05', 'ht_under15'):
                        line = float(mkt.replace('ht_under', '')) / 10.0
                        line_str = mkt.replace('ht_under', '')
                        bookie_odds = row.get(f'Under_HT_{line_str[0]}_{line_str[1]}')
                        model_prob = sum(prob_matrix_ht[x, y] for x in range(max_goals + 1) for y in range(max_goals + 1) if x + y < line)
                        bet_won = (hthg + htag < line)
                            
                model_prob = float(model_prob)
                
                # Assemble ML Features
                elo_diff = float(elo_factor_h - elo_factor_a)
                features = [
                    float(lambda_home), float(lambda_away),
                    float(h_att), float(h_def), float(a_att), float(a_def),
                    elo_diff, model_prob,
                    float(h_xg_att), float(h_xg_def), float(a_xg_att), float(a_xg_def),
                    float(rest_days_home), float(rest_days_away),
                    float(motivation_home), float(motivation_away)
                ]
                
                # 1. Ensemble Blending (Stacking or fallback 50/50)
                poisson_prob = model_prob  # saved for stacking history
                ml_prob = None
                if use_ml and mkt in self.ml_ensembles and self.ml_ensembles[mkt].is_fitted:
                    ml_prob = self.ml_ensembles[mkt].predict_proba(features)
                    if ml_prob is not None:
                        if mkt in self.stacking_learners and self.stacking_learners[mkt].fitted:
                            model_prob = self.stacking_learners[mkt].predict(poisson_prob, ml_prob)
                        else:
                            model_prob = (poisson_prob + ml_prob) / 2.0

                raw_prob = model_prob

                # 2. Apply Platt Calibration
                if mkt in self.calibrators:
                    model_prob = self.calibrators[mkt].calibrate(model_prob)
                    
                # 3. Store ML history (features are pre-game, no leak)
                if use_ml:
                    self.ml_history[mkt]['X'].append(features)
                    self.ml_history[mkt]['y'].append(1 if bet_won else 0)
                
                # NOTE: calibration_history appended AFTER betting evaluation
                # to prevent temporal leak.

                _exstats["markets_evaluated_total"] += 1

                if not pd.isna(bookie_odds) and bookie_odds > 1.0:
                    if min_odds <= bookie_odds <= max_odds:
                        effective_odds = bookie_odds * compute_slippage_factor(bookie_odds, mkt, slippage_base_pct, league_code)
                        expected_value = model_prob * effective_odds
                        if expected_value >= value_threshold:
                            return effective_odds, model_prob, expected_value, bet_won
                        else:
                            _exstats["markets_skipped_ev"] += 1
                    else:
                        _exstats["markets_skipped_filter"] += 1
                else:
                    _exstats["markets_skipped_nan"] += 1
                # 3b. NOW store calibration history (after betting decision)
                self.calibration_history[mkt]['probs'].append(raw_prob)
                self.calibration_history[mkt]['outcomes'].append(1 if bet_won else 0)

                # 3c. Store stacking history (poisson + xgb → outcome)
                if use_ml and ml_prob is not None:
                    self.stacking_history[mkt]['poisson'].append(poisson_prob)
                    self.stacking_history[mkt]['xgb'].append(ml_prob)
                    self.stacking_history[mkt]['outcomes'].append(1 if bet_won else 0)
                return None
                
            # Run parallel updates
            def process_bet_on_state(state_ref, p_mkt, p_odds, p_prob, p_ev, p_won, staking_rule, stake_value):
                date_str_check = match_date.strftime('%Y-%m-%d')
                state_ref['daily_bet_count'][date_str_check] += 1
                n_bets_today = state_ref['daily_bet_count'][date_str_check]
                
                if staking_rule == 'fixed':
                    p_stake = stake_value
                elif staking_rule == 'proportional':
                    p_stake = state_ref['bankroll'] * (stake_value / 100.0)
                elif staking_rule == 'kelly':
                    if p_mkt.startswith('lay_'):
                        p_f_star = p_prob / (p_odds - 1.0) - (1.0 - p_prob) if p_odds > 1.001 else 0.0
                    else:
                        p_f_star = (p_prob * p_odds - 1.0) / (p_odds - 1.0)
                    p_f_star = max(0.0, p_f_star)
                    p_stake = state_ref['bankroll'] * p_f_star * stake_value
                    cap_pct = compute_edge_scaled_cap(p_prob, p_odds, p_mkt, max_cap_pct=10.0)
                    p_stake = min(p_stake, state_ref['bankroll'] * cap_pct / 100.0)
                else:
                    p_stake = 0.0

                # Liquidity cap by league tier × market type (all methods)
                if staking_rule != 'fixed' and p_stake > 0:
                    liq_cap_pct = get_liquidity_max_stake(league_code, p_mkt, base_stake_pct=10.0)
                    p_stake = min(p_stake, state_ref['bankroll'] * liq_cap_pct / 100.0)

                if staking_rule != 'fixed':
                    if n_bets_today > 1:
                        p_stake = p_stake / math.sqrt(n_bets_today)

                    if state_ref['daily_exposure'][date_str_check] + p_stake > state_ref['bankroll'] * 0.10:
                        p_stake = max(0, state_ref['bankroll'] * 0.10 - state_ref['daily_exposure'][date_str_check])

                # Apply drawdown circuit breaker
                dd_mult = compute_drawdown_multiplier(state_ref['bankroll'], state_ref['peak_bankroll'])
                if dd_mult < 1.0:
                    p_stake = p_stake * dd_mult

                if p_stake > 0.01 and state_ref['bankroll'] >= p_stake:
                    _exstats["bets_placed"] += 1
                    state_ref['daily_exposure'][date_str_check] += p_stake
                    state_ref['total_staked'] += p_stake
                    state_ref['total_bets'] += 1
                    
                    if isinstance(p_won, bool):
                        multiplier = 1.0 if p_won else -1.0
                    else:
                        multiplier = float(p_won)

                    if multiplier > 0:
                        if p_mkt.startswith('lay_'):
                            p_profit = p_stake * multiplier
                        else:
                            p_profit = p_stake * (p_odds - 1.0) * multiplier
                        state_ref['bankroll'] += p_profit
                        if multiplier == 1.0:
                            state_ref['wins'] += 1
                    elif multiplier < 0:
                        if p_mkt.startswith('lay_'):
                            p_profit = p_stake * (p_odds - 1.0) * multiplier
                        else:
                            p_profit = p_stake * multiplier
                        state_ref['bankroll'] += p_profit
                    else:
                        p_profit = 0.0

                    # Track peak bankroll for drawdown circuit breaker
                    if state_ref['bankroll'] > state_ref['peak_bankroll']:
                        state_ref['peak_bankroll'] = state_ref['bankroll']


                    p_clv = None
                    p_closing_odd = None
                    if p_mkt in ('home', '1x2_home'): p_closing_odd = closing_odds_h
                    elif p_mkt in ('away', '1x2_away'): p_closing_odd = closing_odds_a
                    elif p_mkt in ('draw', '1x2_draw'): p_closing_odd = closing_odds_d
                    elif p_mkt == 'over25': p_closing_odd = closing_odds_over25
                    elif p_mkt == 'under25': p_closing_odd = closing_odds_under25
                    if p_closing_odd and not pd.isna(p_closing_odd) and p_closing_odd > 1.0:
                        p_clv = (p_odds / p_closing_odd - 1.0) * 100
                        
                    state_ref['bets_for_ai'].append({
                        'date': match_date.strftime('%Y-%m-%d'),
                        'league': league_code,
                        'home_team': home_team,
                        'away_team': away_team,
                        'score': f"{int(fthg)}-{int(ftag)}",
                        'market': p_mkt,
                        'odds': round(p_odds, 2),
                        'prob': round(p_prob * 100, 1),
                        'ev': round(p_ev, 2),
                        'stake': round(p_stake, 2),
                        'profit': round(p_profit, 2),
                        'bankroll': round(state_ref['bankroll'], 2),
                        'clv': round(p_clv, 2) if p_clv is not None else None,
                        # Cross-market odds (used by AI optimizer to simulate cross-market filters)
                        'odds_h': round(float(odds_h), 2) if odds_h is not None and not pd.isna(odds_h) else None,
                        'odds_d': round(float(odds_d), 2) if odds_d is not None and not pd.isna(odds_d) else None,
                        'odds_a': round(float(odds_a), 2) if odds_a is not None and not pd.isna(odds_a) else None,
                        'odds_over25': round(float(odds_over25), 2) if odds_over25 is not None and not pd.isna(odds_over25) else None,
                        'odds_under25': round(float(odds_under25), 2) if odds_under25 is not None and not pd.isna(odds_under25) else None,
                    })

            if match_date <= end_dt:
                if scan_type == 'markets':
                    for mkt in markets_list:
                        res = eval_market(mkt)
                        if res:
                            process_bet_on_state(states[mkt], mkt, res[0], res[1], res[2], res[3], staking_rule, stake_value)
                elif scan_type == 'leagues':
                    for mkt in markets_list:
                        res = eval_market(mkt)
                        if res and league_code in states:
                            process_bet_on_state(states[league_code], mkt, res[0], res[1], res[2], res[3], staking_rule, stake_value)
                elif scan_type == 'combinations':
                    for mkt in markets_list:
                        res = eval_market(mkt)
                        if res:
                            k = f"{league_code}|{mkt}"
                            if k in states:
                                process_bet_on_state(states[k], mkt, res[0], res[1], res[2], res[3], staking_rule, stake_value)
                elif scan_type == 'staking':
                    for mkt in markets_list:
                        res = eval_market(mkt)
                        if res:
                            k = f"{league_code}|{mkt}"
                            if k in states:
                                for method, cfg in STAKING_CONFIGS.items():
                                    process_bet_on_state(
                                        states[k][method], mkt,
                                        res[0], res[1], res[2], res[3],
                                        cfg['staking_rule'], cfg['stake_value']
                                    )

            self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                              league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                              team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                              league_home_sot, league_away_sot, hst, ast,
                              team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                              league_home_xg, league_away_xg, hxg, axg,
                              team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                              league_home_goals_ht, league_away_goals_ht, hthg, htag)
                              
            self._update_corners_form(team_home_corners_for, team_home_corners_against,
                                  team_away_corners_for, team_away_corners_against,
                                  league_home_corners, league_away_corners,
                                  league_code, home_team, away_team,
                                  row.get("HC"), row.get("AC"))
            # Fit Calibration Periodically
            # NOTE: threshold raised from 50 → 200 (same fix as run() method)
            self.matches_since_calibration += 1
            if not models_frozen and self.matches_since_calibration >= 100:
                self.matches_since_calibration = 0
                for c_mkt, hist in self.calibration_history.items():
                    if len(hist['probs']) > 2000:
                        hist['probs'] = hist['probs'][-2000:]
                        hist['outcomes'] = hist['outcomes'][-2000:]
                    if len(hist['probs']) >= 500:  # raised from 200 → 500 to prevent temporal leak on small samples
                        if c_mkt not in self.calibrators:
                            self.calibrators[c_mkt] = IsotonicCalibrator(epochs=200)
                        self.calibrators[c_mkt].fit(hist['probs'], hist['outcomes'])
                        
            # Fit ML Ensemble Periodically
            if use_ml and not models_frozen:
                self.matches_since_ml_fit += 1
            if not models_frozen and self.matches_since_ml_fit >= 300:
                self.matches_since_ml_fit = 0
                for c_mkt, hist in self.ml_history.items():
                    if len(hist['X']) > 3000:
                        hist['X'] = hist['X'][-3000:]
                        hist['y'] = hist['y'][-3000:]
                    if len(hist['X']) >= 200:  # aligned with MLEnsemble.MIN_SAMPLES_TO_FIT
                        if c_mkt not in self.ml_ensembles:
                            self.ml_ensembles[c_mkt] = MLEnsemble(c_mkt)
                        self.ml_ensembles[c_mkt].fit(hist['X'], hist['y'])

            # Fit Stacking Meta-Learner Periodically
            if use_ml and not models_frozen:
                self.matches_since_stacking_fit += 1
            if not models_frozen and self.matches_since_stacking_fit >= 500:
                self.matches_since_stacking_fit = 0
                for s_mkt, s_hist in self.stacking_history.items():
                    if len(s_hist['poisson']) > 4000:
                        s_hist['poisson'] = s_hist['poisson'][-4000:]
                        s_hist['xgb'] = s_hist['xgb'][-4000:]
                        s_hist['outcomes'] = s_hist['outcomes'][-4000:]
                    if len(s_hist['poisson']) >= 200:
                        if s_mkt not in self.stacking_learners:
                            self.stacking_learners[s_mkt] = StackingMetaLearner(s_mkt)
                        self.stacking_learners[s_mkt].history = s_hist
                        self.stacking_learners[s_mkt].fit()
            if not models_frozen:
                elo_tracker.update(home_team, away_team, int(fthg), int(ftag))

            rho_data = league_goals_for_rho[league_code]
            rho_data['h'].append(int(fthg))
            rho_data['a'].append(int(ftag))
            rho_data['lh'].append(lambda_home if 'lambda_home' in dir() else 1.3)
            rho_data['la'].append(lambda_away if 'lambda_away' in dir() else 1.0)
            if len(rho_data['h']) % RHO_CACHE_INVALIDATION_MATCHES == 0:
                league_rho_cache.pop(league_code, None)
        if scan_type == 'staking':
            total_bets = sum(
                sub['total_bets']
                for state in states.values()
                for sub in state.values()
            )
        else:
            total_bets = sum(state['total_bets'] for state in states.values())
        self.last_scan_diagnostics["total_bets_placed"] = total_bets
        result = compile_parallel_scan_summary(
            states, initial_bankroll, value_threshold, staking_rule, stake_value,
            scan_type=scan_type
        )
        result["exclusion_stats"] = _exstats
        return result

    def _update_form(self, *args, **kwargs):
        return update_form(*args, **kwargs)

    def _calculate_xg_ratings(self, *args, **kwargs):
        return calculate_xg_ratings(*args, rolling_games=self.rolling_games, **kwargs)

    def _calculate_motivation(self, *args, **kwargs):
        return calculate_motivation(*args, **kwargs)

    def _compute_match_probabilities(self, team_home_scored, team_home_conceded,
        team_away_scored, team_away_conceded, league_home_goals, league_away_goals,
        team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
        league_home_sot, league_away_sot, team_home_xg, team_home_xg_conceded,
        team_away_xg, team_away_xg_conceded, league_home_xg, league_away_xg,
        team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht,
        team_away_conceded_ht, league_home_goals_ht, league_away_goals_ht,
        home_team, away_team, league_code, _decay, league_rho_cache,
        league_goals_for_rho, elo_tracker, max_goals=8):
        """Compute all match probabilities via unified ProbabilityPipeline.

        Delegates to ProbabilityPipeline.compute_all() — the single source of truth
        for run() and run_parallel_scan().
        """
        return self.probability_pipeline.compute_all(
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
        ).to_dict()

    @staticmethod
    def _update_corners_form(team_home_corners_for, team_home_corners_against,
                             team_away_corners_for, team_away_corners_against,
                             league_home_corners, league_away_corners,
                             league_code, home_team, away_team, hc, ac):
        """Track rolling corners data after each match."""
        if not pd.isna(hc) and not pd.isna(ac):
            team_home_corners_for[home_team].append(int(hc))
            team_home_corners_against[home_team].append(int(ac))
            team_away_corners_for[away_team].append(int(ac))
            team_away_corners_against[away_team].append(int(hc))
            league_home_corners[league_code].append(int(hc))
            league_away_corners[league_code].append(int(ac))
