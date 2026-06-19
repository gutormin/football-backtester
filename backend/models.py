import pandas as pd
import numpy as np
import math
from .elo_model import estimate_dynamic_rho

def find_best_team_match(api_name, historical_teams):
    if not api_name:
        return api_name
    api_name_lower = api_name.lower().strip()
    
    # Direct match
    if api_name in historical_teams:
        return api_name
        
    # Check for lowercase direct match
    for team in historical_teams:
        if team.lower().strip() == api_name_lower:
            return team
            
    # Check if one is a substring of the other (excluding common suffixes like FC, City, United, etc.)
    clean_api = api_name_lower.replace(' fc', '').replace(' united', '').replace(' utd', '').replace(' city', '').replace(' town', '').replace(' athletic', '').replace(' club', '').strip()
    if not clean_api:
        return api_name
        
    for team in historical_teams:
        team_lower = team.lower()
        clean_team = team_lower.replace(' fc', '').replace(' united', '').replace(' utd', '').replace(' city', '').replace(' town', '').replace(' athletic', '').replace(' club', '').strip()
        if clean_api == clean_team or clean_api in clean_team or clean_team in clean_api:
            return team
            
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

class PoissonModel:
    def __init__(self, rolling_window_days=365, min_matches=10, decay_xi=0.0065):
        self.rolling_window_days = rolling_window_days
        self.min_matches = min_matches
        self.decay_xi = decay_xi

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
        home_att = {team: weighted_avg(group, 'FTHG') / avg_home_goals for team, group in home_grouped}
        # Home team defensive strength: avg goals conceded / league avg goals conceded at home
        home_def = {team: weighted_avg(group, 'FTAG') / avg_away_goals for team, group in home_grouped}
        
        # Away team offensive strength: avg goals scored / league avg goals scored away
        away_att = {team: weighted_avg(group, 'FTAG') / avg_away_goals for team, group in away_grouped}
        # Away team defensive strength: avg goals conceded / league avg goals conceded away
        away_def = {team: weighted_avg(group, 'FTHG') / avg_home_goals for team, group in away_grouped}
        
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
        
        home_sot_att = {team: weighted_avg(group, 'HST') / avg_home_sot for team, group in home_grouped}
        home_sot_def = {team: weighted_avg(group, 'AST') / avg_away_sot for team, group in home_grouped}
        
        away_sot_att = {team: weighted_avg(group, 'AST') / avg_away_sot for team, group in away_grouped}
        away_sot_def = {team: weighted_avg(group, 'HST') / avg_home_sot for team, group in away_grouped}
        
        return {
            'home_sot_att': home_sot_att,
            'home_sot_def': home_sot_def,
            'away_sot_att': away_sot_att,
            'away_sot_def': away_sot_def,
            'avg_home_sot': avg_home_sot,
            'avg_away_sot': avg_away_sot
        }

    def predict_match(self, home_team, away_team, historical_df, match_date, elo_tracker=None, home_xg=None, away_xg=None):
        """
        Predicts match outcome probabilities (1X2, Over/Under, BTTS) using a Poisson model.
        """
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
                
                # Try xG blend
                xg_ratings = None
                if xg_ratings:
                    h_xg_att = xg_ratings['home_xg_att'].get(matched_home, 1.0)
                    h_xg_def = xg_ratings['home_xg_def'].get(matched_home, 1.0)
                    a_xg_att = xg_ratings['away_xg_att'].get(matched_away, 1.0)
                    a_xg_def = xg_ratings['away_xg_def'].get(matched_away, 1.0)
                    
                    if np.isnan(h_xg_att): h_xg_att = 1.0
                    if np.isnan(h_xg_def): h_xg_def = 1.0
                    if np.isnan(a_xg_att): a_xg_att = 1.0
                    if np.isnan(a_xg_def): a_xg_def = 1.0
                    
                    lambda_xg_home = xg_ratings['avg_home_xg'] * h_xg_att * a_xg_def
                    lambda_xg_away = xg_ratings['avg_away_xg'] * a_xg_att * h_xg_def
                    
                    lambda_xg_home = max(0.1, min(5.0, lambda_xg_home))
                    lambda_xg_away = max(0.1, min(5.0, lambda_xg_away))
                    
                    lambda_home = 0.50 * lambda_xg_home + 0.30 * lambda_shots_home + 0.20 * lambda_home
                    lambda_away = 0.50 * lambda_xg_away + 0.30 * lambda_shots_away + 0.20 * lambda_away
                else:
                    # Blend (60% Goals, 40% Shots)
                    lambda_home = 0.60 * lambda_home + 0.40 * lambda_shots_home
                    lambda_away = 0.60 * lambda_away + 0.40 * lambda_shots_away
                
            if elo_tracker:
                elo_factor_h = elo_tracker.get_elo_factor(home_team, away_team)
                elo_factor_a = 2.0 - elo_factor_h
                lambda_home *= elo_factor_h
                lambda_away *= elo_factor_a
                
        # Cap goal expectancies to avoid extreme projections
        lambda_home = max(0.1, min(5.0, lambda_home))
        lambda_away = max(0.1, min(5.0, lambda_away))
        
        # Build score matrix (up to 8 goals each team)
        max_goals = 8
        home_probs = [math.exp(-lambda_home) * (lambda_home**i) / math.factorial(i) for i in range(max_goals + 1)]
        away_probs = [math.exp(-lambda_away) * (lambda_away**i) / math.factorial(i) for i in range(max_goals + 1)]
        
        # Compute joint probabilities
        prob_matrix = np.outer(home_probs, away_probs)
        
        # Apply Dixon-Coles adjustment for low-scoring matches (especially 0-0 and draws)
        rho = -0.085 # Standard parameter for football goals dependency
        
        # Estimate dynamic rho from historical_df if available
        if historical_df is not None and not historical_df.empty:
            target_dt = pd.to_datetime(match_date)
            window_start = target_dt - pd.Timedelta(days=self.rolling_window_days)
            mask = (historical_df['Date'] < target_dt) & (historical_df['Date'] >= window_start)
            recent = historical_df[mask].dropna(subset=['FTHG', 'FTAG'])
            if len(recent) >= 50:
                avg_h = recent['FTHG'].mean()
                avg_a = recent['FTAG'].mean()
                lh_list = [avg_h] * len(recent)
                la_list = [avg_a] * len(recent)
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
        # P(Home >= 1 and Away >= 1) = (1 - P(Home=0)) * (1 - P(Away=0))
        prob_btts_yes = float((1.0 - home_probs[0]) * (1.0 - away_probs[0]))
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

def estimate_bookmaker_odds(avg_over_25_odds, avg_under_25_odds, model_lambda_home, model_lambda_away):
    """
    Estimates the bookmaker's odds for Over 1.5, Under 1.5, BTTS Yes, and BTTS No
    by back-calculating from the bookmaker's Over/Under 2.5 odds and the model's home/away ratio.
    """
    # 1. Handle missing/invalid input
    if pd.isna(avg_over_25_odds) or pd.isna(avg_under_25_odds) or avg_over_25_odds <= 1.0 or avg_under_25_odds <= 1.0:
        return {
            'bookie_over_15': np.nan, 'bookie_under_15': np.nan,
            'bookie_over_35': np.nan, 'bookie_under_35': np.nan,
            'bookie_over_45': np.nan, 'bookie_under_45': np.nan,
            'bookie_over_55': np.nan, 'bookie_under_55': np.nan,
            'bookie_btts_yes': np.nan, 'bookie_btts_no': np.nan,
            'bookie_cs_10': np.nan, 'bookie_cs_20': np.nan, 'bookie_cs_21': np.nan,
            'bookie_cs_00': np.nan, 'bookie_cs_11': np.nan, 'bookie_cs_01': np.nan,
            'bookie_cs_02': np.nan, 'bookie_cs_12': np.nan,
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
    
    # 5. Compute fair probabilities for all markets using a joint probability matrix
    # Build score matrix from the bookmaker's perspective (up to 6 goals)
    max_g = 6
    home_probs_bk = [math.exp(-lambda_home_bookie) * (lambda_home_bookie**i) / math.factorial(i) for i in range(max_g + 1)]
    away_probs_bk = [math.exp(-lambda_away_bookie) * (lambda_away_bookie**i) / math.factorial(i) for i in range(max_g + 1)]
    
    bk_matrix = np.outer(home_probs_bk, away_probs_bk)
    rho = -0.085
    tau_00 = 1.0 - lambda_home_bookie * lambda_away_bookie * rho
    tau_10 = 1.0 + lambda_away_bookie * rho
    tau_01 = 1.0 + lambda_home_bookie * rho
    tau_11 = 1.0 - rho
    
    bk_matrix[0, 0] *= max(0.0, tau_00)
    bk_matrix[1, 0] *= max(0.0, tau_10)
    bk_matrix[0, 1] *= max(0.0, tau_01)
    bk_matrix[1, 1] *= max(0.0, tau_11)
    
    bk_sum = np.sum(bk_matrix)
    if bk_sum > 0:
        bk_matrix = bk_matrix / bk_sum
        
    # Over/Under 1.5, 3.5, 4.5, 5.5
    fair_over_15 = 0.0
    fair_over_35 = 0.0
    fair_over_45 = 0.0
    fair_over_55 = 0.0
    for x in range(max_g + 1):
        for y in range(max_g + 1):
            tot = x + y
            if tot > 1: fair_over_15 += bk_matrix[x, y]
            if tot > 3: fair_over_35 += bk_matrix[x, y]
            if tot > 4: fair_over_45 += bk_matrix[x, y]
            if tot > 5: fair_over_55 += bk_matrix[x, y]
            
    fair_under_15 = 1.0 - fair_over_15
    fair_under_35 = 1.0 - fair_over_35
    fair_under_45 = 1.0 - fair_over_45
    fair_under_55 = 1.0 - fair_over_55
    
    # BTTS
    fair_btts_yes = float((1.0 - home_probs_bk[0]) * (1.0 - away_probs_bk[0]))
    fair_btts_no = 1.0 - fair_btts_yes
    
    # Correct Scores
    fair_cs_10 = float(bk_matrix[1, 0])
    fair_cs_20 = float(bk_matrix[2, 0])
    fair_cs_21 = float(bk_matrix[2, 1])
    fair_cs_00 = float(bk_matrix[0, 0])
    fair_cs_11 = float(bk_matrix[1, 1])
    fair_cs_01 = float(bk_matrix[0, 1])
    fair_cs_02 = float(bk_matrix[0, 2])
    fair_cs_12 = float(bk_matrix[1, 2])
    
    # HT probabilities for bookie
    lambda_home_bookie_ht = lambda_home_bookie * 0.45
    lambda_away_bookie_ht = lambda_away_bookie * 0.45
    
    home_probs_bk_ht = [math.exp(-lambda_home_bookie_ht) * (lambda_home_bookie_ht**i) / math.factorial(i) for i in range(max_g + 1)]
    away_probs_bk_ht = [math.exp(-lambda_away_bookie_ht) * (lambda_away_bookie_ht**i) / math.factorial(i) for i in range(max_g + 1)]
    bk_matrix_ht = np.outer(home_probs_bk_ht, away_probs_bk_ht)
    
    tau_00_ht = 1.0 - lambda_home_bookie_ht * lambda_away_bookie_ht * rho
    tau_10_ht = 1.0 + lambda_away_bookie_ht * rho
    tau_01_ht = 1.0 + lambda_home_bookie_ht * rho
    tau_11_ht = 1.0 - rho
    bk_matrix_ht[0, 0] *= max(0.0, tau_00_ht)
    bk_matrix_ht[1, 0] *= max(0.0, tau_10_ht)
    bk_matrix_ht[0, 1] *= max(0.0, tau_01_ht)
    bk_matrix_ht[1, 1] *= max(0.0, tau_11_ht)
    
    bk_sum_ht = np.sum(bk_matrix_ht)
    if bk_sum_ht > 0:
        bk_matrix_ht = bk_matrix_ht / bk_sum_ht
        
    fair_ht_home = float(np.sum(np.tril(bk_matrix_ht, -1)))
    fair_ht_draw = float(np.sum(np.diag(bk_matrix_ht)))
    fair_ht_away = float(np.sum(np.triu(bk_matrix_ht, 1)))
    fair_ht_over05 = 1.0 - float(bk_matrix_ht[0, 0])
    fair_ht_under05 = float(bk_matrix_ht[0, 0])
    
    fair_ht_over15 = 0.0
    for x in range(max_g + 1):
        for y in range(max_g + 1):
            if x + y > 1: fair_ht_over15 += bk_matrix_ht[x, y]
    fair_ht_under15 = 1.0 - fair_ht_over15
    
    # 6. Apply juice and return bookmaker odds
    def apply_juice(prob):
        if prob <= 0.001: return 99.0
        val = 1.0 / (prob * total_implied)
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
        'bookie_cs_10': apply_juice(fair_cs_10),
        'bookie_cs_20': apply_juice(fair_cs_20),
        'bookie_cs_21': apply_juice(fair_cs_21),
        'bookie_cs_00': apply_juice(fair_cs_00),
        'bookie_cs_11': apply_juice(fair_cs_11),
        'bookie_cs_01': apply_juice(fair_cs_01),
        'bookie_cs_02': apply_juice(fair_cs_02),
        'bookie_cs_12': apply_juice(fair_cs_12),
        'bookie_ht_home': apply_juice(fair_ht_home),
        'bookie_ht_draw': apply_juice(fair_ht_draw),
        'bookie_ht_away': apply_juice(fair_ht_away),
        'bookie_ht_over05': apply_juice(fair_ht_over05),
        'bookie_ht_under05': apply_juice(fair_ht_under05),
        'bookie_ht_over15': apply_juice(fair_ht_over15),
        'bookie_ht_under15': apply_juice(fair_ht_under15)
    }
