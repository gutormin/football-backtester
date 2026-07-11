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

# Universo de placares cobertos (20 placares mais frequentes no futebol)
ALL_DUTCH_SCORES = [
    '0-0',
    '1-0', '0-1',
    '2-0', '0-2',
    '3-0', '0-3',
    '4-0', '0-4',
    '1-1',
    '2-1', '1-2',
    '3-1', '1-3',
    '4-1', '1-4',
    '2-2',
    '3-2', '2-3',
    '3-3',
]

# Grupos temáticos de placares para estratégias direcionadas
SCORE_GROUPS = {
    'home_fav': ['1-0', '2-0', '2-1', '3-0', '3-1', '3-2', '4-0', '4-1'],
    'away_fav': ['0-1', '0-2', '1-2', '0-3', '1-3', '2-3', '0-4', '1-4'],
    'draw':     ['0-0', '1-1', '2-2', '3-3'],
    'under':    ['0-0', '1-0', '0-1', '2-0', '0-2', '1-1'],       # total ≤ 2
    'over':     ['2-1', '1-2', '3-0', '0-3', '3-1', '1-3', '2-2',  # total ≥ 3
                 '3-2', '2-3', '4-0', '0-4', '4-1', '1-4', '3-3'],
}

def _score_to_key(score_str: str) -> str:
    return f"bookie_cs_{score_str.replace('-', '')}"

def _get_score_prob(pred, score_str: str) -> float:
    try:
        x, y = map(int, score_str.split('-'))
        return float(pred['prob_matrix'][x][y])
    except Exception:
        return 0.0

def build_dynamic_dutch(pred, est_odds, strategy='dynamic',
                        max_legs=8, max_overround=0.92, min_selections=3):
    """Constrói um dutch agregando os placares mais provaveis da estrategia.

    Com odds ESTIMADAS (derivadas do mercado O/U 2.5), nao faz sentido filtrar por EV
    individual — a divergencia modelo-vs-mercado esta no lambda total, nao por placar.
    O edge de cada placar e aproximadamente 1/juice - 1 (negativo) para todos.

    A estrategia correta com odds estimadas:
    1. Inclui todos os placares do grupo (respeitando max_overround)
    2. Calcula o edge AGREGADO do dutch completo
    3. Se edge agregado > 0, o dutch captura a divergencia modelo vs mercado

    O edge agregado reflete essencialmente o edge que o modelo teria no mercado O/U 2.5,
    redistribuido entre os placares do dutch.

    Com odds REAIS de CS (API), filtrariamos por EV individual (min_ev=5%).
    """
    if strategy in SCORE_GROUPS:
        candidate_scores = list(SCORE_GROUPS[strategy])
    else:
        candidate_scores = list(ALL_DUTCH_SCORES)

    all_candidates = []
    for score in candidate_scores:
        prob = _get_score_prob(pred, score)
        key = _score_to_key(score)
        odd = est_odds.get(key, np.nan)

        if pd.isna(odd) or np.isnan(odd) or odd <= 1.3 or prob <= 0.005:
            continue

        all_candidates.append({
            'score': score,
            'prob': prob,
            'odd': odd,
            'key': key,
            'ev': prob * odd - 1.0,
            'prob_odd_ratio': prob / (1.0 / odd),
        })

    if len(all_candidates) < min_selections:
        return None, None, None, None, None, 0, 0, -1

    # Detecta se temos odds reais de CS (EV varia entre scores)
    # Com odds estimadas, todos os EV sao ~1/juice - 1 (quase identicos)
    ev_values = [c['ev'] for c in all_candidates]
    has_real_odds = (max(ev_values) - min(ev_values)) > 0.03 and max(ev_values) > -0.01

    if has_real_odds:
        # Odds reais: seleciona por EV positivo, depois por EV decrescente
        all_candidates.sort(key=lambda x: (x['ev'] > 0, x['ev']), reverse=True)
    else:
        # Odds estimadas: seleciona por probabilidade (EV individual nao informativo)
        all_candidates.sort(key=lambda x: x['prob'], reverse=True)

    # Seleciona todos os candidatos ate o limite de max_legs e max_overround
    selected = []
    cum_overround = 0.0
    cum_prob = 0.0
    for c in all_candidates:
        new_overround = cum_overround + 1.0 / c['odd']
        if len(selected) >= max_legs or new_overround > max_overround:
            break
        selected.append(c)
        cum_overround = new_overround
        cum_prob += c['prob']

    if len(selected) < min_selections:
        return None, None, None, None, None, 0, 0, -1

    dutching_odd = 1.0 / cum_overround
    edge = cum_prob * dutching_odd - 1.0

    # Remove a pior perna (menor prob/odd) enquanto edge < 0
    # Isso concentra o dutch nos placares onde modelo e mais otimista que o mercado
    while edge < 0 and len(selected) > min_selections:
        worst = min(selected, key=lambda c: c['prob_odd_ratio'])
        selected.remove(worst)
        cum_overround = sum(1.0 / c['odd'] for c in selected)
        cum_prob = sum(c['prob'] for c in selected)
        if cum_overround <= 0:
            return None, None, None, None, None, 0, 0, -1
        dutching_odd = 1.0 / cum_overround
        edge = cum_prob * dutching_odd - 1.0

    if edge < 0:
        return None, None, None, None, None, 0, 0, -1

    outcomes = [c['score'] for c in selected]
    probs_list = [round(c['prob'], 4) for c in selected]
    odds_list = [round(c['odd'], 2) for c in selected]
    keys_list = [c['key'] for c in selected]

    strategy_labels = {
        'dynamic': 'Dinamico (Top Probabilidades)',
        'home_fav': 'Favorito Mandante',
        'away_fav': 'Favorito Visitante',
        'draw': 'Empate',
        'under': 'Under / Jogo Truncado',
        'over': 'Over / Goleada',
    }
    label = strategy_labels.get(strategy, strategy)

    return outcomes, probs_list, odds_list, keys_list, label, cum_prob, dutching_odd, edge


def get_selections_and_alternatives(pred, outcomes_to_cover, est_odds):
    # 1. Selections probs
    selections_probs = []
    for sel in outcomes_to_cover:
        prob = _get_score_prob(pred, sel)
        selections_probs.append(round(prob, 4))

    # 2. Alternative scores (todos os 20 placares, exceto os já cobertos)
    alternative_scores = []
    for score in ALL_DUTCH_SCORES:
        if score in outcomes_to_cover:
            continue
        prob_cs = _get_score_prob(pred, score)
        key = _score_to_key(score)
        odd_cs = est_odds.get(key, np.nan)

        if prob_cs > 0.01 and not pd.isna(odd_cs) and not np.isnan(odd_cs) and odd_cs > 1.0:
            alternative_scores.append({
                'name': score,
                'prob': round(prob_cs, 4),
                'odd': round(odd_cs, 2)
            })

    alternative_scores.sort(key=lambda x: x['prob'], reverse=True)
    return selections_probs, alternative_scores

def fetch_dutching_opportunities(api_key=None, source='odds_api', strategy='auto_ia', data_source='auto', futpython_api_key=''):
    if not api_key:
        api_key = os.getenv('THE_ODDS_API_KEY') or get_odds_api_token()
    opportunities = []

    # Helper para resolver a estratégia: se 'auto_ia', escolhe baseado no perfil do jogo
    def resolve_strategy(strategy_name, pred, is_home_fav):
        if strategy_name != 'auto_ia':
            return strategy_name
        g_exp = pred.get('lambda_home', 1.0) + pred.get('lambda_away', 1.0)
        prob_under25 = pred.get('prob_under_25', 0.5)
        prob_draw = pred.get('prob_d', 0.26)
        prob_h = pred.get('prob_h', 0.37)
        prob_a = pred.get('prob_a', 0.37)

        if g_exp < 2.30 or prob_under25 > 0.55:
            return 'under'
        elif prob_draw > 0.32:
            return 'draw'
        elif is_home_fav and prob_h > 0.45:
            return 'home_fav'
        elif not is_home_fav and prob_a > 0.45:
            return 'away_fav'
        else:
            return 'dynamic'

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

    # 1. FONTE: THE ODDS API (Tempo Real Betfair/Bet365)
    if source == 'odds_api':
        REGIONS = 'eu,uk,us'
        MARKETS = 'h2h,totals'
        headers = {'User-Agent': 'Mozilla/5.0'}

        @retry_with_backoff(max_retries=2, base_delay=0.5)
        def _get_odds(url):
            return requests.get(url, headers=headers, timeout=8)

        if not api_key or api_key == 'test':
            return [{'error': 'no_api_key', 'message': 'API key da The Odds API não configurada. Obtenha uma em https://the-odds-api.com e configure THE_ODDS_API_KEY no ambiente ou em data/odds_api_config.json.'}]

        # Fetch live matches from API first (lightweight), then load data only for leagues with games
        matches_found = []
        api_errors = []
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
                    api_errors.append(f'Chave de API inválida (HTTP 401). Verifique THE_ODDS_API_KEY.')
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
                match_date = match_time.strftime("%d/%m/%Y %H:%M")
            except:
                continue
                
            # Collect odds from all bookmakers that have h2h + totals
            odds_data = {}  # bookie_title -> {h2h, totals_point, totals_over, totals_under, h2h_lay}

            for bookie in match.get('bookmakers', []):
                title = bookie.get('title')
                h2h = {}
                h2h_lay = {}
                totals_by_point = {}  # point -> {name: price}

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
                    odds_data[title] = {
                        'h2h': h2h_lay if use_lay else h2h,
                        'totals': best_totals,
                        'totals_point': best_totals_point,
                        'is_exchange': use_lay,
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

                if not o25_odd or not u25_odd:
                    continue

                try:
                    est_odds = estimate_bookmaker_odds(
                        o25_odd, u25_odd, pred['lambda_home'], pred['lambda_away'],
                        pred.get('rho'), bookmaker=bookie,
                        btts_yes_odd=None, btts_no_odd=None)
                except Exception:
                    continue

                # Se o ponto do totals nao for 2.5 (ex: Pinnacle 2.75), ajusta odds via shift linear
                if abs(o25_point - 2.5) > 0.01 and 'bookie_over_25' not in est_odds:
                    shift = o25_point - 2.5
                    est_odds['total_point'] = o25_point

                # Dutching dinâmico baseado em EV individual
                is_home_fav = pred['prob_h'] > pred['prob_a']
                current_strat = resolve_strategy(strategy, pred, is_home_fav)
                outcomes_to_cover, sel_probs, odds_to_cover, odds_keys, market_label, prob_combined, dutching_odd, edge = \
                    build_dynamic_dutch(pred, est_odds, strategy=current_strat)

                if outcomes_to_cover is None:
                    continue

                if edge > 0:
                    label_prefix = "IA " if strategy == 'auto_ia' else ""
                    _, alt_scores = get_selections_and_alternatives(pred, outcomes_to_cover, est_odds)
                    opportunities.append({
                        'match': match_name,
                        'date': match_date,
                        'bookmaker': bookie,
                        'market': f"{label_prefix}{market_label}",
                        'selections': outcomes_to_cover,
                        'selections_probs': sel_probs,
                        'alternative_scores': alt_scores,
                        'odds': [round(o, 2) for o in odds_to_cover],
                        'dutching_odd': round(dutching_odd, 2),
                        'model_prob': f"{round(prob_combined * 100, 2)}%",
                        'edge': f"+{round(edge * 100, 2)}%",
                        'raw_edge': edge
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
            if row.get('Time'):
                match_date += f" {row.get('Time')}"

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
                opportunities.append({
                    'match': match_name,
                    'date': match_date,
                    'bookmaker': 'Bet365',
                    'market': f"{label_prefix}{market_label}",
                    'selections': outcomes_b365,
                    'selections_probs': sel_probs_b365,
                    'alternative_scores': alt_scores,
                    'odds': [round(o, 2) for o in odds_b365],
                    'dutching_odd': round(dutching_odd, 2),
                    'model_prob': f"{round(prob_combined * 100, 2)}%",
                    'edge': f"+{round(edge * 100, 2)}%",
                    'raw_edge': edge
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
                    opportunities.append({
                        'match': match_name,
                        'date': match_date,
                        'bookmaker': 'Betfair Exchange',
                        'market': f"{label_prefix}{market_label}",
                        'selections': outcomes_b365,
                        'selections_probs': sel_probs_b365,
                        'alternative_scores': alt_scores,
                        'odds': [round(o, 2) for o in odds_betfair],
                        'dutching_odd': round(dutching_odd_bf, 2),
                        'model_prob': f"{round(prob_combined * 100, 2)}%",
                        'edge': f"+{round(edge_bf * 100, 2)}%",
                        'raw_edge': edge_bf
                    })

    # Ordena oportunidades pelo Edge
    opportunities.sort(key=lambda x: x['raw_edge'], reverse=True)
    return opportunities

def get_mock_dutching_opportunities(strategy='auto_ia'):
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    if strategy == 'home_fav':
        opps = [
            {
                'match': 'Flamengo vs Fluminense',
                'date': now_str,
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
