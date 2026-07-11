import os
import json
import math
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from collections import defaultdict

from .probability_pipeline import ProbabilityPipeline, MODEL_POISSON
from .elo_model import EloTracker, estimate_dynamic_rho
from .backtest.helpers import get_league_weighted_decay
from .constants import ELO_K_FACTOR, ELO_HOME_ADVANTAGE, RHO_MLE_WINDOW, RHO_CACHE_INVALIDATION_MATCHES
from .data_loader import get_all_available_leagues

# ─────────────────────────────────────────────
#  CLOSING LINE VALUE (CLV) TRACKER
# ─────────────────────────────────────────────

CLV_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'data', 'steam_clv_tracker.json'
)


def load_clv_data() -> dict:
    """Carrega dados de CLV do disco."""
    if os.path.exists(CLV_FILE):
        try:
            with open(CLV_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_clv_data(data: dict) -> None:
    """Persiste dados de CLV em disco."""
    try:
        with open(CLV_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def register_detection_for_clv(harness_match_id: str, bookmaker: str, market: str,
                               detection_odd: float, detection_time: str,
                               league_code: str) -> str:
    """
    Registra um steam move para rastreamento de CLV.
    Retorna o clv_id (hash do par match+bookmaker+market).
    """
    clv_data = load_clv_data()
    clv_id = f"{harness_match_id}|{bookmaker}|{market}"

    if clv_id in clv_data:
        # Já existe — atualiza detection_odd se for mais baixa (melhor preço)
        if detection_odd < clv_data[clv_id].get('detection_odd', 999):
            clv_data[clv_id]['detection_odd'] = detection_odd
            clv_data[clv_id]['detection_time'] = detection_time
            save_clv_data(clv_data)
        return clv_id

    clv_data[clv_id] = {
        'match': harness_match_id,
        'bookmaker': bookmaker,
        'market': market,
        'detection_odd': detection_odd,
        'detection_time': detection_time,
        'league_code': league_code,
        'closing_odd': None,
        'closing_time': None,
        'resolved': False,
    }
    save_clv_data(clv_data)
    return clv_id


def update_closing_odds_for_kickoffs(tracker_data: dict) -> int:
    """
    Percorre o tracker de odds ao vivo e, para partidas que já começaram,
    registra a odd atual como 'closing odd' para as entradas CLV abertas.

    Deve ser chamado após cada ciclo de fetch_and_update_live_odds().

    Retorna número de entradas CLV resolvidas nesta chamada.
    """
    from datetime import datetime, timezone
    clv_data = load_clv_data()
    resolved_count = 0
    now_utc = datetime.now(timezone.utc)

    for match_id, match_info in tracker_data.items():
        commence_time = match_info.get('commence_time', '')
        try:
            dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
            if now_utc <= dt:
                continue  # Jogo ainda não começou
        except Exception:
            continue

        # Match já começou — para cada bookmaker/mercado, registra closing
        for bookie, markets_data in match_info.get('bookmakers', {}).items():
            for comp_key, odds_data in markets_data.items():
                norm_market = odds_data.get('norm_market', '')
                current_odd = odds_data.get('current', 0)

                clv_id = f"{match_id}|{bookie}|{norm_market}"
                if clv_id in clv_data and not clv_data[clv_id].get('resolved'):
                    clv_data[clv_id]['closing_odd'] = current_odd
                    clv_data[clv_id]['closing_time'] = now_utc.isoformat()
                    clv_data[clv_id]['resolved'] = True
                    resolved_count += 1

    if resolved_count > 0:
        save_clv_data(clv_data)
    return resolved_count


def calculate_clv_metrics(grouped_bets: list) -> dict:
    """
    Calcula métricas de CLV para um grupo de apostas.

    Retorna dict com:
      - mean_clv_pct: CLV médio em % (positivo = bateu o fechamento)
      - clv_positive_pct: % de apostas com CLV positivo
      - clv_count: número de apostas com CLV registrado
    """
    clv_data = load_clv_data()
    clv_values = []

    for bet in grouped_bets:
        match_str = bet.get('match', '')
        bookie = bet.get('bookmaker', '')
        market = bet.get('market', '')

        # Tenta match por título + bookmaker + market
        for clv_id, clv_entry in clv_data.items():
            if not clv_entry.get('resolved'):
                continue
            if (clv_entry.get('bookmaker') == bookie and
                clv_entry.get('market') == market and
                match_str.lower() in clv_entry.get('match', '').lower()):
                det_odd = clv_entry.get('detection_odd', 0)
                cls_odd = clv_entry.get('closing_odd', 0)
                if det_odd > 1.0 and cls_odd > 1.0:
                    # CLV positivo = detection_odd > closing_odd (você pegou preço melhor)
                    clv_pct = ((det_odd / cls_odd) - 1.0) * 100.0
                    clv_values.append(clv_pct)
                break

    if not clv_values:
        return {'mean_clv_pct': 0.0, 'clv_positive_pct': 0.0, 'clv_count': 0}

    mean_clv = np.mean(clv_values)
    positive_pct = (sum(1 for v in clv_values if v > 0) / len(clv_values)) * 100
    return {
        'mean_clv_pct': round(mean_clv, 2),
        'clv_positive_pct': round(positive_pct, 1),
        'clv_count': len(clv_values),
    }


# ─────────────────────────────────────────────
#  LIQUIDEZ E CONFIANÇA
# ─────────────────────────────────────────────

def estimate_liquidity_tier(league_identifier: str):
    """
    Estima a liquidez da liga baseado em sua sigla/nome.
    Retorna (tier_name, weight) onde:
    - tier_name: 'Alta', 'Média', 'Baixa'
    - weight: 1.0, 0.7, 0.4
    """
    if not league_identifier:
        return 'Baixa', 0.4
    lid = league_identifier.lower().strip()

    # Tier 1 - Alta Liquidez (Peso 1.0)
    t1_keys = [
        'e0', 'sp1', 'i1', 'd1', 'f1', 'bra',
        'premier_league', 'la_liga', 'serie_a', 'bundesliga', 'ligue1',
        'campeonato_brasileiro', 'brazil_serie_a'
    ]
    is_t1 = any(k in lid for k in t1_keys)
    if is_t1:
        if 'bundesliga2' in lid or 'bundesliga_2' in lid or 'serie_b' in lid or 'segunda' in lid:
            pass
        else:
            return 'Alta', 1.0

    # Tier 2 - Média Liquidez (Peso 0.7)
    t2_keys = [
        'e1', 'sp2', 'i2', 'd2', 'f2', 'n1', 'b1', 'p1', 't1', 'usa', 'jpn',
        'championship', 'segunda', 'serie_b', 'bundesliga2', 'bundesliga_2',
        'ligue2', 'eredivisie', 'primeira_liga', 'belgium_first_division',
        'super_league', 'mls', 'j_league', 'japan_j_league',
        'netherlands_eredivisie', 'portugal_primeira_liga', 'turkey_super_league'
    ]
    if any(k in lid for k in t2_keys):
        return 'Média', 0.7

    # Tier 3 - Baixa Liquidez (Peso 0.4)
    return 'Baixa', 0.4


def calculate_confidence_score(drop_pct: float, league_identifier: str):
    """
    Calcula um score de confiança de 0 a 100 com base no drop de odds e na liquidez da liga.
    Ligas de alta liquidez exigem menos variação para serem de alta confiança.
    Ligas de baixa liquidez exigem variações violentas para mitigar ruídos de baixo volume.
    Retorna (score, confidence_level, liquidity_tier)

    Se existir calibração salva (steam_confidence_calibration.json), usa thresholds
    calibrados empiricamente. Caso contrário, usa thresholds heurísticos padrão.
    """
    tier_name, weight = estimate_liquidity_tier(league_identifier)
    if drop_pct <= 0:
        return 0.0, 'Baixa', tier_name

    # Carrega calibração se existir
    cal = _load_confidence_calibration()

    if cal and cal.get('calibrated'):
        # Usa fórmula calibrada: score = intercept + drop_pct * slope
        # com caps baseados em evidência empírica
        params = cal.get('tier_params', {}).get(tier_name, {})
        intercept = params.get('intercept', 35.0 if tier_name == 'Alta' else 15.0 if tier_name == 'Média' else 0.0)
        slope = params.get('slope', 12.0 if tier_name == 'Alta' else 8.0 if tier_name == 'Média' else 5.0)
        score = min(100.0, intercept + (drop_pct * slope))
    else:
        # Fórmulas heurísticas padrão (fallback)
        if tier_name == 'Alta':
            score = min(100.0, 35.0 + (drop_pct * 12.0))
        elif tier_name == 'Média':
            score = min(100.0, 15.0 + (drop_pct * 8.0))
        else:  # Baixa
            score = min(100.0, drop_pct * 5.0)

    # Thresholds calibrados ou padrão
    if cal and cal.get('calibrated'):
        thresholds = cal.get('thresholds', {})
        high_th = thresholds.get('high', 75.0)
        med_th = thresholds.get('medium', 45.0)
    else:
        high_th, med_th = 75.0, 45.0

    if score >= high_th:
        confidence_level = 'Alta'
    elif score >= med_th:
        confidence_level = 'Média'
    else:
        confidence_level = 'Baixa'

    return round(score, 1), confidence_level, tier_name


# ── Confidence calibration persistence ─────────────────────────────────

CALIBRATION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'data', 'steam_confidence_calibration.json'
)


def _load_confidence_calibration() -> dict:
    """Carrega calibração de confiança do disco."""
    if os.path.exists(CALIBRATION_FILE):
        try:
            with open(CALIBRATION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_confidence_calibration(cal: dict) -> None:
    """Persiste calibração em disco."""
    try:
        with open(CALIBRATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(cal, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def calibrate_confidence_from_history(min_resolved_bets: int = 50) -> dict:
    """
    Calibra os thresholds de confiança usando dados históricos resolvidos.

    Carrega todas as apostas resolvidas do histórico de steam moves e:
    1. Calcula win_rate por bucket de score (0-25, 25-45, 45-60, 60-75, 75+)
    2. Se houver dados suficientes, ajusta os thresholds para alinhar com
       win_rate observado
    3. Calcula slope e intercept ótimos por tier via regressão linear simples
       (win_rate ~ drop_pct)
    4. Salva a calibração em steam_confidence_calibration.json

    Args:
        min_resolved_bets: mínimo de apostas resolvidas para calibrar (default 50)

    Returns:
        dict com métricas de calibração e status
    """
    import math
    history_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 'data', 'live_steam_moves_history.json'
    )

    all_bets = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            all_bets = [b for b in raw if b.get('resolved') and b.get('won') is not None]
        except Exception:
            pass

    if len(all_bets) < min_resolved_bets:
        return {
            'calibrated': False,
            'message': f'Apenas {len(all_bets)} apostas resolvidas. Mínimo: {min_resolved_bets}.',
            'total_resolved': len(all_bets),
        }

    # ── Agrupar por tier e calcular win_rate por decil de drop_pct ──────
    tier_buckets = {'Alta': [], 'Média': [], 'Baixa': []}
    for bet in all_bets:
        lcode = bet.get('league_code', '')
        drop_pct = bet.get('drop_pct', 0)
        won = bet.get('won', False)
        tier, _ = estimate_liquidity_tier(lcode)
        tier_buckets[tier].append({'drop_pct': drop_pct, 'won': won})

    # ── Regressão linear simples: win_rate ~ drop_pct por tier ─────────
    cal_params = {}
    tier_metrics = {}
    overall_n = 0

    for tier, bets in tier_buckets.items():
        if len(bets) < 15:
            # Fallback para defaults heurísticos
            if tier == 'Alta':
                cal_params[tier] = {'intercept': 35.0, 'slope': 12.0, 'n': len(bets)}
            elif tier == 'Média':
                cal_params[tier] = {'intercept': 15.0, 'slope': 8.0, 'n': len(bets)}
            else:
                cal_params[tier] = {'intercept': 0.0, 'slope': 5.0, 'n': len(bets)}
            tier_metrics[tier] = {'n': len(bets), 'fallback': True}
            continue

        xs = np.array([b['drop_pct'] for b in bets])
        ys = np.array([1.0 if b['won'] else 0.0 for b in bets])

        # Simple linear regression: win_rate = alpha + beta * drop_pct
        # Then score = intercept + slope * drop_pct
        # where intercept and slope map to 0-100 score space
        x_mean, y_mean = np.mean(xs), np.mean(ys)
        beta = np.sum((xs - x_mean) * (ys - y_mean)) / (np.sum((xs - x_mean) ** 2) + 1e-10)
        alpha = y_mean - beta * x_mean

        # Map to 0-100 scale: score = (alpha + beta * drop_pct) * 100
        # Capped at [0, 100]
        # We want: intercept ≈ base confidence at 0% drop, slope ≈ sensitivity
        intercept_100 = max(0.0, min(100.0, alpha * 100.0))
        slope_100 = max(2.0, min(30.0, beta * 100.0))  # Sensible bounds

        cal_params[tier] = {
            'intercept': round(intercept_100, 2),
            'slope': round(slope_100, 2),
            'n': len(bets),
            'mean_win_rate': round(y_mean * 100, 1),
            'r_squared': round(
                1.0 - np.sum((ys - (alpha + beta * xs)) ** 2) / (np.sum((ys - y_mean) ** 2) + 1e-10), 3
            ),
        }
        tier_metrics[tier] = {'n': len(bets), 'mean_win_rate_pct': round(y_mean * 100, 1)}
        overall_n += len(bets)

    # ── Calcular thresholds ótimos baseados nos decis empíricos ─────────
    # Ordena todas as apostas por confidence score (usando novas fórmulas)
    scored_bets = []
    for bet in all_bets:
        lcode = bet.get('league_code', '')
        drop_pct = bet.get('drop_pct', 0)
        won = bet.get('won', False)
        tier, _ = estimate_liquidity_tier(lcode)
        params = cal_params.get(tier, {})
        intercept = params.get('intercept', 35.0)
        slope = params.get('slope', 12.0)
        score = min(100.0, intercept + drop_pct * slope)
        scored_bets.append({'score': score, 'won': won})

    scored_bets.sort(key=lambda x: x['score'])

    # Determina thresholds: high = score onde win_rate > break_even da odd média
    # Simplificação: usa tercis da distribuição de scores dos vencedores
    winner_scores = [b['score'] for b in scored_bets if b['won']]
    loser_scores = [b['score'] for b in scored_bets if not b['won']]

    if len(winner_scores) >= 10 and len(loser_scores) >= 10:
        # High threshold: mediana dos winners
        high_threshold = round(np.percentile(winner_scores, 50), 1)
        # Medium threshold: mediana geral
        all_scores = [b['score'] for b in scored_bets]
        medium_threshold = round(np.percentile(all_scores, 33), 1)
    else:
        high_threshold, medium_threshold = 75.0, 45.0

    calibration = {
        'calibrated': True,
        'calibrated_at': datetime.now(timezone.utc).isoformat(),
        'total_resolved': len(all_bets),
        'thresholds': {
            'high': high_threshold,
            'medium': medium_threshold,
        },
        'tier_params': cal_params,
        'tier_details': tier_metrics,
        'note': 'Thresholds derivados empiricamente de apostas resolvidas. '
                'high = mediana do score dos winners, medium = percentil 33 geral.',
    }

    _save_confidence_calibration(calibration)
    return calibration


def classify_drop_profile(
    drop_pct: float,
    league_identifier: str,
    commence_time_str: str,
    bookmaker_name: str,
    match_entry: dict = None,
    comp_key: str = None
):
    """
    Classifica se o movimento de odds foi provocado por Sharps (dinheiro inteligente)
    ou Squares (público geral/tipster followers).
    Retorna (sharpness_score, profile_type)
    """
    score = 0.0

    # 1. Origem e Consenso (Máx: 35 pontos)
    if bookmaker_name.lower() == 'pinnacle':
        score += 35.0
    else:
        pinnacle_dropped = False
        has_pinnacle = False
        if match_entry and 'bookmakers' in match_entry:
            pinnacle_data = match_entry['bookmakers'].get('Pinnacle')
            if pinnacle_data and comp_key in pinnacle_data:
                has_pinnacle = True
                p_entry = pinnacle_data[comp_key]
                p_open = p_entry.get('opening', 0.0)
                p_curr = p_entry.get('current', 0.0)
                if p_open > 1.0 and p_curr > 0.0 and p_curr < p_open:
                    p_drop = ((p_open / p_curr) - 1.0) * 100
                    if p_drop >= 4.0:
                        pinnacle_dropped = True
        
        if pinnacle_dropped:
            score += 25.0
        elif has_pinnacle:
            score += 0.0
        else:
            score += 12.0

    # 2. Antecedência (Máx: 25 pontos)
    if match_entry is None:
        diff_hours = 12.0  # fallback para histórico CSV
    else:
        try:
            dt_commence = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
            dt_now = datetime.now(timezone.utc)
            diff_hours = (dt_commence - dt_now).total_seconds() / 3600.0
        except Exception:
            diff_hours = 4.0

    if diff_hours >= 12.0:
        score += 25.0
    elif diff_hours >= 6.0:
        score += 18.0
    elif diff_hours >= 3.0:
        score += 10.0
    else:
        score += 0.0

    # 3. Liquidez da Liga (Máx: 25 pontos)
    tier_name, _ = estimate_liquidity_tier(league_identifier)
    if tier_name == 'Alta':
        score += 25.0
    elif tier_name == 'Média':
        score += 12.0
    else:
        score += 0.0

    # 4. Magnitude da Queda (Máx: 15 pontos)
    if drop_pct >= 10.0:
        score += 15.0
    elif drop_pct >= 7.5:
        score += 10.0
    elif drop_pct >= 5.0:
        score += 5.0

    profile_type = 'Sharps' if score >= 60.0 else 'Squares'
    return round(score, 1), profile_type


# ─────────────────────────────────────────────
#  REVERSE LINE MOVEMENT DETECTION
# ─────────────────────────────────────────────

def detect_reverse_line_movement(match_odds_snapshot: dict) -> list:
    """
    Detecta Reverse Line Movement (RLM): odds caindo em um lado
    apesar do público estar apostando majoritariamente no outro lado.

    RLM é considerado o sinal mais forte de smart money porque indica
    que o dinheiro informado está movendo a linha CONTRA o consenso.

    Args:
        match_odds_snapshot: dict com estrutura:
            {
                'home_odds': {'pinnacle': {'open': 2.0, 'current': 1.85}, 'bet365': {...}},
                'away_odds': {...},
                'draw_odds': {...},
                'public_betting_pct': {'home': 65.0, 'away': 20.0, 'draw': 15.0},  # opcional
            }

    Returns:
        Lista de dicts com sinais RLM detectados:
            [
                {
                    'market': 'home',
                    'drop_pct': 7.5,
                    'public_pct': 25.0,  # minoria do público
                    'rlm_score': 80,     # 0-100
                    'signal': 'strong_buy',
                }
            ]

    Nota: public_betting_pct requer fonte externa (Betfair Exchange, OddsJam,
    Action Network). Sem ela, o detector usa proxy baseado em dispersão de odds.
    """
    results = []
    bookie_data = match_odds_snapshot.get('home_odds', {})

    # Sem dados de % público, usa proxy:
    # RLM proxy: odd cai em uma casa mas NÃO cai nas outras (movimento isolado
    # pode ser manipulação de bookmaker, não smart money)
    all_home_drops = []
    for bookie, odds in match_odds_snapshot.get('home_odds', {}).items():
        open_odd = odds.get('open', 0)
        curr_odd = odds.get('current', 0)
        if open_odd > 1.0 and curr_odd > 1.0 and curr_odd < open_odd:
            drop_pct = ((open_odd / curr_odd) - 1.0) * 100.0
            all_home_drops.append({'bookmaker': bookie, 'drop_pct': drop_pct, 'open': open_odd, 'current': curr_odd})

    all_away_drops = []
    for bookie, odds in match_odds_snapshot.get('away_odds', {}).items():
        open_odd = odds.get('open', 0)
        curr_odd = odds.get('current', 0)
        if open_odd > 1.0 and curr_odd > 1.0 and curr_odd < open_odd:
            drop_pct = ((open_odd / curr_odd) - 1.0) * 100.0
            all_away_drops.append({'bookmaker': bookie, 'drop_pct': drop_pct, 'open': open_odd, 'current': curr_odd})

    # RLM proxy: se home está caindo E away está SUBINDO em múltiplas casas,
    # isso é RLM (dinheiro entrando forte no home, afastando o público do away)
    # O contrário também vale (away caindo + home subindo)
    public_pct = match_odds_snapshot.get('public_betting_pct', {})

    if all_home_drops and not all_away_drops:
        # Home caindo, away estável ou subindo → possível RLM no home
        avg_drop = np.mean([d['drop_pct'] for d in all_home_drops])
        n_bookies = len(all_home_drops)
        rlm_score = min(100.0, avg_drop * 5.0 + n_bookies * 8.0)
        home_public = public_pct.get('home', 50.0)
        if home_public < 45.0:  # Minoria do público apostando no home
            rlm_score += 20.0

        if rlm_score >= 30.0:
            results.append({
                'market': 'home',
                'drop_pct': round(avg_drop, 1),
                'n_bookies_dropping': n_bookies,
                'public_pct': home_public,
                'rlm_score': round(rlm_score, 1),
                'signal': 'strong_buy' if rlm_score >= 60 else 'moderate_buy',
                'has_public_data': bool(public_pct),
            })

    if all_away_drops and not all_home_drops:
        avg_drop = np.mean([d['drop_pct'] for d in all_away_drops])
        n_bookies = len(all_away_drops)
        rlm_score = min(100.0, avg_drop * 5.0 + n_bookies * 8.0)
        away_public = public_pct.get('away', 50.0)
        if away_public < 45.0:
            rlm_score += 20.0

        if rlm_score >= 30.0:
            results.append({
                'market': 'away',
                'drop_pct': round(avg_drop, 1),
                'n_bookies_dropping': n_bookies,
                'public_pct': away_public,
                'rlm_score': round(rlm_score, 1),
                'signal': 'strong_buy' if rlm_score >= 60 else 'moderate_buy',
                'has_public_data': bool(public_pct),
            })

    return results


# ─────────────────────────────────────────────
#  SCANNER HISTÓRICO DE STEAM MOVES
# ─────────────────────────────────────────────

def _calc_fair_odds(prob: float) -> float:
    """Converte probabilidade em odd justa (sem margem)."""
    if prob <= 0 or prob >= 1:
        return np.nan
    return round(1.0 / prob, 4)


def _extract_steam_moves_from_df(
    df: pd.DataFrame,
    league_code: str,
    markets: list,
    min_drop_pct: float,
    stake_value: float,
    start_date: str,
    end_date: str,
    latency_seconds: int = 0,
    detection_mode: str = "model_edge"
) -> list:
    """
    Analisa oportunidades históricas em um DataFrame de resultados.

    Dois modos de detecção:

    "model_edge" (default):
      - Compara a odd justa do modelo Poisson/Dixon-Coles com a odd Bet365 do CSV.
      - NÃO detecta steam moves reais — detecta value bets (EV positivo segundo o modelo).
      - Se a odd Bet365 está ACIMA da odd justa em >= min_drop_pct%, há edge.
      - Este é um SCANNER DE VALUE BETTING, não de smart money.

    "temporal_drop":
      - Detecta quedas REAIS de odds entre abertura e fechamento do mesmo bookmaker.
      - Requer colunas de abertura (ex: PSCH/PSCD/PSCA para Pinnacle nos CSVs FD,
        ou odds de abertura de outras casas nos FutPython).
      - Só funciona se o CSV tiver colunas de opening odds.
      - Se as colunas não existirem, retorna lista vazia.

    detection_type no output:
      - "model_edge": value bet do modelo (Poisson/Dixon-Coles vs bookmaker)
      - "odds_movement": queda temporal real de odds (opening → closing)
    """
    if df is None or df.empty:
        return []

    # Filtrar por data
    try:
        df = df.copy()
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['Date'])
        df = df[(df['Date'] >= pd.to_datetime(start_date)) &
                (df['Date'] <= pd.to_datetime(end_date))]
    except Exception:
        pass

    if df.empty:
        return []

    # ── Auto-detect temporal columns ──────────────────────────────────────
    # Pinnacle opening columns (football-data.co.uk standard CSVs)
    # PSH/PSD/PSA = Pinnacle opening; PSCH/PSCD/PSCA = Pinnacle closing
    has_pinnacle_open = all(c in df.columns for c in ['PSH', 'PSD', 'PSA'])
    has_pinnacle_close = all(c in df.columns for c in ['PSCH', 'PSCD', 'PSCA'])
    has_pinnacle_temporal = has_pinnacle_open and has_pinnacle_close

    # Force mode: if user asked for temporal but we have no columns, return empty
    effective_mode = detection_mode
    if detection_mode == "temporal_drop" and not has_pinnacle_temporal:
        # No temporal columns available — return empty list (don't generate false positives)
        return []

    pipeline = None
    elo = None
    if effective_mode == "model_edge":
        pipeline = ProbabilityPipeline(model_type=MODEL_POISSON)
        elo = EloTracker(k_factor=ELO_K_FACTOR, home_advantage=ELO_HOME_ADVANTAGE)

    # ═══ Chronological form tracking (like the engine) ═══
    team_h_scored = defaultdict(list)
    team_h_conceded = defaultdict(list)
    team_a_scored = defaultdict(list)
    team_a_conceded = defaultdict(list)
    team_h_sot = defaultdict(list)
    team_h_sot_conc = defaultdict(list)
    team_a_sot = defaultdict(list)
    team_a_sot_conc = defaultdict(list)
    team_h_xg = defaultdict(list)
    team_h_xg_conc = defaultdict(list)
    team_a_xg = defaultdict(list)
    team_a_xg_conc = defaultdict(list)
    team_h_scored_ht = defaultdict(list)
    team_h_conceded_ht = defaultdict(list)
    team_a_scored_ht = defaultdict(list)
    team_a_conceded_ht = defaultdict(list)

    # League-level tracking
    lge_h_goals = defaultdict(list)
    lge_a_goals = defaultdict(list)
    lge_h_sot = defaultdict(list)
    lge_a_sot = defaultdict(list)
    lge_h_xg = defaultdict(list)
    lge_a_xg = defaultdict(list)
    lge_h_goals_ht = defaultdict(list)
    lge_a_goals_ht = defaultdict(list)

    league_rho_cache = {}
    league_goals_for_rho = defaultdict(lambda: {'h': [], 'a': [], 'lh': [], 'la': []})

    # Pre-warm ratings: iterate once to compute global averages
    for _, row in df.iterrows():
        fthg = row.get('FTHG', np.nan)
        ftag = row.get('FTAG', np.nan)
        if pd.isna(fthg) or pd.isna(ftag):
            continue
        lc = league_code
        lge_h_goals[lc].append(fthg)
        lge_a_goals[lc].append(ftag)
        hst = row.get('HST')
        ast = row.get('AST')
        if not pd.isna(hst):
            lge_h_sot[lc].append(hst)
        if not pd.isna(ast):
            lge_a_sot[lc].append(ast)
        hxg_val = row.get('HomeXG')
        axg_val = row.get('AwayXG')
        if not pd.isna(hxg_val) and hxg_val > 0:
            lge_h_xg[lc].append(hxg_val)
        if not pd.isna(axg_val) and axg_val > 0:
            lge_a_xg[lc].append(axg_val)

    # ── Helper: resolve outcome (shared by both modes) ────────────────────
    def _resolve_outcome(ftr, mkt, row):
        """Returns (won: bool|None, profit: float)."""
        if pd.isna(ftr):
            return None, 0.0
        ftr_str = str(ftr).strip().upper()
        if mkt in ('home', 'draw', 'away'):
            won = (
                (mkt == 'home' and ftr_str == 'H') or
                (mkt == 'draw' and ftr_str == 'D') or
                (mkt == 'away' and ftr_str == 'A')
            )
            return won, 0.0
        elif mkt in ('over25', 'under25'):
            fthg = row.get('FTHG', np.nan)
            ftag = row.get('FTAG', np.nan)
            if pd.notna(fthg) and pd.notna(ftag):
                tg = fthg + ftag
                return (
                    (mkt == 'over25' and tg > 2.5) or
                    (mkt == 'under25' and tg < 2.5)
                ), 0.0
        return None, 0.0

    def _make_alert(date_str, match_str, lcode, bookie, mkt, opening_odd,
                    current_odd, resolved_won, detection_type_label):
        """Builds a standard alert dict for both detection modes."""
        # For model_edge: opening_odd = fair_odd (model), current_odd = bookie_odd.
        # Edge = ((bookie / fair) - 1) * 100 → positive when bookie > fair.
        # For odds_movement: opening_odd = real opening, current_odd = real current.
        # Drop = ((open / current) - 1) * 100 → positive when current < open.
        if detection_type_label == 'model_edge':
            drop_pct = ((current_odd / opening_odd) - 1.0) * 100.0 if opening_odd > 0 else 0.0
        else:
            drop_pct = ((opening_odd / current_odd) - 1.0) * 100.0 if current_odd > 0 else 0.0
        score, confidence_level, tier_name = calculate_confidence_score(drop_pct, lcode)
        sharpness_score, profile_type = classify_drop_profile(
            drop_pct=drop_pct, league_identifier=lcode,
            commence_time_str=date_str, bookmaker_name=bookie,
            match_entry=None, comp_key=None
        )

        executed_odd = current_odd
        profit = 0.0
        won = None
        if resolved_won is not None:
            won = resolved_won[0] if isinstance(resolved_won, tuple) else resolved_won
            if latency_seconds > 0 and detection_type_label == 'odds_movement':
                sf = 1.0 - math.exp(-0.005 * latency_seconds)
                executed_odd = max(1.01, current_odd - (opening_odd - current_odd) * sf)
            elif isinstance(resolved_won, tuple):
                pass  # executed_odd stays as current_odd
            profit = round((executed_odd - 1.0) * stake_value if won else -stake_value, 2)

        return {
            'date': date_str,
            'match': match_str,
            'league_code': lcode,
            'bookmaker': bookie,
            'market': mkt,
            'opening_odd': round(opening_odd, 3),
            'current_odd': round(current_odd, 3),
            'executed_odd': round(executed_odd, 3),
            'drop_pct': round(drop_pct, 1),
            'confidence_score': score,
            'confidence_level': confidence_level,
            'liquidity_tier': tier_name,
            'sharpness_score': sharpness_score,
            'profile_type': profile_type,
            'won': won,
            'profit': profit,
            'stake_value': stake_value,
            'resolved': won is not None,
            'source': 'historical_csv',
            'detection_type': detection_type_label,
        }

    steam_moves = []

    # ══════════════════════════════════════════════════════════════════════
    #  MODO TEMPORAL: opening → closing odds do mesmo bookmaker
    # ══════════════════════════════════════════════════════════════════════
    if effective_mode == "temporal_drop":
        for _, row in df.iterrows():
            home_team = str(row.get('HomeTeam', ''))
            away_team = str(row.get('AwayTeam', ''))
            ftr = row.get('FTR')
            date_val = row.get('Date')
            try:
                date_str = date_val.strftime('%Y-%m-%d') if hasattr(date_val, 'strftime') else str(date_val)
            except Exception:
                date_str = str(date_val)

            match_str = f"{home_team} vs {away_team}"

            # Pinnacle open → close (1X2)
            market_cols = {
                'home': ('PSH', 'PSCH'),
                'draw': ('PSD', 'PSCD'),
                'away': ('PSA', 'PSCA'),
            }
            for mkt in markets:
                if mkt not in market_cols:
                    continue
                open_col, close_col = market_cols[mkt]
                open_odd = row.get(open_col, np.nan)
                close_odd = row.get(close_col, np.nan)
                if pd.isna(open_odd) or pd.isna(close_odd) or open_odd <= 1.0 or close_odd <= 1.0:
                    continue
                drop_pct = ((open_odd / close_odd) - 1.0) * 100.0
                if drop_pct < min_drop_pct:
                    continue
                outcome = _resolve_outcome(ftr, mkt, row)
                alert = _make_alert(date_str, match_str, league_code, 'Pinnacle',
                                    mkt, open_odd, close_odd, outcome, 'odds_movement')
                steam_moves.append(alert)

        return steam_moves

    # ══════════════════════════════════════════════════════════════════════
    #  MODO MODEL_EDGE: value betting (modelo vs bookmaker)
    # ══════════════════════════════════════════════════════════════════════
    for _, row in df.iterrows():
        home_team = str(row.get('HomeTeam', ''))
        away_team = str(row.get('AwayTeam', ''))
        ftr = row.get('FTR')
        date_val = row.get('Date')

        try:
            date_str = date_val.strftime('%Y-%m-%d') if hasattr(date_val, 'strftime') else str(date_val)
        except Exception:
            date_str = str(date_val)

        match_str = f"{home_team} vs {away_team}"

        # Odds Bet365 disponíveis no CSV
        b365h = row.get('B365H', np.nan)
        b365d = row.get('B365D', np.nan)
        b365a = row.get('B365A', np.nan)
        b365o = row.get('B365>2.5', np.nan)
        b365u = row.get('B365<2.5', np.nan)

        # Compute probabilities via unified pipeline (Dixon-Coles + Elo + decay)
        fthg_val = row.get('FTHG', np.nan)
        ftag_val = row.get('FTAG', np.nan)
        hst_val = row.get('HST')
        ast_val = row.get('AST')
        hxg_csv = row.get('HomeXG')
        axg_csv = row.get('AwayXG')
        hthg_val = row.get('HTHG')
        htag_val = row.get('HTAG')

        decay = get_league_weighted_decay(league_code)
        try:
            bundle = pipeline.compute_all(
                team_h_scored, team_h_conceded,
                team_a_scored, team_a_conceded,
                lge_h_goals, lge_a_goals,
                team_h_sot, team_h_sot_conc,
                team_a_sot, team_a_sot_conc,
                lge_h_sot, lge_a_sot,
                team_h_xg, team_h_xg_conc,
                team_a_xg, team_a_xg_conc,
                lge_h_xg, lge_a_xg,
                team_h_scored_ht, team_h_conceded_ht,
                team_a_scored_ht, team_a_conceded_ht,
                lge_h_goals_ht, lge_a_goals_ht,
                home_team, away_team, league_code, decay,
                league_rho_cache, league_goals_for_rho, elo,
            )
            p_home = bundle.prob_h
            p_draw = bundle.prob_d
            p_away = bundle.prob_a
            p_over25 = bundle.prob_over_25
            p_under25 = 1.0 - p_over25
        except Exception:
            continue

        # Mapa: mercado → (prob_modelo, odd_bookie, resultado_vencedor)
        market_map = {
            'home':    (p_home,    b365h, 'H'),
            'draw':    (p_draw,    b365d, 'D'),
            'away':    (p_away,    b365a, 'A'),
            'over25':  (p_over25,  b365o, 'O'),
            'under25': (p_under25, b365u, 'U'),
        }

        for mkt in markets:
            if mkt not in market_map:
                continue

            prob_model, bookie_odd, _winner_code = market_map[mkt]
            if pd.isna(bookie_odd) or bookie_odd <= 1.0 or prob_model <= 0:
                continue

            fair_odd = _calc_fair_odds(prob_model)
            if pd.isna(fair_odd) or fair_odd <= 1.0:
                continue

            # Value bet: modelo diz que odd justa é menor que a do bookmaker
            # → o bookmaker está pagando mais do que deveria
            # bookie_odd > fair_odd → edge a favor do apostador
            edge_pct = ((bookie_odd / fair_odd) - 1.0) * 100.0

            if edge_pct < min_drop_pct:
                continue

            outcome = _resolve_outcome(ftr, mkt, row)

            # For model_edge: opening = fair_odd (teórico), current = bookie_odd
            alert = _make_alert(date_str, match_str, league_code, 'Bet365',
                                mkt, fair_odd, bookie_odd, outcome, 'model_edge')
            # Override opening_odd: fair_odd is NOT an opening odd, it's a model fair value
            # Keep it for display clarity but the detection_type makes the distinction
            steam_moves.append(alert)

        # ── Update chronological form tracking after match ──
        if not pd.isna(fthg_val) and not pd.isna(ftag_val):
            fthg_i = int(fthg_val)
            ftag_i = int(ftag_val)

            team_h_scored[home_team].append(fthg_i)
            team_h_conceded[home_team].append(ftag_i)
            team_a_scored[away_team].append(ftag_i)
            team_a_conceded[away_team].append(fthg_i)

            if not pd.isna(hst_val): team_h_sot[home_team].append(float(hst_val))
            if not pd.isna(ast_val): team_h_sot_conc[home_team].append(float(ast_val))
            if not pd.isna(ast_val): team_a_sot[away_team].append(float(ast_val))
            if not pd.isna(hst_val): team_a_sot_conc[away_team].append(float(hst_val))

            if not pd.isna(hxg_csv) and hxg_csv > 0:
                team_h_xg[home_team].append(float(hxg_csv))
                team_a_xg_conc[away_team].append(float(hxg_csv))
            else:
                team_h_xg[home_team].append(np.mean(lge_h_xg.get(league_code, [1.45])))
                team_a_xg_conc[away_team].append(np.mean(lge_h_xg.get(league_code, [1.45])))
            if not pd.isna(axg_csv) and axg_csv > 0:
                team_a_xg[away_team].append(float(axg_csv))
                team_h_xg_conc[home_team].append(float(axg_csv))
            else:
                team_a_xg[away_team].append(np.mean(lge_a_xg.get(league_code, [1.15])))
                team_h_xg_conc[home_team].append(np.mean(lge_a_xg.get(league_code, [1.15])))

            if not pd.isna(hthg_val): team_h_scored_ht[home_team].append(int(hthg_val))
            if not pd.isna(htag_val): team_h_conceded_ht[home_team].append(int(htag_val))
            if not pd.isna(htag_val): team_a_scored_ht[away_team].append(int(htag_val))
            if not pd.isna(hthg_val): team_a_conceded_ht[away_team].append(int(hthg_val))

            lge_h_goals[league_code].append(fthg_i)
            lge_a_goals[league_code].append(ftag_i)
            if not pd.isna(hst_val): lge_h_sot[league_code].append(float(hst_val))
            if not pd.isna(ast_val): lge_a_sot[league_code].append(float(ast_val))
            if not pd.isna(hthg_val): lge_h_goals_ht[league_code].append(int(hthg_val))
            if not pd.isna(htag_val): lge_a_goals_ht[league_code].append(int(htag_val))

            rho_data = league_goals_for_rho[league_code]
            rho_data['h'].append(fthg_i)
            rho_data['a'].append(ftag_i)
            rho_data['lh'].append(bundle.lambda_goals_home)
            rho_data['la'].append(bundle.lambda_goals_away)
            if len(rho_data['h']) > RHO_MLE_WINDOW:
                for k in rho_data:
                    rho_data[k] = rho_data[k][-RHO_MLE_WINDOW:]

            elo.update(home_team, away_team, fthg_i, ftag_i)

            if len(rho_data['h']) % RHO_CACHE_INVALIDATION_MATCHES == 0:
                league_rho_cache.pop(league_code, None)

    return steam_moves


# ─────────────────────────────────────────────
#  CLASSE PRINCIPAL
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
#  STEAM MOVE SUCCESS PROBABILITY MODEL (ML)
# ─────────────────────────────────────────────

SM_ML_MODEL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'data', 'steam_success_model.json'
)


def train_steam_success_model(min_samples: int = 100) -> dict:
    """
    Treina um modelo de regressão logística para prever a probabilidade
    de um steam move ser lucrativo com base em features observáveis.

    Features:
      - drop_pct: magnitude da queda
      - liquidity_score: 1.0 (alta), 0.7 (média), 0.4 (baixa)
      - time_before_kickoff_hours: antecedência em horas
      - velocity_recent: velocidade recente do drop (%/h)
      - acceleration_ratio: fator de aceleração
      - is_pinnacle: 1 se originado da Pinnacle, 0 caso contrário
      - market_is_home: 1 se mercado home
      - market_is_draw: 1 se mercado draw
      - market_is_over: 1 se mercado over
      - market_is_under: 1 se mercado under
      - elo_diff (proxy): calculado do histórico

    Retorna dict com métricas do modelo (coeficientes, AIC, pseudo-R²).
    O modelo é salvo em steam_success_model.json.
    """
    history_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 'data', 'live_steam_moves_history.json'
    )

    all_bets = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            all_bets = [b for b in raw if b.get('resolved') and b.get('won') is not None]
        except Exception:
            pass

    if len(all_bets) < min_samples:
        return {
            'trained': False,
            'message': f'Precisa de {min_samples} apostas resolvidas. Disponível: {len(all_bets)}.',
            'n_samples': len(all_bets),
        }

    # Extrai features
    X_list = []
    y_list = []
    feature_names = [
        'drop_pct', 'liquidity_score', 'is_pinnacle',
        'market_is_home', 'market_is_draw', 'market_is_away',
        'market_is_over', 'market_is_under',
    ]

    for bet in all_bets:
        lcode = bet.get('league_code', '')
        tier_name, weight = estimate_liquidity_tier(lcode)
        bookie = bet.get('bookmaker', '').lower()
        market = bet.get('market', '').lower()
        drop_pct = bet.get('drop_pct', 0)

        features = [
            drop_pct,
            weight,  # liquidity_score
            1.0 if 'pinnacle' in bookie else 0.0,  # is_pinnacle
            1.0 if market == 'home' else 0.0,
            1.0 if market == 'draw' else 0.0,
            1.0 if market == 'away' else 0.0,
            1.0 if 'over' in market else 0.0,
            1.0 if 'under' in market else 0.0,
        ]
        X_list.append(features)
        y_list.append(1.0 if bet.get('won') else 0.0)

    X = np.array(X_list)
    y = np.array(y_list)

    # Standardize features
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_std[X_std < 1e-8] = 1.0
    X_scaled = (X - X_mean) / X_std

    # Logistic Regression via Newton-Raphson (simplified gradient descent)
    n, d = X_scaled.shape
    w = np.zeros(d)
    lr = 0.1
    for _ in range(200):
        z = X_scaled @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -10, 10)))
        grad = X_scaled.T @ (p - y) / n
        w -= lr * grad

    # Pseudo-R² (McFadden)
    log_lik_full = np.sum(y * np.log(np.clip(p, 1e-10, 1.0)) + (1 - y) * np.log(np.clip(1 - p, 1e-10, 1.0)))
    p_null = np.mean(y)
    log_lik_null = np.sum(y * np.log(p_null) + (1 - y) * np.log(1 - p_null))
    pseudo_r2 = 1.0 - (log_lik_full / log_lik_null) if log_lik_null != 0 else 0.0

    model_data = {
        'trained': True,
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'n_samples': len(all_bets),
        'n_winners': int(sum(y)),
        'win_rate_baseline': round(float(np.mean(y)) * 100, 1),
        'feature_names': feature_names,
        'coefficients': [round(float(c), 6) for c in w.tolist()],
        'X_mean': [round(float(m), 4) for m in X_mean.tolist()],
        'X_std': [round(float(s), 4) for s in X_std.tolist()],
        'pseudo_r2': round(float(pseudo_r2), 4),
        'note': 'Logistic regression coefficients. P(success) = sigmoid(sum(coef_i * (x_i - mean_i) / std_i)).',
    }

    try:
        with open(SM_ML_MODEL_FILE, 'w', encoding='utf-8') as f:
            json.dump(model_data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return model_data


def predict_steam_success_probability(drop_pct: float, league_identifier: str,
                                      bookmaker: str, market: str,
                                      velocity: float = 0.0,
                                      acceleration_ratio: float = 1.0) -> dict:
    """
    Prediz a probabilidade de um steam move ser lucrativo usando o modelo ML treinado.

    Retorna dict com:
      - success_prob: probabilidade estimada (0-100)
      - confidence: 'Alta', 'Média', 'Baixa' baseado na probabilidade
      - model_available: bool indicando se o modelo estava disponível
    """
    if not os.path.exists(SM_ML_MODEL_FILE):
        return {
            'success_prob': 50.0,
            'confidence': 'Média',
            'model_available': False,
            'note': 'Modelo não treinado. Use train_steam_success_model().',
        }

    try:
        with open(SM_ML_MODEL_FILE, 'r', encoding='utf-8') as f:
            model = json.load(f)
    except Exception:
        return {'success_prob': 50.0, 'confidence': 'Média', 'model_available': False}

    if not model.get('trained'):
        return {'success_prob': 50.0, 'confidence': 'Média', 'model_available': False}

    tier_name, weight = estimate_liquidity_tier(league_identifier)
    bookie_lower = bookmaker.lower()
    market_lower = market.lower()

    # Build feature vector (same order as training)
    features = np.array([
        drop_pct,
        weight,
        1.0 if 'pinnacle' in bookie_lower else 0.0,
        1.0 if market_lower == 'home' else 0.0,
        1.0 if market_lower == 'draw' else 0.0,
        1.0 if market_lower == 'away' else 0.0,
        1.0 if 'over' in market_lower else 0.0,
        1.0 if 'under' in market_lower else 0.0,
    ])

    X_mean = np.array(model['X_mean'])
    X_std = np.array(model['X_std'])
    X_std[X_std < 1e-8] = 1.0
    features_scaled = (features - X_mean) / X_std

    w = np.array(model['coefficients'])
    z = np.dot(features_scaled, w)
    prob = 1.0 / (1.0 + np.exp(-np.clip(z, -10, 10)))

    prob_pct = round(float(prob) * 100, 1)

    if prob_pct >= 60:
        conf = 'Alta'
    elif prob_pct >= 45:
        conf = 'Média'
    else:
        conf = 'Baixa'

    return {
        'success_prob': prob_pct,
        'confidence': conf,
        'model_available': True,
        'model_n_samples': model.get('n_samples', 0),
        'model_pseudo_r2': model.get('pseudo_r2', 0),
    }


# ─────────────────────────────────────────────
#  KELLY STAKING INTEGRATION (CLV-weighted)
# ─────────────────────────────────────────────

def calculate_clv_weighted_kelly(
    league_code: str, market: str, current_odd: float,
    model_prob: float = None, bankroll: float = 1000.0,
    kelly_fraction: float = 0.25, max_stake_pct: float = 5.0
) -> dict:
    """
    Calcula o stake ótimo usando Kelly Criterion ajustado pelo CLV histórico
    do nicho (liga|mercado).

    Estratégia:
    1. Se temos model_prob, usa Kelly completo: f* = (p*odds - 1)/(odds - 1)
    2. Se não temos model_prob, estima edge implícito do CLV histórico
    3. Ajusta f* pelo CLV track record:
       - CLV positivo consistente (>60% das vezes) → f* × 1.2 (confiança extra)
       - CLV negativo consistente (<40% das vezes) → f* × 0.5 (reduz exposição)
       - Sem dados de CLV → f* × 0.75 (conservador por padrão)
    4. Aplica fractional Kelly (default: quarter Kelly)
    5. Impõe cap de exposição máxima (default: 5% da banca)

    Args:
        league_code: código da liga (ex: 'E0', 'BRA')
        market: mercado (ex: 'home', 'over25')
        current_odd: odd atual da aposta
        model_prob: probabilidade estimada pelo modelo (opcional)
        bankroll: banca atual
        kelly_fraction: fração de Kelly (0.25 = quarter Kelly)
        max_stake_pct: % máxima da banca por aposta

    Returns:
        dict com:
          - stake_value: valor absoluto da aposta
          - stake_pct: % da banca
          - full_kelly_pct: Kelly não-fracionado (%)
          - edge_estimated: edge estimado (%)
          - clv_adjustment: fator de ajuste CLV
    """
    clv_data = load_clv_data()

    # ── Collect CLV stats for this niche ─────────────────────────────
    clv_values = []
    for clv_id, entry in clv_data.items():
        if not entry.get('resolved'):
            continue
        if entry.get('league_code') != league_code:
            continue
        if entry.get('market') != market:
            continue
        det = entry.get('detection_odd', 0)
        cls = entry.get('closing_odd', 0)
        if det > 1.0 and cls > 1.0:
            clv_pct = ((det / cls) - 1.0) * 100.0
            clv_values.append(clv_pct)

    # ── Determine CLV adjustment factor ──────────────────────────────
    if len(clv_values) >= 5:
        positive_pct = sum(1 for v in clv_values if v > 0) / len(clv_values)
        mean_clv = np.mean(clv_values)

        if positive_pct >= 0.65 and mean_clv > 1.0:
            clv_adj = 1.2   # Strong CLV → can be more aggressive
        elif positive_pct < 0.35 or mean_clv < -1.0:
            clv_adj = 0.5   # Negative CLV → reduce exposure significantly
        else:
            clv_adj = 0.85  # Mixed CLV → slightly conservative
    else:
        clv_adj = 0.75  # No CLV data → conservative default
        mean_clv = 0.0
        positive_pct = 0.5

    # ── Estimate edge ──────────────────────────────────────────────
    if model_prob is not None and model_prob > 0:
        # Full Kelly: f* = (p*b - q) / b = (p*odds - 1) / (odds - 1)
        edge = model_prob * current_odd - 1.0
        if edge > 0:
            full_kelly = edge / (current_odd - 1.0)
        else:
            full_kelly = 0.0
    elif len(clv_values) >= 5 and mean_clv > 0:
        # Estimate edge from CLV: if we consistently beat closing by X%,
        # our edge is approximately X% (simplified)
        edge = mean_clv / 100.0
        full_kelly = edge / (current_odd - 1.0) if current_odd > 1.0 else 0.0
    else:
        edge = 0.0
        full_kelly = 0.0

    # ── Apply adjustments ───────────────────────────────────────────
    adjusted_kelly = full_kelly * kelly_fraction * clv_adj
    adjusted_kelly = max(0.0, min(adjusted_kelly, max_stake_pct / 100.0))

    stake_value = round(adjusted_kelly * bankroll, 2)
    stake_pct = round(adjusted_kelly * 100, 2)

    return {
        'stake_value': stake_value,
        'stake_pct': stake_pct,
        'full_kelly_pct': round(full_kelly * 100, 2),
        'edge_estimated': round(edge * 100, 2),
        'clv_adjustment': clv_adj,
        'clv_mean': round(float(mean_clv), 2) if clv_values else 0.0,
        'clv_positive_pct': round(positive_pct * 100, 1) if clv_values else 50.0,
        'clv_n': len(clv_values),
        'kelly_fraction_used': kelly_fraction,
    }


class SmartMoneyBacktester:
    def __init__(self, data_loader_fn=None):
        self.data_loader_fn = data_loader_fn
        # O history_file aponta para a pasta data/ na raiz do projeto
        self.history_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'data', 'live_steam_moves_history.json'
        )

    def _load_history_alerts(self):
        """Carrega alertas do arquivo JSON de histórico ao vivo."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _load_league_df(self, league_code: str, start_date: str) -> pd.DataFrame:
        """Carrega dados históricos de uma liga via data_loader_fn ou retorna DataFrame vazio."""
        if self.data_loader_fn is None:
            return pd.DataFrame()
        try:
            return self.data_loader_fn(league_code, start_date=start_date)
        except Exception:
            return pd.DataFrame()

    def scan_steam_moves(
        self,
        league_code=None,
        min_drop_pct=5.0,
        markets=None,
        start_date='2021-01-01',
        end_date='2026-12-31',
        stake_value=10,
        profile_filter='all',  # 'all', 'sharps', 'squares'
        latency_seconds=0,
        detection_mode='model_edge'  # 'model_edge' | 'temporal_drop'
    ):
        """
        Varre oportunidades em dois modos complementares:

        1. HISTÓRICO CSV (model_edge - default):
           Detecta VALUE BETS comparando fair value do modelo Poisson/Dixon-Coles
           contra odds Bet365 dos CSVs. NÃO são steam moves reais — são oportunidades
           de valor segundo o modelo. Útil para identificar nichos lucrativos de
           forma independente de movimento de mercado.

           detection_type = "model_edge"

        2. HISTÓRICO CSV (temporal_drop):
           Detecta quedas REAIS de odds comparando abertura vs fechamento da Pinnacle
           (colunas PSH→PSCH, PSD→PSCD, PSA→PSCA dos CSVs football-data.co.uk).
           Se as colunas não existirem, retorna lista vazia.

           detection_type = "odds_movement"

        3. LIVE JSON:
           Usa alertas coletados em tempo real pelo live_odds_tracker —
           estes SÃO steam moves reais (detection_type = "odds_movement").
        """
        if markets is None:
            markets = ['home', 'away', 'draw']

        all_league_objs = get_all_available_leagues()
        default_leagues = [l['code'] for l in all_league_objs]
        leagues_to_scan = [league_code] if league_code else default_leagues

        # ── MODO 1: Histórico CSV ──────────────────────────────────────────
        csv_alerts = []
        for lcode in leagues_to_scan:
            df = self._load_league_df(lcode, start_date=start_date)
            if df is not None and not df.empty:
                moves = _extract_steam_moves_from_df(
                    df=df,
                    league_code=lcode,
                    markets=markets,
                    min_drop_pct=min_drop_pct,
                    stake_value=stake_value,
                    start_date=start_date,
                    end_date=end_date,
                    latency_seconds=latency_seconds,
                    detection_mode=detection_mode
                )
                csv_alerts.extend(moves)

        # ── MODO 2: Live JSON ──────────────────────────────────────────────
        live_alerts = self._load_history_alerts()

        # Combinar ambas as fontes
        all_alerts = csv_alerts + live_alerts

        # ── AGRUPAR POR NICHO ──────────────────────────────────────────────
        niche_groups: dict = {}

        # Pré-popular nichos para garantir exibição mesmo sem dados
        for lcode in leagues_to_scan:
            for mkt in markets:
                niche_key = f"{lcode}|{mkt}"
                niche_groups[niche_key] = []

        for alert in all_alerts:
            lcode = alert.get('league_code', '')
            mkt = str(alert.get('market', '')).lower()
            if not lcode or not mkt:
                continue

            # Aplicar simulação de latência na odd executada e lucro para alertas da Live
            current_odd = alert.get('current_odd', 1.0)
            opening_odd = alert.get('opening_odd', current_odd)
            won = alert.get('won')
            
            executed_odd = current_odd
            if latency_seconds > 0 and won is not None:
                import math
                sf = 1.0 - math.exp(-0.005 * latency_seconds)
                if opening_odd > current_odd:
                    executed_odd = max(1.01, current_odd - (opening_odd - current_odd) * sf)
                
                stake = alert.get('stake_value', stake_value)
                alert['executed_odd'] = round(executed_odd, 3)
                alert['profit'] = round((executed_odd - 1.0) * stake if won else -stake, 2)
            else:
                alert['executed_odd'] = round(executed_odd, 3)
                if won is not None:
                    stake = alert.get('stake_value', stake_value)
                    alert['profit'] = round((current_odd - 1.0) * stake if won else -stake, 2)

            # Fallback para alertas sem perfil (por exemplo, antigos salvos na live)
            if 'profile_type' not in alert:
                drop_pct = alert.get('drop_pct', 0.0)
                commence_time_str = alert.get('date', '')
                bookie = alert.get('bookmaker', 'Bet365')
                sh_score, p_type = classify_drop_profile(
                    drop_pct=drop_pct,
                    league_identifier=lcode,
                    commence_time_str=commence_time_str,
                    bookmaker_name=bookie,
                    match_entry=None,
                    comp_key=None
                )
                alert['sharpness_score'] = sh_score
                alert['profile_type'] = p_type
            # Fallback para detection_type (alertas antigos e live)
            if 'detection_type' not in alert:
                source = alert.get('source', '')
                alert['detection_type'] = 'odds_movement' if source == 'live' else 'model_edge'

            # Filtrar por perfil do drop
            prof = alert.get('profile_type', 'Squares')
            if profile_filter == 'sharps' and prof != 'Sharps':
                continue
            if profile_filter == 'squares' and prof != 'Squares':
                continue

            # Filtrar por data
            alert_date_str = alert.get('date', '')
            try:
                alert_dt = pd.to_datetime(alert_date_str, errors='coerce')
                if pd.notna(alert_dt):
                    if alert_dt < pd.to_datetime(start_date) or alert_dt > pd.to_datetime(end_date):
                        continue
            except Exception:
                pass

            # Filtrar por liga
            if league_code and lcode != league_code:
                continue

            if mkt not in markets:
                continue

            if alert.get('drop_pct', 0.0) < min_drop_pct:
                continue

            niche_key = f"{lcode}|{mkt}"
            if niche_key not in niche_groups:
                niche_groups[niche_key] = []
            niche_groups[niche_key].append(alert)

        # ── CALCULAR MÉTRICAS POR NICHO ────────────────────────────────────
        results = []
        for niche_key, bets in niche_groups.items():
            lcode, mkt = niche_key.split('|')
            tier_name, _ = estimate_liquidity_tier(lcode)

            if not bets:
                score, confidence_level, tier_name = calculate_confidence_score(0.0, lcode)
                results.append({
                    'code': niche_key,
                    'market_name': mkt.capitalize(),
                    'total_bets': 0,
                    'net_profit': 0.0,
                    'roi': 0.0,
                    'avg_drop': 0.0,
                    'win_rate': 0.0,
                    'liquidity_tier': tier_name,
                    'confidence_score': score,
                    'confidence_level': confidence_level,
                    'resolved_count': 0,
                    'source_csv': 0,
                    'source_live': 0,
                    'n_model_edge': 0,
                    'n_odds_movement': 0,
                    'mean_clv_pct': 0.0,
                    'clv_positive_pct': 0.0,
                    'clv_count': 0,
                    'p_value': 1.0,
                    'p_value_fdr': 1.0,
                    'significant_at_10pct': False,
                })
                continue

            total_bets = len(bets)
            resolved_bets = [b for b in bets if b.get('resolved') is True]
            resolved_count = len(resolved_bets)

            net_profit = sum(b.get('profit', 0.0) for b in resolved_bets)
            total_staked = sum(b.get('stake_value', stake_value) for b in resolved_bets)
            roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0

            avg_drop = float(np.mean([b.get('drop_pct', 0.0) for b in bets]))

            wins = sum(1 for b in resolved_bets if b.get('won') is True)
            win_rate = (wins / resolved_count * 100) if resolved_count > 0 else 0.0

            # Confiança baseada no drop médio ponderado pelo número de alertas
            score, confidence_level, tier_name = calculate_confidence_score(avg_drop, lcode)

            # Contar fontes
            source_csv = sum(1 for b in bets if b.get('source') == 'historical_csv')
            source_live = sum(1 for b in bets if b.get('source') != 'historical_csv')

            # Contar detection types
            n_model_edge = sum(1 for b in bets if b.get('detection_type') == 'model_edge')
            n_odds_movement = sum(1 for b in bets if b.get('detection_type') == 'odds_movement')

            # CLV metrics for this niche
            clv = calculate_clv_metrics(bets) if n_odds_movement > 0 else {
                'mean_clv_pct': 0.0, 'clv_positive_pct': 0.0, 'clv_count': 0
            }

            results.append({
                'code': niche_key,
                'market_name': mkt.capitalize(),
                'total_bets': total_bets,
                'net_profit': round(net_profit, 2),
                'roi': round(roi, 2),
                'avg_drop': round(avg_drop, 2),
                'win_rate': round(win_rate, 1),
                'liquidity_tier': tier_name,
                'confidence_score': score,
                'confidence_level': confidence_level,
                'resolved_count': resolved_count,
                'source_csv': source_csv,
                'source_live': source_live,
                'n_model_edge': n_model_edge,
                'n_odds_movement': n_odds_movement,
                'mean_clv_pct': clv['mean_clv_pct'],
                'clv_positive_pct': clv['clv_positive_pct'],
                'clv_count': clv['clv_count'],
            })

        # ── FDR Correction (Benjamini-Hochberg) ─────────────────────────
        # Apply multiple comparison correction to p-values across niches
        # to control false discovery rate at q=0.10
        from scipy import stats as scipy_stats

        niche_pvalues = []
        for r in results:
            resolved_n = r.get('resolved_count', 0)
            wins_n = int(round(r['win_rate'] / 100.0 * resolved_n)) if resolved_n > 0 else 0
            # One-sided binomial test: H0: win_rate <= break_even (1/avg_odds)
            # break_even estimate from avg_drop: avg_odd ≈ 1/(1 - avg_drop/100)
            avg_odd = 1.0 / max(0.01, 1.0 - (r.get('avg_drop', 0) / 100.0))
            break_even = 1.0 / avg_odd
            if resolved_n >= 5 and wins_n > 0:
                p_val = scipy_stats.binomtest(wins_n, n=resolved_n, p=break_even, alternative='greater').pvalue
            else:
                p_val = 1.0
            niche_pvalues.append(p_val)

        # Apply FDR correction
        try:
            from .ai_predictor import apply_fdr_correction
            adjusted_pvals = apply_fdr_correction(niche_pvalues)
        except ImportError:
            adjusted_pvals = niche_pvalues  # Fallback: no correction

        for i, r in enumerate(results):
            r['p_value'] = round(niche_pvalues[i], 4)
            r['p_value_fdr'] = round(adjusted_pvals[i], 4)
            r['significant_at_10pct'] = adjusted_pvals[i] < 0.10

        return results


def calculate_odds_metrics(updates: list):
    """
    Calcula velocidade (queda % por hora) e aceleração de uma série de atualizações de cotações.

    Usa regressão linear nas últimas N atualizações (padrão: 6) para estimar velocidade
    recente de forma robusta, em vez de usar apenas os 2 últimos pontos (que é ruidoso).

    Cada update em 'updates' deve ser um dicionário contendo 'timestamp' (ISO 8601) e 'price' (float).

    Retorna um dicionário com:
        - velocity_global: float (%/h total via regressão em todos os pontos)
        - velocity_recent: float (%/h nas últimas N atualizações via regressão)
        - acceleration_ratio: float (recent / global)
        - acceleration_text: str ("Aceleração Forte", "Acelerando", "Desacelerando", "Constante")
        - drop_total_pct: float (% drop total)
        - r_squared_recent: float (R² da regressão recente — qualidade do ajuste)
        - r_squared_global: float (R² da regressão global — qualidade do ajuste)
    """
    if not updates or len(updates) < 2:
        return {
            "velocity_global": 0.0,
            "velocity_recent": 0.0,
            "acceleration_ratio": 1.0,
            "acceleration_text": "Constante",
            "drop_total_pct": 0.0,
            "r_squared_recent": 0.0,
            "r_squared_global": 0.0,
        }

    def parse_dt(ts):
        if not ts:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except Exception:
            return datetime.now(timezone.utc)

    def _linear_velocity(subset: list):
        """
        Calcula velocidade (%/h) via regressão linear de log(price) vs horas.
        Retorna (velocity_pct_per_hour, r_squared).
        """
        if len(subset) < 2:
            return 0.0, 0.0

        times = [parse_dt(u.get('timestamp')).timestamp() / 3600.0 for u in subset]
        prices = [float(u.get('price', 1.0)) for u in subset]

        # Regressão linear: price ~ time
        x = np.array(times)
        y = np.array(prices)
        x_mean, y_mean = np.mean(x), np.mean(y)

        num = np.sum((x - x_mean) * (y - y_mean))
        den = np.sum((x - x_mean) ** 2)

        if abs(den) < 1e-10 or y_mean <= 0:
            return 0.0, 0.0

        slope = num / den
        # velocity em %/h: (delta_price / price_mean) / delta_hour * 100
        # slope está em odds/hora; %/hora = slope / y_mean * 100
        vel = abs((slope / y_mean) * 100.0)

        # R²
        y_pred = slope * (x - x_mean) + y_mean
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y_mean) ** 2)
        r_sq = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-10 else 0.0

        return round(vel, 2), round(max(0.0, min(1.0, r_sq)), 3)

    # Ordenar por timestamp
    sorted_updates = sorted(updates, key=lambda x: x.get('timestamp', ''))

    # Drop total
    p0 = float(sorted_updates[0].get('price', 1.0))
    p_last = float(sorted_updates[-1].get('price', 1.0))
    drop_total = max(0.0, ((p0 / p_last) - 1.0) * 100.0) if p0 > 0 and p_last > 0 else 0.0

    # Velocidade global via regressão em todos os pontos
    vel_global, r_sq_global = _linear_velocity(sorted_updates)

    # Velocidade recente via regressão nas últimas 6 atualizações
    N_RECENT = min(6, len(sorted_updates))
    recent_window = sorted_updates[-N_RECENT:]
    vel_recent, r_sq_recent = _linear_velocity(recent_window)

    # Fallback: se regressão falhar por falta de variação, usa método antigo
    if vel_global < 0.01 and len(sorted_updates) >= 2:
        t0_dt = parse_dt(sorted_updates[0].get('timestamp'))
        t_last_dt = parse_dt(sorted_updates[-1].get('timestamp'))
        dur = max(0.016, (t_last_dt - t0_dt).total_seconds() / 3600.0)
        vel_global = drop_total / dur

    if vel_recent < 0.01 and len(recent_window) >= 2:
        t_prev_dt = parse_dt(recent_window[0].get('timestamp'))
        t_last_dt2 = parse_dt(recent_window[-1].get('timestamp'))
        dur_r = max(0.016, (t_last_dt2 - t_prev_dt).total_seconds() / 3600.0)
        p_first_recent = float(recent_window[0].get('price', 1.0))
        p_last_recent = float(recent_window[-1].get('price', 1.0))
        drop_recent_raw = max(0.0, ((p_first_recent / p_last_recent) - 1.0) * 100.0) if p_first_recent > 0 else 0.0
        vel_recent = drop_recent_raw / dur_r

    # Aceleração
    if vel_global > 0.1:
        acc_ratio = vel_recent / vel_global
    else:
        acc_ratio = 1.0

    # Texto de classificação
    if acc_ratio >= 2.0 and vel_recent >= 8.0:
        acc_text = "Aceleração Forte"
    elif acc_ratio >= 1.3 and vel_recent >= 4.0:
        acc_text = "Acelerando"
    elif acc_ratio <= 0.7:
        acc_text = "Desacelerando"
    else:
        acc_text = "Constante"

    return {
        "velocity_global": round(float(vel_global), 2),
        "velocity_recent": round(float(vel_recent), 2),
        "acceleration_ratio": round(float(acc_ratio), 2),
        "acceleration_text": acc_text,
        "drop_total_pct": round(drop_total, 2),
        "r_squared_recent": float(r_sq_recent),
        "r_squared_global": float(r_sq_global),
    }


def calculate_time_decay_adjusted_drop(norm_market: str, opening: float, current: float, elapsed_minutes: float):
    """
    Calcula a odd esperada pelo decaimento natural de tempo em partidas In-Play
    usando modelo exponencial (survival curve) e retorna (odd_decay, adjusted_drop_pct).

    Modelo: decay_ratio = exp(-k * elapsed_minutes / 90)
    onde k varia por tipo de mercado:

    - Under 2.5: k=3.5 (acelera fortemente perto do fim — probabilidade de Under
      sobe exponencialmente quando faltam poucos minutos)
    - Under 1.5: k=2.5 (menos sensível)
    - Under 3.5: k=4.0 (muito sensível — cada minuto sem gol é crítico)
    - Over: k=0 (odds de Over SOBEM com o tempo, não caem — sem decaimento)
    - Draw: k=2.8 (o draw fica mais provável conforme o 0x0 persiste)
    - Home/Away: k=1.4 (decaimento moderado, resultado ainda incerto)

    Vantagens sobre o modelo linear anterior:
    - Decaimento mais lento nos primeiros minutos (exponencial é mais plano que linear perto de 0)
    - Aceleração natural nos minutos finais (exponencial cai mais rápido que linear no final)
    - Baseado em princípios de processos de Poisson com taxa constante
    """
    import math
    if elapsed_minutes <= 0:
        return opening, max(0.0, ((opening / current) - 1.0) * 100.0)

    m_lower = str(norm_market).lower().strip()
    t_frac = elapsed_minutes / 90.0  # Fração do jogo decorrida

    # Constante de decaimento exponencial por tipo de mercado
    # Valores calibrados para refletir a dinâmica real de odds in-play:
    # - Under: odds caem cada vez mais rápido conforme o tempo passa sem gols
    # - Over: odds SOBEM com o tempo (k=0 → sem decaimento)
    # - Draw: acelera após o intervalo sem gols
    if 'under' in m_lower:
        if '2.5' in m_lower or '25' in m_lower:
            k = 3.5
        elif '1.5' in m_lower or '15' in m_lower:
            k = 2.5
        elif '3.5' in m_lower or '35' in m_lower:
            k = 4.0
        elif '4.5' in m_lower or '45' in m_lower:
            k = 4.5
        elif '5.5' in m_lower or '55' in m_lower:
            k = 5.0
        else:
            k = 3.5  # default: assume Under 2.5
        decay_ratio = math.exp(-k * t_frac)
    elif 'draw' in m_lower or 'empate' in m_lower:
        k = 2.8
        decay_ratio = math.exp(-k * t_frac)
    elif 'over' in m_lower:
        # Over: odds SOBEM com o tempo (sem gols → menos chance de over)
        # Se a odd caiu, é um sinal ainda mais forte (totalmente anômalo)
        # Não aplicamos decaimento — drop nominal é 100% real
        odd_decay = opening
        adjusted_drop = ((opening / current) - 1.0) * 100.0 if current < opening else 0.0
        return round(odd_decay, 3), round(adjusted_drop, 2)
    elif 'home' in m_lower or 'away' in m_lower or 'dnb' in m_lower:
        k = 1.4
        decay_ratio = math.exp(-k * t_frac)
    elif 'btts' in m_lower:
        k = 2.0
        decay_ratio = math.exp(-k * t_frac)
    else:
        # Mercado desconhecido — sem decaimento
        odd_decay = opening
        adjusted_drop = ((opening / current) - 1.0) * 100.0 if current < opening else 0.0
        return round(odd_decay, 3), round(adjusted_drop, 2)

    # Odd teórica considerando decaimento natural
    odd_decay = 1.0 + (opening - 1.0) * decay_ratio
    odd_decay = max(1.01, min(opening, odd_decay))

    # Drop ajustado: só conta o que excede o decaimento natural
    if current < odd_decay:
        adjusted_drop = ((odd_decay / current) - 1.0) * 100.0
    else:
        adjusted_drop = 0.0

    return round(odd_decay, 3), round(adjusted_drop, 2)
