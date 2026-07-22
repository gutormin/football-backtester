import os
import json
import math
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import List, Optional, Union, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator

from ..data_loader import (
    DATA_DIR, sync_fixtures, get_all_available_leagues, load_league_data,
    get_api_token, load_upcoming_from_api, LEAGUES_SEASONAL, auto_detect_data_source
)
from ..backtester import ChronologicalBacktester
from ..smart_money import SmartMoneyBacktester, calculate_confidence_score
from ..arbitrage_scanner import fetch_arbitrage_opportunities
from ..dutching_scanner import fetch_dutching_opportunities
from ..telegram_bot import (
    get_telegram_config, save_telegram_config, send_test_message,
    send_telegram_message, format_telegram_tip, get_telegram_tips,
    add_telegram_tip, update_telegram_tip_status, clear_telegram_tips,
    format_telegram_arbitrage_tip, format_telegram_dutching_tip
)
from ..scheduler import (
    get_scheduler_config, save_scheduler_config, run_automatic_tips_scan,
    get_arbitrage_scheduler_config, save_arbitrage_scheduler_config,
    get_dutching_scheduler_config, save_dutching_scheduler_config
)
from ..cluster_ai_tracker import get_cluster_ai_config, save_cluster_ai_config
from ..ml_clustering import extract_league_features, cluster_leagues
from ..history_manager import load_history
from ..models import PoissonModel, estimate_bookmaker_odds
from ..constants import RHO_FALLBACK
from ..elo_model import build_elo_tracker_from_history
from ..ai_predictor import compute_edge_quality_score, apply_fdr_correction

router = APIRouter()
logger = logging.getLogger(__name__)

# Request schemas
class ClusterRequest(BaseModel):
    leagues: List[str]
    startDate: str
    endDate: str
    data_source: str = "football-data"
    futpython_api_key: str = ""
    n_clusters: Optional[int] = None

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
    odds_timing: Optional[str] = "closing"
    scanType: str  # 'markets' or 'leagues'
    minOdds: Optional[float] = 1.0
    maxOdds: Optional[float] = 2.50
    use_ml: bool = False
    data_source: str = "footballdata"
    futpython_api_key: str = ""
    model_type: str = "poisson"  # "poisson" or "negative_binomial"
    walk_forward_folds: int = 0  # 0 = disabled, 2-10 = walk-forward mode

    @validator('startDate', 'endDate')
    def validate_date_format(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("As datas devem estar no formato YYYY-MM-DD")
        return v

    @validator('endDate')
    def validate_dates_relation(cls, v, values):
        start_date_str = values.get('startDate')
        if start_date_str:
            try:
                start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
                end_dt = datetime.strptime(v, "%Y-%m-%d")
                if start_dt > end_dt:
                    raise ValueError("A data de início (startDate) deve ser igual ou anterior à data de fim (endDate)")
            except ValueError as e:
                if "formato" not in str(e):
                    raise e
        return v

    @validator('initialBankroll')
    def validate_bankroll(cls, v):
        if v <= 0:
            raise ValueError("A banca inicial (initialBankroll) deve ser maior que zero")
        return v

    @validator('minOdds')
    def validate_min_odds(cls, v):
        if v is not None and v <= 0:
            raise ValueError("As odds mínimas devem ser maiores que zero")
        return v

    @validator('maxOdds')
    def validate_max_odds(cls, v, values):
        min_odds = values.get('minOdds')
        if v is not None and min_odds is not None and v < min_odds:
            raise ValueError("As odds máximas não podem ser menores que as odds mínimas")
        return v

    @validator('stakeValue')
    def validate_stake_value(cls, v, values):
        rule = values.get('stakingRule')
        if rule in ['kelly', 'kelly_quarter', 'kelly_half', 'kelly_eighth']:
            if v <= 0 or v > 1.0:
                raise ValueError("Para regras Kelly, o stakeValue representa a porcentagem limite e deve estar entre 0.0 e 1.0 (ex: 0.25 para 25%)")
        else:
            if v <= 0:
                raise ValueError("O stakeValue deve ser maior que zero")
        return v

class SteamMovesRequest(BaseModel):
    leagues: List[str]
    startDate: str
    endDate: str
    markets: List[str]
    minDropPct: float = 5.0
    stakeValue: float = 10.0
    data_source: str = "footballdata"
    futpython_api_key: str = ""
    profileFilter: str = "all"
    latencySeconds: int = 0
    detectionMode: str = "model_edge"  # 'model_edge' | 'temporal_drop'

    @validator('startDate', 'endDate')
    def validate_date_format(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("As datas devem estar no formato YYYY-MM-DD")
        return v

    @validator('endDate')
    def validate_dates_relation(cls, v, values):
        start_date_str = values.get('startDate')
        if start_date_str:
            try:
                start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
                end_dt = datetime.strptime(v, "%Y-%m-%d")
                if start_dt > end_dt:
                    raise ValueError("A data de início (startDate) deve ser igual ou anterior à data de fim (endDate)")
            except ValueError as e:
                if "formato" not in str(e):
                    raise e
        return v

    @validator('minDropPct')
    def validate_min_drop(cls, v):
        if v <= 0:
            raise ValueError("O percentual de queda mínima (minDropPct) deve ser maior que zero")
        return v

    @validator('stakeValue')
    def validate_stake(cls, v):
        if v <= 0:
            raise ValueError("O stakeValue deve ser maior que zero")
        return v

class ArbitrageRequest(BaseModel):
    min_profit_pct: float = 0.5

    @validator('min_profit_pct')
    def validate_min_profit(cls, v):
        if v < 0:
            raise ValueError("O lucro mínimo percentual (min_profit_pct) não pode ser negativo")
        return v

class ArbitrageSchedulerConfig(BaseModel):
    enabled: bool
    check_interval_hours: float
    min_profit_pct: float

class TelegramDutchingConfigRequest(BaseModel):
    enabled: bool
    check_interval_hours: float
    min_edge_pct: float
    min_hours_before: float

class OddsApiConfigRequest(BaseModel):
    api_key: str

class TelegramConfigRequest(BaseModel):
    enabled: bool
    token: str
    chat_id: str

    @validator('token', 'chat_id')
    def validate_telegram_params(cls, v, values):
        enabled = values.get('enabled')
        if enabled:
            if not v or not v.strip():
                raise ValueError("O token e o chat_id não podem ser vazios quando o bot do Telegram está ativado")
        return v.strip() if v else v

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

class LiveSteamRequest(BaseModel):
    minDropPct: float = 5.0
    markets: List[str] = ['home']
    leagues: List[str] = []
    profileFilter: str = "all"

class ClusterAIConfigReq(BaseModel):
    enabled: bool
    check_interval_hours: float
    value_threshold: float
    min_odds: float
    max_odds: float
    leagues: List[str]


@router.post("/cluster_leagues")
def api_cluster_leagues(req: ClusterRequest):
    try:
        import os as _os
        is_render = _os.environ.get("RENDER") is not None
        max_leagues = 100 if is_render else len(req.leagues)
        if len(req.leagues) > max_leagues:
            req.leagues = req.leagues[:max_leagues]

        features_list = []
        errors = []
        for league in req.leagues:
            try:
                df = load_league_data(league, start_date=req.startDate, data_source=req.data_source, api_key=req.futpython_api_key)
                features = extract_league_features(league, df)
                if features:
                    features_list.append(features)
            except Exception as league_error:
                import traceback
                logger.error(f"Erro ao processar liga {league} para clusterização: {league_error}")
                traceback.print_exc()
                errors.append({"league": league, "error": str(league_error)})

        if not features_list:
            raise ValueError("Não foi possível extrair dados para nenhuma das ligas selecionadas.")

        cluster_results = cluster_leagues(features_list, req.n_clusters)
        if 'error' in cluster_results:
            raise ValueError(cluster_results['error'])

        if errors:
            cluster_results['_warnings'] = errors

        return cluster_results

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/clear_cache")
def clear_cache():
    """Clear the league data cache. Use when leagues show zero results."""
    from ..data_loader import clear_league_data_cache
    clear_league_data_cache()
    return {"status": "success", "message": "Cache limpo com sucesso."}

@router.get("/status")
def get_status():
    try:
        if not os.path.exists(DATA_DIR):
            return {"synced": False, "files_count": 0, "last_updated": None}
            
        files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
        if not files:
            return {"synced": False, "files_count": 0, "last_updated": None}
            
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

@router.post("/scan_steam_moves")
def run_steam_moves_scan(req: SteamMovesRequest):
    try:
        def loader(code, start_date='2021-01-01'):
            return load_league_data(code, start_date=start_date, data_source=req.data_source, api_key=req.futpython_api_key)

        backtester = SmartMoneyBacktester(loader)

        all_results = []
        errors = []
        for league in req.leagues:
            try:
                results = backtester.scan_steam_moves(
                    league_code=league,
                    min_drop_pct=req.minDropPct,
                    markets=req.markets,
                    start_date=req.startDate,
                    end_date=req.endDate,
                    stake_value=req.stakeValue,
                    profile_filter=req.profileFilter,
                    latency_seconds=req.latencySeconds,
                    detection_mode=req.detectionMode
                )
                all_results.extend(results)
            except Exception as league_error:
                logger.error(f"Erro ao escanear liga {league}: {league_error}")
                errors.append({"league": league, "error": str(league_error)})

        return {"status": "success", "scan_results": all_results, "results": all_results, "errors": errors}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/scan_arbitrage")
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

@router.get("/scan_dutching")
def scan_dutching(source: str = "odds_api", strategy: str = "dynamic", data_source: str = "auto", futpython_api_key: str = ""):
    try:
        from ..dutching_scanner import get_odds_api_token
        token = os.getenv('THE_ODDS_API_KEY') or get_odds_api_token()
        return fetch_dutching_opportunities(api_key=token, source=source, strategy=strategy, data_source=data_source, futpython_api_key=futpython_api_key)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/arbitrage_scheduler/config")
def get_arb_scheduler_config_api():
    try:
        return get_arbitrage_scheduler_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/arbitrage_scheduler/config")
def save_arb_scheduler_config_api(req: ArbitrageSchedulerConfig):
    try:
        config = req.dict()
        return save_arbitrage_scheduler_config(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/scan")
def run_scan(req: ScanRequest):
    try:
        # Always clear stale cache before scanning — prevents zero-results from cached empty DataFrames
        from ..data_loader import clear_league_data_cache
        clear_league_data_cache()

        backtester = ChronologicalBacktester()
        scan_results = []

        # Walk-forward mode: single market or league, expanding window validation
        if getattr(req, 'walk_forward_folds', 0) >= 2:
            wf_market = req.market[0] if isinstance(req.market, list) else req.market
            if not wf_market or wf_market == 'string':
                wf_market = 'home'
            wf_result = backtester.run_walk_forward(
                leagues=req.leagues,
                start_date=req.startDate,
                end_date=req.endDate,
                n_folds=req.walk_forward_folds,
                market=wf_market,
                value_threshold=req.valueThreshold,
                initial_bankroll=req.initialBankroll,
                staking_rule=req.stakingRule,
                stake_value=req.stakeValue,
                odds_source=req.oddsSource,
                odds_timing=req.odds_timing or 'closing',
                min_odds=req.minOdds or 1.0,
                max_odds=req.maxOdds or 2.50,
                use_ml=req.use_ml,
                data_source=req.data_source,
                futpython_api_key=req.futpython_api_key,
                model_type=req.model_type
            )
            if 'error' in wf_result:
                raise HTTPException(status_code=400, detail=wf_result['error'])
            return wf_result

        all_markets_def = [
            {'code': 'home', 'name': 'Mandante (1)'},
            {'code': 'away', 'name': 'Visitante (2)'},
            {'code': 'draw', 'name': 'Empate (X)'},
            {'code': 'ht_home', 'name': 'HT Mandante'},
            {'code': 'ht_away', 'name': 'HT Visitante'},
            {'code': 'ht_draw', 'name': 'HT Empate'},
            {'code': 'ht_over05', 'name': 'HT Over 0.5'},
            {'code': 'ht_under05', 'name': 'HT Under 0.5'},
            {'code': 'ht_over15', 'name': 'HT Over 1.5'},
            {'code': 'ht_under15', 'name': 'HT Under 1.5'},
            {'code': 'ht_over25', 'name': 'HT Over 2.5'},
            {'code': 'ht_under25', 'name': 'HT Under 2.5'},
            {'code': 'ht_over35', 'name': 'HT Over 3.5'},
            {'code': 'ht_under35', 'name': 'HT Under 3.5'},
            # 2º Tempo (2H)
            {'code': 'sh_home', 'name': '2H Mandante'},
            {'code': 'sh_draw', 'name': '2H Empate'},
            {'code': 'sh_away', 'name': '2H Visitante'},
            {'code': 'sh_over05', 'name': '2H Over 0.5'},
            {'code': 'sh_under05', 'name': '2H Under 0.5'},
            {'code': 'sh_over15', 'name': '2H Over 1.5'},
            {'code': 'sh_under15', 'name': '2H Under 1.5'},
            {'code': 'sh_over25', 'name': '2H Over 2.5'},
            {'code': 'sh_under25', 'name': '2H Under 2.5'},
            {'code': 'sh_over35', 'name': '2H Over 3.5'},
            {'code': 'sh_under35', 'name': '2H Under 3.5'},
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
            {'code': 'lay_home_ex', 'name': 'Lay Mandante'},
            {'code': 'lay_away_ex', 'name': 'Lay Visitante'},
            {'code': 'lay_draw_ex', 'name': 'Lay Empate'},
            # Empate Anula (DNB)
            {'code': 'dnb_h', 'name': 'DNB Mandante'},
            {'code': 'dnb_a', 'name': 'DNB Visitante'},
            # Handicap Asiático
            {'code': 'ah_home', 'name': 'AH Casa'},
            {'code': 'ah_away', 'name': 'AH Fora'},
            # Vitória sem Sofrer Gols
            {'code': 'win_to_nil_home', 'name': 'Mandante Ganha de Zero'},
            {'code': 'win_to_nil_away', 'name': 'Visitante Ganha de Zero'},
            # Escanteios
            {'code': 'corners_1', 'name': 'Mais Escanteios Mandante'},
            {'code': 'corners_x', 'name': 'Mais Escanteios Empate'},
            {'code': 'corners_2', 'name': 'Mais Escanteios Visitante'},
            {'code': 'corners_over_75', 'name': 'Escanteios Over 7.5'},
            {'code': 'corners_under_75', 'name': 'Escanteios Under 7.5'},
            {'code': 'corners_over_85', 'name': 'Escanteios Over 8.5'},
            {'code': 'corners_under_85', 'name': 'Escanteios Under 8.5'},
            {'code': 'corners_over_95', 'name': 'Escanteios Over 9.5'},
            {'code': 'corners_under_95', 'name': 'Escanteios Under 9.5'},
            {'code': 'corners_over_105', 'name': 'Escanteios Over 10.5'},
            {'code': 'corners_under_105', 'name': 'Escanteios Under 10.5'},
            {'code': 'corners_over_115', 'name': 'Escanteios Over 11.5'},
            {'code': 'corners_under_115', 'name': 'Escanteios Under 11.5'},
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
                odds_timing=req.odds_timing or 'closing',
                min_odds=req.minOdds or 1.0,
                max_odds=req.maxOdds or 2.50,
                scan_type='markets',
                markets_list=market_codes,
                use_ml=req.use_ml,
                data_source=req.data_source,
                futpython_api_key=req.futpython_api_key,
                model_type=req.model_type
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
            raw_market_list = [req.market] if isinstance(req.market, str) else req.market
            # Expand group market codes (e.g. '1X2' → ['home', 'draw', 'away'])
            MARKET_EXPAND_MAP = {
                '1X2': ['home', 'draw', 'away'],
                '1x2': ['home', 'draw', 'away'],
            }
            market_list = []
            for m in raw_market_list:
                if m in MARKET_EXPAND_MAP:
                    market_list.extend(MARKET_EXPAND_MAP[m])
                else:
                    market_list.append(m)
            parallel_results = backtester.run_parallel_scan(
                leagues=req.leagues,
                start_date=req.startDate,
                end_date=req.endDate,
                value_threshold=req.valueThreshold,
                initial_bankroll=req.initialBankroll,
                staking_rule=req.stakingRule,
                stake_value=req.stakeValue,
                odds_source=req.oddsSource,
                odds_timing=req.odds_timing or 'closing',
                min_odds=req.minOdds or 1.0,
                max_odds=req.maxOdds or 2.50,
                scan_type='leagues',
                markets_list=market_list,
                use_ml=req.use_ml,
                data_source=req.data_source,
                futpython_api_key=req.futpython_api_key,
                model_type=req.model_type
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
                odds_timing=req.odds_timing or 'closing',
                min_odds=req.minOdds or 1.0,
                max_odds=req.maxOdds or 2.50,
                scan_type='combinations',
                markets_list=market_codes,
                use_ml=req.use_ml,
                data_source=req.data_source,
                futpython_api_key=req.futpython_api_key,
                model_type=req.model_type
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

        elif req.scanType == 'staking':
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
                odds_timing=req.odds_timing or 'closing',
                min_odds=req.minOdds or 1.0,
                max_odds=req.maxOdds or 2.50,
                scan_type='staking',
                markets_list=market_codes,
                use_ml=req.use_ml,
                data_source=req.data_source,
                futpython_api_key=req.futpython_api_key,
                model_type=req.model_type
            )
            all_leagues = get_all_available_leagues()
            for key, methods_data in parallel_results.items():
                if key == 'model_version' or key == 'exclusion_stats':
                    continue
                parts = key.split('|', 1)
                if len(parts) == 2:
                    league_code, m_code = parts
                    league_name = next((l['name'] for l in all_leagues if l['code'] == league_code), league_code)
                    market_name = next((m['name'] for m in all_markets_def if m['code'] == m_code), m_code)

                    entry = {
                        'code': key,
                        'name': f"{league_name} / {market_name}",
                        'total_bets': methods_data['fixed']['total_bets'],
                    }
                    best_method = 'fixed'
                    best_roi = methods_data['fixed']['roi']
                    for method in ('proportional', 'kelly'):
                        if methods_data[method]['roi'] > best_roi:
                            best_roi = methods_data[method]['roi']
                            best_method = method
                    entry['best_method'] = best_method
                    entry['best_roi'] = best_roi

                    for method in ('fixed', 'proportional', 'kelly'):
                        summary = methods_data[method]
                        eqs_data = compute_edge_quality_score(summary, summary.get('oos_summary'))
                        v_color = eqs_data.get('verdict_color', '')
                        hex_color = '#34d399' if v_color == 'success' else '#f59e0b' if v_color == 'warning' else '#ef4444' if v_color == 'danger' else '#888888'
                        entry[method] = {
                            'net_profit': summary['net_profit'],
                            'roi': summary['roi'],
                            'win_rate': summary['win_rate'],
                            'total_bets': summary['total_bets'],
                            'ai_score': summary.get('ai_score', 0.0),
                            'p_value': summary.get('p_value'),
                            'max_drawdown': summary.get('max_drawdown', 0.0),
                            'eqs_score': eqs_data.get('score', 0),
                            'eqs_verdict': eqs_data.get('verdict', 'N/A'),
                            'eqs_color': hex_color,
                            'avg_clv': summary.get('avg_clv', 0.0),
                            'opt_range': summary.get('optimized_odds_range'),
                            'opt_eqs': summary.get('optimized_eqs_score'),
                        }
                    scan_results.append(entry)

        # Aplica correção FDR (Benjamini-Hochberg) aos p-values do scanner
        # Skip FDR for staking scan — each method already has EQS score
        if scan_results and req.scanType != 'staking':
            p_values_raw = [r.get('p_value', 1.0) for r in scan_results]
            if any(p is not None for p in p_values_raw):
                p_values_clean = [p if p is not None else 1.0 for p in p_values_raw]
                adjusted = apply_fdr_correction(p_values_clean)
                for i, r in enumerate(scan_results):
                    r['p_value_adjusted'] = adjusted[i]
                    r['significant'] = adjusted[i] < 0.05

        # Calcula percentis EQS relativos por grupo de peer
        # Skip staking scan — structure is different (nested methods)
        if scan_results and req.scanType != 'staking':
            from collections import defaultdict

            def _bets_band(n):
                if n < 30: return '<30'
                if n < 80: return '30-79'
                if n < 200: return '80-199'
                return '200+'

            def _percentile(score, scores_list):
                if not scores_list or len(scores_list) < 2:
                    return None
                return round(sum(1 for s in scores_list if s < score) / len(scores_list) * 100)

            # Grupo: por mercado (market code) — extrai do campo 'code'
            market_scores = defaultdict(list)
            for r in scan_results:
                code = r.get('code', '')
                # 'leagues' scan: code = league_code; 'markets': code = market_code;
                # 'combinations': code = "league|market"; 'staking': code = "league|market"
                if '|' in code:
                    m_key = code.split('|')[1] if len(code.split('|')) > 1 else code
                else:
                    m_key = code
                market_scores[m_key].append(r['eqs_score'])

            # Grupo: por faixa de bets
            bets_scores = defaultdict(list)
            for r in scan_results:
                bets_scores[_bets_band(r.get('total_bets', 0))].append(r['eqs_score'])

            for r in scan_results:
                code = r.get('code', '')
                if '|' in code:
                    m_key = code.split('|')[1] if len(code.split('|')) > 1 else code
                else:
                    m_key = code
                band = _bets_band(r.get('total_bets', 0))
                r['eqs_percentile_market'] = _percentile(r['eqs_score'], market_scores.get(m_key, []))
                r['eqs_percentile_bets'] = _percentile(r['eqs_score'], bets_scores.get(band, []))
                r['eqs_percentile_bets_label'] = f'Top entre {band} apostas' if r['eqs_percentile_bets'] is not None else None

        return {
            "status": "success",
            "scan_type": req.scanType,
            "results": scan_results,
            "scan_results": scan_results,
            "diagnostics": getattr(backtester, 'last_scan_diagnostics', {})
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/telegram/config")
def get_tg_config():
    try:
        return get_telegram_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram/config")
def set_tg_config(req: TelegramConfigRequest):
    try:
        return save_telegram_config(req.token, req.chat_id, req.enabled)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram/test")
def test_tg_connection():
    try:
        ok, msg = send_test_message()
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"status": "success", "message": msg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram/test_arbitrage")
def test_tg_arbitrage_connection():
    try:
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

@router.post("/telegram/send_tips")
def send_match_tip(req: TelegramTipSendRequest):
    try:
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

@router.get("/telegram/dutching_config")
def get_tg_dutching_config_api():
    try:
        return get_dutching_scheduler_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram/dutching_config")
def save_tg_dutching_config_api(req: TelegramDutchingConfigRequest):
    try:
        config = {
            "enabled": req.enabled,
            "check_interval_hours": req.check_interval_hours,
            "min_edge_pct": req.min_edge_pct,
            "min_hours_before": req.min_hours_before
        }
        return save_dutching_scheduler_config(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram/test_dutching")
def test_tg_dutching_connection():
    try:
        msg_text = format_telegram_dutching_tip(
            match_name="IA Akranes vs Fram",
            match_date="29/06/2026 16:15",
            bookmaker="Betfair Exchange",
            market="🧠 IA: Jogo Truncado / Under (Mandante)",
            selections=["0-0", "1-0", "2-0", "1-1"],
            odds=[11.0, 7.00, 8.00, 7.50],
            dutching_odd=2.08,
            model_prob="58.10%",
            edge="+20.85%"
        )
        ok, msg = send_telegram_message(msg_text)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"status": "success", "message": msg}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/telegram/odds_api_config")
def get_odds_api_config_api():
    try:
        from ..dutching_scanner import get_odds_api_token
        return {"api_key": get_odds_api_token()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram/odds_api_config")
def save_odds_api_config_api(req: OddsApiConfigRequest):
    try:
        config_path = os.path.join(DATA_DIR, 'odds_api_config.json')
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump({"api_key": req.api_key.strip()}, f, indent=4)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/telegram/tips")
def list_telegram_tips():
    try:
        return get_telegram_tips()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram/tips")
def create_telegram_tip(req: CreateTipRequest):
    try:
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

@router.put("/telegram/tips/{tip_id}")
def update_tip_status(tip_id: str, req: UpdateTipStatusRequest):
    try:
        return update_telegram_tip_status(tip_id, req.status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/telegram/tips")
def delete_all_tips():
    try:
        return clear_telegram_tips()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/telegram/scheduler")
def get_tg_scheduler():
    try:
        return get_scheduler_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram/scheduler")
def set_tg_scheduler(req: TelegramSchedulerRequest):
    try:
        return save_scheduler_config(req.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram/scheduler/run")
async def run_tg_scheduler_now():
    try:
        results = await run_automatic_tips_scan()
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/steam_confidence_calibration")
def get_steam_confidence_calibration(min_resolved: int = 50):
    """Calibra thresholds de confiança do Smart Money usando dados reais resolvidos."""
    try:
        from ..smart_money import calibrate_confidence_from_history, _load_confidence_calibration
        # Tenta calibrar com dados resolvidos
        result = calibrate_confidence_from_history(min_resolved_bets=min_resolved)
        # Inclui estado atual da calibração
        result['current_calibration'] = _load_confidence_calibration()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/live_steam_moves")
def get_live_steam_moves(req: LiveSteamRequest):
    tracker_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'live_odds_tracker.json')
    if not os.path.exists(tracker_file):
        return {"status": "success", "scan_results": [], "results": []}
        
    try:
        with open(tracker_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        results = []
        for match_id, match_info in data.items():
            title = match_info.get('title', 'Desconhecido')
            commence_time = match_info.get('commence_time', '')
            
            try:
                dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                dt_local = dt.astimezone()
                date_str = dt_local.strftime('%d/%m %H:%M')
            except:
                date_str = commence_time
            
            for bookie, markets_data in match_info.get('bookmakers', {}).items():
                for comp_key, odds_data in markets_data.items():
                    norm_market = odds_data['norm_market']
                    if norm_market not in req.markets:
                        continue
                        
                    opening = odds_data['opening']
                    current = odds_data['current']
                    
                    if opening > 1.0 and current > 0.0 and current < opening:
                        drop_pct = ((opening / current) - 1.0) * 100
                        
                        # In-Play e Time Decay
                        is_in_play = False
                        elapsed_minutes = 0.0
                        try:
                            commence_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                            now_utc = datetime.now(timezone.utc)
                            if now_utc > commence_dt:
                                is_in_play = True
                                elapsed_minutes = (now_utc - commence_dt).total_seconds() / 60.0
                                if elapsed_minutes > 95.0:
                                    elapsed_minutes = 95.0
                        except Exception:
                            pass
                            
                        from ..smart_money import calculate_time_decay_adjusted_drop
                        odd_decay, adjusted_drop_pct = calculate_time_decay_adjusted_drop(
                            norm_market=norm_market,
                            opening=opening,
                            current=current,
                            elapsed_minutes=elapsed_minutes
                        )
                        
                        trigger_drop = adjusted_drop_pct if is_in_play else drop_pct
                        
                        if trigger_drop >= req.minDropPct:
                            sport_key = match_info.get('sport', '')
                            from ..live_odds_tracker import map_sport_to_league_code
                            mapped_league = map_sport_to_league_code(sport_key)
                            from ..smart_money import calculate_confidence_score, classify_drop_profile, calculate_odds_metrics
                            score, confidence_level, tier_name = calculate_confidence_score(trigger_drop, mapped_league)
                            sharpness_score, profile_type = classify_drop_profile(
                                drop_pct=trigger_drop,
                                league_identifier=mapped_league,
                                commence_time_str=commence_time,
                                bookmaker_name=bookie,
                                match_entry=match_info,
                                comp_key=comp_key
                            )
                            
                            # Calcular métricas de velocidade e aceleração
                            updates = odds_data.get('updates', [])
                            if not updates:
                                first_seen = odds_data.get('first_seen') or odds_data.get('last_updated') or commence_time
                                last_updated = odds_data.get('last_updated') or commence_time
                                updates = [
                                    {'timestamp': first_seen, 'price': opening},
                                    {'timestamp': last_updated, 'price': current}
                                ]
                            
                            metrics = calculate_odds_metrics(updates)
                            
                            if req.profileFilter == 'sharps' and profile_type != 'Sharps':
                                continue
                            if req.profileFilter == 'squares' and profile_type != 'Squares':
                                continue
                                
                            league_code = mapped_league
                            
                            results.append({
                                'match': title,
                                'date': date_str,
                                'bookmaker': bookie,
                                'market': norm_market.upper(),
                                'opening_odd': opening,
                                'current_odd': current,
                                'drop_pct': round(drop_pct, 1),
                                'is_in_play': is_in_play,
                                'elapsed_minutes': round(elapsed_minutes),
                                'adjusted_drop_pct': round(adjusted_drop_pct, 1),
                                'liquidity_tier': tier_name,
                                'confidence_score': score,
                                'confidence_level': confidence_level,
                                'sharpness_score': sharpness_score,
                                'profile_type': profile_type,
                                'velocity': metrics['velocity_recent'],
                                'acceleration_ratio': metrics['acceleration_ratio'],
                                'acceleration_text': metrics['acceleration_text'],
                                'league_code': league_code
                            })
                            
        results = sorted(results, key=lambda x: x['drop_pct'], reverse=True)
        return {"status": "success", "scan_results": results, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/autopilot')
def get_autopilot_predictions(source: str = 'api'):
    try:
        history = load_history()
        active_portfolios = [s for s in history if (s.get('type') == 'portfolio' or 'strategy_ids' in s.get('params', {})) and s.get('is_tg_active')]
        active_strategy_ids = set()
        for p_item in active_portfolios:
            ids = p_item.get('params', {}).get('strategy_ids', [])
            active_strategy_ids.update(ids)
            
        valid_strategies = []
        for s in history:
            if s.get('type') == 'portfolio' or 'strategy_ids' in s.get('params', {}):
                continue
                
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
                hist = load_league_data(league_code, start_date='2020-08-01', data_source=auto_detect_data_source(league_code))
                league_cache[league_code] = hist
                elo_cache[league_code] = build_elo_tracker_from_history(hist, league_code)
                
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
            
            est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, pred['lambda_home'], pred['lambda_away'], pred.get('rho', RHO_FALLBACK))
            
            for strategy in valid_strategies:
                p = strategy.get('params', {})
                s_leagues = p.get('leagues', [])
                if league_code not in s_leagues:
                    continue
                    
                s_markets_raw = p.get('markets') or p.get('market', 'home')
                if isinstance(s_markets_raw, str):
                    s_markets = [m.strip() for m in s_markets_raw.split(',')]
                elif isinstance(s_markets_raw, list):
                    s_markets = [str(m).strip() for m in s_markets_raw]
                else:
                    s_markets = ['home']
                
                s_min = float(p.get('minOdds', 1.0))
                s_max = float(p.get('maxOdds', 2.50))
                s_val = float(p.get('valThreshold', 1.05))
                
                strategy_name_prefix = ""
                stakingRule = p.get('stakingRule', 'fixed')
                stakeValue = float(p.get('stakeValue', 10.0))
                initialBankroll = float(p.get('initialBankroll', 1000.0))
                
                containing_portfolio = next((p_item for p_item in active_portfolios if strategy.get('id') in p_item.get('params', {}).get('strategy_ids', [])), None) if active_portfolios else None
                
                if containing_portfolio:
                    port_params = containing_portfolio.get('params', {})
                    port_rm = port_params.get('risk_method', 'kelly_quarter')
                    if port_rm == 'kelly_quarter':
                        stakingRule = 'kelly_quarter'
                        stakeValue = 0.0
                    elif port_rm.startswith('fixed_'):
                        stakingRule = 'fixed'
                        try:
                            stakeValue = float(port_rm.split('_')[1])
                        except:
                            stakeValue = 1.0
                    else:
                        stakingRule = 'kelly_quarter'
                        stakeValue = 0.0
                        
                    initialBankroll = float(port_params.get('initial_bankroll', 1000.0))
                    strategy_name_prefix = f"[Portfólio: {containing_portfolio.get('name')}] "
                
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
                    elif s_m == 'lay_home_ex':
                        market_prob = pred['prob_draw'] + pred['prob_away']
                        try:
                            _dc = float(row.get('DC_X2')) if not pd.isna(row.get('DC_X2')) else np.nan
                            if pd.isna(_dc) or _dc <= 1.0:
                                _dc = 1.0 / (1.0/odds_d + 1.0/odds_a) if (odds_d > 1.0 and odds_a > 1.0) else np.nan
                            bookie_odds = _dc / (_dc - 1.0) if (_dc > 1.001) else np.nan
                        except Exception:
                            bookie_odds = np.nan
                        market_label = "Lay Mandante"
                    elif s_m == 'lay_away_ex':
                        market_prob = pred['prob_home'] + pred['prob_draw']
                        try:
                            _dc = float(row.get('DC_1X')) if not pd.isna(row.get('DC_1X')) else np.nan
                            if pd.isna(_dc) or _dc <= 1.0:
                                _dc = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan
                            bookie_odds = _dc / (_dc - 1.0) if (_dc > 1.001) else np.nan
                        except Exception:
                            bookie_odds = np.nan
                        market_label = "Lay Visitante"
                    elif s_m == 'lay_draw_ex':
                        market_prob = pred['prob_home'] + pred['prob_away']
                        try:
                            _dc = float(row.get('DC_12')) if not pd.isna(row.get('DC_12')) else np.nan
                            if pd.isna(_dc) or _dc <= 1.0:
                                _dc = 1.0 / (1.0/odds_h + 1.0/odds_a) if (odds_h > 1.0 and odds_a > 1.0) else np.nan
                            bookie_odds = _dc / (_dc - 1.0) if (_dc > 1.001) else np.nan
                        except Exception:
                            bookie_odds = np.nan
                        market_label = "Lay Empate"
                    elif s_m == 'dnb_h': market_prob = pred['prob_home'] / (pred['prob_home'] + pred['prob_away']) if (pred['prob_home'] + pred['prob_away']) > 0 else 0.5; bookie_odds = odds_h * (odds_d - 1.0) / odds_d if (odds_h and odds_d and odds_d > 1.0) else np.nan; market_label = "DNB Mandante"
                    elif s_m == 'dnb_a': market_prob = pred['prob_away'] / (pred['prob_home'] + pred['prob_away']) if (pred['prob_home'] + pred['prob_away']) > 0 else 0.5; bookie_odds = odds_a * (odds_d - 1.0) / odds_d if (odds_a and odds_d and odds_d > 1.0) else np.nan; market_label = "DNB Visitante"

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
                            'strategy_name': strategy_name_prefix + strategy.get('name', 'Autopilot Strategy')
                        })
                    
        autopilot_matches.sort(key=lambda x: (x['date'], x['time']))
        return autopilot_matches
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/telegram/cluster_ai_config")
def api_get_cluster_ai_config():
    return get_cluster_ai_config()

@router.post("/telegram/cluster_ai_config")
def api_save_cluster_ai_config(req: ClusterAIConfigReq):
    save_cluster_ai_config(req.dict())
    return {"status": "success"}

@router.post("/telegram/cluster_ai_test")
def api_test_cluster_ai_alerts():
    """Manually trigger cluster AI alerts for testing."""
    import asyncio
    import traceback
    from ..cluster_ai_tracker import run_cluster_ai_alerts

    logs = []
    try:
        config = get_cluster_ai_config()
        tg_config = get_telegram_config()

        if not tg_config.get('enabled'):
            return {"status": "warning", "message": "Telegram não está habilitado.", "config": config}
        if not tg_config.get('token') or not tg_config.get('chat_id'):
            return {"status": "warning", "message": "Token ou Chat ID do Telegram não configurados.", "config": config}

        diag = asyncio.run(run_cluster_ai_alerts())
        return {
            "status": "success" if not diag.get("errors") else "partial",
            "message": "Varredura concluída.",
            "diagnostics": diag,
            "config": config,
        }
    except Exception as e:
        logs.append(f"Erro: {traceback.format_exc()}")
        return {"status": "error", "message": str(e), "logs": logs}
