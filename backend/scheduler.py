import os
import json
import asyncio
from datetime import datetime
import pandas as pd
import numpy as np

from .data_loader import (
    DATA_DIR, sync_fixtures, load_league_data, get_all_available_leagues,
    get_api_token, load_upcoming_from_api
)
from .models import PoissonModel, estimate_bookmaker_odds
from .telegram_bot import (
    get_telegram_tips, add_telegram_tip, send_telegram_message, format_telegram_tip,
    get_telegram_arbitrage_tips, add_telegram_arbitrage_tip, format_telegram_arbitrage_tip
)
from .arbitrage_scanner import fetch_arbitrage_opportunities
CONFIG_PATH = os.path.join(DATA_DIR, 'telegram_scheduler_config.json')

DEFAULT_CONFIG = {
    "enabled": False,
    "check_interval_hours": 6,
    "leagues": ["E0", "SP1", "I1", "D1", "F1", "BRA"],
    "market": "home",
    "value_threshold": 1.05,
    "min_odds": 1.0,
    "max_odds": 50.0,
    "staking_rule": "fixed",
    "stake_value": 10.0,
    "initial_bankroll": 1000.0,
    "upcoming_source": "api"
}

def get_scheduler_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Ensure all default keys exist
                for k, v in DEFAULT_CONFIG.items():
                    if k not in config:
                        config[k] = v
                return config
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_scheduler_config(config):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    return config

async def run_automatic_tips_scan():
    config = get_scheduler_config()
    if not config.get("enabled"):
        return {"status": "skipped", "message": "O agendador de tips está desativado."}
        
    source = config.get("upcoming_source", "api")
    df_fixtures = pd.DataFrame()
    loop = asyncio.get_event_loop()
    
    # 1. Fetch from DataFootball API if chosen and token is present
    if source == 'api':
        token = get_api_token()
        if token:
            try:
                df_fixtures = await loop.run_in_executor(None, lambda: load_upcoming_from_api(token))
                if not df_fixtures.empty:
                    print("[Scheduler API] Loaded upcoming matches from DataFootball API webhook.")
                else:
                    print("[Scheduler API Fallback] DataFootball API returned no matches, falling back to CSV.")
            except Exception as e:
                print(f"[Scheduler API Error] {e}. Falling back to CSV.")
        else:
            print("[Scheduler API Fallback] No API token found, falling back to CSV.")
            
    # 2. Fallback to standard CSV if needed
    if df_fixtures.empty:
        try:
            await loop.run_in_executor(None, lambda: sync_fixtures(force=True))
        except Exception as e:
            print(f"[Scheduler Error] Falha ao sincronizar calendário de jogos: {e}")
            
        fixtures_path = os.path.join(DATA_DIR, "fixtures.csv")
        if os.path.exists(fixtures_path):
            try:
                df_fixtures = pd.read_csv(fixtures_path, encoding='latin1')
                df_fixtures.columns = [c.replace('ï»¿', '').replace('\ufeff', '').strip() for c in df_fixtures.columns]
                print("[Scheduler CSV] Loaded upcoming matches from local fixtures.csv.")
            except Exception as e:
                return {"status": "error", "message": f"Erro ao ler arquivo de jogos: {str(e)}"}
        else:
            return {"status": "skipped", "message": "Nenhum arquivo de jogos futuros encontrado."}
            
    poisson = PoissonModel()
    all_leagues = get_all_available_leagues()
    code_to_name = {l['code']: l['name'] for l in all_leagues}
    league_codes = [l['code'] for l in all_leagues]
    
    # Load settings from scheduler config
    target_leagues = config.get("leagues", [])
    markets_to_scan = config.get("market", "home")
    if isinstance(markets_to_scan, str):
        markets_to_scan = [markets_to_scan]
    value_threshold = config.get("value_threshold", 1.05)
    min_odds = config.get("min_odds", 1.0)
    max_odds = config.get("max_odds", 50.0)
    staking_rule = config.get("staking_rule", "fixed")
    stake_value = config.get("stake_value", 10.0)
    initial_bankroll = config.get("initial_bankroll", 1000.0)
    
    league_cache = {}
    sent_tips = get_telegram_tips()
    
    # Build a lookup set for sent tips to check duplicates in O(1)
    sent_lookup = set()
    for t in sent_tips:
        key = (t.get('home_team'), t.get('away_team'), t.get('market'), t.get('date'))
        sent_lookup.add(key)
        
    tips_to_send = []
    
    for row in df_fixtures.to_dict('records'):
        league_code = row.get('Div')
        if not league_code or league_code not in league_codes or league_code not in target_leagues:
            continue
            
        home_team = row.get('HomeTeam')
        away_team = row.get('AwayTeam')
        if pd.isna(home_team) or pd.isna(away_team):
            continue
            
        # Load league data to get ratings
        if league_code not in league_cache:
            try:
                hist_df = await loop.run_in_executor(None, lambda: load_league_data(league_code, start_date='2020-08-01'))
                league_cache[league_code] = hist_df
            except Exception:
                continue
                
        hist_df = league_cache[league_code]
        if hist_df.empty:
            continue
            
        try:
            match_date = pd.to_datetime(row.get('Date'), dayfirst=True)
            date_str = match_date.strftime('%Y-%m-%d')
        except Exception:
            date_str = str(row.get('Date'))
            match_date = datetime.now()
            
        # Predict outcome probabilities
        pred = poisson.predict_match(home_team, away_team, hist_df, match_date)
        
        # Map odds
        odds_h = float(row.get('B365H', np.nan))
        odds_d = float(row.get('B365D', np.nan))
        odds_a = float(row.get('B365A', np.nan))
        odds_over25 = float(row.get('B365>2.5', np.nan))
        odds_under25 = float(row.get('B365<2.5', np.nan))
        
        est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, pred['lambda_home'], pred['lambda_away'])
        
        for market in markets_to_scan:
            # Calculate EV Edge
            market_prob = 0.0
            bookie_odds = np.nan
            market_label = ""
            
            if market == 'home':
                market_prob = pred['prob_home']
                bookie_odds = odds_h
                market_label = "1 (Mandante)"
            elif market == 'away':
                market_prob = pred['prob_away']
                bookie_odds = odds_a
                market_label = "2 (Visitante)"
            elif market == 'draw':
                market_prob = pred['prob_draw']
                bookie_odds = odds_d
                market_label = "X (Empate)"
            elif market == 'over15':
                market_prob = pred['prob_over_15']
                bookie_odds = est_odds.get('bookie_over_15', np.nan)
                market_label = "Over 1.5"
            elif market == 'over25':
                market_prob = pred['prob_over_25']
                bookie_odds = odds_over25
                market_label = "Over 2.5"
            elif market == 'under25':
                market_prob = pred['prob_under_25']
                bookie_odds = odds_under25
                market_label = "Under 2.5"
            elif market == 'over35':
                market_prob = pred['prob_over_35']
                bookie_odds = est_odds.get('bookie_over_35', np.nan)
                market_label = "Over 3.5"
            elif market == 'under35':
                market_prob = pred['prob_under_35']
                bookie_odds = est_odds.get('bookie_under_35', np.nan)
                market_label = "Under 3.5"
            elif market == 'over45':
                market_prob = pred['prob_over_45']
                bookie_odds = est_odds.get('bookie_over_45', np.nan)
                market_label = "Over 4.5"
            elif market == 'under45':
                market_prob = pred['prob_under_45']
                bookie_odds = est_odds.get('bookie_under_45', np.nan)
                market_label = "Under 4.5"
            elif market == 'over55':
                market_prob = pred['prob_over_55']
                bookie_odds = est_odds.get('bookie_over_55', np.nan)
                market_label = "Over 5.5"
            elif market == 'under55':
                market_prob = pred['prob_under_55']
                bookie_odds = est_odds.get('bookie_under_55', np.nan)
                market_label = "Under 5.5"
            elif market == 'lay_home':
                market_prob = pred['prob_draw'] + pred['prob_away']
                bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan
                market_label = "Contra Mandante (X2)"
            elif market == 'lay_away':
                market_prob = pred['prob_home'] + pred['prob_draw']
                bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan
                market_label = "Contra Visitante (1X)"
            elif market == 'lay_draw':
                market_prob = pred['prob_home'] + pred['prob_away']
                bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_a) if (odds_h > 1.0 and odds_a > 1.0) else np.nan
                market_label = "Contra Empate (12)"
            elif market == 'btts_yes':
                market_prob = pred['prob_btts_yes']
                bookie_odds = est_odds.get('bookie_btts_yes', np.nan)
                market_label = "BTTS Sim"
            elif market == 'btts_no':
                market_prob = pred['prob_btts_no']
                bookie_odds = est_odds.get('bookie_btts_no', np.nan)
                market_label = "BTTS Não"
            elif market.startswith('cs_'):
                market_prob = pred.get(f"prob_{market}", 0.0)
                bookie_odds = est_odds.get(f"bookie_{market}", np.nan)
                market_label = f"Placar Exato {market[3]}-{market[4]}"
                
            if pd.isna(bookie_odds) or bookie_odds <= 1.0:
                continue
                
            ev = market_prob * bookie_odds
            is_tip = (ev >= value_threshold) and (min_odds <= bookie_odds <= max_odds)
            
            if not is_tip:
                continue
                
            # Check duplicate
            dup_key = (home_team, away_team, market_label, date_str)
            if dup_key in sent_lookup:
                continue
                
            # Calculate stake pct
            stake_pct = 0.0
            if staking_rule == 'kelly':
                f_star = (market_prob * bookie_odds - 1.0) / (bookie_odds - 1.0)
                stake_pct = max(0.0, f_star) * stake_value * 100.0
                stake_pct = min(stake_pct, 10.0)
            elif staking_rule == 'proportional':
                stake_pct = stake_value
            else:
                stake_pct = (stake_value / initial_bankroll) * 100.0
                
            league_name = code_to_name.get(league_code, league_code)
            time_str = str(row.get('Time')) if not pd.isna(row.get('Time')) else '00:00'
            
            tips_to_send.append({
                'league_name': league_name,
                'date_str': date_str,
                'time_str': time_str,
                'home_team': home_team,
                'away_team': away_team,
                'market_label': market_label,
                'prob': market_prob * 100.0,
                'fair_odds': 1.0 / market_prob if market_prob > 0 else 99.0,
                'bookie_odds': bookie_odds,
                'ev': ev,
                'stake_pct': stake_pct
            })
            
    # Apply concurrent bet penalization (Freio de Variância) grouped by date
    from collections import defaultdict
    import math
    
    date_counts = defaultdict(int)
    for tip in tips_to_send:
        date_counts[tip['date_str']] += 1
        
    for tip in tips_to_send:
        n_bets = date_counts[tip['date_str']]
        if n_bets > 1:
            tip['stake_pct'] = round(tip['stake_pct'] / math.sqrt(n_bets), 2)
            
    # Send tips to Telegram
    sent_count = 0
    for tip in tips_to_send:
        # Formulate telegram alert
        msg_text = format_telegram_tip(
            tip['league_name'], tip['date_str'], tip['time_str'],
            tip['home_team'], tip['away_team'], tip['market_label'],
            tip['prob'], tip['fair_odds'], tip['bookie_odds'],
            tip['ev'], tip['stake_pct']
        )
        ok, msg = send_telegram_message(msg_text)
        if ok:
            # Save in local JSON log
            add_telegram_tip(
                tip['league_name'], tip['date_str'], tip['time_str'],
                tip['home_team'], tip['away_team'], tip['market_label'],
                tip['bookie_odds'], tip['stake_pct']
            )
            sent_count += 1
            await asyncio.sleep(1.0)
        else:
            print(f"[Scheduler Telegram Alert Error]: {msg}")
            
    return {
        "status": "success",
        "scanned": len(df_fixtures),
        "found_tips": len(tips_to_send),
        "sent_tips": sent_count
    }

async def run_scheduler_loop():
    print("[Scheduler Startup] Iniciando robô automático de tips...")
    while True:
        try:
            config = get_scheduler_config()
            enabled = config.get("enabled", False)
            interval_hours = config.get("check_interval_hours", 6)
            
            if enabled:
                print(f"[Scheduler Run] Iniciando varredura agendada de novos jogos...")
                res = await run_automatic_tips_scan()
                print(f"[Scheduler Complete] Resultado: {res}")
            
            # Wait for next interval
            await asyncio.sleep(interval_hours * 3600)
            
        except asyncio.CancelledError:
            print("[Scheduler Shutdown] Robô automático de tips finalizado.")
            break
        except Exception as e:
            print(f"[Scheduler Exception] Ocorreu um erro no loop: {e}")
            await asyncio.sleep(600)

ARB_CONFIG_PATH = os.path.join(DATA_DIR, 'telegram_arbitrage_config.json')

DEFAULT_ARB_CONFIG = {
    "enabled": False,
    "check_interval_hours": 1.0,
    "min_profit_pct": 0.5
}

def get_arbitrage_scheduler_config():
    if os.path.exists(ARB_CONFIG_PATH):
        try:
            with open(ARB_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                for k, v in DEFAULT_ARB_CONFIG.items():
                    if k not in config:
                        config[k] = v
                return config
        except Exception:
            pass
    return DEFAULT_ARB_CONFIG.copy()

def save_arbitrage_scheduler_config(config):
    os.makedirs(os.path.dirname(ARB_CONFIG_PATH), exist_ok=True)
    with open(ARB_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    return config

async def run_automatic_arbitrage_scan():
    config = get_arbitrage_scheduler_config()
    if not config.get("enabled"):
        return {"status": "skipped", "message": "Robô de arbitragem desativado."}
        
    loop = asyncio.get_event_loop()
    min_profit = config.get("min_profit_pct", 0.5)
    
    try:
        # Puxar oportunidades
        opps = await loop.run_in_executor(None, fetch_arbitrage_opportunities)
    except Exception as e:
        return {"status": "error", "message": f"Erro ao buscar arbitragem: {e}"}
        
    if not opps:
        return {"status": "success", "message": "Nenhuma arbitragem encontrada."}
        
    sent_tips = get_telegram_arbitrage_tips()
    sent_lookup = set()
    for t in sent_tips:
        key = (t.get('match'), t.get('date'))
        sent_lookup.add(key)
        
    sent_count = 0
    
    for opp in opps:
        profit = opp.get('profit_margin', 0)
        if profit < min_profit:
            continue
            
        match_name = opp.get('match')
        match_date = opp.get('date')
        
        dup_key = (match_name, match_date)
        if dup_key in sent_lookup:
            continue
            
        msg_text = format_telegram_arbitrage_tip(
            match_name, match_date, opp.get('bookmakers', {}), profit,
            market_name=opp.get('market', 'Match Odds (1X2)'),
            is_2_way=opp.get('is_2_way', False),
            labels_dict=opp.get('labels', None)
        )
        
        ok, msg = send_telegram_message(msg_text)
        if ok:
            add_telegram_arbitrage_tip(match_name, match_date, profit)
            sent_lookup.add(dup_key)
            sent_count += 1
            await asyncio.sleep(1.0)
            
    return {
        "status": "success",
        "found": len(opps),
        "sent": sent_count
    }

async def run_arbitrage_scheduler_loop():
    print("[Arbitrage Scheduler Startup] Iniciando robô de arbitragem...")
    while True:
        try:
            config = get_arbitrage_scheduler_config()
            enabled = config.get("enabled", False)
            interval_hours = config.get("check_interval_hours", 1.0)
            
            if enabled:
                print(f"[Arbitrage Scheduler Run] Buscando novas surebets...")
                res = await run_automatic_arbitrage_scan()
                print(f"[Arbitrage Scheduler Complete] Resultado: {res}")
            
            # Wait for next interval
            await asyncio.sleep(interval_hours * 3600)
            
        except asyncio.CancelledError:
            print("[Arbitrage Scheduler Shutdown] Robô de arbitragem finalizado.")
            break
        except Exception as e:
            print(f"[Arbitrage Scheduler Exception] Erro no loop: {e}")
            await asyncio.sleep(600)



async def run_live_odds_tracker_loop():
    import asyncio
    from .live_odds_tracker import fetch_and_update_live_odds
    while True:
        try:
            # Run blocking I/O in thread pool
            await asyncio.to_thread(fetch_and_update_live_odds)
        except Exception as e:
            print(f'[Live Odds Tracker] Erro no loop: {e}')
        # Run every 30 minutes
        await asyncio.sleep(1800)
