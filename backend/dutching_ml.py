"""
Dutching ML Ensemble — XGBoost-boosted score group probabilities.

Trains 3 binary XGBoost classifiers to adjust Poisson/NB score probabilities:
- CS_Under_Bias: P(actual score ∈ under group)
- CS_Over_Bias:  P(actual score ∈ over group)
- CS_Draw_Bias:  P(actual score ∈ draw group)

Each classifier predicts whether the real score falls into the group,
using 12 features from the Poisson/NB model. The output is blended 50/50
with the NB model — the ML adjusts the group-level bias while the NB
preserves the within-group correlation structure.

Architecture:
- Offline: train_from_history() trains models on historical data
- Online: adjust_score_matrix() applies ML correction to prob_matrix
- Persistence: save_models() / load_models() via pickle
"""

import os
import pickle
import logging
import numpy as np

logger = logging.getLogger(__name__)

from xgboost import XGBClassifier
from sklearn.isotonic import IsotonicRegression

# Score groups for classification targets
UNDER_SCORES = {'0-0', '1-0', '0-1', '2-0', '0-2', '1-1'}
OVER_SCORES = {'2-1', '1-2', '3-0', '0-3', '3-1', '1-3', '2-2',
               '3-2', '2-3', '4-0', '0-4', '4-1', '1-4', '3-3'}
DRAW_SCORES = {'0-0', '1-1', '2-2', '3-3'}

# Default features
FEATURE_NAMES = [
    'lambda_home', 'lambda_away', 'prob_h', 'prob_d', 'prob_a',
    'prob_over_25', 'prob_under_25', 'lambda_total', 'lambda_ratio',
    'h_att', 'h_def', 'a_att', 'a_def',
]


def _extract_features(pred: dict) -> np.ndarray:
    """Extract 13 features from prediction dict for ML input."""
    lam_h = pred.get('lambda_home', 1.2)
    lam_a = pred.get('lambda_away', 1.0)
    features = np.array([
        lam_h,
        lam_a,
        pred.get('prob_h', 0.37),
        pred.get('prob_d', 0.26),
        pred.get('prob_a', 0.37),
        pred.get('prob_over_25', 0.5),
        pred.get('prob_under_25', 0.5),
        lam_h + lam_a,
        lam_h / max(lam_a, 0.1),
        pred.get('h_att', 1.0),
        pred.get('h_def', 1.0),
        pred.get('a_att', 1.0),
        pred.get('a_def', 1.0),
    ], dtype=float)
    return features


def _score_in_group(score_str, group):
    """Check if a score belongs to a group."""
    return 1 if score_str in group else 0


class ScoreGroupClassifier:
    """Single binary XGBoost classifier for one score group."""

    def __init__(self, group_name: str, group_scores: set):
        self.group_name = group_name
        self.group_scores = group_scores
        self.model = XGBClassifier(
            n_estimators=150, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=20,
            eval_metric='logloss', verbosity=0, n_jobs=1,
        )
        self.calibrator = IsotonicRegression(out_of_bounds='clip')
        self.is_fitted = False
        self.n_trained = 0
        self.feature_importance = None

    def fit(self, X, y):
        """Train classifier and calibrator. Requires >= 200 samples."""
        if len(X) < 200 or len(set(y)) < 2:
            return False
        X_arr = np.array(X, dtype=float)
        y_arr = np.array(y, dtype=int)

        self.model.fit(X_arr, y_arr)
        raw_probs = self.model.predict_proba(X_arr)[:, 1]
        self.calibrator.fit(raw_probs, y_arr)
        self.is_fitted = True
        self.n_trained = len(X)
        self.feature_importance = dict(zip(
            FEATURE_NAMES,
            self.model.feature_importances_.tolist()
        ))
        return True

    def predict_proba(self, features):
        """Return calibrated probability that score belongs to this group."""
        if not self.is_fitted:
            return None
        X_arr = np.array([features], dtype=float)
        raw = float(self.model.predict_proba(X_arr)[0, 1])
        try:
            calibrated = float(self.calibrator.predict(np.array([raw]))[0])
            return np.clip(calibrated, 0.001, 0.999)
        except Exception:
            return raw


class DutchingMLEnsemble:
    """Ensemble of 3 binary classifiers for score group bias correction."""

    def __init__(self):
        self.classifiers = {
            'under': ScoreGroupClassifier('under', UNDER_SCORES),
            'over': ScoreGroupClassifier('over', OVER_SCORES),
            'draw': ScoreGroupClassifier('draw', DRAW_SCORES),
        }
        self.fitted = False

    def train(self, historical_df):
        """Train all 3 classifiers from historical match data.

        Args:
            historical_df: DataFrame with at least: HomeTeam, AwayTeam,
                FTHG, FTAG, and columns from ProbabilityPipeline output
                (lambda_home, lambda_away, prob_h, etc.)
        """
        X_data = {'under': [], 'over': [], 'draw': []}
        y_data = {'under': [], 'over': [], 'draw': []}

        # Use the existing predict_match_nb but we need features per match
        # For efficiency, iterate through matches and collect features
        from .probability_pipeline import build_form_state_from_df, ProbabilityPipeline, MODEL_NEGATIVE_BINOMIAL
        from .elo_model import EloTracker
        from .backtest.helpers import get_league_weighted_decay
        from collections import defaultdict

        hist = historical_df.copy()
        if 'Date' in hist.columns:
            hist['Date'] = pd.to_datetime(hist['Date'], format='mixed', dayfirst=True)
            hist = hist.sort_values('Date')

        pipeline = ProbabilityPipeline(model_type=MODEL_NEGATIVE_BINOMIAL)
        elo_tracker = EloTracker()
        league_code = 'all'
        decay = get_league_weighted_decay(league_code)
        league_rho_cache = {}
        league_goals_for_rho = defaultdict(lambda: {'h': [], 'a': [], 'lh': [], 'la': []})

        # Team form state (walk-forward)
        team_h_scored = defaultdict(list)
        team_h_conc = defaultdict(list)
        team_a_scored = defaultdict(list)
        team_a_conc = defaultdict(list)
        # minimal state for pipeline
        team_h_sot = defaultdict(list); team_h_sot_c = defaultdict(list)
        team_a_sot = defaultdict(list); team_a_sot_c = defaultdict(list)
        team_h_xg = defaultdict(list); team_h_xg_c = defaultdict(list)
        team_a_xg = defaultdict(list); team_a_xg_c = defaultdict(list)
        team_h_ht_sc = defaultdict(list); team_h_ht_c = defaultdict(list)
        team_a_ht_sc = defaultdict(list); team_a_ht_c = defaultdict(list)
        lge_h_goals = defaultdict(list); lge_a_goals = defaultdict(list)
        lge_h_sot = defaultdict(list); lge_a_sot = defaultdict(list)
        lge_h_xg = defaultdict(list); lge_a_xg = defaultdict(list)
        lge_h_ht = defaultdict(list); lge_a_ht = defaultdict(list)

        trained = 0
        for _, row in hist.iterrows():
            home = row.get('HomeTeam', '')
            away = row.get('AwayTeam', '')
            fthg = row.get('FTHG')
            ftag = row.get('FTAG')
            if pd.isna(fthg) or pd.isna(ftag) or not home or not away:
                continue
            fthg, ftag = int(fthg), int(ftag)
            score_str = f"{fthg}-{ftag}"

            # Compute prediction from current state (no look-ahead)
            try:
                bundle = pipeline.compute_all(
                    team_h_scored, team_h_conc, team_a_scored, team_a_conc,
                    lge_h_goals, lge_a_goals,
                    team_h_sot, team_h_sot_c, team_a_sot, team_a_sot_c,
                    lge_h_sot, lge_a_sot,
                    team_h_xg, team_h_xg_c, team_a_xg, team_a_xg_c,
                    lge_h_xg, lge_a_xg,
                    team_h_ht_sc, team_h_ht_c, team_a_ht_sc, team_a_ht_c,
                    lge_h_ht, lge_a_ht,
                    home, away, league_code, decay,
                    league_rho_cache, league_goals_for_rho, elo_tracker,
                )
                pred = bundle.to_dict()
                pred['h_att'] = bundle.h_att
                pred['h_def'] = bundle.h_def
                pred['a_att'] = bundle.a_att
                pred['a_def'] = bundle.a_def

                features = _extract_features(pred)

                for group_name in ['under', 'over', 'draw']:
                    X_data[group_name].append(features.tolist())
                    y_data[group_name].append(_score_in_group(score_str, self.classifiers[group_name].group_scores))

                trained += 1
            except Exception:
                pass

            # Update form AFTER prediction
            _update_minimal_state(
                team_h_scored, team_h_conc, team_a_scored, team_a_conc,
                lge_h_goals, lge_a_goals, home, away, fthg, ftag,
                team_h_sot, team_h_sot_c, team_a_sot, team_a_sot_c,
                lge_h_sot, lge_a_sot, row,
                team_h_xg, team_h_xg_c, team_a_xg, team_a_xg_c,
                lge_h_xg, lge_a_xg, row,
                team_h_ht_sc, team_h_ht_c, team_a_ht_sc, team_a_ht_c,
                lge_h_ht, lge_a_ht, row,
            )
            elo_tracker.update(home, away, fthg, ftag)
            # Update rho data
            rho_d = league_goals_for_rho[league_code]
            rho_d['h'].append(fthg); rho_d['a'].append(ftag)
            rho_d['lh'].append(float(fthg)); rho_d['la'].append(float(ftag))

        # Fit classifiers
        fitted_count = 0
        for group_name in ['under', 'over', 'draw']:
            clf = self.classifiers[group_name]
            if clf.fit(X_data[group_name], y_data[group_name]):
                fitted_count += 1
                logger.info(f"[DutchingML] {group_name}: fitted on {clf.n_trained} samples. "
                           f"Top features: {sorted(clf.feature_importance.items(), key=lambda x: -x[1])[:4]}")

        self.fitted = fitted_count >= 1
        logger.info(f"[DutchingML] Trained {fitted_count}/3 classifiers on {trained} matches")
        return self.fitted

    def adjust_score_matrix(self, prob_matrix, pred, max_goals=8):
        """Apply ML group bias correction to NB score matrix.

        Returns adjusted matrix with ML-corrected group probabilities.
        If models aren't fitted, returns original matrix unchanged.
        """
        if not self.fitted:
            return prob_matrix

        features = _extract_features(pred)

        # Get ML group probabilities
        ml_probs = {}
        nb_group_probs = {}
        for group_name in ['under', 'over', 'draw']:
            ml_p = self.classifiers[group_name].predict_proba(features)
            if ml_p is None:
                return prob_matrix  # model not ready
            ml_probs[group_name] = ml_p

            # Compute NB model's implied group probability
            nb_p = 0.0
            for score_str in self.classifiers[group_name].group_scores:
                try:
                    hg, ag = map(int, score_str.split('-'))
                    if hg <= max_goals and ag <= max_goals:
                        nb_p += prob_matrix[hg, ag]
                except (ValueError, IndexError):
                    pass
            nb_group_probs[group_name] = max(0.001, nb_p)

        # Blend: 50% NB + 50% ML-adjusted
        blend_weight = 0.5
        adj_matrix = prob_matrix.copy()

        for group_name in ['under', 'over', 'draw']:
            nb_p = nb_group_probs[group_name]
            ml_p = ml_probs[group_name]
            if nb_p <= 0:
                continue
            # Correction factor
            factor = (blend_weight * ml_p + (1 - blend_weight) * nb_p) / nb_p
            factor = max(0.3, min(3.0, factor))  # sanity cap

            for score_str in self.classifiers[group_name].group_scores:
                try:
                    hg, ag = map(int, score_str.split('-'))
                    if hg <= max_goals and ag <= max_goals:
                        adj_matrix[hg, ag] *= factor
                except (ValueError, IndexError):
                    pass

        # Renormalize
        total = adj_matrix.sum()
        if total > 0:
            adj_matrix = adj_matrix / total

        return adj_matrix

    def save(self, path):
        """Persist trained models to disk."""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump(self, f)
        logger.info(f"[DutchingML] Models saved to {path}")

    @staticmethod
    def load(path):
        """Load trained models from disk."""
        with open(path, 'rb') as f:
            return pickle.load(f)

    def get_diagnostics(self):
        """Return model status for each classifier."""
        diag = {}
        for name, clf in self.classifiers.items():
            diag[name] = {
                'fitted': clf.is_fitted,
                'n_trained': clf.n_trained,
                'top_features': (sorted(clf.feature_importance.items(), key=lambda x: -x[1])[:3]
                                 if clf.feature_importance else []),
            }
        return diag


def _update_minimal_state(th_s, th_c, ta_s, ta_c, lh_g, la_g, home, away, fthg, ftag,
                          th_sot, th_sot_c, ta_sot, ta_sot_c, lh_sot, la_sot, row,
                          th_xg, th_xg_c, ta_xg, ta_xg_c, lh_xg, la_xg, row_xg,
                          th_ht_s, th_ht_c, ta_ht_s, ta_ht_c, lh_ht, la_ht, row_ht):
    """Minimal form update after each match (no look-ahead)."""
    th_s[home].append(fthg); th_c[home].append(ftag)
    ta_s[away].append(ftag); ta_c[away].append(fthg)
    lh_g['all'].append(fthg); la_g['all'].append(ftag)

    hst = row.get('HST'); ast = row.get('AST')
    if not pd.isna(hst) and not pd.isna(ast):
        th_sot[home].append(hst); th_sot_c[home].append(ast)
        ta_sot[away].append(ast); ta_sot_c[away].append(hst)
        lh_sot['all'].append(hst); la_sot['all'].append(ast)

    hxg = row.get('HomeXG'); axg = row.get('AwayXG')
    if not pd.isna(hxg) and not pd.isna(axg):
        th_xg[home].append(hxg); th_xg_c[home].append(axg)
        ta_xg[away].append(axg); ta_xg_c[away].append(hxg)
        lh_xg['all'].append(hxg); la_xg['all'].append(axg)

    hthg = row.get('HTHG'); htag = row.get('HTAG')
    if not pd.isna(hthg) and not pd.isna(htag):
        th_ht_s[home].append(hthg); th_ht_c[home].append(htag)
        ta_ht_s[away].append(htag); ta_ht_c[away].append(hthg)
        lh_ht['all'].append(hthg); la_ht['all'].append(htag)


import pandas as pd
