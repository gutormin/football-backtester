"""
Probability Pipeline — unified probability computation for all backtest paths.

Single source of truth for:
- Team rating computation (goals, SOT, xG, HT)
- Lambda blending (multi-tier: xG > SOT > goals)
- Elo factor application
- Score matrix construction (Poisson or Negative Binomial)
- Dixon-Coles rho correction
- All market probability derivations (1X2, O/U, BTTS, CS, HT, AH)

Used by: ChronologicalBacktester.run(), run_parallel_scan(), dutching_scanner.py
"""

import math
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, List

from .elo_model import estimate_dynamic_rho
from .models import calculate_ah_probabilities, get_fair_ah_odds
from .constants import (
    NB_ALPHA_HOME, NB_ALPHA_AWAY,
    SHRINKAGE_FT, SHRINKAGE_HT,
    RATING_CAP_LOW, RATING_CAP_HIGH,
    LAMBDA_CAP_LOW, LAMBDA_CAP_HIGH,
    LAMBDA_CAP_HT_LOW, LAMBDA_CAP_HT_HIGH,
    HT_RATING_CAP_LOW, HT_RATING_CAP_HIGH,
    HT_AWAY_FLOOR_FACTOR,
    MAX_GOALS, RHO_FALLBACK,
    BLEND_XG, BLEND_SOT, BLEND_GOALS,
    BLEND_NO_XG_GOALS, BLEND_NO_XG_SOT,
)

_FACTORIALS = [math.factorial(i) for i in range(16)]

# ── Model type constants ───────────────────────────────────────────
MODEL_POISSON = "poisson"
MODEL_NEGATIVE_BINOMIAL = "negative_binomial"
MODEL_TYPES = [MODEL_POISSON, MODEL_NEGATIVE_BINOMIAL]

# Re-export for backward compatibility
DEFAULT_NB_ALPHA_HOME = NB_ALPHA_HOME
DEFAULT_NB_ALPHA_AWAY = NB_ALPHA_AWAY


@dataclass
class MatchProbabilityBundle:
    """Output bundle from ProbabilityPipeline.compute_all()."""
    lambda_home: float
    lambda_away: float
    lambda_goals_home: float
    lambda_goals_away: float
    lambda_shots_home: Optional[float]
    lambda_shots_away: Optional[float]
    lambda_xg_home: Optional[float]
    lambda_xg_away: Optional[float]
    lambda_home_ht: float
    lambda_away_ht: float
    h_att: float
    h_def: float
    a_att: float
    a_def: float
    h_xg_att: float
    h_xg_def: float
    a_xg_att: float
    a_xg_def: float
    elo_factor_h: float
    elo_factor_a: float
    prob_matrix: np.ndarray
    prob_h: float
    prob_d: float
    prob_a: float
    prob_over_25: float
    prob_over_15: float
    prob_over_35: float
    prob_over_45: float
    prob_over_55: float
    prob_btts_yes: float
    prob_matrix_ht: np.ndarray
    max_goals: int
    prob_h_ht: float
    prob_d_ht: float
    prob_a_ht: float
    prob_over_05_ht: float
    prob_over_15_ht: float
    rho: float
    avg_h_goals: float
    avg_a_goals: float

    def to_dict(self) -> dict:
        """Convert to dict compatible with existing _compute_match_probabilities() callers."""
        return {
            'lambda_home': self.lambda_home,
            'lambda_away': self.lambda_away,
            'lambda_goals_home': self.lambda_goals_home,
            'lambda_goals_away': self.lambda_goals_away,
            'lambda_shots_home': self.lambda_shots_home,
            'lambda_shots_away': self.lambda_shots_away,
            'lambda_xg_home': self.lambda_xg_home,
            'lambda_xg_away': self.lambda_xg_away,
            'lambda_home_ht': self.lambda_home_ht,
            'lambda_away_ht': self.lambda_away_ht,
            'h_att': self.h_att, 'h_def': self.h_def,
            'a_att': self.a_att, 'a_def': self.a_def,
            'h_xg_att': self.h_xg_att, 'h_xg_def': self.h_xg_def,
            'a_xg_att': self.a_xg_att, 'a_xg_def': self.a_xg_def,
            'elo_factor_h': self.elo_factor_h, 'elo_factor_a': self.elo_factor_a,
            'prob_matrix': self.prob_matrix,
            'prob_h': self.prob_h, 'prob_d': self.prob_d, 'prob_a': self.prob_a,
            'prob_over_25': self.prob_over_25, 'prob_under_25': 1.0 - self.prob_over_25,
            'prob_over_15': self.prob_over_15, 'prob_under_15': 1.0 - self.prob_over_15,
            'prob_over_35': self.prob_over_35, 'prob_under_35': 1.0 - self.prob_over_35,
            'prob_over_45': self.prob_over_45, 'prob_under_45': 1.0 - self.prob_over_45,
            'prob_over_55': self.prob_over_55, 'prob_under_55': 1.0 - self.prob_over_55,
            'prob_btts_yes': self.prob_btts_yes, 'prob_btts_no': 1.0 - self.prob_btts_yes,
            'prob_matrix_ht': self.prob_matrix_ht,
            'prob_h_ht': self.prob_h_ht, 'prob_d_ht': self.prob_d_ht, 'prob_a_ht': self.prob_a_ht,
            'prob_over_05_ht': self.prob_over_05_ht, 'prob_over_15_ht': self.prob_over_15_ht,
            'max_goals': self.max_goals,
            'rho': self.rho, 'avg_h_goals': self.avg_h_goals, 'avg_a_goals': self.avg_a_goals,
        }


class ProbabilityPipeline:
    """Unified probability computation for football match prediction.

    Consolidates what was previously split across:
    - PoissonModel.predict_match() (models.py) — time-decay, not used by engine
    - ChronologicalBacktester._compute_match_probabilities() — performance-decay, primary
    - compute_nb_score_matrix() (models.py) — Negative Binomial, only dutching scanner

    Now all paths go through this single class with configurable model type.
    """

    def __init__(self,
                 model_type: str = MODEL_POISSON,
                 rolling_games: int = 15,
                 shrinkage: float = SHRINKAGE_FT,
                 rating_cap_low: float = RATING_CAP_LOW,
                 rating_cap_high: float = RATING_CAP_HIGH,
                 lambda_cap_low: float = LAMBDA_CAP_LOW,
                 lambda_cap_high: float = LAMBDA_CAP_HIGH,
                 lambda_cap_ht_low: float = LAMBDA_CAP_HT_LOW,
                 lambda_cap_ht_high: float = LAMBDA_CAP_HT_HIGH,
                 max_goals: int = MAX_GOALS,
                 nb_alpha_home: float = NB_ALPHA_HOME,
                 nb_alpha_away: float = NB_ALPHA_AWAY,
                 # Blending weights
                 blend_xg: float = BLEND_XG,
                 blend_sot: float = BLEND_SOT,
                 blend_goals: float = BLEND_GOALS,
                 blend_no_xg_goals: float = BLEND_NO_XG_GOALS,
                 blend_no_xg_sot: float = BLEND_NO_XG_SOT):
        self.model_type = model_type
        self.rolling_games = rolling_games
        self.shrinkage = shrinkage
        self.rating_cap_low = rating_cap_low
        self.rating_cap_high = rating_cap_high
        self.lambda_cap_low = lambda_cap_low
        self.lambda_cap_high = lambda_cap_high
        self.lambda_cap_ht_low = lambda_cap_ht_low
        self.lambda_cap_ht_high = lambda_cap_ht_high
        self.max_goals = max_goals
        self.nb_alpha_home = nb_alpha_home
        self.nb_alpha_away = nb_alpha_away
        self.blend_xg = blend_xg
        self.blend_sot = blend_sot
        self.blend_goals = blend_goals
        self.blend_no_xg_goals = blend_no_xg_goals
        self.blend_no_xg_sot = blend_no_xg_sot

    # ── Rating computation ─────────────────────────────────────────

    @staticmethod
    def _weighted_mean(values: list, decay: float) -> float:
        """Exponentially weighted mean of recent values."""
        if not values:
            return 1.0
        n = len(values)
        weights = np.exp(-decay * np.arange(n - 1, -1, -1))
        w_sum = weights.sum()
        if w_sum == 0:
            return float(np.mean(values))
        return float(np.sum(np.array(values) * weights) / w_sum)

    @staticmethod
    def _shrink_and_cap(value: float, shrinkage: float,
                        cap_low: float, cap_high: float) -> float:
        """Apply Bayesian shrinkage toward 1.0, then hard-cap."""
        shrunk = shrinkage * value + (1.0 - shrinkage) * 1.0
        if np.isnan(shrunk):
            return 1.0
        return max(cap_low, min(cap_high, shrunk))

    def _compute_ratings(self, scored: list, conceded: list,
                         league_scored_avg: float, league_conceded_avg: float,
                         decay: float) -> Tuple[float, float, float, float]:
        """Compute attack/defense ratings from rolling lists.

        Returns: (att, def, att_raw, def_raw)
        """
        if not scored or league_scored_avg <= 0:
            return 1.0, 1.0, 1.0, 1.0

        att_raw = self._weighted_mean(scored, decay) / league_scored_avg
        def_raw = self._weighted_mean(conceded, decay) / league_conceded_avg

        att = self._shrink_and_cap(att_raw, self.shrinkage,
                                   self.rating_cap_low, self.rating_cap_high)
        def_rt = self._shrink_and_cap(def_raw, self.shrinkage,
                                      self.rating_cap_low, self.rating_cap_high)
        return att, def_rt, att_raw, def_raw

    # ── Lambda computation ─────────────────────────────────────────

    def _compute_lambda_goals(self, team_home_scored, team_home_conceded,
                              team_away_scored, team_away_conceded,
                              league_home_goals, league_away_goals,
                              home_team, away_team, league_code, decay):
        """Compute goals-based expected goals (lambda)."""
        h_scored = team_home_scored[home_team][-self.rolling_games:]
        h_conceded = team_home_conceded[home_team][-self.rolling_games:]
        a_scored = team_away_scored[away_team][-self.rolling_games:]
        a_conceded = team_away_conceded[away_team][-self.rolling_games:]

        leg_h_goals = league_home_goals[league_code][-100:]
        leg_a_goals = league_away_goals[league_code][-100:]
        avg_h_goals = np.mean(leg_h_goals) if leg_h_goals else 1.35
        avg_a_goals = np.mean(leg_a_goals) if leg_a_goals else 1.05

        h_att, h_def, _, _ = self._compute_ratings(
            h_scored, h_conceded, avg_h_goals, avg_a_goals, decay)
        a_att, a_def, _, _ = self._compute_ratings(
            a_scored, a_conceded, avg_a_goals, avg_h_goals, decay)

        lambda_home = avg_h_goals * h_att * a_def
        lambda_away = avg_a_goals * a_att * h_def

        return lambda_home, lambda_away, h_att, h_def, a_att, a_def, avg_h_goals, avg_a_goals

    def _compute_lambda_sot(self, team_home_sot, team_home_sot_conceded,
                            team_away_sot, team_away_sot_conceded,
                            league_home_sot, league_away_sot,
                            home_team, away_team, league_code, decay,
                            avg_h_goals, avg_a_goals):
        """Compute SOT-based expected goals. Returns (lambda_h, lambda_a) or (None, None)."""
        h_sot_scored = team_home_sot[home_team][-self.rolling_games:]
        h_sot_conceded = team_home_sot_conceded[home_team][-self.rolling_games:]
        a_sot_scored = team_away_sot[away_team][-self.rolling_games:]
        a_sot_conceded = team_away_sot_conceded[away_team][-self.rolling_games:]
        leg_h_sot = league_home_sot[league_code][-100:]
        leg_a_sot = league_away_sot[league_code][-100:]

        has_data = (h_sot_scored and h_sot_conceded and a_sot_scored and
                    a_sot_conceded and leg_h_sot and leg_a_sot)
        if not has_data:
            return None, None

        avg_h_sot = np.mean(leg_h_sot)
        avg_a_sot = np.mean(leg_a_sot)
        if pd.isna(avg_h_sot) or avg_h_sot == 0:
            avg_h_sot = 4.5
        if pd.isna(avg_a_sot) or avg_a_sot == 0:
            avg_a_sot = 3.5

        h_sot_att, h_sot_def, _, _ = self._compute_ratings(
            h_sot_scored, h_sot_conceded, avg_h_sot, avg_a_sot, decay)
        a_sot_att, a_sot_def, _, _ = self._compute_ratings(
            a_sot_scored, a_sot_conceded, avg_a_sot, avg_h_sot, decay)

        exp_sot_home = avg_h_sot * h_sot_att * a_sot_def
        exp_sot_away = avg_a_sot * a_sot_att * h_sot_def
        conversion_home = avg_h_goals / avg_h_sot
        conversion_away = avg_a_goals / avg_a_sot

        lambda_shots_home = exp_sot_home * conversion_home
        lambda_shots_away = exp_sot_away * conversion_away
        lambda_shots_home = max(0.1, min(5.0, lambda_shots_home))
        lambda_shots_away = max(0.1, min(5.0, lambda_shots_away))

        return lambda_shots_home, lambda_shots_away

    def _compute_lambda_xg(self, team_home_xg, team_home_xg_conceded,
                           team_away_xg, team_away_xg_conceded,
                           league_home_xg, league_away_xg,
                           home_team, away_team, league_code, decay):
        """Compute xG-based expected goals. Returns (lambda_h, lambda_a, h_xg_att, h_xg_def, a_xg_att, a_xg_def) or None."""
        h_xg_scored = team_home_xg[home_team][-self.rolling_games:]
        h_xg_conceded = team_home_xg_conceded[home_team][-self.rolling_games:]
        a_xg_scored = team_away_xg[away_team][-self.rolling_games:]
        a_xg_conceded = team_away_xg_conceded[away_team][-self.rolling_games:]
        leg_h_xg = league_home_xg[league_code][-100:]
        leg_a_xg = league_away_xg[league_code][-100:]

        has_data = (h_xg_scored and h_xg_conceded and a_xg_scored and
                    a_xg_conceded and leg_h_xg and leg_a_xg)
        if not has_data:
            return None

        avg_h_xg = np.mean(leg_h_xg)
        avg_a_xg = np.mean(leg_a_xg)
        if pd.isna(avg_h_xg) or avg_h_xg == 0:
            avg_h_xg = 1.35
        if pd.isna(avg_a_xg) or avg_a_xg == 0:
            avg_a_xg = 1.05

        h_xg_att, h_xg_def, _, _ = self._compute_ratings(
            h_xg_scored, h_xg_conceded, avg_h_xg, avg_a_xg, decay)
        a_xg_att, a_xg_def, _, _ = self._compute_ratings(
            a_xg_scored, a_xg_conceded, avg_a_xg, avg_h_xg, decay)

        lambda_xg_home = avg_h_xg * h_xg_att * a_xg_def
        lambda_xg_away = avg_a_xg * a_xg_att * h_xg_def
        lambda_xg_home = max(0.1, min(5.0, lambda_xg_home))
        lambda_xg_away = max(0.1, min(5.0, lambda_xg_away))

        return (lambda_xg_home, lambda_xg_away,
                h_xg_att, h_xg_def, a_xg_att, a_xg_def)

    # ── HT Lambda computation ──────────────────────────────────────

    def _compute_lambda_ht(self, team_home_scored_ht, team_home_conceded_ht,
                           team_away_scored_ht, team_away_conceded_ht,
                           league_home_goals_ht, league_away_goals_ht,
                           home_team, away_team, league_code, decay,
                           avg_h_goals, avg_a_goals):
        """Compute halftime expected goals."""
        h_scored_ht = team_home_scored_ht[home_team][-self.rolling_games:]
        h_conceded_ht = team_home_conceded_ht[home_team][-self.rolling_games:]
        a_scored_ht = team_away_scored_ht[away_team][-self.rolling_games:]
        a_conceded_ht = team_away_conceded_ht[away_team][-self.rolling_games:]
        leg_h_goals_ht = league_home_goals_ht[league_code][-100:]
        leg_a_goals_ht = league_away_goals_ht[league_code][-100:]

        avg_h_goals_ht = np.mean(leg_h_goals_ht) if leg_h_goals_ht else (avg_h_goals * 0.45)
        avg_a_goals_ht = np.mean(leg_a_goals_ht) if leg_a_goals_ht else (avg_a_goals * 0.45)
        if avg_h_goals_ht == 0:
            avg_h_goals_ht = 0.6
        if avg_a_goals_ht == 0:
            avg_a_goals_ht = 0.45

        # HT uses heavier shrinkage (60/40) and tighter caps
        ht_shrinkage = SHRINKAGE_HT
        h_att_ht_raw = (self._weighted_mean(h_scored_ht, decay) / avg_h_goals_ht) if h_scored_ht else 1.0
        h_def_ht_raw = (self._weighted_mean(h_conceded_ht, decay) / avg_a_goals_ht) if h_conceded_ht else 1.0
        a_att_ht_raw = (self._weighted_mean(a_scored_ht, decay) / avg_a_goals_ht) if a_scored_ht else 1.0
        a_def_ht_raw = (self._weighted_mean(a_conceded_ht, decay) / avg_h_goals_ht) if a_conceded_ht else 1.0

        h_att_ht = self._shrink_and_cap(h_att_ht_raw, ht_shrinkage, HT_RATING_CAP_LOW, HT_RATING_CAP_HIGH)
        h_def_ht = self._shrink_and_cap(h_def_ht_raw, ht_shrinkage, HT_RATING_CAP_LOW, HT_RATING_CAP_HIGH)
        a_att_ht = self._shrink_and_cap(a_att_ht_raw, ht_shrinkage, HT_RATING_CAP_LOW, HT_RATING_CAP_HIGH)
        a_def_ht = self._shrink_and_cap(a_def_ht_raw, ht_shrinkage, HT_RATING_CAP_LOW, HT_RATING_CAP_HIGH)

        lambda_home_ht = avg_h_goals_ht * h_att_ht * a_def_ht
        lambda_away_ht = avg_a_goals_ht * a_att_ht * h_def_ht

        return lambda_home_ht, lambda_away_ht

    # ── Score matrix construction ──────────────────────────────────

    def _build_poisson_matrix(self, lambda_home: float, lambda_away: float,
                              rho: float) -> np.ndarray:
        """Build a bivariate Poisson score matrix with Dixon-Coles correction."""
        max_g = self.max_goals
        home_probs = np.array([math.exp(-lambda_home) * (lambda_home ** i) / _FACTORIALS[i]
                               for i in range(max_g + 1)])
        away_probs = np.array([math.exp(-lambda_away) * (lambda_away ** i) / _FACTORIALS[i]
                               for i in range(max_g + 1)])
        prob_matrix = np.outer(home_probs, away_probs)

        # Dixon-Coles correction for low-scoring outcomes
        tau_00 = max(0.0, 1.0 - lambda_home * lambda_away * rho)
        tau_10 = max(0.0, 1.0 + lambda_away * rho)
        tau_01 = max(0.0, 1.0 + lambda_home * rho)
        tau_11 = max(0.0, 1.0 - rho)

        prob_matrix[0, 0] *= tau_00
        prob_matrix[1, 0] *= tau_10
        prob_matrix[0, 1] *= tau_01
        prob_matrix[1, 1] *= tau_11

        matrix_sum = prob_matrix.sum()
        if matrix_sum > 0:
            prob_matrix = prob_matrix / matrix_sum

        return prob_matrix

    def _build_nb_matrix(self, lambda_home: float, lambda_away: float,
                         rho: float) -> np.ndarray:
        """Build a bivariate Negative Binomial score matrix with Dixon-Coles correction.

        NB2 parameterization: Var = mu + alpha * mu^2 (accounts for overdispersion).
        """
        max_g = self.max_goals
        alpha_h = self.nb_alpha_home
        alpha_a = self.nb_alpha_away

        def nb_pmf(k, mu, alpha):
            if alpha <= 0:
                return math.exp(-mu) * (mu ** k) / math.factorial(k)
            n_param = 1.0 / alpha
            p_param = 1.0 / (1.0 + alpha * mu)
            # scipy.stats.nbinom.pmf
            from scipy.stats import nbinom
            return nbinom.pmf(k, n_param, p_param)

        home_probs = np.array([nb_pmf(i, lambda_home, alpha_h) for i in range(max_g + 1)])
        away_probs = np.array([nb_pmf(i, lambda_away, alpha_a) for i in range(max_g + 1)])

        home_probs = home_probs / home_probs.sum()
        away_probs = away_probs / away_probs.sum()

        prob_matrix = np.outer(home_probs, away_probs)

        # Dixon-Coles correction
        tau_00 = max(0.0, 1.0 - lambda_home * lambda_away * rho)
        tau_10 = max(0.0, 1.0 + lambda_away * rho)
        tau_01 = max(0.0, 1.0 + lambda_home * rho)
        tau_11 = max(0.0, 1.0 - rho)

        prob_matrix[0, 0] *= tau_00
        prob_matrix[1, 0] *= tau_10
        prob_matrix[0, 1] *= tau_01
        prob_matrix[1, 1] *= tau_11

        matrix_sum = prob_matrix.sum()
        if matrix_sum > 0:
            prob_matrix = prob_matrix / matrix_sum

        return prob_matrix

    def _build_score_matrix(self, lambda_home: float, lambda_away: float,
                            rho: float) -> np.ndarray:
        """Build score matrix using the configured model type."""
        if self.model_type == MODEL_NEGATIVE_BINOMIAL:
            return self._build_nb_matrix(lambda_home, lambda_away, rho)
        return self._build_poisson_matrix(lambda_home, lambda_away, rho)

    # ── Market probability derivation ──────────────────────────────

    @staticmethod
    def _derive_market_probs(prob_matrix: np.ndarray, max_goals: int) -> dict:
        """Derive all market probabilities from a score matrix."""
        prob_h = float(np.sum(np.tril(prob_matrix, -1)))
        prob_d = float(np.sum(np.diag(prob_matrix)))
        prob_a = float(np.sum(np.triu(prob_matrix, 1)))

        prob_over_25 = 0.0
        prob_over_15 = 0.0
        prob_over_35 = 0.0
        prob_over_45 = 0.0
        prob_over_55 = 0.0
        for x in range(max_goals + 1):
            for y in range(max_goals + 1):
                tot = x + y
                if tot > 2:
                    prob_over_25 += prob_matrix[x, y]
                if tot > 1:
                    prob_over_15 += prob_matrix[x, y]
                if tot > 3:
                    prob_over_35 += prob_matrix[x, y]
                if tot > 4:
                    prob_over_45 += prob_matrix[x, y]
                if tot > 5:
                    prob_over_55 += prob_matrix[x, y]

        prob_btts_yes = float(sum(
            prob_matrix[i, j] for i in range(1, max_goals + 1)
            for j in range(1, max_goals + 1)
        ))

        return {
            'prob_h': prob_h, 'prob_d': prob_d, 'prob_a': prob_a,
            'prob_over_25': prob_over_25, 'prob_under_25': 1.0 - prob_over_25,
            'prob_over_15': prob_over_15, 'prob_under_15': 1.0 - prob_over_15,
            'prob_over_35': prob_over_35, 'prob_under_35': 1.0 - prob_over_35,
            'prob_over_45': prob_over_45, 'prob_under_45': 1.0 - prob_over_45,
            'prob_over_55': prob_over_55, 'prob_under_55': 1.0 - prob_over_55,
            'prob_btts_yes': prob_btts_yes, 'prob_btts_no': 1.0 - prob_btts_yes,
        }

    # ── Main entry point ───────────────────────────────────────────

    def compute_all(self,
                    team_home_scored, team_home_conceded,
                    team_away_scored, team_away_conceded,
                    league_home_goals, league_away_goals,
                    team_home_sot, team_home_sot_conceded,
                    team_away_sot, team_away_sot_conceded,
                    league_home_sot, league_away_sot,
                    team_home_xg, team_home_xg_conceded,
                    team_away_xg, team_away_xg_conceded,
                    league_home_xg, league_away_xg,
                    team_home_scored_ht, team_home_conceded_ht,
                    team_away_scored_ht, team_away_conceded_ht,
                    league_home_goals_ht, league_away_goals_ht,
                    home_team, away_team, league_code, decay,
                    league_rho_cache: dict,
                    league_goals_for_rho: dict,
                    elo_tracker,
                    models_frozen: bool = False) -> MatchProbabilityBundle:
        """Compute all match probabilities.

        This is the single entry point that replaces both:
        - PoissonModel.predict_match()
        - ChronologicalBacktester._compute_match_probabilities()

        Returns a MatchProbabilityBundle with all derived probabilities.
        """
        h_xg_att = 1.0; h_xg_def = 1.0; a_xg_att = 1.0; a_xg_def = 1.0
        lambda_shots_home = None; lambda_shots_away = None
        lambda_xg_home = None; lambda_xg_away = None

        # 1. Goals-based ratings
        (lambda_goals_home, lambda_goals_away,
         h_att, h_def, a_att, a_def,
         avg_h_goals, avg_a_goals) = self._compute_lambda_goals(
            team_home_scored, team_home_conceded,
            team_away_scored, team_away_conceded,
            league_home_goals, league_away_goals,
            home_team, away_team, league_code, decay)

        lambda_home = lambda_goals_home
        lambda_away = lambda_goals_away

        # 2. SOT-based lambda
        lambda_shots_home, lambda_shots_away = self._compute_lambda_sot(
            team_home_sot, team_home_sot_conceded,
            team_away_sot, team_away_sot_conceded,
            league_home_sot, league_away_sot,
            home_team, away_team, league_code, decay,
            avg_h_goals, avg_a_goals)

        has_sot = lambda_shots_home is not None

        # 3. xG-based lambda and multi-tier blending
        if has_sot:
            xg_result = self._compute_lambda_xg(
                team_home_xg, team_home_xg_conceded,
                team_away_xg, team_away_xg_conceded,
                league_home_xg, league_away_xg,
                home_team, away_team, league_code, decay)

            if xg_result is not None:
                (lambda_xg_home, lambda_xg_away,
                 h_xg_att, h_xg_def, a_xg_att, a_xg_def) = xg_result
                # Tier 1: xG 50% + Shots 30% + Goals 20%
                lambda_home = (self.blend_xg * lambda_xg_home +
                               self.blend_sot * lambda_shots_home +
                               self.blend_goals * lambda_goals_home)
                lambda_away = (self.blend_xg * lambda_xg_away +
                               self.blend_sot * lambda_shots_away +
                               self.blend_goals * lambda_goals_away)
            else:
                # Tier 2: Goals 60% + Shots 40%
                lambda_home = (self.blend_no_xg_goals * lambda_goals_home +
                               self.blend_no_xg_sot * lambda_shots_home)
                lambda_away = (self.blend_no_xg_goals * lambda_goals_away +
                               self.blend_no_xg_sot * lambda_shots_away)

            # Apply Elo factor (after blending, before caps)
            elo_factor_h = elo_tracker.get_elo_factor(home_team, away_team)
            elo_factor_a = 2.0 - elo_factor_h
            lambda_home *= elo_factor_h
            lambda_away *= elo_factor_a
        else:
            # Tier 3: Goals only, still apply Elo
            elo_factor_h = elo_tracker.get_elo_factor(home_team, away_team)
            elo_factor_a = 2.0 - elo_factor_h
            lambda_home *= elo_factor_h
            lambda_away *= elo_factor_a

        # 4. Hard caps
        lambda_home = max(self.lambda_cap_low, min(self.lambda_cap_high, lambda_home))
        lambda_away = max(self.lambda_cap_low, min(self.lambda_cap_high, lambda_away))

        # 5. HT lambda
        lambda_home_ht, lambda_away_ht = self._compute_lambda_ht(
            team_home_scored_ht, team_home_conceded_ht,
            team_away_scored_ht, team_away_conceded_ht,
            league_home_goals_ht, league_away_goals_ht,
            home_team, away_team, league_code, decay,
            avg_h_goals, avg_a_goals)
        lambda_home_ht = max(self.lambda_cap_ht_low, min(self.lambda_cap_ht_high, lambda_home_ht))
        lambda_away_ht = max(self.lambda_cap_ht_low * HT_AWAY_FLOOR_FACTOR, min(self.lambda_cap_ht_high, lambda_away_ht))

        # 6. Rho (Dixon-Coles correlation)
        if league_code in league_rho_cache:
            rho = league_rho_cache[league_code]
        else:
            rho_data = league_goals_for_rho[league_code]
            rho = estimate_dynamic_rho(rho_data['h'], rho_data['a'],
                                       rho_data['lh'], rho_data['la'])
            league_rho_cache[league_code] = rho

        # 7. Build score matrix (Poisson or Negative Binomial)
        prob_matrix = self._build_score_matrix(lambda_home, lambda_away, rho)

        # 8. Derive full-time market probabilities
        mkt = self._derive_market_probs(prob_matrix, self.max_goals)

        # 9. HT score matrix and market probabilities
        home_probs_ht = np.array([math.exp(-lambda_home_ht) * (lambda_home_ht ** i) / _FACTORIALS[i]
                                  for i in range(self.max_goals + 1)])
        away_probs_ht = np.array([math.exp(-lambda_away_ht) * (lambda_away_ht ** i) / _FACTORIALS[i]
                                  for i in range(self.max_goals + 1)])
        prob_matrix_ht = np.outer(home_probs_ht, away_probs_ht)

        tau_00_ht = max(0.0, 1.0 - lambda_home_ht * lambda_away_ht * rho)
        tau_10_ht = max(0.0, 1.0 + lambda_away_ht * rho)
        tau_01_ht = max(0.0, 1.0 + lambda_home_ht * rho)
        tau_11_ht = max(0.0, 1.0 - rho)
        prob_matrix_ht[0, 0] *= tau_00_ht
        prob_matrix_ht[1, 0] *= tau_10_ht
        prob_matrix_ht[0, 1] *= tau_01_ht
        prob_matrix_ht[1, 1] *= tau_11_ht
        matrix_sum_ht = prob_matrix_ht.sum()
        if matrix_sum_ht > 0:
            prob_matrix_ht = prob_matrix_ht / matrix_sum_ht

        prob_h_ht = float(np.sum(np.tril(prob_matrix_ht, -1)))
        prob_d_ht = float(np.sum(np.diag(prob_matrix_ht)))
        prob_a_ht = float(np.sum(np.triu(prob_matrix_ht, 1)))
        prob_over_05_ht = 1.0 - float(prob_matrix_ht[0, 0])
        prob_over_15_ht = 0.0
        for x in range(self.max_goals + 1):
            for y in range(self.max_goals + 1):
                if x + y > 1:
                    prob_over_15_ht += prob_matrix_ht[x, y]

        return MatchProbabilityBundle(
            lambda_home=lambda_home,
            lambda_away=lambda_away,
            lambda_goals_home=lambda_goals_home,
            lambda_goals_away=lambda_goals_away,
            lambda_shots_home=lambda_shots_home,
            lambda_shots_away=lambda_shots_away,
            lambda_xg_home=lambda_xg_home,
            lambda_xg_away=lambda_xg_away,
            lambda_home_ht=lambda_home_ht,
            lambda_away_ht=lambda_away_ht,
            h_att=h_att, h_def=h_def,
            a_att=a_att, a_def=a_def,
            h_xg_att=h_xg_att, h_xg_def=h_xg_def,
            a_xg_att=a_xg_att, a_xg_def=a_xg_def,
            elo_factor_h=elo_factor_h, elo_factor_a=elo_factor_a,
            prob_matrix=prob_matrix,
            prob_h=mkt['prob_h'], prob_d=mkt['prob_d'], prob_a=mkt['prob_a'],
            prob_over_25=mkt['prob_over_25'], prob_over_15=mkt['prob_over_15'],
            prob_over_35=mkt['prob_over_35'], prob_over_45=mkt['prob_over_45'],
            prob_over_55=mkt['prob_over_55'],
            prob_btts_yes=mkt['prob_btts_yes'],
            prob_matrix_ht=prob_matrix_ht,
            prob_h_ht=prob_h_ht, prob_d_ht=prob_d_ht, prob_a_ht=prob_a_ht,
            prob_over_05_ht=prob_over_05_ht, prob_over_15_ht=prob_over_15_ht,
            max_goals=self.max_goals,
            rho=rho, avg_h_goals=avg_h_goals, avg_a_goals=avg_a_goals,
        )

    # ── Simplified interface for dutching_scanner and other callers ─

    def compute_score_matrix(self, lambda_home: float, lambda_away: float,
                             rho: Optional[float] = None) -> np.ndarray:
        """Build just the score matrix for given lambdas — used by dutching_scanner.

        This replaces compute_nb_score_matrix() from models.py for Negative Binomial,
        and the inline Poisson matrix in dutching_scanner for Poisson.
        """
        if rho is None:
            rho = RHO_FALLBACK
        return self._build_score_matrix(lambda_home, lambda_away, rho)


# ── Standalone helpers ──────────────────────────────────────────────

def build_form_state_from_df(historical_df, match_date):
    """Build chronological form state dicts from historical data for use with ProbabilityPipeline.

    Iterates all matches BEFORE target_date chronologically, populating the same
    state dictionaries the engine uses. Returns a dict suitable for pipeline.compute_all().

    Moved from PoissonModel._build_form_state_from_df() in models.py.
    """
    from collections import defaultdict
    df = historical_df.copy()
    df['Date'] = pd.to_datetime(df['Date'], format='mixed', dayfirst=True)
    target_dt = pd.to_datetime(match_date)
    prior = df[df['Date'] < target_dt].sort_values('Date')

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
    lge_h_goals = defaultdict(list)
    lge_a_goals = defaultdict(list)
    lge_h_sot = defaultdict(list)
    lge_a_sot = defaultdict(list)
    lge_h_xg = defaultdict(list)
    lge_a_xg = defaultdict(list)
    lge_h_goals_ht = defaultdict(list)
    lge_a_goals_ht = defaultdict(list)

    for _, row in prior.iterrows():
        ht = row.get('HomeTeam', '')
        at = row.get('AwayTeam', '')
        fthg = row.get('FTHG')
        ftag = row.get('FTAG')
        if pd.isna(fthg) or pd.isna(ftag):
            continue
        fthg, ftag = float(fthg), float(ftag)

        team_h_scored[ht].append(fthg)
        team_h_conceded[ht].append(ftag)
        team_a_scored[at].append(ftag)
        team_a_conceded[at].append(fthg)
        lge_h_goals['all'].append(fthg)
        lge_a_goals['all'].append(ftag)

        hst = row.get('HST')
        ast_val = row.get('AST')
        if not pd.isna(hst) and not pd.isna(ast_val):
            hst, ast_val = float(hst), float(ast_val)
            team_h_sot[ht].append(hst)
            team_h_sot_conc[ht].append(ast_val)
            team_a_sot[at].append(ast_val)
            team_a_sot_conc[at].append(hst)
            lge_h_sot['all'].append(hst)
            lge_a_sot['all'].append(ast_val)

        hxg = row.get('HomeXG')
        axg = row.get('AwayXG')
        if not pd.isna(hxg) and not pd.isna(axg):
            hxg, axg = float(hxg), float(axg)
            team_h_xg[ht].append(hxg)
            team_h_xg_conc[ht].append(axg)
            team_a_xg[at].append(axg)
            team_a_xg_conc[at].append(hxg)
            lge_h_xg['all'].append(hxg)
            lge_a_xg['all'].append(axg)

        hthg = row.get('HTHG')
        htag = row.get('HTAG')
        if not pd.isna(hthg) and not pd.isna(htag):
            hthg, htag = float(hthg), float(htag)
            team_h_scored_ht[ht].append(hthg)
            team_h_conceded_ht[ht].append(htag)
            team_a_scored_ht[at].append(htag)
            team_a_conceded_ht[at].append(hthg)
            lge_h_goals_ht['all'].append(hthg)
            lge_a_goals_ht['all'].append(htag)

    return {
        'team_h_scored': team_h_scored, 'team_h_conceded': team_h_conceded,
        'team_a_scored': team_a_scored, 'team_a_conceded': team_a_conceded,
        'team_h_sot': team_h_sot, 'team_h_sot_conc': team_h_sot_conc,
        'team_a_sot': team_a_sot, 'team_a_sot_conc': team_a_sot_conc,
        'team_h_xg': team_h_xg, 'team_h_xg_conc': team_h_xg_conc,
        'team_a_xg': team_a_xg, 'team_a_xg_conc': team_a_xg_conc,
        'team_h_scored_ht': team_h_scored_ht, 'team_h_conceded_ht': team_h_conceded_ht,
        'team_a_scored_ht': team_a_scored_ht, 'team_a_conceded_ht': team_a_conceded_ht,
        'lge_h_goals': lge_h_goals, 'lge_a_goals': lge_a_goals,
        'lge_h_sot': lge_h_sot, 'lge_a_sot': lge_a_sot,
        'lge_h_xg': lge_h_xg, 'lge_a_xg': lge_a_xg,
        'lge_h_goals_ht': lge_h_goals_ht, 'lge_a_goals_ht': lge_a_goals_ht,
    }


def predict_match_nb(home_team: str, away_team: str, historical_df,
                     match_date, elo_tracker=None) -> dict:
    """Convenience function for Dutching CS scanner.

    Builds form state from a DataFrame, runs the unified pipeline with
    Negative Binomial (NB2) model, and returns a dict with all probabilities.

    Replaces: PoissonModel.predict_match() + _apply_negative_binomial().
    """
    from collections import defaultdict
    from .elo_model import EloTracker
    from .backtest.helpers import get_league_weighted_decay

    state = build_form_state_from_df(historical_df, match_date)

    if elo_tracker is None:
        elo_tracker = EloTracker()

    pipeline = ProbabilityPipeline(model_type=MODEL_NEGATIVE_BINOMIAL)
    league_code = 'all'
    decay = get_league_weighted_decay(league_code)
    league_rho_cache = {}
    league_goals_for_rho = defaultdict(lambda: {'h': [], 'a': [], 'lh': [], 'la': []})

    bundle = pipeline.compute_all(
        state['team_h_scored'], state['team_h_conceded'],
        state['team_a_scored'], state['team_a_conceded'],
        state['lge_h_goals'], state['lge_a_goals'],
        state['team_h_sot'], state['team_h_sot_conc'],
        state['team_a_sot'], state['team_a_sot_conc'],
        state['lge_h_sot'], state['lge_a_sot'],
        state['team_h_xg'], state['team_h_xg_conc'],
        state['team_a_xg'], state['team_a_xg_conc'],
        state['lge_h_xg'], state['lge_a_xg'],
        state['team_h_scored_ht'], state['team_h_conceded_ht'],
        state['team_a_scored_ht'], state['team_a_conceded_ht'],
        state['lge_h_goals_ht'], state['lge_a_goals_ht'],
        home_team, away_team, league_code, decay,
        league_rho_cache, league_goals_for_rho, elo_tracker,
    )
    return bundle.to_dict()
