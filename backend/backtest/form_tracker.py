import pandas as pd
import numpy as np
from .helpers import weighted_mean, get_league_weighted_decay

def update_form(team_home_scored, team_home_conceded, team_away_scored, team_away_conceded,
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

    # HT goals — independent of FT goals, SOT, and xG
    if hthg is not None and htag is not None and not pd.isna(hthg) and not pd.isna(htag):
        if team_home_scored_ht is not None:
            team_home_scored_ht[home_team].append(hthg)
            team_home_conceded_ht[home_team].append(htag)
            team_away_scored_ht[away_team].append(htag)
            team_away_conceded_ht[away_team].append(hthg)
            league_home_goals_ht[league_code].append(hthg)
            league_away_goals_ht[league_code].append(htag)

    # SOT — independent of HT and xG (was nested inside HT check, fixed 02/07/2026)
    if hst is not None and ast is not None and not pd.isna(hst) and not pd.isna(ast):
        if team_home_sot is not None:
            team_home_sot[home_team].append(hst)
            team_home_sot_conceded[home_team].append(ast)
            team_away_sot[away_team].append(ast)
            team_away_sot_conceded[away_team].append(hst)
            league_home_sot[league_code].append(hst)
            league_away_sot[league_code].append(ast)

    # xG — independent of HT and SOT (was nested inside HT check, fixed 02/07/2026)
    if hxg is not None and axg is not None and not pd.isna(hxg) and not pd.isna(axg):
        if team_home_xg is not None:
            team_home_xg[home_team].append(hxg)
            team_home_xg_conceded[home_team].append(axg)
            team_away_xg[away_team].append(axg)
            team_away_xg_conceded[away_team].append(hxg)
            league_home_xg[league_code].append(hxg)
            league_away_xg[league_code].append(axg)

def calculate_xg_ratings(team_home_xg, team_home_xg_conceded, team_away_xg, team_away_xg_conceded,
                         league_home_xg, league_away_xg, home_team, away_team, league_code, rolling_games=15):
    h_xg_scored = team_home_xg[home_team][-rolling_games:]
    h_xg_conceded = team_home_xg_conceded[home_team][-rolling_games:]
    a_xg_scored = team_away_xg[away_team][-rolling_games:]
    a_xg_conceded = team_away_xg_conceded[away_team][-rolling_games:]
    
    leg_h_xg = league_home_xg[league_code][-100:]
    leg_a_xg = league_away_xg[league_code][-100:]
    
    has_xg_data = (h_xg_scored and h_xg_conceded and a_xg_scored and a_xg_conceded and leg_h_xg and leg_a_xg)
    if has_xg_data:
        avg_h_xg = np.mean(leg_h_xg)
        avg_a_xg = np.mean(leg_a_xg)
        if pd.isna(avg_h_xg) or avg_h_xg == 0: avg_h_xg = 1.35
        if pd.isna(avg_a_xg) or avg_a_xg == 0: avg_a_xg = 1.05

        _decay = get_league_weighted_decay(league_code)
        h_xg_att = (weighted_mean(h_xg_scored, _decay) / avg_h_xg) if h_xg_scored else 1.0
        h_xg_def = (weighted_mean(h_xg_conceded, _decay) / avg_a_xg) if h_xg_conceded else 1.0
        a_xg_att = (weighted_mean(a_xg_scored, _decay) / avg_a_xg) if a_xg_scored else 1.0
        a_xg_def = (weighted_mean(a_xg_conceded, _decay) / avg_h_xg) if a_xg_conceded else 1.0
        
        h_xg_att = 1.0 if pd.isna(h_xg_att) else max(0.2, min(4.0, h_xg_att))
        h_xg_def = 1.0 if pd.isna(h_xg_def) else max(0.2, min(4.0, h_xg_def))
        a_xg_att = 1.0 if pd.isna(a_xg_att) else max(0.2, min(4.0, a_xg_att))
        a_xg_def = 1.0 if pd.isna(a_xg_def) else max(0.2, min(4.0, a_xg_def))
        
        return h_xg_att, h_xg_def, a_xg_att, a_xg_def
    else:
        return 1.0, 1.0, 1.0, 1.0

def calculate_motivation(standings_dict, team, games_played_dict):
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
        
    if rel_rank <= 0.25 or rel_rank >= 0.75:
        rel_motivation = 1.0
    elif 0.35 <= rel_rank <= 0.65:
        rel_motivation = 0.0
    else:
        if rel_rank < 0.35:
            rel_motivation = 1.0 - (rel_rank - 0.25) / 0.10
        else:
            rel_motivation = (rel_rank - 0.65) / 0.10
            
    games = games_played_dict.get(team, 0)
    season_length = 38
    if num_teams > 5:
        season_length = 2 * (num_teams - 1)
        
    progress = min(1.0, games / season_length)
    
    if progress > 0.70:
        weight = (progress - 0.70) / 0.30
        motivation = rel_motivation * weight + 0.5 * (1.0 - weight)
    else:
        motivation = 0.5
        
    return motivation
