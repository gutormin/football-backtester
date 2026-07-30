"""
Dutching Recalculation Engine.

Provides full recalculation of ALL metrics when the user edits odds manually.
Used by both Module A (Odds API) and Module B (OddsPapi) via their respective
recalculate endpoints.

Pipeline (12 steps):
1. Validate inputs
2. Load historical data for the league
3. Run predict_match_nb() for λ_home, λ_away, prob_matrix
4. Map selections_probs from prob_matrix
5. Run build_dynamic_dutch() with user's odds
6. Run classify_game_profile() with market divergence
7. Run bootstrap_dutching_edge() with 300 samples
8. Run dutching_quality_score() with adaptive weights
9. Run dutching_stake_recommendation()
10. Run bankroll_simulation() with 1000 sims
11. Build verdict_summary
12. Return RecalculateResponse
"""

import logging
import math
import numpy as np
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

from pydantic import BaseModel, Field

from backend.probability_pipeline import predict_match_nb
from backend.data_loader import load_league_data, auto_detect_data_source

from .core import (
    build_dynamic_dutch,
    classify_game_profile,
    bootstrap_dutching_edge,
    dutching_quality_score,
    dutching_stake_recommendation,
    bankroll_simulation,
    _score_to_key,
    _get_score_prob,
    _hours_until_match,
)


# ═══════════════════════════════════════════════════════════════════════
# Pydantic Models
# ═══════════════════════════════════════════════════════════════════════

class RecalculateRequest(BaseModel):
    """Request for full Dutching recalculation with user-edited odds."""
    match_name: str
    home_team: str
    away_team: str
    league_code: str
    commence_time: Optional[str] = None       # ISO datetime of match kickoff
    selections: List[str]                      # e.g. ["1-0", "2-1"]
    odds: List[float]                          # user-edited odds
    selections_probs: Optional[List[float]] = None  # model probs per selection
    bookmaker: str = "Bet365"

    # Optional — if not provided, recalculated from scratch
    o25_odd: Optional[float] = None
    u25_odd: Optional[float] = None
    h2h_odds: Optional[Tuple[float, float, float]] = None  # (H, D, A)

    # Bankroll parameters (editáveis)
    bankroll: float = 1000.0
    kelly_fraction: float = 0.25
    max_exposure_pct: float = 0.05

    # Odds source info
    odds_source_type: str = "estimated"  # 'real' or 'estimated'


class RecalculateResponse(BaseModel):
    """Full recalculation result with all Dutching metrics."""
    # Core Dutching
    dutching_odd: float
    combined_prob: float
    edge: float
    edge_pct: float

    # Bootstrap
    edge_ci_95: Optional[Tuple[float, float]] = None
    edge_ci_80: Optional[Tuple[float, float]] = None
    edge_prob_positive: Optional[float] = None

    # Game Profile
    game_profile: str
    profile_scores: Dict[str, float] = {}
    profile_confidence: float
    market_divergence: float

    # Quality Score
    quality_score: float
    quality_verdict: str
    quality_verdict_label: str
    quality_verdict_color: str
    quality_verdict_icon: str
    quality_breakdown: Dict[str, float] = {}
    adaptive_weights: Dict[str, float] = {}

    # Kelly Stake
    stake_recommendation: Dict[str, Any] = {}

    # Bankroll Simulation
    bankroll_simulation: Dict[str, Any] = {}

    # Final Verdict
    passes_filter: bool
    verdict_summary: str

    # Metadata
    odds_source_type: str
    recalculated_at: str


# ═══════════════════════════════════════════════════════════════════════
# Engine
# ═══════════════════════════════════════════════════════════════════════

def _find_closest_team(api_name, all_teams_local):
    """Match team name to local historical data."""
    api_lower = api_name.lower()
    for t in all_teams_local:
        if t.lower() in api_lower or api_lower in t.lower():
            return t
    return None


def full_recalculate(req: RecalculateRequest) -> RecalculateResponse:
    """
    Execute the full 12-step recalculation pipeline.

    Args:
        req: RecalculateRequest with user-edited odds and match context.

    Returns:
        RecalculateResponse with all computed metrics.

    Raises:
        ValueError: if inputs are invalid (caught by caller → HTTP 400)
    """
    # ── Step 1: Validate inputs ──────────────────────────────────
    if len(req.selections) < 2:
        raise ValueError("Informe ao menos 2 seleções de placar.")

    odds = [o for o in req.odds if o and o > 1.0]
    if len(odds) != len(req.selections):
        raise ValueError("Número de odds deve ser igual ao número de seleções.")

    # ── Step 2: Load historical data ─────────────────────────────
    ds = auto_detect_data_source(req.league_code)
    hist_df = load_league_data(req.league_code, start_date='2020-08-01', data_source=ds)
    if hist_df is None or hist_df.empty:
        raise ValueError(f"Sem dados históricos para a liga {req.league_code}.")

    all_teams = list(set(hist_df['HomeTeam'].tolist() + hist_df['AwayTeam'].tolist()))
    home_local = _find_closest_team(req.home_team, all_teams)
    away_local = _find_closest_team(req.away_team, all_teams)
    if not home_local or not away_local:
        raise ValueError(f"Times não encontrados nos dados históricos: {req.home_team} / {req.away_team}")

    # ── Step 3: Run predict_match_nb ─────────────────────────────
    pred = predict_match_nb(home_local, away_local, hist_df, datetime.now())
    if not pred or 'lambda_home' not in pred:
        raise ValueError("Falha ao rodar modelo NB para este jogo.")

    # ── Step 4: Map selections_probs from prob_matrix ────────────
    selections_probs = req.selections_probs
    if not selections_probs or len(selections_probs) != len(req.selections):
        selections_probs = []
        for sel in req.selections:
            prob = _get_score_prob(pred, sel)
            selections_probs.append(round(float(prob), 4))

    prob_combined = sum(selections_probs)

    # Build est_odds dict for build_dynamic_dutch
    est_odds = {}
    for sel, odd in zip(req.selections, odds):
        key = _score_to_key(sel)
        est_odds[key] = float(odd)

    # ── Step 5: Run build_dynamic_dutch ──────────────────────────
    is_home_fav = pred['prob_h'] > pred['prob_a']
    outcomes, _, _, _, _, cum_prob, dutching_odd, edge = \
        build_dynamic_dutch(pred, est_odds, strategy='dynamic',
                            max_legs=8, max_overround=0.92, min_selections=2)

    if outcomes is None:
        raise ValueError("Combinação Dutching inviável com essas odds e seleções.")

    # Use manual seleção se build_dynamic_dutch alterou os selecionados
    # (preserva a ordem do usuário, mas recalcula edge com a fórmula padrão)
    if len(outcomes) != len(req.selections):
        # Recompute directly with user's exact selections
        overround = sum(1.0 / o for o in odds)
        dutching_odd = 1.0 / overround if overround > 0 else 1.0
        prob_combined_final = prob_combined
        edge = prob_combined_final * dutching_odd - 1.0
    else:
        prob_combined_final = cum_prob
        # dutching_odd and edge from build_dynamic_dutch

    # ── Step 6: Classify game profile ────────────────────────────
    market_ou = None
    if req.o25_odd and req.u25_odd and req.o25_odd > 1.01 and req.u25_odd > 1.01:
        market_ou = (req.o25_odd, req.u25_odd)

    game_profile = classify_game_profile(
        pred, is_home_fav,
        market_ou_odds=market_ou,
        league_code=req.league_code
    )

    # ── Step 7: Bootstrap ────────────────────────────────────────
    has_real_odds = req.odds_source_type == 'real'
    edge_ci = bootstrap_dutching_edge(
        pred, est_odds, strategy='dynamic',
        max_legs=8, max_overround=0.92, min_selections=2,
        n_bootstrap=300, is_home_fav=is_home_fav,
        odds_source_type=req.odds_source_type,
    )

    # ── Step 8: Quality score ────────────────────────────────────
    hours_to_kickoff = _hours_until_match(req.commence_time) if req.commence_time else None

    quality = dutching_quality_score(
        edge=edge,
        edge_ci_95=edge_ci.get('edge_ci_95'),
        profile_confidence=game_profile['confidence'],
        dutching_odd=dutching_odd,
        n_selections=len(outcomes),
        market_divergence=game_profile.get('market_divergence', 0),
        edge_prob_positive=edge_ci.get('prob_positive'),
        edge_std=edge_ci.get('edge_std'),
        has_real_odds=has_real_odds,
        hours_to_kickoff=hours_to_kickoff,
        odds_stale_hours=None,
    )

    # ── Step 9: Kelly stake ──────────────────────────────────────
    stake_rec = dutching_stake_recommendation(
        bankroll=req.bankroll,
        cum_prob=prob_combined_final,
        dutching_odd=dutching_odd,
        edge=edge,
        edge_prob_positive=edge_ci.get('prob_positive'),
        max_exposure_pct=req.max_exposure_pct,
        kelly_fraction=req.kelly_fraction,
    )

    # ── Step 10: Bankroll simulation ─────────────────────────────
    bankroll_sim = bankroll_simulation(
        bankroll=req.bankroll,
        cum_prob=prob_combined_final,
        dutching_odd=dutching_odd,
        edge=edge,
        kelly_fraction=req.kelly_fraction,
    )

    # ── Step 11: Build verdict summary ───────────────────────────
    passes_quality = quality['score'] >= 40
    passes_edge = edge > 0
    passes_filter = passes_quality and passes_edge and stake_rec.get('stake', 0) > 0

    verdict_parts = []
    if passes_filter:
        verdict_parts.append(f"✅ PASSA — Score {quality['score']:.0f}/100, Edge +{edge*100:.1f}%")
        if stake_rec.get('stake', 0) > 0:
            verdict_parts.append(
                f"Stake: R${stake_rec['stake']:.2f} ({stake_rec['kelly_pct']:.1f}% da banca)")
        if bankroll_sim.get('growth_median_pct', 0) > 0:
            verdict_parts.append(
                f"Simulação: crescimento mediano +{bankroll_sim['growth_median_pct']:.0f}%, "
                f"ruína {bankroll_sim['ruin_prob']*100:.1f}%")
        if edge_ci.get('prob_positive') is not None:
            verdict_parts.append(f"P(edge>0): {edge_ci['prob_positive']*100:.0f}%")
    else:
        if not passes_edge:
            verdict_parts.append("❌ NÃO PASSA — Edge negativo ou zero")
        elif stake_rec.get('stake', 0) == 0:
            verdict_parts.append("❌ NÃO PASSA — Kelly não recomenda aposta")
        else:
            verdict_parts.append(f"❌ NÃO PASSA — Score de qualidade insuficiente ({quality['score']:.0f}/100)")

    verdict_summary = " | ".join(verdict_parts)

    # ── Step 12: Build response ──────────────────────────────────
    return RecalculateResponse(
        dutching_odd=round(float(dutching_odd), 3),
        combined_prob=round(float(prob_combined_final), 4),
        edge=round(float(edge), 4),
        edge_pct=round(float(edge) * 100, 2),
        edge_ci_95=edge_ci.get('edge_ci_95'),
        edge_ci_80=edge_ci.get('edge_ci_80'),
        edge_prob_positive=edge_ci.get('prob_positive'),
        game_profile=game_profile['best_profile'],
        profile_scores=game_profile.get('scores', {}),
        profile_confidence=game_profile['confidence'],
        market_divergence=game_profile.get('market_divergence', 0.0),
        quality_score=quality['score'],
        quality_verdict=quality['verdict'],
        quality_verdict_label=quality['verdict_label'],
        quality_verdict_color=quality['verdict_color'],
        quality_verdict_icon=quality['verdict_icon'],
        quality_breakdown=quality.get('breakdown', {}),
        adaptive_weights=quality.get('adaptive_weights', {}),
        stake_recommendation=stake_rec,
        bankroll_simulation=bankroll_sim,
        passes_filter=passes_filter,
        verdict_summary=verdict_summary,
        odds_source_type=req.odds_source_type,
        recalculated_at=datetime.now().isoformat(),
    )
