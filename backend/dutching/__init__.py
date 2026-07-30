"""
Dutching Scanner Package — Refactored modular architecture.

Modules:
- core.py:     Shared functions reused by all scanners (profiling, bootstrap, quality, Kelly, bankroll)
- ml.py:       XGBoost ensemble for score group bias correction
- anchored.py: Anchored triage scoring (ranks games by real market divergence WITHOUT inventing CS odds)
- scanner_odds_api.py:  Module A — pipeline using The Odds API (real CS odds)
- scanner_oddspapi.py:  Module B — pipeline using OddsPapi (estimated CS odds)
- recalculate.py:       Full recalculation engine for user-edited odds
"""

from .core import (
    # Constants
    ALL_DUTCH_SCORES, SCORE_GROUPS, LEAGUE_AVG_GOALS, LEAGUE_AVG_GOALS_DEFAULT,
    LEAGUE_STD_GOALS, STRATEGY_LABELS, PROFILE_LABELS, QUALITY_VERDICTS,
    # Game profile
    _get_league_avg_goals, _solve_lambda_from_under25_fast,
    classify_game_profile, resolve_strategy,
    # Dominance scoring
    score_dominance_weight,
    # Team dispersions
    compute_team_dispersions, _estimate_team_alpha, get_team_alphas,
    # Dutching builder
    _score_to_key, _get_score_prob, build_dynamic_dutch,
    get_selections_and_alternatives,
    # Bootstrap
    bootstrap_dutching_edge, _build_bootstrap_matrix,
    # Kelly & bankroll
    dutching_stake_recommendation, _stake_reason, bankroll_simulation,
    # Quality score
    _hours_until_match, evaluate_extra_score, dutching_quality_score,
    evaluate_alternatives,
    # League guessing
    _guess_league_from_teams,
)

from .ml import DutchingMLEnsemble, ScoreGroupClassifier
from .anchored import compute_anchored_score, _concentration_score, _model_confidence
