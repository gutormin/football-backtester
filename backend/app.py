import os
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Union

from .data_loader import (
    sync_data, get_all_available_leagues, load_league_data, DATA_DIR, sync_fixtures,
    get_api_token, load_upcoming_from_api
)
from .backtester import ChronologicalBacktester
from .smart_money import SmartMoneyBacktester
from .models import PoissonModel, estimate_bookmaker_odds
from .elo_model import build_elo_tracker_from_history
from .telegram_bot import (
    get_telegram_config, save_telegram_config, send_test_message,
    send_telegram_message, format_telegram_tip, get_telegram_tips,
    add_telegram_tip, update_telegram_tip_status, clear_telegram_tips
)
from .history_manager import load_history, add_strategy, delete_strategy
from .scheduler import (
    get_scheduler_config, save_scheduler_config,
    run_automatic_tips_scan, run_scheduler_loop,
    run_arbitrage_scheduler_loop, get_arbitrage_scheduler_config, save_arbitrage_scheduler_config,
    run_live_odds_tracker_loop
)
from .ai_predictor import apply_fdr_correction, compute_edge_quality_score
import math
import json
import numpy as np
import pandas as pd
from datetime import datetime

app = FastAPI(title="Sports Betting Backtester API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    print("Starting background scheduler...")
    asyncio.create_task(run_scheduler_loop())
    asyncio.create_task(run_arbitrage_scheduler_loop())
    asyncio.create_task(run_live_odds_tracker_loop())

# Request schema for Backtest
class BacktestRequest(BaseModel):
    leagues: List[str]
    startDate: str
    endDate: str
    market: Union[List[str], str]
    valueThreshold: float
    initialBankroll: float
    stakingRule: str
    stakeValue: float
    oddsSource: str
    minOdds: Optional[float] = 1.0
    maxOdds: Optional[float] = 50.0
    exchange_commission: float = 0.0
    out_of_sample: bool = False
    use_ml: bool = False
    data_source: str = "footballdata"
    futpython_api_key: str = ""
    minOddsH: Optional[float] = None
    maxOddsH: Optional[float] = None
    minOddsD: Optional[float] = None
    maxOddsD: Optional[float] = None
    minOddsA: Optional[float] = None
    maxOddsA: Optional[float] = None
    minOddsOver25: Optional[float] = None
    maxOddsOver25: Optional[float] = None
    minOddsUnder25: Optional[float] = None
    maxOddsUnder25: Optional[float] = None

@app.get("/api/leagues")
def list_leagues(source: str = "footballdata"):
    try:
        return get_all_available_leagues(source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sync")
def trigger_sync(source: str = "csv"):
    try:
        sync_data(force=False, source=source)
        return {"status": "success", "message": f"Dados sincronizados via {source.upper()} com sucesso."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status")
def get_status():
    try:
        if not os.path.exists(DATA_DIR):
            return {"synced": False, "files_count": 0, "last_updated": None}
            
        files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
        if not files:
            return {"synced": False, "files_count": 0, "last_updated": None}
            
        # Get the latest file modification time
        latest_file = max([os.path.join(DATA_DIR, f) for f in files])
        mtime = os.path.getmtime(latest_file)
        last_updated = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        return {
            "synced": True,
            "files_count": len(files),
            "last_updated": last_updated
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/backtest")
def run_backtest(req: BacktestRequest):
    try:
        backtester = ChronologicalBacktester()

        results = backtester.run(
            leagues=req.leagues,
            start_date=req.startDate,
            end_date=req.endDate,
            market=req.market,
            value_threshold=req.valueThreshold,
            initial_bankroll=req.initialBankroll,
            staking_rule=req.stakingRule,
            stake_value=req.stakeValue,
            odds_source=req.oddsSource,
            min_odds=req.minOdds or 1.0,
            max_odds=req.maxOdds or 50.0,
            exchange_commission=req.exchange_commission,
            use_ml=req.use_ml,
            data_source=req.data_source,
            futpython_api_key=req.futpython_api_key,
            min_odds_h=req.minOddsH,
            max_odds_h=req.maxOddsH,
            min_odds_d=req.minOddsD,
            max_odds_d=req.maxOddsD,
            min_odds_a=req.minOddsA,
            max_odds_a=req.maxOddsA,
            min_odds_over25=req.minOddsOver25,
            max_odds_over25=req.maxOddsOver25,
            min_odds_under25=req.minOddsUnder25,
            max_odds_under25=req.maxOddsUnder25
        )
        if "error" in results:
            raise HTTPException(status_code=400, detail=results["error"])
            
        summary = results.get('summary', {})
        results['edge_quality'] = compute_edge_quality_score(summary, summary.get('oos_summary'))
        
        # If user explicitly requested OOS logic in frontend, it is now seamlessly
        # handled by the backtester's internal oos_summary without breaking the Elo timeline.
        
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ScanRequest(BaseModel):
    leagues: List[str]
    startDate: str
    endDate: str
    market: Union[List[str], str]
    valueThreshold: float
    initialBankroll: float
    stakingRule: str
    stakeValue: float
    oddsSource: str
    scanType: str  # 'markets' or 'leagues'
    minOdds: Optional[float] = 1.0
    maxOdds: Optional[float] = 50.0
    use_ml: bool = False
    data_source: str = "footballdata"
    futpython_api_key: str = ""

class SteamMovesRequest(BaseModel):
    leagues: List[str]
    startDate: str
    endDate: str
    markets: List[str]
    minDropPct: float = 5.0
    stakeValue: float = 10.0
    data_source: str = "footballdata"
    futpython_api_key: str = ""

@app.post("/api/scan_steam_moves")
def run_steam_moves_scan(req: SteamMovesRequest):
    try:
        from .data_loader import load_league_data
        
        # Helper that injects the data source and api key into the load_league_data call
        def loader(code, start_date='2021-01-01'):
            return load_league_data(code, start_date=start_date, data_source=req.data_source, api_key=req.futpython_api_key)
            
        backtester = SmartMoneyBacktester(loader)
        
        all_results = []
        for league in req.leagues:
            results = backtester.scan_steam_moves(
                league_code=league,
                min_drop_pct=req.minDropPct,
                markets=req.markets,
                start_date=req.startDate,
                end_date=req.endDate,
                stake_value=req.stakeValue
            )
            all_results.extend(results)
            
        return {"status": "success", "scan_results": all_results}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class ArbitrageRequest(BaseModel):
    min_profit_pct: float = 0.5  # Minimal guaranteed profit to alert

from .arbitrage_scanner import fetch_arbitrage_opportunities

@app.get("/api/scan_arbitrage")
def scan_arbitrage(bookies: str = None):
    try:
        allowed_bookies = None
        if bookies:
            allowed_bookies = [b.strip() for b in bookies.split(',') if b.strip()]
        return fetch_arbitrage_opportunities(allowed_bookies=allowed_bookies)

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class ArbitrageSchedulerConfig(BaseModel):
    enabled: bool
    check_interval_hours: float
    min_profit_pct: float

@app.get("/api/arbitrage_scheduler/config")
def get_arb_scheduler_config_api():
    try:
        return get_arbitrage_scheduler_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/arbitrage_scheduler/config")
def save_arb_scheduler_config_api(req: ArbitrageSchedulerConfig):
    try:
        config = req.dict()
        return save_arbitrage_scheduler_config(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/scan")
def run_scan(req: ScanRequest):
    try:
        backtester = ChronologicalBacktester()
        scan_results = []
        
        all_markets_def = [
            {'code': 'home', 'name': 'Mandante (1)'},
            {'code': 'away', 'name': 'Visitante (2)'},
            {'code': 'draw', 'name': 'Empate (X)'},
            {'code': 'over15', 'name': 'Over 1.5 Gols'},
            {'code': 'over25', 'name': 'Over 2.5 Gols'},
            {'code': 'under25', 'name': 'Under 2.5 Gols'},
            {'code': 'over35', 'name': 'Over 3.5 Gols'},
            {'code': 'under35', 'name': 'Under 3.5 Gols'},
            {'code': 'over45', 'name': 'Over 4.5 Gols'},
            {'code': 'under45', 'name': 'Under 4.5 Gols'},
            {'code': 'over55', 'name': 'Over 5.5 Gols'},
            {'code': 'under55', 'name': 'Under 5.5 Gols'},
            {'code': 'lay_home', 'name': 'Contra Mandante (X2)'},
            {'code': 'lay_away', 'name': 'Contra Visitante (1X)'},
            {'code': 'lay_draw', 'name': 'Contra Empate (12)'},
            {'code': 'btts_yes', 'name': 'Ambas Marcam Sim'},
            {'code': 'btts_no', 'name': 'Ambas Marcam Não'},
            {'code': 'cs_10', 'name': 'Placar Exato 1-0'},
            {'code': 'cs_20', 'name': 'Placar Exato 2-0'},
            {'code': 'cs_21', 'name': 'Placar Exato 2-1'},
            {'code': 'cs_00', 'name': 'Placar Exato 0-0'},
            {'code': 'cs_11', 'name': 'Placar Exato 1-1'},
            {'code': 'cs_01', 'name': 'Placar Exato 0-1'},
            {'code': 'cs_02', 'name': 'Placar Exato 0-2'},
            {'code': 'cs_12', 'name': 'Placar Exato 1-2'},
            {'code': 'lay_cs_10', 'name': 'Lay Placar Exato 1-0'},
            {'code': 'lay_cs_20', 'name': 'Lay Placar Exato 2-0'},
            {'code': 'lay_cs_21', 'name': 'Lay Placar Exato 2-1'},
            {'code': 'lay_cs_00', 'name': 'Lay Placar Exato 0-0'},
            {'code': 'lay_cs_11', 'name': 'Lay Placar Exato 1-1'},
            {'code': 'lay_cs_01', 'name': 'Lay Placar Exato 0-1'},
            {'code': 'lay_cs_02', 'name': 'Lay Placar Exato 0-2'},
            {'code': 'lay_cs_12', 'name': 'Lay Placar Exato 1-2'}
        ]

        if req.scanType == 'markets':
            user_markets = req.market if isinstance(req.market, list) else [req.market]
            if not user_markets or len(user_markets) == 0:
                markets_to_scan = all_markets_def
            else:
                markets_to_scan = [m for m in all_markets_def if m['code'] in user_markets or m['code'].replace('home', '1x2_home').replace('away', '1x2_away').replace('draw', '1x2_draw') in user_markets]
                
            market_codes = [m['code'] for m in markets_to_scan]
            parallel_results = backtester.run_parallel_scan(
                leagues=req.leagues,
                start_date=req.startDate,
                end_date=req.endDate,
                value_threshold=req.valueThreshold,
                initial_bankroll=req.initialBankroll,
                staking_rule=req.stakingRule,
                stake_value=req.stakeValue,
                odds_source=req.oddsSource,
                min_odds=req.minOdds or 1.0,
                max_odds=req.maxOdds or 50.0,
                scan_type='markets',
                markets_list=market_codes,
                use_ml=req.use_ml,
                data_source=req.data_source,
                futpython_api_key=req.futpython_api_key
            )
            for m in markets_to_scan:
                m_code = m['code']
                if m_code in parallel_results:
                    summary = parallel_results[m_code]
                    eqs_data = compute_edge_quality_score(summary, summary.get('oos_summary'))
                    v_color = eqs_data.get('verdict_color', '')
                    hex_color = '#34d399' if v_color == 'success' else '#f59e0b' if v_color == 'warning' else '#ef4444' if v_color == 'danger' else '#888888'
                    scan_results.append({
                        'code': m_code,
                        'name': m['name'],
                        'net_profit': summary['net_profit'],
                        'roi': summary['roi'],
                        'win_rate': summary['win_rate'],
                        'total_bets': summary['total_bets'],
                        'ai_score': summary.get('ai_score', 0.0),
                        'p_value': summary.get('p_value', None),
                        'eqs_score': eqs_data.get('score', 0),
                        'eqs_verdict': eqs_data.get('verdict', 'N/A'),
                        'eqs_color': hex_color,
                        'avg_clv': summary.get('avg_clv', 0.0),
                        'opt_range': summary.get('optimized_odds_range'),
                        'opt_eqs': summary.get('optimized_eqs_score')
                    })
        elif req.scanType == 'leagues':
            market_list = [req.market] if isinstance(req.market, str) else req.market
            parallel_results = backtester.run_parallel_scan(
                leagues=req.leagues,
                start_date=req.startDate,
                end_date=req.endDate,
                value_threshold=req.valueThreshold,
                initial_bankroll=req.initialBankroll,
                staking_rule=req.stakingRule,
                stake_value=req.stakeValue,
                odds_source=req.oddsSource,
                min_odds=req.minOdds or 1.0,
                max_odds=req.maxOdds or 50.0,
                scan_type='leagues',
                markets_list=market_list,
                use_ml=req.use_ml,
                data_source=req.data_source,
                futpython_api_key=req.futpython_api_key
            )
            all_leagues = get_all_available_leagues()
            for league_code in req.leagues:
                if league_code in parallel_results:
                    summary = parallel_results[league_code]
                    league_name = next((l['name'] for l in all_leagues if l['code'] == league_code), league_code)
                    eqs_data = compute_edge_quality_score(summary, summary.get('oos_summary'))
                    v_color = eqs_data.get('verdict_color', '')
                    hex_color = '#34d399' if v_color == 'success' else '#f59e0b' if v_color == 'warning' else '#ef4444' if v_color == 'danger' else '#888888'
                    scan_results.append({
                        'code': league_code,
                        'name': league_name,
                        'net_profit': summary['net_profit'],
                        'roi': summary['roi'],
                        'win_rate': summary['win_rate'],
                        'total_bets': summary['total_bets'],
                        'ai_score': summary.get('ai_score', 0.0),
                        'p_value': summary.get('p_value', None),
                        'eqs_score': eqs_data.get('score', 0),
                        'eqs_verdict': eqs_data.get('verdict', 'N/A'),
                        'eqs_color': hex_color,
                        'avg_clv': summary.get('avg_clv', 0.0),
                        'opt_range': summary.get('optimized_odds_range'),
                        'opt_eqs': summary.get('optimized_eqs_score')
                    })
                    
        elif req.scanType == 'combinations':
            user_markets = req.market if isinstance(req.market, list) else [req.market]
            if not user_markets or len(user_markets) == 0:
                markets_to_scan = all_markets_def
            else:
                markets_to_scan = [m for m in all_markets_def if m['code'] in user_markets or m['code'].replace('home', '1x2_home').replace('away', '1x2_away').replace('draw', '1x2_draw') in user_markets]
                
            market_codes = [m['code'] for m in markets_to_scan]
            parallel_results = backtester.run_parallel_scan(
                leagues=req.leagues,
                start_date=req.startDate,
                end_date=req.endDate,
                value_threshold=req.valueThreshold,
                initial_bankroll=req.initialBankroll,
                staking_rule=req.stakingRule,
                stake_value=req.stakeValue,
                odds_source=req.oddsSource,
                min_odds=req.minOdds or 1.0,
                max_odds=req.maxOdds or 50.0,
                scan_type='combinations',
                markets_list=market_codes,
                use_ml=req.use_ml,
                data_source=req.data_source,
                futpython_api_key=req.futpython_api_key
            )
            all_leagues = get_all_available_leagues()
            for key, summary in parallel_results.items():
                parts = key.split('|', 1)
                if len(parts) == 2:
                    league_code, m_code = parts
                    league_name = next((l['name'] for l in all_leagues if l['code'] == league_code), league_code)
                    market_name = next((m['name'] for m in all_markets_def if m['code'] == m_code), m_code)
                    eqs_data = compute_edge_quality_score(summary, summary.get('oos_summary'))
                    v_color = eqs_data.get('verdict_color', '')
                    hex_color = '#34d399' if v_color == 'success' else '#f59e0b' if v_color == 'warning' else '#ef4444' if v_color == 'danger' else '#888888'
                    scan_results.append({
                        'code': f"{league_code}|{m_code}",
                        'name': f"{league_name} / {market_name}",
                        'net_profit': summary['net_profit'],
                        'roi': summary['roi'],
                        'win_rate': summary['win_rate'],
                        'total_bets': summary['total_bets'],
                        'ai_score': summary.get('ai_score', 0.0),
                        'p_value': summary.get('p_value', None),
                        'eqs_score': eqs_data.get('score', 0),
                        'eqs_verdict': eqs_data.get('verdict', 'N/A'),
                        'eqs_color': hex_color,
                        'avg_clv': summary.get('avg_clv', 0.0),
                        'opt_range': summary.get('optimized_odds_range'),
                        'opt_eqs': summary.get('optimized_eqs_score')
                    })
                    
        # Aplica correção FDR (Benjamini-Hochberg) aos p-values do scanner
        if scan_results:
            from .ai_predictor import apply_fdr_correction
            p_values_raw = [r.get('p_value', 1.0) for r in scan_results]
            if any(p is not None for p in p_values_raw):
                p_values_clean = [p if p is not None else 1.0 for p in p_values_raw]
                adjusted = apply_fdr_correction(p_values_clean)
                for i, r in enumerate(scan_results):
                    r['p_value_adjusted'] = adjusted[i]
                    r['significant'] = adjusted[i] < 0.05

        return {"scan_type": req.scanType, "results": scan_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Match predictor request and endpoints
class PredictRequest(BaseModel):
    league: str
    homeTeam: str
    awayTeam: str
    data_source: str = "footballdata"
    futpython_api_key: str = ""

@app.get("/api/teams")
def get_teams(league: str, source: str = "footballdata", api_key: str = ""):
    try:
        df = load_league_data(league, start_date='2020-08-01', data_source=source, api_key=api_key)
        if df.empty:
            return []
        teams = sorted(list(set(df['HomeTeam'].dropna().unique()) | set(df['AwayTeam'].dropna().unique())))
        return teams
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/predict")
def predict_matchup(req: PredictRequest):
    try:
        df = load_league_data(req.league, start_date='2020-08-01', data_source=req.data_source, api_key=req.futpython_api_key)
        if df.empty:
            raise HTTPException(status_code=400, detail="Sem dados para a liga selecionada.")
            
        poisson = PoissonModel()
        latest_date = df['Date'].max()
        elo_tracker = build_elo_tracker_from_history(df)
        pred = poisson.predict_match(req.homeTeam, req.awayTeam, df, latest_date + pd.Timedelta(days=1), elo_tracker=elo_tracker)
        
        fair_h = round(1.0 / pred['prob_home'], 2) if pred['prob_home'] > 0 else 99.0
        fair_d = round(1.0 / pred['prob_draw'], 2) if pred['prob_draw'] > 0 else 99.0
        fair_a = round(1.0 / pred['prob_away'], 2) if pred['prob_away'] > 0 else 99.0
        
        fair_over15 = round(1.0 / pred['prob_over_15'], 2) if pred['prob_over_15'] > 0 else 99.0
        fair_over25 = round(1.0 / pred['prob_over_25'], 2) if pred['prob_over_25'] > 0 else 99.0
        fair_under25 = round(1.0 / pred['prob_under_25'], 2) if pred['prob_under_25'] > 0 else 99.0
        
        fair_over35 = round(1.0 / pred['prob_over_35'], 2) if pred['prob_over_35'] > 0 else 99.0
        fair_under35 = round(1.0 / pred['prob_under_35'], 2) if pred['prob_under_35'] > 0 else 99.0
        fair_over45 = round(1.0 / pred['prob_over_45'], 2) if pred['prob_over_45'] > 0 else 99.0
        fair_under45 = round(1.0 / pred['prob_under_45'], 2) if pred['prob_under_45'] > 0 else 99.0
        fair_over55 = round(1.0 / pred['prob_over_55'], 2) if pred['prob_over_55'] > 0 else 99.0
        fair_under55 = round(1.0 / pred['prob_under_55'], 2) if pred['prob_under_55'] > 0 else 99.0
        
        prob_lay_home = pred['prob_draw'] + pred['prob_away']
        prob_lay_away = pred['prob_home'] + pred['prob_draw']
        prob_lay_draw = pred['prob_home'] + pred['prob_away']
        
        fair_lay_home = round(1.0 / prob_lay_home, 2) if prob_lay_home > 0 else 99.0
        fair_lay_away = round(1.0 / prob_lay_away, 2) if prob_lay_away > 0 else 99.0
        fair_lay_draw = round(1.0 / prob_lay_draw, 2) if prob_lay_draw > 0 else 99.0
        
        fair_btts_yes = round(1.0 / pred['prob_btts_yes'], 2) if pred['prob_btts_yes'] > 0 else 99.0
        fair_btts_no = round(1.0 / pred['prob_btts_no'], 2) if pred['prob_btts_no'] > 0 else 99.0
        
        prob_lay_cs_10 = 1.0 - pred['prob_cs_10']
        prob_lay_cs_20 = 1.0 - pred['prob_cs_20']
        prob_lay_cs_21 = 1.0 - pred['prob_cs_21']
        prob_lay_cs_00 = 1.0 - pred['prob_cs_00']
        prob_lay_cs_11 = 1.0 - pred['prob_cs_11']
        prob_lay_cs_01 = 1.0 - pred['prob_cs_01']
        prob_lay_cs_02 = 1.0 - pred['prob_cs_02']
        prob_lay_cs_12 = 1.0 - pred['prob_cs_12']
        
        fair_lay_cs_10 = round(1.0 / prob_lay_cs_10, 2) if prob_lay_cs_10 > 0 else 99.0
        fair_lay_cs_20 = round(1.0 / prob_lay_cs_20, 2) if prob_lay_cs_20 > 0 else 99.0
        fair_lay_cs_21 = round(1.0 / prob_lay_cs_21, 2) if prob_lay_cs_21 > 0 else 99.0
        fair_lay_cs_00 = round(1.0 / prob_lay_cs_00, 2) if prob_lay_cs_00 > 0 else 99.0
        fair_lay_cs_11 = round(1.0 / prob_lay_cs_11, 2) if prob_lay_cs_11 > 0 else 99.0
        fair_lay_cs_01 = round(1.0 / prob_lay_cs_01, 2) if prob_lay_cs_01 > 0 else 99.0
        fair_lay_cs_02 = round(1.0 / prob_lay_cs_02, 2) if prob_lay_cs_02 > 0 else 99.0
        fair_lay_cs_12 = round(1.0 / prob_lay_cs_12, 2) if prob_lay_cs_12 > 0 else 99.0
        
        fair_cs_10 = round(1.0 / pred['prob_cs_10'], 2) if pred['prob_cs_10'] > 0 else 99.0
        fair_cs_20 = round(1.0 / pred['prob_cs_20'], 2) if pred['prob_cs_20'] > 0 else 99.0
        fair_cs_21 = round(1.0 / pred['prob_cs_21'], 2) if pred['prob_cs_21'] > 0 else 99.0
        fair_cs_00 = round(1.0 / pred['prob_cs_00'], 2) if pred['prob_cs_00'] > 0 else 99.0
        fair_cs_11 = round(1.0 / pred['prob_cs_11'], 2) if pred['prob_cs_11'] > 0 else 99.0
        fair_cs_01 = round(1.0 / pred['prob_cs_01'], 2) if pred['prob_cs_01'] > 0 else 99.0
        fair_cs_02 = round(1.0 / pred['prob_cs_02'], 2) if pred['prob_cs_02'] > 0 else 99.0
        fair_cs_12 = round(1.0 / pred['prob_cs_12'], 2) if pred['prob_cs_12'] > 0 else 99.0
        
        lambda_h = pred['lambda_home']
        lambda_a = pred['lambda_away']
        
        max_g = 5
        home_probs = [math.exp(-lambda_h) * (lambda_h**i) / math.factorial(i) for i in range(max_g + 1)]
        away_probs = [math.exp(-lambda_a) * (lambda_a**i) / math.factorial(i) for i in range(max_g + 1)]
        
        score_grid = []
        rho = -0.085
        tau_00 = 1.0 - lambda_h * lambda_a * rho
        tau_10 = 1.0 + lambda_a * rho
        tau_01 = 1.0 + lambda_h * rho
        tau_11 = 1.0 - rho
        
        matrix = np.outer(home_probs, away_probs)
        matrix[0, 0] *= max(0.0, tau_00)
        matrix[1, 0] *= max(0.0, tau_10)
        matrix[0, 1] *= max(0.0, tau_01)
        matrix[1, 1] *= max(0.0, tau_11)
        
        m_sum = np.sum(matrix)
        if m_sum > 0:
            matrix = matrix / m_sum
            
        for h in range(max_g + 1):
            row_probs = []
            for a in range(max_g + 1):
                row_probs.append({
                    'score': f"{h}-{a}",
                    'prob': round(float(matrix[h, a]) * 100, 1)
                })
            score_grid.append(row_probs)
            
        home_att, home_def, away_att, away_def, avg_h, avg_a = poisson.compute_team_ratings(df, latest_date + pd.Timedelta(days=1))
        h_att = home_att.get(req.homeTeam, 1.0)
        h_def = home_def.get(req.homeTeam, 1.0)
        a_att = away_att.get(req.awayTeam, 1.0)
        a_def = away_def.get(req.awayTeam, 1.0)
        
        return {
            'expectancy': {
                'home_lambda': round(lambda_h, 2),
                'away_lambda': round(lambda_a, 2),
                'home_att': round(h_att if not pd.isna(h_att) else 1.0, 2),
                'home_def': round(h_def if not pd.isna(h_def) else 1.0, 2),
                'away_att': round(a_att if not pd.isna(a_att) else 1.0, 2),
                'away_def': round(a_def if not pd.isna(a_def) else 1.0, 2),
                'league_avg_home': round(avg_h, 2),
                'league_avg_away': round(avg_a, 2)
            },
            'probabilities': {
                'home': round(pred['prob_home'] * 100, 1),
                'draw': round(pred['prob_draw'] * 100, 1),
                'away': round(pred['prob_away'] * 100, 1),
                'over15': round(pred['prob_over_15'] * 100, 1),
                'over25': round(pred['prob_over_25'] * 100, 1),
                'under25': round(pred['prob_under_25'] * 100, 1),
                'over35': round(pred['prob_over_35'] * 100, 1),
                'under35': round(pred['prob_under_35'] * 100, 1),
                'over45': round(pred['prob_over_45'] * 100, 1),
                'under45': round(pred['prob_under_45'] * 100, 1),
                'over55': round(pred['prob_over_55'] * 100, 1),
                'under55': round(pred['prob_under_55'] * 100, 1),
                'lay_home': round(prob_lay_home * 100, 1),
                'lay_away': round(prob_lay_away * 100, 1),
                'lay_draw': round(prob_lay_draw * 100, 1),
                'btts_yes': round(pred['prob_btts_yes'] * 100, 1),
                'btts_no': round(pred['prob_btts_no'] * 100, 1),
                'cs_10': round(pred['prob_cs_10'] * 100, 1),
                'cs_20': round(pred['prob_cs_20'] * 100, 1),
                'cs_21': round(pred['prob_cs_21'] * 100, 1),
                'cs_00': round(pred['prob_cs_00'] * 100, 1),
                'cs_11': round(pred['prob_cs_11'] * 100, 1),
                'cs_01': round(pred['prob_cs_01'] * 100, 1),
                'cs_02': round(pred['prob_cs_02'] * 100, 1),
                'cs_12': round(pred['prob_cs_12'] * 100, 1),
                'lay_cs_10': round(prob_lay_cs_10 * 100, 1),
                'lay_cs_20': round(prob_lay_cs_20 * 100, 1),
                'lay_cs_21': round(prob_lay_cs_21 * 100, 1),
                'lay_cs_00': round(prob_lay_cs_00 * 100, 1),
                'lay_cs_11': round(prob_lay_cs_11 * 100, 1),
                'lay_cs_01': round(prob_lay_cs_01 * 100, 1),
                'lay_cs_02': round(prob_lay_cs_02 * 100, 1),
                'lay_cs_12': round(prob_lay_cs_12 * 100, 1)
            },
            'fair_odds': {
                'home': fair_h,
                'draw': fair_d,
                'away': fair_a,
                'over15': fair_over15,
                'over25': fair_over25,
                'under25': fair_under25,
                'over35': fair_over35,
                'under35': fair_under35,
                'over45': fair_over45,
                'under45': fair_under45,
                'over55': fair_over55,
                'under55': fair_under55,
                'lay_home': fair_lay_home,
                'lay_away': fair_lay_away,
                'lay_draw': fair_lay_draw,
                'btts_yes': fair_btts_yes,
                'btts_no': fair_btts_no,
                'cs_10': fair_cs_10,
                'cs_20': fair_cs_20,
                'cs_21': fair_cs_21,
                'cs_00': fair_cs_00,
                'cs_11': fair_cs_11,
                'cs_01': fair_cs_01,
                'cs_02': fair_cs_02,
                'cs_12': fair_cs_12,
                'lay_cs_10': fair_lay_cs_10,
                'lay_cs_20': fair_lay_cs_20,
                'lay_cs_21': fair_lay_cs_21,
                'lay_cs_00': fair_lay_cs_00,
                'lay_cs_11': fair_lay_cs_11,
                'lay_cs_01': fair_lay_cs_01,
                'lay_cs_02': fair_lay_cs_02,
                'lay_cs_12': fair_lay_cs_12
            },
            'fair_ah_home': pred.get('fair_ah_home', {}),
            'fair_ah_away': pred.get('fair_ah_away', {}),
            'score_grid': score_grid,
            'odds_comparison': (lambda: {
                'Bet365': {
                    'H': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365H') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365CH')) 
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365H') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365CH')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'D': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365D') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365CD'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365D') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365CD')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'A': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365A') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365CA'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365A') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('B365CA')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    )
                },
                'Pinnacle': {
                    'H': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSH') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSCH'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSH') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSCH')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'D': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSD') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSCD'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSD') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSCD')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'A': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSA') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSCA'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSA') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('PSCA')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    )
                },
                'Bwin': {
                    'H': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWH') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWCH'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWH') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWCH')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'D': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWD') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWCD'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWD') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWCD')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'A': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWA') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWCA'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWA') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('BWCA')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    )
                },
                'Media': {
                    'H': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgH') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgCH'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgH') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgCH')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'D': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgD') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgCD'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgD') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgCD')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'A': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgA') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgCA'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgA') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('AvgCA')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    )
                },
                'Maxima': {
                    'H': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxH') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxCH'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxH') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxCH')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'D': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxD') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxCD'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxD') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxCD')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    ),
                    'A': (lambda x: round(float(x), 2) if x and not pd.isna(x) and float(x) > 0 else None)(
                        (df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxA') or 
                         df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxCA'))
                        if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) and not df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else (
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxA') or
                        df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].iloc[-1].get('MaxCA')
                        if not df[((df['HomeTeam'].str.lower() == req.homeTeam.lower()) & (df['AwayTeam'].str.lower() == req.awayTeam.lower()))].empty else None)
                    )
                }
            })() if (lambda _: True)(df_fix := pd.read_csv(os.path.join(DATA_DIR, "fixtures.csv"), encoding='latin1') if os.path.exists(os.path.join(DATA_DIR, "fixtures.csv")) else None) else {}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class TelegramConfigRequest(BaseModel):
    token: str
    chat_id: str
    enabled: bool

class TelegramTipSendRequest(BaseModel):
    league_name: str
    date_str: str
    time_str: str
    home_team: str
    away_team: str
    market_label: str
    prob: float
    fair_odds: float
    bookie_odds: float
    ev: float
    stake_pct: float

class CreateTipRequest(BaseModel):
    league_name: str
    date_str: str
    time_str: str
    home_team: str
    away_team: str
    market_label: str
    bookie_odds: float
    stake_pct: float

class UpdateTipStatusRequest(BaseModel):
    status: str

@app.get("/api/telegram/config")
def get_tg_config():
    try:
        return get_telegram_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/config")
def set_tg_config(req: TelegramConfigRequest):
    try:
        return save_telegram_config(req.token, req.chat_id, req.enabled)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/test")
def test_tg_connection():
    try:
        ok, msg = send_test_message()
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"status": "success", "message": msg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/test_arbitrage")
def test_tg_arbitrage_connection():
    try:
        from .telegram_bot import format_telegram_arbitrage_tip, send_telegram_message
        
        msg_text = format_telegram_arbitrage_tip(
            match_name="Real Madrid vs Barcelona",
            match_date="12/10/2026 16:00",
            bookies_dict={'1': 'Bet365', 'X': 'Pinnacle', '2': 'Betfair'},
            profit_margin=4.20,
            odds_dict={'1': 3.10, 'X': 3.50, '2': 3.20}
        )
        
        ok, msg = send_telegram_message(msg_text)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"status": "success", "message": msg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/send_tips")
def send_match_tip(req: TelegramTipSendRequest):
    try:
        # Validate that the league is in the backtesting system
        leagues = get_all_available_leagues()
        allowed_names = {l['name'] for l in leagues}
        if req.league_name not in allowed_names:
            raise HTTPException(status_code=400, detail="Esta liga não faz parte do sistema de backtesting.")
            
        msg_text = format_telegram_tip(
            req.league_name, req.date_str, req.time_str,
            req.home_team, req.away_team, req.market_label,
            req.prob, req.fair_odds, req.bookie_odds,
            req.ev, req.stake_pct
        )
        ok, msg = send_telegram_message(msg_text)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        
        # Save to database
        add_telegram_tip(
            req.league_name, req.date_str, req.time_str,
            req.home_team, req.away_team, req.market_label,
            req.bookie_odds, req.stake_pct
        )
        
        return {"status": "success", "message": msg}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/telegram/tips")
def list_telegram_tips():
    try:
        return get_telegram_tips()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/tips")
def create_telegram_tip(req: CreateTipRequest):
    try:
        # Validate that the league is in the backtesting system
        leagues = get_all_available_leagues()
        allowed_names = {l['name'] for l in leagues}
        if req.league_name not in allowed_names:
            raise HTTPException(status_code=400, detail="Esta liga não faz parte do sistema de backtesting.")
            
        return add_telegram_tip(
            req.league_name, req.date_str, req.time_str,
            req.home_team, req.away_team, req.market_label,
            req.bookie_odds, req.stake_pct
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/telegram/tips/{tip_id}")
def update_tip_status(tip_id: str, req: UpdateTipStatusRequest):
    try:
        return update_telegram_tip_status(tip_id, req.status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/telegram/tips")
def delete_all_tips():
    try:
        return clear_telegram_tips()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class TelegramSchedulerRequest(BaseModel):
    enabled: bool
    mode: Optional[str] = 'manual'
    check_interval_hours: int
    leagues: List[str]
    market: Union[List[str], str]
    value_threshold: float
    min_odds: float
    max_odds: float
    staking_rule: str
    stake_value: float
    initial_bankroll: float
    upcoming_source: Optional[str] = 'api'

@app.get("/api/telegram/scheduler")
def get_tg_scheduler():
    try:
        return get_scheduler_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/scheduler")
def set_tg_scheduler(req: TelegramSchedulerRequest):
    try:
        return save_scheduler_config(req.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telegram/scheduler/run")
async def run_tg_scheduler_now():
    try:
        results = await run_automatic_tips_scan()
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/upcoming")
def get_upcoming_predicted_matches(
    markets: str = 'home',
    valueThreshold: float = 1.05,
    minOdds: float = 1.0,
    maxOdds: float = 50.0,
    stakingRule: str = 'fixed',
    stakeValue: float = 10.0,
    initialBankroll: float = 1000.0,
    source: str = 'api'
):
    try:
        df_fixtures = pd.DataFrame()
        used_api = False
        
        req_markets = [m.strip() for m in markets.split(',')] if markets else ['home']
        
        # 1. Fetch from DataFootball API if chosen and token is present
        if source == 'api':
            token = get_api_token()
            if token:
                df_fixtures = load_upcoming_from_api(token)
                if not df_fixtures.empty:
                    used_api = True
                    print("[API] Loaded upcoming matches from DataFootball API webhook.")
                else:
                    print("[API Fallback] DataFootball API returned no matches, falling back to CSV.")
            else:
                print("[API Fallback] No API token found, falling back to CSV.")
                
        # 2. Fallback to standard CSV if needed
        if df_fixtures.empty:
            sync_fixtures(force=False)
            fixtures_path = os.path.join(DATA_DIR, "fixtures.csv")
            if os.path.exists(fixtures_path):
                df_fixtures = pd.read_csv(fixtures_path, encoding='latin1')
                df_fixtures.columns = [c.replace('', '').replace('\ufeff', '').strip() for c in df_fixtures.columns]
                print("[CSV] Loaded upcoming matches from local fixtures.csv.")
            else:
                return []
                
        upcoming_matches = []
        poisson = PoissonModel()
        
        # Group leagues to load data once
        all_leagues = get_all_available_leagues()
        league_codes = [l['code'] for l in all_leagues]
        
        # Load and cache league df to speed up predictions
        league_cache = {}
        elo_cache = {}
        
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
                hist = load_league_data(league_code, start_date='2020-08-01')
                league_cache[league_code] = hist
                elo_cache[league_code] = build_elo_tracker_from_history(hist)
                
            hist_df = league_cache[league_code]
            elo_tracker = elo_cache[league_code]
            if hist_df.empty:
                continue
                
            try:
                match_date = pd.to_datetime(row.get('Date'), dayfirst=True)
            except Exception:
                match_date = datetime.now()
                
            pred = poisson.predict_match(home_team, away_team, hist_df, match_date, elo_tracker=elo_tracker)
            
            # Map odds
            odds_h = float(row.get('B365H', np.nan))
            odds_d = float(row.get('B365D', np.nan))
            odds_a = float(row.get('B365A', np.nan))
            odds_over25 = float(row.get('B365>2.5', np.nan))
            odds_under25 = float(row.get('B365<2.5', np.nan))
            
            # Estimate other bookmaker odds
            est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, pred['lambda_home'], pred['lambda_away'])
            
            from .data_loader import LEAGUES_SEASONAL
            league_name = row.get('LeagueName') or LEAGUES_SEASONAL.get(league_code, league_code)
            
            def clean_odd(val):
                try:
                    v = float(val)
                    return round(v, 2) if not pd.isna(v) and v > 0 else None
                except Exception:
                    return None
                    
            odds_comp = {
                'Bet365': {
                    'H': clean_odd(row.get('B365H')),
                    'D': clean_odd(row.get('B365D')),
                    'A': clean_odd(row.get('B365A'))
                },
                'Pinnacle': {
                    'H': clean_odd(row.get('PSH')),
                    'D': clean_odd(row.get('PSD')),
                    'A': clean_odd(row.get('PSA'))
                },
                'Bwin': {
                    'H': clean_odd(row.get('BWH')),
                    'D': clean_odd(row.get('BWD')),
                    'A': clean_odd(row.get('BWA'))
                },
                'Media': {
                    'H': clean_odd(row.get('AvgH')),
                    'D': clean_odd(row.get('AvgD')),
                    'A': clean_odd(row.get('AvgA'))
                },
                'Maxima': {
                    'H': clean_odd(row.get('MaxH')),
                    'D': clean_odd(row.get('MaxD')),
                    'A': clean_odd(row.get('MaxA'))
                }
            }
            odds_comp = {k: v for k, v in odds_comp.items() if any(val is not None for val in v.values())}

            for m_key in req_markets:
                market_prob = 0.0
                bookie_odds = np.nan
                market_label = ""
                
                if m_key == 'home':
                    market_prob = pred['prob_home']
                    bookie_odds = odds_h
                    market_label = "1 (Mandante)"
                elif m_key == 'away':
                    market_prob = pred['prob_away']
                    bookie_odds = odds_a
                    market_label = "2 (Visitante)"
                elif m_key == 'draw':
                    market_prob = pred['prob_draw']
                    bookie_odds = odds_d
                    market_label = "X (Empate)"
                elif m_key == 'over15':
                    market_prob = pred['prob_over_15']
                    bookie_odds = est_odds.get('bookie_over_15', np.nan)
                    market_label = "Over 1.5"
                elif m_key == 'over25':
                    market_prob = pred['prob_over_25']
                    bookie_odds = odds_over25
                    market_label = "Over 2.5"
                elif m_key == 'under25':
                    market_prob = pred['prob_under_25']
                    bookie_odds = odds_under25
                    market_label = "Under 2.5"
                elif m_key == 'over35':
                    market_prob = pred['prob_over_35']
                    bookie_odds = est_odds.get('bookie_over_35', np.nan)
                    market_label = "Over 3.5"
                elif m_key == 'under35':
                    market_prob = pred['prob_under_35']
                    bookie_odds = est_odds.get('bookie_under_35', np.nan)
                    market_label = "Under 3.5"
                elif m_key == 'over45':
                    market_prob = pred['prob_over_45']
                    bookie_odds = est_odds.get('bookie_over_45', np.nan)
                    market_label = "Over 4.5"
                elif m_key == 'under45':
                    market_prob = pred['prob_under_45']
                    bookie_odds = est_odds.get('bookie_under_45', np.nan)
                    market_label = "Under 4.5"
                elif m_key == 'over55':
                    market_prob = pred['prob_over_55']
                    bookie_odds = est_odds.get('bookie_over_55', np.nan)
                    market_label = "Over 5.5"
                elif m_key == 'under55':
                    market_prob = pred['prob_under_55']
                    bookie_odds = est_odds.get('bookie_under_55', np.nan)
                    market_label = "Under 5.5"
                elif m_key == 'lay_home':
                    market_prob = pred['prob_draw'] + pred['prob_away']
                    bookie_odds = 1.0 / (1.0/odds_d + 1.0/odds_a) if (odds_d > 1.0 and odds_a > 1.0) else np.nan
                    market_label = "Contra Mandante (X2)"
                elif m_key == 'lay_away':
                    market_prob = pred['prob_home'] + pred['prob_draw']
                    bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan
                    market_label = "Contra Visitante (1X)"
                elif m_key == 'lay_draw':
                    market_prob = pred['prob_home'] + pred['prob_away']
                    bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_a) if (odds_h > 1.0 and odds_a > 1.0) else np.nan
                    market_label = "Contra Empate (12)"
                elif m_key == 'btts_yes':
                    market_prob = pred['prob_btts_yes']
                    bookie_odds = est_odds.get('bookie_btts_yes', np.nan)
                    market_label = "BTTS Sim"
                elif m_key == 'btts_no':
                    market_prob = pred['prob_btts_no']
                    bookie_odds = est_odds.get('bookie_btts_no', np.nan)
                    market_label = "BTTS Não"
                elif m_key.startswith('cs_'):
                    market_prob = pred.get(f"prob_{m_key}", 0.0)
                    bookie_odds = est_odds.get(f"bookie_{m_key}", np.nan)
                    market_label = f"Placar Exato {m_key[3]}-{m_key[4]}"
                    
                ev = np.nan
                is_tip = False
                stake_pct = 0.0
                
                if not pd.isna(bookie_odds) and bookie_odds > 1.0:
                    ev = market_prob * bookie_odds
                    is_tip = (ev >= valueThreshold) and (minOdds <= bookie_odds <= maxOdds)
                    
                    if stakingRule.startswith('kelly'):
                        mult_k = 1.0
                        if stakingRule == 'kelly_half': mult_k = 0.5
                        elif stakingRule == 'kelly_quarter': mult_k = 0.25
                        elif stakingRule == 'kelly_eighth': mult_k = 0.125
                        elif stakingRule == 'kelly_sixteenth': mult_k = 0.0625
                        elif stakingRule == 'kelly': mult_k = stakeValue
                        else: mult_k = stakeValue
                        
                        f_star = (market_prob * bookie_odds - 1.0) / (bookie_odds - 1.0)
                        stake_pct = max(0.0, f_star) * mult_k * 100.0
                        stake_pct = min(stake_pct, 5.0)
                    elif stakingRule == 'proportional':
                        stake_pct = stakeValue
                    else:
                        stake_pct = (stakeValue / initialBankroll) * 100.0
                
                upcoming_matches.append({
                    'league_code': league_code,
                    'league_name': league_name,
                    'date': str(row.get('Date')),
                    'time': str(row.get('Time')) if not pd.isna(row.get('Time')) else '00:00',
                    'home_team': home_team,
                    'away_team': away_team,
                    'market_label': market_label,
                    'prob': round(market_prob * 100, 1),
                    'fair_odds': round(1.0 / market_prob, 2) if market_prob > 0.001 else 99.0,
                    'bookie_odds': round(bookie_odds, 2) if not pd.isna(bookie_odds) else np.nan,
                    'ev': round(ev, 2) if not pd.isna(ev) else np.nan,
                    'is_tip': bool(is_tip),
                    'stake_pct': round(stake_pct, 1),
                    'odds_comparison': odds_comp
                })
            
        # Apply concurrent bet penalization (Freio de Variância) grouped by date
        from collections import defaultdict
        date_counts = defaultdict(int)
        for m in upcoming_matches:
            if m['is_tip']:
                date_counts[m['date']] += 1
                
        for m in upcoming_matches:
            if m['is_tip'] and date_counts[m['date']] > 1:
                m['stake_pct'] = round(m['stake_pct'] / math.sqrt(date_counts[m['date']]), 2)
                    
        # Sort by date and time
        upcoming_matches.sort(key=lambda x: (x['date'], x['time']))
        return upcoming_matches
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Import datetime for mod time query
from datetime import datetime

# --- ROTAS DE HISTÓRICO DE ESTRATÉGIAS ---
@app.get("/api/history")
def api_get_history():
    return load_history()

@app.post("/api/history")
def api_save_history(payload: dict):
    try:
        new_entry = add_strategy(payload)
        return {"status": "ok", "entry": new_entry}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/history/{strategy_id}")
def api_delete_history(strategy_id: str):
    try:
        delete_strategy(strategy_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount frontend files
class LiveSteamRequest(BaseModel):
    minDropPct: float = 5.0
    markets: List[str] = ['home']
    leagues: List[str] = []

@app.post("/api/live_steam_moves")
def get_live_steam_moves(req: LiveSteamRequest):
    import json
    import os
    from datetime import datetime, timezone
    
    tracker_file = os.path.join(os.path.dirname(__file__), 'data', 'live_odds_tracker.json')
    if not os.path.exists(tracker_file):
        return {"status": "success", "scan_results": []}
        
    try:
        with open(tracker_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        results = []
        for match_id, match_info in data.items():
            title = match_info.get('title', 'Desconhecido')
            commence_time = match_info.get('commence_time', '')
            
            # Format date beautifully
            try:
                dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                dt_local = dt.astimezone() # convert to server local time
                date_str = dt_local.strftime('%d/%m %H:%M')
            except:
                date_str = commence_time
            
            for bookie, markets_data in match_info.get('bookmakers', {}).items():
                for comp_key, odds_data in markets_data.items():
                    norm_market = odds_data['norm_market']
                    # Filter by requested markets
                    if norm_market not in req.markets:
                        continue
                        
                    opening = odds_data['opening']
                    current = odds_data['current']
                    
                    if opening > 1.0 and current > 0.0 and current < opening:
                        drop_pct = ((opening / current) - 1.0) * 100
                        if drop_pct >= req.minDropPct:
                            from .smart_money import calculate_confidence_score
                            sport_key = match_info.get('sport', '')
                            score, confidence_level, tier_name = calculate_confidence_score(drop_pct, sport_key)
                            results.append({
                                'match': title,
                                'date': date_str,
                                'bookmaker': bookie,
                                'market': norm_market.upper(),
                                'opening_odd': opening,
                                'current_odd': current,
                                'drop_pct': round(drop_pct, 1),
                                'liquidity_tier': tier_name,
                                'confidence_score': score,
                                'confidence_level': confidence_level
                            })
                            
        # Sort by biggest drop
        results = sorted(results, key=lambda x: x['drop_pct'], reverse=True)
        return {"status": "success", "scan_results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# To serve index.html at root, uvicorn must find the static files directory
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend')
@app.get('/api/autopilot')
def get_autopilot_predictions(source: str = 'api'):
    try:
        import pandas as pd
        from datetime import datetime
        import numpy as np
        from .history_manager import load_history
        from .models import PoissonModel
        from .models import estimate_bookmaker_odds
        
        history = load_history()
        # Filter strategies that have positive net_profit
        valid_strategies = []
        for s in history:
            net_profit = s.get('summary', {}).get('net_profit', 0)
            if net_profit > 0:
                valid_strategies.append(s)
                
        if not valid_strategies:
            return []
            
        df_fixtures = pd.DataFrame()
        if source == 'api':
            token = get_api_token()
            if token:
                df_fixtures = load_upcoming_from_api(token)
                
        if df_fixtures.empty:
            sync_fixtures(force=False)
            import os
            fixtures_path = os.path.join(DATA_DIR, 'fixtures.csv')
            if os.path.exists(fixtures_path):
                df_fixtures = pd.read_csv(fixtures_path, encoding='latin1')
                df_fixtures.columns = [c.replace('ï»¿', '').replace('\ufeff', '').strip() for c in df_fixtures.columns]
            else:
                return []
                
        all_leagues = get_all_available_leagues()
        league_codes = [l['code'] for l in all_leagues]
        poisson = PoissonModel()
        league_cache = {}
        elo_cache = {}
        
        autopilot_matches = []
        
        for row in df_fixtures.to_dict('records'):
            league_code = row.get('Div')
            if not league_code or league_code not in league_codes:
                continue
                
            home_team = row.get('HomeTeam')
            away_team = row.get('AwayTeam')
            if pd.isna(home_team) or pd.isna(away_team):
                continue
                
            if league_code not in league_cache:
                hist = load_league_data(league_code, start_date='2020-08-01')
                league_cache[league_code] = hist
                elo_cache[league_code] = build_elo_tracker_from_history(hist)
                
            hist_df = league_cache[league_code]
            elo_tracker = elo_cache[league_code]
            if hist_df.empty:
                continue
                
            try:
                match_date = pd.to_datetime(row.get('Date'), dayfirst=True)
            except:
                match_date = datetime.now()
                
            pred = poisson.predict_match(home_team, away_team, hist_df, match_date, elo_tracker=elo_tracker)
            
            odds_h = float(row.get('B365H', np.nan))
            odds_d = float(row.get('B365D', np.nan))
            odds_a = float(row.get('B365A', np.nan))
            odds_over25 = float(row.get('B365>2.5', np.nan))
            odds_under25 = float(row.get('B365<2.5', np.nan))
            
            est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, pred['lambda_home'], pred['lambda_away'])
            
            for strategy in valid_strategies:
                p = strategy.get('params', {})
                s_leagues = p.get('leagues', [])
                if league_code not in s_leagues:
                    continue
                    
                # Market parameter support in saved strategies could be 'market' or 'markets' (comma separated)
                s_markets_raw = p.get('markets') or p.get('market', 'home')
                if isinstance(s_markets_raw, str):
                    s_markets = [m.strip() for m in s_markets_raw.split(',')]
                elif isinstance(s_markets_raw, list):
                    s_markets = [str(m).strip() for m in s_markets_raw]
                else:
                    s_markets = ['home']
                
                s_min = float(p.get('minOdds', 1.0))
                s_max = float(p.get('maxOdds', 50.0))
                s_val = float(p.get('valThreshold', 1.05))
                stakingRule = p.get('stakingRule', 'fixed')
                stakeValue = float(p.get('stakeValue', 10.0))
                initialBankroll = float(p.get('initialBankroll', 1000.0))
                
                for s_m in s_markets:
                    market_prob = 0.0
                    bookie_odds = np.nan
                    market_label = ''
                    
                    if s_m == 'home': market_prob = pred['prob_home']; bookie_odds = odds_h; market_label = '1 (Mandante)'
                    elif s_m == 'away': market_prob = pred['prob_away']; bookie_odds = odds_a; market_label = '2 (Visitante)'
                    elif s_m == 'draw': market_prob = pred['prob_draw']; bookie_odds = odds_d; market_label = 'X (Empate)'
                    elif s_m == 'btts_yes': market_prob = pred['prob_btts_yes']; bookie_odds = est_odds.get('bookie_btts_yes', np.nan); market_label = 'BTTS Sim'
                    elif s_m == 'btts_no': market_prob = pred['prob_btts_no']; bookie_odds = est_odds.get('bookie_btts_no', np.nan); market_label = 'BTTS Não'
                    elif s_m == 'over15': market_prob = pred['prob_over_15']; bookie_odds = est_odds.get('bookie_over_15', np.nan); market_label = 'Over 1.5'
                    elif s_m == 'over25': market_prob = pred['prob_over_25']; bookie_odds = odds_over25; market_label = 'Over 2.5'
                    elif s_m == 'under25': market_prob = pred['prob_under_25']; bookie_odds = odds_under25; market_label = 'Under 2.5'
                    elif s_m.startswith('cs_'): market_prob = pred.get(f"prob_{s_m}", 0.0); bookie_odds = est_odds.get(f"bookie_{s_m}", np.nan); market_label = f"Placar Exato {s_m[3]}-{s_m[4]}"
                    elif s_m == 'lay_home': market_prob = pred['prob_draw'] + pred['prob_away']; bookie_odds = 1.0 / (1.0/odds_d + 1.0/odds_a) if (odds_d > 1.0 and odds_a > 1.0) else np.nan; market_label = "Contra Mandante (X2)"
                    elif s_m == 'lay_away': market_prob = pred['prob_home'] + pred['prob_draw']; bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan; market_label = "Contra Visitante (1X)"
                    elif s_m == 'lay_draw': market_prob = pred['prob_home'] + pred['prob_away']; bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_a) if (odds_h > 1.0 and odds_a > 1.0) else np.nan; market_label = "Contra Empate (12)"

                    if pd.isna(bookie_odds) or bookie_odds <= 1.0:
                        continue
                        
                    ev = market_prob * bookie_odds
                    if ev >= s_val and s_min <= bookie_odds <= s_max:
                        stake_pct = 0.0
                        if stakingRule.startswith('kelly'):
                            mult_k = 1.0
                            if stakingRule == 'kelly_half': mult_k = 0.5
                            elif stakingRule == 'kelly_quarter': mult_k = 0.25
                            elif stakingRule == 'kelly_eighth': mult_k = 0.125
                            elif stakingRule == 'kelly_sixteenth': mult_k = 0.0625
                            elif stakingRule == 'kelly': mult_k = stakeValue
                            else: mult_k = stakeValue
                            f_star = (market_prob * bookie_odds - 1.0) / (bookie_odds - 1.0)
                            stake_pct = max(0.0, f_star) * mult_k * 100.0
                            stake_pct = min(stake_pct, 5.0)
                        elif stakingRule == 'proportional':
                            stake_pct = stakeValue
                        else:
                            stake_pct = (stakeValue / initialBankroll) * 100.0
                            
                        from .data_loader import LEAGUES_SEASONAL
                        league_name = row.get('LeagueName') or LEAGUES_SEASONAL.get(league_code, league_code)
                        
                        def clean_odd(val):
                            try:
                                v = float(val)
                                return round(v, 2) if not pd.isna(v) and v > 0 else None
                            except:
                                return None
                                
                        odds_comp = {
                            'Bet365': {'H': clean_odd(row.get('B365H')), 'D': clean_odd(row.get('B365D')), 'A': clean_odd(row.get('B365A'))}
                        }
                        
                        autopilot_matches.append({
                            'league_code': league_code,
                            'league_name': league_name,
                            'date': str(row.get('Date')),
                            'time': str(row.get('Time')) if not pd.isna(row.get('Time')) else '00:00',
                            'home_team': home_team,
                            'away_team': away_team,
                            'market_label': market_label,
                            'prob': round(market_prob * 100, 1),
                            'fair_odds': round(1.0 / market_prob, 2) if market_prob > 0.001 else 99.0,
                            'bookie_odds': round(bookie_odds, 2),
                            'ev': round(ev, 2),
                            'is_tip': True,
                            'stake_pct': round(stake_pct, 1),
                            'odds_comparison': odds_comp,
                            'strategy_name': strategy.get('name', 'Autopilot Strategy')
                        })
                    
        # Sort and return
        autopilot_matches.sort(key=lambda x: (x['date'], x['time']))
        return autopilot_matches
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
