"""
Dutching Core — Shared functions reused by all scanner modules.

Extracted from the monolithic backend/dutching_scanner.py (~1900 lines → this file ~900 lines).
All functions here are PURE: they don't call external APIs or depend on global state.

Modules A (scanner_odds_api.py) and B (scanner_oddspapi.py) both import from here.
"""

import os
import math
import logging
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
from scipy.special import expit

logger = logging.getLogger(__name__)

# Fuso horário de Brasília para exibição correta das datas dos jogos
BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")

from backend.models import estimate_bookmaker_odds
from backend.data_loader import load_league_data, auto_detect_data_source, DATA_DIR

# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

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
    'under':    ['0-0', '1-0', '0-1', '2-0', '0-2', '1-1'],
    'over':     ['2-1', '1-2', '3-0', '0-3', '3-1', '1-3', '2-2',
                 '3-2', '2-3', '4-0', '0-4', '4-1', '1-4', '3-3'],
}

# ── League-average goals for z-score calibration ──────────────────
LEAGUE_AVG_GOALS = {
    # High-scoring leagues (3.0+)
    'N1': 3.15, 'D1': 3.10, 'D2': 2.85,
    # Medium-high
    'E0': 2.85, 'E1': 2.60, 'E2': 2.55, 'E3': 2.55,
    'I1': 2.75, 'I2': 2.45,
    'SP1': 2.60, 'SP2': 2.35,
    'F1': 2.70, 'F2': 2.45,
    'TUR': 2.65, 'BEL': 2.75, 'SWISS': 2.85, 'AUT': 2.80,
    'MLS': 2.80, 'J1': 2.55, 'J2': 2.50,
    # Medium
    'BRAZIL_SERIE_A': 2.45, 'BRAZIL_SERIE_B': 2.30, 'BRAZIL_SERIE_C': 2.20,
    'ARG': 2.35, 'ARGENTINA_PRIMERA_DIVISION': 2.35,
    # Lower
    'RUSSIA': 2.35, 'UKRAINE': 2.40, 'CHINA': 2.55, 'KOR': 2.30,
    'GRE': 2.40, 'POR': 2.55,
}
LEAGUE_AVG_GOALS_DEFAULT = 2.55
LEAGUE_STD_GOALS = 1.25

STRATEGY_LABELS = {
    'dynamic': 'Dinamico (Top Probabilidades)',
    'home_fav': 'Favorito Mandante',
    'away_fav': 'Favorito Visitante',
    'draw': 'Empate',
    'under': 'Under / Jogo Truncado',
    'over': 'Over / Goleada',
}

PROFILE_LABELS = {
    'under': 'Under / Jogo Truncado',
    'over': 'Over / Goleada',
    'draw': 'Empate',
    'home_fav': 'Favorito Mandante',
    'away_fav': 'Favorito Visitante',
    'dynamic': 'Dinamico (Top Probabilidades)',
}

QUALITY_VERDICTS = {
    'STRONG_BET':  {'min': 70, 'label': 'FORTE: Apostar',       'color': '#34d399', 'icon': '🟢'},
    'BET':         {'min': 55, 'label': 'OK: Apostar',          'color': '#f59e0b', 'icon': '🟡'},
    'CAUTION':     {'min': 40, 'label': 'Cautela: Avaliar',     'color': '#f97316', 'icon': '🟠'},
    'SKIP':        {'min': 0,  'label': 'Pular: Não Apostar',   'color': '#f87171', 'icon': '🔴'},
}


# ═══════════════════════════════════════════════════════════════════════
# League Helpers
# ═══════════════════════════════════════════════════════════════════════

def _get_league_avg_goals(league_code=None):
    if league_code and league_code in LEAGUE_AVG_GOALS:
        return LEAGUE_AVG_GOALS[league_code]
    return LEAGUE_AVG_GOALS_DEFAULT


def _guess_league_from_teams(home_team, away_team):
    """Best-effort: mapeia times para um codigo de liga com dados historicos.
    Retorna None se nao conseguir identificar (jogo sera ignorado)."""
    cache = _get_team_league_cache()

    h = (home_team or '').lower().strip()
    a = (away_team or '').lower().strip()
    if h in cache:
        return cache[h]
    if a in cache:
        return cache[a]
    for team_name, lc in cache.items():
        if h and (h in team_name or team_name in h):
            return lc
        if a and (a in team_name or team_name in a):
            return lc
    return None


# Module-level cache for team→league mapping
_TEAM_LEAGUE_CACHE = None

def _get_team_league_cache():
    """Lazy-build and return the team→league cache."""
    global _TEAM_LEAGUE_CACHE
    if _TEAM_LEAGUE_CACHE is not None:
        return _TEAM_LEAGUE_CACHE

    from backend.data_loader import load_league_data, auto_detect_data_source
    cache = {}
    priority_leagues = ['BRA', 'BRAZIL_SERIE_B', 'E0', 'SP1', 'I1', 'D1', 'F1',
                        'E1', 'SP2', 'I2', 'N1', 'P1', 'ARG']
    for lc in priority_leagues:
        try:
            df = load_league_data(lc, start_date='2023-01-01', data_source=auto_detect_data_source(lc))
            if df is not None and not df.empty:
                teams = set(df['HomeTeam'].dropna().unique()) | set(df['AwayTeam'].dropna().unique())
                for t in teams:
                    cache[str(t).lower().strip()] = lc
        except Exception:
            continue
    _TEAM_LEAGUE_CACHE = cache
    return cache


# ═══════════════════════════════════════════════════════════════════════
# Lambda from Under 2.5
# ═══════════════════════════════════════════════════════════════════════

def _solve_lambda_from_under25_fast(prob_under):
    """Quick approximate lambda from under 2.5 probability via bisection."""
    if prob_under <= 0.01: return 6.0
    if prob_under >= 0.99: return 0.1
    lo, hi = 0.05, 10.0
    for _ in range(10):
        mid = (lo + hi) / 2.0
        p = math.exp(-mid) * (1.0 + mid + (mid ** 2) / 2.0)
        if p > prob_under: lo = mid
        else: hi = mid
    return (lo + hi) / 2.0 * 1.12  # NB2 correction


# ═══════════════════════════════════════════════════════════════════════
# Game Profile Classification (Melhoria #2)
# ═══════════════════════════════════════════════════════════════════════

def classify_game_profile(pred, is_home_fav, market_ou_odds=None, league_code=None):
    """Classify game profile using fuzzy membership scores (sigmoid transitions).

    Returns a dict with scores per profile, best_profile, confidence, and metadata.
    Each score is in [0, 1] representing membership strength.

    Uses: lambda z-score (league-calibrated), model-vs-market divergence,
    draw probability, and home/away dominance ratio.
    """
    lambda_home = pred.get('lambda_home', 1.2)
    lambda_away = pred.get('lambda_away', 1.0)
    lambda_total = lambda_home + lambda_away
    prob_under25 = pred.get('prob_under_25', 0.5)
    prob_draw = pred.get('prob_d', 0.26)
    prob_h = pred.get('prob_h', 0.37)
    prob_a = pred.get('prob_a', 0.37)

    # League-calibrated z-score
    league_avg = _get_league_avg_goals(league_code)
    lambda_z = (lambda_total - league_avg) / LEAGUE_STD_GOALS

    # Model-vs-market divergence
    market_divergence = 0.0
    if market_ou_odds:
        over_odd, under_odd = market_ou_odds
        if over_odd > 1.01 and under_odd > 1.01:
            imp_over = 1.0 / over_odd
            imp_under = 1.0 / under_odd
            fair_under = imp_under / (imp_over + imp_under)
            if 0.01 < fair_under < 0.99:
                mkt_lambda = _solve_lambda_from_under25_fast(fair_under)
                if mkt_lambda > 0:
                    market_divergence = lambda_total - mkt_lambda

    # Dominance and balance
    lambda_ratio = lambda_home / max(lambda_away, 0.1)
    dominance = (lambda_home - lambda_away) / max(lambda_total, 1.0)

    # ── Fuzzy profile scores ──────────────────────────────────────
    under_score = expit(-(lambda_z + 0.3) * 3.0)
    if market_divergence < -0.1:
        under_score = min(1.0, under_score * 1.3)

    over_score = expit((lambda_z - 0.3) * 3.0)
    if market_divergence > 0.1:
        over_score = min(1.0, over_score * 1.3)

    draw_strength = max(0.0, min(1.0, (prob_draw - 0.24) / 0.10))
    balance_factor = 1.0 - min(1.0, abs(dominance))
    draw_score = max(0.0, min(1.0, draw_strength * 0.7 + balance_factor * 0.3))

    home_fav_score = expit((lambda_ratio - 1.5) * 2.5) * min(1.0, prob_h / 0.40)
    away_ratio = lambda_away / max(lambda_home, 0.1)
    away_fav_score = expit((away_ratio - 1.5) * 2.5) * min(1.0, prob_a / 0.40)

    max_specific = max(under_score, over_score, draw_score, home_fav_score, away_fav_score)
    dynamic_score = 1.0 - max_specific

    scores = {
        'under': round(under_score, 4),
        'over': round(over_score, 4),
        'draw': round(draw_score, 4),
        'home_fav': round(home_fav_score, 4),
        'away_fav': round(away_fav_score, 4),
        'dynamic': round(dynamic_score, 4),
    }

    best = max(scores, key=scores.get)
    best_score = scores[best]
    sorted_scores = sorted(scores.values(), reverse=True)
    confidence = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else 0.0

    return {
        'scores': scores,
        'best_profile': best,
        'confidence': round(confidence, 4),
        'profile_label': PROFILE_LABELS.get(best, best),
        'lambda_z': round(lambda_z, 3),
        'market_divergence': round(market_divergence, 3),
        'lambda_total': round(lambda_total, 2),
        'dominance': round(dominance, 3),
    }


def resolve_strategy(strategy_name, pred, is_home_fav):
    """Resolve strategy for Dutching: if 'auto_ia', pick based on game profile.

    Uses classify_game_profile() internally for fuzzy classification.
    Backward-compatible with callers that expect a single string.
    """
    if strategy_name != 'auto_ia':
        return strategy_name
    profile = classify_game_profile(pred, is_home_fav)
    return profile['best_profile']


# ═══════════════════════════════════════════════════════════════════════
# Directional Dominance Scoring (Melhoria #3)
# ═══════════════════════════════════════════════════════════════════════

def score_dominance_weight(score_str, lambda_home, lambda_away):
    """Directional dominance weight for a score given expected goal ratio.

    Returns [0.10, 2.0] representing how consistent this score is with
    the λ_home/λ_away ratio.
    - Strong match (score aligns with dominance) → ~1.8
    - Neutral → ~1.0
    - Mismatch (score contradicts dominance) → ~0.15
    """
    try:
        hg, ag = map(int, score_str.split('-'))
    except Exception:
        return 1.0
    total = lambda_home + lambda_away
    if total < 0.1 or (hg + ag) == 0:
        return 1.0
    score_home_ratio = hg / (hg + ag)
    expected_ratio = lambda_home / total
    ratio_diff = abs(score_home_ratio - expected_ratio)
    if ratio_diff < 0.10:
        weight = 1.8
    elif ratio_diff < 0.20:
        weight = 1.4
    elif ratio_diff < 0.30:
        weight = 1.0
    elif ratio_diff < 0.45:
        weight = 0.5
    else:
        weight = 0.15
    # Suppress scores with 0 goals on the dominant side
    if expected_ratio > 0.62 and hg == 0 and ag > 0:
        weight *= 0.5
    if expected_ratio < 0.38 and ag == 0 and hg > 0:
        weight *= 0.5
    return max(0.10, min(2.0, weight))


# ═══════════════════════════════════════════════════════════════════════
# Team-Specific NB Dispersion (Melhoria #8)
# ═══════════════════════════════════════════════════════════════════════

def compute_team_dispersions(historical_df, target_date=None):
    """Estimate per-team Negative Binomial overdispersion from history.

    NB2: Var = μ + α·μ² → α = max(0.005, (Var - μ) / μ²) when Var > μ.

    Returns dict: team_name → {alpha_home, alpha_away, n_home_games, n_away_games}
    """
    df = historical_df.copy()
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], format='mixed', dayfirst=True)
        if target_date is not None:
            df = df[df['Date'] < pd.to_datetime(target_date)]

    team_home_goals = defaultdict(list)
    team_away_goals = defaultdict(list)
    for _, row in df.iterrows():
        ht = row.get('HomeTeam', '')
        at = row.get('AwayTeam', '')
        fthg = row.get('FTHG')
        ftag = row.get('FTAG')
        if pd.isna(fthg) or pd.isna(ftag): continue
        team_home_goals[ht].append(float(fthg))
        team_away_goals[at].append(float(ftag))

    MIN_GAMES = 15
    dispersions = {}
    for team in set(list(team_home_goals) + list(team_away_goals)):
        alpha_h = _estimate_team_alpha(team_home_goals.get(team, []), MIN_GAMES)
        alpha_a = _estimate_team_alpha(team_away_goals.get(team, []), MIN_GAMES)
        dispersions[team] = {
            'alpha_home': alpha_h, 'alpha_away': alpha_a,
            'n_home_games': len(team_home_goals.get(team, [])),
            'n_away_games': len(team_away_goals.get(team, [])),
        }
    return dispersions


def _estimate_team_alpha(goals, min_games=15):
    """Estimate NB2 α from goal list. Returns None if insufficient data."""
    if len(goals) < min_games: return None
    arr = np.array(goals, dtype=float)
    mu = arr.mean()
    var = arr.var(ddof=1)
    if var > mu and mu > 0:
        return max(0.005, min(0.35, (var - mu) / (mu ** 2)))
    return 0.01  # under-dispersed → near-Poisson


def get_team_alphas(home_team, away_team, dispersions):
    """Extract home/away alpha overrides from dispersion dict."""
    if not dispersions: return None, None, False
    hd = dispersions.get(home_team, {})
    ad = dispersions.get(away_team, {})
    alpha_h = hd.get('alpha_home') if hd else None
    alpha_a = ad.get('alpha_away') if ad else None
    return alpha_h, alpha_a, (alpha_h is not None and alpha_a is not None)


# ═══════════════════════════════════════════════════════════════════════
# Dutching Builder
# ═══════════════════════════════════════════════════════════════════════

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
    """Build a Dutching combination of correct scores.

    With ESTIMATED odds (derived from O/U 2.5 market), individual EV per score
    is ~constant — the real edge comes from model-vs-market divergence in
    total lambda. Selection uses:

    1. Strategy group → candidate scores (or all 20 for 'dynamic')
    2. Directional dominance weighting: scores consistent with λ_home/λ_away
       get boosted, mismatched scores get suppressed
    3. Composite = prob × dominance_weight → sort descending
    4. Select up to max_legs within max_overround
    5. Trim worst legs while edge < 0

    With REAL CS odds (from API), would filter by individual EV instead.
    """
    lambda_home = pred.get('lambda_home', 1.2)
    lambda_away = pred.get('lambda_away', 1.0)

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

        # Directional dominance weight (new — respects λ ratio)
        dom_weight = score_dominance_weight(score, lambda_home, lambda_away)
        composite = prob * dom_weight

        all_candidates.append({
            'score': score,
            'prob': prob,
            'odd': odd,
            'key': key,
            'ev': prob * odd - 1.0,
            'prob_odd_ratio': prob / (1.0 / odd),
            'dominance_weight': dom_weight,
            'composite': composite,
        })

    if len(all_candidates) < min_selections:
        return None, None, None, None, None, 0, 0, -1

    # Detect real CS odds (EV varies) vs estimated (EV ~constant)
    ev_values = [c['ev'] for c in all_candidates]
    has_real_odds = (max(ev_values) - min(ev_values)) > 0.03 and max(ev_values) > -0.01

    if has_real_odds:
        all_candidates.sort(key=lambda x: (x['ev'] > 0, x['ev']), reverse=True)
    else:
        # Sort by composite (prob × dominance) instead of raw prob
        all_candidates.sort(key=lambda x: x['composite'], reverse=True)

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

    # Trim worst leg while edge < 0
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
    label = STRATEGY_LABELS.get(strategy, strategy)

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


# ═══════════════════════════════════════════════════════════════════════
# Bootstrap Confidence for Dutching Edge (Melhoria #7)
# ═══════════════════════════════════════════════════════════════════════

def bootstrap_dutching_edge(pred, est_odds, strategy='auto_ia',
                            max_legs=8, max_overround=0.92, min_selections=3,
                            n_bootstrap=300, is_home_fav=True, seed=None,
                            odds_source_type='estimated'):
    """Parametric bootstrap: sample λ from Gamma posterior, recompute edge.

    Returns edge_median, 95% CI, 80% CI, P(edge > 0), mean, std.

    When odds_source_type='estimated' (Module B), inflates edge_std by
    1.0 + 0.3 / sqrt(n_cs_quotes_available + 1) to reflect additional
    estimation uncertainty.
    """
    rng = np.random.RandomState(seed)
    lambda_home = max(0.1, pred.get('lambda_home', 1.2))
    lambda_away = max(0.1, pred.get('lambda_away', 1.0))
    n_h = max(5, min(30, int(lambda_home * 15)))
    n_a = max(5, min(30, int(lambda_away * 15)))

    edge_samples = []
    for _ in range(n_bootstrap):
        lam_h = max(0.05, rng.gamma(shape=n_h * lambda_home, scale=1.0 / n_h))
        lam_a = max(0.05, rng.gamma(shape=n_a * lambda_away, scale=1.0 / n_a))
        boot_pred = _build_bootstrap_matrix(lam_h, lam_a)
        outcomes, _, _, _, _, _, _, edge = build_dynamic_dutch(
            boot_pred, est_odds, strategy=strategy,
            max_legs=max_legs, max_overround=max_overround,
            min_selections=min_selections)
        if outcomes is not None:
            edge_samples.append(edge)

    if len(edge_samples) < 10:
        return {'edge_median': None, 'edge_ci_95': None, 'edge_ci_80': None,
                'prob_positive': None, 'edge_mean': None, 'edge_std': None,
                'insufficient_samples': True}

    arr = np.array(edge_samples)
    edge_std = float(np.std(arr))

    # Module B: inflate uncertainty for estimated CS odds
    if odds_source_type == 'estimated':
        # Count how many CS quotes are available (non-estimated from the odds dict)
        n_cs_available = sum(1 for k in est_odds if k.startswith('bookie_cs_') and est_odds.get(k, 0) > 1.0)
        inflation = 1.0 + 0.3 / math.sqrt(max(1, n_cs_available) + 1)
        edge_std = edge_std * inflation

    return {
        'edge_median': round(float(np.median(arr)), 4),
        'edge_ci_95': (round(float(np.percentile(arr, 2.5)), 4),
                       round(float(np.percentile(arr, 97.5)), 4)),
        'edge_ci_80': (round(float(np.percentile(arr, 10)), 4),
                       round(float(np.percentile(arr, 90)), 4)),
        'prob_positive': round(float(np.mean(arr > 0)), 4),
        'edge_mean': round(float(np.mean(arr)), 4),
        'edge_std': round(edge_std, 4),
        'insufficient_samples': False,
    }


def _build_bootstrap_matrix(lambda_home, lambda_away, max_goals=8):
    """Quick bivariate Poisson matrix for bootstrap sampling."""
    prob_matrix = np.zeros((max_goals + 1, max_goals + 1))
    for i in range(max_goals + 1):
        pi = math.exp(-lambda_home) * (lambda_home ** i) / math.factorial(i)
        for j in range(max_goals + 1):
            pj = math.exp(-lambda_away) * (lambda_away ** j) / math.factorial(j)
            prob_matrix[i, j] = pi * pj
    total = prob_matrix.sum()
    if total > 0: prob_matrix /= total
    return {
        'prob_matrix': prob_matrix,
        'lambda_home': lambda_home, 'lambda_away': lambda_away,
        'prob_h': float(np.sum(np.tril(prob_matrix, -1))),
        'prob_d': float(np.sum(np.diag(prob_matrix))),
        'prob_a': float(np.sum(np.triu(prob_matrix, 1))),
        'prob_over_25': float(sum(prob_matrix[i, j] for i in range(max_goals + 1)
                                 for j in range(max_goals + 1) if i + j > 2)),
        'prob_under_25': float(sum(prob_matrix[i, j] for i in range(max_goals + 1)
                                   for j in range(max_goals + 1) if i + j <= 2)),
    }


# ═══════════════════════════════════════════════════════════════════════
# Bankroll Management & Kelly Criterion for Dutching
# ═══════════════════════════════════════════════════════════════════════

def dutching_stake_recommendation(bankroll, cum_prob, dutching_odd, edge,
                                  edge_prob_positive=None, max_exposure_pct=0.05,
                                  kelly_fraction=0.25, min_stake=5.0):
    """Calculate optimal stake for a Dutching bet using fractional Kelly.

    Dutching is equivalent to a single bet with:
    - Win probability = cum_prob
    - Payout = dutching_odd
    - Net odds = dutching_odd - 1

    Kelly formula: f* = (p·b - 1) / (b - 1) = edge / (dutching_odd - 1)

    This function applies safety layers:
    1. Fractional Kelly (default 1/4 = conservative)
    2. Max exposure cap (% of bankroll per bet)
    3. Edge confidence adjustment (reduces stake when edge uncertain)
    4. Minimum stake floor (avoids micro-bets)

    Args:
        bankroll: Current bankroll in currency units
        cum_prob: Sum of model probabilities for covered scores
        dutching_odd: Combined Dutching odd
        edge: Predicted edge (cum_prob * dutching_odd - 1)
        edge_prob_positive: P(edge > 0) from bootstrap (optional)
        max_exposure_pct: Max % of bankroll per bet (default 5%)
        kelly_fraction: Fraction of full Kelly (default 0.25 = 1/4)
        min_stake: Minimum stake to place (default $5)

    Returns dict with recommended stake, Kelly fraction, and breakdown
    """
    if edge <= 0 or dutching_odd <= 1.01 or bankroll <= 0:
        return {'stake': 0.0, 'kelly_pct': 0.0, 'risk_level': 'skip',
                'reason': 'Edge negativo ou odd inválida — não apostar'}

    # Full Kelly fraction
    full_kelly = edge / (dutching_odd - 1.0)

    # Apply fractional Kelly
    fractional_kelly = full_kelly * kelly_fraction

    # Edge confidence adjustment
    # When P(edge > 0) < 0.85, reduce Kelly fraction further
    confidence_mult = 1.0
    if edge_prob_positive is not None:
        if edge_prob_positive < 0.65:
            confidence_mult = 0.0  # too uncertain, don't bet
        elif edge_prob_positive < 0.80:
            confidence_mult = 0.5
        elif edge_prob_positive < 0.90:
            confidence_mult = 0.75
        else:
            confidence_mult = 1.0

    adjusted_kelly = fractional_kelly * confidence_mult

    # Apply max exposure cap
    adjusted_kelly = min(adjusted_kelly, max_exposure_pct)

    # Calculate stake
    stake = bankroll * adjusted_kelly
    stake = max(min_stake, round(stake, 2))

    # Risk level classification
    exposure_pct = (stake / bankroll * 100) if bankroll > 0 else 0
    if exposure_pct <= 1.0:
        risk_level = 'conservative'
    elif exposure_pct <= 2.5:
        risk_level = 'moderate'
    elif exposure_pct <= 5.0:
        risk_level = 'aggressive'
    else:
        risk_level = 'max'

    return {
        'stake': stake,
        'kelly_pct': round(adjusted_kelly * 100, 2),
        'full_kelly_pct': round(full_kelly * 100, 2),
        'fractional_kelly_pct': round(fractional_kelly * 100, 2),
        'risk_level': risk_level,
        'confidence_mult': round(confidence_mult, 2),
        'max_exposure_pct': round(max_exposure_pct * 100, 1),
        'expected_profit': round(stake * edge, 2),
        'reason': _stake_reason(adjusted_kelly, risk_level, confidence_mult, edge),
    }


def _stake_reason(kelly_pct, risk_level, confidence_mult, edge):
    """Human-readable explanation for the stake recommendation."""
    if kelly_pct <= 0:
        return 'Edge com confiança insuficiente — não apostar'
    if confidence_mult < 0.75:
        return f'Stake reduzida (confiança {confidence_mult:.0%}). Edge +{edge*100:.1f}%, mas IC do bootstrap cruza zero'
    if risk_level == 'conservative':
        return f'Stake conservadora (1/4 Kelly). Edge +{edge*100:.1f}%, boa relação risco/retorno'
    if risk_level == 'moderate':
        return f'Stake moderada. Edge significativo (+{edge*100:.1f}%) com boa confiança'
    if risk_level == 'aggressive':
        return f'Stake agressiva. Edge forte (+{edge*100:.1f}%) com alta confiança estatística'
    return f'Stake máxima permitida. Edge excepcional (+{edge*100:.1f}%)'


def bankroll_simulation(bankroll, cum_prob, dutching_odd, edge, n_simulations=1000,
                        kelly_fraction=0.25, max_bets=100, seed=None):
    """Monte Carlo simulation of bankroll growth with Dutching Kelly staking.

    Simulates n_simulations paths of max_bets consecutive bets with the
    same edge and odds profile. Useful for visualizing risk of ruin.

    Returns dict with median final bankroll, ruin probability, growth stats.
    """
    rng = np.random.RandomState(seed)
    full_kelly = edge / (dutching_odd - 1.0) if dutching_odd > 1.01 else 0.0
    stake_pct = min(0.05, full_kelly * kelly_fraction)

    if stake_pct <= 0 or cum_prob <= 0:
        return {'median_final': bankroll, 'ruin_prob': 1.0,
                'growth_median_pct': 0, 'growth_p10_pct': 0, 'growth_p90_pct': 0}

    final_bankrolls = []
    ruins = 0
    ruin_threshold = bankroll * 0.10  # ruin = < 10% of original

    for _ in range(n_simulations):
        br = bankroll
        for _ in range(max_bets):
            stake = br * stake_pct
            if stake <= 0 or br <= ruin_threshold:
                ruins += 1
                break
            # Simulate outcome
            if rng.random() < cum_prob:
                br += stake * (dutching_odd - 1)
            else:
                br -= stake
            if br <= ruin_threshold:
                ruins += 1
                break
        final_bankrolls.append(max(0.01, br))

    arr = np.array(final_bankrolls)
    return {
        'median_final': round(float(np.median(arr)), 2),
        'ruin_prob': round(ruins / n_simulations, 4),
        'growth_median_pct': round((np.median(arr) / bankroll - 1) * 100, 1),
        'growth_p10_pct': round((np.percentile(arr, 10) / bankroll - 1) * 100, 1),
        'growth_p90_pct': round((np.percentile(arr, 90) / bankroll - 1) * 100, 1),
        'stake_pct_used': round(stake_pct * 100, 2),
    }


# ═══════════════════════════════════════════════════════════════════════
# Decision Layer: "Add this score?" and "Bet or skip?"
# ═══════════════════════════════════════════════════════════════════════

def _hours_until_match(commence_time_str):
    """Calculate hours until match kickoff from ISO datetime string."""
    try:
        kickoff = datetime.strptime(commence_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        delta = kickoff - datetime.now(timezone.utc)
        return max(0.0, delta.total_seconds() / 3600.0)
    except Exception:
        return None


def evaluate_extra_score(current_outcomes, current_odds, current_cum_prob,
                         cand_score, cand_prob, cand_odd):
    """Evaluate whether adding an extra score improves the Dutching edge.

    Calculates the marginal effect of adding cand_score to the current
    selection. The decision rule:
    - ADD: edge improves (edge_change > 0)
    - NEUTRAL: edge doesn't change significantly (-0.5% to 0)
    - SKIP: edge degrades (edge_change <= -0.5%)

    Args:
        current_outcomes: list of score strings already selected
        current_odds: list of odds for already-selected scores
        current_cum_prob: sum of probabilities for current selection
        cand_score: candidate score string (e.g. '1-0')
        cand_prob: model probability for candidate score
        cand_odd: bookmaker odd for candidate score

    Returns dict with edge_change, recommendation, new values
    """
    n_current = len(current_outcomes)
    if n_current == 0:
        return {'recommendation': 'add', 'edge_change': cand_prob * cand_odd - 1.0,
                'new_dutching_odd': cand_odd, 'new_cum_prob': cand_prob,
                'reason': 'First selection — always add'}

    if cand_odd <= 1.3:
        return {'recommendation': 'skip', 'edge_change': -0.10,
                'new_dutching_odd': None, 'new_cum_prob': None,
                'reason': 'Odd muito baixa (< 1.30), dilui o edge'}

    # Current Dutching
    cur_overround = sum(1.0 / o for o in current_odds)
    cur_dutching_odd = 1.0 / cur_overround if cur_overround > 0 else 1.0
    cur_edge = current_cum_prob * cur_dutching_odd - 1.0

    # With candidate added
    new_overround = cur_overround + 1.0 / cand_odd
    new_dutching_odd = 1.0 / new_overround if new_overround > 0 else 1.0
    new_cum_prob = current_cum_prob + cand_prob
    new_edge = new_cum_prob * new_dutching_odd - 1.0

    edge_change = new_edge - cur_edge

    if edge_change > 0:
        rec = 'add'
        reason = f'Adicionar melhora edge em +{edge_change*100:.1f}%'
    elif edge_change > -0.008:
        rec = 'neutral'
        reason = f'Neutro ({edge_change*100:+.1f}% edge), +{cand_prob*100:.1f}% cobertura'
    else:
        rec = 'skip'
        reason = f'Dilui edge em {edge_change*100:.1f}% — não recomendado'

    return {
        'recommendation': rec,
        'edge_change': round(edge_change, 4),
        'cur_edge': round(cur_edge, 4),
        'new_edge': round(new_edge, 4),
        'new_dutching_odd': round(new_dutching_odd, 2),
        'new_cum_prob': round(new_cum_prob, 4),
        'reason': reason,
    }


def dutching_quality_score(edge, edge_ci_95=None, profile_confidence=0.0,
                           dutching_odd=2.0, n_selections=5,
                           market_divergence=0.0, edge_prob_positive=None,
                           edge_std=None, has_real_odds=False,
                           hours_to_kickoff=None, odds_stale_hours=None):
    """Aggregate quality score (0-100) for a Dutching bet decision.

    Combines 6 signals into a single score. Weights are ADAPTIVE:
    - With ESTIMATED odds: less weight on edge (weak signal), more on
      market divergence and profile confidence (stronger signals)
    - With REAL CS odds: more weight on edge and bootstrap robustness
      (each score has independent EV, signal is much stronger)

    New: Sharpe-like edge scoring (edge/σ_boostrap), exponential time factor,
    odds staleness penalty.
    """
    # ── Adaptive weights based on odds source ────────────────────
    if has_real_odds:
        w_edge = 0.38
        w_bootstrap = 0.28
        w_profile = 0.10
        w_odds = 0.08
        w_market = 0.08
        w_selection = 0.08
    else:
        # Estimated odds: edge is weak, market divergence is king
        w_edge = 0.20
        w_bootstrap = 0.20
        w_profile = 0.18
        w_odds = 0.10
        w_market = 0.22
        w_selection = 0.10

    # ── 1. Edge: Sharpe-like (edge / σ) instead of raw edge ─────
    if edge_std is not None and edge_std > 0:
        sharpe = edge / edge_std
        # Sharpe 0.5 → score ~15%, Sharpe 3.0 → score ~100%
        edge_factor = min(1.0, max(0.0, sharpe / 3.0))
    else:
        # Fallback: raw edge clipping
        edge_factor = max(0.0, min(1.0, edge / 0.15))
    edge_score = edge_factor * w_edge * 100  # scale to component weight

    # ── 2. Bootstrap robustness ─────────────────────────────────
    bootstrap_score = 0.0
    if edge_prob_positive is not None:
        # P(edge > 0): 50% → 0pts, 100% → full
        bootstrap_factor = max(0.0, (edge_prob_positive - 0.50) / 0.50)
        bootstrap_score = bootstrap_factor * w_bootstrap * 100
    elif edge_ci_95 is not None:
        low, high = edge_ci_95
        if low is not None and high is not None:
            ci_range = high - low if high > low else 0.01
            if low > 0:
                bootstrap_score = w_bootstrap * 100
            elif high > 0:
                bootstrap_score = (high / ci_range) * w_bootstrap * 100
            else:
                bootstrap_score = 0.0

    # ── 3. Profile confidence ───────────────────────────────────
    profile_score = profile_confidence * w_profile * 100

    # ── 4. Dutching odd quality ─────────────────────────────────
    if 1.5 <= dutching_odd <= 6.0:
        odd_factor = 1.0
    elif 1.2 <= dutching_odd < 1.5:
        odd_factor = 0.4
    elif dutching_odd > 6.0:
        odd_factor = 0.6
    else:
        odd_factor = 0.0
    odd_score = odd_factor * w_odds * 100

    # ── 5. Market divergence ────────────────────────────────────
    div_abs = abs(market_divergence)
    if div_abs > 0.8:
        div_factor = 1.0
    elif div_abs > 0.4:
        div_factor = 0.75
    elif div_abs > 0.20:
        div_factor = 0.50
    elif div_abs > 0.08:
        div_factor = 0.25
    else:
        div_factor = 0.05
    div_score = div_factor * w_market * 100

    # ── 6. Selection diversity ──────────────────────────────────
    if 5 <= n_selections <= 6:
        sel_factor = 1.0
    elif n_selections == 4 or n_selections == 7:
        sel_factor = 0.7
    elif n_selections == 3:
        sel_factor = 0.5
    elif n_selections >= 8:
        sel_factor = 0.3
    else:
        sel_factor = 0.0
    sel_score = sel_factor * w_selection * 100

    total = edge_score + bootstrap_score + profile_score + odd_score + div_score + sel_score

    # ── Time factor: exponential decay (Melhoria #4) ────────────
    if hours_to_kickoff is not None and hours_to_kickoff > 0:
        time_bonus = (1.0 - math.exp(-hours_to_kickoff / 6.0)) * 12.0  # up to ~12 pts
        total = min(100.0, total + time_bonus)

    # ── Odds staleness penalty (Melhoria #5) ────────────────────
    staleness_mult = 1.0
    if odds_stale_hours is not None and odds_stale_hours > 0:
        if odds_stale_hours > 12:
            staleness_mult = 0.50
        elif odds_stale_hours > 6:
            staleness_mult = 0.75
        elif odds_stale_hours > 3:
            staleness_mult = 0.90
    total = total * staleness_mult

    total = round(min(100.0, total), 1)

    # ── Verdict ─────────────────────────────────────────────────
    verdict = 'SKIP'
    verdict_label = QUALITY_VERDICTS['SKIP']['label']
    verdict_color = QUALITY_VERDICTS['SKIP']['color']
    verdict_icon = QUALITY_VERDICTS['SKIP']['icon']
    for vkey in ['STRONG_BET', 'BET', 'CAUTION', 'SKIP']:
        if total >= QUALITY_VERDICTS[vkey]['min']:
            verdict = vkey
            verdict_label = QUALITY_VERDICTS[vkey]['label']
            verdict_color = QUALITY_VERDICTS[vkey]['color']
            verdict_icon = QUALITY_VERDICTS[vkey]['icon']
            break

    return {
        'score': total,
        'verdict': verdict,
        'verdict_label': verdict_label,
        'verdict_color': verdict_color,
        'verdict_icon': verdict_icon,
        'adaptive_weights': {
            'edge': w_edge, 'bootstrap': w_bootstrap, 'profile': w_profile,
            'odd_quality': w_odds, 'market_divergence': w_market, 'selection': w_selection,
        },
        'breakdown': {
            'edge_sharpe': round(edge_score, 1),
            'bootstrap_robustness': round(bootstrap_score, 1),
            'profile_confidence': round(profile_score, 1),
            'odd_quality': round(odd_score, 1),
            'market_divergence': round(div_score, 1),
            'selection_diversity': round(sel_score, 1),
        },
    }


def evaluate_alternatives(current_outcomes, current_odds, current_cum_prob,
                          alternative_scores, pred, est_odds):
    """Evaluate all alternative scores for a Dutching selection.

    Returns alternatives with recommendations attached.
    """
    for alt in alternative_scores:
        cand_prob = alt['prob']
        cand_odd = alt['odd']
        eval_result = evaluate_extra_score(
            current_outcomes, current_odds, current_cum_prob,
            alt['name'], cand_prob, cand_odd
        )
        alt['recommendation'] = eval_result['recommendation']
        alt['edge_change'] = eval_result['edge_change']
        alt['reason'] = eval_result['reason']
        alt['new_dutching_odd'] = eval_result['new_dutching_odd']
        alt['new_edge'] = eval_result['new_edge']

    # Sort: ADD first, then NEUTRAL, then SKIP
    rec_order = {'add': 0, 'neutral': 1, 'skip': 2}
    alternative_scores.sort(key=lambda x: (rec_order.get(x.get('recommendation', 'skip'), 2), -(x.get('edge_change', -1))))

    return alternative_scores
