"""Shared Odds API sport_key ↔ league_code mappings.

Import from here in arbitrage_scanner, dutching_scanner, and live_odds_tracker
to keep the mappings in sync across all Odds API modules.
"""

# The Odds API sport_key → internal league_code
SPORT_TO_LEAGUE = {
    # Inglaterra
    'soccer_epl': 'E0',
    'soccer_england_efl_champ': 'E1',
    'soccer_england_league1': 'E2',
    'soccer_england_league2': 'E3',
    # Espanha
    'soccer_spain_la_liga': 'SP1',
    'soccer_spain_segunda_division': 'SP2',
    # Itália
    'soccer_italy_serie_a': 'I1',
    'soccer_italy_serie_b': 'I2',
    # Alemanha
    'soccer_germany_bundesliga': 'D1',
    'soccer_germany_bundesliga2': 'D2',
    # França
    'soccer_france_ligue_one': 'F1',
    'soccer_france_ligue_two': 'F2',
    # Outros europeus
    'soccer_netherlands_eredivisie': 'N1',
    'soccer_belgium_first_div': 'B1',
    'soccer_portugal_primeira_liga': 'P1',
    'soccer_turkey_super_league': 'T1',
    'soccer_greece_super_league': 'G1',
    'soccer_spl': 'SC0',
    'soccer_switzerland_super_league': 'SWITZERLAND_SUPER_LEAGUE',
    'soccer_austria_bundesliga': 'AUSTRIA_BUNDESLIGA',
    'soccer_denmark_superliga': 'DENMARK_SUPERLIGA',
    'soccer_finland_veikkausliiga': 'FINLAND_VEIKKAUSLIIGA',
    'soccer_sweden_allsvenskan': 'SWEDEN_ALLSVENSKAN',
    'soccer_norway_eliteserien': 'NORWAY_ELITESERIEN',
    'soccer_poland_ekstraklasa': 'POLAND_EKSTRAKLASA',
    'soccer_russia_premier_league': 'RUSSIA_RUSSIAN_PREMIER_LEAGUE',
    'soccer_czech_republic': 'CZECHIA_FIRST_LEAGUE',
    'soccer_romania': 'ROMANIA_LIGA_I',
    'soccer_croatia': 'CROATIA_PRVA_HNL',
    'soccer_bulgaria': 'BULGARIA_FIRST_LEAGUE',
    'soccer_hungary': 'HUNGARY_NB_I',
    'soccer_slovakia': 'SLOVAKIA_SUPER_LIGA',
    'soccer_slovenia': 'SLOVENIA_PRVALIGA',
    'soccer_cyprus': 'CYPRUS_FIRST_DIVISION',
    'soccer_israel': 'ISRAEL_ISRAELI_PREMIER_LEAGUE',
    'soccer_serbia': 'SERBIA_SUPERLIGA',
    # Américas
    'soccer_brazil_campeonato': 'BRA',
    'soccer_brazil_serie_b': 'BRAZIL_SERIE_B',
    'soccer_argentina_primera_division': 'ARG',
    'soccer_usa_mls': 'USA',
    'soccer_mexico_ligamx': 'MEX',
    'soccer_chile_campeonato': 'CHILE_PRIMERA_DIVISIN',
    # Ásia
    'soccer_japan_j_league': 'JPN',
    'soccer_korea_kleague1': 'SOUTH_KOREA_K_LEAGUE_1',
    'soccer_australia_aleague': 'AUSTRALIA_A_LEAGUE',
    'soccer_china_superleague': 'CHINA_CHINESE_SUPER_LEAGUE',
    # UEFA
    'soccer_uefa_champs_league': 'EUROPE_UEFA_CHAMPIONS_LEAGUE',
    'soccer_uefa_europa_league': 'EUROPE_UEFA_EUROPA_LEAGUE',
    'soccer_uefa_europa_conference_league': 'EUROPE_UEFA_EUROPA_CONFERENCE_LEAGUE',
}

# All soccer sport keys known to The Odds API (for arbitrage scanning)
ALL_SOCCER_SPORT_KEYS = list(SPORT_TO_LEAGUE.keys())

# Reverse: internal league_code → Odds API sport_key (for live odds tracking)
LEAGUE_TO_SPORT = {v: k for k, v in SPORT_TO_LEAGUE.items()}

# Fallback code for unmapped leagues (shared across modules)
UNMAPPED_LEAGUE_CODE = 'OUTROS'
