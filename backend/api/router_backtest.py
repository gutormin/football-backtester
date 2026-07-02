import os
import math
import numpy as np
import pandas as pd
from datetime import datetime
from typing import List, Optional, Union, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator

from ..data_loader import (
    sync_data, get_all_available_leagues, load_league_data, DATA_DIR, sync_fixtures,
    get_api_token, load_upcoming_from_api, LEAGUES_SEASONAL
)
from ..backtester import ChronologicalBacktester
from ..models import PoissonModel, estimate_bookmaker_odds
from ..elo_model import build_elo_tracker_from_history
from ..ai_predictor import apply_fdr_correction, compute_edge_quality_score
from ..portfolio_backtester import run_portfolio

router = APIRouter()

# Request schemas
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
    odds_timing: Optional[str] = "closing"
    minOdds: Optional[float] = 1.0
    maxOdds: Optional[float] = 2.50
    exchange_commission: float = 0.0
    out_of_sample: bool = False
    oos_split: Optional[float] = 20.0
    slippage: Optional[float] = None
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

    @validator('maxOddsH')
    def validate_odds_h(cls, v, values):
        min_h = values.get('minOddsH')
        if v is not None and min_h is not None and v < min_h:
            raise ValueError("odds máxima H não pode ser menor que odds mínima H")
        return v

    @validator('maxOddsD')
    def validate_odds_d(cls, v, values):
        min_d = values.get('minOddsD')
        if v is not None and min_d is not None and v < min_d:
            raise ValueError("odds máxima D não pode ser menor que odds mínima D")
        return v

    @validator('maxOddsA')
    def validate_odds_a(cls, v, values):
        min_a = values.get('minOddsA')
        if v is not None and min_a is not None and v < min_a:
            raise ValueError("odds máxima A não pode ser menor que odds mínima A")
        return v

    @validator('maxOddsOver25')
    def validate_odds_over25(cls, v, values):
        min_over = values.get('minOddsOver25')
        if v is not None and min_over is not None and v < min_over:
            raise ValueError("odds máxima Over 2.5 não pode ser menor que odds mínima Over 2.5")
        return v

    @validator('maxOddsUnder25')
    def validate_odds_under25(cls, v, values):
        min_under = values.get('minOddsUnder25')
        if v is not None and min_under is not None and v < min_under:
            raise ValueError("odds máxima Under 2.5 não pode ser menor que odds mínima Under 2.5")
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

class PredictRequest(BaseModel):
    league: str
    homeTeam: str
    awayTeam: str
    data_source: str = "footballdata"
    futpython_api_key: str = ""

    @validator('league', 'homeTeam', 'awayTeam')
    def validate_non_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("O campo não pode ser vazio")
        return v.strip()

    @validator('awayTeam')
    def validate_different_teams(cls, v, values):
        home = values.get('homeTeam')
        if home and home.strip().lower() == v.strip().lower():
            raise ValueError("O time visitante (awayTeam) deve ser diferente do time mandante (homeTeam)")
        return v

class PortfolioRequest(BaseModel):
    strategy_ids: List[str]
    initial_bankroll: float = 1000.0
    risk_method: str = "kelly_quarter"

    @validator('strategy_ids')
    def validate_strategies_list(cls, v):
        if not v:
            raise ValueError("A lista de strategy_ids não pode estar vazia")
        return v

    @validator('initial_bankroll')
    def validate_portfolio_bankroll(cls, v):
        if v <= 0:
            raise ValueError("A banca inicial deve ser maior que zero")
        return v


@router.get("/leagues")
def list_leagues(source: str = "footballdata"):
    try:
        return get_all_available_leagues(source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sync")
def trigger_sync(source: str = "csv"):
    try:
        sync_data(force=True, source=source)
        return {"status": "success", "message": f"Dados sincronizados via {source.upper()} com sucesso."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/backtest")
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
            odds_timing=req.odds_timing or 'closing',
            min_odds=req.minOdds or 1.0,
            max_odds=req.maxOdds or 2.50,
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
            max_odds_under25=req.maxOddsUnder25,
            slippage=req.slippage,
            oos_split_pct=req.oos_split if req.out_of_sample else 0.0
        )
        if "error" in results:
            raise HTTPException(status_code=400, detail=results["error"])
            
        summary = results.get('summary', {})
        results['edge_quality'] = compute_edge_quality_score(summary, summary.get('oos_summary'))
        
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/teams")
def get_teams(league: str, source: str = "footballdata", api_key: str = ""):
    try:
        df = load_league_data(league, start_date='2020-08-01', data_source=source, api_key=api_key)
        if df.empty:
            return []
        teams = sorted(list(set(df['HomeTeam'].dropna().unique()) | set(df['AwayTeam'].dropna().unique())))
        return teams
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/predict")
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
        fair_over45 = round(1.0 / (prob_lay_cs_10 := 1.0 - pred['prob_cs_10']), 2) if False else 99.0 # Placeholder/Cleaned
        
        # Recalculate correctly using pred variables
        prob_lay_home = pred['prob_draw'] + pred['prob_away']
        prob_lay_away = pred['prob_home'] + pred['prob_draw']
        prob_lay_draw = pred['prob_home'] + pred['prob_away']
        
        prob_dnb_h = pred['prob_home'] / (pred['prob_home'] + pred['prob_away']) if (pred['prob_home'] + pred['prob_away']) > 0 else 0.5
        prob_dnb_a = pred['prob_away'] / (pred['prob_home'] + pred['prob_away']) if (pred['prob_home'] + pred['prob_away']) > 0 else 0.5
        
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
        
        fair_over35 = round(1.0 / pred['prob_over_35'], 2) if pred['prob_over_35'] > 0 else 99.0
        fair_under35 = round(1.0 / pred['prob_under_35'], 2) if pred['prob_under_35'] > 0 else 99.0
        fair_over45 = round(1.0 / pred['prob_over_45'], 2) if pred['prob_over_45'] > 0 else 99.0
        fair_under45 = round(1.0 / pred['prob_under_45'], 2) if pred['prob_under_45'] > 0 else 99.0
        fair_over55 = round(1.0 / pred['prob_over_55'], 2) if pred['prob_over_55'] > 0 else 99.0
        fair_under55 = round(1.0 / pred['prob_under_55'], 2) if pred['prob_under_55'] > 0 else 99.0
        
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
        
        # Load fixtures odds if possible
        fixtures_path = os.path.join(DATA_DIR, "fixtures.csv")
        df_fix = pd.read_csv(fixtures_path, encoding='latin1') if os.path.exists(fixtures_path) else None
        
        def get_bookie_odds():
            if df_fix is None:
                return {}
            match_row = df_fix[((df_fix['HomeTeam'].str.lower() == req.homeTeam.lower()) & 
                                (df_fix['AwayTeam'].str.lower() == req.awayTeam.lower()))]
            if match_row.empty:
                return {}
            last_row = match_row.iloc[-1]
            
            def clean_odd(val):
                try:
                    v = float(val)
                    return round(v, 2) if not pd.isna(v) and v > 0 else None
                except Exception:
                    return None
                    
            return {
                'Bet365': {
                    'H': clean_odd(last_row.get('B365H') or last_row.get('B365CH')),
                    'D': clean_odd(last_row.get('B365D') or last_row.get('B365CD')),
                    'A': clean_odd(last_row.get('B365A') or last_row.get('B365CA'))
                },
                'Pinnacle': {
                    'H': clean_odd(last_row.get('PSH') or last_row.get('PSCH')),
                    'D': clean_odd(last_row.get('PSD') or last_row.get('PSCD')),
                    'A': clean_odd(last_row.get('PSA') or last_row.get('PSCA'))
                },
                'Bwin': {
                    'H': clean_odd(last_row.get('BWH') or last_row.get('BWCH')),
                    'D': clean_odd(last_row.get('BWD') or last_row.get('BWCD')),
                    'A': clean_odd(last_row.get('BWA') or last_row.get('BWCA'))
                },
                'Media': {
                    'H': clean_odd(last_row.get('AvgH') or last_row.get('AvgCH')),
                    'D': clean_odd(last_row.get('AvgD') or last_row.get('AvgCD')),
                    'A': clean_odd(last_row.get('AvgA') or last_row.get('AvgCA'))
                },
                'Maxima': {
                    'H': clean_odd(last_row.get('MaxH') or last_row.get('MaxCH')),
                    'D': clean_odd(last_row.get('MaxD') or last_row.get('MaxCD')),
                    'A': clean_odd(last_row.get('MaxA') or last_row.get('MaxCA'))
                }
            }
            
        odds_comparison = get_bookie_odds()
        
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
                'lay_cs_12': round(prob_lay_cs_12 * 100, 1),
                'dnb_h': round(prob_dnb_h * 100, 1),
                'dnb_a': round(prob_dnb_a * 100, 1)
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
                'lay_cs_12': fair_lay_cs_12,
                'dnb_h': round(1.0 / prob_dnb_h, 2) if prob_dnb_h > 0 else 99.0,
                'dnb_a': round(1.0 / prob_dnb_a, 2) if prob_dnb_a > 0 else 99.0
            },
            'fair_ah_home': pred.get('fair_ah_home', {}),
            'fair_ah_away': pred.get('fair_ah_away', {}),
            'score_grid': score_grid,
            'odds_comparison': odds_comparison
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/upcoming")
def get_upcoming_predicted_matches(
    markets: str = 'home',
    valueThreshold: float = 1.05,
    minOdds: float = 1.0,
    maxOdds: float = 2.50,
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
                elif m_key == 'dnb_h':
                    market_prob = pred['prob_home'] / (pred['prob_home'] + pred['prob_away']) if (pred['prob_home'] + pred['prob_away']) > 0 else 0.5
                    bookie_odds = odds_h * (odds_d - 1.0) / odds_d if (odds_h and odds_d and odds_d > 1.0) else np.nan
                    market_label = "DNB Mandante"
                elif m_key == 'dnb_a':
                    market_prob = pred['prob_away'] / (pred['prob_home'] + pred['prob_away']) if (pred['prob_home'] + pred['prob_away']) > 0 else 0.5
                    bookie_odds = odds_a * (odds_d - 1.0) / odds_d if (odds_a and odds_d and odds_d > 1.0) else np.nan
                    market_label = "DNB Visitante"
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

@router.post("/portfolio_backtest")
def api_run_portfolio(req: PortfolioRequest):
    try:
        res = run_portfolio(req.strategy_ids, req.initial_bankroll, req.risk_method)
        if "error" in res:
            raise HTTPException(status_code=400, detail=res["error"])
        return res
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
