import pandas as pd
import numpy as np
import math
from datetime import datetime
from collections import defaultdict
from .data_loader import load_league_data, get_all_available_leagues
from .models import PoissonModel, estimate_bookmaker_odds, calculate_ah_probabilities, get_fair_ah_odds
from .ai_predictor import (predict_strategy_sustainability, compute_brier_score, 
                           compute_bootstrap_ci, compute_power_analysis, compute_rolling_roi, 
                           compute_pvalue_binomial, compute_edge_quality_score)
from .calibration import PlattCalibrator
from .ml_ensemble import MLEnsemble
from .elo_model import EloTracker, estimate_dynamic_rho

_WEIGHTS_CACHE = {}

def weighted_mean(values, decay=0.06):
    if not values:
        return 0.0
    n = len(values)
    cache_key = (n, decay)
    global _WEIGHTS_CACHE
    if cache_key not in _WEIGHTS_CACHE:
        weights = [math.exp(-decay * (n - 1 - i)) for i in range(n)]
        sum_weights = sum(weights)
        _WEIGHTS_CACHE[cache_key] = (weights, sum_weights)
    else:
        weights, sum_weights = _WEIGHTS_CACHE[cache_key]
    return sum(v * w for v, w in zip(values, weights)) / sum_weights

def solve_kelly_multi(probs, outcomes, max_f=1.0):
    low = 0.0
    high = max_f
    ev = sum(p * x for p, x in zip(probs, outcomes))
    if ev <= 0:
        return 0.0
    for _ in range(15):
        mid = (low + high) / 2.0
        deriv = sum(p * x / (1.0 + mid * x) for p, x in zip(probs, outcomes))
        if deriv > 0:
            low = mid
        else:
            high = mid
    return low

_FACTORIALS = [math.factorial(i) for i in range(16)]

class ChronologicalBacktester:
    def __init__(self, rolling_games=15):
        self.rolling_games = rolling_games
        self.calibrators = {}
        self.calibration_history = defaultdict(lambda: {'probs': [], 'outcomes': []})
        self.matches_since_calibration = 0
        
        self.ml_ensembles = {}
        self.ml_history = defaultdict(lambda: {'X': [], 'y': []})
        self.matches_since_ml_fit = 0

    def run(self, leagues, start_date, end_date, market, value_threshold, initial_bankroll, staking_rule, stake_value, odds_source='B365', run_monte_carlo=True, min_odds=1.0, max_odds=50.0, exchange_commission=0.0, use_ml=False, data_source='football-data', futpython_api_key='', min_odds_h=None, max_odds_h=None, min_odds_d=None, max_odds_d=None, min_odds_a=None, max_odds_a=None, min_odds_over25=None, max_odds_over25=None, min_odds_under25=None, max_odds_under25=None):
        """
        Runs a chronological backtest across selected leagues.
        
        leagues: list of league codes
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
        market: 'home', 'away', 'draw', 'over15', 'under25', 'over25', 'btts_yes', 'btts_no'
        value_threshold: float, e.g., 1.05 (bet when Model_Prob * Bookie_Odds > threshold)
        initial_bankroll: float, e.g., 1000.0
        staking_rule: 'fixed', 'proportional', 'kelly'
        stake_value: float (fixed amount, % of bankroll, or kelly multiplier)
        odds_source: 'B365' or 'Avg' or 'Max'
        """
        # 1. Load data for all selected leagues
        all_matches = []
        for league_code in leagues:
            df = load_league_data(league_code, start_date='2020-08-01', data_source=data_source, api_key=futpython_api_key) # Load from 2020 to populate form
            if not df.empty:
                with open('C:\\Users\\Gustavo\\.gemini\\antigravity\\scratch\\columns.txt', 'w') as f:
                    f.write(','.join(df.columns.tolist()))
                all_matches.append(df)
                
        if not all_matches:
            return {"error": "Nenhum dado encontrado para as ligas selecionadas."}
            
        # Combine all matches and sort chronologically
        combined_df = pd.concat(all_matches, ignore_index=True)
        combined_df = combined_df.sort_values(by=['Date', 'Time']).reset_index(drop=True)
        
        # 2. Setup state trackers for rolling form (Chronological O(M) simulation)
        # We track goals scored and conceded for home and away separately
        team_home_scored = defaultdict(list)
        team_home_conceded = defaultdict(list)
        team_away_scored = defaultdict(list)
        team_away_conceded = defaultdict(list)
        
        # Track HT goals
        team_home_scored_ht = defaultdict(list)
        team_home_conceded_ht = defaultdict(list)
        team_away_scored_ht = defaultdict(list)
        team_away_conceded_ht = defaultdict(list)
        league_home_goals_ht = defaultdict(list)
        league_away_goals_ht = defaultdict(list)
        
        # Track Shots on Target (SOT) for home and away separately
        team_home_sot = defaultdict(list)
        team_home_sot_conceded = defaultdict(list)
        team_away_sot = defaultdict(list)
        team_away_sot_conceded = defaultdict(list)
        
        # Track Expected Goals (xG)
        team_home_xg = defaultdict(list)
        team_home_xg_conceded = defaultdict(list)
        team_away_xg = defaultdict(list)
        team_away_xg_conceded = defaultdict(list)
        
        # Track league-wide goals and SOT
        team_home_xg = defaultdict(list)
        team_home_xg_conceded = defaultdict(list)
        team_away_xg = defaultdict(list)
        team_away_xg_conceded = defaultdict(list)
        
        league_home_goals = defaultdict(list)
        league_away_goals = defaultdict(list)
        league_home_sot = defaultdict(list)
        league_away_sot = defaultdict(list)
        league_home_xg = defaultdict(list)
        league_away_xg = defaultdict(list)
        league_home_xg = defaultdict(list)
        league_away_xg = defaultdict(list)
        
        # Setup markets list
        markets_list = [market] if isinstance(market, str) else market

        # Backtest statistics
        bankroll = initial_bankroll
        peak_bankroll = initial_bankroll
        max_drawdown = 0.0
        
        # Parallel bankrolls for multigestão comparison
        bankroll_fixed = initial_bankroll
        bankroll_proportional = initial_bankroll
        bankroll_kelly = initial_bankroll
        
        equity_curve_fixed = [{'date': start_date, 'bankroll': round(initial_bankroll, 2)}]
        equity_curve_proportional = [{'date': start_date, 'bankroll': round(initial_bankroll, 2)}]
        equity_curve_kelly = [{'date': start_date, 'bankroll': round(initial_bankroll, 2)}]
        
        # Track statistics for each staking method to return alternative summaries
        peak_fixed = initial_bankroll
        max_dd_fixed = 0.0
        current_dd_duration_fixed = 0
        max_dd_duration_fixed = 0
        bets_fixed = 0
        wins_fixed = 0
        staked_fixed = 0.0
        
        peak_prop = initial_bankroll
        max_dd_prop = 0.0
        current_dd_duration_prop = 0
        max_dd_duration_prop = 0
        bets_prop = 0
        wins_prop = 0
        staked_prop = 0.0
        
        peak_kelly = initial_bankroll
        max_dd_kelly = 0.0
        current_dd_duration_kelly = 0
        max_dd_duration_kelly = 0
        bets_kelly = 0
        wins_kelly = 0
        staked_kelly = 0.0
        
        bets_record = []
        cumulative_profit = 0.0
        total_staked = 0.0
        
        # Date boundaries
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        poisson = PoissonModel()
        elo_tracker = EloTracker(k_factor=20, home_advantage=65)
        league_rho_cache = {}  # Cache rho per league
        league_goals_for_rho = defaultdict(lambda: {'h': [], 'a': [], 'lh': [], 'la': []})
        daily_exposure = defaultdict(float)  # Track daily total stake exposure
        daily_bet_count = defaultdict(int)  # Track number of bets per day
        
        last_match_date = {}
        season_points = defaultdict(lambda: defaultdict(int))
        season_games = defaultdict(lambda: defaultdict(int))
        
        # 3. Chronological iteration
        for row in combined_df.to_dict('records'):
            match_date = row['Date']
            league_code = row['LeagueCode']
            home_team = row['HomeTeam']
            away_team = row['AwayTeam']
            fthg = row['FTHG']
            ftag = row['FTAG']
            ftr = row['FTR']
            
            # HT Goals extraction
            hthg = row.get('HTHG')
            htag = row.get('HTAG')
            if pd.isna(hthg) or pd.isna(htag):
                # Fallback to 45% of full-time goals if HT data is completely missing
                hthg = fthg * 0.45 if not pd.isna(fthg) else 0.0
                htag = ftag * 0.45 if not pd.isna(ftag) else 0.0
            
            # Skip matches that haven't been played yet (missing scores)
            if pd.isna(fthg) or pd.isna(ftag):
                continue
                
            # Warm up ratings only (skip heavy model calculations) if match is before backtest window
            hst = row.get('HST')
            ast = row.get('AST')
            hxg = row.get('HomeXG')
            axg = row.get('AwayXG')
            
            # xG Fallback logic
            if pd.isna(hxg) or hxg == 0:
                hxg = (hst * 0.33) if not pd.isna(hst) else (fthg * 0.9)
            if pd.isna(axg) or axg == 0:
                axg = (ast * 0.33) if not pd.isna(ast) else (ftag * 0.9)
                
            # Calculate rest days (fatigue)
            current_dt = pd.to_datetime(match_date)
            home_last = last_match_date.get(home_team)
            away_last = last_match_date.get(away_team)
            rest_days_home = min(15, (current_dt - home_last).days) if home_last else 10
            rest_days_away = min(15, (current_dt - away_last).days) if away_last else 10
            
            # Save/update last match date
            last_match_date[home_team] = current_dt
            last_match_date[away_team] = current_dt
            
            # Calculate motivation/urgency based on standings
            season_key = (league_code, row.get('Season', 'All'))
            motivation_home = self._calculate_motivation(season_points[season_key], home_team, season_games[season_key])
            motivation_away = self._calculate_motivation(season_points[season_key], away_team, season_games[season_key])
            
            # Update points and games in standings (for future matches)
            if home_team not in season_points[season_key]:
                season_points[season_key][home_team] = 0
                season_games[season_key][home_team] = 0
            if away_team not in season_points[season_key]:
                season_points[season_key][away_team] = 0
                season_games[season_key][away_team] = 0
                
            season_games[season_key][home_team] += 1
            season_games[season_key][away_team] += 1
            
            if ftr == 'H':
                season_points[season_key][home_team] += 3
            elif ftr == 'A':
                season_points[season_key][away_team] += 3
            elif ftr == 'D':
                season_points[season_key][home_team] += 1
                season_points[season_key][away_team] += 1
                
            if match_date < start_dt:
                self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                                  league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                                  team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                                  league_home_sot, league_away_sot, hst, ast,
                                  team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                                  league_home_xg, league_away_xg, hxg, axg,
                                  team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                                  league_home_goals_ht, league_away_goals_ht, hthg, htag)
                continue
                
            # Map odds columns based on source
            if odds_source == 'B365':
                odds_h = row.get('B365H')
                odds_d = row.get('B365D')
                odds_a = row.get('B365A')
                odds_over25 = row.get('B365>2.5')
                odds_under25 = row.get('B365<2.5')
            elif odds_source == 'Avg':
                odds_h = row.get('AvgH')
                odds_d = row.get('AvgD')
                odds_a = row.get('AvgA')
                odds_over25 = row.get('Avg>2.5')
                odds_under25 = row.get('Avg<2.5')
            else: # Max
                odds_h = row.get('MaxH')
                odds_d = row.get('MaxD')
                odds_a = row.get('MaxA')
                odds_over25 = row.get('Max>2.5')
                odds_under25 = row.get('Max<2.5')
                
            # Pinnacle closing line odds for CLV calculation
            closing_odds_h = row.get('PSCH', row.get('PSH', row.get('MaxCH')))
            closing_odds_d = row.get('PSCD', row.get('PSD', row.get('MaxCD')))
            closing_odds_a = row.get('PSCA', row.get('PSA', row.get('MaxCA')))
            closing_odds_over25 = row.get('PC>2.5', row.get('MaxC>2.5'))
            closing_odds_under25 = row.get('PC<2.5', row.get('MaxC<2.5'))
            
            # Synthetic closing odds for DNB
            closing_odds_dnb_h = closing_odds_h * (closing_odds_d - 1.0) / closing_odds_d if (closing_odds_h and closing_odds_d and closing_odds_d > 1.0 and not pd.isna(closing_odds_h) and not pd.isna(closing_odds_d)) else np.nan
            closing_odds_dnb_a = closing_odds_a * (closing_odds_d - 1.0) / closing_odds_d if (closing_odds_a and closing_odds_d and closing_odds_d > 1.0 and not pd.isna(closing_odds_a) and not pd.isna(closing_odds_d)) else np.nan
            
            # Closing line for AH
            closing_line = row.get('AHCh', row.get('AHh'))
            if pd.isna(closing_line):
                closing_line = 0.0
            closing_odds_ah_h = row.get('PCAHH', row.get('AvgCAHH'))
            closing_odds_ah_a = row.get('PCAHA', row.get('AvgCAHA'))
            
            # Fallback for closing AH if they are NaN
            if pd.isna(closing_odds_ah_h) or pd.isna(closing_odds_ah_a):
                if closing_line == 0.0:
                    closing_odds_ah_h = closing_odds_dnb_h
                    closing_odds_ah_a = closing_odds_dnb_a
                elif closing_line == -0.5:
                    closing_odds_ah_h = closing_odds_h
                    closing_odds_ah_a = 1.0 / (1.0/closing_odds_d + 1.0/closing_odds_a) if (closing_odds_d and closing_odds_a and closing_odds_d > 1.0 and closing_odds_a > 1.0 and not pd.isna(closing_odds_d) and not pd.isna(closing_odds_a)) else np.nan
                elif closing_line == 0.5:
                    closing_odds_ah_h = 1.0 / (1.0/closing_odds_h + 1.0/closing_odds_d) if (closing_odds_h and closing_odds_d and closing_odds_h > 1.0 and closing_odds_d > 1.0 and not pd.isna(closing_odds_h) and not pd.isna(closing_odds_d)) else np.nan
                    closing_odds_ah_a = closing_odds_a
                else:
                    closing_odds_ah_h = np.nan
                    closing_odds_ah_a = np.nan
            # Shots and xG already fetched above
            
            # If standard odds are missing, we cannot proceed with this match
            if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
                # Still record the match result in team histories to keep form up-to-date!
                self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                                  league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                                  team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                                  league_home_sot, league_away_sot, hst, ast,
                                  team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                                  league_home_xg, league_away_xg, hxg, axg,
                                  team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                                  league_home_goals_ht, league_away_goals_ht, hthg, htag)
                continue
                
            # Compute predictive probabilities
            # To avoid bias, we calculate ratings using team history BEFORE this match
            h_xg_att = 1.0
            h_xg_def = 1.0
            a_xg_att = 1.0
            a_xg_def = 1.0
            
            h_scored = team_home_scored[home_team][-self.rolling_games:]
            h_conceded = team_home_conceded[home_team][-self.rolling_games:]
            a_scored = team_away_scored[away_team][-self.rolling_games:]
            a_conceded = team_away_conceded[away_team][-self.rolling_games:]
            
            leg_h_goals = league_home_goals[league_code][-100:] # Last 100 league games
            leg_a_goals = league_away_goals[league_code][-100:]
            
            # Fallback to defaults if no history
            avg_h_goals = np.mean(leg_h_goals) if leg_h_goals else 1.35
            avg_a_goals = np.mean(leg_a_goals) if leg_a_goals else 1.05
            
            h_att = (weighted_mean(h_scored, 0.06) / avg_h_goals) if h_scored else 1.0
            h_def = (weighted_mean(h_conceded, 0.06) / avg_a_goals) if h_conceded else 1.0
            a_att = (weighted_mean(a_scored, 0.06) / avg_a_goals) if a_scored else 1.0
            a_def = (weighted_mean(a_conceded, 0.06) / avg_h_goals) if a_conceded else 1.0
            
            # Verify and cap
            h_att = 1.0 if pd.isna(h_att) else max(0.2, min(4.0, h_att))
            h_def = 1.0 if pd.isna(h_def) else max(0.2, min(4.0, h_def))
            a_att = 1.0 if pd.isna(a_att) else max(0.2, min(4.0, a_att))
            a_def = 1.0 if pd.isna(a_def) else max(0.2, min(4.0, a_def))
            
            lambda_goals_home = avg_h_goals * h_att * a_def
            lambda_goals_away = avg_a_goals * a_att * h_def
            
            # HT Goals lambda
            h_scored_ht = team_home_scored_ht[home_team][-self.rolling_games:]
            h_conceded_ht = team_home_conceded_ht[home_team][-self.rolling_games:]
            a_scored_ht = team_away_scored_ht[away_team][-self.rolling_games:]
            a_conceded_ht = team_away_conceded_ht[away_team][-self.rolling_games:]
            
            leg_h_goals_ht = league_home_goals_ht[league_code][-100:]
            leg_a_goals_ht = league_away_goals_ht[league_code][-100:]
            
            avg_h_goals_ht = np.mean(leg_h_goals_ht) if leg_h_goals_ht else (avg_h_goals * 0.45)
            avg_a_goals_ht = np.mean(leg_a_goals_ht) if leg_a_goals_ht else (avg_a_goals * 0.45)
            
            if avg_h_goals_ht == 0: avg_h_goals_ht = 0.6
            if avg_a_goals_ht == 0: avg_a_goals_ht = 0.45
            
            h_att_ht = (weighted_mean(h_scored_ht, 0.06) / avg_h_goals_ht) if h_scored_ht else 1.0
            h_def_ht = (weighted_mean(h_conceded_ht, 0.06) / avg_a_goals_ht) if h_conceded_ht else 1.0
            a_att_ht = (weighted_mean(a_scored_ht, 0.06) / avg_a_goals_ht) if a_scored_ht else 1.0
            a_def_ht = (weighted_mean(a_conceded_ht, 0.06) / avg_h_goals_ht) if a_conceded_ht else 1.0
            
            h_att_ht = 1.0 if pd.isna(h_att_ht) else max(0.2, min(4.0, h_att_ht))
            h_def_ht = 1.0 if pd.isna(h_def_ht) else max(0.2, min(4.0, h_def_ht))
            a_att_ht = 1.0 if pd.isna(a_att_ht) else max(0.2, min(4.0, a_att_ht))
            a_def_ht = 1.0 if pd.isna(a_def_ht) else max(0.2, min(4.0, a_def_ht))
            
            lambda_home_ht = avg_h_goals_ht * h_att_ht * a_def_ht
            lambda_away_ht = avg_a_goals_ht * a_att_ht * h_def_ht

            # Gratefully blend with SOT expected goals if shot data is available
            h_sot_scored = team_home_sot[home_team][-self.rolling_games:]
            h_sot_conceded = team_home_sot_conceded[home_team][-self.rolling_games:]
            a_sot_scored = team_away_sot[away_team][-self.rolling_games:]
            a_sot_conceded = team_away_sot_conceded[away_team][-self.rolling_games:]
            
            leg_h_sot = league_home_sot[league_code][-100:]
            leg_a_sot = league_away_sot[league_code][-100:]
            
            has_sot_data = (h_sot_scored and h_sot_conceded and a_sot_scored and a_sot_conceded and leg_h_sot and leg_a_sot)
            
            if has_sot_data:
                avg_h_sot = np.mean(leg_h_sot)
                avg_a_sot = np.mean(leg_a_sot)
                
                # Check for division by zero or NaN
                if pd.isna(avg_h_sot) or avg_h_sot == 0: avg_h_sot = 4.5
                if pd.isna(avg_a_sot) or avg_a_sot == 0: avg_a_sot = 3.5
                
                h_sot_att = (weighted_mean(h_sot_scored, 0.06) / avg_h_sot) if h_sot_scored else 1.0
                h_sot_def = (weighted_mean(h_sot_conceded, 0.06) / avg_a_sot) if h_sot_conceded else 1.0
                a_sot_att = (weighted_mean(a_sot_scored, 0.06) / avg_a_sot) if a_sot_scored else 1.0
                a_sot_def = (weighted_mean(a_sot_conceded, 0.06) / avg_h_sot) if a_sot_conceded else 1.0
                
                # Verify and cap SOT ratings
                h_sot_att = 1.0 if pd.isna(h_sot_att) else max(0.2, min(4.0, h_sot_att))
                h_sot_def = 1.0 if pd.isna(h_sot_def) else max(0.2, min(4.0, h_sot_def))
                a_sot_att = 1.0 if pd.isna(a_sot_att) else max(0.2, min(4.0, a_sot_att))
                a_sot_def = 1.0 if pd.isna(a_sot_def) else max(0.2, min(4.0, a_sot_def))
                
                exp_sot_home = avg_h_sot * h_sot_att * a_sot_def
                exp_sot_away = avg_a_sot * a_sot_att * h_sot_def
                
                # Goals per SOT
                conversion_home = avg_h_goals / avg_h_sot
                conversion_away = avg_a_goals / avg_a_sot
                
                lambda_shots_home = exp_sot_home * conversion_home
                lambda_shots_away = exp_sot_away * conversion_away
                
                # Cap project shots-based lambda
                lambda_shots_home = max(0.1, min(5.0, lambda_shots_home))
                lambda_shots_away = max(0.1, min(5.0, lambda_shots_away))
                
                # Calculate Expected Goals (xG) based lambda
                h_xg_scored = team_home_xg[home_team][-self.rolling_games:]
                h_xg_conceded = team_home_xg_conceded[home_team][-self.rolling_games:]
                a_xg_scored = team_away_xg[away_team][-self.rolling_games:]
                a_xg_conceded = team_away_xg_conceded[away_team][-self.rolling_games:]
                
                leg_h_xg = league_home_xg[league_code][-100:]
                leg_a_xg = league_away_xg[league_code][-100:]
                
                has_xg_data = (h_xg_scored and h_xg_conceded and a_xg_scored and a_xg_conceded and leg_h_xg and leg_a_xg)
                if has_xg_data:
                    avg_h_xg = np.mean(leg_h_xg)
                    avg_a_xg = np.mean(leg_a_xg)
                    if pd.isna(avg_h_xg) or avg_h_xg == 0: avg_h_xg = 1.35
                    if pd.isna(avg_a_xg) or avg_a_xg == 0: avg_a_xg = 1.05
                    
                    h_xg_att = (weighted_mean(h_xg_scored, 0.06) / avg_h_xg) if h_xg_scored else 1.0
                    h_xg_def = (weighted_mean(h_xg_conceded, 0.06) / avg_a_xg) if h_xg_conceded else 1.0
                    a_xg_att = (weighted_mean(a_xg_scored, 0.06) / avg_a_xg) if a_xg_scored else 1.0
                    a_xg_def = (weighted_mean(a_xg_conceded, 0.06) / avg_h_xg) if a_xg_conceded else 1.0
                    
                    h_xg_att = 1.0 if pd.isna(h_xg_att) else max(0.2, min(4.0, h_xg_att))
                    h_xg_def = 1.0 if pd.isna(h_xg_def) else max(0.2, min(4.0, h_xg_def))
                    a_xg_att = 1.0 if pd.isna(a_xg_att) else max(0.2, min(4.0, a_xg_att))
                    a_xg_def = 1.0 if pd.isna(a_xg_def) else max(0.2, min(4.0, a_xg_def))
                    
                    lambda_xg_home = avg_h_xg * h_xg_att * a_xg_def
                    lambda_xg_away = avg_a_xg * a_xg_att * h_xg_def
                    
                    lambda_xg_home = max(0.1, min(5.0, lambda_xg_home))
                    lambda_xg_away = max(0.1, min(5.0, lambda_xg_away))
                    
                    # BLEND: 50% xG, 30% Shots, 20% Goals
                    lambda_home = 0.50 * lambda_xg_home + 0.30 * lambda_shots_home + 0.20 * lambda_goals_home
                    lambda_away = 0.50 * lambda_xg_away + 0.30 * lambda_shots_away + 0.20 * lambda_goals_away
                else:
                    # BLEND: 60% Goals, 40% Shots
                    lambda_home = 0.60 * lambda_goals_home + 0.40 * lambda_shots_home
                    lambda_away = 0.60 * lambda_goals_away + 0.40 * lambda_shots_away
                
                # Apply Elo-based adjustment to lambdas
                elo_factor_h = elo_tracker.get_elo_factor(home_team, away_team)
                elo_factor_a = 2.0 - elo_factor_h
                lambda_home *= elo_factor_h
                lambda_away *= elo_factor_a
            else:
                lambda_home = lambda_goals_home
                lambda_away = lambda_goals_away
                # Apply Elo-based adjustment to lambdas (goals only)
                elo_factor_h = elo_tracker.get_elo_factor(home_team, away_team)
                elo_factor_a = 2.0 - elo_factor_h
                lambda_home *= elo_factor_h
                lambda_away *= elo_factor_a
            
            # Predict outcome probabilities
            max_goals = 8
            home_probs = [math.exp(-lambda_home) * (lambda_home**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
            away_probs = [math.exp(-lambda_away) * (lambda_away**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
            
            # Compute joint probabilities
            prob_matrix = np.outer(home_probs, away_probs)
            
            # Dynamic rho estimation per league
            if league_code in league_rho_cache:
                rho = league_rho_cache[league_code]
            else:
                rho_data = league_goals_for_rho[league_code]
                rho = estimate_dynamic_rho(rho_data['h'], rho_data['a'], rho_data['lh'], rho_data['la'])
                league_rho_cache[league_code] = rho
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
            
            prob_h = float(np.sum(np.tril(prob_matrix, -1))) # x > y (Home Win)
            prob_d = float(np.sum(np.diag(prob_matrix)))     # x == y (Draw)
            prob_a = float(np.sum(np.triu(prob_matrix, 1)))  # x < y (Away Win)
            
            prob_over_25 = 0.0
            prob_over_15 = 0.0
            prob_over_35 = 0.0
            prob_over_45 = 0.0
            prob_over_55 = 0.0
            for x in range(max_goals + 1):
                for y in range(max_goals + 1):
                    tot = x + y
                    if tot > 2: prob_over_25 += prob_matrix[x, y]
                    if tot > 1: prob_over_15 += prob_matrix[x, y]
                    if tot > 3: prob_over_35 += prob_matrix[x, y]
                    if tot > 4: prob_over_45 += prob_matrix[x, y]
                    if tot > 5: prob_over_55 += prob_matrix[x, y]
            
            prob_btts_yes = float((1.0 - home_probs[0]) * (1.0 - away_probs[0]))
            
            # HT Probabilities
            home_probs_ht = [math.exp(-lambda_home_ht) * (lambda_home_ht**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
            away_probs_ht = [math.exp(-lambda_away_ht) * (lambda_away_ht**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
            prob_matrix_ht = np.outer(home_probs_ht, away_probs_ht)
            
            tau_00_ht = 1.0 - lambda_home_ht * lambda_away_ht * rho
            tau_10_ht = 1.0 + lambda_away_ht * rho
            tau_01_ht = 1.0 + lambda_home_ht * rho
            tau_11_ht = 1.0 - rho
            prob_matrix_ht[0, 0] *= max(0.0, tau_00_ht)
            prob_matrix_ht[1, 0] *= max(0.0, tau_10_ht)
            prob_matrix_ht[0, 1] *= max(0.0, tau_01_ht)
            prob_matrix_ht[1, 1] *= max(0.0, tau_11_ht)
            matrix_sum_ht = np.sum(prob_matrix_ht)
            if matrix_sum_ht > 0:
                prob_matrix_ht = prob_matrix_ht / matrix_sum_ht
                
            prob_h_ht = float(np.sum(np.tril(prob_matrix_ht, -1)))
            prob_d_ht = float(np.sum(np.diag(prob_matrix_ht)))
            prob_a_ht = float(np.sum(np.triu(prob_matrix_ht, 1)))
            prob_over_05_ht = 1.0 - float(prob_matrix_ht[0, 0])
            prob_over_15_ht = 0.0
            for x in range(max_goals + 1):
                for y in range(max_goals + 1):
                    if x + y > 1: prob_over_15_ht += prob_matrix_ht[x, y]
            
            # Lazy loading of estimated odds from the solver
            est_odds = None
            
            # Evaluate each selected market for this match
            for mkt in markets_list:
                # Decide market to evaluate
                model_prob = 0.0
                bookie_odds = np.nan
                bet_won = False
                market_label = ""
                result_factor = -1.0

                if mkt in ('home', '1x2_home'):
                    model_prob = prob_h
                    bookie_odds = odds_h
                    bet_won = (ftr == 'H')
                    market_label = "1 (Mandante)"
                elif mkt in ('away', '1x2_away'):
                    model_prob = prob_a
                    bookie_odds = odds_a
                    bet_won = (ftr == 'A')
                    market_label = "2 (Visitante)"
                elif mkt in ('draw', '1x2_draw'):
                    model_prob = prob_d
                    bookie_odds = odds_d
                    bet_won = (ftr == 'D')
                    market_label = "X (Empate)"
                elif mkt == 'over25':
                    model_prob = prob_over_25
                    bookie_odds = odds_over25
                    bet_won = (fthg + ftag > 2)
                    market_label = "Over 2.5"
                elif mkt == 'under25':
                    model_prob = 1.0 - prob_over_25
                    bookie_odds = odds_under25
                    bet_won = (fthg + ftag < 3)
                    market_label = "Under 2.5"
                elif mkt == 'ht_home':
                    model_prob = prob_h_ht
                    bookie_odds = 1.0 / (prob_h_ht + 0.035) if (prob_h_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg > htag)
                    market_label = "HT Mandante"
                elif mkt == 'ht_draw':
                    model_prob = prob_d_ht
                    bookie_odds = 1.0 / (prob_d_ht + 0.035) if (prob_d_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg == htag)
                    market_label = "HT Empate"
                elif mkt == 'ht_away':
                    model_prob = prob_a_ht
                    bookie_odds = 1.0 / (prob_a_ht + 0.035) if (prob_a_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg < htag)
                    market_label = "HT Visitante"
                elif mkt == 'ht_over05':
                    model_prob = prob_over_05_ht
                    bookie_odds = 1.0 / (prob_over_05_ht + 0.035) if (prob_over_05_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg + htag > 0)
                    market_label = "HT Over 0.5"
                elif mkt == 'ht_under05':
                    model_prob = 1.0 - prob_over_05_ht
                    bookie_odds = 1.0 / ((1.0 - prob_over_05_ht) + 0.035) if ((1.0 - prob_over_05_ht) + 0.035) > 0 else 1.01
                    bet_won = (hthg + htag == 0)
                    market_label = "HT Under 0.5"
                elif mkt == 'ht_over15':
                    model_prob = prob_over_15_ht
                    bookie_odds = 1.0 / (prob_over_15_ht + 0.035) if (prob_over_15_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg + htag > 1)
                    market_label = "HT Over 1.5"
                elif mkt == 'ht_under15':
                    model_prob = 1.0 - prob_over_15_ht
                    bookie_odds = 1.0 / ((1.0 - prob_over_15_ht) + 0.035) if ((1.0 - prob_over_15_ht) + 0.035) > 0 else 1.01
                    bet_won = (hthg + htag <= 1)
                    market_label = "HT Under 1.5"
                elif mkt == 'over15':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = prob_over_15
                    bookie_odds = est_odds['bookie_over_15']
                    bet_won = (fthg + ftag > 1)
                    market_label = "Over 1.5"
                elif mkt == 'over35':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = prob_over_35
                    bookie_odds = est_odds['bookie_over_35']
                    bet_won = (fthg + ftag > 3)
                    market_label = "Over 3.5"
                elif mkt == 'under35':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = 1.0 - prob_over_35
                    bookie_odds = est_odds['bookie_under_35']
                    bet_won = (fthg + ftag < 4)
                    market_label = "Under 3.5"
                elif mkt == 'over45':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = prob_over_45
                    bookie_odds = est_odds['bookie_over_45']
                    bet_won = (fthg + ftag > 4)
                    market_label = "Over 4.5"
                elif mkt == 'under45':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = 1.0 - prob_over_45
                    bookie_odds = est_odds['bookie_under_45']
                    bet_won = (fthg + ftag < 5)
                    market_label = "Under 4.5"
                elif mkt == 'over55':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = prob_over_55
                    bookie_odds = est_odds['bookie_over_55']
                    bet_won = (fthg + ftag > 5)
                    market_label = "Over 5.5"
                elif mkt == 'under55':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = 1.0 - prob_over_55
                    bookie_odds = est_odds['bookie_under_55']
                    bet_won = (fthg + ftag < 6)
                    market_label = "Under 5.5"
                elif mkt == 'lay_home':
                    model_prob = prob_d + prob_a
                    bookie_odds = 1.0 / (1.0/odds_d + 1.0/odds_a) if (odds_d > 1.0 and odds_a > 1.0) else np.nan
                    bet_won = (ftr != 'H')
                    market_label = "Contra Mandante (X2)"
                elif mkt == 'lay_away':
                    model_prob = prob_h + prob_d
                    bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan
                    bet_won = (ftr != 'A')
                    market_label = "Contra Visitante (1X)"
                elif mkt == 'lay_draw':
                    model_prob = prob_h + prob_a
                    bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_a) if (odds_h > 1.0 and odds_a > 1.0) else np.nan
                    bet_won = (ftr != 'D')
                    market_label = "Contra Empate (12)"
                elif mkt == 'btts_yes':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = prob_btts_yes
                    
                    actual_odd = row.get('BTTS_Yes', np.nan)
                    try:
                        parsed_odd = float(str(actual_odd).replace(',', '.')) if not pd.isna(actual_odd) else np.nan
                        bookie_odds = parsed_odd if 1.0 < parsed_odd < 10.0 else est_odds['bookie_btts_yes']
                    except Exception:
                        bookie_odds = est_odds['bookie_btts_yes']
                        
                    bet_won = (fthg > 0 and ftag > 0)
                    market_label = "BTTS Sim"
                elif mkt == 'btts_no':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = 1.0 - prob_btts_yes
                    
                    actual_odd = row.get('BTTS_No', np.nan)
                    try:
                        parsed_odd = float(str(actual_odd).replace(',', '.')) if not pd.isna(actual_odd) else np.nan
                        bookie_odds = parsed_odd if 1.0 < parsed_odd < 10.0 else est_odds['bookie_btts_no']
                    except Exception:
                        bookie_odds = est_odds['bookie_btts_no']
                        
                    bet_won = (fthg == 0 or ftag == 0)
                    market_label = "BTTS Não"
                elif mkt.startswith('cs_'):
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    if mkt == 'cs_10':
                        model_prob = float(prob_matrix[1, 0])
                        bookie_odds = est_odds['bookie_cs_10']
                        bet_won = (fthg == 1 and ftag == 0)
                        market_label = "Placar Exato 1-0"
                    elif mkt == 'cs_20':
                        model_prob = float(prob_matrix[2, 0])
                        bookie_odds = est_odds['bookie_cs_20']
                        bet_won = (fthg == 2 and ftag == 0)
                        market_label = "Placar Exato 2-0"
                    elif mkt == 'cs_21':
                        model_prob = float(prob_matrix[2, 1])
                        bookie_odds = est_odds['bookie_cs_21']
                        bet_won = (fthg == 2 and ftag == 1)
                        market_label = "Placar Exato 2-1"
                    elif mkt == 'cs_00':
                        model_prob = float(prob_matrix[0, 0])
                        bookie_odds = est_odds['bookie_cs_00']
                        bet_won = (fthg == 0 and ftag == 0)
                        market_label = "Placar Exato 0-0"
                    elif mkt == 'cs_11':
                        model_prob = float(prob_matrix[1, 1])
                        bookie_odds = est_odds['bookie_cs_11']
                        bet_won = (fthg == 1 and ftag == 1)
                        market_label = "Placar Exato 1-1"
                    elif mkt == 'cs_01':
                        model_prob = float(prob_matrix[0, 1])
                        bookie_odds = est_odds['bookie_cs_01']
                        bet_won = (fthg == 0 and ftag == 1)
                        market_label = "Placar Exato 0-1"
                    elif mkt == 'cs_02':
                        model_prob = float(prob_matrix[0, 2])
                        bookie_odds = est_odds['bookie_cs_02']
                        bet_won = (fthg == 0 and ftag == 2)
                        market_label = "Placar Exato 0-2"
                    elif mkt == 'cs_12':
                        model_prob = float(prob_matrix[1, 2])
                        bookie_odds = est_odds['bookie_cs_12']
                        bet_won = (fthg == 1 and ftag == 2)
                        market_label = "Placar Exato 1-2"
                    elif mkt.startswith('lay_cs_'):
                        if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                        cs_code = mkt.replace('lay_', '')
                        
                        if cs_code == 'cs_10':
                            back_prob = float(prob_matrix[1, 0])
                            back_odds = est_odds['bookie_cs_10']
                            is_cs = (fthg == 1 and ftag == 0)
                            market_label = "Lay Placar Exato 1-0"
                        elif cs_code == 'cs_20':
                            back_prob = float(prob_matrix[2, 0])
                            back_odds = est_odds['bookie_cs_20']
                            is_cs = (fthg == 2 and ftag == 0)
                            market_label = "Lay Placar Exato 2-0"
                        elif cs_code == 'cs_21':
                            back_prob = float(prob_matrix[2, 1])
                            back_odds = est_odds['bookie_cs_21']
                            is_cs = (fthg == 2 and ftag == 1)
                            market_label = "Lay Placar Exato 2-1"
                        elif cs_code == 'cs_00':
                            back_prob = float(prob_matrix[0, 0])
                            back_odds = est_odds['bookie_cs_00']
                            is_cs = (fthg == 0 and ftag == 0)
                            market_label = "Lay Placar Exato 0-0"
                        elif cs_code == 'cs_11':
                            back_prob = float(prob_matrix[1, 1])
                            back_odds = est_odds['bookie_cs_11']
                            is_cs = (fthg == 1 and ftag == 1)
                            market_label = "Lay Placar Exato 1-1"
                        elif cs_code == 'cs_01':
                            back_prob = float(prob_matrix[0, 1])
                            back_odds = est_odds['bookie_cs_01']
                            is_cs = (fthg == 0 and ftag == 1)
                            market_label = "Lay Placar Exato 0-1"
                        elif cs_code == 'cs_02':
                            back_prob = float(prob_matrix[0, 2])
                            back_odds = est_odds['bookie_cs_02']
                            is_cs = (fthg == 0 and ftag == 2)
                            market_label = "Lay Placar Exato 0-2"
                        elif cs_code == 'cs_12':
                            back_prob = float(prob_matrix[1, 2])
                            back_odds = est_odds['bookie_cs_12']
                            is_cs = (fthg == 1 and ftag == 2)
                            market_label = "Lay Placar Exato 1-2"
                        
                        model_prob = 1.0 - back_prob
                        bookie_odds = 1.0 / (1.0 - 1.0/back_odds) if (back_odds > 1.0001) else np.nan
                        bet_won = not is_cs
                    elif mkt == 'dnb_h':
                        model_prob = prob_h / (prob_h + prob_a) if (prob_h + prob_a) > 0 else 0.5
                        odds_dnb_h_synth = odds_h * (odds_d - 1.0) / odds_d if (odds_h and odds_d and odds_d > 1.0) else np.nan
                        bookie_odds = odds_dnb_h_synth
                        
                        kelly_probs = [prob_h, prob_d, prob_a]
                        kelly_outcomes = [bookie_odds - 1.0, 0.0, -1.0] if not pd.isna(bookie_odds) else [0.0, 0.0, 0.0]
                        
                        if ftr == 'H':
                            result_factor = 1.0
                            bet_won = True
                        elif ftr == 'D':
                            result_factor = 0.0
                            bet_won = False
                        else:
                            result_factor = -1.0
                            bet_won = False
                        market_label = "DNB Mandante"
                        
                    elif mkt == 'dnb_a':
                        model_prob = prob_a / (prob_h + prob_a) if (prob_h + prob_a) > 0 else 0.5
                        odds_dnb_a_synth = odds_a * (odds_d - 1.0) / odds_d if (odds_a and odds_d and odds_d > 1.0) else np.nan
                        bookie_odds = odds_dnb_a_synth
                        
                        kelly_probs = [prob_a, prob_d, prob_h]
                        kelly_outcomes = [bookie_odds - 1.0, 0.0, -1.0] if not pd.isna(bookie_odds) else [0.0, 0.0, 0.0]
                        
                        if ftr == 'A':
                            result_factor = 1.0
                            bet_won = True
                        elif ftr == 'D':
                            result_factor = 0.0
                            bet_won = False
                        else:
                            result_factor = -1.0
                            bet_won = False
                        market_label = "DNB Visitante"
                        
                    elif mkt == 'ah_home':
                        line = row.get('AHh')
                        if pd.isna(line):
                            line = 0.0
                        if odds_source == 'B365':
                            odds_ah_h = row.get('B365AHH')
                            odds_ah_a = row.get('B365AHA')
                        elif odds_source == 'Avg':
                            odds_ah_h = row.get('AvgAHH')
                            odds_ah_a = row.get('AvgAHA')
                        else:
                            odds_ah_h = row.get('MaxAHH')
                            odds_ah_a = row.get('MaxAHA')
                            
                        if pd.isna(odds_ah_h) or pd.isna(odds_ah_a) or odds_ah_h <= 1.0:
                            if line == 0.0:
                                odds_ah_h = odds_h * (odds_d - 1.0) / odds_d if (odds_h and odds_d and odds_d > 1.0) else np.nan
                            elif line == -0.5:
                                odds_ah_h = odds_h
                            elif line == 0.5:
                                odds_ah_h = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h and odds_d and odds_h > 1.0 and odds_d > 1.0) else np.nan
                            else:
                                ah_probs_h = calculate_ah_probabilities(prob_matrix, line)
                                odds_ah_h = get_fair_ah_odds(ah_probs_h) / 1.05
                        bookie_odds = odds_ah_h
                        
                        ah_probs = calculate_ah_probabilities(prob_matrix, line)
                        expected_return_factor = (ah_probs['win'] * bookie_odds + 
                                                  ah_probs['half_win'] * (bookie_odds + 1.0) / 2.0 + 
                                                  ah_probs['push'] * 1.0 + 
                                                  ah_probs['half_loss'] * 0.5) if not pd.isna(bookie_odds) else 0.0
                        model_prob = expected_return_factor / bookie_odds if (not pd.isna(bookie_odds) and bookie_odds > 0.0) else 0.0
                        
                        kelly_probs = [ah_probs['win'], ah_probs['half_win'], ah_probs['push'], ah_probs['half_loss'], ah_probs['loss']]
                        kelly_outcomes = [bookie_odds - 1.0, (bookie_odds - 1.0) / 2.0, 0.0, -0.5, -1.0] if not pd.isna(bookie_odds) else [0.0, 0.0, 0.0, 0.0, 0.0]
                        
                        margin = float(fthg - ftag)
                        score = margin + line
                        score = round(score * 4) / 4
                        
                        if score >= 0.5:
                            result_factor = 1.0
                            bet_won = True
                        elif score == 0.25:
                            result_factor = 0.5
                            bet_won = True
                        elif score == 0.0:
                            result_factor = 0.0
                            bet_won = False
                        elif score == -0.25:
                            result_factor = -0.5
                            bet_won = False
                        else:
                            result_factor = -1.0
                            bet_won = False
                        market_label = f"AH Mandante ({'+' if line > 0 else ''}{line})"
                        
                    elif mkt == 'ah_away':
                        home_line = row.get('AHh')
                        if pd.isna(home_line):
                            line = 0.0
                        else:
                            line = -home_line
                        if odds_source == 'B365':
                            odds_ah_h = row.get('B365AHH')
                            odds_ah_a = row.get('B365AHA')
                        elif odds_source == 'Avg':
                            odds_ah_h = row.get('AvgAHH')
                            odds_ah_a = row.get('AvgAHA')
                        else:
                            odds_ah_h = row.get('MaxAHH')
                            odds_ah_a = row.get('MaxAHA')
                            
                        if pd.isna(odds_ah_h) or pd.isna(odds_ah_a) or odds_ah_a <= 1.0:
                            if line == 0.0:
                                odds_ah_a = odds_a * (odds_d - 1.0) / odds_d if (odds_a and odds_d and odds_d > 1.0) else np.nan
                            elif line == -0.5:
                                odds_ah_a = odds_a
                            elif line == 0.5:
                                odds_ah_a = 1.0 / (1.0/odds_a + 1.0/odds_d) if (odds_a and odds_d and odds_a > 1.0 and odds_d > 1.0) else np.nan
                            else:
                                ah_probs_a = calculate_ah_probabilities(prob_matrix, line)
                                odds_ah_a = get_fair_ah_odds(ah_probs_a) / 1.05
                        bookie_odds = odds_ah_a
                        
                        ah_probs = calculate_ah_probabilities(prob_matrix, line)
                        expected_return_factor = (ah_probs['win'] * bookie_odds + 
                                                  ah_probs['half_win'] * (bookie_odds + 1.0) / 2.0 + 
                                                  ah_probs['push'] * 1.0 + 
                                                  ah_probs['half_loss'] * 0.5) if not pd.isna(bookie_odds) else 0.0
                        model_prob = expected_return_factor / bookie_odds if (not pd.isna(bookie_odds) and bookie_odds > 0.0) else 0.0
                        
                        kelly_probs = [ah_probs['win'], ah_probs['half_win'], ah_probs['push'], ah_probs['half_loss'], ah_probs['loss']]
                        kelly_outcomes = [bookie_odds - 1.0, (bookie_odds - 1.0) / 2.0, 0.0, -0.5, -1.0] if not pd.isna(bookie_odds) else [0.0, 0.0, 0.0, 0.0, 0.0]
                        
                        margin = float(ftag - fthg)
                        score = margin + line
                        score = round(score * 4) / 4
                        
                        if score >= 0.5:
                            result_factor = 1.0
                            bet_won = True
                        elif score == 0.25:
                            result_factor = 0.5
                            bet_won = True
                        elif score == 0.0:
                            result_factor = 0.0
                            bet_won = False
                        elif score == -0.25:
                            result_factor = -0.5
                            bet_won = False
                        else:
                            result_factor = -1.0
                            bet_won = False
                        market_label = f"AH Visitante ({'+' if line > 0 else ''}{line})"

                if mkt not in ('dnb_h', 'dnb_a', 'ah_home', 'ah_away'):
                    result_factor = 1.0 if bet_won else -1.0

                model_prob = float(model_prob)
                
                # Assemble ML Features
                elo_diff = float(elo_factor_h - elo_factor_a)
                features = [
                    float(lambda_home), float(lambda_away),
                    float(h_att), float(h_def), float(a_att), float(a_def),
                    elo_diff, model_prob,
                    float(h_xg_att), float(h_xg_def), float(a_xg_att), float(a_xg_def),
                    float(rest_days_home), float(rest_days_away),
                    float(motivation_home), float(motivation_away)
                ]
                
                # 1. Ensemble Blending
                if use_ml and mkt in self.ml_ensembles and self.ml_ensembles[mkt].is_fitted:
                    ml_prob = self.ml_ensembles[mkt].predict_proba(features)
                    if ml_prob is not None:
                        model_prob = (model_prob + ml_prob) / 2.0
                        
                raw_prob = model_prob

                # 2. Apply Platt Calibration
                if mkt in self.calibrators:
                    model_prob = self.calibrators[mkt].calibrate(model_prob)
                    
                # 3. Store History
                if use_ml:
                    self.ml_history[mkt]['X'].append(features)
                    self.ml_history[mkt]['y'].append(1 if bet_won else 0)
                
                self.calibration_history[mkt]['probs'].append(raw_prob)
                self.calibration_history[mkt]['outcomes'].append(1 if bet_won else 0)

                # If match date is within our backtest active window, evaluate betting
                if start_dt <= match_date <= end_dt:
                    # We can place a bet if odds are valid and we have a "+EV" (positive expected value) edge
                    if not pd.isna(bookie_odds) and bookie_odds > 1.0:
                        # Cross-market odds filtering
                        if min_odds_h is not None and not pd.isna(odds_h) and odds_h < min_odds_h: continue
                        if max_odds_h is not None and not pd.isna(odds_h) and odds_h > max_odds_h: continue
                        if min_odds_d is not None and not pd.isna(odds_d) and odds_d < min_odds_d: continue
                        if max_odds_d is not None and not pd.isna(odds_d) and odds_d > max_odds_d: continue
                        if min_odds_a is not None and not pd.isna(odds_a) and odds_a < min_odds_a: continue
                        if max_odds_a is not None and not pd.isna(odds_a) and odds_a > max_odds_a: continue
                        if min_odds_over25 is not None and not pd.isna(odds_over25) and odds_over25 < min_odds_over25: continue
                        if max_odds_over25 is not None and not pd.isna(odds_over25) and odds_over25 > max_odds_over25: continue
                        if min_odds_under25 is not None and not pd.isna(odds_under25) and odds_under25 < min_odds_under25: continue
                        if max_odds_under25 is not None and not pd.isna(odds_under25) and odds_under25 > max_odds_under25: continue

                        # Filter by odds range
                        if bookie_odds < min_odds or bookie_odds > max_odds:
                            continue
                        expected_value = model_prob * bookie_odds

                        if expected_value >= value_threshold:
                            # Intra-day correlation: limit daily exposure
                            date_str_check = match_date.strftime('%Y-%m-%d')
                            daily_bet_count[date_str_check] += 1
                            n_bets_today = daily_bet_count[date_str_check]

                            # Determine bet size (Staking)
                            if staking_rule == 'fixed':
                                stake = stake_value
                            elif staking_rule == 'proportional':
                                # e.g., 2% of current bankroll
                                stake = bankroll * (stake_value / 100.0)
                            elif staking_rule == 'kelly':
                                mult_k = stake_value
                                
                                # Kelly Criterion = (p * b - 1) / (b - 1)
                                if bookie_odds > 1.0:
                                    f_star = (model_prob * bookie_odds - 1.0) / (bookie_odds - 1.0)
                                    f_star = max(0.0, f_star) # No short selling
                                    stake = bankroll * f_star * mult_k
                                    stake = min(stake, bankroll * 0.05) # Cap at 5% of bankroll
                                else:
                                    stake = 0.0
                            else:
                                stake = 0.0

                            # Apply intra-day correlation correction (only for Kelly/Proportional)
                            if staking_rule != 'fixed':
                                if n_bets_today > 1:
                                    stake = stake / math.sqrt(n_bets_today)
                                
                                # Cap daily exposure at 10% of bankroll
                                if daily_exposure[date_str_check] + stake > bankroll * 0.10:
                                    stake = max(0, bankroll * 0.10 - daily_exposure[date_str_check])

                            # Avoid placing bet if stake is tiny or we have no bankroll left
                            if stake > 0.01 and bankroll >= stake:
                                total_staked += stake

                                if bet_won:
                                    profit = stake * (bookie_odds - 1.0)
                                    # Aplicar comissão de exchange em apostas Lay ganhas
                                    if exchange_commission > 0 and mkt.startswith('lay'):
                                        profit = profit * (1 - exchange_commission / 100)
                                    bankroll += profit
                                else:
                                    profit = -stake
                                    bankroll += profit

                                cumulative_profit += profit
                                daily_exposure[date_str_check] += stake

                                # Max Drawdown calculation
                                if bankroll > peak_bankroll:
                                    peak_bankroll = bankroll
                                dd = (peak_bankroll - bankroll) / peak_bankroll
                                if dd > max_drawdown:
                                    max_drawdown = dd

                                # --- Parallel Bankroll Simulations ---
                                date_str = match_date.strftime('%Y-%m-%d')

                                # 1. Fixed Stake Simulation ($10 or the active stake value if it is fixed)
                                st_fixed = stake_value if staking_rule == 'fixed' else 10.0
                                if bankroll_fixed >= st_fixed and st_fixed > 0.01:
                                    bets_fixed += 1
                                    staked_fixed += st_fixed
                                    if bet_won:
                                        bankroll_fixed += st_fixed * (bookie_odds - 1.0)
                                        wins_fixed += 1
                                    else:
                                        bankroll_fixed -= st_fixed

                                    if bankroll_fixed >= peak_fixed:
                                        peak_fixed = bankroll_fixed
                                        current_dd_duration_fixed = 0
                                    else:
                                        current_dd_duration_fixed += 1
                                        if current_dd_duration_fixed > max_dd_duration_fixed:
                                            max_dd_duration_fixed = current_dd_duration_fixed
                                            
                                    dd_fixed = (peak_fixed - bankroll_fixed) / peak_fixed if peak_fixed > 0 else 0
                                    if dd_fixed > max_dd_fixed:
                                        max_dd_fixed = dd_fixed
                                    equity_curve_fixed.append({'date': date_str, 'bankroll': round(bankroll_fixed, 2)})

                                # 2. Proportional Stake Simulation (2% of current bankroll or the active stake value if proportional)
                                pct_prop = stake_value if staking_rule == 'proportional' else 2.0
                                st_prop = bankroll_proportional * (pct_prop / 100.0)
                                if bankroll_proportional >= st_prop and st_prop > 0.01:
                                    bets_prop += 1
                                    staked_prop += st_prop
                                    if bet_won:
                                        bankroll_proportional += st_prop * (bookie_odds - 1.0)
                                        wins_prop += 1
                                    else:
                                        bankroll_proportional -= st_prop

                                    if bankroll_proportional >= peak_prop:
                                        peak_prop = bankroll_proportional
                                        current_dd_duration_prop = 0
                                    else:
                                        current_dd_duration_prop += 1
                                        if current_dd_duration_prop > max_dd_duration_prop:
                                            max_dd_duration_prop = current_dd_duration_prop
                                            
                                    dd_prop = (peak_prop - bankroll_proportional) / peak_prop if peak_prop > 0 else 0
                                    if dd_prop > max_dd_prop:
                                        max_dd_prop = dd_prop
                                    equity_curve_proportional.append({'date': date_str, 'bankroll': round(bankroll_proportional, 2)})

                                # 3. Kelly Stake Simulation (1/4 Kelly or active fraction if Kelly)
                                mult_k = 0.25
                                if staking_rule == 'kelly': mult_k = stake_value

                                if bookie_odds > 1.0:
                                    f_star = (model_prob * bookie_odds - 1.0) / (bookie_odds - 1.0)
                                    f_star = max(0.0, f_star)
                                    st_kelly = bankroll_kelly * f_star * mult_k
                                    st_kelly = min(st_kelly, bankroll_kelly * 0.05)
                                else:
                                    st_kelly = 0.0

                                if bankroll_kelly >= st_kelly and st_kelly > 0.01:
                                    bets_kelly += 1
                                    staked_kelly += st_kelly
                                    if bet_won:
                                        bankroll_kelly += st_kelly * (bookie_odds - 1.0)
                                        wins_kelly += 1
                                    else:
                                        bankroll_kelly -= st_kelly

                                    if bankroll_kelly >= peak_kelly:
                                        peak_kelly = bankroll_kelly
                                        current_dd_duration_kelly = 0
                                    else:
                                        current_dd_duration_kelly += 1
                                        if current_dd_duration_kelly > max_dd_duration_kelly:
                                            max_dd_duration_kelly = current_dd_duration_kelly
                                            
                                    dd_kelly = (peak_kelly - bankroll_kelly) / peak_kelly if peak_kelly > 0 else 0
                                    if dd_kelly > max_dd_kelly:
                                        max_dd_kelly = dd_kelly
                                    equity_curve_kelly.append({'date': date_str, 'bankroll': round(bankroll_kelly, 2)})

                                # Update daily exposure
                                daily_exposure[date_str_check] += stake

                                # Calculate CLV (Closing Line Value)
                                clv = None
                                closing_odd = None
                                if mkt in ('home', '1x2_home'):
                                    closing_odd = closing_odds_h
                                elif mkt in ('away', '1x2_away'):
                                    closing_odd = closing_odds_a
                                elif mkt in ('draw', '1x2_draw'):
                                    closing_odd = closing_odds_d
                                elif mkt == 'over25':
                                    closing_odd = closing_odds_over25
                                elif mkt == 'under25':
                                    closing_odd = closing_odds_under25
                                
                                if closing_odd and not pd.isna(closing_odd) and closing_odd > 1.0:
                                    clv = (bookie_odds / closing_odd - 1.0) * 100  # as percentage

                                bets_record.append({
                                    'date': match_date.strftime('%Y-%m-%d'),
                                    'league': league_code,
                                    'home_team': home_team,
                                    'away_team': away_team,
                                    'score': f"{int(fthg)}-{int(ftag)}",
                                    'market': market_label,
                                    'odds': round(bookie_odds, 2),
                                    'prob': round(model_prob * 100, 1),
                                    'ev': round(expected_value, 2),
                                    'stake': round(stake, 2),
                                    'profit': round(profit, 2),
                                    'bankroll': round(bankroll, 2),
                                    'won': bet_won,
                                    'clv': round(clv, 2) if clv is not None else None,
                                    'odds_h': round(odds_h, 2) if (odds_h and not pd.isna(odds_h)) else None,
                                    'odds_d': round(odds_d, 2) if (odds_d and not pd.isna(odds_d)) else None,
                                    'odds_a': round(odds_a, 2) if (odds_a and not pd.isna(odds_a)) else None,
                                    'odds_over25': round(odds_over25, 2) if (odds_over25 and not pd.isna(odds_over25)) else None,
                                    'odds_under25': round(odds_under25, 2) if (odds_under25 and not pd.isna(odds_under25)) else None
                                })
                            
            # Fit Calibration Periodically
            self.matches_since_calibration += 1
            if self.matches_since_calibration >= 100:
                self.matches_since_calibration = 0
                for c_mkt, hist in self.calibration_history.items():
                    if len(hist['probs']) > 2000:
                        hist['probs'] = hist['probs'][-2000:]
                        hist['outcomes'] = hist['outcomes'][-2000:]
                    if len(hist['probs']) >= 50:
                        if c_mkt not in self.calibrators:
                            self.calibrators[c_mkt] = PlattCalibrator(epochs=200)
                        self.calibrators[c_mkt].fit(hist['probs'], hist['outcomes'])
                        
            # Fit ML Ensemble Periodically
            if use_ml:
                self.matches_since_ml_fit += 1
            if self.matches_since_ml_fit >= 300:
                self.matches_since_ml_fit = 0
                for c_mkt, hist in self.ml_history.items():
                    if len(hist['X']) > 3000:
                        hist['X'] = hist['X'][-3000:]
                        hist['y'] = hist['y'][-3000:]
                    if len(hist['X']) >= 100:
                        if c_mkt not in self.ml_ensembles:
                            self.ml_ensembles[c_mkt] = MLEnsemble(c_mkt)
                        self.ml_ensembles[c_mkt].fit(hist['X'], hist['y'])

            # 4. Update the rolling form lists with this match result (chronological flow)
            self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                              league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                              team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                              league_home_sot, league_away_sot, hst, ast,
                              team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                              league_home_xg, league_away_xg, hxg, axg,
                              team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                              league_home_goals_ht, league_away_goals_ht, hthg, htag)
                              
            elo_tracker.update(home_team, away_team, int(fthg), int(ftag))
            # Update rho estimation data
            rho_data = league_goals_for_rho[league_code]
            rho_data['h'].append(int(fthg))
            rho_data['a'].append(int(ftag))
            rho_data['lh'].append(lambda_home if 'lambda_home' in dir() else 1.3)
            rho_data['la'].append(lambda_away if 'lambda_away' in dir() else 1.0)
            # Invalidate rho cache for this league every 50 matches
            if len(rho_data['h']) % 50 == 0:
                league_rho_cache.pop(league_code, None)

        # Compile performance results
        total_bets = len(bets_record)
        wins = sum(1 for b in bets_record if b['profit'] > 0)
        win_rate = (wins / total_bets * 100) if total_bets > 0 else 0.0
        net_profit = bankroll - initial_bankroll
        yield_roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
        profit_in_stakes = sum(b['profit'] / b['stake'] for b in bets_record) if bets_record else 0.0

        # Calculate advanced financial metrics
        daily_profits = defaultdict(float)
        for b in bets_record:
            daily_profits[b['date']] += b['profit']
            
        daily_returns = [profit / initial_bankroll for date, profit in daily_profits.items()]
        
        sharpe_ratio = 0.0
        sortino_ratio = 0.0
        skewness = 0.0
        
        if len(daily_returns) > 1:
            mean_ret = np.mean(daily_returns)
            std_ret = np.std(daily_returns)
            
            if std_ret > 0:
                sharpe_ratio = float((mean_ret / std_ret) * math.sqrt(252))
                
            downside_returns = [r for r in daily_returns if r < 0]
            if downside_returns:
                downside_std = np.std(downside_returns)
                if downside_std > 0:
                    sortino_ratio = float((mean_ret / downside_std) * math.sqrt(252))
            else:
                sortino_ratio = sharpe_ratio
                
            if std_ret > 0:
                skewness = float(np.mean((np.array(daily_returns) - mean_ret)**3) / (std_ret**3))
                
        # Consecutive wins / losses runs
        max_consec_wins = 0
        max_consec_losses = 0
        current_wins = 0
        current_losses = 0
        
        for b in bets_record:
            if b['profit'] > 0:
                current_wins += 1
                max_consec_wins = max(max_consec_wins, current_wins)
                current_losses = 0
            elif b['profit'] < 0:
                current_losses += 1
                max_consec_losses = max(max_consec_losses, current_losses)
                current_wins = 0

        # Markowitz Portfolio Monte Carlo Optimization
        portfolio_opt = None
        unique_bets_markets = list(set(b['market'] for b in bets_record))
        if len(unique_bets_markets) > 1 and len(bets_record) >= 10:
            try:
                unique_dates_list = list(set(b['date'] for b in bets_record))
                unique_dates_list.sort()
                
                market_indices = {mkt: i for i, mkt in enumerate(unique_bets_markets)}
                date_indices = {dt: i for i, dt in enumerate(unique_dates_list)}
                
                R = np.zeros((len(unique_dates_list), len(unique_bets_markets)))
                for b in bets_record:
                    r_idx = date_indices[b['date']]
                    c_idx = market_indices[b['market']]
                    R[r_idx, c_idx] += b['profit'] / initial_bankroll
                    
                mean_returns = np.mean(R, axis=0)
                cov_matrix = np.atleast_2d(np.cov(R, rowvar=False))
                
                best_sharpe = -999.0
                best_weights = None
                
                np.random.seed(42)
                for _ in range(1000):
                    w = np.random.random(len(unique_bets_markets))
                    w /= np.sum(w)
                    
                    p_ret = np.sum(mean_returns * w)
                    p_var = np.dot(w.T, np.dot(cov_matrix, w))
                    p_std = math.sqrt(p_var) if p_var > 0 else 0.0
                    
                    p_sharpe = p_ret / p_std if p_std > 0 else 0.0
                    if p_sharpe > best_sharpe:
                        best_sharpe = p_sharpe
                        best_weights = w
                        
                if best_weights is not None:
                    portfolio_opt = {
                        'weights': {unique_bets_markets[i]: round(float(best_weights[i]), 3) for i in range(len(unique_bets_markets))},
                        'expected_return_pct': round(float(np.sum(mean_returns * best_weights) * 100), 2),
                        'volatility_pct': round(float(math.sqrt(np.dot(best_weights.T, np.dot(cov_matrix, best_weights))) * 100), 2)
                    }
            except Exception as e:
                print(f"[Markowitz Error] {e}")
        
        # Group by league for performance breakdowns
        league_performance = defaultdict(float)
        league_bets = defaultdict(int)
        for b in bets_record:
            league_performance[b['league']] += b['profit']
            league_bets[b['league']] += 1
            
        # Resolve league names dynamically
        all_leagues = get_all_available_leagues()
        code_to_name = {l['code']: l['name'] for l in all_leagues}

        league_stats = []
        for l_code, l_profit in league_performance.items():
            l_name = code_to_name.get(l_code, l_code)
            l_bets = league_bets[l_code]
            league_stats.append({
                'code': l_code,
                'name': l_name,
                'bets': l_bets,
                'profit': round(l_profit, 2)
            })
        # Group by odds range
        odds_ranges = {
            'super_fav': {'name': 'Super Favs (<=1.50)', 'profit': 0.0, 'bets': 0},
            'fav': {'name': 'Favs (1.50-2.00)', 'profit': 0.0, 'bets': 0},
            'med': {'name': 'Med (2.00-3.00)', 'profit': 0.0, 'bets': 0},
            'dog': {'name': 'Zebras (>3.00)', 'profit': 0.0, 'bets': 0}
        }
        
        # Group by month
        monthly_data = defaultdict(lambda: {'profit': 0.0, 'bets': 0})
        
        for b in bets_record:
            # Group by odds
            odd = b['odds']
            if odd <= 1.50:
                key = 'super_fav'
            elif odd <= 2.00:
                key = 'fav'
            elif odd <= 3.00:
                key = 'med'
            else:
                key = 'dog'
            odds_ranges[key]['profit'] += b['profit']
            odds_ranges[key]['bets'] += 1
            
            # Group by month (extract YYYY-MM from date string YYYY-MM-DD)
            month_key = b['date'][:7]
            monthly_data[month_key]['profit'] += b['profit']
            monthly_data[month_key]['bets'] += 1
            
        odds_stats = []
        for key, val in odds_ranges.items():
            odds_stats.append({
                'range': val['name'],
                'profit': round(val['profit'], 2),
                'bets': val['bets']
            })
            
        monthly_stats = []
        for m_key in sorted(monthly_data.keys()):
            monthly_stats.append({
                'month': m_key,
                'profit': round(monthly_data[m_key]['profit'], 2),
                'bets': monthly_data[m_key]['bets']
            })
            
        # Group by month for equity curve charting
        equity_curve = []
        if bets_record:
            # Add initial point
            equity_curve.append({'date': start_date, 'bankroll': round(initial_bankroll, 2)})
            for b in bets_record:
                equity_curve.append({'date': b['date'], 'bankroll': b['bankroll']})
        else:
            equity_curve.append({'date': start_date, 'bankroll': round(initial_bankroll, 2)})
            equity_curve.append({'date': end_date, 'bankroll': round(initial_bankroll, 2)})
            
        if not bets_record:
            equity_curve_fixed.append({'date': end_date, 'bankroll': round(initial_bankroll, 2)})
            equity_curve_proportional.append({'date': end_date, 'bankroll': round(initial_bankroll, 2)})
            equity_curve_kelly.append({'date': end_date, 'bankroll': round(initial_bankroll, 2)})
            
        # Compute AI sustainability analysis
        ai_res = predict_strategy_sustainability(bets_record, initial_bankroll, value_threshold, staking_rule, stake_value, run_monte_carlo=run_monte_carlo)
        
        # Calculate quartiles (4 chronological blocks of 25% of bets)
        quartiles = []
        if total_bets >= 4:
            chunk_size = total_bets // 4
            for i in range(4):
                start_idx = i * chunk_size
                end_idx = (i + 1) * chunk_size if i < 3 else total_bets
                
                chunk = bets_record[start_idx:end_idx]
                c_profit = sum(b['profit'] for b in chunk)
                c_staked = sum(b['stake'] for b in chunk)
                c_wins = sum(1 for b in chunk if b['profit'] > 0)
                
                c_win_rate = (c_wins / len(chunk) * 100) if chunk else 0.0
                c_roi = (c_profit / c_staked * 100) if c_staked > 0 else 0.0
                c_stakes = sum(b['profit'] / b['stake'] for b in chunk) if chunk else 0.0
                
                quartiles.append({
                    'profit': round(c_profit, 2),
                    'stakes': round(c_stakes, 2),
                    'roi': round(c_roi, 2),
                    'win_rate': round(c_win_rate, 1),
                    'total_bets': len(chunk)
                })
        else:
            # Fallback if too few bets
            for _ in range(4):
                quartiles.append({
                    'profit': 0.0,
                    'stakes': 0.0,
                    'roi': 0.0,
                    'win_rate': 0.0,
                    'total_bets': 0
                })
        
        # Compile summaries for the three comparative staking methods
        summary_fixed = {
            'final_bankroll': round(bankroll_fixed, 2),
            'net_profit': round(bankroll_fixed - initial_bankroll, 2),
            'total_bets': bets_fixed,
            'win_rate': round((wins_fixed / bets_fixed * 100) if bets_fixed > 0 else 0.0, 1),
            'roi': round(((bankroll_fixed - initial_bankroll) / staked_fixed * 100) if staked_fixed > 0 else 0.0, 2),
            'max_drawdown': round(max_dd_fixed * 100, 2),
            'max_dd_duration': max_dd_duration_fixed
        }
        
        summary_proportional = {
            'final_bankroll': round(bankroll_proportional, 2),
            'net_profit': round(bankroll_proportional - initial_bankroll, 2),
            'total_bets': bets_prop,
            'win_rate': round((wins_prop / bets_prop * 100) if bets_prop > 0 else 0.0, 1),
            'roi': round(((bankroll_proportional - initial_bankroll) / staked_prop * 100) if staked_prop > 0 else 0.0, 2),
            'max_drawdown': round(max_dd_prop * 100, 2),
            'max_dd_duration': max_dd_duration_prop
        }
        
        summary_kelly = {
            'final_bankroll': round(bankroll_kelly, 2),
            'net_profit': round(bankroll_kelly - initial_bankroll, 2),
            'total_bets': bets_kelly,
            'win_rate': round((wins_kelly / bets_kelly * 100) if bets_kelly > 0 else 0.0, 1),
            'roi': round(((bankroll_kelly - initial_bankroll) / staked_kelly * 100) if staked_kelly > 0 else 0.0, 2),
            'max_drawdown': round(max_dd_kelly * 100, 2),
            'max_dd_duration': max_dd_duration_kelly
        }
        
        summary = {
                'initial_bankroll': round(initial_bankroll, 2),
                'final_bankroll': round(bankroll, 2),
                'net_profit': round(net_profit, 2),
                'profit_in_stakes': round(profit_in_stakes, 2),
                'total_bets': total_bets,
                'wins': wins,
                'losses': total_bets - wins,
                'win_rate': round(win_rate, 1),
                'roi': round(yield_roi, 2),
                'max_drawdown': round(max_drawdown * 100, 2),
                'max_dd_duration': max_dd_duration_fixed if staking_rule == 'fixed' else (max_dd_duration_prop if staking_rule == 'proportional' else max_dd_duration_kelly),
                'total_staked': round(total_staked, 2),
                'avg_odds': round(np.mean([b['odds'] for b in bets_record]), 2) if bets_record else 0.0,
                'sharpe_ratio': round(sharpe_ratio, 2),
                'sortino_ratio': round(sortino_ratio, 2),
                'skewness': round(skewness, 2),
                'max_consec_wins': max_consec_wins,
                'max_consec_losses': max_consec_losses,
                'avg_clv': round(float(np.mean([b['clv'] for b in bets_record if b.get('clv') is not None])), 2) if any(b.get('clv') is not None for b in bets_record) else None,
                'bcl_percent': round(len([b for b in bets_record if b.get('clv') is not None and b['clv'] > 0]) / len([b for b in bets_record if b.get('clv') is not None]) * 100, 1) if any(b.get('clv') is not None for b in bets_record) else None
        }

        # Métricas estatísticas avançadas
        if bets_record and total_bets >= 2:
            avg_odds = summary['avg_odds']
            summary['p_value'] = compute_pvalue_binomial(wins, total_bets, avg_odds)
            try:
                brier = compute_brier_score(bets_record)
                summary['brier_score'] = brier['brier_score']
                summary['brier_score_market'] = brier['brier_score_market']
                summary['brier_improvement'] = brier['brier_improvement']
            except Exception:
                summary['brier_score'] = None
                summary['brier_score_market'] = None
                summary['brier_improvement'] = None

            try:
                bootstrap = compute_bootstrap_ci(bets_record)
                summary['bootstrap_roi_ci_lower'] = bootstrap['bootstrap_roi_ci_lower']
                summary['bootstrap_roi_ci_upper'] = bootstrap['bootstrap_roi_ci_upper']
                summary['bootstrap_roi_median'] = bootstrap['bootstrap_roi_median']
                summary['prob_positive_roi'] = bootstrap['prob_positive_roi']
            except Exception:
                summary['bootstrap_roi_ci_lower'] = None
                summary['bootstrap_roi_ci_upper'] = None
                summary['bootstrap_roi_median'] = None
                summary['prob_positive_roi'] = None

            try:
                power = compute_power_analysis(summary['roi'], summary.get('avg_odds', 2.0), summary['total_bets'])
                summary['min_sample_size'] = power['min_sample_size']
                summary['sample_sufficient'] = power['sample_sufficient']
                summary['power_ratio'] = power['power_ratio']
            except Exception:
                summary['min_sample_size'] = None
                summary['sample_sufficient'] = None
                summary['power_ratio'] = None

            try:
                rolling = compute_rolling_roi(bets_record)
                summary['rolling_roi'] = rolling['rolling_roi']
                summary['edge_decay_pct'] = rolling['edge_decay_pct']
                summary['edge_decay_alert'] = rolling['edge_decay_alert']
            except Exception:
                summary['rolling_roi'] = []
                summary['edge_decay_pct'] = None
                summary['edge_decay_alert'] = None

        # --- Computar EQS Score Dinamicamente ---
        oos_summary = None
        if len(bets_record) >= 20:
            n_oos = max(10, int(len(bets_record) * 0.2))
            oos_bets = bets_record[-n_oos:]
            oos_staked = sum([b['stake'] for b in oos_bets])
            oos_profit = sum([b['profit'] for b in oos_bets])
            oos_roi = (oos_profit / oos_staked * 100) if oos_staked > 0 else 0.0
            oos_wins = sum([1 for b in oos_bets if b['profit'] > 0])
            oos_win_rate = (oos_wins / len(oos_bets) * 100) if oos_bets else 0.0
            oos_summary = {
                'net_profit': round(oos_profit, 2),
                'roi': round(oos_roi, 2),
                'win_rate': round(oos_win_rate, 1),
                'total_bets': len(oos_bets)
            }
        
        eqs_data = compute_edge_quality_score(summary, oos_summary)
        
        if isinstance(ai_res, dict):
            ai_res['score'] = eqs_data.get('score', 0)
            ai_res['breakdown'] = eqs_data.get('breakdown', [])
            ai_res['verdict'] = eqs_data.get('verdict', 'Avaliando...')
            ai_res['verdict_color'] = eqs_data.get('verdict_color', 'warning')
            ai_res['risk_recommendation'] = eqs_data.get('risk_recommendation', '')
            ai_res['oos_summary'] = oos_summary


        return {
            'summary': summary,
            'summary_fixed': summary_fixed,
            'summary_proportional': summary_proportional,
            'summary_kelly': summary_kelly,
            'league_stats': league_stats,
            'odds_stats': odds_stats,
            'monthly_stats': monthly_stats,
            'equity_curve': equity_curve,
            'equity_curve_fixed': equity_curve_fixed,
            'equity_curve_proportional': equity_curve_proportional,
            'equity_curve_kelly': equity_curve_kelly,
            'bets': bets_record[-1000:], # Limit bets sent to client to last 1000 for performance
            'ai_analysis': ai_res,
            'quartiles': quartiles,
            'portfolio_optimization': portfolio_opt
        }

    def run_parallel_scan(self, leagues, start_date, end_date, value_threshold, initial_bankroll, staking_rule, stake_value, odds_source='B365', min_odds=1.0, max_odds=50.0, scan_type='markets', markets_list=None, use_ml=False, data_source='football-data', futpython_api_key=''):
        """
        Runs a highly optimized parallel scan of either multiple markets or multiple leagues
        in a single chronological pass to avoid duplicate ratings computation.
        """
        # 1. Load data for all selected leagues
        all_matches = []
        for league_code in leagues:
            df = load_league_data(league_code, start_date='2020-08-01', data_source=data_source, api_key=futpython_api_key)
            if not df.empty:
                all_matches.append(df)
                
        if not all_matches:
            return {}
            
        combined_df = pd.concat(all_matches, ignore_index=True)
        
        if combined_df.empty:
            return {}
            
        print('Total combined_df matches:', len(combined_df))
        combined_df.sort_values('Date', inplace=True)
        combined_df = combined_df.sort_values(by=['Date', 'Time']).reset_index(drop=True)
        
        # 2. Setup state trackers for rolling form
        team_home_scored = defaultdict(list)
        team_home_conceded = defaultdict(list)
        team_away_scored = defaultdict(list)
        team_away_conceded = defaultdict(list)
        
        team_home_sot = defaultdict(list)
        team_home_sot_conceded = defaultdict(list)
        team_away_sot = defaultdict(list)
        team_away_sot_conceded = defaultdict(list)
        
        league_home_goals = defaultdict(list)
        league_away_goals = defaultdict(list)
        league_home_sot = defaultdict(list)
        league_away_sot = defaultdict(list)
        
        team_home_xg = defaultdict(list)
        team_home_xg_conceded = defaultdict(list)
        team_away_xg = defaultdict(list)
        team_away_xg_conceded = defaultdict(list)
        
        league_home_xg = defaultdict(list)
        league_away_xg = defaultdict(list)
        
        team_home_scored_ht = defaultdict(list)
        team_home_conceded_ht = defaultdict(list)
        team_away_scored_ht = defaultdict(list)
        team_away_conceded_ht = defaultdict(list)
        league_home_goals_ht = defaultdict(list)
        league_away_goals_ht = defaultdict(list)
        
        elo_tracker = EloTracker(k_factor=20, home_advantage=65)
        league_rho_cache = {}
        league_goals_for_rho = defaultdict(lambda: {'h': [], 'a': [], 'lh': [], 'la': []})
        
        last_match_date = {}
        season_points = defaultdict(lambda: defaultdict(int))
        season_games = defaultdict(lambda: defaultdict(int))
        
        # 3. Setup independent simulation states
        states = {}
        if scan_type == 'markets':
            for mkt in markets_list:
                states[mkt] = {
                    'bankroll': initial_bankroll,
                    'total_staked': 0.0,
                    'total_bets': 0,
                    'wins': 0,
                    'bets_for_ai': [],
                    'daily_exposure': defaultdict(float),
                    'daily_bet_count': defaultdict(int)
                }
        elif scan_type == 'leagues':
            for l_code in leagues:
                states[l_code] = {
                    'bankroll': initial_bankroll,
                    'total_staked': 0.0,
                    'total_bets': 0,
                    'wins': 0,
                    'bets_for_ai': [],
                    'daily_exposure': defaultdict(float),
                    'daily_bet_count': defaultdict(int)
                }
        elif scan_type == 'combinations':
            for l in leagues:
                for m in markets_list:
                    states[f"{l}|{m}"] = {
                        'bankroll': initial_bankroll,
                        'total_staked': 0.0,
                        'total_bets': 0,
                        'wins': 0,
                        'bets_for_ai': [],
                        'daily_exposure': defaultdict(float),
                        'daily_bet_count': defaultdict(int)
                    }
                
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        # 4. Simulation loop
        for row in combined_df.to_dict('records'):
            match_date = row['Date']
            league_code = row['LeagueCode']
            home_team = row['HomeTeam']
            away_team = row['AwayTeam']
            fthg = row['FTHG']
            ftag = row['FTAG']
            ftr = row['FTR']
            
            # HT Goals extraction
            hthg = row.get('HTHG')
            htag = row.get('HTAG')
            if pd.isna(hthg) or pd.isna(htag):
                hthg = fthg * 0.45
                htag = ftag * 0.45
            
            if pd.isna(fthg) or pd.isna(ftag):
                continue
                
            # Skip heavy calculations for warm-up matches
            hst = row.get('HST')
            ast = row.get('AST')
            hxg = row.get('HomeXG')
            axg = row.get('AwayXG')
            
            if pd.isna(hxg) or hxg == 0:
                hxg = (hst * 0.33) if not pd.isna(hst) else (fthg * 0.9)
            if pd.isna(axg) or axg == 0:
                axg = (ast * 0.33) if not pd.isna(ast) else (ftag * 0.9)
                
            # Calculate rest days (fatigue)
            current_dt = pd.to_datetime(match_date)
            home_last = last_match_date.get(home_team)
            away_last = last_match_date.get(away_team)
            rest_days_home = min(15, (current_dt - home_last).days) if home_last else 10
            rest_days_away = min(15, (current_dt - away_last).days) if away_last else 10
            
            # Save/update last match date
            last_match_date[home_team] = current_dt
            last_match_date[away_team] = current_dt
            
            # Calculate motivation/urgency based on standings
            season_key = (league_code, row.get('Season', 'All'))
            motivation_home = self._calculate_motivation(season_points[season_key], home_team, season_games[season_key])
            motivation_away = self._calculate_motivation(season_points[season_key], away_team, season_games[season_key])
            
            # Update points and games in standings (for future matches)
            if home_team not in season_points[season_key]:
                season_points[season_key][home_team] = 0
                season_games[season_key][home_team] = 0
            if away_team not in season_points[season_key]:
                season_points[season_key][away_team] = 0
                season_games[season_key][away_team] = 0
                
            season_games[season_key][home_team] += 1
            season_games[season_key][away_team] += 1
            
            if ftr == 'H':
                season_points[season_key][home_team] += 3
            elif ftr == 'A':
                season_points[season_key][away_team] += 3
            elif ftr == 'D':
                season_points[season_key][home_team] += 1
                season_points[season_key][away_team] += 1
                
            if match_date < start_dt:
                self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                                  league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                                  team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                                  league_home_sot, league_away_sot, hst, ast,
                                  team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                                  league_home_xg, league_away_xg, hxg, axg,
                                  team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                                  league_home_goals_ht, league_away_goals_ht, hthg, htag)
                continue
                
            odds_h = row.get('B365H') if odds_source == 'B365' else (row.get('AvgH') if odds_source == 'Avg' else row.get('MaxH'))
            odds_d = row.get('B365D') if odds_source == 'B365' else (row.get('AvgD') if odds_source == 'Avg' else row.get('MaxD'))
            odds_a = row.get('B365A') if odds_source == 'B365' else (row.get('AvgA') if odds_source == 'Avg' else row.get('MaxA'))
            
            odds_over25 = row.get('B365>2.5') if odds_source == 'B365' else (row.get('Avg>2.5') if odds_source == 'Avg' else row.get('Max>2.5'))
            odds_under25 = row.get('B365<2.5') if odds_source == 'B365' else (row.get('Avg<2.5') if odds_source == 'Avg' else row.get('Max<2.5'))
            
            # Asian Handicap (Main Spread)
            ahh_line = row.get('AHh')
            odds_ahh = row.get('B365AHH') if odds_source == 'B365' else (row.get('AvgAHH') if odds_source == 'Avg' else row.get('MaxAHH'))
            odds_aha = row.get('B365AHA') if odds_source == 'B365' else (row.get('AvgAHA') if odds_source == 'Avg' else row.get('MaxAHA'))
            
            closing_odds_h = row.get('PSCH', row.get('PSH', row.get('MaxCH')))
            closing_odds_d = row.get('PSCD', row.get('PSD', row.get('MaxCD')))
            closing_odds_a = row.get('PSCA', row.get('PSA', row.get('MaxCA')))
            closing_odds_over25 = row.get('PC>2.5', row.get('MaxC>2.5'))
            closing_odds_under25 = row.get('PC<2.5', row.get('MaxC<2.5'))
            if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
                self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                                  league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                                  team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                                  league_home_sot, league_away_sot, hst, ast,
                                  team_home_scored_ht=team_home_scored_ht, team_home_conceded_ht=team_home_conceded_ht, 
                                  team_away_scored_ht=team_away_scored_ht, team_away_conceded_ht=team_away_conceded_ht,
                                  league_home_goals_ht=league_home_goals_ht, league_away_goals_ht=league_away_goals_ht, hthg=hthg, htag=htag)
                continue
                
            # Compute predictive ratings
            h_xg_att, h_xg_def, a_xg_att, a_xg_def = self._calculate_xg_ratings(
                team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                league_home_xg, league_away_xg, home_team, away_team, league_code
            )
            h_scored = team_home_scored[home_team][-self.rolling_games:]
            h_conceded = team_home_conceded[home_team][-self.rolling_games:]
            a_scored = team_away_scored[away_team][-self.rolling_games:]
            a_conceded = team_away_conceded[away_team][-self.rolling_games:]
            
            leg_h_goals = league_home_goals[league_code][-100:]
            leg_a_goals = league_away_goals[league_code][-100:]
            
            avg_h_goals = np.mean(leg_h_goals) if leg_h_goals else 1.35
            avg_a_goals = np.mean(leg_a_goals) if leg_a_goals else 1.05
            
            h_att = (weighted_mean(h_scored, 0.06) / avg_h_goals) if h_scored else 1.0
            h_def = (weighted_mean(h_conceded, 0.06) / avg_a_goals) if h_conceded else 1.0
            a_att = (weighted_mean(a_scored, 0.06) / avg_a_goals) if a_scored else 1.0
            a_def = (weighted_mean(a_conceded, 0.06) / avg_h_goals) if a_conceded else 1.0
            
            h_att = 1.0 if pd.isna(h_att) else max(0.2, min(4.0, h_att))
            h_def = 1.0 if pd.isna(h_def) else max(0.2, min(4.0, h_def))
            a_att = 1.0 if pd.isna(a_att) else max(0.2, min(4.0, a_att))
            a_def = 1.0 if pd.isna(a_def) else max(0.2, min(4.0, a_def))
            
            lambda_goals_home = avg_h_goals * h_att * a_def
            lambda_goals_away = avg_a_goals * a_att * h_def
            
            # HT Goals lambda
            h_scored_ht = team_home_scored_ht[home_team][-self.rolling_games:]
            h_conceded_ht = team_home_conceded_ht[home_team][-self.rolling_games:]
            a_scored_ht = team_away_scored_ht[away_team][-self.rolling_games:]
            a_conceded_ht = team_away_conceded_ht[away_team][-self.rolling_games:]
            
            leg_h_goals_ht = league_home_goals_ht[league_code][-100:]
            leg_a_goals_ht = league_away_goals_ht[league_code][-100:]
            
            avg_h_goals_ht = np.mean(leg_h_goals_ht) if leg_h_goals_ht else (avg_h_goals * 0.45)
            avg_a_goals_ht = np.mean(leg_a_goals_ht) if leg_a_goals_ht else (avg_a_goals * 0.45)
            
            if avg_h_goals_ht == 0: avg_h_goals_ht = 0.6
            if avg_a_goals_ht == 0: avg_a_goals_ht = 0.45
            
            h_att_ht = (weighted_mean(h_scored_ht, 0.06) / avg_h_goals_ht) if h_scored_ht else 1.0
            h_def_ht = (weighted_mean(h_conceded_ht, 0.06) / avg_a_goals_ht) if h_conceded_ht else 1.0
            a_att_ht = (weighted_mean(a_scored_ht, 0.06) / avg_a_goals_ht) if a_scored_ht else 1.0
            a_def_ht = (weighted_mean(a_conceded_ht, 0.06) / avg_h_goals_ht) if a_conceded_ht else 1.0
            
            h_att_ht = 1.0 if pd.isna(h_att_ht) else max(0.2, min(4.0, h_att_ht))
            h_def_ht = 1.0 if pd.isna(h_def_ht) else max(0.2, min(4.0, h_def_ht))
            a_att_ht = 1.0 if pd.isna(a_att_ht) else max(0.2, min(4.0, a_att_ht))
            a_def_ht = 1.0 if pd.isna(a_def_ht) else max(0.2, min(4.0, a_def_ht))
            
            lambda_home_ht = avg_h_goals_ht * h_att_ht * a_def_ht
            lambda_away_ht = avg_a_goals_ht * a_att_ht * h_def_ht
            lambda_home = lambda_goals_home
            lambda_away = lambda_goals_away
            
            elo_factor_h = elo_tracker.get_elo_factor(home_team, away_team)
            elo_factor_a = 2.0 - elo_factor_h
            lambda_home *= elo_factor_h
            lambda_away *= elo_factor_a
            
            h_sot_scored = team_home_sot[home_team][-self.rolling_games:]
            h_sot_conceded = team_home_sot_conceded[home_team][-self.rolling_games:]
            a_sot_scored = team_away_sot[away_team][-self.rolling_games:]
            a_sot_conceded = team_away_sot_conceded[away_team][-self.rolling_games:]
            
            leg_h_sot = league_home_sot[league_code][-100:]
            leg_a_sot = league_away_sot[league_code][-100:]
            
            has_sot_data = (h_sot_scored and h_sot_conceded and a_sot_scored and a_sot_conceded and leg_h_sot and leg_a_sot)
            
            if has_sot_data:
                avg_h_sot = np.mean(leg_h_sot)
                avg_a_sot = np.mean(leg_a_sot)
                
                if pd.isna(avg_h_sot) or avg_h_sot == 0: avg_h_sot = 4.5
                if pd.isna(avg_a_sot) or avg_a_sot == 0: avg_a_sot = 3.5
                
                h_sot_att = (weighted_mean(h_sot_scored, 0.06) / avg_h_sot) if h_sot_scored else 1.0
                h_sot_def = (weighted_mean(h_sot_conceded, 0.06) / avg_a_sot) if h_sot_conceded else 1.0
                a_sot_att = (weighted_mean(a_sot_scored, 0.06) / avg_a_sot) if a_sot_scored else 1.0
                a_sot_def = (weighted_mean(a_sot_conceded, 0.06) / avg_h_sot) if a_sot_conceded else 1.0
                
                h_sot_att = 1.0 if pd.isna(h_sot_att) else max(0.2, min(4.0, h_sot_att))
                h_sot_def = 1.0 if pd.isna(h_sot_def) else max(0.2, min(4.0, h_sot_def))
                a_sot_att = 1.0 if pd.isna(a_sot_att) else max(0.2, min(4.0, a_sot_att))
                a_sot_def = 1.0 if pd.isna(a_sot_def) else max(0.2, min(4.0, a_sot_def))
                
                exp_sot_home = avg_h_sot * h_sot_att * a_sot_def
                exp_sot_away = avg_a_sot * a_sot_att * h_sot_def
                
                conversion_home = avg_h_goals / avg_h_sot
                conversion_away = avg_a_goals / avg_a_sot
                
                lambda_shots_home = exp_sot_home * conversion_home
                lambda_shots_away = exp_sot_away * conversion_away
                
                lambda_shots_home = max(0.1, min(5.0, lambda_shots_home))
                lambda_shots_away = max(0.1, min(5.0, lambda_shots_away))
                
                # Calculate Expected Goals (xG) based lambda
                h_xg_scored = team_home_xg[home_team][-self.rolling_games:]
                h_xg_conceded = team_home_xg_conceded[home_team][-self.rolling_games:]
                a_xg_scored = team_away_xg[away_team][-self.rolling_games:]
                a_xg_conceded = team_away_xg_conceded[away_team][-self.rolling_games:]
                
                leg_h_xg = league_home_xg[league_code][-100:]
                leg_a_xg = league_away_xg[league_code][-100:]
                
                has_xg_data = (h_xg_scored and h_xg_conceded and a_xg_scored and a_xg_conceded and leg_h_xg and leg_a_xg)
                if has_xg_data:
                    avg_h_xg = np.mean(leg_h_xg)
                    avg_a_xg = np.mean(leg_a_xg)
                    if pd.isna(avg_h_xg) or avg_h_xg == 0: avg_h_xg = 1.35
                    if pd.isna(avg_a_xg) or avg_a_xg == 0: avg_a_xg = 1.05
                    
                    lambda_xg_home = avg_h_xg * h_xg_att * a_xg_def
                    lambda_xg_away = avg_a_xg * a_xg_att * h_xg_def
                    
                    lambda_xg_home = max(0.1, min(5.0, lambda_xg_home))
                    lambda_xg_away = max(0.1, min(5.0, lambda_xg_away))
                    
                    # BLEND: 50% xG, 30% Shots, 20% Goals
                    lambda_home = 0.50 * lambda_xg_home + 0.30 * lambda_shots_home + 0.20 * lambda_goals_home
                    lambda_away = 0.50 * lambda_xg_away + 0.30 * lambda_shots_away + 0.20 * lambda_goals_away
                else:
                    # BLEND: 60% Goals, 40% Shots
                    lambda_home = 0.60 * lambda_goals_home + 0.40 * lambda_shots_home
                    lambda_away = 0.60 * lambda_goals_away + 0.40 * lambda_shots_away
                
                lambda_home *= elo_factor_h
                lambda_away *= elo_factor_a
                
            max_goals = 8
            home_probs = [math.exp(-lambda_home) * (lambda_home**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
            away_probs = [math.exp(-lambda_away) * (lambda_away**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
            
            prob_matrix = np.outer(home_probs, away_probs)
            
            if league_code in league_rho_cache:
                rho = league_rho_cache[league_code]
            else:
                rho_data = league_goals_for_rho[league_code]
                rho = estimate_dynamic_rho(rho_data['h'], rho_data['a'], rho_data['lh'], rho_data['la'])
                league_rho_cache[league_code] = rho
                
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
                    if tot > 2: prob_over_25 += prob_matrix[x, y]
                    if tot > 1: prob_over_15 += prob_matrix[x, y]
                    if tot > 3: prob_over_35 += prob_matrix[x, y]
                    if tot > 4: prob_over_45 += prob_matrix[x, y]
                    if tot > 5: prob_over_55 += prob_matrix[x, y]
                    
            prob_btts_yes = float((1.0 - home_probs[0]) * (1.0 - away_probs[0]))
            
            # HT Probabilities
            home_probs_ht = [math.exp(-lambda_home_ht) * (lambda_home_ht**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
            away_probs_ht = [math.exp(-lambda_away_ht) * (lambda_away_ht**i) / _FACTORIALS[i] for i in range(max_goals + 1)]
            prob_matrix_ht = np.outer(home_probs_ht, away_probs_ht)
            
            tau_00_ht = 1.0 - lambda_home_ht * lambda_away_ht * rho
            tau_10_ht = 1.0 + lambda_away_ht * rho
            tau_01_ht = 1.0 + lambda_home_ht * rho
            tau_11_ht = 1.0 - rho
            prob_matrix_ht[0, 0] *= max(0.0, tau_00_ht)
            prob_matrix_ht[1, 0] *= max(0.0, tau_10_ht)
            prob_matrix_ht[0, 1] *= max(0.0, tau_01_ht)
            prob_matrix_ht[1, 1] *= max(0.0, tau_11_ht)
            matrix_sum_ht = np.sum(prob_matrix_ht)
            if matrix_sum_ht > 0:
                prob_matrix_ht = prob_matrix_ht / matrix_sum_ht
                
            prob_h_ht = float(np.sum(np.tril(prob_matrix_ht, -1)))
            prob_d_ht = float(np.sum(np.diag(prob_matrix_ht)))
            prob_a_ht = float(np.sum(np.triu(prob_matrix_ht, 1)))
            prob_over_05_ht = 1.0 - float(prob_matrix_ht[0, 0])
            prob_over_15_ht = 0.0
            for x in range(max_goals + 1):
                for y in range(max_goals + 1):
                    if x + y > 1: prob_over_15_ht += prob_matrix_ht[x, y]
            
            est_odds = None
            
            def eval_market(mkt):
                nonlocal est_odds
                model_prob = 0.0
                bookie_odds = np.nan
                bet_won = False
                
                if mkt in ('home', '1x2_home'):
                    model_prob = prob_h
                    bookie_odds = odds_h
                    bet_won = (ftr == 'H')
                elif mkt in ('away', '1x2_away'):
                    model_prob = prob_a
                    bookie_odds = odds_a
                    bet_won = (ftr == 'A')
                elif mkt in ('draw', '1x2_draw'):
                    model_prob = prob_d
                    bookie_odds = odds_d
                    bet_won = (ftr == 'D')
                elif mkt == 'over25':
                    model_prob = prob_over_25
                    bookie_odds = odds_over25
                    bet_won = (fthg + ftag > 2)
                elif mkt == 'under25':
                    model_prob = 1.0 - prob_over_25
                    bookie_odds = odds_under25
                    bet_won = (fthg + ftag < 3)
                elif mkt == 'ht_home':
                    model_prob = prob_h_ht
                    bookie_odds = 1.0 / (prob_h_ht + 0.035) if (prob_h_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg > htag)
                elif mkt == 'ht_draw':
                    model_prob = prob_d_ht
                    bookie_odds = 1.0 / (prob_d_ht + 0.035) if (prob_d_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg == htag)
                elif mkt == 'ht_away':
                    model_prob = prob_a_ht
                    bookie_odds = 1.0 / (prob_a_ht + 0.035) if (prob_a_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg < htag)
                elif mkt == 'ht_over05':
                    model_prob = prob_over_05_ht
                    bookie_odds = 1.0 / (prob_over_05_ht + 0.035) if (prob_over_05_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg + htag > 0)
                elif mkt == 'ht_under05':
                    model_prob = 1.0 - prob_over_05_ht
                    bookie_odds = 1.0 / ((1.0 - prob_over_05_ht) + 0.035) if ((1.0 - prob_over_05_ht) + 0.035) > 0 else 1.01
                    bet_won = (hthg + htag == 0)
                elif mkt == 'ht_over15':
                    model_prob = prob_over_15_ht
                    bookie_odds = 1.0 / (prob_over_15_ht + 0.035) if (prob_over_15_ht + 0.035) > 0 else 1.01
                    bet_won = (hthg + htag > 1)
                elif mkt == 'ht_under15':
                    model_prob = 1.0 - prob_over_15_ht
                    bookie_odds = 1.0 / ((1.0 - prob_over_15_ht) + 0.035) if ((1.0 - prob_over_15_ht) + 0.035) > 0 else 1.01
                    bet_won = (hthg + htag <= 1)
                elif mkt == 'ah_home':
                    if ahh_line is None or pd.isna(ahh_line): return None
                    from .models import calculate_ah_probabilities
                    ah_probs = calculate_ah_probabilities(pred['prob_matrix'], ahh_line)
                    model_prob = ah_probs['win'] + 0.5 * ah_probs['half_win']
                    bookie_odds = odds_ahh
                    
                    score = (fthg - ftag) + ahh_line
                    if score > 0.24: bet_won = 1.0
                    elif 0.10 < score <= 0.25: bet_won = 0.5
                    elif -0.10 <= score <= 0.10: bet_won = 0.0
                    elif -0.25 <= score < -0.10: bet_won = -0.5
                    else: bet_won = -1.0
                elif mkt == 'ah_away':
                    if ahh_line is None or pd.isna(ahh_line): return None
                    from .models import calculate_ah_probabilities
                    ah_probs = calculate_ah_probabilities(pred['prob_matrix'], -ahh_line)
                    model_prob = ah_probs['win'] + 0.5 * ah_probs['half_win']
                    bookie_odds = odds_aha
                    
                    score = (ftag - fthg) - ahh_line
                    if score > 0.24: bet_won = 1.0
                    elif 0.10 < score <= 0.25: bet_won = 0.5
                    elif -0.10 <= score <= 0.10: bet_won = 0.0
                    elif -0.25 <= score < -0.10: bet_won = -0.5
                    else: bet_won = -1.0
                else:
                    if est_odds is None:
                        est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    
                    if mkt == 'over15':
                        model_prob = prob_over_15
                        bookie_odds = est_odds['bookie_over_15']
                        bet_won = (fthg + ftag > 1)
                    elif mkt == 'over35':
                        model_prob = prob_over_35
                        bookie_odds = est_odds['bookie_over_35']
                        bet_won = (fthg + ftag > 3)
                    elif mkt == 'under35':
                        model_prob = 1.0 - prob_over_35
                        bookie_odds = est_odds['bookie_under_35']
                        bet_won = (fthg + ftag < 4)
                    elif mkt == 'over45':
                        model_prob = prob_over_45
                        bookie_odds = est_odds['bookie_over_45']
                        bet_won = (fthg + ftag > 4)
                    elif mkt == 'under45':
                        model_prob = 1.0 - prob_over_45
                        bookie_odds = est_odds['bookie_under_45']
                        bet_won = (fthg + ftag < 5)
                    elif mkt == 'over55':
                        model_prob = prob_over_55
                        bookie_odds = est_odds['bookie_over_55']
                        bet_won = (fthg + ftag > 5)
                    elif mkt == 'under55':
                        model_prob = 1.0 - prob_over_55
                        bookie_odds = est_odds['bookie_under_55']
                        bet_won = (fthg + ftag < 6)
                    elif mkt == 'lay_home':
                        model_prob = prob_d + prob_a
                        bookie_odds = 1.0 / (1.0/odds_d + 1.0/odds_a) if (odds_d > 1.0 and odds_a > 1.0) else np.nan
                        bet_won = (ftr != 'H')
                    elif mkt == 'lay_away':
                        model_prob = prob_h + prob_d
                        bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan
                        bet_won = (ftr != 'A')
                    elif mkt == 'lay_draw':
                        model_prob = prob_h + prob_a
                        bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_a) if (odds_h > 1.0 and odds_a > 1.0) else np.nan
                        bet_won = (ftr != 'D')
                    elif mkt == 'btts_yes':
                        model_prob = prob_btts_yes
                        
                        actual_odd = row.get('BTTS_Yes', np.nan)
                        try:
                            parsed_odd = float(str(actual_odd).replace(',', '.')) if not pd.isna(actual_odd) else np.nan
                            bookie_odds = parsed_odd if 1.0 < parsed_odd < 10.0 else est_odds['bookie_btts_yes']
                        except Exception:
                            bookie_odds = est_odds['bookie_btts_yes']
                            
                        bet_won = (fthg > 0 and ftag > 0)
                    elif mkt == 'btts_no':
                        model_prob = 1.0 - prob_btts_yes
                        
                        actual_odd = row.get('BTTS_No', np.nan)
                        try:
                            parsed_odd = float(str(actual_odd).replace(',', '.')) if not pd.isna(actual_odd) else np.nan
                            bookie_odds = parsed_odd if 1.0 < parsed_odd < 10.0 else est_odds['bookie_btts_no']
                        except Exception:
                            bookie_odds = est_odds['bookie_btts_no']
                            
                        bet_won = (fthg == 0 or ftag == 0)
                    elif mkt.startswith('cs_'):
                        if mkt == 'cs_10':
                            model_prob = float(prob_matrix[1, 0])
                            bookie_odds = est_odds['bookie_cs_10']
                            bet_won = (fthg == 1 and ftag == 0)
                        elif mkt == 'cs_20':
                            model_prob = float(prob_matrix[2, 0])
                            bookie_odds = est_odds['bookie_cs_20']
                            bet_won = (fthg == 2 and ftag == 0)
                        elif mkt == 'cs_21':
                            model_prob = float(prob_matrix[2, 1])
                            bookie_odds = est_odds['bookie_cs_21']
                            bet_won = (fthg == 2 and ftag == 1)
                        elif mkt == 'cs_00':
                            model_prob = float(prob_matrix[0, 0])
                            bookie_odds = est_odds['bookie_cs_00']
                            bet_won = (fthg == 0 and ftag == 0)
                        elif mkt == 'cs_11':
                            model_prob = float(prob_matrix[1, 1])
                            bookie_odds = est_odds['bookie_cs_11']
                            bet_won = (fthg == 1 and ftag == 1)
                        elif mkt == 'cs_01':
                            model_prob = float(prob_matrix[0, 1])
                            bookie_odds = est_odds['bookie_cs_01']
                            bet_won = (fthg == 0 and ftag == 1)
                        elif mkt == 'cs_02':
                            model_prob = float(prob_matrix[0, 2])
                            bookie_odds = est_odds['bookie_cs_02']
                            bet_won = (fthg == 0 and ftag == 2)
                        elif mkt == 'cs_12':
                            model_prob = float(prob_matrix[1, 2])
                            bookie_odds = est_odds['bookie_cs_12']
                            bet_won = (fthg == 1 and ftag == 2)
                        elif mkt.startswith('lay_cs_'):
                            cs_code = mkt.replace('lay_', '')
                            if cs_code == 'cs_10':
                                back_prob = float(prob_matrix[1, 0])
                                back_odds = est_odds['bookie_cs_10']
                                is_cs = (fthg == 1 and ftag == 0)
                            elif cs_code == 'cs_20':
                                back_prob = float(prob_matrix[2, 0])
                                back_odds = est_odds['bookie_cs_20']
                                is_cs = (fthg == 2 and ftag == 0)
                            elif cs_code == 'cs_21':
                                back_prob = float(prob_matrix[2, 1])
                                back_odds = est_odds['bookie_cs_21']
                                is_cs = (fthg == 2 and ftag == 1)
                            elif cs_code == 'cs_00':
                                back_prob = float(prob_matrix[0, 0])
                                back_odds = est_odds['bookie_cs_00']
                                is_cs = (fthg == 0 and ftag == 0)
                            elif cs_code == 'cs_11':
                                back_prob = float(prob_matrix[1, 1])
                                back_odds = est_odds['bookie_cs_11']
                                is_cs = (fthg == 1 and ftag == 1)
                            elif cs_code == 'cs_01':
                                back_prob = float(prob_matrix[0, 1])
                                back_odds = est_odds['bookie_cs_01']
                                is_cs = (fthg == 0 and ftag == 1)
                            elif cs_code == 'cs_02':
                                back_prob = float(prob_matrix[0, 2])
                                back_odds = est_odds['bookie_cs_02']
                                is_cs = (fthg == 0 and ftag == 2)
                            elif cs_code == 'cs_12':
                                back_prob = float(prob_matrix[1, 2])
                                back_odds = est_odds['bookie_cs_12']
                                is_cs = (fthg == 1 and ftag == 2)
                            
                            model_prob = 1.0 - back_prob
                            bookie_odds = 1.0 / (1.0 - 1.0/back_odds) if (back_odds > 1.0001) else np.nan
                            bet_won = not is_cs
                            
                model_prob = float(model_prob)
                
                # Assemble ML Features
                elo_diff = float(elo_factor_h - elo_factor_a)
                features = [
                    float(lambda_home), float(lambda_away),
                    float(h_att), float(h_def), float(a_att), float(a_def),
                    elo_diff, model_prob,
                    float(h_xg_att), float(h_xg_def), float(a_xg_att), float(a_xg_def),
                    float(rest_days_home), float(rest_days_away),
                    float(motivation_home), float(motivation_away)
                ]
                
                # 1. Ensemble Blending
                if use_ml and mkt in self.ml_ensembles and self.ml_ensembles[mkt].is_fitted:
                    ml_prob = self.ml_ensembles[mkt].predict_proba(features)
                    if ml_prob is not None:
                        model_prob = (model_prob + ml_prob) / 2.0
                        
                raw_prob = model_prob

                # 2. Apply Platt Calibration
                if mkt in self.calibrators:
                    model_prob = self.calibrators[mkt].calibrate(model_prob)
                    
                # 3. Store History
                if use_ml:
                    self.ml_history[mkt]['X'].append(features)
                    self.ml_history[mkt]['y'].append(1 if bet_won else 0)
                
                self.calibration_history[mkt]['probs'].append(raw_prob)
                self.calibration_history[mkt]['outcomes'].append(1 if bet_won else 0)
                            
                if not pd.isna(bookie_odds) and bookie_odds > 1.0:
                    if min_odds <= bookie_odds <= max_odds:
                        expected_value = model_prob * bookie_odds
                        if expected_value >= value_threshold:
                            return bookie_odds, model_prob, expected_value, bet_won
                return None
                
            # Run parallel updates
            def process_bet_on_state(state_ref, p_mkt, p_odds, p_prob, p_ev, p_won):
                date_str_check = match_date.strftime('%Y-%m-%d')
                state_ref['daily_bet_count'][date_str_check] += 1
                n_bets_today = state_ref['daily_bet_count'][date_str_check]
                
                if staking_rule == 'fixed':
                    p_stake = stake_value
                elif staking_rule == 'proportional':
                    p_stake = state_ref['bankroll'] * (stake_value / 100.0)
                elif staking_rule == 'kelly':
                    p_f_star = (p_prob * p_odds - 1.0) / (p_odds - 1.0)
                    p_f_star = max(0.0, p_f_star)
                    p_stake = state_ref['bankroll'] * p_f_star * stake_value
                    p_stake = min(p_stake, state_ref['bankroll'] * 0.10)
                else:
                    p_stake = 0.0
                    
                if staking_rule != 'fixed':
                    if n_bets_today > 1:
                        p_stake = p_stake / math.sqrt(n_bets_today)
                        
                    if state_ref['daily_exposure'][date_str_check] + p_stake > state_ref['bankroll'] * 0.10:
                        p_stake = max(0, state_ref['bankroll'] * 0.10 - state_ref['daily_exposure'][date_str_check])
                    
                if p_stake > 0.01 and state_ref['bankroll'] >= p_stake:
                    state_ref['daily_exposure'][date_str_check] += p_stake
                    state_ref['total_staked'] += p_stake
                    state_ref['total_bets'] += 1
                    
                    if isinstance(p_won, bool):
                        multiplier = 1.0 if p_won else -1.0
                    else:
                        multiplier = float(p_won)

                    if multiplier > 0:
                        p_profit = p_stake * (p_odds - 1.0) * multiplier
                        state_ref['bankroll'] += p_profit
                        if multiplier == 1.0:
                            state_ref['wins'] += 1
                    elif multiplier < 0:
                        p_profit = p_stake * multiplier
                        state_ref['bankroll'] += p_profit
                    else:
                        p_profit = 0.0
                        
                        
                    p_clv = None
                    p_closing_odd = None
                    if p_mkt in ('home', '1x2_home'): p_closing_odd = closing_odds_h
                    elif p_mkt in ('away', '1x2_away'): p_closing_odd = closing_odds_a
                    elif p_mkt in ('draw', '1x2_draw'): p_closing_odd = closing_odds_d
                    elif p_mkt == 'over25': p_closing_odd = closing_odds_over25
                    elif p_mkt == 'under25': p_closing_odd = closing_odds_under25
                    if p_closing_odd and not pd.isna(p_closing_odd) and p_closing_odd > 1.0:
                        p_clv = (p_odds / p_closing_odd - 1.0) * 100
                        
                    state_ref['bets_for_ai'].append({
                        'date': match_date.strftime('%Y-%m-%d'),
                        'league': league_code,
                        'home_team': home_team,
                        'away_team': away_team,
                        'score': f"{int(fthg)}-{int(ftag)}",
                        'market': p_mkt,
                        'odds': round(p_odds, 2),
                        'prob': round(p_prob * 100, 1),
                        'ev': round(p_ev, 2),
                        'stake': round(p_stake, 2),
                        'profit': round(p_profit, 2),
                        'bankroll': round(state_ref['bankroll'], 2),
                        'clv': round(p_clv, 2) if p_clv is not None else None
                    })

            if match_date <= end_dt:
                if scan_type == 'markets':
                    for mkt in markets_list:
                        res = eval_market(mkt)
                        if res:
                            process_bet_on_state(states[mkt], mkt, res[0], res[1], res[2], res[3])
                elif scan_type == 'leagues':
                    res = eval_market(markets_list[0])
                    if res and league_code in states:
                        process_bet_on_state(states[league_code], markets_list[0], res[0], res[1], res[2], res[3])
                elif scan_type == 'combinations':
                    for mkt in markets_list:
                        res = eval_market(mkt)
                        if res:
                            k = f"{league_code}|{mkt}"
                            if k in states:
                                process_bet_on_state(states[k], mkt, res[0], res[1], res[2], res[3])
                                
            self._update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                              league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                              team_home_sot, team_home_sot_conceded, team_away_sot, team_away_sot_conceded,
                              league_home_sot, league_away_sot, hst, ast,
                              team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                              league_home_xg, league_away_xg, hxg, axg,
                              team_home_scored_ht, team_home_conceded_ht, team_away_scored_ht, team_away_conceded_ht,
                              league_home_goals_ht, league_away_goals_ht, hthg, htag)
                              
            # Fit Calibration Periodically
            self.matches_since_calibration += 1
            if self.matches_since_calibration >= 100:
                self.matches_since_calibration = 0
                for c_mkt, hist in self.calibration_history.items():
                    if len(hist['probs']) > 2000:
                        hist['probs'] = hist['probs'][-2000:]
                        hist['outcomes'] = hist['outcomes'][-2000:]
                    if len(hist['probs']) >= 50:
                        if c_mkt not in self.calibrators:
                            self.calibrators[c_mkt] = PlattCalibrator(epochs=200)
                        self.calibrators[c_mkt].fit(hist['probs'], hist['outcomes'])
                        
            # Fit ML Ensemble Periodically
            if use_ml:
                self.matches_since_ml_fit += 1
            if self.matches_since_ml_fit >= 300:
                self.matches_since_ml_fit = 0
                for c_mkt, hist in self.ml_history.items():
                    if len(hist['X']) > 3000:
                        hist['X'] = hist['X'][-3000:]
                        hist['y'] = hist['y'][-3000:]
                    if len(hist['X']) >= 100:
                        if c_mkt not in self.ml_ensembles:
                            self.ml_ensembles[c_mkt] = MLEnsemble(c_mkt)
                        self.ml_ensembles[c_mkt].fit(hist['X'], hist['y'])
            elo_tracker.update(home_team, away_team, int(fthg), int(ftag))
            
            rho_data = league_goals_for_rho[league_code]
            rho_data['h'].append(int(fthg))
            rho_data['a'].append(int(ftag))
            rho_data['lh'].append(lambda_home if 'lambda_home' in dir() else 1.3)
            rho_data['la'].append(lambda_away if 'lambda_away' in dir() else 1.0)
            if len(rho_data['h']) % 50 == 0:
                league_rho_cache.pop(league_code, None)
        # Compile summaries
        summaries = {}
        for key, state in states.items():
            net_profit = state['bankroll'] - initial_bankroll
            roi = (net_profit / state['total_staked'] * 100) if state['total_staked'] > 0 else 0.0
            win_rate = (state['wins'] / state['total_bets'] * 100) if state['total_bets'] > 0 else 0.0
            
            # Compute AI score if we have enough bets
            ai_score = 0.0
            if len(state['bets_for_ai']) >= 20:
                try:
                    ai_res = predict_strategy_sustainability(
                        state['bets_for_ai'],
                        initial_bankroll=initial_bankroll,
                        value_threshold=value_threshold,
                        staking_rule=staking_rule,
                        stake_value=stake_value,
                        run_monte_carlo=False
                    )
                    ai_score = ai_res.get('ml_probability', 0.0)
                except Exception as e:
                    print(f"Error computing AI score for {key}: {e}")
                    
            # Calcular p-value para significância estatística
            avg_odds = 2.0
            avg_expected_value = 0.0
            if state['bets_for_ai']:
                avg_odds = float(np.mean([float(b['odds']) for b in state['bets_for_ai']]))
                avg_expected_value = float(np.mean([float(b.get('ev', 1.0)) for b in state['bets_for_ai']]))
            p_value = compute_pvalue_binomial(state['wins'], state['total_bets'], avg_odds)

            # --- Out-of-Sample (OOS) Summary for EQS ---
            oos_summary = None
            if len(state['bets_for_ai']) >= 20:
                # Pegamos os últimos 20% das apostas
                n_oos = max(10, int(len(state['bets_for_ai']) * 0.2))
                oos_bets = state['bets_for_ai'][-n_oos:]
                
                oos_staked = sum([b['stake'] for b in oos_bets])
                oos_profit = sum([b['profit'] for b in oos_bets])
                oos_roi = (oos_profit / oos_staked * 100) if oos_staked > 0 else 0.0
                oos_wins = sum([1 for b in oos_bets if b['profit'] > 0])
                oos_win_rate = (oos_wins / len(oos_bets) * 100) if oos_bets else 0.0
                
                oos_summary = {
                    'net_profit': round(oos_profit, 2),
                    'roi': round(oos_roi, 2),
                    'win_rate': round(oos_win_rate, 1),
                    'total_bets': len(oos_bets)
                }

            # Simular o max_drawdown (simplificado)
            max_drawdown = 0.0
            peak = initial_bankroll
            current_bank = initial_bankroll
            for b in state['bets_for_ai']:
                current_bank += b['profit']
                if current_bank > peak:
                    peak = current_bank
                dd = (peak - current_bank) / peak if peak > 0 else 0
                if dd > max_drawdown:
                    max_drawdown = dd
                    
            # --- Advanced Metrics for EQS ---
            brier_improvement = None
            power_ratio = None
            bootstrap_roi_ci_lower = None
            edge_decay_pct = None

            if len(state['bets_for_ai']) >= 20:
                # 1. Power Ratio
                power_res = compute_power_analysis(roi, avg_odds, state['total_bets'])
                power_ratio = power_res.get('power_ratio')

                # 2. Brier Score Improvement
                brier_res = compute_brier_score(state['bets_for_ai'])
                brier_improvement = brier_res.get('improvement_pct')

                # 3. Bootstrap CI (Fast, 100 resamples for scanner)
                boot_res = compute_bootstrap_ci(state['bets_for_ai'], n_resamples=100)
                bootstrap_roi_ci_lower = boot_res.get('bootstrap_roi_ci_lower')

                # 4. Rolling ROI / Edge Decay
                window = max(10, min(100, int(len(state['bets_for_ai']) * 0.2)))
                roll_res = compute_rolling_roi(state['bets_for_ai'], window=window)
                edge_decay_pct = roll_res.get('edge_decay_pct')
                
            valid_clvs = [b.get('clv') for b in state['bets_for_ai'] if b.get('clv') is not None]
            avg_clv = float(np.mean(valid_clvs)) if valid_clvs else None
            bcl_percent = round(len([clv for clv in valid_clvs if clv > 0]) / len(valid_clvs) * 100, 1) if valid_clvs else None

            summaries[key] = {
                'net_profit': round(net_profit, 2),
                'roi': round(roi, 2),
                'win_rate': round(win_rate, 1),
                'total_bets': state['total_bets'],
                'ai_score': ai_score,
                'p_value': p_value,
                'avg_odds': round(avg_odds, 2),
                'avg_expected_value': round(avg_expected_value, 3),
                'max_drawdown': round(max_drawdown * 100, 2), # In percentage
                'oos_summary': oos_summary,
                'power_ratio': power_ratio,
                'brier_improvement': brier_improvement,
                'bootstrap_roi_ci_lower': bootstrap_roi_ci_lower,
                'edge_decay_pct': edge_decay_pct,
                'avg_clv': round(avg_clv, 2) if avg_clv is not None else None,
                'bcl_percent': bcl_percent
            }
            
            # --- Nível 2: Otimização de Faixa de Odds ---
            base_summary = summaries[key]
            base_eqs_data = compute_edge_quality_score(base_summary, oos_summary)
            base_eqs_score = base_eqs_data.get('score', 0)
            
            best_opt_score = base_eqs_score
            best_opt_range = None
            
            if len(state['bets_for_ai']) >= 30: # Precisa de amostra pra fatiar
                odds_slices = {
                    'Qualquer Odd': lambda b: True,
                    'Super Favoritos (<= 1.50)': lambda b: b['odds'] <= 1.50,
                    'Favoritos (1.50 - 2.00)': lambda b: 1.50 < b['odds'] <= 2.00,
                    'Odds Médias (2.00 - 3.00)': lambda b: 2.00 < b['odds'] <= 3.00,
                    'Zebras (> 3.00)': lambda b: b['odds'] > 3.00,
                    'Excluir Zebras (<= 3.00)': lambda b: b['odds'] <= 3.00,
                    'Excluir Super Favs (> 1.50)': lambda b: b['odds'] > 1.50
                }
                
                ev_slices = {
                    '': lambda b: True,
                    ' + Gatilho EV > 1.05': lambda b: b.get('ev', 1.0) > 1.05,
                    ' + Gatilho EV > 1.10': lambda b: b.get('ev', 1.0) > 1.10,
                    ' + Gatilho EV > 1.15': lambda b: b.get('ev', 1.0) > 1.15,
                    ' + Gatilho EV > 1.25': lambda b: b.get('ev', 1.0) > 1.25
                }
                
                slices = {}
                for o_name, o_func in odds_slices.items():
                    for e_name, e_func in ev_slices.items():
                        if o_name == 'Qualquer Odd' and e_name == '':
                            continue
                        name = o_name + e_name
                        slices[name] = lambda b, o=o_func, e=e_func: o(b) and e(b)
                
                for s_name, s_func in slices.items():
                    s_bets = [b for b in state['bets_for_ai'] if s_func(b)]
                    if len(s_bets) >= 20: # Amostra mínima na fatia
                        s_staked = sum([b['stake'] for b in s_bets])
                        s_profit = sum([b['profit'] for b in s_bets])
                        s_roi = (s_profit / s_staked * 100) if s_staked > 0 else 0.0
                        
                        # Filtro rápido: só recalcular EQS profundo se ROI da fatia for melhor
                        if s_roi > 0 and s_roi > base_summary['roi'] + 2.0:
                            s_wins = sum([1 for b in s_bets if b['profit'] > 0])
                            s_avg_odds = float(np.mean([b['odds'] for b in s_bets]))
                            s_avg_ev = float(np.mean([b.get('ev', 1.0) for b in s_bets]))
                            
                            s_oos_summary = None
                            n_oos = max(10, int(len(s_bets) * 0.2))
                            s_oos_bets = s_bets[-n_oos:]
                            s_oos_staked = sum([b['stake'] for b in s_oos_bets])
                            s_oos_profit = sum([b['profit'] for b in s_oos_bets])
                            if s_oos_staked > 0:
                                s_oos_roi = (s_oos_profit / s_oos_staked * 100)
                                s_oos_wins = sum([1 for b in s_oos_bets if b['profit'] > 0])
                                s_oos_summary = {
                                    'roi': round(s_oos_roi, 2),
                                    'win_rate': round((s_oos_wins / len(s_oos_bets) * 100), 1)
                                }
                                
                            s_p_value = compute_pvalue_binomial(s_wins, len(s_bets), s_avg_odds)
                            s_power = compute_power_analysis(s_roi, s_avg_odds, len(s_bets)).get('power_ratio')
                            s_brier = compute_brier_score(s_bets).get('improvement_pct')
                            s_boot = compute_bootstrap_ci(s_bets, n_resamples=100).get('bootstrap_roi_ci_lower')
                            s_decay = compute_rolling_roi(s_bets, window=max(10, int(len(s_bets)*0.2))).get('edge_decay_pct')
                            
                            s_valid_clvs = [b.get('clv') for b in s_bets if b.get('clv') is not None]
                            s_avg_clv = float(np.mean(s_valid_clvs)) if s_valid_clvs else None
                            
                            s_summary = {
                                'roi': s_roi,
                                'bootstrap_roi_ci_lower': s_boot,
                                'avg_clv': s_avg_clv,
                                'edge_decay_pct': s_decay,
                                'p_value': s_p_value,
                                'power_ratio': s_power,
                                'brier_improvement': s_brier
                            }
                            
                            s_eqs_data = compute_edge_quality_score(s_summary, s_oos_summary)
                            s_eqs_score = s_eqs_data.get('score', 0)
                            
                            if s_eqs_score > best_opt_score and s_eqs_score >= 60:
                                best_opt_score = s_eqs_score
                                best_opt_range = s_name

            if best_opt_range and best_opt_score >= base_eqs_score + 5:
                summaries[key]['optimized_odds_range'] = best_opt_range
                summaries[key]['optimized_eqs_score'] = best_opt_score

        return summaries

    def _update_form(self, team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
                     league_home_goals, league_away_goals, league_code, home_team, away_team, fthg, ftag,
                     team_home_sot=None, team_home_sot_conceded=None, team_away_sot=None, team_away_sot_conceded=None,
                     league_home_sot=None, league_away_sot=None, hst=None, ast=None,
                     team_home_xg=None, team_home_xg_conceded=None, team_away_xg=None, team_away_xg_conceded=None,
                     league_home_xg=None, league_away_xg=None, hxg=None, axg=None,
                     team_home_scored_ht=None, team_home_conceded_ht=None, team_away_scored_ht=None, team_away_conceded_ht=None,
                     league_home_goals_ht=None, league_away_goals_ht=None, hthg=None, htag=None):
        """Helper to append current match results to team form databases."""
        if not pd.isna(fthg) and not pd.isna(ftag):
            team_home_scored[home_team].append(fthg)
            team_home_conceded[home_team].append(ftag)
            team_away_scored[away_team].append(ftag)
            team_away_conceded[away_team].append(fthg)
            
            league_home_goals[league_code].append(fthg)
            league_away_goals[league_code].append(ftag)
            
        if hthg is not None and htag is not None and not pd.isna(hthg) and not pd.isna(htag):
            if team_home_scored_ht is not None:
                team_home_scored_ht[home_team].append(hthg)
                team_home_conceded_ht[home_team].append(htag)
                team_away_scored_ht[away_team].append(htag)
                team_away_conceded_ht[away_team].append(hthg)
                league_home_goals_ht[league_code].append(hthg)
                league_away_goals_ht[league_code].append(htag)

            if hst is not None and ast is not None and not pd.isna(hst) and not pd.isna(ast):
                if team_home_sot is not None:
                    team_home_sot[home_team].append(hst)
                    team_home_sot_conceded[home_team].append(ast)
                    team_away_sot[away_team].append(ast)
                    team_away_sot_conceded[away_team].append(hst)
                    league_home_sot[league_code].append(hst)
                    league_away_sot[league_code].append(ast)
                    
            if hxg is not None and axg is not None and not pd.isna(hxg) and not pd.isna(axg):
                if team_home_xg is not None:
                    team_home_xg[home_team].append(hxg)
                    team_home_xg_conceded[home_team].append(axg)
                    team_away_xg[away_team].append(axg)
                    team_away_xg_conceded[away_team].append(hxg)
                    league_home_xg[league_code].append(hxg)
                    league_away_xg[league_code].append(axg)

    def _calculate_xg_ratings(self, team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                              league_home_xg, league_away_xg, home_team, away_team, league_code):
        h_xg_scored = team_home_xg[home_team][-self.rolling_games:]
        h_xg_conceded = team_home_xg_conceded[home_team][-self.rolling_games:]
        a_xg_scored = team_away_xg[away_team][-self.rolling_games:]
        a_xg_conceded = team_away_xg_conceded[away_team][-self.rolling_games:]
        
        leg_h_xg = league_home_xg[league_code][-100:]
        leg_a_xg = league_away_xg[league_code][-100:]
        
        has_xg_data = (h_xg_scored and h_xg_conceded and a_xg_scored and a_xg_conceded and leg_h_xg and leg_a_xg)
        if has_xg_data:
            avg_h_xg = np.mean(leg_h_xg)
            avg_a_xg = np.mean(leg_a_xg)
            if pd.isna(avg_h_xg) or avg_h_xg == 0: avg_h_xg = 1.35
            if pd.isna(avg_a_xg) or avg_a_xg == 0: avg_a_xg = 1.05
            
            h_xg_att = (weighted_mean(h_xg_scored, 0.06) / avg_h_xg) if h_xg_scored else 1.0
            h_xg_def = (weighted_mean(h_xg_conceded, 0.06) / avg_a_xg) if h_xg_conceded else 1.0
            a_xg_att = (weighted_mean(a_xg_scored, 0.06) / avg_a_xg) if a_xg_scored else 1.0
            a_xg_def = (weighted_mean(a_xg_conceded, 0.06) / avg_h_xg) if a_xg_conceded else 1.0
            
            h_xg_att = 1.0 if pd.isna(h_xg_att) else max(0.2, min(4.0, h_xg_att))
            h_xg_def = 1.0 if pd.isna(h_xg_def) else max(0.2, min(4.0, h_xg_def))
            a_xg_att = 1.0 if pd.isna(a_xg_att) else max(0.2, min(4.0, a_xg_att))
            a_xg_def = 1.0 if pd.isna(a_xg_def) else max(0.2, min(4.0, a_xg_def))
            
            return h_xg_att, h_xg_def, a_xg_att, a_xg_def
        else:
            return 1.0, 1.0, 1.0, 1.0

    def _calculate_motivation(self, standings_dict, team, games_played_dict):
        if team not in standings_dict:
            return 0.5
            
        standings = sorted(standings_dict.items(), key=lambda x: x[1], reverse=True)
        num_teams = len(standings)
        
        if num_teams > 3:
            try:
                rank = [t for t, p in standings].index(team)
            except ValueError:
                rank = num_teams // 2
            rel_rank = rank / (num_teams - 1)
        else:
            rel_rank = 0.5
            
        # Define baseline motivation based on relative standing (relegation battle or title race)
        if rel_rank <= 0.25 or rel_rank >= 0.75:
            rel_motivation = 1.0
        elif 0.35 <= rel_rank <= 0.65:
            rel_motivation = 0.0
        else:
            # Linear interpolation
            if rel_rank < 0.35:
                rel_motivation = 1.0 - (rel_rank - 0.25) / 0.10
            else:
                rel_motivation = (rel_rank - 0.65) / 0.10
                
        # Season progress
        games = games_played_dict.get(team, 0)
        # Estimate season length
        season_length = 38
        if num_teams > 5:
            season_length = 2 * (num_teams - 1)
            
        progress = min(1.0, games / season_length)
        
        # Motivation weight: only matters in the last 30% of the season
        if progress > 0.70:
            weight = (progress - 0.70) / 0.30
            motivation = rel_motivation * weight + 0.5 * (1.0 - weight)
        else:
            motivation = 0.5
            
        return motivation
