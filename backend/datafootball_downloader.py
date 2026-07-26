"""
DataFootball API Historical Downloader

Downloads all seasons for all available leagues from the DataFootball API
and converts them to CSV files compatible with the backtester engine.

Usage:
    python -m backend.datafootball_downloader           # download all
    python -m backend.datafootball_downloader --test    # test with 1 league
"""

import os
import json
import time
import logging
import urllib.parse
import pandas as pd
import numpy as np
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
BASE_URL = "https://webhook.datafootball.com.br/webhook"


def _get_token():
    """Load token from api_config.json or env var."""
    config_path = os.path.join(DATA_DIR, 'api_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            tok = config.get('token')
            if tok:
                return tok
    return os.environ.get('DATAFOOTBALL_API_KEY')


def fetch_seasons(headers):
    """Get list of available season names from the API."""
    r = requests.get(f"{BASE_URL}/seasons", headers=headers, timeout=15)
    if r.status_code == 200:
        seasons = r.json()
        return [s.get('season') or s.get('name') for s in seasons if isinstance(s, dict)]
    return []


def fetch_league_matches(league_name, season_name, headers, max_retries=3):
    """
    Download ALL matches for a specific league + season.
    Returns list of match dicts with FULL stats and odds fields.
    """
    url = f"{BASE_URL}/matches?liga={urllib.parse.quote(league_name)}&temporada={season_name}"

    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers, timeout=60)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    # Filter out null records
                    valid = [d for d in data if isinstance(d, dict) and d.get('home_name') and d.get('date')]
                    return valid
            elif r.status_code == 429:
                wait = (attempt + 1) * 30
                logger.warning(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                logger.warning(f"HTTP {r.status_code} for {league_name} {season_name}")
                time.sleep(5)
        except Exception as e:
            logger.error(f"Error fetching {league_name} {season_name}: {e}")
            time.sleep(5 * (attempt + 1))

    return []


def _parse_float(val):
    """Safely parse float, return NaN for None/missing."""
    try:
        if val is None:
            return np.nan
        return float(val)
    except (ValueError, TypeError):
        return np.nan


def _parse_int(val):
    """Safely parse int, return NaN for None/missing."""
    try:
        if val is None:
            return np.nan
        return int(val)
    except (ValueError, TypeError):
        return np.nan


def match_to_backtester_row(match, league_code):
    """
    Convert a single DataFootball API match dict to a row compatible
    with the backtester CSV format (football-data.co.uk schema).
    """
    return {
        'Div': league_code,
        'Date': (match.get('date') or '')[:10],  # YYYY-MM-DD
        'Time': (match.get('time') or '00:00')[:5],
        'HomeTeam': match.get('home_name', ''),
        'AwayTeam': match.get('away_name', ''),
        'FTHG': _parse_int(match.get('homeGoalCount')),
        'FTAG': _parse_int(match.get('awayGoalCount')),
        'FTR': _determine_ftr(match),
        'HTHG': _parse_int(match.get('ht_goals_team_a')),
        'HTAG': _parse_int(match.get('ht_goals_team_b')),
        'HTR': _determine_htr(match),

        # Bet365 odds (1X2)
        'B365H': _parse_float(match.get('odds_ft_1')),
        'B365D': _parse_float(match.get('odds_ft_x')),
        'B365A': _parse_float(match.get('odds_ft_2')),

        # Over/Under odds
        'B365>2.5': _parse_float(match.get('odds_ft_over25')),
        'B365<2.5': _parse_float(match.get('odds_ft_under25')),

        # BTTS odds
        'B365_BTTS_Yes': _parse_float(match.get('odds_btts_yes')),
        'B365_BTTS_No': _parse_float(match.get('odds_btts_no')),

        # HT Result odds
        'B365H_H': _parse_float(match.get('odds_1st_half_result_1')),
        'B365H_D': _parse_float(match.get('odds_1st_half_result_x')),
        'B365H_A': _parse_float(match.get('odds_1st_half_result_2')),

        # HT Over/Under odds
        'B365_HT_Over05': _parse_float(match.get('odds_1st_half_over05')),
        'B365_HT_Under05': _parse_float(match.get('odds_1st_half_under05')),
        'B365_HT_Over15': _parse_float(match.get('odds_1st_half_over15')),
        'B365_HT_Under15': _parse_float(match.get('odds_1st_half_under15')),
        'B365_HT_Over25': _parse_float(match.get('odds_1st_half_over25')),
        'B365_HT_Under25': _parse_float(match.get('odds_1st_half_under25')),
        'B365_HT_Over35': _parse_float(match.get('odds_1st_half_over35')),
        'B365_HT_Under35': _parse_float(match.get('odds_1st_half_under35')),

        # Over/Under FT extended
        'B365_Over05': _parse_float(match.get('odds_ft_over05')),
        'B365_Under05': _parse_float(match.get('odds_ft_under05')),
        'B365_Over15': _parse_float(match.get('odds_ft_over15')),
        'B365_Under15': _parse_float(match.get('odds_ft_under15')),
        'B365_Over35': _parse_float(match.get('odds_ft_over35')),
        'B365_Under35': _parse_float(match.get('odds_ft_under35')),
        'B365_Over45': _parse_float(match.get('odds_ft_over45')),
        'B365_Under45': _parse_float(match.get('odds_ft_under45')),

        # Double Chance
        'B365_DC_1X': _parse_float(match.get('odds_doublechance_1x')),
        'B365_DC_12': _parse_float(match.get('odds_doublechance_12')),
        'B365_DC_X2': _parse_float(match.get('odds_doublechance_x2')),

        # DNB
        'B365_DNB_H': _parse_float(match.get('odds_dnb_1')),
        'B365_DNB_A': _parse_float(match.get('odds_dnb_2')),

        # 2H Result odds
        'B365_2H_H': _parse_float(match.get('odds_2nd_half_result_1')),
        'B365_2H_D': _parse_float(match.get('odds_2nd_half_result_x')),
        'B365_2H_A': _parse_float(match.get('odds_2nd_half_result_2')),

        # 2H Over/Under odds
        'B365_2H_Over05': _parse_float(match.get('odds_2nd_half_over05')),
        'B365_2H_Under05': _parse_float(match.get('odds_2nd_half_under05')),
        'B365_2H_Over15': _parse_float(match.get('odds_2nd_half_over15')),
        'B365_2H_Under15': _parse_float(match.get('odds_2nd_half_under15')),
        'B365_2H_Over25': _parse_float(match.get('odds_2nd_half_over25')),
        'B365_2H_Under25': _parse_float(match.get('odds_2nd_half_under25')),
        'B365_2H_Over35': _parse_float(match.get('odds_2nd_half_over35')),
        'B365_2H_Under35': _parse_float(match.get('odds_2nd_half_under35')),

        # Win to Nil
        'B365_WinToNil_H': _parse_float(match.get('odds_win_to_nil_1')),
        'B365_WinToNil_A': _parse_float(match.get('odds_win_to_nil_2')),

        # Corners 1X2
        'B365_Corners_1': _parse_float(match.get('odds_corners_1')),
        'B365_Corners_x': _parse_float(match.get('odds_corners_x')),
        'B365_Corners_2': _parse_float(match.get('odds_corners_2')),

        # Stats
        'HS': _parse_int(match.get('team_a_shotsOnTarget')),
        'AS': _parse_int(match.get('team_b_shotsOnTarget')),
        'HST': _parse_int(match.get('team_a_shotsOnTarget')),
        'AST': _parse_int(match.get('team_b_shotsOnTarget')),
        'HC': _parse_int(match.get('team_a_corners')),
        'AC': _parse_int(match.get('team_b_corners')),
        'HY': _parse_int(match.get('team_a_yellow_cards')),
        'AY': _parse_int(match.get('team_b_yellow_cards')),
        'HR': _parse_int(match.get('team_a_red_cards')),
        'AR': _parse_int(match.get('team_b_red_cards')),

        # xG
        'HomeXG': _parse_float(match.get('team_a_xg')),
        'AwayXG': _parse_float(match.get('team_b_xg')),
        'HomeXG_Pre': _parse_float(match.get('team_a_xg_prematch')),
        'AwayXG_Pre': _parse_float(match.get('team_b_xg_prematch')),

        # Corners odds
        'B365_Corners_Over75': _parse_float(match.get('odds_corners_over_75')),
        'B365_Corners_Under75': _parse_float(match.get('odds_corners_under_75')),
        'B365_Corners_Over85': _parse_float(match.get('odds_corners_over_85')),
        'B365_Corners_Under85': _parse_float(match.get('odds_corners_under_85')),
        'B365_Corners_Over95': _parse_float(match.get('odds_corners_over_95')),
        'B365_Corners_Under95': _parse_float(match.get('odds_corners_under_95')),
        'B365_Corners_Over105': _parse_float(match.get('odds_corners_over_105')),
        'B365_Corners_Under105': _parse_float(match.get('odds_corners_under_105')),
        'B365_Corners_Over115': _parse_float(match.get('odds_corners_over_115')),
        'B365_Corners_Under115': _parse_float(match.get('odds_corners_under_115')),

        # Possession
        'HPos': _parse_int(match.get('team_a_possession')),
        'APos': _parse_int(match.get('team_b_possession')),

        # PPG
        'HomePPG': _parse_float(match.get('home_ppg')),
        'AwayPPG': _parse_float(match.get('away_ppg')),

        # Metadata
        'LeagueName': match.get('league', ''),
        'Season': match.get('season', ''),
        'GameWeek': _parse_int(match.get('game_week')),
        'Stadium': match.get('stadium_name', ''),
        'Attendance': _parse_int(match.get('attendance')),
    }


def _determine_ftr(match):
    """Full Time Result: H, D, or A"""
    hg = match.get('homeGoalCount')
    ag = match.get('awayGoalCount')
    if hg is None or ag is None:
        return ''
    if hg > ag:
        return 'H'
    elif hg < ag:
        return 'A'
    return 'D'


def _determine_htr(match):
    """Half Time Result: H, D, or A"""
    hg = match.get('ht_goals_team_a')
    ag = match.get('ht_goals_team_b')
    if hg is None or ag is None:
        return ''
    if hg > ag:
        return 'H'
    elif hg < ag:
        return 'A'
    return 'D'


def _generate_league_code(league_name):
    """Generate a stable internal code from the league name."""
    import re
    code = re.sub(r'[^a-zA-Z0-9\s\-]', '', league_name)
    code = re.sub(r'[\s\-]+', '_', code)
    return code.upper()


def download_league_season(league_name, season_name, headers, league_code=None):
    """Download one season and save to CSV."""
    if league_code is None:
        league_code = _generate_league_code(league_name)

    matches = fetch_league_matches(league_name, season_name, headers)
    if not matches:
        logger.info(f"  {league_name} {season_name}: 0 matches")
        return 0

    rows = [match_to_backtester_row(m, league_code) for m in matches]
    df = pd.DataFrame(rows)

    # Save as aggregate CSV (one file per league, appended)
    # Use the standard _all.csv naming so the data loader picks them up automatically
    filename = f"{league_code}_all.csv"
    filepath = os.path.join(DATA_DIR, filename)

    # Deduplicate: if file exists, load, concat, drop duplicates, save fresh
    if os.path.exists(filepath):
        try:
            existing = pd.read_csv(filepath, encoding='utf-8')
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(subset=['Date', 'HomeTeam', 'AwayTeam'], keep='last')
            df = df.sort_values('Date')
        except Exception:
            pass

    df.to_csv(filepath, index=False, encoding='utf-8')

    logger.info(f"  {league_name} {season_name}: {len(matches)} matches -> {filename}")
    return len(matches)


def download_all(leagues_file=None, test_mode=False):
    """
    Main entry point: download all leagues × all seasons.

    Args:
        leagues_file: JSON file with {league_name: match_count} mapping
        test_mode: If True, only download 1 league's latest season
    """
    token = _get_token()
    if not token:
        logger.error("No DataFootball API token found!")
        return

    headers = {'Authorization': f'Bearer {token}'}

    # Load league list
    if leagues_file is None:
        leagues_file = os.path.join(DATA_DIR, 'datafootball_historical_leagues.json')

    if os.path.exists(leagues_file):
        with open(leagues_file, 'r', encoding='utf-8') as f:
            leagues = json.load(f)
    else:
        logger.error(f"Leagues file not found: {leagues_file}")
        return

    if not isinstance(leagues, dict):
        logger.error("Leagues file must be a dict {name: count}")
        return

    # Get available seasons
    seasons = fetch_seasons(headers)
    logger.info(f"Available seasons: {seasons}")

    # Filter to numeric seasons (2018, 2019, ... 2026) for fastest results
    numeric_seasons = [s for s in seasons if s.isdigit() and int(s) >= 2018]
    numeric_seasons.sort()
    logger.info(f"Numeric seasons to download: {numeric_seasons}")

    league_names = sorted(leagues.keys(), key=lambda l: -leagues[l])

    if test_mode:
        league_names = [league_names[0]]
        numeric_seasons = [numeric_seasons[-1]]
        logger.info(f"TEST MODE: {league_names[0]} season {numeric_seasons[0]}")

    total_matches = 0
    start_time = time.time()

    for i, league_name in enumerate(league_names):
        league_code = _generate_league_code(league_name)
        logger.info(f"[{i+1}/{len(league_names)}] {league_name} ({league_code})")

        league_matches = 0
        for season in numeric_seasons:
            count = download_league_season(league_name, season, headers, league_code)
            league_matches += count
            total_matches += count
            time.sleep(0.5)  # Rate limiting

        logger.info(f"  {league_name}: {league_matches} total matches")
        time.sleep(1.0)  # Brief pause between leagues

    elapsed = time.time() - start_time
    logger.info(f"\nDone! {total_matches} matches across {len(league_names)} leagues")
    logger.info(f"Time: {elapsed/60:.1f} minutes")


def sync_today_completed(headers=None):
    """
    Incremental sync: fetch today's matches via /matches_day and append
    any COMPLETED matches (with final scores) to the league CSV files.

    This keeps the backtester data up-to-date daily without re-downloading
    entire seasons. Called by the scheduler every 6-12 hours.

    Returns: dict with {league_code: new_matches_count}
    """
    if headers is None:
        token = _get_token()
        if not token:
            logger.error("No DataFootball token for sync_today_completed")
            return {}
        headers = {'Authorization': f'Bearer {token}'}

    try:
        r = requests.get(f"{BASE_URL}/matches_day", headers=headers, timeout=30)
        if r.status_code != 200:
            logger.error(f"matches_day returned {r.status_code}")
            return {}
        matches = r.json()
    except Exception as e:
        logger.error(f"Error fetching matches_day: {e}")
        return {}

    if not isinstance(matches, list):
        logger.error("matches_day did not return a list")
        return {}

    # Process only COMPLETED matches with scores
    completed = [m for m in matches
                 if isinstance(m, dict)
                 and m.get('status') == 'complete'
                 and m.get('home_name')
                 and m.get('homeGoalCount') is not None
                 and m.get('awayGoalCount') is not None]

    if not completed:
        logger.info("sync_today: no completed matches today")
        return {}

    updates = {}
    for match in completed:
        league_name = match.get('league', '')
        if not league_name:
            continue

        league_code = _generate_league_code(league_name)
        row = match_to_backtester_row(match, league_code)
        filename = f"{league_code}_all.csv"
        filepath = os.path.join(DATA_DIR, filename)

        # Only append if this match isn't already in the file
        if os.path.exists(filepath):
            try:
                existing = pd.read_csv(filepath, encoding='utf-8')
                dup = existing[(existing['Date'] == row['Date']) &
                               (existing['HomeTeam'] == row['HomeTeam']) &
                               (existing['AwayTeam'] == row['AwayTeam'])]
                if len(dup) > 0:
                    continue  # Already saved, skip
            except Exception:
                pass

        # Append single row
        df = pd.DataFrame([row])
        write_header = not os.path.exists(filepath)
        df.to_csv(filepath, mode='a' if not write_header else 'w',
                  index=False, header=write_header, encoding='utf-8')

        updates[league_code] = updates.get(league_code, 0) + 1

    if updates:
        logger.info(f"sync_today: added {sum(updates.values())} new matches across {len(updates)} leagues")
        for code, count in sorted(updates.items()):
            logger.info(f"  {code}: +{count} matches")

    return updates


def get_available_datafootball_leagues():
    """Return list of league dicts for the frontend selector (same format as get_all_available_leagues)."""
    leagues_file = os.path.join(DATA_DIR, 'datafootball_historical_leagues.json')
    if not os.path.exists(leagues_file):
        return []
    with open(leagues_file, 'r', encoding='utf-8') as f:
        league_map = json.load(f)
    result = []
    for name in sorted(league_map.keys()):
        code = _generate_league_code(name)
        result.append({
            'code': code,
            'name': name,
            'type': 'datafootball',
            'match_count': league_map[name],
        })
    return result


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    if '--sync-today' in sys.argv:
        # Incremental sync only
        sync_today_completed()
    elif '--test' in sys.argv:
        download_all(test_mode=True)
    else:
        download_all(test_mode=False)
