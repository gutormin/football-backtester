import os
import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from backend.models import estimate_bookmaker_odds
from backend.probability_pipeline import predict_match_nb
from backend.api_utils import retry_with_backoff

import json
from backend.data_loader import load_league_data, get_all_available_leagues, DATA_DIR, get_api_token, load_upcoming_from_api, auto_detect_data_source

def get_odds_api_token():
    config_path = os.path.join(DATA_DIR, 'odds_api_config.json')
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                return cfg.get('api_key', '').strip()
        except Exception:
            pass
    return ''

from .odds_api_mappings import SPORT_TO_LEAGUE as SPORT_LEAGUE_MAP

# ═══════════════════════════════════════════════════════════════════════
# Import all shared functions from the refactored dutching package
# ═══════════════════════════════════════════════════════════════════════
from .dutching.core import (
    ALL_DUTCH_SCORES, SCORE_GROUPS, LEAGUE_AVG_GOALS, LEAGUE_AVG_GOALS_DEFAULT,
    LEAGUE_STD_GOALS, STRATEGY_LABELS, PROFILE_LABELS, QUALITY_VERDICTS,
    _get_league_avg_goals, _solve_lambda_from_under25_fast,
    classify_game_profile, resolve_strategy,
    score_dominance_weight,
    compute_team_dispersions, _estimate_team_alpha, get_team_alphas,
    _score_to_key, _get_score_prob, build_dynamic_dutch,
    get_selections_and_alternatives,
    bootstrap_dutching_edge, _build_bootstrap_matrix,
    dutching_stake_recommendation, _stake_reason, bankroll_simulation,
    _hours_until_match, evaluate_extra_score, dutching_quality_score,
    evaluate_alternatives,
    _guess_league_from_teams, BRAZIL_TZ,
)


def fetch_dutching_opportunities(api_key=None, source='odds_api', strategy='auto_ia', data_source='auto', futpython_api_key=''):
    if not api_key:
        api_key = os.getenv('THE_ODDS_API_KEY') or get_odds_api_token()
    opportunities = []

    def _load_league_data(league_code):
        """Lazy-load historical data for a single league."""
        try:
            ds = data_source if data_source != 'auto' else auto_detect_data_source(league_code)
            df = load_league_data(league_code, start_date='2020-08-01', data_source=ds, api_key=futpython_api_key)
            if not df.empty:
                return df
        except Exception:
            pass
        return None

    # Pré-fetch OddsPapi (fonte alternativa à The Odds API)
    # A OddsPapi retorna jogos no formato compatível; injetamos e reusamos o pipeline.
    _prefetched_matches = None
    if source == 'oddspapi':
        from .oddspapi_client import fetch_oddspapi_matches
        _opapi_matches, _opapi_err = fetch_oddspapi_matches()
        if _opapi_err:
            return [_opapi_err]
        if not _opapi_matches:
            return []
        # Mapear cada match para uma liga com dados históricos, pelos nomes dos times
        for m in _opapi_matches:
            m['sport_key'] = 'soccer_oddspapi'
            m['_league_code'] = _guess_league_from_teams(m.get('home_team', ''), m.get('away_team', ''))
        _prefetched_matches = [m for m in _opapi_matches if m['_league_code']]
        source = 'odds_api'  # reusar o pipeline

    # 1. FONTE: THE ODDS API (Tempo Real Betfair/Bet365)
    if source == 'odds_api':
        REGIONS = 'eu,uk,us'
        MARKETS = 'h2h,totals,correct_score'
        headers = {'User-Agent': 'Mozilla/5.0'}

        @retry_with_backoff(max_retries=2, base_delay=0.5)
        def _get_odds(url):
            return requests.get(url, headers=headers, timeout=8)

        if not api_key or api_key == 'test':
            if _prefetched_matches is None:
                return [{'error': 'no_api_key', 'message': 'API key da The Odds API não configurada. Obtenha uma em https://the-odds-api.com e configure THE_ODDS_API_KEY no ambiente ou em data/odds_api_config.json.'}]

        # Fetch live matches from API first (lightweight), then load data only for leagues with games
        matches_found = []
        api_errors = []
        if _prefetched_matches is not None:
            # Já temos os jogos da OddsPapi
            matches_found = _prefetched_matches
        else:
            for sport_key, league_code in SPORT_LEAGUE_MAP.items():
                url = f'https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={api_key}&regions={REGIONS}&markets={MARKETS}'
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

        # Lazy-load historical data only for leagues that have live matches
        needed_leagues = set(m['_league_code'] for m in matches_found)
        leagues_data = {}
        for lc in needed_leagues:
            df = _load_league_data(lc)
            if df is not None:
                leagues_data[lc] = df

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
                # Converter UTC para horário de Brasília para exibição correta
                match_time_local = match_time.astimezone(BRAZIL_TZ)
                match_date = match_time_local.strftime("%d/%m/%Y %H:%M")
            except:
                continue
                
            # Collect odds from all bookmakers that have h2h + totals
            odds_data = {}  # bookie_title -> {h2h, totals_point, totals_over, totals_under, h2h_lay, cs_odds}

            for bookie in match.get('bookmakers', []):
                title = bookie.get('title')
                bookie_last_update = bookie.get('last_update')  # ISO timestamp UTC
                h2h = {}
                h2h_lay = {}
                totals_by_point = {}  # point -> {name: price}
                cs_odds_raw = {}      # "1-0" -> price, "2-1" -> price, etc.

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
                            score_name = outcome.get('name')  # e.g. "1-0", "2-1"
                            if score_name:
                                cs_odds_raw[score_name] = outcome.get('price')

                # Escolhe o ponto mais proximo de 2.5 com Over/Under completos
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
                    # Map real CS odds to bookie_cs_<score> keys
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

            # Filtrar apenas 1xBet e Pinnacle
            odds_data = {k: v for k, v in odds_data.items() if k.lower() in ('1xbet', 'pinnacle')}

            if not odds_data:
                continue

            hist_df = leagues_data[league_code]
            all_teams_local = list(set(hist_df['HomeTeam'].tolist() + hist_df['AwayTeam'].tolist()))
            
            def find_closest_team(api_name):
                api_name_lower = api_name.lower()
                for t in all_teams_local:
                    if t.lower() in api_name_lower or api_name_lower in t.lower():
                        return t
                return None
                
            home_team_local = find_closest_team(home_team)
            away_team_local = find_closest_team(away_team)
            
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

                # Detectar odds desatualizadas (jogo possivelmente adiado)
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

                # ── Odds source: real CS > estimated ──────────────────
                odds_source_type = 'estimated'
                if has_real_cs:
                    # Use real CS odds directly from API
                    cs_odds = real_cs
                    odds_source_type = 'real'
                else:
                    # Fallback: estimate CS odds from O/U 2.5 market
                    try:
                        cs_odds = estimate_bookmaker_odds(
                            o25_odd, u25_odd, pred['lambda_home'], pred['lambda_away'],
                            pred.get('rho'), bookmaker=bookie,
                            btts_yes_odd=None, btts_no_odd=None)
                    except Exception:
                        continue

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

                    # Decision layer: evaluate alternatives & quality
                    alt_scores = evaluate_alternatives(
                        outcomes_to_cover,
                        [round(o, 2) for o in odds_to_cover],
                        prob_combined,
                        alt_scores, pred, cs_odds
                    )
                    game_profile = classify_game_profile(pred, is_home_fav,
                        market_ou_odds=(o25_odd, u25_odd) if o25_odd and u25_odd else None)
                    edge_ci = bootstrap_dutching_edge(
                        pred, cs_odds, strategy=current_strat,
                        max_legs=8, max_overround=0.92, min_selections=3,
                        n_bootstrap=150, is_home_fav=is_home_fav
                    )
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
                        hours_to_kickoff=_hours_until_match(dt),
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
                        'market_divergence': game_profile.get('market_divergence', 0.0),
                        'hours_to_kickoff': _hours_until_match(dt),
                        'odds_stale_hours': round(odds_stale_hours, 1) if odds_stale_hours is not None else None,
                        'odds_last_update': odds_last_update_str,
                        'possibly_postponed': (odds_stale_hours is not None and odds_stale_hours > 8),
                        'edge_ci_95': edge_ci.get('edge_ci_95'),
                        'edge_prob_positive': edge_ci.get('prob_positive'),
                        'quality_score': quality['score'],
                        'quality_verdict': quality['verdict'],
                        'quality_verdict_label': quality['verdict_label'],
                        'quality_verdict_color': quality['verdict_color'],
                        'quality_verdict_icon': quality['verdict_icon'],
                        'quality_breakdown': quality['breakdown'],
                        'odds_source_type': odds_source_type,
                    })

    # 2. FONTE: API DATAFOOTBALL OU FOOTBALL-DATA CSV (DADOS LOCAIS)
    elif source in ['datafootball', 'csv_fixtures']:
        df_fixtures = pd.DataFrame()
        
        if source == 'datafootball':
            token = get_api_token()
            if token:
                try:
                    df_fixtures = load_upcoming_from_api(token)
                except Exception:
                    pass
                    
        if df_fixtures.empty:
            fixtures_path = os.path.join(DATA_DIR, 'fixtures.csv')
            if os.path.exists(fixtures_path):
                try:
                    df_fixtures = pd.read_csv(fixtures_path, encoding='latin1')
                    df_fixtures.columns = [c.replace('ï»¿', '').replace('\ufeff', '').strip() for c in df_fixtures.columns]
                except Exception:
                    pass
                    
        if df_fixtures.empty:
            return []
            
        # Lazy-load league data on demand (avoids OOM on low-RAM environments)
        _csv_leagues_data = {}

        for row in df_fixtures.to_dict('records'):
            league_code = row.get('Div')
            if not league_code:
                continue

            if league_code not in _csv_leagues_data:
                df = _load_league_data(league_code)
                if df is None:
                    _csv_leagues_data[league_code] = False
                    continue
                _csv_leagues_data[league_code] = df

            hist_df = _csv_leagues_data[league_code]
            if hist_df is False:
                continue

            home_team = row.get('HomeTeam')
            away_team = row.get('AwayTeam')
            if pd.isna(home_team) or pd.isna(away_team):
                continue

            match_name = f"{home_team} vs {away_team}"
            match_date = str(row.get('Date', 'Hoje'))
            raw_date = str(row.get('Date', ''))
            raw_time = str(row.get('Time', ''))
            if row.get('Time'):
                match_date += f" {raw_time}"

            # Parse date for sorting (supports DD/MM/YYYY and YYYY-MM-DD)
            match_date_sort = ''
            match_time_sort = raw_time[:5] if raw_time and raw_time != 'nan' else '00:00'
            for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
                try:
                    parsed = datetime.strptime(raw_date.strip()[:10], fmt)
                    match_date_sort = parsed.strftime('%Y-%m-%d')
                    break
                except (ValueError, IndexError):
                    continue

            # Extrai odds da Bet365 ou Médias da base
            odds_h = float(row.get('B365H', row.get('AvgH', np.nan)))
            odds_d = float(row.get('B365D', row.get('AvgD', np.nan)))
            odds_a = float(row.get('B365A', row.get('AvgA', np.nan)))
            odds_over25 = float(row.get('B365>2.5', row.get('Avg>2.5', np.nan)))
            odds_under25 = float(row.get('B365<2.5', row.get('Avg<2.5', np.nan)))

            if pd.isna(odds_over25) or pd.isna(odds_under25):
                continue
            
            try:
                pred = predict_match_nb(home_team, away_team, hist_df, datetime.now())
                if not pred or 'lambda_home' not in pred:
                    continue
            except Exception:
                continue

            # Calcula estimativa de Correct Score para Bet365
            try:
                est_odds_b365 = estimate_bookmaker_odds(odds_over25, odds_under25, pred['lambda_home'], pred['lambda_away'], pred.get('rho'), bookmaker='Bet365')
            except Exception:
                continue
                
            # Dutching dinâmico baseado em EV individual
            is_home_fav = pred['prob_h'] > pred['prob_a']
            current_strat = resolve_strategy(strategy, pred, is_home_fav)
            outcomes_b365, sel_probs_b365, odds_b365, odds_keys_b365, market_label, prob_combined, dutching_odd, edge = \
                build_dynamic_dutch(pred, est_odds_b365, strategy=current_strat)

            if outcomes_b365 is None:
                continue

            # 2.1 ESTRATÉGIA PARA BET365 (Física)
            if edge > 0:
                label_prefix = "IA " if strategy == 'auto_ia' else ""
                _, alt_scores = get_selections_and_alternatives(pred, outcomes_b365, est_odds_b365)
                alt_scores = evaluate_alternatives(
                    outcomes_b365, [round(o, 2) for o in odds_b365],
                    prob_combined, alt_scores, pred, est_odds_b365
                )
                game_profile = classify_game_profile(pred, is_home_fav,
                    market_ou_odds=(odds_over25, odds_under25))
                edge_ci = bootstrap_dutching_edge(
                    pred, est_odds_b365, strategy=current_strat,
                    n_bootstrap=150, is_home_fav=is_home_fav
                )
                quality = dutching_quality_score(
                    edge=edge, edge_ci_95=edge_ci.get('edge_ci_95'),
                    profile_confidence=game_profile['confidence'],
                    dutching_odd=dutching_odd,
                    n_selections=len(outcomes_b365),
                    market_divergence=game_profile.get('market_divergence', 0),
                    edge_prob_positive=edge_ci.get('prob_positive'),
                    edge_std=edge_ci.get('edge_std'),
                    has_real_odds=False,
                )
                opportunities.append({
                    'match': match_name,
                    'date': match_date,
                    'match_date_sort': match_date_sort,
                    'match_time_sort': match_time_sort,
                    'bookmaker': 'Bet365',
                    'market': f"{label_prefix}{market_label}",
                    'selections': outcomes_b365,
                    'selections_probs': sel_probs_b365,
                    'alternative_scores': alt_scores,
                    'odds': [round(o, 2) for o in odds_b365],
                    'dutching_odd': round(dutching_odd, 2),
                    'model_prob': f"{round(prob_combined * 100, 2)}%",
                    'edge': f"+{round(edge * 100, 2)}%",
                    'raw_edge': edge,
                    'game_profile': game_profile['best_profile'],
                    'profile_confidence': game_profile['confidence'],
                    'edge_ci_95': edge_ci.get('edge_ci_95'),
                    'edge_prob_positive': edge_ci.get('prob_positive'),
                    'quality_score': quality['score'],
                    'quality_verdict': quality['verdict'],
                    'quality_verdict_label': quality['verdict_label'],
                    'quality_verdict_color': quality['verdict_color'],
                    'quality_verdict_icon': quality['verdict_icon'],
                    'quality_breakdown': quality['breakdown'],
                    'odds_source_type': 'estimated',
                })

            # 2.2 ESTRATÉGIA SIMULADA PARA BETFAIR EXCHANGE (+8% de valor de odd)
            odds_betfair = [(odd - 1.0) * 1.08 + 1.0 for odd in odds_b365]
            sum_prob_bf = sum(1.0 / odd for odd in odds_betfair if odd > 1.0)
            if sum_prob_bf > 0:
                dutching_odd_bf = 1.0 / sum_prob_bf
                edge_bf = prob_combined * dutching_odd_bf - 1.0

                if edge_bf > 0.01:
                    label_prefix = "IA " if strategy == 'auto_ia' else ""
                    _, alt_scores = get_selections_and_alternatives(pred, outcomes_b365, est_odds_b365)
                    alt_scores = evaluate_alternatives(
                        outcomes_b365, [round(o, 2) for o in odds_betfair],
                        prob_combined, alt_scores, pred, est_odds_b365
                    )
                    quality = dutching_quality_score(
                        edge=edge_bf, edge_ci_95=None,
                        profile_confidence=0.0,
                        dutching_odd=dutching_odd_bf,
                        n_selections=len(outcomes_b365),
                        edge_std=None, has_real_odds=False,
                    )
                    opportunities.append({
                        'match': match_name,
                        'date': match_date,
                        'match_date_sort': match_date_sort,
                        'match_time_sort': match_time_sort,
                        'bookmaker': 'Betfair Exchange',
                        'market': f"{label_prefix}{market_label}",
                        'selections': outcomes_b365,
                        'selections_probs': sel_probs_b365,
                        'alternative_scores': alt_scores,
                        'odds': [round(o, 2) for o in odds_betfair],
                        'dutching_odd': round(dutching_odd_bf, 2),
                        'model_prob': f"{round(prob_combined * 100, 2)}%",
                        'edge': f"+{round(edge_bf * 100, 2)}%",
                        'raw_edge': edge_bf,
                        'game_profile': None,
                        'profile_confidence': 0,
                        'edge_ci_95': None,
                        'edge_prob_positive': None,
                        'quality_score': quality['score'],
                        'quality_verdict': quality['verdict'],
                        'quality_verdict_label': quality['verdict_label'],
                        'quality_verdict_color': quality['verdict_color'],
                        'quality_verdict_icon': quality['verdict_icon'],
                        'quality_breakdown': quality['breakdown'],
                        'odds_source_type': 'estimated',
                    })

    # Ordena oportunidades pelo Edge
    opportunities.sort(key=lambda x: x['raw_edge'], reverse=True)
    return opportunities

def get_mock_dutching_opportunities(strategy='auto_ia'):
    now = datetime.now()
    now_str = now.strftime("%d/%m/%Y %H:%M")
    mock_sort_date = now.strftime("%Y-%m-%d")
    mock_sort_time = now.strftime("%H:%M")

    if strategy == 'home_fav':
        opps = [
            {
                'match': 'Flamengo vs Fluminense',
                'date': now_str,
                'match_date_sort': mock_sort_date,
                'match_time_sort': mock_sort_time,
                'bookmaker': 'Betfair Exchange',
                'market': 'Favorito Mandante',
                'selections': ['1-0', '2-0', '2-1', '3-0', '3-1', '3-2'],
                'selections_probs': [0.18, 0.14, 0.12, 0.09, 0.08, 0.04],
                'alternative_scores': [
                    {'name': '0-0', 'prob': 0.08, 'odd': 10.50},
                    {'name': '1-1', 'prob': 0.07, 'odd': 7.00},
                    {'name': '4-0', 'prob': 0.03, 'odd': 25.0}
                ],
                'odds': [7.00, 8.00, 9.00, 12.0, 14.0, 22.0],
                'dutching_odd': 2.35,
                'model_prob': '65.00%',
                'edge': '+18.50%',
                'raw_edge': 0.185
            }
        ]
    elif strategy == 'under':
        opps = [
            {
                'match': 'Castellon vs Eibar',
                'date': now_str,
                'match_date_sort': mock_sort_date,
                'match_time_sort': mock_sort_time,
                'bookmaker': 'Bet365',
                'market': 'Under / Jogo Truncado',
                'selections': ['0-0', '1-0', '0-1', '2-0', '1-1'],
                'selections_probs': [0.13, 0.17, 0.10, 0.13, 0.12],
                'alternative_scores': [
                    {'name': '2-1', 'prob': 0.08, 'odd': 9.00},
                    {'name': '0-2', 'prob': 0.05, 'odd': 18.0}
                ],
                'odds': [11.0, 7.00, 10.0, 8.50, 7.50],
                'dutching_odd': 1.88,
                'model_prob': '65.00%',
                'edge': '+22.20%',
                'raw_edge': 0.222
            }
        ]
    elif strategy == 'draw':
        opps = [
            {
                'match': 'Corinthians vs São Paulo',
                'date': now_str,
                'match_date_sort': mock_sort_date,
                'match_time_sort': mock_sort_time,
                'bookmaker': 'Bet365',
                'market': 'Empate',
                'selections': ['0-0', '1-1', '2-2'],
                'selections_probs': [0.12, 0.16, 0.06],
                'alternative_scores': [
                    {'name': '1-0', 'prob': 0.14, 'odd': 6.50},
                    {'name': '0-1', 'prob': 0.11, 'odd': 8.00},
                    {'name': '3-3', 'prob': 0.01, 'odd': 80.0}
                ],
                'odds': [9.00, 7.00, 18.0],
                'dutching_odd': 3.02,
                'model_prob': '34.00%',
                'edge': '+15.30%',
                'raw_edge': 0.153
            }
        ]
    elif strategy == 'away_fav':
        opps = [
            {
                'match': 'Atlético Mineiro vs Palmeiras',
                'date': now_str,
                'match_date_sort': mock_sort_date,
                'match_time_sort': mock_sort_time,
                'bookmaker': 'Betfair Exchange',
                'market': 'Favorito Visitante',
                'selections': ['0-1', '0-2', '1-2', '0-3', '1-3'],
                'selections_probs': [0.16, 0.11, 0.10, 0.07, 0.06],
                'alternative_scores': [
                    {'name': '0-0', 'prob': 0.10, 'odd': 12.0},
                    {'name': '1-1', 'prob': 0.09, 'odd': 8.00}
                ],
                'odds': [8.00, 11.0, 12.0, 18.0, 22.0],
                'dutching_odd': 2.66,
                'model_prob': '50.00%',
                'edge': '+16.50%',
                'raw_edge': 0.165
            }
        ]
    elif strategy == 'over':
        opps = [
            {
                'match': 'RB Bragantino vs Fortaleza',
                'date': now_str,
                'match_date_sort': mock_sort_date,
                'match_time_sort': mock_sort_time,
                'bookmaker': 'Bet365',
                'market': 'Over / Goleada',
                'selections': ['2-1', '1-2', '3-1', '2-2', '3-2', '1-3'],
                'selections_probs': [0.11, 0.09, 0.08, 0.07, 0.05, 0.05],
                'alternative_scores': [
                    {'name': '2-0', 'prob': 0.10, 'odd': 8.50},
                    {'name': '3-0', 'prob': 0.06, 'odd': 14.0}
                ],
                'odds': [9.00, 12.0, 15.0, 14.0, 25.0, 22.0],
                'dutching_odd': 3.15,
                'model_prob': '45.00%',
                'edge': '+12.80%',
                'raw_edge': 0.128
            }
        ]
    else:  # auto_ia / dynamic
        opps = [
            {
                'match': 'Flamengo vs Fluminense',
                'date': now_str,
                'match_date_sort': mock_sort_date,
                'match_time_sort': mock_sort_time,
                'bookmaker': 'Betfair Exchange',
                'market': 'IA Favorito Mandante',
                'selections': ['1-0', '2-0', '2-1', '3-0', '3-1', '3-2'],
                'selections_probs': [0.18, 0.14, 0.12, 0.09, 0.08, 0.04],
                'alternative_scores': [
                    {'name': '0-0', 'prob': 0.08, 'odd': 10.50},
                    {'name': '1-1', 'prob': 0.07, 'odd': 7.00}
                ],
                'odds': [7.00, 8.00, 9.00, 12.0, 14.0, 22.0],
                'dutching_odd': 2.35,
                'model_prob': '65.00%',
                'edge': '+18.50%',
                'raw_edge': 0.185
            },
            {
                'match': 'Castellon vs Eibar',
                'date': now_str,
                'match_date_sort': mock_sort_date,
                'match_time_sort': mock_sort_time,
                'bookmaker': 'Bet365',
                'market': 'IA Under / Jogo Truncado',
                'selections': ['0-0', '1-0', '0-1', '2-0', '1-1'],
                'selections_probs': [0.13, 0.17, 0.10, 0.13, 0.12],
                'alternative_scores': [
                    {'name': '2-1', 'prob': 0.08, 'odd': 9.00},
                    {'name': '0-2', 'prob': 0.05, 'odd': 18.0}
                ],
                'odds': [11.0, 7.00, 10.0, 8.50, 7.50],
                'dutching_odd': 1.88,
                'model_prob': '65.00%',
                'edge': '+22.20%',
                'raw_edge': 0.222
            }
        ]
    return opps


def _score_probs_from_matrix(prob_matrix, max_display=6):
    """Extrai dict {"1-0": prob, ...} da matriz de probabilidades."""
    score_probs = {}
    rows = min(prob_matrix.shape[0], max_display)
    cols = min(prob_matrix.shape[1], max_display)
    for i in range(rows):
        for j in range(cols):
            score_probs[f"{i}-{j}"] = float(prob_matrix[i, j])
    return score_probs


def fetch_dutching_anchored_opportunities(api_key=None, source='oddspapi', data_source='auto'):
    """
    Triagem Ancorada: ranqueia jogos futuros por divergência modelo × mercado
    REAL (1X2 e Over/Under), SEM inventar odds de Correct Score.

    Retorna lista de jogos ordenados por anchored_score (maior primeiro), cada um
    com prévia de placares estimados (claramente marcados como estimativa).
    """
    from .dutching.anchored import compute_anchored_score

    if not api_key:
        api_key = os.getenv('THE_ODDS_API_KEY') or get_odds_api_token()

    # ── 1. Buscar jogos futuros conforme a fonte ──
    matches = []
    if source == 'oddspapi':
        from .oddspapi_client import fetch_oddspapi_matches
        opapi_matches, err = fetch_oddspapi_matches()
        if err:
            return [err]
        for m in opapi_matches:
            lc = _guess_league_from_teams(m.get('home_team', ''), m.get('away_team', ''))
            if lc:
                matches.append({
                    'home_team': m.get('home_team'),
                    'away_team': m.get('away_team'),
                    'commence_time': m.get('commence_time'),
                    'league_code': lc,
                    'bookmakers': m.get('bookmakers', []),
                })
    elif source in ('datafootball', 'csv_fixtures'):
        # Reusar o carregamento de fixtures locais/DataFootball
        df_fixtures = pd.DataFrame()
        if source == 'datafootball':
            token = get_api_token()
            if token:
                try:
                    df_fixtures = load_upcoming_from_api(token)
                except Exception:
                    pass
        if df_fixtures.empty:
            fixtures_path = os.path.join(DATA_DIR, 'fixtures.csv')
            if os.path.exists(fixtures_path):
                try:
                    df_fixtures = pd.read_csv(fixtures_path, encoding='latin1')
                    df_fixtures.columns = [c.replace('ï»¿', '').replace('\ufeff', '').strip() for c in df_fixtures.columns]
                except Exception:
                    pass
        if df_fixtures.empty:
            return []
        for row in df_fixtures.to_dict('records'):
            lc = row.get('Div')
            if not lc:
                continue
            matches.append({
                'home_team': row.get('HomeTeam'),
                'away_team': row.get('AwayTeam'),
                'commence_time': None,
                'date_raw': f"{row.get('Date', '')} {row.get('Time', '')}",
                'league_code': lc,
                'ou_odds': (row.get('B365>2.5'), row.get('B365<2.5')),
                'x2_odds': (row.get('B365H'), row.get('B365D'), row.get('B365A')),
                'bookmakers': [],
            })
    else:
        return [{'error': 'invalid_source', 'message': f'Fonte {source} não suportada na triagem ancorada.'}]

    if not matches:
        return []

    # ── 2. Carregar dados históricos por liga (lazy) ──
    leagues_data = {}
    results = []

    for match in matches:
        lc = match['league_code']
        if lc not in leagues_data:
            try:
                ds = data_source if data_source != 'auto' else auto_detect_data_source(lc)
                df = load_league_data(lc, start_date='2020-08-01', data_source=ds)
                leagues_data[lc] = df if (df is not None and not df.empty) else None
            except Exception:
                leagues_data[lc] = None
        df = leagues_data.get(lc)
        if df is None:
            continue

        home = match['home_team']
        away = match['away_team']
        if not home or not away:
            continue

        # ── 3. Rodar o modelo ──
        try:
            pred_match_date = pd.Timestamp.now()
            pred = predict_match_nb(home, away, df, pred_match_date)
            if pred is None:
                continue
        except Exception:
            continue

        # ── 4. Extrair odds reais de mercado (1X2 e O/U) ──
        market_ou = match.get('ou_odds')
        market_1x2 = match.get('x2_odds')

        # Se veio de bookmakers (OddsPapi/OddsAPI), extrair h2h
        if not market_1x2 and match.get('bookmakers'):
            for bm in match['bookmakers']:
                for mk in bm.get('markets', []):
                    if mk.get('key') == 'h2h':
                        outs = {o['name']: o['price'] for o in mk.get('outcomes', [])}
                        h = outs.get(home) or outs.get('Home')
                        d = outs.get('Draw')
                        a = outs.get(away) or outs.get('Away')
                        if h and a:
                            market_1x2 = (h, d or 0, a)
                            break
                if market_1x2:
                    break

        # Normalizar OU odds
        def _valid_odd(x):
            try:
                v = float(x)
                return v if v > 1.01 else None
            except (ValueError, TypeError):
                return None

        if market_ou:
            ou_over = _valid_odd(market_ou[0])
            ou_under = _valid_odd(market_ou[1])
            market_ou = (ou_over, ou_under) if (ou_over and ou_under) else None

        # ── 5. Placares estimados (prévia) ──
        prob_matrix = pred.get('prob_matrix')
        if prob_matrix is None:
            continue
        score_probs = _score_probs_from_matrix(prob_matrix)

        # Top placares por probabilidade
        top_scores = sorted(score_probs.items(), key=lambda kv: kv[1], reverse=True)[:6]

        # ── 6. Score ancorado ──
        anchored = compute_anchored_score(
            pred, market_ou_odds=market_ou, market_1x2_odds=market_1x2,
            score_probs=score_probs, league_code=lc
        )

        # Data
        match_date = match.get('date_raw')
        if not match_date and match.get('commence_time'):
            try:
                mt = datetime.strptime(match['commence_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if mt < datetime.now(timezone.utc):
                    continue
                match_date = mt.astimezone(BRAZIL_TZ).strftime("%d/%m/%Y %H:%M")
            except Exception:
                match_date = '—'

        # Odds estimadas de CS (prévia — claramente marcadas)
        preview_selections = []
        for score_str, prob in top_scores:
            est_odd = round(1.0 / prob, 2) if prob > 0.001 else 999.0
            preview_selections.append({
                'score': score_str,
                'prob': round(prob, 4),
                'estimated_odd': est_odd,
            })

        results.append({
            'match': f"{home} vs {away}",
            'home_team': home,
            'away_team': away,
            'date': match_date or '—',
            'league': lc,
            'anchored_score': anchored['anchored_score'],
            'score_components': anchored['components'],
            'reasons': anchored['reasons'],
            'ou_divergence': anchored['ou_divergence'],
            'x2_divergence': anchored['x2_divergence'],
            'concentration': anchored['concentration'],
            'model_confidence': anchored['model_confidence'],
            'has_real_ou': anchored['has_real_ou'],
            'has_real_1x2': anchored['has_real_1x2'],
            'preview_selections': preview_selections,
            'market_ou': market_ou,
            'market_1x2': market_1x2,
            'lambda_home': round(pred.get('lambda_home', 0), 2),
            'lambda_away': round(pred.get('lambda_away', 0), 2),
        })

    # ── 7. Ordenar por score de oportunidade ──
    results.sort(key=lambda r: r['anchored_score'], reverse=True)
    return results
