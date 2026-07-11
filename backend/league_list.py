"""Lightweight league listing — no pandas, no CSV loading. Safe to import on Render Free tier."""

import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

# League configuration — mirrors data_loader.py without the heavy imports
LEAGUES_SEASONAL = {
    'E0': 'England Premier League', 'E1': 'England Championship',
    'E2': 'England League One', 'E3': 'England League Two',
    'SP1': 'Spain La Liga 1', 'SP2': 'Spain La Liga 2',
    'I1': 'Italy Serie A', 'I2': 'Italy Serie B',
    'D1': 'Germany Bundesliga 1', 'D2': 'Germany Bundesliga 2',
    'F1': 'France Ligue 1', 'F2': 'France Ligue 2',
    'N1': 'Netherlands Eredivisie', 'B1': 'Belgian Pro League',
    'P1': 'Portugal Primeira Liga', 'T1': 'Turkey Super Lig',
    'G1': 'Greece Super League',
    'SC0': 'Scotland Premier League', 'SC1': 'Scotland Championship',
}

LEAGUES_AGGREGATE = {
    'ARG': 'Argentina Primera Division', 'BRA': 'Brazil Serie A',
    'USA': 'USA MLS', 'MEX': 'Mexico Liga MX',
    'JPN': 'Japan J-League', 'SWEDEN_ALLSVENSKAN': 'Sweden Allsvenskan',
    'NORWAY_ELITESERIEN': 'Norway Eliteserien',
}

SOUTH_AMERICAN_LEAGUES = {'ARG', 'BRA', 'MEX', 'USA'}
SEASONS = ['2021', '2122', '2223', '2324', '2425', '2526']


def _load_futpython_leagues_from_json():
    """Reads futpython_leagues.json — lightweight, no pandas needed."""
    config_path = os.path.join(DATA_DIR, 'futpython_leagues.json')
    if not os.path.exists(config_path):
        return []
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
        leagues = []
        for pais, ligas in mapping.items():
            for liga in ligas:
                code = f"{pais}/{liga}"
                display_code = code.upper().replace('/', ' | ')
                display_name = liga.replace('-', ' ').title()
                leagues.append({
                    'code': code,
                    'name': f"{display_code}",
                    'type': 'futpython',
                })
        return leagues
    except Exception:
        return []


def _scan_disk_for_aggregate_leagues():
    """Scan data/ for *_all.csv files not yet in hardcoded lists."""
    import glob
    import re
    existing = set()
    existing.update(LEAGUES_SEASONAL.keys())
    existing.update(LEAGUES_AGGREGATE.keys())

    leagues = []
    for filepath in glob.glob(os.path.join(DATA_DIR, '*_all.csv')):
        filename = os.path.basename(filepath)
        # Skip empty/corrupt placeholder files (<= 5000 bytes)
        if os.path.getsize(filepath) <= 5000:
            continue
        # Skip old-format footystats files (mixed-case names like "Argentina_all.csv", "Austria_all.csv")
        # These use Portuguese column names (Casa, Fora, Gols Casa) and lack B365 odds columns.
        # Standard football-data.co.uk files are always uppercase: ARG_all.csv, AUSTRIA_BUNDESLIGA_all.csv.
        code_raw = filename.replace('_all.csv', '')
        if code_raw != code_raw.upper():
            continue
        original_filename = filename
        code = code_raw
        # Normalize spaces to underscores (legacy files like "Australia A_all.csv")
        if ' ' in code:
            code = re.sub(r'\s+', '_', code.strip()).upper()
        if code in existing:
            continue
        name = code.replace('_', ' ').title()
        league_entry = {'code': code, 'name': name, 'type': 'aggregate'}
        if original_filename != f"{code}_all.csv":
            league_entry['original_filename'] = original_filename
        leagues.append(league_entry)
        existing.add(code)

    return leagues


def get_all_available_leagues(source="footballdata"):
    """Returns a list of all supported leagues. Pure data — no I/O."""
    if source == 'futpython':
        leagues = _load_futpython_leagues_from_json()
        if leagues:
            return leagues
        # Fallback: return only south american aggregate leagues
        all_leagues = []
        for code, name in LEAGUES_AGGREGATE.items():
            if code in SOUTH_AMERICAN_LEAGUES:
                all_leagues.append({'code': code, 'name': name, 'type': 'aggregate'})
        return all_leagues

    all_leagues = []
    seen_codes = set()

    for code, name in LEAGUES_SEASONAL.items():
        all_leagues.append({'code': code, 'name': name, 'type': 'seasonal'})
        seen_codes.add(code)

    for code, name in LEAGUES_AGGREGATE.items():
        all_leagues.append({'code': code, 'name': name, 'type': 'aggregate'})
        seen_codes.add(code)

    # Scan disk for additional aggregate CSV files
    for league in _scan_disk_for_aggregate_leagues():
        if league['code'] not in seen_codes:
            all_leagues.append(league)
            seen_codes.add(league['code'])

    return all_leagues
