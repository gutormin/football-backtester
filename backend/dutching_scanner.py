import os
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from backend.models import PoissonModel, estimate_bookmaker_odds
import json
from backend.data_loader import load_league_data, get_all_available_leagues, DATA_DIR, get_api_token, load_upcoming_from_api

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

# Mapeamento do sport_key da The Odds API para o código de liga do nosso sistema
SPORT_LEAGUE_MAP = {
    'soccer_epl': 'E0',
    'soccer_spain_la_liga': 'SP1',
    'soccer_italy_serie_a': 'I1',
    'soccer_germany_bundesliga': 'D1',
    'soccer_france_ligue_one': 'F1',
    'soccer_brazil_campeonato': 'BRA',
    'soccer_usa_mls': 'USA',
    'soccer_japan_j_league': 'JPN',
    'soccer_sweden_allsvenskan': 'SWEDEN_ALLSVENSKAN',
    'soccer_norway_eliteserien': 'NORWAY_ELITESERIEN'
}

def get_selections_and_alternatives(pred, outcomes_to_cover, est_odds):
    # 1. Selections probs
    selections_probs = []
    for sel in outcomes_to_cover:
        try:
            x, y = map(int, sel.split('-'))
            prob = float(pred['prob_matrix'][x][y])
        except Exception:
            prob = 0.0
        selections_probs.append(round(prob, 4))
        
    # 2. Alternative scores
    alternative_scores = []
    standard_scores = ['0-0', '1-0', '2-0', '2-1', '3-0', '3-1', '0-1', '0-2', '1-2', '0-3', '1-3', '1-1']
    for score in standard_scores:
        if score not in outcomes_to_cover:
            try:
                x, y = map(int, score.split('-'))
                prob_cs = float(pred['prob_matrix'][x][y])
            except Exception:
                prob_cs = 0.0
            
            key = f"bookie_cs_{score.replace('-', '')}"
            odd_cs = est_odds.get(key, np.nan)
            
            if prob_cs > 0.015 and not pd.isna(odd_cs) and not np.isnan(odd_cs) and odd_cs > 1.0:
                alternative_scores.append({
                    'name': score,
                    'prob': round(prob_cs, 4),
                    'odd': round(odd_cs, 2)
                })
    # Sort alternatives by probability descending
    alternative_scores.sort(key=lambda x: x['prob'], reverse=True)
    return selections_probs, alternative_scores

def fetch_dutching_opportunities(api_key=None, source='odds_api', strategy='auto_ia'):
    if not api_key:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv('THE_ODDS_API_KEY')
    opportunities = []
    poisson = PoissonModel()
    
    # Carrega dados históricos apenas das ligas mapeadas para evitar leituras repetidas em loop
    all_leagues = get_all_available_leagues()
    league_codes = [l['code'] for l in all_leagues]
    leagues_data = {}
    
    for league_code in league_codes:
        try:
            df = load_league_data(league_code, start_date='2020-08-01')
            if not df.empty:
                leagues_data[league_code] = df
        except Exception:
            pass

    # Helper para estruturar placares e probabilidades com base na estratégia selecionada
    def get_strategy_layout(pred, is_home_fav, strategy_name):
        if strategy_name == 'fav_classic':
            if is_home_fav:
                fav_side = 'home'
                outcomes = ['1-0', '2-0', '2-1', '3-0', '3-1']
                prob = pred['prob_matrix'][1][0] + pred['prob_matrix'][2][0] + pred['prob_matrix'][2][1] + pred['prob_matrix'][3][0] + pred['prob_matrix'][3][1]
                keys = ['bookie_cs_10', 'bookie_cs_20', 'bookie_cs_21', 'bookie_cs_30', 'bookie_cs_31']
            else:
                fav_side = 'away'
                outcomes = ['0-1', '0-2', '1-2', '0-3', '1-3']
                prob = pred['prob_matrix'][0][1] + pred['prob_matrix'][0][2] + pred['prob_matrix'][1][2] + pred['prob_matrix'][0][3] + pred['prob_matrix'][1][3]
                keys = ['bookie_cs_01', 'bookie_cs_02', 'bookie_cs_12', 'bookie_cs_03', 'bookie_cs_13']
            market_label = f"Favorito Clássico ({'Mandante' if fav_side == 'home' else 'Visitante'})"
            
        elif strategy_name == 'under_trunc':
            if is_home_fav:
                fav_side = 'home'
                outcomes = ['0-0', '1-0', '2-0', '1-1']
                prob = pred['prob_matrix'][0][0] + pred['prob_matrix'][1][0] + pred['prob_matrix'][2][0] + pred['prob_matrix'][1][1]
                keys = ['bookie_cs_00', 'bookie_cs_10', 'bookie_cs_20', 'bookie_cs_11']
            else:
                fav_side = 'away'
                outcomes = ['0-0', '0-1', '0-2', '1-1']
                prob = pred['prob_matrix'][0][0] + pred['prob_matrix'][0][1] + pred['prob_matrix'][0][2] + pred['prob_matrix'][1][1]
                keys = ['bookie_cs_00', 'bookie_cs_01', 'bookie_cs_02', 'bookie_cs_11']
            market_label = f"Jogo Truncado / Under ({'Mandante' if fav_side == 'home' else 'Visitante'})"
            
        else: # fav_short
            if is_home_fav:
                fav_side = 'home'
                outcomes = ['1-0', '2-0', '2-1']
                prob = pred['prob_matrix'][1][0] + pred['prob_matrix'][2][0] + pred['prob_matrix'][2][1]
                keys = ['bookie_cs_10', 'bookie_cs_20', 'bookie_cs_21']
            else:
                fav_side = 'away'
                outcomes = ['0-1', '0-2', '1-2']
                prob = pred['prob_matrix'][0][1] + pred['prob_matrix'][0][2] + pred['prob_matrix'][1][2]
                keys = ['bookie_cs_01', 'bookie_cs_02', 'bookie_cs_12']
            market_label = f"Favorito Curto ({'Mandante' if fav_side == 'home' else 'Visitante'})"
            
        return outcomes, prob, keys, market_label

    # Helper para selecionar a melhor estratégia de forma automática (IA Recomendada)
    def determine_best_strategy(pred, is_home_fav):
        g_exp = pred.get('lambda_home', 1.0) + pred.get('lambda_away', 1.0)
        prob_under25 = pred.get('prob_under_25', 0.5)
        prob_fav = pred['prob_home'] if is_home_fav else pred['prob_away']
        
        if g_exp < 2.30 or prob_under25 > 0.55:
            return 'under_trunc'
        elif prob_fav > 0.50:
            return 'fav_classic'
        else:
            return 'fav_short'

    # 1. FONTE: THE ODDS API (Tempo Real Betfair/Bet365)
    if source == 'odds_api':
        REGIONS = 'eu,uk,us'
        MARKETS = 'h2h,totals'
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        matches_found = []
        for sport_key, league_code in SPORT_LEAGUE_MAP.items():
            if league_code not in leagues_data:
                continue
            url = f'https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={api_key}&regions={REGIONS}&markets={MARKETS}'
            try:
                response = requests.get(url, headers=headers, timeout=8)
                if response.status_code == 200:
                    matches_found.extend(response.json())
            except Exception as e:
                print(f"Erro ao buscar Odds API para {sport_key}: {e}")
                
        if not matches_found:
            return []
            
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
                
            odds_data = {
                'Bet365': {'h2h': {}, 'totals': {}},
                'Betfair Exchange': {'h2h': {}, 'totals': {}},
                'Pinnacle': {'h2h': {}, 'totals': {}}
            }
            
            for bookie in match.get('bookmakers', []):
                title = bookie.get('title')
                if title == 'Betfair':
                    title = 'Betfair Exchange'
                if title not in ['Bet365', 'Betfair Exchange', 'Pinnacle']:
                    continue
                    
                for market in bookie.get('markets', []):
                    key = market.get('key')
                    if key == 'h2h':
                        for outcome in market.get('outcomes', []):
                            odds_data[title]['h2h'][outcome.get('name')] = outcome.get('price')
                    elif key == 'totals':
                        for outcome in market.get('outcomes', []):
                            point = outcome.get('point')
                            if point == 2.5:
                                odds_data[title]['totals'][outcome.get('name')] = outcome.get('price')
                                
            has_bet365 = len(odds_data['Bet365']['h2h']) == 3 and len(odds_data['Bet365']['totals']) == 2
            has_betfair = len(odds_data['Betfair Exchange']['h2h']) == 3 and len(odds_data['Betfair Exchange']['totals']) == 2
            has_pinnacle = len(odds_data['Pinnacle']['h2h']) == 3 and len(odds_data['Pinnacle']['totals']) == 2
            
            if not (has_bet365 or has_betfair or has_pinnacle):
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
                pred = poisson.predict_match(home_team_local, away_team_local, hist_df, datetime.now())
                if not pred or 'lambda_home' not in pred:
                    continue
            except Exception:
                continue
                
            for bookie in ['Bet365', 'Betfair Exchange', 'Pinnacle']:
                if not (len(odds_data[bookie]['h2h']) == 3 and len(odds_data[bookie]['totals']) == 2):
                    continue
                    
                o25_odd = odds_data[bookie]['totals'].get('Over')
                u25_odd = odds_data[bookie]['totals'].get('Under')
                
                if not o25_odd or not u25_odd:
                    continue
                    
                try:
                    est_odds = estimate_bookmaker_odds(o25_odd, u25_odd, pred['lambda_home'], pred['lambda_away'])
                except Exception:
                    continue
                    
                # Layout dinâmico da estratégia
                is_home_fav = pred['prob_home'] > pred['prob_away']
                current_strat = determine_best_strategy(pred, is_home_fav) if strategy == 'auto_ia' else strategy
                outcomes_to_cover, prob_combined, odds_keys, market_label = get_strategy_layout(pred, is_home_fav, current_strat)
                odds_to_cover = [est_odds.get(key, np.nan) for key in odds_keys]
                
                # Evita falha de serialização JSON pulando se houver odds NaN ou inválidas
                if any(pd.isna(odd) or odd <= 1.001 or np.isnan(odd) for odd in odds_to_cover):
                    continue
                    
                sum_prob_implied = sum(1.0 / odd for odd in odds_to_cover)
                if sum_prob_implied > 0:
                    dutching_odd = 1.0 / sum_prob_implied
                    edge = prob_combined * dutching_odd - 1.0
                    
                    if edge > 0.01:
                        label_prefix = "🧠 IA: " if strategy == 'auto_ia' else ""
                        sel_probs, alt_scores = get_selections_and_alternatives(pred, outcomes_to_cover, est_odds)
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
            
        for row in df_fixtures.to_dict('records'):
            league_code = row.get('Div')
            if not league_code or league_code not in leagues_data:
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
                
            hist_df = leagues_data[league_code]
            
            try:
                pred = poisson.predict_match(home_team, away_team, hist_df, datetime.now())
                if not pred or 'lambda_home' not in pred:
                    continue
            except Exception:
                continue
                
            # Calcula estimativa de Correct Score para Bet365
            try:
                est_odds_b365 = estimate_bookmaker_odds(odds_over25, odds_under25, pred['lambda_home'], pred['lambda_away'])
            except Exception:
                continue
                
            # Layout dinâmico da estratégia
            is_home_fav = pred['prob_home'] > pred['prob_away']
            current_strat = determine_best_strategy(pred, is_home_fav) if strategy == 'auto_ia' else strategy
            outcomes_to_cover, prob_combined, odds_keys, market_label = get_strategy_layout(pred, is_home_fav, current_strat)
            odds_b365 = [est_odds_b365.get(key, np.nan) for key in odds_keys]
            
            # Evita falha de serialização JSON pulando se houver odds NaN ou inválidas
            if any(pd.isna(odd) or odd <= 1.001 or np.isnan(odd) for odd in odds_b365):
                continue
                
            # 2.1 ESTRATÉGIA PARA BET365 (Física)
            sum_prob_b365 = sum(1.0 / odd for odd in odds_b365)
            if sum_prob_b365 > 0:
                dutching_odd = 1.0 / sum_prob_b365
                edge = prob_combined * dutching_odd - 1.0
                
                if edge > 0.01:
                    label_prefix = "🧠 IA: " if strategy == 'auto_ia' else ""
                    sel_probs, alt_scores = get_selections_and_alternatives(pred, outcomes_to_cover, est_odds_b365)
                    opportunities.append({
                        'match': match_name,
                        'date': match_date,
                        'bookmaker': 'Bet365',
                        'market': f"{label_prefix}{market_label}",
                        'selections': outcomes_to_cover,
                        'selections_probs': sel_probs,
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
                    label_prefix = "🧠 IA: " if strategy == 'auto_ia' else ""
                    sel_probs, alt_scores = get_selections_and_alternatives(pred, outcomes_to_cover, est_odds_b365)
                    opportunities.append({
                        'match': match_name,
                        'date': match_date,
                        'bookmaker': 'Betfair Exchange',
                        'market': f"{label_prefix}{market_label}",
                        'selections': outcomes_to_cover,
                        'selections_probs': sel_probs,
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
    
    if strategy == 'fav_classic':
        opps = [
            {
                'match': 'Flamengo vs Fluminense',
                'date': now_str,
                'bookmaker': 'Betfair Exchange',
                'market': 'Dutching Favorito Clássico (Mandante)',
                'selections': ['1-0', '2-0', '2-1', '3-0', '3-1'],
                'selections_probs': [0.20, 0.15, 0.12, 0.11, 0.105],
                'alternative_scores': [
                    {'name': '0-0', 'prob': 0.08, 'odd': 9.0},
                    {'name': '1-1', 'prob': 0.07, 'odd': 6.50}
                ],
                'odds': [6.50, 7.50, 8.50, 11.0, 13.0],
                'dutching_odd': 1.68,
                'model_prob': '68.50%',
                'edge': '+15.08%',
                'raw_edge': 0.1508
            }
        ]
    elif strategy == 'under_trunc':
        opps = [
            {
                'match': 'Flamengo vs Fluminense',
                'date': now_str,
                'bookmaker': 'Betfair Exchange',
                'market': 'Dutching Jogo Truncado / Under (Mandante)',
                'selections': ['0-0', '1-0', '2-0', '1-1'],
                'selections_probs': [0.15, 0.20, 0.14, 0.125],
                'alternative_scores': [
                    {'name': '2-1', 'prob': 0.08, 'odd': 8.50},
                    {'name': '0-1', 'prob': 0.06, 'odd': 10.0}
                ],
                'odds': [10.0, 6.50, 7.50, 7.00],
                'dutching_odd': 1.95,
                'model_prob': '61.50%',
                'edge': '+19.93%',
                'raw_edge': 0.1993
            }
        ]
    elif strategy == 'fav_short':
        opps = [
            {
                'match': 'Flamengo vs Fluminense',
                'date': now_str,
                'bookmaker': 'Betfair Exchange',
                'market': 'Dutching Favorito Curto (Mandante)',
                'selections': ['1-0', '2-0', '2-1'],
                'selections_probs': [0.20, 0.15, 0.125],
                'alternative_scores': [
                    {'name': '0-0', 'prob': 0.08, 'odd': 9.0},
                    {'name': '1-1', 'prob': 0.07, 'odd': 6.5}
                ],
                'odds': [6.50, 7.50, 8.50],
                'dutching_odd': 2.45,
                'model_prob': '47.50%',
                'edge': '+16.38%',
                'raw_edge': 0.1638
            }
        ]
    else: # auto_ia
        opps = [
            {
                'match': 'Flamengo vs Fluminense',
                'date': now_str,
                'bookmaker': 'Betfair Exchange',
                'market': '🧠 IA: Favorito Clássico (Mandante)',
                'selections': ['1-0', '2-0', '2-1', '3-0', '3-1'],
                'selections_probs': [0.20, 0.15, 0.12, 0.11, 0.105],
                'alternative_scores': [
                    {'name': '0-0', 'prob': 0.08, 'odd': 9.0},
                    {'name': '1-1', 'prob': 0.07, 'odd': 6.5}
                ],
                'odds': [6.50, 7.50, 8.50, 11.0, 13.0],
                'dutching_odd': 1.68,
                'model_prob': '68.50%',
                'edge': '+15.08%',
                'raw_edge': 0.1508
            },
            {
                'match': 'Castellon vs Eibar',
                'date': now_str,
                'bookmaker': 'Bet365',
                'market': '🧠 IA: Jogo Truncado / Under (Mandante)',
                'selections': ['0-0', '1-0', '2-0', '1-1'],
                'selections_probs': [0.12, 0.18, 0.15, 0.131],
                'alternative_scores': [
                    {'name': '2-1', 'prob': 0.09, 'odd': 8.0},
                    {'name': '0-1', 'prob': 0.07, 'odd': 9.50}
                ],
                'odds': [11.0, 7.00, 8.00, 7.50],
                'dutching_odd': 2.08,
                'model_prob': '58.10%',
                'edge': '+20.85%',
                'raw_edge': 0.2085
            }
        ]
    return opps
