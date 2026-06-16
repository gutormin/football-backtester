import os
import urllib.request
import pandas as pd
from datetime import datetime

def read_csv_robust(path):
    try:
        df = pd.read_csv(path, encoding='utf-8')
    except Exception:
        df = pd.read_csv(path, encoding='latin1')
        
    return translate_custom_csv(df)

def translate_custom_csv(df):
    """
    Translates Datafootball custom spreadsheet columns to standard Football-Data.co.uk format.
    """
    if 'Casa' in df.columns and 'Fora' in df.columns:
        rename_dict = {
            'Data': 'Date',
            'Casa': 'HomeTeam',
            'Fora': 'AwayTeam',
            'Gols Casa': 'FTHG',
            'Gols Fora': 'FTAG',
            'Odd 1': 'B365H',
            'Odd X': 'B365D',
            'Odd 2': 'B365A'
        }
        df.rename(columns=rename_dict, inplace=True)
        
        # Calculate FTR (Full Time Result) if missing
        if 'FTR' not in df.columns and 'FTHG' in df.columns and 'FTAG' in df.columns:
            def calc_ftr(row):
                if pd.isna(row['FTHG']) or pd.isna(row['FTAG']):
                    return None
                if row['FTHG'] > row['FTAG']:
                    return 'H'
                elif row['FTHG'] < row['FTAG']:
                    return 'A'
                return 'D'
            df['FTR'] = df.apply(calc_ftr, axis=1)
            
        # Optional: Map over/under odds if they exist in the spreadsheet
        # e.g., 'Odd Over 2.5' -> 'B365>2.5', 'Odd Under 2.5' -> 'B365<2.5'
        if 'Odd Over 2.5' in df.columns: df.rename(columns={'Odd Over 2.5': 'B365>2.5'}, inplace=True)
        if 'Odd Under 2.5' in df.columns: df.rename(columns={'Odd Under 2.5': 'B365<2.5'}, inplace=True)
            
        # Filter incomplete matches for history, but keep them if we need them for upcoming
        # However, data_loader.py is usually for history, so we only need rows with FTR
        # We won't drop them here, we let the logic below handle NaNs
        
    return df

# In-memory cache for loaded league dataframes
_LEAGUE_DATA_CACHE = {}

def clear_league_data_cache():
    global _LEAGUE_DATA_CACHE
    _LEAGUE_DATA_CACHE.clear()

# Directory to save downloaded CSV files
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

# League configuration
# Main leagues are downloaded season-by-season
LEAGUES_SEASONAL = {
    'E0': 'England Premier League',
    'E1': 'England Championship',
    'E2': 'England League One',
    'E3': 'England League Two',
    'SP1': 'Spain La Liga 1',
    'SP2': 'Spain La Liga 2',
    'I1': 'Italy Serie A',
    'I2': 'Italy Serie B',
    'D1': 'Germany Bundesliga 1',
    'D2': 'Germany Bundesliga 2',
    'F1': 'France Ligue 1',
    'F2': 'France Ligue 2',
    'N1': 'Netherlands Eredivisie',
    'B1': 'Belgian Pro League',
    'P1': 'Portugal Primeira Liga',
    'T1': 'Turkey Super Lig',
    'G1': 'Greece Super League',
    'SC0': 'Scotland Premier League',
    'SC1': 'Scotland Championship'
}

# Extra leagues are downloaded as single combined CSVs
LEAGUES_AGGREGATE = {
    'ARG': 'Argentina Primera Division',
    'BRA': 'Brazil Serie A',
    'USA': 'USA MLS',
    'MEX': 'Mexico Liga MX',
    'JPN': 'Japan J-League'
}

SEASONS = ['2021', '2122', '2223', '2324', '2425', '2526']

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def download_file(url, local_path):
    """Downloads a file setting a User-Agent to bypass Cloudflare/503 limits."""
    print(f"Downloading {url} to {local_path}...")
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as response, open(local_path, 'wb') as out_file:
            out_file.write(response.read())
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False

def sync_data(force=False, source="csv"):
    """Downloads all missing or outdated league CSVs from Football-Data or DataFootball API."""
    clear_league_data_cache()
    ensure_data_dir()
    
    if source == "api":
        sync_data_from_api(force=force)
        return
        
    # 1. Sync Seasonal Leagues
    for league_code in LEAGUES_SEASONAL.keys():
        for season in SEASONS:
            local_filename = f"{league_code}_{season}.csv"
            local_path = os.path.join(DATA_DIR, local_filename)
            
            # Check if file exists and age
            if not force and os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                # If it's the current season (2526), we want to update it if it's older than 3 days
                if season == '2526':
                    file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(local_path))
                    if file_age.days < 3:
                        continue
                else:
                    # Past seasons are static, no need to redownload
                    continue
            
            url = f"https://www.football-data.co.uk/mmz4281/{season}/{league_code}.csv"
            download_file(url, local_path)
            
    # 2. Sync Aggregate Leagues
    for league_code in LEAGUES_AGGREGATE.keys():
        local_filename = f"{league_code}_all.csv"
        local_path = os.path.join(DATA_DIR, local_filename)
        
        # Aggregate files are regularly updated, update if older than 3 days
        if not force and os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(local_path))
            if file_age.days < 3:
                continue
                
        url = f"https://www.football-data.co.uk/new/{league_code}.csv"
        download_file(url, local_path)

def sync_single_league_from_api(league_code, force=False):
    """Sincroniza apenas uma liga específica da API do DataFootball."""
    import requests
    import numpy as np
    
    token = get_api_token()
    if not token:
        return False
        
    all_leagues = get_all_available_leagues()
    league_info = next((l for l in all_leagues if l['code'] == league_code), None)
    if not league_info:
        return False
        
    headers = {"Authorization": f"Bearer {token}"}
    base_api_url = "https://webhook.datafootball.com.br/webhook"
    
    # Check if we need to sync based on file existence/age
    is_seasonal = (league_info['type'] == 'seasonal')
    
    if is_seasonal:
        all_exist = True
        for season in SEASONS:
            local_filename = f"{league_code}_{season}.csv"
            local_path = os.path.join(DATA_DIR, local_filename)
            if not os.path.exists(local_path) or os.path.getsize(local_path) <= 250:
                all_exist = False
                break
        if not force and all_exist:
            return True
    else:
        local_filename = f"{league_code}_all.csv"
        local_path = os.path.join(DATA_DIR, local_filename)
        if not force and os.path.exists(local_path) and os.path.getsize(local_path) > 250:
            return True
            
    # Fetch seasons
    try:
        res_seasons = requests.get(f"{base_api_url}/seasons", headers=headers, timeout=15)
        if res_seasons.status_code != 200:
            return False
        seasons_list = res_seasons.json()
        
        api_league_name = league_info['api_name']
        
        def fetch_matches(api_season_name):
            season_id = None
            for s in seasons_list:
                name = s.get('name') or s.get('season')
                if name == api_season_name:
                    season_id = s.get('id') or s.get('season')
                    break
            if season_id is None:
                return pd.DataFrame()
                
            params = {
                "liga": api_league_name,
                "temporada": season_id
            }
            try:
                res = requests.get(f"{base_api_url}/matches", headers=headers, params=params, timeout=20)
                if res.status_code != 200:
                    return pd.DataFrame()
                data = res.json()
                if not isinstance(data, list) or len(data) == 0 or (len(data) == 1 and not data[0]):
                    return pd.DataFrame()
                    
                records = []
                for m in data:
                    def parse_odd(val):
                        try:
                            fval = float(val)
                            return fval if fval > 0 else np.nan
                        except (ValueError, TypeError):
                            return np.nan
                            
                    def parse_numeric(val):
                        try:
                            fval = float(val)
                            return fval if fval >= 0 else np.nan
                        except (ValueError, TypeError):
                            return np.nan
                            
                    hg = parse_numeric(m.get('homeGoalCount'))
                    ag = parse_numeric(m.get('awayGoalCount'))
                    ftr = np.nan
                    if not pd.isna(hg) and not pd.isna(ag):
                        ftr = 'H' if hg > ag else ('A' if ag > hg else 'D')
                        
                    rec = {
                        'Date': m.get('date'),
                        'Time': m.get('time', '00:00:00'),
                        'HomeTeam': m.get('home_name'),
                        'AwayTeam': m.get('away_name'),
                        'FTHG': hg,
                        'FTAG': ag,
                        'FTR': ftr,
                        'B365H': parse_odd(m.get('odds_ft_1')),
                        'B365D': parse_odd(m.get('odds_ft_x')),
                        'B365A': parse_odd(m.get('odds_ft_2')),
                        'B365>2.5': parse_odd(m.get('odds_ft_over25')),
                        'B365<2.5': parse_odd(m.get('odds_ft_under25')),
                        'HST': parse_numeric(m.get('team_a_shotsOnTarget')),
                        'AST': parse_numeric(m.get('team_b_shotsOnTarget')),
                        'HomeXG': parse_numeric(m.get('team_a_xg') or m.get('team_a_xg_prematch')),
                        'AwayXG': parse_numeric(m.get('team_b_xg') or m.get('team_b_xg_prematch'))
                    }
                    records.append(rec)
                return pd.DataFrame(records)
            except Exception:
                return pd.DataFrame()
                
        # Perform sync
        if is_seasonal:
            for season in SEASONS:
                local_filename = f"{league_code}_{season}.csv"
                local_path = os.path.join(DATA_DIR, local_filename)
                
                if not force and os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                    if season != '2526':
                        continue
                        
                season_map = {
                    '2021': '2020/2021',
                    '2122': '2021/2022',
                    '2223': '2022/2023',
                    '2324': '2023/2024',
                    '2425': '2024/2025',
                    '2526': '2025/2026'
                }
                api_season = season_map.get(season)
                if not api_season:
                    continue
                df = fetch_matches(api_season)
                if not df.empty:
                    df.to_csv(local_path, index=False, encoding='utf-8')
                    print(f"[On-Demand Sync] Saved seasonal {local_filename}")
        else:
            local_filename = f"{league_code}_all.csv"
            local_path = os.path.join(DATA_DIR, local_filename)
            dfs = []
            seasons_to_query = [
                "2020/2021", "2021",
                "2021/2022", "2022",
                "2022/2023", "2023",
                "2023/2024", "2024",
                "2024/2025", "2025",
                "2025/2026", "2026"
            ]
            for yr in seasons_to_query:
                df_yr = fetch_matches(yr)
                if not df_yr.empty:
                    dfs.append(df_yr)
            if dfs:
                combined = pd.concat(dfs, ignore_index=True)
                combined.to_csv(local_path, index=False, encoding='utf-8')
                print(f"[On-Demand Sync] Saved aggregate {local_filename}")
            else:
                if not os.path.exists(local_path) or os.path.getsize(local_path) <= 250:
                    with open(local_path, 'w', encoding='utf-8') as f:
                        f.write("Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n")
                    print(f"[On-Demand Sync] Created placeholder for empty aggregate {local_filename}")
        return True
    except Exception as e:
        print(f"Error syncing league {league_code} on-demand: {e}")
        return False

def sync_data_from_api(force=False):
    """Downloads league historical matches from DataFootball API and writes standard CSVs."""
    token = get_api_token()
    if not token:
        raise ValueError("Token do DataFootball não encontrado em data/api_config.json")
        
    all_leagues = get_all_available_leagues()
    for l in all_leagues:
        try:
            sync_single_league_from_api(l['code'], force=force)
        except Exception as e:
            print(f"Error syncing league {l['code']}: {e}")

def load_league_data(league_code, start_date='2021-01-01'):
    """Loads and standardizes data for a given league starting from a specific date."""
    global _LEAGUE_DATA_CACHE
    
    if league_code not in _LEAGUE_DATA_CACHE:
        ensure_data_dir()
        dfs = []
        
        # Get list of all available leagues to find type and name dynamically
        all_leagues = get_all_available_leagues()
        league_info = next((l for l in all_leagues if l['code'] == league_code), None)
        
        if league_info:
            # Check if dynamic / aggregate files are missing, if so auto-download on-demand
            token = get_api_token()
            if token:
                file_missing = False
                if league_info['type'] == 'seasonal':
                    for season in SEASONS:
                        local_filename = f"{league_code}_{season}.csv"
                        local_path = os.path.join(DATA_DIR, local_filename)
                        if not os.path.exists(local_path) or os.path.getsize(local_path) <= 250:
                            file_missing = True
                            break
                else:
                    local_filename = f"{league_code}_all.csv"
                    local_path = os.path.join(DATA_DIR, local_filename)
                    if not os.path.exists(local_path) or os.path.getsize(local_path) <= 250:
                        file_missing = True
                
                if file_missing:
                    print(f"[On-Demand Auto-Sync] File for league {league_code} is missing. Triggering sync...")
                    try:
                        sync_single_league_from_api(league_code, force=False)
                    except Exception as e:
                        print(f"Error on-demand syncing {league_code}: {e}")

            league_type = league_info['type']
            league_name = league_info['name']
            
            # Check if league is seasonal
            if league_type == 'seasonal':
                for season in SEASONS:
                    local_filename = f"{league_code}_{season}.csv"
                    local_path = os.path.join(DATA_DIR, local_filename)
                    
                    if os.path.exists(local_path) and os.path.getsize(local_path) > 250:
                        try:
                            df = read_csv_robust(local_path)
                            if len(df) > 0:
                                # Validate that required columns exist
                                required = ['Date', 'HomeTeam', 'AwayTeam']
                                if all(col in df.columns for col in required):
                                    df['Season'] = season
                                    dfs.append(df)
                                else:
                                    print(f"Warning: {local_filename} is missing required columns. Skipping corrupted file.")
                        except Exception as e:
                            print(f"Error loading {local_filename}: {e}")
                            
            # Check if league is aggregate
            elif league_type == 'aggregate':
                local_filename = f"{league_code}_all.csv"
                local_path = os.path.join(DATA_DIR, local_filename)
                
                if os.path.exists(local_path) and os.path.getsize(local_path) > 250:
                    try:
                        df = read_csv_robust(local_path)
                        if len(df) > 0:
                            # Map aggregate columns to seasonal standard columns
                            rename_dict = {
                                'Home': 'HomeTeam',
                                'Away': 'AwayTeam',
                                'HG': 'FTHG',
                                'AG': 'FTAG',
                                'Res': 'FTR',
                                'B365CH': 'B365H',
                                'B365CD': 'B365D',
                                'B365CA': 'B365A',
                                'AvgCH': 'AvgH',
                                'AvgCD': 'AvgD',
                                'AvgCA': 'AvgA',
                                'MaxCH': 'MaxH',
                                'MaxCD': 'MaxD',
                                'MaxCA': 'MaxA'
                            }
                            rename_dict = {k: v for k, v in rename_dict.items() if k in df.columns}
                            df = df.rename(columns=rename_dict)
                            
                            required = ['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'FTR']
                            if all(col in df.columns for col in required):
                                df['Season'] = 'All'
                                dfs.append(df)
                            else:
                                missing = [c for c in required if c not in df.columns]
                                print(f"Warning: {local_filename} is missing required columns {missing}. Skipping corrupted file.")
                    except Exception as e:
                        print(f"Error loading {local_filename}: {e}")
                        
        if not dfs:
            _LEAGUE_DATA_CACHE[league_code] = pd.DataFrame()
        else:
            # Combine all loaded seasons
            combined_df = pd.concat(dfs, ignore_index=True)
            
            # Clean dataframe
            combined_df = combined_df.dropna(subset=['Date', 'HomeTeam', 'AwayTeam'])
            
            # Parse Dates robustly
            combined_df['Date'] = pd.to_datetime(combined_df['Date'], format='mixed', dayfirst=True)
            
            # Sort by date
            combined_df = combined_df.sort_values(by='Date').reset_index(drop=True)
            
            # Standardize names
            combined_df['LeagueCode'] = league_code
            combined_df['LeagueName'] = league_info['name'] if league_info else league_code
            
            _LEAGUE_DATA_CACHE[league_code] = combined_df
            
    cached_df = _LEAGUE_DATA_CACHE[league_code]
    if cached_df.empty:
        return cached_df
        
    # Filter and return a copy to prevent in-place modification of cached dataframe
    return cached_df[cached_df['Date'] >= pd.to_datetime(start_date)].copy()

def sync_fixtures(force=False):
    """Downloads the upcoming fixtures list from football-data.co.uk."""
    ensure_data_dir()
    local_path = os.path.join(DATA_DIR, "fixtures.csv")
    
    # Cache fixtures file for 12 hours
    if not force and os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(local_path))
        if file_age.total_seconds() < 43200:  # 12 hours
            return True
            
    url = "https://www.football-data.co.uk/fixtures.csv"
    return download_file(url, local_path)

# Mapping of DataFootball API league names to internal league codes
API_LEAGUE_MAP = {
    'England Premier League': 'E0',
    'England Championship': 'E1',
    'England EFL League One': 'E2',
    'England EFL League Two': 'E3',
    'Spain La Liga': 'SP1',
    'Spain Segunda División': 'SP2',
    'Italy Serie A': 'I1',
    'Italy Serie B': 'I2',
    'Germany Bundesliga': 'D1',
    'Germany 2. Bundesliga': 'D2',
    'France Ligue 1': 'F1',
    'France Ligue 2': 'F2',
    'Netherlands Eredivisie': 'N1',
    'Belgium Pro League': 'B1',
    'Portugal Liga NOS': 'P1',
    'Turkey Süper Lig': 'T1',
    'Greece Super League': 'G1',
    'Scotland Premiership': 'SC0',
    'Scotland Championship': 'SC1',
    'Argentina Primera División': 'ARG',
    'Brazil Serie A': 'BRA',
    'USA MLS': 'USA',
    'Japan J1 League': 'JPN',
    'Mexico Liga MX': 'MEX'
}

def clean_league_code(league_name):
    """Maps exact DataFootball API names to their internal codes or generates a clean slug."""
    for api_name, code in API_LEAGUE_MAP.items():
        if api_name.lower().strip() == league_name.lower().strip():
            return code
            
    # If not found, generate a dynamic slug code
    import re
    cleaned = re.sub(r'[^a-zA-Z0-9\s\-]', '', league_name)
    cleaned = re.sub(r'[\s\-]+', '_', cleaned)
    return cleaned.upper()

def get_api_leagues():
    """Loads or fetches the list of leagues from the DataFootball API."""
    token = get_api_token()
    if not token:
        return []
        
    config_path = os.path.join(DATA_DIR, 'api_leagues_list.json')
    # Try to load from local file first to be fast
    if os.path.exists(config_path):
        try:
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading api_leagues_list.json: {e}")
            
    # If not exists or error, fetch from API
    try:
        import requests
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get("https://webhook.datafootball.com.br/webhook/leagues", headers=headers, timeout=10)
        if res.status_code == 200:
            leagues = res.json()
            league_names = []
            for l in leagues:
                name = l.get('liga') or l.get('league')
                if name and name not in league_names:
                    league_names.append(name)
            # Save to file
            try:
                import json
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(league_names, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Error saving api_leagues_list.json: {e}")
            return league_names
    except Exception as e:
        print(f"Error fetching leagues from DataFootball API: {e}")
        
    return []

def get_all_available_leagues():
    """Returns a list of all leagues supported by the system."""
    all_leagues = []
    seen_codes = set()
    
    # Static seasonal leagues
    for k, v in LEAGUES_SEASONAL.items():
        api_name = next((api_n for api_n, code in API_LEAGUE_MAP.items() if code == k), v)
        all_leagues.append({'code': k, 'name': v, 'type': 'seasonal', 'api_name': api_name})
        seen_codes.add(k)
        
    # Static aggregate leagues
    for k, v in LEAGUES_AGGREGATE.items():
        api_name = next((api_n for api_n, code in API_LEAGUE_MAP.items() if code == k), v)
        all_leagues.append({'code': k, 'name': v, 'type': 'aggregate', 'api_name': api_name})
        seen_codes.add(k)
        
    # Dynamic leagues from API
    token = get_api_token()
    if token:
        api_leagues = get_api_leagues()
        for api_name in api_leagues:
            code = clean_league_code(api_name)
            if code not in seen_codes:
                all_leagues.append({
                    'code': code,
                    'name': api_name,
                    'type': 'aggregate',
                    'api_name': api_name
                })
                seen_codes.add(code)
                
    return all_leagues

def get_api_token():
    """Loads the DataFootball API bearer token from data/api_config.json."""
    config_path = os.path.join(DATA_DIR, 'api_config.json')
    if os.path.exists(config_path):
        try:
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('token')
        except Exception as e:
            print(f"Error loading API token from config: {e}")
    return None

def load_upcoming_from_api(token):
    """
    Fetches today's matches from the DataFootball API and standardizes them 
    into a pandas DataFrame matching the fixtures format.
    """
    import requests
    import numpy as np
    
    url = "https://webhook.datafootball.com.br/webhook/matches_day"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    print(f"Fetching upcoming matches from DataFootball API: {url}...")
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"DataFootball API returned status code {response.status_code}")
            return pd.DataFrame()
            
        matches = response.json()
        if not isinstance(matches, list):
            print("DataFootball API did not return a list of matches")
            return pd.DataFrame()
            
        mapped_records = []
        for match in matches:
            api_league = match.get('league')
            if not api_league:
                continue
                
            # Lookup league code dynamically
            league_code = clean_league_code(api_league)
                
            # Map odds fields, handle missing or zero values gracefully
            def parse_odd(val):
                try:
                    fval = float(val)
                    return fval if fval > 0 else np.nan
                except (ValueError, TypeError):
                    return np.nan

            def parse_numeric(val):
                try:
                    fval = float(val)
                    return fval if fval >= 0 else np.nan
                except (ValueError, TypeError):
                    return np.nan
                    
            record = {
                'Div': league_code,
                'LeagueName': api_league,
                'HomeTeam': match.get('home_name'),
                'AwayTeam': match.get('away_name'),
                'Date': match.get('date'),
                'Time': match.get('time', '00:00:00'),
                'B365H': parse_odd(match.get('odds_ft_1')),
                'B365D': parse_odd(match.get('odds_ft_x')),
                'B365A': parse_odd(match.get('odds_ft_2')),
                'B365>2.5': parse_odd(match.get('odds_ft_over25')),
                'B365<2.5': parse_odd(match.get('odds_ft_under25')),
                'HST': parse_numeric(match.get('team_a_shotsOnTarget')),
                'AST': parse_numeric(match.get('team_b_shotsOnTarget')),
                'HomeXG': parse_numeric(match.get('team_a_xg_prematch')),
                'AwayXG': parse_numeric(match.get('team_b_xg_prematch'))
            }
            mapped_records.append(record)
            
        if not mapped_records:
            return pd.DataFrame()
            
        df = pd.DataFrame(mapped_records)
        return df
    except Exception as e:
        print(f"Error loading upcoming matches from DataFootball API: {e}")
        return pd.DataFrame()
