import os
import json
import asyncio
import logging
import time
import tempfile
import threading

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
STATE_FILE = os.path.join(DATA_DIR, 'scheduler_state.json')

_state_lock = threading.Lock()

def _read_state():
    """Read scheduler state dict. Returns {} if file missing or corrupt."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("scheduler_state.json corrompido, resetando estado.")
        return {}

def _write_state(state):
    """Atomic write: temp file + os.replace to prevent corruption on crash."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(STATE_FILE), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(state, f)
            os.replace(tmp_path, STATE_FILE)
        except Exception:
            os.unlink(tmp_path)
            raise
    except OSError:
        # Fallback: direct write if tempfile fails
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f)

def get_last_run(task_name):
    """Return last successful run timestamp for task_name (0.0 if never)."""
    with _state_lock:
        return _read_state().get(task_name, 0.0)

def set_last_run(task_name, timestamp):
    """Record successful run timestamp (atomic, thread-safe)."""
    with _state_lock:
        state = _read_state()
        state[task_name] = timestamp
        _write_state(state)

def mark_scan_attempt(task_name):
    """Record attempt timestamp BEFORE running scan. Used for crash recovery.
    Returns (can_run: bool, last_success: float).
    """
    with _state_lock:
        state = _read_state()
        last_attempt = state.get(f"{task_name}_attempt", 0.0)
        last_success = state.get(task_name, 0.0)
        now = time.time()
        # Only block if an attempt was made recently (< 60s ago) without success
        if last_attempt > last_success and (now - last_attempt) < 60:
            return False, last_success
        state[f"{task_name}_attempt"] = now
        _write_state(state)
        return True, last_success

from datetime import datetime
import pandas as pd
import numpy as np

from .data_loader import (
    DATA_DIR, sync_fixtures, load_league_data, get_all_available_leagues,
    get_api_token, load_upcoming_from_api, auto_detect_data_source
)
from .models import PoissonModel, estimate_bookmaker_odds
from .constants import RHO_FALLBACK
from .telegram_bot import (
    get_telegram_tips, add_telegram_tip, send_telegram_message, format_telegram_tip,
    get_telegram_arbitrage_tips, add_telegram_arbitrage_tip, format_telegram_arbitrage_tip,
    get_telegram_dutching_tips, add_telegram_dutching_tip, format_telegram_dutching_tip
)
from .arbitrage_scanner import fetch_arbitrage_opportunities
from .dutching_scanner import fetch_dutching_opportunities
CONFIG_PATH = os.path.join(DATA_DIR, 'telegram_scheduler_config.json')

DEFAULT_CONFIG = {
    "enabled": False,
    "mode": "manual",
    "check_interval_hours": 6,
    "leagues": ["E0", "SP1", "I1", "D1", "F1", "E1", "E2", "E3", "SP2", "I2",
                "D2", "F2", "N1", "B1", "P1", "T1", "G1", "SC0", "SC1",
                "BRA", "ARG", "USA", "MEX", "JPN", "SWEDEN_ALLSVENSKAN", "NORWAY_ELITESERIEN"],
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
                    logger.info("Loaded upcoming matches from DataFootball API webhook.")
                else:
                    logger.warning("DataFootball API returned no matches, falling back to CSV.")
            except Exception as e:
                logger.error(f"DataFootball API error: {e}. Falling back to CSV.", exc_info=True)
        else:
            logger.warning("No API token found, falling back to CSV.")
            
    # 2. Fallback to standard CSV if needed
    if df_fixtures.empty:
        try:
            await loop.run_in_executor(None, lambda: sync_fixtures(force=True))
        except Exception as e:
            logger.error(f"Falha ao sincronizar calendário de jogos: {e}", exc_info=True)
            
        fixtures_path = os.path.join(DATA_DIR, "fixtures.csv")
        if os.path.exists(fixtures_path):
            try:
                df_fixtures = pd.read_csv(fixtures_path, encoding='latin1')
                df_fixtures.columns = [c.replace('ï»¿', '').replace('\ufeff', '').strip() for c in df_fixtures.columns]
                logger.info("Loaded upcoming matches from local fixtures.csv.")
            except Exception as e:
                return {"status": "error", "message": f"Erro ao ler arquivo de jogos: {str(e)}"}
        else:
            return {"status": "skipped", "message": "Nenhum arquivo de jogos futuros encontrado."}
            

    mode = config.get("mode", "manual")
    sent_tips = get_telegram_tips()
    sent_lookup = set()
    for t in sent_tips:
        key = (t.get('home_team'), t.get('away_team'), t.get('market'), t.get('date'))
        sent_lookup.add(key)
        
    tips_to_send = []
    
    if mode == "autopilot":
        try:
            from .app import get_autopilot_predictions
            # Get autopilot matches (they are already sorted and checked for EV/odds)
            auto_matches = get_autopilot_predictions(source)
            for m in auto_matches:
                tips_to_send.append({
                    'league_name': m['league_name'],
                    'date_str': m['date'],
                    'time_str': m['time'],
                    'home_team': m['home_team'],
                    'away_team': m['away_team'],
                    'market_label': m['market_label'],
                    'prob': m['prob'],
                    'fair_odds': m['fair_odds'],
                    'bookie_odds': m['bookie_odds'],
                    'ev': m['ev'],
                    'stake_pct': m['stake_pct']
                })
        except Exception as e:
            logger.error(f"Autopilot error: {e}", exc_info=True)

    # Gather active strategies and portfolios from history database
    from .history_manager import load_history
    saved_strategies = load_history() or []
    
    active_portfolios = [s for s in saved_strategies if (s.get('type') == 'portfolio' or 'strategy_ids' in s.get('params', {})) and s.get('is_tg_active') == True]
    active_portfolio_strategy_ids = set()
    for p_item in active_portfolios:
        ids = p_item.get('params', {}).get('strategy_ids', [])
        active_portfolio_strategy_ids.update(ids)
        
    active_individual_strategies = [s for s in saved_strategies if s.get('type') != 'portfolio' and 'strategy_ids' not in s.get('params', {}) and s.get('is_tg_active') == True]
    
    history_strategies_to_process = []
    for s in saved_strategies:
        if s.get('id') in active_portfolio_strategy_ids or s.get('id') in [x.get('id') for x in active_individual_strategies]:
            if s not in history_strategies_to_process:
                history_strategies_to_process.append(s)

    run_manual_scan = (mode == "manual")
    run_history_scan = len(history_strategies_to_process) > 0

    if run_manual_scan or run_history_scan:
        poisson = PoissonModel()
        all_leagues = get_all_available_leagues()
        code_to_name = {l['code']: l['name'] for l in all_leagues}
        league_codes = [l['code'] for l in all_leagues]
        
        # Manual configuration parameters
        target_leagues_manual = config.get("leagues", [])
        markets_to_scan_manual = config.get("market", "home")
        if isinstance(markets_to_scan_manual, str):
            markets_to_scan_manual = [markets_to_scan_manual]
        value_threshold_manual = config.get("value_threshold", 1.05)
        min_odds_manual = config.get("min_odds", 1.0)
        max_odds_manual = config.get("max_odds", 50.0)
        staking_rule_manual = config.get("staking_rule", "fixed")
        stake_value_manual = config.get("stake_value", 10.0)
        initial_bankroll_manual = config.get("initial_bankroll", 1000.0)
        
        league_cache = {}

        def get_market_prob_and_odds(market_code, pr, est, h_odds, d_odds, a_odds, o25_odds, u25_odds):
            m_prob = 0.0
            b_odds = np.nan
            m_label = ""
            
            if market_code == 'home':
                m_prob = pr['prob_home']
                b_odds = h_odds
                m_label = "1 (Mandante)"
            elif market_code == 'away':
                m_prob = pr['prob_away']
                b_odds = a_odds
                m_label = "2 (Visitante)"
            elif market_code == 'draw':
                m_prob = pr['prob_draw']
                b_odds = d_odds
                m_label = "X (Empate)"
            elif market_code == 'over15':
                m_prob = pr['prob_over_15']
                b_odds = est.get('bookie_over_15', np.nan)
                m_label = "Over 1.5"
            elif market_code == 'over25':
                m_prob = pr['prob_over_25']
                b_odds = o25_odds
                m_label = "Over 2.5"
            elif market_code == 'under25':
                m_prob = pr['prob_under_25']
                b_odds = u25_odds
                m_label = "Under 2.5"
            elif market_code == 'over35':
                m_prob = pr['prob_over_35']
                b_odds = est.get('bookie_over_35', np.nan)
                m_label = "Over 3.5"
            elif market_code == 'under35':
                m_prob = pr['prob_under_35']
                b_odds = est.get('bookie_under_35', np.nan)
                m_label = "Under 3.5"
            elif market_code == 'over45':
                m_prob = pr['prob_over_45']
                b_odds = est.get('bookie_over_45', np.nan)
                m_label = "Over 4.5"
            elif market_code == 'under45':
                m_prob = pr['prob_under_45']
                b_odds = est.get('bookie_under_45', np.nan)
                m_label = "Under 4.5"
            elif market_code == 'over55':
                m_prob = pr['prob_over_55']
                b_odds = est.get('bookie_over_55', np.nan)
                m_label = "Over 5.5"
            elif market_code == 'under55':
                m_prob = pr['prob_under_55']
                b_odds = est.get('bookie_under_55', np.nan)
                m_label = "Under 5.5"
            elif market_code == 'btts_yes':
                m_prob = pr['prob_btts_yes']
                b_odds = est.get('bookie_btts_yes', np.nan)
                m_label = "BTTS Sim"
            elif market_code == 'btts_no':
                m_prob = pr['prob_btts_no']
                b_odds = est.get('bookie_btts_no', np.nan)
                m_label = "BTTS Não"
            elif market_code.startswith('cs_'):
                m_prob = pr.get(f"prob_{market_code}", 0.0)
                b_odds = est.get(f"bookie_{market_code}", np.nan)
                m_label = f"Placar Exato {market_code[3]}-{market_code[4]}"
            elif market_code == 'lay_home':
                m_prob = pr['prob_draw'] + pr['prob_away']
                b_odds = 1.0 / (1.0/d_odds + 1.0/a_odds) if (d_odds > 1.0 and a_odds > 1.0) else np.nan
                m_label = "Contra Mandante (X2)"
            elif market_code == 'lay_away':
                m_prob = pr['prob_home'] + pr['prob_draw']
                b_odds = 1.0 / (1.0/h_odds + 1.0/d_odds) if (h_odds > 1.0 and d_odds > 1.0) else np.nan
                m_label = "Contra Visitante (1X)"
            elif market_code == 'lay_draw':
                m_prob = pr['prob_home'] + pr['prob_away']
                b_odds = 1.0 / (1.0/h_odds + 1.0/a_odds) if (h_odds > 1.0 and a_odds > 1.0) else np.nan
                m_label = "Contra Empate (12)"
                
            return m_prob, b_odds, m_label

        def calculate_stake_pct(rule, val, bankroll, prob, odds, mkt=''):
            pct = 0.0
            if rule == 'kelly':
                if mkt.startswith('lay_'):
                    f_star = prob / (odds - 1.0) - (1.0 - prob)
                else:
                    f_star = (prob * odds - 1.0) / (odds - 1.0)
                pct = max(0.0, f_star) * val * 100.0
                pct = min(pct, 10.0)
            elif rule == 'proportional':
                pct = val
            else:
                pct = (val / bankroll) * 100.0
            return pct

        for row in df_fixtures.to_dict('records'):
            league_code = row.get('Div')
            if not league_code or league_code not in league_codes:
                continue
                
            home_team = row.get('HomeTeam')
            away_team = row.get('AwayTeam')
            if pd.isna(home_team) or pd.isna(away_team):
                continue
                
            # Load league data
            if league_code not in league_cache:
                try:
                    _ds = auto_detect_data_source(league_code)
                    hist_df = await loop.run_in_executor(None, lambda: load_league_data(league_code, start_date='2020-08-01', data_source=_ds))
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
            
            est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, pred['lambda_home'], pred['lambda_away'], pred.get('rho', RHO_FALLBACK))
            
            # Sub-run 1: Manual Scan
            if run_manual_scan and league_code in target_leagues_manual:
                for market in markets_to_scan_manual:
                    m_prob, b_odds, m_label = get_market_prob_and_odds(market, pred, est_odds, odds_h, odds_d, odds_a, odds_over25, odds_under25)
                    if pd.isna(b_odds) or b_odds <= 1.0:
                        continue
                        
                    ev = m_prob * b_odds
                    is_tip = (ev >= value_threshold_manual) and (min_odds_manual <= b_odds <= max_odds_manual)
                    if not is_tip:
                        continue
                        
                    dup_key = (home_team, away_team, f"{m_label} (Manual)", date_str)
                    if dup_key in sent_lookup:
                        continue
                        
                    stake_pct = calculate_stake_pct(staking_rule_manual, stake_value_manual, initial_bankroll_manual, m_prob, b_odds, market)
                    
                    league_name = code_to_name.get(league_code, league_code)
                    time_str = str(row.get('Time')) if not pd.isna(row.get('Time')) else '00:00'
                    
                    tips_to_send.append({
                        'league_name': league_name,
                        'date_str': date_str,
                        'time_str': time_str,
                        'home_team': home_team,
                        'away_team': away_team,
                        'market_label': f"{m_label} (Manual)",
                        'prob': m_prob * 100.0,
                        'fair_odds': 1.0 / m_prob if m_prob > 0 else 99.0,
                        'bookie_odds': b_odds,
                        'ev': ev,
                        'stake_pct': stake_pct
                    })
            
            # Sub-run 2: History Strategies Scan
            if run_history_scan:
                for strategy in history_strategies_to_process:
                    params = strategy.get('params', {})
                    target_leagues = params.get('leagues', [])
                    if league_code not in target_leagues:
                        continue
                        
                    s_markets_raw = params.get('markets') or params.get('market', 'home')
                    if isinstance(s_markets_raw, str):
                        s_markets = [m.strip() for m in s_markets_raw.split(',')]
                    elif isinstance(s_markets_raw, list):
                        s_markets = [str(m).strip() for m in s_markets_raw]
                    else:
                        s_markets = ['home']
                        
                    val_threshold = float(params.get('valueThreshold') or params.get('valThreshold', 1.05))
                    min_odds = float(params.get('minOdds', 1.0))
                    max_odds = float(params.get('maxOdds', 50.0))
                    
                    # Override risk management parameters if active portfolio is present
                    containing_portfolio = next((p_item for p_item in active_portfolios if strategy.get('id') in p_item.get('params', {}).get('strategy_ids', [])), None) if active_portfolios else None
                    
                    if containing_portfolio:
                        port_params = containing_portfolio.get('params', {})
                        portfolio_risk = port_params.get('risk_method', 'fixed_2.0')
                        portfolio_bankroll = float(port_params.get('initial_bankroll', 1000.0))
                        
                        if portfolio_risk.startswith('fixed_'):
                            try:
                                pct = float(portfolio_risk.split('_')[1])
                            except:
                                pct = 2.0
                            staking_rule = 'fixed'
                            stake_value = pct
                        elif portfolio_risk == 'fixed':
                            staking_rule = 'fixed'
                            stake_value = 2.0
                        elif portfolio_risk == 'kelly_quarter':
                            staking_rule = 'kelly'
                            stake_value = 0.25
                        else:
                            staking_rule = 'fixed'
                            stake_value = 2.0
                            
                        initial_bankroll = portfolio_bankroll
                    else:
                        staking_rule = params.get('stakingRule', 'fixed')
                        stake_value = float(params.get('stakeValue', 10.0))
                        initial_bankroll = float(params.get('initialBankroll', 1000.0))
                        
                    for market in s_markets:
                        m_prob, b_odds, m_label = get_market_prob_and_odds(market, pred, est_odds, odds_h, odds_d, odds_a, odds_over25, odds_under25)
                        if pd.isna(b_odds) or b_odds <= 1.0:
                            continue
                            
                        ev = m_prob * b_odds
                        is_tip = (ev >= val_threshold) and (min_odds <= b_odds <= max_odds)
                        if not is_tip:
                            continue
                            
                        strategy_name = strategy.get('name', 'Estratégia Salva')
                        if containing_portfolio:
                            market_label_text = f"{m_label} (Portfólio: {containing_portfolio.get('name')} | Estratégia: {strategy_name})"
                        else:
                            market_label_text = f"{m_label} (Estratégia: {strategy_name})"
                            
                        dup_key = (home_team, away_team, market_label_text, date_str)
                        if dup_key in sent_lookup:
                            continue
                            
                        stake_pct = calculate_stake_pct(staking_rule, stake_value, initial_bankroll, m_prob, b_odds, market)
                        
                        league_name = code_to_name.get(league_code, league_code)
                        time_str = str(row.get('Time')) if not pd.isna(row.get('Time')) else '00:00'
                        
                        tips_to_send.append({
                            'league_name': league_name,
                            'date_str': date_str,
                            'time_str': time_str,
                            'home_team': home_team,
                            'away_team': away_team,
                            'market_label': market_label_text,
                            'prob': m_prob * 100.0,
                            'fair_odds': 1.0 / m_prob if m_prob > 0 else 99.0,
                            'bookie_odds': b_odds,
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
            logger.error(f"Telegram alert failed: {msg}")
            
    return {
        "status": "success",
        "scanned": len(df_fixtures),
        "found_tips": len(tips_to_send),
        "sent_tips": sent_count
    }

async def _run_generic_scheduler_loop(task_name, scan_func, get_config_func=None,
                                       interval_seconds=None, error_sleep=600,
                                       log_labels=None):
    """Generic scheduler loop — single implementation for all 4 scheduler types.

    Args:
        task_name: key for mark_scan_attempt / set_last_run (e.g. "tips_scan")
        scan_func: async callable that runs the scan
        get_config_func: callable returning dict with "enabled" and "check_interval_hours" keys.
                         If None, the scheduler is always enabled with the given interval_seconds.
        interval_seconds: fallback interval when get_config_func is None
        error_sleep: seconds to sleep on unexpected Exception
        log_labels: dict of log strings with keys: startup, scanning, done, scan_error, loop_error, cancelled
    """
    if log_labels is None:
        log_labels = {}
    startup = log_labels.get('startup', f'{task_name} scheduler iniciado.')
    scanning = log_labels.get('scanning', f'Iniciando {task_name}...')
    done = log_labels.get('done', f'{task_name} concluída:')
    scan_error = log_labels.get('scan_error', f'{task_name} falhou:')
    loop_error = log_labels.get('loop_error', f'Erro no loop {task_name}:')
    cancelled = log_labels.get('cancelled', f'{task_name} scheduler finalizado.')

    logger.info(startup)
    while True:
        try:
            if get_config_func is not None:
                config = get_config_func()
                enabled = config.get("enabled", False)
                interval_hours = config.get("check_interval_hours", 6)
                interval = interval_hours * 3600
            else:
                enabled = True
                interval = interval_seconds or 1800

            if enabled:
                can_run, last_success = mark_scan_attempt(task_name)
                time_since_last = time.time() - last_success
                if can_run and time_since_last >= interval:
                    logger.info(scanning)
                    try:
                        res = await scan_func()
                        set_last_run(task_name, time.time())
                        if res is not None:
                            logger.info(f"{done} {res}")
                    except Exception as e:
                        logger.error(f"{scan_error} {e}", exc_info=True)
                    await asyncio.sleep(max(interval - (time.time() - last_success), 60))
                else:
                    remaining = max(interval - time_since_last, 60)
                    await asyncio.sleep(remaining)
            else:
                await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info(cancelled)
            break
        except Exception as e:
            logger.error(f"{loop_error} {e}", exc_info=True)
            await asyncio.sleep(error_sleep)

async def run_scheduler_loop():
    await _run_generic_scheduler_loop(
        task_name="tips_scan",
        scan_func=run_automatic_tips_scan,
        get_config_func=get_scheduler_config,
        log_labels={
            "startup": "Scheduler iniciado.",
            "scanning": "Iniciando varredura agendada...",
            "done": "Varredura concluída:",
            "scan_error": "Varredura falhou:",
            "loop_error": "Erro no loop do scheduler:",
            "cancelled": "Scheduler finalizado.",
        }
    )

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
        gross_profit = opp.get('profit_margin', 0)
        net_profit = opp.get('profit_margin_net', gross_profit)

        # Use net profit (after slippage + commission) for the filter
        if net_profit < min_profit:
            continue

        match_name = opp.get('match')
        match_date = opp.get('date')

        dup_key = (match_name, match_date)
        if dup_key in sent_lookup:
            continue

        msg_text = format_telegram_arbitrage_tip(
            match_name, match_date, opp.get('bookmakers', {}), gross_profit,
            market_name=opp.get('market', 'Match Odds (1X2)'),
            is_2_way=opp.get('is_2_way', False),
            labels_dict=opp.get('labels', None),
            odds_dict=opp.get('odds', {}),
            net_profit=round(net_profit, 2),
            quality_score=opp.get('quality_score'),
            sport_key=opp.get('sport_key', ''),
        )
        
        ok, msg = send_telegram_message(msg_text)
        if ok:
            add_telegram_arbitrage_tip(match_name, match_date, round(net_profit, 2))
            sent_lookup.add(dup_key)
            sent_count += 1
            await asyncio.sleep(1.0)
            
    return {
        "status": "success",
        "found": len(opps),
        "sent": sent_count
    }

async def run_arbitrage_scheduler_loop():
    await _run_generic_scheduler_loop(
        task_name="arbitrage_scan",
        scan_func=run_automatic_arbitrage_scan,
        get_config_func=get_arbitrage_scheduler_config,
        log_labels={
            "startup": "Arbitrage scheduler iniciado.",
            "scanning": "Buscando novas surebets...",
            "done": "Arbitrage varredura concluída:",
            "scan_error": "Arbitrage scan falhou:",
            "loop_error": "Erro no loop de arbitragem:",
            "cancelled": "Arbitrage scheduler finalizado.",
        }
    )



async def run_live_odds_tracker_loop():
    from .live_odds_tracker import fetch_and_update_live_odds
    await _run_generic_scheduler_loop(
        task_name="live_odds_scan",
        scan_func=lambda: asyncio.to_thread(fetch_and_update_live_odds),
        interval_seconds=1800,
        error_sleep=60,
        log_labels={
            "startup": "Live Odds Tracker iniciado.",
            "scanning": "Atualizando odds ao vivo...",
            "done": "Live Odds atualizados com sucesso.",
            "scan_error": "Live Odds scan falhou:",
            "loop_error": "Erro no Live Odds Tracker:",
            "cancelled": "Live Odds Tracker cancelado.",
        }
    )


DUTCH_CONFIG_PATH = os.path.join(DATA_DIR, 'telegram_dutching_config.json')

DEFAULT_DUTCH_CONFIG = {
    "enabled": False,
    "check_interval_hours": 1.0,
    "min_edge_pct": 1.0,
    "min_hours_before": 2.0
}

def get_dutching_scheduler_config():
    if os.path.exists(DUTCH_CONFIG_PATH):
        try:
            with open(DUTCH_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                for k, v in DEFAULT_DUTCH_CONFIG.items():
                    if k not in config:
                        config[k] = v
                return config
        except Exception:
            pass
    return DEFAULT_DUTCH_CONFIG.copy()

def save_dutching_scheduler_config(config):
    os.makedirs(os.path.dirname(DUTCH_CONFIG_PATH), exist_ok=True)
    with open(DUTCH_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    return config

async def run_automatic_dutching_scan():
    config = get_dutching_scheduler_config()
    if not config.get("enabled"):
        return {"status": "skipped", "message": "Robô de Dutching desativado."}
        
    loop = asyncio.get_event_loop()
    min_edge = config.get("min_edge_pct", 1.0)
    min_hours_before = config.get("min_hours_before", 2.0)
    import os
    from dotenv import load_dotenv
    load_dotenv()
    token = get_api_token() or os.getenv('THE_ODDS_API_KEY')
    
    try:
        # Puxar oportunidades via The Odds API (live)
        opps = await loop.run_in_executor(None, lambda: fetch_dutching_opportunities(api_key=token, source='odds_api', strategy='auto_ia', data_source='auto'))
    except Exception as e:
        return {"status": "error", "message": f"Erro ao buscar Dutching: {e}"}
        
    if not opps:
        return {"status": "success", "message": "Nenhuma oportunidade de Dutching encontrada."}
        
    sent_tips = get_telegram_dutching_tips()
    sent_lookup = set()
    for t in sent_tips:
        key = (t.get('match'), t.get('date'))
        sent_lookup.add(key)
        
    sent_count = 0
    
    for opp in opps:
        edge_pct = opp.get('raw_edge', 0.0) * 100.0
        if edge_pct < min_edge:
            continue
            
        match_name = opp.get('match')
        match_date = opp.get('date')
        
        # Filtro de antecedência mínima
        try:
            match_dt = datetime.strptime(match_date, "%d/%m/%Y %H:%M")
            time_diff = (match_dt - datetime.now()).total_seconds() / 3600.0
        except Exception:
            time_diff = 999.0
            
        if time_diff < min_hours_before:
            continue
            
        dup_key = (match_name, match_date)
        if dup_key in sent_lookup:
            continue
            
        msg_text = format_telegram_dutching_tip(
            match_name, match_date, opp.get('bookmaker'), opp.get('market'),
            opp.get('selections'), opp.get('odds'), opp.get('dutching_odd'),
            opp.get('model_prob'), opp.get('edge')
        )
        
        ok, msg = send_telegram_message(msg_text)
        if ok:
            add_telegram_dutching_tip(match_name, match_date, edge_pct)
            sent_lookup.add(dup_key)
            sent_count += 1
            await asyncio.sleep(1.0)
            
    return {
        "status": "success",
        "found": len(opps),
        "sent": sent_count
    }

async def run_dutching_scheduler_loop():
    await _run_generic_scheduler_loop(
        task_name="dutching_scan",
        scan_func=run_automatic_dutching_scan,
        get_config_func=get_dutching_scheduler_config,
        log_labels={
            "startup": "Dutching scheduler iniciado.",
            "scanning": "Buscando novas oportunidades de Dutching...",
            "done": "Dutching varredura concluída:",
            "scan_error": "Dutching scan falhou:",
            "loop_error": "Erro no loop de Dutching:",
            "cancelled": "Dutching scheduler finalizado.",
        }
    )
