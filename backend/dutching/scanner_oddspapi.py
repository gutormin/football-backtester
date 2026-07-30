"""
Módulo B — Scanner OddsPapi (CS Estimado).

Pipeline dedicado usando OddsPapi (API que NÃO fornece odds de Correct Score).
Mercado disponível: apenas H2H (Market 101). Sem totals, sem CS.

Estratégia: estimar CS odds via estimate_bookmaker_odds() a partir do
modelo NB + calibração de liga. TODAS as odds são marcadas como
odds_source_type='estimated'.

Inclui ajustes conservadores:
- Kelly fraction reduzida (0.15 vs 0.25 do Módulo A)
- Bootstrap com inflação de incerteza (+30% edge_std)
"""

import os
import logging
import numpy as np
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from backend.models import estimate_bookmaker_odds
from backend.probability_pipeline import predict_match_nb
from backend.data_loader import load_league_data, auto_detect_data_source

from ..oddspapi_client import fetch_oddspapi_matches

from .core import (
    BRAZIL_TZ,
    ALL_DUTCH_SCORES,
    SCORE_GROUPS,
    STRATEGY_LABELS,
    resolve_strategy,
    classify_game_profile,
    build_dynamic_dutch,
    get_selections_and_alternatives,
    bootstrap_dutching_edge,
    dutching_quality_score,
    dutching_stake_recommendation,
    bankroll_simulation,
    evaluate_alternatives,
    _hours_until_match,
    _guess_league_from_teams,
    _get_league_avg_goals,
    LEAGUE_STD_GOALS,
    _score_to_key,
)


def _load_league_data_lazy(league_code, data_source='auto', futpython_api_key=''):
    """Lazy-load historical data for a single league."""
    try:
        ds = data_source if data_source != 'auto' else auto_detect_data_source(league_code)
        df = load_league_data(league_code, start_date='2020-08-01', data_source=ds, api_key=futpython_api_key)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None


def _estimate_cs_odds_from_model(pred, league_code=None):
    """Estimate CS odds purely from the NB model, calibrated to league average.

    When OddsPapi has no O/U market, we estimate CS odds from the model's
    probability matrix directly. Each CS odd = 1 / prob_matrix[i,j] adjusted
    by a league calibration factor to match typical overround.
    """
    prob_matrix = pred.get('prob_matrix')
    if prob_matrix is None:
        return {}

    league_avg = _get_league_avg_goals(league_code)
    lambda_total = pred.get('lambda_home', 1.2) + pred.get('lambda_away', 1.0)
    league_z = (lambda_total - league_avg) / LEAGUE_STD_GOALS if LEAGUE_STD_GOALS > 0 else 0

    # Calibration factor: adjust model probs to match typical bookmaker margin
    # When model expects MORE goals than league avg → slightly inflate odds for
    # high scores (market is less efficient there)
    calibration = 1.0 + max(-0.10, min(0.15, league_z * 0.05))

    cs_odds = {}
    max_g = min(8, prob_matrix.shape[0] - 1, prob_matrix.shape[1] - 1)
    for i in range(max_g + 1):
        for j in range(max_g + 1):
            score_key = _score_to_key(f"{i}-{j}")
            prob = float(prob_matrix[i, j])
            if prob > 0.001:
                # Fair odd = 1/prob, then apply overround and calibration
                fair_odd = 1.0 / prob
                # Apply ~8% overround (typical for CS market)
                bookmaker_odd = fair_odd / 1.08 * calibration
                cs_odds[score_key] = round(max(1.50, bookmaker_odd), 2)

    return cs_odds


def fetch_oddspapi_opportunities(strategy='auto_ia', data_source='auto',
                                 futpython_api_key=''):
    """
    Scan OddsPapi for Dutching opportunities using ESTIMATED Correct Score odds.

    Pipeline:
    1. Fetch matches from OddsPapi (H2H market only, no CS, no O/U)
    2. Guess league from team names → load historical data
    3. Predict match via NB model
    4. Estimate CS odds from model (Módulo B: pure model-based estimation)
    5. Build Dutching → bootstrap (with inflation) → quality score
    6. Apply conservative adjustments (kelly_fraction=0.15)

    Returns list of opportunity dicts, sorted by raw_edge descending.
    """
    opportunities = []

    # ── 1. Fetch matches from OddsPapi ────────────────────────────
    opapi_matches, opapi_err = fetch_oddspapi_matches()
    if opapi_err:
        return [opapi_err]
    if not opapi_matches:
        return []

    # Map each match to a league with historical data
    valid_matches = []
    for m in opapi_matches:
        lc = _guess_league_from_teams(m.get('home_team', ''), m.get('away_team', ''))
        if lc:
            m['_league_code'] = lc
            valid_matches.append(m)

    if not valid_matches:
        return []

    # ── 2. Lazy-load historical data per league ────────────────────
    needed_leagues = set(m['_league_code'] for m in valid_matches)
    leagues_data = {}
    for lc in needed_leagues:
        df = _load_league_data_lazy(lc, data_source, futpython_api_key)
        if df is not None:
            leagues_data[lc] = df

    # ── 3. Process each match ─────────────────────────────────────
    for match in valid_matches:
        league_code = match['_league_code']
        if league_code not in leagues_data:
            continue

        home_team = match.get('home_team')
        away_team = match.get('away_team')
        match_name = f"{home_team} vs {away_team}"

        dt = match.get('commence_time')
        if not dt:
            continue

        try:
            match_time = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if match_time < datetime.now(timezone.utc):
                continue
            match_time_local = match_time.astimezone(BRAZIL_TZ)
            match_date = match_time_local.strftime("%d/%m/%Y %H:%M")
        except Exception:
            continue

        hist_df = leagues_data[league_code]
        all_teams_local = list(set(hist_df['HomeTeam'].tolist() + hist_df['AwayTeam'].tolist()))

        # Match team names
        def find_team(api_name):
            api_lower = api_name.lower()
            for t in all_teams_local:
                if t.lower() in api_lower or api_lower in t.lower():
                    return t
            return None

        home_local = find_team(home_team)
        away_local = find_team(away_team)
        if not home_local or not away_local:
            continue

        # ── 4. Predict match ──────────────────────────────────────
        try:
            pred = predict_match_nb(home_local, away_local, hist_df, datetime.now())
            if not pred or 'lambda_home' not in pred:
                continue
        except Exception:
            continue

        # ── 5. Estimate CS odds from model (no market O/U available) ──
        cs_odds = _estimate_cs_odds_from_model(pred, league_code)
        if not cs_odds or len(cs_odds) < 10:
            continue

        # Extract H2H odds from bookmakers for market divergence
        h2h_odds = None
        for bookie in match.get('bookmakers', []):
            for market in bookie.get('markets', []):
                if market.get('key') == 'h2h':
                    outs = {o['name']: o['price'] for o in market.get('outcomes', [])}
                    h = outs.get(home_team) or outs.get('Home')
                    a = outs.get(away_team) or outs.get('Away')
                    d = outs.get('Draw')
                    if h and a:
                        h2h_odds = (h, d or 0, a)
                        break
            if h2h_odds:
                break

        # ── 6. Build Dutching ────────────────────────────────────
        is_home_fav = pred['prob_h'] > pred['prob_a']
        current_strat = resolve_strategy(strategy, pred, is_home_fav)
        outcomes_to_cover, sel_probs, odds_to_cover, odds_keys, market_label, prob_combined, dutching_odd, edge = \
            build_dynamic_dutch(pred, cs_odds, strategy=current_strat)

        if outcomes_to_cover is None:
            continue

        if edge > 0:
            label_prefix = "IA " if strategy == 'auto_ia' else ""
            _, alt_scores = get_selections_and_alternatives(pred, outcomes_to_cover, cs_odds)

            alt_scores = evaluate_alternatives(
                outcomes_to_cover,
                [round(o, 2) for o in odds_to_cover],
                prob_combined,
                alt_scores, pred, cs_odds
            )

            # Game profile (without market O/U — estimated odds have no real market)
            game_profile = classify_game_profile(
                pred, is_home_fav,
                market_ou_odds=None,
                league_code=league_code
            )

            # Módulo B: conservative kelly fraction
            kelly_frac = 0.15

            # Bootstrap with inflation for estimated odds
            edge_ci = bootstrap_dutching_edge(
                pred, cs_odds, strategy=current_strat,
                max_legs=8, max_overround=0.92, min_selections=3,
                n_bootstrap=150, is_home_fav=is_home_fav,
                odds_source_type='estimated',  # triggers inflation
            )

            hours_to_kickoff = _hours_until_match(dt)

            quality = dutching_quality_score(
                edge=edge,
                edge_ci_95=edge_ci.get('edge_ci_95'),
                profile_confidence=game_profile['confidence'],
                dutching_odd=dutching_odd,
                n_selections=len(outcomes_to_cover),
                market_divergence=game_profile.get('market_divergence', 0),
                edge_prob_positive=edge_ci.get('prob_positive'),
                edge_std=edge_ci.get('edge_std'),
                has_real_odds=False,  # Module B: always estimated
                hours_to_kickoff=hours_to_kickoff,
                odds_stale_hours=None,  # OddsPapi doesn't report last_update reliably
            )

            # Kelly stake
            bankroll = 1000.0
            stake_rec = dutching_stake_recommendation(
                bankroll=bankroll,
                cum_prob=prob_combined,
                dutching_odd=dutching_odd,
                edge=edge,
                edge_prob_positive=edge_ci.get('prob_positive'),
                kelly_fraction=kelly_frac,
            )

            # Bankroll simulation
            bankroll_sim = bankroll_simulation(
                bankroll=bankroll,
                cum_prob=prob_combined,
                dutching_odd=dutching_odd,
                edge=edge,
                kelly_fraction=kelly_frac,
            )

            # Determine bookmaker name from data
            bookie_name = 'OddsPapi'
            for bm in match.get('bookmakers', []):
                title = bm.get('title', '')
                if title:
                    bookie_name = title
                    break

            opportunities.append({
                'match': match_name,
                'date': match_date,
                'match_date_sort': match_time_local.strftime("%Y-%m-%d"),
                'match_time_sort': match_time_local.strftime("%H:%M"),
                'bookmaker': bookie_name,
                'market': f"{label_prefix}{market_label}",
                'selections': outcomes_to_cover,
                'selections_probs': sel_probs,
                'alternative_scores': alt_scores,
                'odds': [round(o, 2) for o in odds_to_cover],
                'dutching_odd': round(dutching_odd, 2),
                'model_prob': f"{round(prob_combined * 100, 2)}%",
                'edge': f"+{round(edge * 100, 2)}%",
                'raw_edge': edge,
                'game_profile': game_profile['best_profile'],
                'profile_confidence': game_profile['confidence'],
                'profile_scores': game_profile.get('scores', {}),
                'market_divergence': game_profile.get('market_divergence', 0.0),
                'hours_to_kickoff': hours_to_kickoff,
                'odds_stale_hours': None,
                'odds_last_update': None,
                'possibly_postponed': False,
                'edge_ci_95': edge_ci.get('edge_ci_95'),
                'edge_ci_80': edge_ci.get('edge_ci_80'),
                'edge_prob_positive': edge_ci.get('prob_positive'),
                'quality_score': quality['score'],
                'quality_verdict': quality['verdict'],
                'quality_verdict_label': quality['verdict_label'],
                'quality_verdict_color': quality['verdict_color'],
                'quality_verdict_icon': quality['verdict_icon'],
                'quality_breakdown': quality['breakdown'],
                'odds_source_type': 'estimated',
                'odds_source_estimated': True,  # explicit flag for Module B
                # Recalculation context
                'home_team': home_team,
                'away_team': away_team,
                'league_code': league_code,
                'commence_time': dt,
                'kelly_stake': stake_rec,
                'bankroll_simulation': bankroll_sim,
            })

    opportunities.sort(key=lambda x: x['raw_edge'], reverse=True)
    return opportunities
