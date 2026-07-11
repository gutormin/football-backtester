import os
import urllib.request
import logging
import threading
import pandas as pd
from datetime import datetime
import requests

from .api_utils import retry_with_backoff

logger = logging.getLogger(__name__)

def read_csv_robust(path):
    """Read CSV with automatic encoding detection.

    Tries UTF-8-sig (handles BOM), then UTF-8, then Latin1.
    Only logs warnings for genuine encoding issues, not other parse errors.
    """
    for encoding in ('utf-8-sig', 'utf-8', 'latin1'):
        try:
            df = pd.read_csv(path, encoding=encoding)
            return translate_custom_csv(df)
        except UnicodeDecodeError:
            continue  # Try next encoding
        except Exception:
            # Not an encoding error — try next encoding anyway, but don't warn yet
            continue
    # Last resort: try with on_bad_lines='skip' for files with a few malformed rows
    try:
        df = pd.read_csv(path, encoding='latin1', on_bad_lines='skip')
        logger.warning(f"Fallback forçado Latin1 + skip bad lines para {os.path.basename(path)}")
        return translate_custom_csv(df)
    except Exception:
        pass
    # Absolute last resort
    try:
        df = pd.read_csv(path, encoding='latin1')
        logger.warning(f"Fallback forçado Latin1 para {os.path.basename(path)}")
        return translate_custom_csv(df)
    except Exception as e:
        logger.error(f"Nao foi possivel ler CSV {os.path.basename(path)}: {e}")
        raise

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
        
        # Calculate FTR (Full Time Result) if missing (Vectorized using np.select)
        if 'FTR' not in df.columns and 'FTHG' in df.columns and 'FTAG' in df.columns:
            import numpy as np
            fthg = pd.to_numeric(df['FTHG'], errors='coerce')
            ftag = pd.to_numeric(df['FTAG'], errors='coerce')
            conditions = [
                fthg.isna() | ftag.isna(),
                fthg > ftag,
                fthg < ftag
            ]
            choices = [None, 'H', 'A']
            df['FTR'] = np.select(conditions, choices, default='D')
            
        # Optional: Map over/under odds if they exist in the spreadsheet
        # e.g., 'Odd Over 2.5' -> 'B365>2.5', 'Odd Under 2.5' -> 'B365<2.5'
        if 'Odd Over 2.5' in df.columns: df.rename(columns={'Odd Over 2.5': 'B365>2.5'}, inplace=True)
        if 'Odd Under 2.5' in df.columns: df.rename(columns={'Odd Under 2.5': 'B365<2.5'}, inplace=True)
        
        # Map additional odds columns from spreadsheet format
        # Double Chance
        if 'odds_doublechance_1x' in df.columns: df.rename(columns={'odds_doublechance_1x': 'DC_1X'}, inplace=True)
        if 'odds_doublechance_12' in df.columns: df.rename(columns={'odds_doublechance_12': 'DC_12'}, inplace=True)
        if 'odds_doublechance_x2' in df.columns: df.rename(columns={'odds_doublechance_x2': 'DC_X2'}, inplace=True)
        
        # Draw No Bet
        if 'odds_dnb_1' in df.columns: df.rename(columns={'odds_dnb_1': 'DNB_1'}, inplace=True)
        if 'odds_dnb_2' in df.columns: df.rename(columns={'odds_dnb_2': 'DNB_2'}, inplace=True)
        
        # HT Result
        if 'odds_1st_half_result_1' in df.columns: df.rename(columns={'odds_1st_half_result_1': 'Odd_1_HT'}, inplace=True)
        if 'odds_1st_half_result_x' in df.columns: df.rename(columns={'odds_1st_half_result_x': 'Odd_X_HT'}, inplace=True)
        if 'odds_1st_half_result_2' in df.columns: df.rename(columns={'odds_1st_half_result_2': 'Odd_2_HT'}, inplace=True)
        
        # BTTS
        if 'BTTS Sim' in df.columns: df.rename(columns={'BTTS Sim': 'BTTS_Yes'}, inplace=True)
        if 'BTTS Não' in df.columns: df.rename(columns={'BTTS Não': 'BTTS_No'}, inplace=True)
        if 'odds_btts_yes' in df.columns: df.rename(columns={'odds_btts_yes': 'BTTS_Yes'}, inplace=True)
        if 'odds_btts_no' in df.columns: df.rename(columns={'odds_btts_no': 'BTTS_No'}, inplace=True)
        
        # Over/Under FT Goals
        if 'Over 0.5' in df.columns: df.rename(columns={'Over 0.5': 'Over_FT_0_5'}, inplace=True)
        if 'Under 0.5' in df.columns: df.rename(columns={'Under 0.5': 'Under_FT_0_5'}, inplace=True)
        if 'odds_ft_over05' in df.columns: df.rename(columns={'odds_ft_over05': 'Over_FT_0_5'}, inplace=True)
        if 'odds_ft_under05' in df.columns: df.rename(columns={'odds_ft_under05': 'Under_FT_0_5'}, inplace=True)
        if 'Over 1.5' in df.columns: df.rename(columns={'Over 1.5': 'Over_FT_1_5'}, inplace=True)
        if 'Under 1.5' in df.columns: df.rename(columns={'Under 1.5': 'Under_FT_1_5'}, inplace=True)
        if 'Over 3.5' in df.columns: df.rename(columns={'Over 3.5': 'Over_FT_3_5'}, inplace=True)
        if 'Under 3.5' in df.columns: df.rename(columns={'Under 3.5': 'Under_FT_3_5'}, inplace=True)
        if 'Over 4.5' in df.columns: df.rename(columns={'Over 4.5': 'Over_FT_4_5'}, inplace=True)
        if 'Under 4.5' in df.columns: df.rename(columns={'Under 4.5': 'Under_FT_4_5'}, inplace=True)
        
        # Win to Nil
        if 'odds_win_to_nil_1' in df.columns: df.rename(columns={'odds_win_to_nil_1': 'odds_win_to_nil_1'}, inplace=True)
        if 'odds_win_to_nil_2' in df.columns: df.rename(columns={'odds_win_to_nil_2': 'odds_win_to_nil_2'}, inplace=True)
        
        # Corners Over/Under
        for line in ['75', '85', '95', '105', '115']:
            col_over = f'odds_corners_over_{line}'
            col_under = f'odds_corners_under_{line}'
            if col_over in df.columns: df.rename(columns={col_over: col_over}, inplace=True)
            if col_under in df.columns: df.rename(columns={col_under: col_under}, inplace=True)
            
        # Corners 1X2
        if 'odds_corners_1' in df.columns: df.rename(columns={'odds_corners_1': 'odds_corners_1'}, inplace=True)
        if 'odds_corners_x' in df.columns: df.rename(columns={'odds_corners_x': 'odds_corners_x'}, inplace=True)
        if 'odds_corners_2' in df.columns: df.rename(columns={'odds_corners_2': 'odds_corners_2'}, inplace=True)
        
        # HT Over/Under Goals
        if 'odds_1st_half_over05' in df.columns: df.rename(columns={'odds_1st_half_over05': 'Over_HT_0_5'}, inplace=True)
        if 'odds_1st_half_under05' in df.columns: df.rename(columns={'odds_1st_half_under05': 'Under_HT_0_5'}, inplace=True)
        if 'odds_1st_half_over15' in df.columns: df.rename(columns={'odds_1st_half_over15': 'Over_HT_1_5'}, inplace=True)
        if 'odds_1st_half_under15' in df.columns: df.rename(columns={'odds_1st_half_under15': 'Under_HT_1_5'}, inplace=True)
        if 'odds_1st_half_over25' in df.columns: df.rename(columns={'odds_1st_half_over25': 'Over_HT_2_5'}, inplace=True)
        if 'odds_1st_half_under25' in df.columns: df.rename(columns={'odds_1st_half_under25': 'Under_HT_2_5'}, inplace=True)
        if 'odds_1st_half_over35' in df.columns: df.rename(columns={'odds_1st_half_over35': 'Over_HT_3_5'}, inplace=True)
        if 'odds_1st_half_under35' in df.columns: df.rename(columns={'odds_1st_half_under35': 'Under_HT_3_5'}, inplace=True)
        
        # 2H Over/Under Goals
        for line in ['05', '15', '25', '35']:
            col_over = f'odds_2nd_half_over{line}'
            col_under = f'odds_2nd_half_under{line}'
            if col_over in df.columns: df.rename(columns={col_over: f'Over_2H_{line[0]}_{line[1]}'}, inplace=True)
            if col_under in df.columns: df.rename(columns={col_under: f'Under_2H_{line[0]}_{line[1]}'}, inplace=True)
            
        # 2nd Half Result
        if 'odds_2nd_half_result_1' in df.columns: df.rename(columns={'odds_2nd_half_result_1': 'Odd_1_2H'}, inplace=True)
        if 'odds_2nd_half_result_x' in df.columns: df.rename(columns={'odds_2nd_half_result_x': 'Odd_X_2H'}, inplace=True)
        if 'odds_2nd_half_result_2' in df.columns: df.rename(columns={'odds_2nd_half_result_2': 'Odd_2_2H'}, inplace=True)
        
        # HTHG / HTAG (HT Goals)
        if 'Gols HT Casa' in df.columns: df.rename(columns={'Gols HT Casa': 'HTHG'}, inplace=True)
        if 'Gols HT Fora' in df.columns: df.rename(columns={'Gols HT Fora': 'HTAG'}, inplace=True)
        if 'ht_goals_team_a' in df.columns: df.rename(columns={'ht_goals_team_a': 'HTHG'}, inplace=True)
        if 'ht_goals_team_b' in df.columns: df.rename(columns={'ht_goals_team_b': 'HTAG'}, inplace=True)
            
        # Filter incomplete matches for history, but keep them if we need them for upcoming
        # However, data_loader.py is usually for history, so we only need rows with FTR
        # We won't drop them here, we let the logic below handle NaNs
        
    return df

# In-memory cache for loaded league dataframes
_LEAGUE_DATA_CACHE = {}
_cache_lock = threading.Lock()

def clear_league_data_cache():
    global _LEAGUE_DATA_CACHE
    with _cache_lock:
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
    'JPN': 'Japan J-League',
    'SWEDEN_ALLSVENSKAN': 'Sweden Allsvenskan',
    'NORWAY_ELITESERIEN': 'Norway Eliteserien'
}

SEASONS = ['2021', '2122', '2223', '2324', '2425', '2526']

# Leagues that use FutPythonTrader API instead of football-data.co.uk CSVs
SOUTH_AMERICAN_LEAGUES = {'ARG', 'BRA', 'MEX', 'USA'}

def auto_detect_data_source(league_code):
    """Returns the appropriate data source for a league code."""
    if '/' in league_code:
        return 'futpython'  # pais/liga format from FutPythonTrader
    if league_code in SOUTH_AMERICAN_LEAGUES:
        return 'futpython'
    return 'footballdata'


def startup_data_quality_check():
    """
    Lightweight data quality check at application startup.
    Scans data/ CSV files and logs warnings for leagues with >10% missing data
    in key columns (odds 1X2, match results).
    Also reports encoding status of all CSV files.
    """
    import glob
    issues_found = 0
    encoding_issues = 0

    for csv_path in glob.glob(os.path.join(DATA_DIR, '*.csv')):
        fname = os.path.basename(csv_path)
        if fname in ('fixtures.csv', 'telegram_tips_sent.json',
                      'telegram_arbitrage_tips_sent.json', 'telegram_dutching_tips_sent.json'):
            continue

        # Encoding check: verify file is readable as UTF-8
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                f.read(1024)
        except UnicodeDecodeError:
            encoding_issues += 1
            try:
                with open(csv_path, 'r', encoding='latin1') as f:
                    content = f.read()
                # Convert to UTF-8 in-place
                with open(csv_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info(f"data_quality: {fname} convertido de Latin1 para UTF-8")
            except Exception as e:
                logger.warning(f"data_quality: {fname} encoding problemático: {e}")

        # Column completeness check
        try:
            df = read_csv_robust(csv_path)
        except Exception:
            logger.warning(f"data_quality: não foi possível ler {fname}")
            continue

        if df.empty or 'Date' not in df.columns:
            continue

        total = len(df)

        # Check core odds columns
        for col in ['B365H', 'B365D', 'B365A', 'FTHG', 'FTAG']:
            if col in df.columns:
                missing_pct = df[col].isna().mean() * 100
                if missing_pct > 10:
                    logger.warning(
                        f"data_quality: {fname} — {col} com {missing_pct:.1f}% ausentes "
                        f"({total} linhas)"
                    )
                    issues_found += 1

    if issues_found or encoding_issues:
        if encoding_issues:
            logger.info(f"data_quality: {encoding_issues} arquivos convertidos de Latin1 para UTF-8")
        if issues_found:
            logger.warning(f"data_quality: {issues_found} problemas de completude encontrados nos CSVs")
    else:
        logger.info("data_quality: verificação de CSVs concluída sem problemas críticos")

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def download_file(url, local_path):
    """Downloads a file setting a User-Agent to bypass Cloudflare/503 limits."""
    logger.info(f"Downloading {url} to {local_path}...")
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as response, open(local_path, 'wb') as out_file:
            out_file.write(response.read())
        return True
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}", exc_info=True)
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
    @retry_with_backoff(max_retries=2, base_delay=1.0)
    def _get_seasons():
        return requests.get(f"{base_api_url}/seasons", headers=headers, timeout=15)

    try:
        res_seasons = _get_seasons()
        if res_seasons.status_code != 200:
            return False
        seasons_list = res_seasons.json()
        
        api_league_name = league_info.get('api_name')
        if not api_league_name:
            return False
        
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
                @retry_with_backoff(max_retries=2, base_delay=1.0)
                def _get_matches():
                    return requests.get(f"{base_api_url}/matches", headers=headers, params=params, timeout=20)
                res = _get_matches()
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
                        'HTHG': parse_numeric(m.get('ht_goals_team_a')),
                        'HTAG': parse_numeric(m.get('ht_goals_team_b')),
                        'B365H': parse_odd(m.get('odds_ft_1')),
                        'B365D': parse_odd(m.get('odds_ft_x')),
                        'B365A': parse_odd(m.get('odds_ft_2')),
                        'B365>2.5': parse_odd(m.get('odds_ft_over25')),
                        'B365<2.5': parse_odd(m.get('odds_ft_under25')),
                        'HST': parse_numeric(m.get('team_a_shotsOnTarget')),
                        'AST': parse_numeric(m.get('team_b_shotsOnTarget')),
                        'HC': parse_numeric(m.get('team_a_corners')),
                        'AC': parse_numeric(m.get('team_b_corners')),
                        'HomeXG': parse_numeric(m.get('team_a_xg') or m.get('team_a_xg_prematch')),
                        'AwayXG': parse_numeric(m.get('team_b_xg') or m.get('team_b_xg_prematch')),
                        'Odd_1_HT': parse_odd(m.get('odds_1st_half_result_1')),
                        'Odd_X_HT': parse_odd(m.get('odds_1st_half_result_x')),
                        'Odd_2_HT': parse_odd(m.get('odds_1st_half_result_2')),
                        'BTTS_Yes': parse_odd(m.get('odds_btts_yes') or m.get('BTTS Sim')),
                        'BTTS_No': parse_odd(m.get('odds_btts_no') or m.get('BTTS Não')),
                        'Over_FT_0_5': parse_odd(m.get('odds_ft_over05') or m.get('Over 0.5')),
                        'Under_FT_0_5': parse_odd(m.get('odds_ft_under05') or m.get('Under 0.5')),
                        'Over_FT_1_5': parse_odd(m.get('odds_ft_over15') or m.get('Over 1.5')),
                        'Under_FT_1_5': parse_odd(m.get('odds_ft_under15') or m.get('Under 1.5')),
                        'Over_FT_3_5': parse_odd(m.get('odds_ft_over35') or m.get('Over 3.5')),
                        'Under_FT_3_5': parse_odd(m.get('odds_ft_under35') or m.get('Under 3.5')),
                        'Over_FT_4_5': parse_odd(m.get('odds_ft_over45') or m.get('Over 4.5')),
                        'Under_FT_4_5': parse_odd(m.get('odds_ft_under45') or m.get('Under 4.5')),
                        'DC_1X': parse_odd(m.get('odds_doublechance_1x')),
                        'DC_12': parse_odd(m.get('odds_doublechance_12')),
                        'DC_X2': parse_odd(m.get('odds_doublechance_x2')),
                        'DNB_1': parse_odd(m.get('odds_dnb_1')),
                        'DNB_2': parse_odd(m.get('odds_dnb_2')),
                        'Over_HT_0_5': parse_odd(m.get('odds_1st_half_over05')),
                        'Under_HT_0_5': parse_odd(m.get('odds_1st_half_under05')),
                        'Over_HT_1_5': parse_odd(m.get('odds_1st_half_over15')),
                        'Under_HT_1_5': parse_odd(m.get('odds_1st_half_under15')),
                        'Over_HT_2_5': parse_odd(m.get('odds_1st_half_over25')),
                        'Under_HT_2_5': parse_odd(m.get('odds_1st_half_under25')),
                        'Over_HT_3_5': parse_odd(m.get('odds_1st_half_over35')),
                        'Under_HT_3_5': parse_odd(m.get('odds_1st_half_under35')),
                        'Over_2H_0_5': parse_odd(m.get('odds_2nd_half_over05')),
                        'Under_2H_0_5': parse_odd(m.get('odds_2nd_half_under05')),
                        'Over_2H_1_5': parse_odd(m.get('odds_2nd_half_over15')),
                        'Under_2H_1_5': parse_odd(m.get('odds_2nd_half_under15')),
                        'Over_2H_2_5': parse_odd(m.get('odds_2nd_half_over25')),
                        'Under_2H_2_5': parse_odd(m.get('odds_2nd_half_under25')),
                        'Over_2H_3_5': parse_odd(m.get('odds_2nd_half_over35')),
                        'Under_2H_3_5': parse_odd(m.get('odds_2nd_half_under35')),
                        'Odd_1_2H': parse_odd(m.get('odds_2nd_half_result_1')),
                        'Odd_X_2H': parse_odd(m.get('odds_2nd_half_result_x')),
                        'Odd_2_2H': parse_odd(m.get('odds_2nd_half_result_2')),
                        'odds_win_to_nil_1': parse_odd(m.get('odds_win_to_nil_1')),
                        'odds_win_to_nil_2': parse_odd(m.get('odds_win_to_nil_2')),
                        'odds_corners_over_75': parse_odd(m.get('odds_corners_over_75')),
                        'odds_corners_over_85': parse_odd(m.get('odds_corners_over_85')),
                        'odds_corners_over_95': parse_odd(m.get('odds_corners_over_95')),
                        'odds_corners_over_105': parse_odd(m.get('odds_corners_over_105')),
                        'odds_corners_over_115': parse_odd(m.get('odds_corners_over_115')),
                        'odds_corners_under_75': parse_odd(m.get('odds_corners_under_75')),
                        'odds_corners_under_85': parse_odd(m.get('odds_corners_under_85')),
                        'odds_corners_under_95': parse_odd(m.get('odds_corners_under_95')),
                        'odds_corners_under_105': parse_odd(m.get('odds_corners_under_105')),
                        'odds_corners_under_115': parse_odd(m.get('odds_corners_under_115')),
                        'odds_corners_1': parse_odd(m.get('odds_corners_1')),
                        'odds_corners_x': parse_odd(m.get('odds_corners_x')),
                        'odds_corners_2': parse_odd(m.get('odds_corners_2'))
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
                    logger.info(f"[On-Demand Sync] Saved seasonal {local_filename}")
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
                logger.info(f"[On-Demand Sync] Saved aggregate {local_filename}")
            else:
                if not os.path.exists(local_path) or os.path.getsize(local_path) <= 250:
                    with open(local_path, 'w', encoding='utf-8') as f:
                        f.write("Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n")
                    logger.info(f"[On-Demand Sync] Created placeholder for empty aggregate {local_filename}")
        return True
    except Exception as e:
        logger.error(f"Error syncing league {league_code} on-demand: {e}", exc_info=True)
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
            logger.error(f"Error syncing league {l['code']}: {e}", exc_info=True)

def load_league_data(league_code, start_date='2021-01-01', data_source="footballdata", api_key=""):
    """Loads and standardizes data for a given league starting from a specific date."""
    if data_source == "futpython":
        # Translate Football-Data codes to FutPythonTrader slugs if necessary
        translation_map = {
            'E0': 'england/premier-league',
            'E1': 'england/championship',
            'E2': 'england/league-one',
            'E3': 'england/league-two',
            'SP1': 'spain/laliga',
            'SP2': 'spain/laliga2',
            'I1': 'italy/serie-a',
            'I2': 'italy/serie-b',
            'D1': 'germany/bundesliga',
            'D2': 'germany/2-bundesliga',
            'F1': 'france/ligue-1',
            'F2': 'france/ligue-2',
            'N1': 'netherlands/eredivisie',
            'B1': 'belgium/pro-league',
            'P1': 'portugal/primeira-liga',
            'T1': 'turkey/super-lig',
            'G1': 'greece/super-league',
            'SC0': 'scotland/premiership',
            'SC1': 'scotland/championship',
            'BRA': 'brazil/serie-a-betano',
            'USA': 'usa/mls',
            'ARG': 'argentina/torneo-betano',
            'MEX': 'mexico/liga-mx',
            'JPN': 'japan/j1-league',
            'SWEDEN_ALLSVENSKAN': 'sweden/allsvenskan',
            'NORWAY_ELITESERIEN': 'norway/eliteserien'
        }
        if league_code in translation_map:
            league_code = translation_map[league_code]
            
        if not api_key:
            api_key = get_futpython_api_key()
        return fetch_futpython_data(league_code, start_date, api_key)
        
    global _LEAGUE_DATA_CACHE

    with _cache_lock:
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
                        logger.info(f"[On-Demand Auto-Sync] File for league {league_code} is missing. Triggering sync...")
                        try:
                            sync_single_league_from_api(league_code, force=False)
                        except Exception as e:
                            logger.error(f"Error on-demand syncing {league_code}: {e}", exc_info=True)

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
                                        logger.warning(f"{local_filename} is missing required columns. Skipping corrupted file.")
                            except Exception as e:
                                logger.error(f"Error loading {local_filename}: {e}", exc_info=True)

                # Check if league is aggregate
                elif league_type == 'aggregate':
                    local_filename = f"{league_code}_all.csv"
                    local_path = os.path.join(DATA_DIR, local_filename)
                    # Fallback: use original filename from disk scan if code-based name doesn't exist
                    if not os.path.exists(local_path):
                        orig_fn = league_info.get('original_filename')
                        if orig_fn:
                            local_path = os.path.join(DATA_DIR, orig_fn)

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
                                    logger.warning(f"{local_filename} is missing required columns {missing}. Skipping corrupted file.")
                        except Exception as e:
                            logger.error(f"Error loading {local_filename}: {e}", exc_info=True)

            if not dfs:
                # Don't cache empty DataFrames — allows retry on next request
                # (files may have been repaired, sync may have completed, etc.)
                pass
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

        cached_df = _LEAGUE_DATA_CACHE.get(league_code)
    if cached_df is None or cached_df.empty:
        return pd.DataFrame()
        
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
    'Mexico Liga MX': 'MEX',
    'Sweden Allsvenskan': 'SWEDEN_ALLSVENSKAN',
    'Norway Eliteserien': 'NORWAY_ELITESERIEN'
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
        code_raw = filename.replace('_all.csv', '')
        if code_raw != code_raw.upper():
            continue
        original_filename = filename
        code = code_raw
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
            logger.error(f"Error loading api_leagues_list.json: {e}", exc_info=True)
            
    # If not exists or error, fetch from API
    try:
        headers = {"Authorization": f"Bearer {token}"}

        @retry_with_backoff(max_retries=2, base_delay=1.0)
        def _get_leagues():
            return requests.get("https://webhook.datafootball.com.br/webhook/leagues", headers=headers, timeout=10)

        res = _get_leagues()
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
                logger.error(f"Error saving api_leagues_list.json: {e}", exc_info=True)
            return league_names
    except Exception as e:
        logger.error(f"Error fetching leagues from DataFootball API: {e}", exc_info=True)
        
    return []

def get_all_available_leagues(source="footballdata"):
    """Returns a list of all leagues supported by the system."""
    if source == "futpython":
        return get_futpython_leagues()
        
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

    # Scan disk for additional aggregate CSV files (works even without API token)
    for league in _scan_disk_for_aggregate_leagues():
        if league['code'] not in seen_codes:
            all_leagues.append(league)
            seen_codes.add(league['code'])

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
            logger.error(f"Error loading API token from config: {e}", exc_info=True)
    return None

def get_futpython_api_key():
    """Loads the FutPythonTrader API key from data/futpython_config.json, falling back to default."""
    config_path = os.path.join(DATA_DIR, 'futpython_config.json')
    if os.path.exists(config_path):
        try:
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                key = config.get('api_key')
                if key and key.strip():
                    return key.strip()
        except Exception as e:
            logger.error(f"Error loading FutPythonTrader API key: {e}", exc_info=True)
    return os.getenv('FUTPYTHON_API_KEY', 'cmqa6oz0p01i1wq6lzxknltmd')

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
    
    logger.info(f"Fetching upcoming matches from DataFootball API: {url}...")
    try:
        @retry_with_backoff(max_retries=2, base_delay=1.0)
        def _get_upcoming():
            return requests.get(url, headers=headers, timeout=15)
        response = _get_upcoming()
        if response.status_code != 200:
            logger.error(f"DataFootball API returned status code {response.status_code}")
            return pd.DataFrame()
            
        matches = response.json()
        if not isinstance(matches, list):
            logger.error("DataFootball API did not return a list of matches")
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
                'HC': parse_numeric(match.get('team_a_corners')),
                'AC': parse_numeric(match.get('team_b_corners')),
                'HomeXG': parse_numeric(match.get('team_a_xg_prematch')),
                'AwayXG': parse_numeric(match.get('team_b_xg_prematch')),
                'Odd_1_HT': parse_odd(match.get('odds_1st_half_result_1')),
                'Odd_X_HT': parse_odd(match.get('odds_1st_half_result_x')),
                'Odd_2_HT': parse_odd(match.get('odds_1st_half_result_2')),
                'BTTS_Yes': parse_odd(match.get('odds_btts_yes') or match.get('BTTS Sim')),
                'BTTS_No': parse_odd(match.get('odds_btts_no') or match.get('BTTS Não')),
                'Over_FT_0_5': parse_odd(match.get('odds_ft_over05') or match.get('Over 0.5')),
                'Under_FT_0_5': parse_odd(match.get('odds_ft_under05') or match.get('Under 0.5')),
                'Over_FT_1_5': parse_odd(match.get('odds_ft_over15') or match.get('Over 1.5')),
                'Under_FT_1_5': parse_odd(match.get('odds_ft_under15') or match.get('Under 1.5')),
                'Over_FT_3_5': parse_odd(match.get('odds_ft_over35') or match.get('Over 3.5')),
                'Under_FT_3_5': parse_odd(match.get('odds_ft_under35') or match.get('Under 3.5')),
                'Over_FT_4_5': parse_odd(match.get('odds_ft_over45') or match.get('Over 4.5')),
                'Under_FT_4_5': parse_odd(match.get('odds_ft_under45') or match.get('Under 4.5')),
                'DC_1X': parse_odd(match.get('odds_doublechance_1x')),
                'DC_12': parse_odd(match.get('odds_doublechance_12')),
                'DC_X2': parse_odd(match.get('odds_doublechance_x2')),
                'DNB_1': parse_odd(match.get('odds_dnb_1')),
                'DNB_2': parse_odd(match.get('odds_dnb_2')),
                'Over_HT_0_5': parse_odd(match.get('odds_1st_half_over05')),
                'Under_HT_0_5': parse_odd(match.get('odds_1st_half_under05')),
                'Over_HT_1_5': parse_odd(match.get('odds_1st_half_over15')),
                'Under_HT_1_5': parse_odd(match.get('odds_1st_half_under15')),
                'Over_HT_2_5': parse_odd(match.get('odds_1st_half_over25')),
                'Under_HT_2_5': parse_odd(match.get('odds_1st_half_under25')),
                'Over_HT_3_5': parse_odd(match.get('odds_1st_half_over35')),
                'Under_HT_3_5': parse_odd(match.get('odds_1st_half_under35')),
                'Over_2H_0_5': parse_odd(match.get('odds_2nd_half_over05')),
                'Under_2H_0_5': parse_odd(match.get('odds_2nd_half_under05')),
                'Over_2H_1_5': parse_odd(match.get('odds_2nd_half_over15')),
                'Under_2H_1_5': parse_odd(match.get('odds_2nd_half_under15')),
                'Over_2H_2_5': parse_odd(match.get('odds_2nd_half_over25')),
                'Under_2H_2_5': parse_odd(match.get('odds_2nd_half_under25')),
                'Over_2H_3_5': parse_odd(match.get('odds_2nd_half_over35')),
                'Under_2H_3_5': parse_odd(match.get('odds_2nd_half_under35')),
                'Odd_1_2H': parse_odd(match.get('odds_2nd_half_result_1')),
                'Odd_X_2H': parse_odd(match.get('odds_2nd_half_result_x')),
                'Odd_2_2H': parse_odd(match.get('odds_2nd_half_result_2')),
                'odds_win_to_nil_1': parse_odd(match.get('odds_win_to_nil_1')),
                'odds_win_to_nil_2': parse_odd(match.get('odds_win_to_nil_2')),
                'odds_corners_over_75': parse_odd(match.get('odds_corners_over_75')),
                'odds_corners_over_85': parse_odd(match.get('odds_corners_over_85')),
                'odds_corners_over_95': parse_odd(match.get('odds_corners_over_95')),
                'odds_corners_over_105': parse_odd(match.get('odds_corners_over_105')),
                'odds_corners_over_115': parse_odd(match.get('odds_corners_over_115')),
                'odds_corners_under_75': parse_odd(match.get('odds_corners_under_75')),
                'odds_corners_under_85': parse_odd(match.get('odds_corners_under_85')),
                'odds_corners_under_95': parse_odd(match.get('odds_corners_under_95')),
                'odds_corners_under_105': parse_odd(match.get('odds_corners_under_105')),
                'odds_corners_under_115': parse_odd(match.get('odds_corners_under_115')),
                'odds_corners_1': parse_odd(match.get('odds_corners_1')),
                'odds_corners_x': parse_odd(match.get('odds_corners_x')),
                'odds_corners_2': parse_odd(match.get('odds_corners_2'))
            }
            mapped_records.append(record)
            
        if not mapped_records:
            return pd.DataFrame()
            
        df = pd.DataFrame(mapped_records)
        return df
    except Exception as e:
        logger.error(f"Error loading upcoming matches from DataFootball API: {e}", exc_info=True)
        return pd.DataFrame()

def get_futpython_leagues():
    """Loads custom leagues for FutPythonTrader from local json."""
    import json
    config_path = os.path.join(DATA_DIR, 'futpython_leagues.json')
    if not os.path.exists(config_path):
        return []
    
    leagues_list = []
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
            for pais, ligas in mapping.items():
                for liga in ligas:
                    code = f"{pais}/{liga}"
                    leagues_list.append({
                        'code': code,
                        'name': f"{pais.capitalize()} - {liga.capitalize().replace('-', ' ')}",
                        'type': 'futpython',
                        'api_name': code
                    })
    except Exception as e:
        logger.error(f"Error loading futpython leagues: {e}", exc_info=True)
    return leagues_list

def fetch_futpython_data(league_code, start_date, api_key):
    """Fetches CSV data from FutPythonTrader and converts it to pandas DataFrame."""
    import requests
    import io
    import pandas as pd
    
    # Check if league code has pais/liga format
    if "/" not in league_code:
        return pd.DataFrame()
        
    parts = league_code.split("/")
    pais = parts[0]
    liga = "/".join(parts[1:])
    
    temporadas = [
        # Single-year (South American leagues: Brazil, Argentina, Colombia, Chile, etc.)
        "2025", "2024", "2023", "2022", "2021", "2020",
        # Biannual (European/Asian leagues)
        "2025-2026", "2024-2025", "2023-2024", "2022-2023", "2021-2022",
    ]
    base_url = "https://futpythontrader.com.br/api/download"
    status_codes = {}
    dataframes = []
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def download_season(temp):
        url = f"{base_url}/{pais}/{liga}/{temp}?api_key={api_key}"
        import os
        proxy_url = os.environ.get("FUTPYTHON_PROXY")
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        
        # Local cache path inside the data directory
        cache_filename = f"futpython_{pais}_{liga.replace('/', '_')}_{temp}.csv"
        cache_path = os.path.join(DATA_DIR, cache_filename)
        
        # Bypasses: 
        # 1. On Render (API is blocked/unreachable): load cache immediately to avoid timeout delay.
        # 2. Past seasons (completed/fixed data): load cache immediately to speed up local backtests.
        is_current_season = temp in ["2025-2026", "2026", "2026-2027"]
        on_render = os.environ.get("RENDER") is not None
        
        if (on_render or not is_current_season) and os.path.exists(cache_path) and os.path.getsize(cache_path) > 250:
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_text = f.read()
                return temp, 200, cached_text
            except Exception:
                pass
                
        try:
            @retry_with_backoff(max_retries=2, base_delay=1.0)
            def _get_futpython():
                return requests.get(url, timeout=12, proxies=proxies)
            res = _get_futpython()
            if res.status_code == 200 and not res.text.strip().startswith("{"):
                # Write to local cache
                try:
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        f.write(res.text)
                except Exception as cache_err:
                    logger.error(f"Error caching {cache_filename}: {cache_err}", exc_info=True)
                return temp, res.status_code, res.text
            else:
                # If status code is not 200 or there is a JSON error, fall back to cache if available
                if os.path.exists(cache_path) and os.path.getsize(cache_path) > 250:
                    try:
                        with open(cache_path, 'r', encoding='utf-8') as f:
                            cached_text = f.read()
                        logger.info(f"Using cached file for {cache_filename} due to API response status {res.status_code}")
                        return temp, 200, cached_text
                    except Exception as cache_err:
                        logger.error(f"Error reading cache {cache_filename}: {cache_err}", exc_info=True)
                return temp, res.status_code, res.text
        except Exception as e:
            # If exception (network connection error/timeout), fall back to cache if available
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 250:
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        cached_text = f.read()
                    logger.warning(f"Using cached file for {cache_filename} due to connection error: {e}")
                    return temp, 200, cached_text
                except Exception as cache_err:
                    logger.error(f"Error reading cache {cache_filename}: {cache_err}", exc_info=True)
            return temp, None, str(e)
            
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(download_season, temp): temp for temp in temporadas}
        for future in as_completed(futures):
            temp, status_code, response_text = future.result()
            if status_code is not None:
                status_codes[temp] = status_code
                if status_code == 200:
                    if response_text.strip().startswith("{"):
                        continue # JSON error like Dataset não encontrado
                    try:
                        df = pd.read_csv(io.StringIO(response_text))
                        
                        # Check and fix swapped HT odds columns (dataset-specific errors in FutPythonTrader)
                        for line in ['0_5', '1_5', '2_5']:
                            over_col = f'Over_HT_{line}'
                            under_col = f'Under_HT_{line}'
                            if over_col in df.columns and under_col in df.columns:
                                # Convert to numeric to ensure correct comparison (some columns might load as object type due to commas)
                                df[over_col] = pd.to_numeric(df[over_col].astype(str).str.replace(',', '.'), errors='coerce')
                                df[under_col] = pd.to_numeric(df[under_col].astype(str).str.replace(',', '.'), errors='coerce')
                                
                                valid_odds = df[(df[over_col] > 1.0) & (df[under_col] > 1.0)]
                                if len(valid_odds) > 0:
                                    if line == '0_5':
                                        swapped_count = len(valid_odds[valid_odds[over_col] > valid_odds[under_col]])
                                    else:
                                        swapped_count = len(valid_odds[valid_odds[under_col] > valid_odds[over_col]])
                                    
                                    if swapped_count > len(valid_odds) * 0.5:
                                        # Swap values of the columns
                                        temp_over = df[over_col].copy()
                                        df[over_col] = df[under_col]
                                        df[under_col] = temp_over
                                        
                        # Rename columns to match standard backtester format
                        df = df.rename(columns={
                            'Home': 'HomeTeam',
                            'Away': 'AwayTeam',
                            'Home_Score': 'FTHG',
                            'Away_Score': 'FTAG',
                            'Odd_1_FT': 'B365H',
                            'Odd_X_FT': 'B365D',
                            'Odd_2_FT': 'B365A',
                            'Over_FT_2_5': 'B365>2.5',
                            'Under_FT_2_5': 'B365<2.5',
                            'Over_HT_0_5': 'B365>0.5HT',
                            'Under_HT_0_5': 'B365<0.5HT',
                            'Over_HT_1_5': 'B365>1.5HT',
                            'Under_HT_1_5': 'B365<1.5HT',
                            'Over_HT_2_5': 'B365>2.5HT',
                            'Under_HT_2_5': 'B365<2.5HT',
                            'Shots_On_Target_Home_FT': 'HST',
                            'Shots_On_Target_Away_FT': 'AST',
                            'xG_Home_FT': 'HomeXG',
                            'xG_Away_FT': 'AwayXG'
                        })
                        
                        # Fix comma-separated decimals for all numeric columns in FutPythonTrader
                        for col in df.columns:
                            if col not in ['HomeTeam', 'AwayTeam', 'League', 'Date', 'Time']:
                                if df[col].dtype == 'object':
                                    df[col] = df[col].astype(str).str.replace(',', '.')
                                    df[col] = pd.to_numeric(df[col], errors='coerce')
                                    
                        # Validate and correct Double Chance odds (corrupted or missing)
                        dc_cols = ['DC_1X', 'DC_X2', 'DC_12']
                        one_x_two = ['B365H', 'B365D', 'B365A']
                        
                        # Make sure 1X2 and DC columns are clean float types
                        for col in dc_cols + one_x_two:
                            if col in df.columns:
                                df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '.'), errors='coerce')
                        
                        if all(col in df.columns for col in one_x_two):
                            # Calculate unnormalized synthetic odds as fallback
                            h_prob = 1.0 / df['B365H']
                            d_prob = 1.0 / df['B365D']
                            a_prob = 1.0 / df['B365A']
                            
                            synth_1X = 1.0 / (h_prob + d_prob)
                            synth_X2 = 1.0 / (a_prob + d_prob)
                            synth_12 = 1.0 / (h_prob + a_prob)
                            
                            # Fill missing/corrupt values
                            for col, synth_val in [('DC_1X', synth_1X), ('DC_X2', synth_X2), ('DC_12', synth_12)]:
                                if col not in df.columns:
                                    df[col] = synth_val
                                else:
                                    # 1. Null, zero or <= 1.0 odds
                                    is_invalid = df[col].isna() | (df[col] <= 1.0)
                                    
                                    # 2. Mathematical corruption or API bug (copy-paste signature)
                                    if col == 'DC_12':
                                        is_corrupt = (
                                            (df[col] == df['B365D']) | # copied Draw odd
                                            (df[col] >= df['B365H']) | # combined odd >= home odd
                                            (df[col] >= df['B365A']) | # combined odd >= away odd
                                            ((df[col] - synth_val).abs() > 0.25) # large math discrepancy
                                        )
                                    elif col == 'DC_1X':
                                        is_corrupt = (
                                            (df[col] == df['B365H']) | # copied Home odd
                                            ((df[col] - synth_val).abs() > 0.25)
                                        )
                                    else: # DC_X2
                                        is_corrupt = (
                                            (df[col] == df['B365A']) | # copied Away odd
                                            ((df[col] - synth_val).abs() > 0.25)
                                        )
                                    
                                    # Replace invalid or corrupt values with synthetic fallback
                                    df[col] = df[col].where(~(is_invalid | is_corrupt), synth_val)
                                    
                        # Derive HTHG and HTAG from Min_Goals_Home and Min_Goals_Away if they exist
                        import numpy as np
                        def parse_ht_goals_robust(s_min, ft_val):
                            try:
                                ft_goals = int(float(str(ft_val).strip() or 0))
                            except:
                                ft_goals = 0
        
                            if pd.isna(s_min) or not str(s_min).strip() or str(s_min).strip() == '[]':
                                if ft_goals > 0:
                                    return np.nan
                                return 0
                                
                            import ast
                            goals = 0
                            try:
                                lst = ast.literal_eval(str(s_min))
                                if len(lst) != ft_goals:
                                    return np.nan
                                for m in lst:
                                    m_str = str(m).split('+')[0].strip()
                                    if m_str.isdigit() and int(m_str) <= 45:
                                        goals += 1
                            except:
                                return np.nan
                            return goals
        
                        if 'Min_Goals_Home' in df.columns and 'FTHG' in df.columns:
                            df['HTHG'] = [parse_ht_goals_robust(r, f) for r, f in zip(df['Min_Goals_Home'], df['FTHG'])]
                        if 'Min_Goals_Away' in df.columns and 'FTAG' in df.columns:
                            df['HTAG'] = [parse_ht_goals_robust(r, f) for r, f in zip(df['Min_Goals_Away'], df['FTAG'])]
        
                        dataframes.append(df)
                    except Exception as e:
                        logger.error(f"Error parsing csv for temp {temp}: {e}", exc_info=True)
                elif status_code == 401:
                    logger.error("FutPythonTrader API Key inválida.")
                    break
            else:
                logger.error(f"Error fetching FutPythonTrader temp {temp}: {response_text}")
                
    if not dataframes:
        if status_codes:
            codes_str = ", ".join([f"{t}: {code}" for t, code in status_codes.items()])
            raise Exception(f"API retornou erros de status HTTP. Códigos: {codes_str}")
        else:
            raise Exception("Nenhuma conexão pôde ser estabelecida com a API do FutPython (Possível bloqueio de IP ou Timeout).")
        
    df_total = pd.concat(dataframes, ignore_index=True)
    
    if 'Date' in df_total.columns:
        df_total['Date'] = pd.to_datetime(df_total['Date'], dayfirst=True, errors='coerce')
    
    df_total = df_total[df_total['Date'] >= pd.to_datetime(start_date)]
    df_total.sort_values(by=['Date', 'Time'], inplace=True, na_position='first')
    
    df_total = df_total.copy()
    df_total['LeagueCode'] = league_code
    
    # Calculate FTR (Full Time Result)
    import numpy as np
    conditions = [
        (df_total['FTHG'] > df_total['FTAG']),
        (df_total['FTHG'] < df_total['FTAG']),
        (df_total['FTHG'] == df_total['FTAG'])
    ]
    choices = ['H', 'A', 'D']
    df_total['FTR'] = np.select(conditions, choices, default='')
    
    return df_total
