import pandas as pd
import numpy as np
import math
from typing import Optional
from scipy.stats import nbinom
from .elo_model import estimate_dynamic_rho
from .constants import (
    RHO_FALLBACK, NB_ALPHA_HOME, NB_ALPHA_AWAY,
    SHRINKAGE_FT, RATING_CAP_LOW, RATING_CAP_HIGH,
    TIME_DECAY_XI, MAX_GOALS, RHO_MLE_MIN_MATCHES,
)

def find_best_team_match(api_name, historical_teams):
    if not api_name or not historical_teams:
        return api_name
    api_name_lower = api_name.lower().strip()
    
    # 1. Direct match (Fast Path)
    if api_name in historical_teams:
        return api_name
        
    # 2. Check for lowercase direct match
    for team in historical_teams:
        if team.lower().strip() == api_name_lower:
            return team
            
    # 3. Clean common suffixes to compare substring or do quick match
    suffixes = [' fc', ' united', ' utd', ' city', ' town', ' athletic', ' club', ' de ']
    clean_api = api_name_lower
    for s in suffixes:
        clean_api = clean_api.replace(s, '')
    clean_api = clean_api.strip()
    
    if not clean_api:
        return api_name
        
    # Check if a clean match exists
    for team in historical_teams:
        team_lower = team.lower()
        clean_team = team_lower
        for s in suffixes:
            clean_team = clean_team.replace(s, '')
        clean_team = clean_team.strip()
        if clean_api == clean_team or clean_api in clean_team or clean_team in clean_api:
            return team
            
    # 4. Fuzzy Match with difflib (stdlib — no external dependency)
    try:
        import difflib
        cleaned_historical = []
        team_map = {}
        for team in historical_teams:
            clean_t = team.lower()
            for s in suffixes:
                clean_t = clean_t.replace(s, '')
            clean_t = clean_t.strip()
            cleaned_historical.append(clean_t)
            team_map[clean_t] = team

        matches = difflib.get_close_matches(clean_api, cleaned_historical, n=1, cutoff=0.85)
        if matches:
            return team_map[matches[0]]
    except Exception:
        pass
        
    # Default fallback
    return api_name

def calculate_ah_probabilities(prob_matrix, line):
    """
    Given a bivariate Poisson probability matrix (prob_matrix) and an Asian Handicap line for the Home team,
    returns the exact probability of Win, Half-Win, Push, Half-Loss, and Loss.
    """
    prob_win = 0.0
    prob_half_win = 0.0
    prob_push = 0.0
    prob_half_loss = 0.0
    prob_loss = 0.0
    
    for x in range(prob_matrix.shape[0]):
        for y in range(prob_matrix.shape[1]):
            prob = prob_matrix[x, y]
            if prob == 0: continue
            
            margin = x - y
            score = margin + line
            
            # Using a tiny epsilon to prevent float rounding issues
            if score > 0.24:
                prob_win += prob
            elif 0.10 < score <= 0.25:
                prob_half_win += prob
            elif -0.10 <= score <= 0.10:
                prob_push += prob
            elif -0.25 <= score < -0.10:
                prob_half_loss += prob
            elif score < -0.24:
                prob_loss += prob
                
    return {
        'win': prob_win,
        'half_win': prob_half_win,
        'push': prob_push,
        'half_loss': prob_half_loss,
        'loss': prob_loss
    }

def get_fair_ah_odds(ah_probs):
    """
    Calculates the exact Fair Odds (EV=0) for an Asian Handicap outcome based on its component probabilities.
    Formula: O = (P_win + 0.5 * P_half_win + 0.5 * P_half_loss + P_loss) / (P_win + 0.5 * P_half_win)
    """
    prob_win = ah_probs['win']
    prob_half_win = ah_probs['half_win']
    prob_half_loss = ah_probs['half_loss']
    prob_loss = ah_probs['loss']
    
    denominator = prob_win + 0.5 * prob_half_win
    if denominator <= 0:
        return 99.0
        
    numerator = prob_win + 0.5 * prob_half_win + 0.5 * prob_half_loss + prob_loss
    odds = numerator / denominator
    return float(max(1.01, min(99.0, odds)))


def compute_nb_score_matrix(lambda_home, lambda_away, alpha_home=NB_ALPHA_HOME, alpha_away=NB_ALPHA_AWAY, max_goals=MAX_GOALS, rho=RHO_FALLBACK):
    """
    Negative Binomial score matrix with Dixon-Coles correction.
    NB2 parameterization: Var = mu + alpha * mu^2 (accounts for overdispersion).
    Uses scipy.stats.nbinom — no extra dependencies needed.

    Default alpha values from football analytics literature:
    - Home dispersion ~0.10-0.20 (higher: more unpredictable at home)
    - Away dispersion ~0.08-0.15 (lower: more consistent on the road)

    Returns: (prob_matrix, home_margin, away_margin)
    """
    # NB2 → scipy nbinom parameterization
    # n = 1/alpha, p = 1/(1 + alpha*mu)
    def nb_pmf(k, mu, alpha):
        if alpha <= 0:
            # Degenerate case: alpha=0 → Poisson
            return math.exp(-mu) * (mu ** k) / math.factorial(k)
        n_param = 1.0 / alpha
        p_param = 1.0 / (1.0 + alpha * mu)
        return nbinom.pmf(k, n_param, p_param)

    home_probs = np.array([nb_pmf(i, lambda_home, alpha_home) for i in range(max_goals + 1)])
    away_probs = np.array([nb_pmf(i, lambda_away, alpha_away) for i in range(max_goals + 1)])

    # Normalize (truncation at max_goals)
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

    prob_sum = prob_matrix.sum()
    if prob_sum > 0:
        prob_matrix = prob_matrix / prob_sum

    home_margin = float(np.sum(np.tril(prob_matrix, -1)))
    away_margin = float(np.sum(np.triu(prob_matrix, 1)))

    return prob_matrix, home_margin, away_margin


class PoissonModel:
    def __init__(self, rolling_window_days=365, min_matches=10, decay_xi=TIME_DECAY_XI):
        self.rolling_window_days = rolling_window_days
        self.min_matches = min_matches
        self.decay_xi = decay_xi

    @staticmethod
    def _build_form_state_from_df(historical_df, match_date):
        """Delegate to standalone function in probability_pipeline.py."""
        from .probability_pipeline import build_form_state_from_df
        return build_form_state_from_df(historical_df, match_date)

    def compute_team_ratings(self, historical_df, target_date):
        """
        Computes rolling attack and defense ratings for all teams based on matches
        played BEFORE target_date, applying exponential time decay.
        """
        # Filter matches before target date and within rolling window
        target_dt = pd.to_datetime(target_date)
        window_start = target_dt - pd.Timedelta(days=self.rolling_window_days)
        
        mask = (historical_df['Date'] < target_dt) & (historical_df['Date'] >= window_start)
        recent_matches = historical_df[mask].copy()
        
        if len(recent_matches) < self.min_matches:
            # If not enough matches in the league yet, return empty ratings (regressed to average)
            return {}, {}, 1.0, 1.0
            
        # Compute exponential time decay weights
        days_diff = (target_dt - recent_matches['Date']).dt.days
        recent_matches['Weight'] = np.exp(-self.decay_xi * days_diff)
        
        weight_sum = recent_matches['Weight'].sum()
        
        # Calculate weighted league averages
        avg_home_goals = (recent_matches['FTHG'] * recent_matches['Weight']).sum() / weight_sum
        avg_away_goals = (recent_matches['FTAG'] * recent_matches['Weight']).sum() / weight_sum
        
        # Avoid division by zero
        if pd.isna(avg_home_goals) or avg_home_goals == 0: avg_home_goals = 1.3
        if pd.isna(avg_away_goals) or avg_away_goals == 0: avg_away_goals = 1.0
        
        def weighted_avg(group, col):
            w = group['Weight']
            w_sum = w.sum()
            if w_sum == 0: return group[col].mean()
            return (group[col] * w).sum() / w_sum

        # Calculate goals scored and conceded by team
        home_grouped = recent_matches.groupby('HomeTeam')
        away_grouped = recent_matches.groupby('AwayTeam')
        
        # Home team offensive strength: avg goals scored / league avg goals scored at home
        home_att_raw = {team: weighted_avg(group, 'FTHG') / avg_home_goals for team, group in home_grouped}
        # Home team defensive strength: avg goals conceded / league avg goals conceded at home
        home_def_raw = {team: weighted_avg(group, 'FTAG') / avg_away_goals for team, group in home_grouped}
        
        # Away team offensive strength: avg goals scored / league avg goals scored away
        away_att_raw = {team: weighted_avg(group, 'FTAG') / avg_away_goals for team, group in away_grouped}
        # Away team defensive strength: avg goals conceded / league avg goals conceded away
        away_def_raw = {team: weighted_avg(group, 'FTHG') / avg_home_goals for team, group in away_grouped}
        
        # Apply Shrinkage (Regression to the mean) and Caps
        def shrink_and_cap(ratings_dict):
            return {team: max(RATING_CAP_LOW, min(RATING_CAP_HIGH, SHRINKAGE_FT * val + (1.0 - SHRINKAGE_FT) * 1.0)) for team, val in ratings_dict.items()}
            
        home_att = shrink_and_cap(home_att_raw)
        home_def = shrink_and_cap(home_def_raw)
        away_att = shrink_and_cap(away_att_raw)
        away_def = shrink_and_cap(away_def_raw)
        
        return home_att, home_def, away_att, away_def, avg_home_goals, avg_away_goals

    def compute_sot_ratings(self, historical_df, target_date):
        """
        Computes rolling attack and defense SOT ratings for all teams based on matches
        played BEFORE target_date, applying exponential time decay.
        """
        if 'HST' not in historical_df.columns or 'AST' not in historical_df.columns:
            return None
            
        target_dt = pd.to_datetime(target_date)
        window_start = target_dt - pd.Timedelta(days=self.rolling_window_days)
        
        mask = (historical_df['Date'] < target_dt) & (historical_df['Date'] >= window_start)
        recent_matches = historical_df[mask].dropna(subset=['HST', 'AST']).copy()
        
        if len(recent_matches) < self.min_matches:
            return None
            
        # Compute exponential time decay weights
        days_diff = (target_dt - recent_matches['Date']).dt.days
        recent_matches['Weight'] = np.exp(-self.decay_xi * days_diff)
        
        weight_sum = recent_matches['Weight'].sum()
        
        avg_home_sot = (recent_matches['HST'] * recent_matches['Weight']).sum() / weight_sum
        avg_away_sot = (recent_matches['AST'] * recent_matches['Weight']).sum() / weight_sum
        
        if pd.isna(avg_home_sot) or avg_home_sot == 0: avg_home_sot = 4.5
        if pd.isna(avg_away_sot) or avg_away_sot == 0: avg_away_sot = 3.5
        
        def weighted_avg(group, col):
            w = group['Weight']
            w_sum = w.sum()
            if w_sum == 0: return group[col].mean()
            return (group[col] * w).sum() / w_sum

        home_grouped = recent_matches.groupby('HomeTeam')
        away_grouped = recent_matches.groupby('AwayTeam')
        
        home_sot_att_raw = {team: weighted_avg(group, 'HST') / avg_home_sot for team, group in home_grouped}
        home_sot_def_raw = {team: weighted_avg(group, 'AST') / avg_away_sot for team, group in home_grouped}
        
        away_sot_att_raw = {team: weighted_avg(group, 'AST') / avg_away_sot for team, group in away_grouped}
        away_sot_def_raw = {team: weighted_avg(group, 'HST') / avg_home_sot for team, group in away_grouped}
        
        def shrink_and_cap(ratings_dict):
            return {team: max(RATING_CAP_LOW, min(RATING_CAP_HIGH, SHRINKAGE_FT * val + (1.0 - SHRINKAGE_FT) * 1.0)) for team, val in ratings_dict.items()}
            
        home_sot_att = shrink_and_cap(home_sot_att_raw)
        home_sot_def = shrink_and_cap(home_sot_def_raw)
        away_sot_att = shrink_and_cap(away_sot_att_raw)
        away_sot_def = shrink_and_cap(away_sot_def_raw)
        
        return {
            'home_sot_att': home_sot_att,
            'home_sot_def': home_sot_def,
            'away_sot_att': away_sot_att,
            'away_sot_def': away_sot_def,
            'avg_home_sot': avg_home_sot,
            'avg_away_sot': avg_away_sot
        }

    def predict_match(self, home_team, away_team, historical_df, match_date,
                      elo_tracker=None, home_xg=None, away_xg=None,
                      use_unified_pipeline=True):
        """
        Predicts match outcome probabilities (1X2, Over/Under, BTTS) using a Poisson model.

        When use_unified_pipeline=True (default), delegates to ProbabilityPipeline for
        consistent xG/SOT/Goals multi-tier blending, dynamic rho, Elo, and HT probabilities.
        The legacy time-decay path (use_unified_pipeline=False) is preserved for backward compat.
        """
        if use_unified_pipeline and home_xg is None:
            return self._predict_via_pipeline(home_team, away_team, historical_df, match_date, elo_tracker)

        # ── Legacy path (time-decay, no xG/NB/HT support) ──────────────
        import warnings
        warnings.warn(
            "PoissonModel.predict_match() legacy path (use_unified_pipeline=False) is deprecated. "
            "Use ProbabilityPipeline.compute_all() directly.",
            DeprecationWarning, stacklevel=2
        )
        if home_xg is not None and away_xg is not None and not np.isnan(home_xg) and not np.isnan(away_xg):
            lambda_home = home_xg
            lambda_away = away_xg
        else:
            home_att, home_def, away_att, away_def, avg_home_goals, avg_away_goals = \
                self.compute_team_ratings(historical_df, match_date)
                
            # Match team names to historical records to avoid nans/defaults
            historical_teams = set(historical_df['HomeTeam'].dropna().unique()) | set(historical_df['AwayTeam'].dropna().unique())
            matched_home = find_best_team_match(home_team, historical_teams)
            matched_away = find_best_team_match(away_team, historical_teams)
                
            # Attack and defense ratings with Bayesian shrinkage (regressed to 1.0 if not enough data)
            h_att = home_att.get(matched_home, 1.0)
            h_def = home_def.get(matched_home, 1.0)
            a_att = away_att.get(matched_away, 1.0)
            a_def = away_def.get(matched_away, 1.0)
            
            # Handle nan values
            if np.isnan(h_att): h_att = 1.0
            if np.isnan(h_def): h_def = 1.0
            if np.isnan(a_att): a_att = 1.0
            if np.isnan(a_def): a_def = 1.0
            
            # Calculate expected goals (lambda)
            lambda_home = avg_home_goals * h_att * a_def
            lambda_away = avg_away_goals * a_att * h_def
            
            # Blend SOT expected goals if shot data is available
            sot_ratings = self.compute_sot_ratings(historical_df, match_date)
            if sot_ratings:
                h_sot_att = sot_ratings['home_sot_att'].get(matched_home, 1.0)
                h_sot_def = sot_ratings['home_sot_def'].get(matched_home, 1.0)
                a_sot_att = sot_ratings['away_sot_att'].get(matched_away, 1.0)
                a_sot_def = sot_ratings['away_sot_def'].get(matched_away, 1.0)
                
                if np.isnan(h_sot_att): h_sot_att = 1.0
                if np.isnan(h_sot_def): h_sot_def = 1.0
                if np.isnan(a_sot_att): a_sot_att = 1.0
                if np.isnan(a_sot_def): a_sot_def = 1.0
                
                avg_home_sot = sot_ratings['avg_home_sot']
                avg_away_sot = sot_ratings['avg_away_sot']
                
                exp_sot_home = avg_home_sot * h_sot_att * a_sot_def
                exp_sot_away = avg_away_sot * a_sot_att * h_sot_def
                
                conversion_home = avg_home_goals / avg_home_sot
                conversion_away = avg_away_goals / avg_away_sot
                
                lambda_shots_home = exp_sot_home * conversion_home
                lambda_shots_away = exp_sot_away * conversion_away
                
                lambda_shots_home = max(0.1, min(5.0, lambda_shots_home))
                lambda_shots_away = max(0.1, min(5.0, lambda_shots_away))
                
                # Blend (60% Goals, 40% Shots)
                lambda_home = 0.60 * lambda_home + 0.40 * lambda_shots_home
                lambda_away = 0.60 * lambda_away + 0.40 * lambda_shots_away
                
            if elo_tracker:
                elo_factor_h = elo_tracker.get_elo_factor(home_team, away_team)
                elo_factor_a = 2.0 - elo_factor_h
                lambda_home *= elo_factor_h
                lambda_away *= elo_factor_a
                
        # Cap goal expectancies to avoid extreme projections (underflow/overflow probabilities)
        lambda_home = max(0.5, min(5.0, lambda_home))
        lambda_away = max(0.5, min(5.0, lambda_away))
        
        # Build score matrix (up to 8 goals each team)
        max_goals = 8
        home_probs = [math.exp(-lambda_home) * (lambda_home**i) / math.factorial(i) for i in range(max_goals + 1)]
        away_probs = [math.exp(-lambda_away) * (lambda_away**i) / math.factorial(i) for i in range(max_goals + 1)]
        
        # Compute joint probabilities
        prob_matrix = np.outer(home_probs, away_probs)
        
        # Apply Dixon-Coles adjustment for low-scoring matches (especially 0-0 and draws)
        rho = RHO_FALLBACK

        # Estimate dynamic rho from historical_df if available
        if historical_df is not None and not historical_df.empty:
            target_dt = pd.to_datetime(match_date)
            window_start = target_dt - pd.Timedelta(days=self.rolling_window_days)
            mask = (historical_df['Date'] < target_dt) & (historical_df['Date'] >= window_start)
            recent = historical_df[mask].dropna(subset=['FTHG', 'FTAG'])
            if len(recent) >= RHO_MLE_MIN_MATCHES:
                lh_list = recent['FTHG'].astype(float).tolist()
                la_list = recent['FTAG'].astype(float).tolist()
                dyn_rho = estimate_dynamic_rho(
                    recent['FTHG'].astype(int).tolist(),
                    recent['FTAG'].astype(int).tolist(),
                    lh_list,
                    la_list
                )
                if dyn_rho is not None and not pd.isna(dyn_rho):
                    rho = dyn_rho

        tau_00 = 1.0 - lambda_home * lambda_away * rho
        tau_10 = 1.0 + lambda_away * rho
        tau_01 = 1.0 + lambda_home * rho
        tau_11 = 1.0 - rho
        
        prob_matrix[0, 0] *= max(0.0, tau_00)
        prob_matrix[1, 0] *= max(0.0, tau_10)
        prob_matrix[0, 1] *= max(0.0, tau_01)
        prob_matrix[1, 1] *= max(0.0, tau_11)
        
        matrix_sum = np.sum(prob_matrix)
        if matrix_sum > 0:
            prob_matrix = prob_matrix / matrix_sum
        
        # Calculate outcomes
        prob_home = float(np.sum(np.tril(prob_matrix, -1))) # x > y (Home Win)
        prob_draw = float(np.sum(np.diag(prob_matrix)))     # x == y (Draw)
        prob_away = float(np.sum(np.triu(prob_matrix, 1)))  # x < y (Away Win)
        
        # Goals markets
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
                    
        prob_under_25 = 1.0 - prob_over_25
        prob_under_15 = 1.0 - prob_over_15
        prob_under_35 = 1.0 - prob_over_35
        prob_under_45 = 1.0 - prob_over_45
        prob_under_55 = 1.0 - prob_over_55
        
        # BTTS (Both Teams To Score)
        # Uses joint probability matrix (respects Dixon-Coles correlation) instead of assuming independence
        prob_btts_yes = float(sum(
            prob_matrix[i, j] for i in range(1, max_goals + 1) for j in range(1, max_goals + 1)
        ))
        prob_btts_no = 1.0 - prob_btts_yes
        
        # Asian Handicap Fair Odds
        # We calculate the probability components for common AH lines and derive their Fair Odds.
        ah_lines = [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5]
        fair_ah_home = {}
        fair_ah_away = {}
        
        for line in ah_lines:
            ah_h = calculate_ah_probabilities(prob_matrix, line)
            ah_a = calculate_ah_probabilities(prob_matrix, -line) # Away perspective is exactly the inverse line
            
            fair_ah_home[f"{line:g}"] = get_fair_ah_odds(ah_h)
            fair_ah_away[f"{-line:g}"] = get_fair_ah_odds(ah_a)
            
        # We also pass raw prob_matrix so other functions can calculate AH dynamically if needed.
        
        return {
            'lambda_home': lambda_home,
            'lambda_away': lambda_away,
            'prob_home': prob_home,
            'prob_draw': prob_draw,
            'prob_away': prob_away,
            'prob_over_15': prob_over_15,
            'prob_under_15': prob_under_15,
            'prob_over_25': prob_over_25,
            'prob_under_25': prob_under_25,
            'prob_over_35': prob_over_35,
            'prob_under_35': prob_under_35,
            'prob_over_45': prob_over_45,
            'prob_under_45': prob_under_45,
            'prob_over_55': prob_over_55,
            'prob_under_55': prob_under_55,
            'prob_btts_yes': prob_btts_yes,
            'prob_btts_no': prob_btts_no,
            'prob_cs_10': float(prob_matrix[1, 0]),
            'prob_cs_20': float(prob_matrix[2, 0]),
            'prob_cs_21': float(prob_matrix[2, 1]),
            'prob_cs_00': float(prob_matrix[0, 0]),
            'prob_cs_11': float(prob_matrix[1, 1]),
            'prob_cs_01': float(prob_matrix[0, 1]),
            'prob_cs_02': float(prob_matrix[0, 2]),
            'prob_cs_12': float(prob_matrix[1, 2]),
            'fair_ah_home': fair_ah_home,
            'fair_ah_away': fair_ah_away,
            'prob_matrix': prob_matrix
        }

    def _predict_via_pipeline(self, home_team, away_team, historical_df, match_date, elo_tracker=None):
        """Unified prediction using ProbabilityPipeline (xG/SOT/Goals multi-tier blending, dynamic rho, Elo, HT)."""
        from collections import defaultdict
        from .probability_pipeline import ProbabilityPipeline, MODEL_POISSON
        from .elo_model import EloTracker, estimate_dynamic_rho
        from .backtest.helpers import get_league_weighted_decay

        state = self._build_form_state_from_df(historical_df, match_date)

        if elo_tracker is None:
            elo_tracker = EloTracker()

        pipeline = ProbabilityPipeline(model_type=MODEL_POISSON)
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

        max_g = MAX_GOALS
        prob_matrix = bundle.prob_matrix

        ah_lines = [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5]
        fair_ah_home = {}
        fair_ah_away = {}
        for line in ah_lines:
            ah_h = calculate_ah_probabilities(prob_matrix, line)
            ah_a = calculate_ah_probabilities(prob_matrix, -line)
            fair_ah_home[f"{line:g}"] = get_fair_ah_odds(ah_h)
            fair_ah_away[f"{-line:g}"] = get_fair_ah_odds(ah_a)

        return {
            'lambda_home': bundle.lambda_home, 'lambda_away': bundle.lambda_away,
            'prob_home': bundle.prob_h, 'prob_draw': bundle.prob_d, 'prob_away': bundle.prob_a,
            'prob_over_15': bundle.prob_over_15, 'prob_under_15': 1.0 - bundle.prob_over_15,
            'prob_over_25': bundle.prob_over_25, 'prob_under_25': 1.0 - bundle.prob_over_25,
            'prob_over_35': bundle.prob_over_35, 'prob_under_35': 1.0 - bundle.prob_over_35,
            'prob_over_45': bundle.prob_over_45, 'prob_under_45': 1.0 - bundle.prob_over_45,
            'prob_over_55': bundle.prob_over_55, 'prob_under_55': 1.0 - bundle.prob_over_55,
            'prob_btts_yes': bundle.prob_btts_yes, 'prob_btts_no': 1.0 - bundle.prob_btts_yes,
            'prob_cs_10': float(prob_matrix[1, 0]) if prob_matrix.shape[0] > 1 and prob_matrix.shape[1] > 0 else 0.0,
            'prob_cs_20': float(prob_matrix[2, 0]) if prob_matrix.shape[0] > 2 and prob_matrix.shape[1] > 0 else 0.0,
            'prob_cs_21': float(prob_matrix[2, 1]) if prob_matrix.shape[0] > 2 and prob_matrix.shape[1] > 1 else 0.0,
            'prob_cs_00': float(prob_matrix[0, 0]),
            'prob_cs_11': float(prob_matrix[1, 1]) if prob_matrix.shape[0] > 1 and prob_matrix.shape[1] > 1 else 0.0,
            'prob_cs_01': float(prob_matrix[0, 1]) if prob_matrix.shape[1] > 1 else 0.0,
            'prob_cs_02': float(prob_matrix[0, 2]) if prob_matrix.shape[1] > 2 else 0.0,
            'prob_cs_12': float(prob_matrix[1, 2]) if prob_matrix.shape[0] > 1 and prob_matrix.shape[1] > 2 else 0.0,
            'fair_ah_home': fair_ah_home, 'fair_ah_away': fair_ah_away,
            'prob_matrix': prob_matrix,
            'rho': bundle.rho,
        }

# Import pandas here for use in ratings
import pandas as pd

def solve_lambda_from_under25(prob_under_25):
    """
    Given the probability of Under 2.5 goals, solves for the expected total goals (lambda)
    under a Poisson distribution using bisection search.
    P(X <= 2) = e^-lambda * (1 + lambda + (lambda^2)/2)
    """
    if prob_under_25 <= 0.01:
        return 5.0
    if prob_under_25 >= 0.99:
        return 0.1
        
    # Bisection search
    low = 0.05
    high = 10.0
    for _ in range(15):
        mid = (low + high) / 2.0
        p_under = math.exp(-mid) * (1.0 + mid + (mid**2) / 2.0)
        # Since p_under decreases as mid (lambda) increases
        if p_under > prob_under_25:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0

def estimate_bookmaker_odds(avg_over_25_odds, avg_under_25_odds, model_lambda_home, model_lambda_away,
                          rho: Optional[float] = None, bookmaker: str = 'Bet365',
                          btts_yes_odd=None, btts_no_odd=None):
    """
    Estimates the bookmaker's odds for all CS markets by back-calculating from
    the bookmaker's Over/Under 2.5 odds and the model's home/away goal ratio.

    Juice is scaled per bookmaker type:
    - Betfair Exchange: no overround (exchange), ~1.02-1.05 (commission only)
    - Pinnacle: low margin, ~1.06-1.12
    - Bet365: traditional, ~1.22-1.40

    If BTTS odds are provided, they are used to adjust the Dixon-Coles rho
    parameter in the estimated distribution, capturing market sentiment about
    goal correlation that a simple Poisson model misses.
    """
    import numpy as np
    import pandas as pd
    # 1. Handle missing/invalid input
    if pd.isna(avg_over_25_odds) or pd.isna(avg_under_25_odds) or avg_over_25_odds <= 1.0 or avg_under_25_odds <= 1.0:
        return {
            'bookie_over_15': np.nan, 'bookie_under_15': np.nan,
            'bookie_over_35': np.nan, 'bookie_under_35': np.nan,
            'bookie_over_45': np.nan, 'bookie_under_45': np.nan,
            'bookie_over_55': np.nan, 'bookie_under_55': np.nan,
            'bookie_btts_yes': np.nan, 'bookie_btts_no': np.nan,
            'bookie_cs_00': np.nan,
            'bookie_cs_10': np.nan, 'bookie_cs_01': np.nan,
            'bookie_cs_20': np.nan, 'bookie_cs_02': np.nan,
            'bookie_cs_30': np.nan, 'bookie_cs_03': np.nan,
            'bookie_cs_40': np.nan, 'bookie_cs_04': np.nan,
            'bookie_cs_11': np.nan,
            'bookie_cs_21': np.nan, 'bookie_cs_12': np.nan,
            'bookie_cs_31': np.nan, 'bookie_cs_13': np.nan,
            'bookie_cs_41': np.nan, 'bookie_cs_14': np.nan,
            'bookie_cs_22': np.nan,
            'bookie_cs_32': np.nan, 'bookie_cs_23': np.nan,
            'bookie_cs_33': np.nan,
            'bookie_ht_home': np.nan, 'bookie_ht_draw': np.nan, 'bookie_ht_away': np.nan,
            'bookie_ht_over05': np.nan, 'bookie_ht_under05': np.nan,
            'bookie_ht_over15': np.nan, 'bookie_ht_under15': np.nan
        }
        
    # 2. Calculate bookmaker's implied probabilities (with margin/juice included)
    implied_over = 1.0 / avg_over_25_odds
    implied_under = 1.0 / avg_under_25_odds
    total_implied = implied_over + implied_under # Usually around 1.05 - 1.10
    
    # Fair (no-juice) probability of Under 2.5
    fair_under = implied_under / total_implied
    
    # 3. Solve for bookmaker's implied average goals (lambda_total)
    lambda_total = solve_lambda_from_under25(fair_under)
    
    # 4. Partition total lambda based on model's home/away goal expectancy ratio
    total_model_lambda = model_lambda_home + model_lambda_away
    if total_model_lambda > 0:
        ratio_home = model_lambda_home / total_model_lambda
    else:
        ratio_home = 0.5
        
    lambda_home_bookie = lambda_total * ratio_home
    lambda_away_bookie = lambda_total * (1.0 - ratio_home)
    
    # Avoid zero values
    lambda_home_bookie = max(0.05, lambda_home_bookie)
    lambda_away_bookie = max(0.05, lambda_away_bookie)
    
    # 5. Compute fair probabilities using Negative Binomial (NB2) matrix
    # Same dispersion params as the probability pipeline for consistency
    max_goals = 8
    alpha_h = NB_ALPHA_HOME
    alpha_a = NB_ALPHA_AWAY

    def _nb2_pmf(k, mu, alpha):
        if alpha <= 0 or mu <= 0.001:
            return math.exp(-mu) * (mu ** k) / math.factorial(k) if k <= 170 else 0.0
        n_param = 1.0 / alpha
        p_param = 1.0 / (1.0 + alpha * mu)
        return nbinom.pmf(k, n_param, p_param)

    home_probs_bk = np.array([_nb2_pmf(i, lambda_home_bookie, alpha_h) for i in range(max_goals + 1)])
    away_probs_bk = np.array([_nb2_pmf(i, lambda_away_bookie, alpha_a) for i in range(max_goals + 1)])

    home_probs_bk = home_probs_bk / home_probs_bk.sum()
    away_probs_bk = away_probs_bk / away_probs_bk.sum()

    bk_matrix = np.outer(home_probs_bk, away_probs_bk)
    rho_val = rho if rho is not None else RHO_FALLBACK
    tau_00 = max(0.0, 1.0 - lambda_home_bookie * lambda_away_bookie * rho_val)
    tau_10 = max(0.0, 1.0 + lambda_away_bookie * rho_val)
    tau_01 = max(0.0, 1.0 + lambda_home_bookie * rho_val)
    tau_11 = max(0.0, 1.0 - rho_val)

    bk_matrix[0, 0] *= tau_00
    bk_matrix[1, 0] *= tau_10
    bk_matrix[0, 1] *= tau_01
    bk_matrix[1, 1] *= tau_11

    bk_sum = np.sum(bk_matrix)
    if bk_sum > 0:
        bk_matrix = bk_matrix / bk_sum
        
    # Over/Under 1.5, 3.5, 4.5, 5.5
    fair_over_15 = 0.0
    fair_over_35 = 0.0
    fair_over_45 = 0.0
    fair_over_55 = 0.0
    for x in range(max_goals + 1):
        for y in range(max_goals + 1):
            tot = x + y
            if tot > 1: fair_over_15 += bk_matrix[x, y]
            if tot > 3: fair_over_35 += bk_matrix[x, y]
            if tot > 4: fair_over_45 += bk_matrix[x, y]
            if tot > 5: fair_over_55 += bk_matrix[x, y]
            
    fair_under_15 = 1.0 - fair_over_15
    fair_under_35 = 1.0 - fair_over_35
    fair_under_45 = 1.0 - fair_over_45
    fair_under_55 = 1.0 - fair_over_55
    
    # BTTS — usa a matriz conjunta (respeita correlação Dixon-Coles), igual ao predict_match
    fair_btts_yes = float(sum(
        bk_matrix[i, j] for i in range(1, max_goals + 1) for j in range(1, max_goals + 1)
    ))
    fair_btts_no = 1.0 - fair_btts_yes
    
    # Correct Scores — cobertura expandida (20 placares)
    fair_cs_00 = float(bk_matrix[0, 0])
    fair_cs_10 = float(bk_matrix[1, 0]); fair_cs_01 = float(bk_matrix[0, 1])
    fair_cs_20 = float(bk_matrix[2, 0]); fair_cs_02 = float(bk_matrix[0, 2])
    fair_cs_30 = float(bk_matrix[3, 0]); fair_cs_03 = float(bk_matrix[0, 3])
    fair_cs_40 = float(bk_matrix[4, 0]); fair_cs_04 = float(bk_matrix[0, 4])
    fair_cs_11 = float(bk_matrix[1, 1])
    fair_cs_21 = float(bk_matrix[2, 1]); fair_cs_12 = float(bk_matrix[1, 2])
    fair_cs_31 = float(bk_matrix[3, 1]); fair_cs_13 = float(bk_matrix[1, 3])
    fair_cs_41 = float(bk_matrix[4, 1]); fair_cs_14 = float(bk_matrix[1, 4])
    fair_cs_22 = float(bk_matrix[2, 2])
    fair_cs_32 = float(bk_matrix[3, 2]); fair_cs_23 = float(bk_matrix[2, 3])
    fair_cs_33 = float(bk_matrix[3, 3])
    
    # HT probabilities for bookie (NB2 with same dispersion, reduced lambda ~45%)
    lambda_home_bookie_ht = lambda_home_bookie * 0.45
    lambda_away_bookie_ht = lambda_away_bookie * 0.45

    home_probs_bk_ht = np.array([_nb2_pmf(i, lambda_home_bookie_ht, alpha_h) for i in range(max_goals + 1)])
    away_probs_bk_ht = np.array([_nb2_pmf(i, lambda_away_bookie_ht, alpha_a) for i in range(max_goals + 1)])
    home_probs_bk_ht = home_probs_bk_ht / home_probs_bk_ht.sum()
    away_probs_bk_ht = away_probs_bk_ht / away_probs_bk_ht.sum()
    bk_matrix_ht = np.outer(home_probs_bk_ht, away_probs_bk_ht)

    tau_00_ht = max(0.0, 1.0 - lambda_home_bookie_ht * lambda_away_bookie_ht * rho_val)
    tau_10_ht = max(0.0, 1.0 + lambda_away_bookie_ht * rho_val)
    tau_01_ht = max(0.0, 1.0 + lambda_home_bookie_ht * rho_val)
    tau_11_ht = max(0.0, 1.0 - rho_val)
    bk_matrix_ht[0, 0] *= tau_00_ht
    bk_matrix_ht[1, 0] *= tau_10_ht
    bk_matrix_ht[0, 1] *= tau_01_ht
    bk_matrix_ht[1, 1] *= tau_11_ht
    
    bk_sum_ht = np.sum(bk_matrix_ht)
    if bk_sum_ht > 0:
        bk_matrix_ht = bk_matrix_ht / bk_sum_ht
        
    fair_ht_home = float(np.sum(np.tril(bk_matrix_ht, -1)))
    fair_ht_draw = float(np.sum(np.diag(bk_matrix_ht)))
    fair_ht_away = float(np.sum(np.triu(bk_matrix_ht, 1)))
    fair_ht_over05 = 1.0 - float(bk_matrix_ht[0, 0])
    fair_ht_under05 = float(bk_matrix_ht[0, 0])
    
    fair_ht_over15 = 0.0
    for x in range(max_goals + 1):
        for y in range(max_goals + 1):
            if x + y > 1: fair_ht_over15 += bk_matrix_ht[x, y]
    fair_ht_under15 = 1.0 - fair_ht_over15
    
    # 6. Calibrate rho from BTTS market odds (if available)
    if btts_yes_odd and btts_no_odd and btts_yes_odd > 1.01 and btts_no_odd > 1.01:
        try:
            implied_btts_yes = 1.0 / btts_yes_odd
            implied_btts_no = 1.0 / btts_no_odd
            market_btts_prob = implied_btts_yes / (implied_btts_yes + implied_btts_no)
            # Model BTTS (computed above with current rho)
            model_btts = float(sum(
                bk_matrix[i, j] for i in range(1, max_goals + 1) for j in range(1, max_goals + 1)
            ))
            if 0.20 < market_btts_prob < 0.80 and abs(market_btts_prob - model_btts) > 0.015:
                # Adjust rho: higher rho → more correlated → fewer BTTS
                # Try 3 rho candidates and pick closest BTTS match
                best_rho = rho_val
                best_diff = abs(market_btts_prob - model_btts)
                for candidate_rho in [min(0.15, rho_val - 0.08), max(-0.15, rho_val + 0.08), 0.0]:
                    if candidate_rho == rho_val:
                        continue
                    test_matrix = np.outer(home_probs_bk, away_probs_bk)
                    t00 = 1.0 - lambda_home_bookie * lambda_away_bookie * candidate_rho
                    t10 = 1.0 + lambda_away_bookie * candidate_rho
                    t01 = 1.0 + lambda_home_bookie * candidate_rho
                    t11 = 1.0 - candidate_rho
                    test_matrix[0, 0] *= max(0.0, t00)
                    test_matrix[1, 0] *= max(0.0, t10)
                    test_matrix[0, 1] *= max(0.0, t01)
                    test_matrix[1, 1] *= max(0.0, t11)
                    t_sum = np.sum(test_matrix)
                    if t_sum > 0:
                        test_matrix = test_matrix / t_sum
                    test_btts = float(sum(
                        test_matrix[i, j] for i in range(1, max_goals + 1) for j in range(1, max_goals + 1)
                    ))
                    diff = abs(market_btts_prob - test_btts)
                    if diff < best_diff:
                        best_diff = diff
                        best_rho = candidate_rho
                if best_rho != rho_val:
                    rho_val = best_rho
                    # Recompute DC adjustment on bk_matrix
                    bk_matrix = np.outer(home_probs_bk, away_probs_bk)
                    bk_matrix[0, 0] *= max(0.0, 1.0 - lambda_home_bookie * lambda_away_bookie * rho_val)
                    bk_matrix[1, 0] *= max(0.0, 1.0 + lambda_away_bookie * rho_val)
                    bk_matrix[0, 1] *= max(0.0, 1.0 + lambda_home_bookie * rho_val)
                    bk_matrix[1, 1] *= max(0.0, 1.0 - rho_val)
                    bk_sum = np.sum(bk_matrix)
                    if bk_sum > 0:
                        bk_matrix = bk_matrix / bk_sum
                    # Recompute all fair probabilities that depend on the matrix
                    fair_over_15 = 0.0; fair_over_35 = 0.0; fair_over_45 = 0.0; fair_over_55 = 0.0
                    for x in range(max_goals + 1):
                        for y in range(max_goals + 1):
                            tot = x + y
                            if tot > 1: fair_over_15 += bk_matrix[x, y]
                            if tot > 3: fair_over_35 += bk_matrix[x, y]
                            if tot > 4: fair_over_45 += bk_matrix[x, y]
                            if tot > 5: fair_over_55 += bk_matrix[x, y]
                    fair_under_15 = 1.0 - fair_over_15
                    fair_under_35 = 1.0 - fair_over_35
                    fair_under_45 = 1.0 - fair_over_45
                    fair_under_55 = 1.0 - fair_over_55
                    fair_btts_yes = float(sum(
                        bk_matrix[i, j] for i in range(1, max_goals + 1) for j in range(1, max_goals + 1)
                    ))
                    fair_btts_no = 1.0 - fair_btts_yes
                    fair_cs_00 = float(bk_matrix[0, 0])
                    fair_cs_10 = float(bk_matrix[1, 0]); fair_cs_01 = float(bk_matrix[0, 1])
                    fair_cs_20 = float(bk_matrix[2, 0]); fair_cs_02 = float(bk_matrix[0, 2])
                    fair_cs_30 = float(bk_matrix[3, 0]); fair_cs_03 = float(bk_matrix[0, 3])
                    fair_cs_40 = float(bk_matrix[4, 0]); fair_cs_04 = float(bk_matrix[0, 4])
                    fair_cs_11 = float(bk_matrix[1, 1])
                    fair_cs_21 = float(bk_matrix[2, 1]); fair_cs_12 = float(bk_matrix[1, 2])
                    fair_cs_31 = float(bk_matrix[3, 1]); fair_cs_13 = float(bk_matrix[1, 3])
                    fair_cs_41 = float(bk_matrix[4, 1]); fair_cs_14 = float(bk_matrix[1, 4])
                    fair_cs_22 = float(bk_matrix[2, 2])
                    fair_cs_32 = float(bk_matrix[3, 2]); fair_cs_23 = float(bk_matrix[2, 3])
                    fair_cs_33 = float(bk_matrix[3, 3])
        except Exception:
            pass  # BTTS calibration failed silently, use original rho

    # 7. Apply juice and return bookmaker odds
    is_betfair = (bookmaker or '').lower().startswith('betfair')
    is_pinnacle = (bookmaker or '').lower().startswith('pinnacle')

    def apply_juice(prob, market_type="default"):
        if prob <= 0.001: return 99.0

        if is_betfair:
            # Betfair Exchange: commission 2-5%, no traditional overround
            # CS markets still carry wider spreads due to lower liquidity
            base_juice = 1.03
            if market_type == "cs":
                if prob > 0.06:      juice_val = 1.06
                elif prob > 0.03:    juice_val = 1.08
                elif prob > 0.015:   juice_val = 1.10
                else:                juice_val = 1.13
            elif market_type == "ht_1x2":
                juice_val = 1.04
            else:
                juice_val = base_juice
        elif is_pinnacle:
            # Pinnacle: low-margin sharp bookmaker (~6-12% overround)
            base_juice = 1.06
            if market_type == "cs":
                if prob > 0.06:      juice_val = 1.10
                elif prob > 0.03:    juice_val = 1.13
                elif prob > 0.015:   juice_val = 1.16
                else:                juice_val = 1.20
            elif market_type == "ht_1x2":
                juice_val = 1.08
            else:
                juice_val = base_juice
        else:
            # Bet365 / default: standard bookmaker overround
            juice_val = total_implied
            if market_type == "ht_1x2":
                juice_val = max(1.12, total_implied + 0.06)
            elif market_type == "cs":
                if prob > 0.06:
                    juice_val = max(1.22, total_implied + 0.15)
                elif prob > 0.03:
                    juice_val = max(1.28, total_implied + 0.20)
                elif prob > 0.015:
                    juice_val = max(1.33, total_implied + 0.26)
                else:
                    juice_val = max(1.40, total_implied + 0.33)

        val = 1.0 / (prob * juice_val)
        return float(round(max(1.01, min(99.0, val)), 3))
        
    return {
        'bookie_over_15': apply_juice(fair_over_15),
        'bookie_under_15': apply_juice(fair_under_15),
        'bookie_over_35': apply_juice(fair_over_35),
        'bookie_under_35': apply_juice(fair_under_35),
        'bookie_over_45': apply_juice(fair_over_45),
        'bookie_under_45': apply_juice(fair_under_45),
        'bookie_over_55': apply_juice(fair_over_55),
        'bookie_under_55': apply_juice(fair_under_55),
        'bookie_btts_yes': apply_juice(fair_btts_yes),
        'bookie_btts_no': apply_juice(fair_btts_no),
        # Correct Scores — 20 placares com juice variável por raridade
        'bookie_cs_00': apply_juice(fair_cs_00, "cs"),
        'bookie_cs_10': apply_juice(fair_cs_10, "cs"), 'bookie_cs_01': apply_juice(fair_cs_01, "cs"),
        'bookie_cs_20': apply_juice(fair_cs_20, "cs"), 'bookie_cs_02': apply_juice(fair_cs_02, "cs"),
        'bookie_cs_30': apply_juice(fair_cs_30, "cs"), 'bookie_cs_03': apply_juice(fair_cs_03, "cs"),
        'bookie_cs_40': apply_juice(fair_cs_40, "cs"), 'bookie_cs_04': apply_juice(fair_cs_04, "cs"),
        'bookie_cs_11': apply_juice(fair_cs_11, "cs"),
        'bookie_cs_21': apply_juice(fair_cs_21, "cs"), 'bookie_cs_12': apply_juice(fair_cs_12, "cs"),
        'bookie_cs_31': apply_juice(fair_cs_31, "cs"), 'bookie_cs_13': apply_juice(fair_cs_13, "cs"),
        'bookie_cs_41': apply_juice(fair_cs_41, "cs"), 'bookie_cs_14': apply_juice(fair_cs_14, "cs"),
        'bookie_cs_22': apply_juice(fair_cs_22, "cs"),
        'bookie_cs_32': apply_juice(fair_cs_32, "cs"), 'bookie_cs_23': apply_juice(fair_cs_23, "cs"),
        'bookie_cs_33': apply_juice(fair_cs_33, "cs"),
        'bookie_ht_home': apply_juice(fair_ht_home, "ht_1x2"),
        'bookie_ht_draw': apply_juice(fair_ht_draw, "ht_1x2"),
        'bookie_ht_away': apply_juice(fair_ht_away, "ht_1x2"),
        'bookie_ht_over05': apply_juice(fair_ht_over05),
        'bookie_ht_under05': apply_juice(fair_ht_under05),
        'bookie_ht_over15': apply_juice(fair_ht_over15),
        'bookie_ht_under15': apply_juice(fair_ht_under15)
    }
