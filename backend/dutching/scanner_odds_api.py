"""
Módulo A — Scanner The Odds API (CS Real).

Pipeline dedicado usando odds REAIS de Correct Score da The Odds API v4.
Mercados: h2h, totals, correct_score.
Bookmakers: 1xBet e Pinnacle (filtrados).

Quando o bookmaker tem CS odds reais → odds_source_type='real'.
Quando não tem → fallback com estimate_bookmaker_odds() → odds_source_type='estimated'.
"""

import os
import logging
import requests
import numpy as np
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from backend.models import estimate_bookmaker_odds
from backend.probability_pipeline import predict_match_nb
from backend.api_utils import retry_with_backoff
from backend.data_loader import (
    load_league_data, DATA_DIR, auto_detect_data_source
)

from ..odds_api_mappings import SPORT_TO_LEAGUE as SPORT_LEAGUE_MAP

from .core import (
    BRAZIL_TZ,
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
    STRATEGY_LABELS,
)


def _get_odds_api_token():
    """Read The Odds API key from config file."""
    import json
    config_path = os.path.join(DATA_DIR, 'odds_api_config.json')
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                return cfg.get('api_key', '').strip()
        except Exception:
            pass
    return ''


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


def _find_closest_team(api_name, all_teams_local):
    """Match API team name to local historical data team name."""
    api_name_lower = api_name.lower()
    for t in all_teams_local:
        if t.lower() in api_name_lower or api_name_lower in t.lower():
            return t
    return None


def fetch_odds_api_opportunities(api_key=None, strategy='auto_ia',
                                 data_source='auto', futpython_api_key=''):
    """
    Scan the The Odds API for Dutching opportunities with REAL Correct Score odds.

    Pipeline:
    1. Fetch matches from The Odds API v4 (h2h + totals + correct_score)
    2. For each match with H2H + totals, extract CS odds (real or estimated)
    3. Predict match via NB model → classify profile → build Dutching
    4. Bootstrap edge → quality score → opportunity dict

    Returns list of opportunity dicts, sorted by raw_edge descending.
    """
    if not api_key:
        api_key = os.getenv('THE_ODDS_API_KEY') or _get_odds_api_token()

    opportunities = []
    REGIONS = 'eu,uk,us'
    MARKETS = 'h2h,totals,correct_score'
    headers = {'User-Agent': 'Mozilla/5.0'}

    @retry_with_backoff(max_retries=2, base_delay=0.5)
    def _get_odds(url):
        return requests.get(url, headers=headers, timeout=8)

    if not api_key or api_key == 'test':
        return [{
            'error': 'no_api_key',
            'message': ('API key da The Odds API não configurada. '
                        'Obtenha uma em https://the-odds-api.com e configure '
                        'THE_ODDS_API_KEY no ambiente ou em data/odds_api_config.json.')
        }]

    # ── 1. Fetch live matches from API ────────────────────────────────
    matches_found = []
    api_errors = []

    for sport_key, league_code in SPORT_LEAGUE_MAP.items():
        url = (f'https://api.the-odds-api.com/v4/sports/{sport_key}/odds/'
               f'?apiKey={api_key}&regions={REGIONS}&markets={MARKETS}')
        try:
            response = _get_odds(url)
            if response.status_code == 200:
                data = response.json()
                for m in data:
                    m['_league_code'] = league_code
                matches_found.extend(data)
            elif response.status_code == 401:
                try:
                    body = response.json()
                    error_code = body.get('error_code', '')
                except Exception:
                    error_code = ''
                if error_code == 'OUT_OF_USAGE_CREDITS':
                    api_errors.append('Créditos da The Odds API esgotados. O plano gratuito renova mensalmente.')
                else:
                    api_errors.append('Chave de API inválida (HTTP 401). Verifique THE_ODDS_API_KEY.')
                break
            else:
                api_errors.append(f'{sport_key}: HTTP {response.status_code}')
        except Exception as e:
            logger.error(f"Erro ao buscar Odds API para {sport_key}: {e}", exc_info=True)

    if api_errors and not matches_found:
        return [{'error': 'api_error', 'message': api_errors[0]}]

    if not matches_found:
        return []

    # ── 2. Lazy-load historical data per league ────────────────────
    needed_leagues = set(m['_league_code'] for m in matches_found)
    leagues_data = {}
    for lc in needed_leagues:
        df = _load_league_data_lazy(lc, data_source, futpython_api_key)
        if df is not None:
            leagues_data[lc] = df

    # ── 3. Process each match ─────────────────────────────────────
    for match in matches_found:
        sport_key = match.get('sport_key')
        league_code = SPORT_LEAGUE_MAP.get(sport_key)
        if not league_code or league_code not in leagues_data:
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

        # ── Collect odds from bookmakers ──────────────────────────
        odds_data = {}

        for bookie in match.get('bookmakers', []):
            title = bookie.get('title')
            bookie_last_update = bookie.get('last_update')
            h2h = {}
            h2h_lay = {}
            totals_by_point = {}
            cs_odds_raw = {}

            for market in bookie.get('markets', []):
                key = market.get('key')
                if key == 'h2h':
                    for outcome in market.get('outcomes', []):
                        h2h[outcome.get('name')] = outcome.get('price')
                elif key == 'h2h_lay':
                    for outcome in market.get('outcomes', []):
                        h2h_lay[outcome.get('name')] = outcome.get('price')
                elif key == 'totals':
                    for outcome in market.get('outcomes', []):
                        point = outcome.get('point')
                        if point is not None:
                            if point not in totals_by_point:
                                totals_by_point[point] = {}
                            totals_by_point[point][outcome.get('name')] = outcome.get('price')
                elif key == 'correct_score':
                    for outcome in market.get('outcomes', []):
                        score_name = outcome.get('name')
                        if score_name:
                            cs_odds_raw[score_name] = outcome.get('price')

            # Pick point closest to 2.5
            best_totals = {}
            best_totals_point = None
            best_dist = 999
            for point, outcomes in totals_by_point.items():
                if len(outcomes) == 2:
                    dist = abs(point - 2.5)
                    if dist < best_dist:
                        best_dist = dist
                        best_totals_point = point
                        best_totals = outcomes

            has_h2h = len(h2h) == 3
            has_totals = len(best_totals) == 2

            if has_h2h and has_totals:
                use_lay = len(h2h_lay) == 3
                cs_mapped = {}
                if cs_odds_raw:
                    for score_name, price in cs_odds_raw.items():
                        key_cs = f"bookie_cs_{score_name.replace('-', '')}"
                        if price and price > 1.0:
                            cs_mapped[key_cs] = float(price)

                odds_data[title] = {
                    'h2h': h2h_lay if use_lay else h2h,
                    'totals': best_totals,
                    'totals_point': best_totals_point,
                    'is_exchange': use_lay,
                    'cs_odds': cs_mapped,
                    'has_real_cs': len(cs_mapped) >= 6,
                    'last_update': bookie_last_update,
                }

        # Filter only 1xBet and Pinnacle
        odds_data = {k: v for k, v in odds_data.items() if k.lower() in ('1xbet', 'pinnacle')}

        if not odds_data:
            continue

        hist_df = leagues_data[league_code]
        all_teams_local = list(set(hist_df['HomeTeam'].tolist() + hist_df['AwayTeam'].tolist()))

        home_team_local = _find_closest_team(home_team, all_teams_local)
        away_team_local = _find_closest_team(away_team, all_teams_local)

        if not home_team_local or not away_team_local:
            continue

        try:
            pred = predict_match_nb(home_team_local, away_team_local, hist_df, datetime.now())
            if not pred or 'lambda_home' not in pred:
                continue
        except Exception:
            continue

        for bookie, data in odds_data.items():
            o25_odd = data['totals'].get('Over')
            u25_odd = data['totals'].get('Under')
            o25_point = data.get('totals_point', 2.5)
            is_exchange = data.get('is_exchange', False)
            real_cs = data.get('cs_odds', {})
            has_real_cs = data.get('has_real_cs', False)

            # ── Odds staleness check ──────────────────────────────
            odds_stale_hours = None
            odds_last_update_str = None
            last_upd = data.get('last_update')
            if last_upd:
                try:
                    upd_dt = datetime.strptime(last_upd, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    odds_stale_hours = (datetime.now(timezone.utc) - upd_dt).total_seconds() / 3600.0
                    odds_last_update_str = upd_dt.astimezone(BRAZIL_TZ).strftime("%d/%m %H:%M")
                except Exception:
                    pass

            if not o25_odd or not u25_odd:
                continue

            # ── Determine odds source ─────────────────────────────
            if has_real_cs:
                cs_odds = real_cs
                odds_source_type = 'real'
            else:
                try:
                    cs_odds = estimate_bookmaker_odds(
                        o25_odd, u25_odd, pred['lambda_home'], pred['lambda_away'],
                        pred.get('rho'), bookmaker=bookie,
                        btts_yes_odd=None, btts_no_odd=None)
                except Exception:
                    continue
                odds_source_type = 'estimated'

                if abs(o25_point - 2.5) > 0.01 and 'bookie_over_25' not in cs_odds:
                    cs_odds['total_point'] = o25_point

            # ── Build Dutching ────────────────────────────────────
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

                game_profile = classify_game_profile(
                    pred, is_home_fav,
                    market_ou_odds=(o25_odd, u25_odd) if o25_odd and u25_odd else None,
                    league_code=league_code
                )

                # Use adaptive kelly fraction: 0.25 for real CS, 0.15 for estimated
                kelly_frac = 0.25 if odds_source_type == 'real' else 0.15

                edge_ci = bootstrap_dutching_edge(
                    pred, cs_odds, strategy=current_strat,
                    max_legs=8, max_overround=0.92, min_selections=3,
                    n_bootstrap=150, is_home_fav=is_home_fav,
                    odds_source_type=odds_source_type,
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
                    has_real_odds=has_real_cs,
                    hours_to_kickoff=hours_to_kickoff,
                    odds_stale_hours=odds_stale_hours,
                )

                # Kelly stake recommendation
                bankroll = 1000.0  # default, user can override via recalculate
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

                opportunities.append({
                    'match': match_name,
                    'date': match_date,
                    'match_date_sort': match_time_local.strftime("%Y-%m-%d"),
                    'match_time_sort': match_time_local.strftime("%H:%M"),
                    'bookmaker': bookie,
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
                    'odds_stale_hours': round(odds_stale_hours, 1) if odds_stale_hours is not None else None,
                    'odds_last_update': odds_last_update_str,
                    'possibly_postponed': (odds_stale_hours is not None and odds_stale_hours > 8),
                    'edge_ci_95': edge_ci.get('edge_ci_95'),
                    'edge_ci_80': edge_ci.get('edge_ci_80'),
                    'edge_prob_positive': edge_ci.get('prob_positive'),
                    'quality_score': quality['score'],
                    'quality_verdict': quality['verdict'],
                    'quality_verdict_label': quality['verdict_label'],
                    'quality_verdict_color': quality['verdict_color'],
                    'quality_verdict_icon': quality['verdict_icon'],
                    'quality_breakdown': quality['breakdown'],
                    'odds_source_type': odds_source_type,
                    # New fields for full recalculation context
                    'home_team': home_team,
                    'away_team': away_team,
                    'league_code': league_code,
                    'commence_time': dt,
                    'kelly_stake': stake_rec,
                    'bankroll_simulation': bankroll_sim,
                })

    opportunities.sort(key=lambda x: x['raw_edge'], reverse=True)
    return opportunities
