import json
import os

new_urls = """
/api/download/egypt/division-2-a/2025-2026
/api/download/egypt/premier-league/2025-2026
/api/download/england/championship/2025-2026
/api/download/england/efl-cup/2025-2026
/api/download/england/fa-cup/2025-2026
/api/download/england/league-one/2025-2026
/api/download/england/league-two/2025-2026
/api/download/england/national-league/2025-2026
/api/download/england/premier-league/2025-2026
/api/download/england/wsl/2025-2026
/api/download/estonia/esiliiga/2026
/api/download/estonia/meistriliiga/2026
/api/download/europe/champions-league/2025-2026
/api/download/europe/euro/2020
/api/download/europe/europa-conference-league/2025-2026
/api/download/europe/europa-league/2025-2026
/api/download/europe/uefa-nations-league/2024-2025
/api/download/finland/veikkausliiga/2026
/api/download/finland/ykkosliiga/2026
/api/download/france/coupe-de-france/2025-2026
/api/download/france/ligue-1/2025-2026
/api/download/france/ligue-2/2025-2026
/api/download/france/national/2025-2026
/api/download/france/national-2-group-a/2025-2026
/api/download/france/national-2-group-b/2025-2026
/api/download/france/national-2-group-c/2025-2026
/api/download/france/premiere-ligue-women/2025-2026
/api/download/germany/2-bundesliga/2025-2026
/api/download/germany/3-liga/2025-2026
/api/download/germany/bundesliga-women/2025-2026
/api/download/germany/bundesliga/2025-2026
/api/download/germany/dfb-pokal/2025-2026
/api/download/greece/super-league/2025-2026
/api/download/greece/super-league-2/2025-2026
/api/download/iceland/besta-deild-karla/2026
/api/download/iceland/division-1/2026
/api/download/ireland/division-1/2026
/api/download/ireland/premier-division/2026
/api/download/israel/leumit-league/2025-2026
/api/download/israel/ligat-ha-al/2025-2026
/api/download/italy/coppa-italia/2025-2026
/api/download/italy/serie-a/2025-2026
/api/download/italy/serie-a-women/2025-2026
/api/download/italy/serie-b/2025-2026
/api/download/italy/serie-c-group-a/2025-2026
/api/download/italy/serie-c-group-b/2025-2026
/api/download/italy/serie-c-group-c/2025-2026
/api/download/italy/serie-d-group-a/2025-2026
/api/download/italy/serie-d-group-b/2025-2026
/api/download/italy/serie-d-group-c/2025-2026
/api/download/italy/serie-d-group-d/2025-2026
/api/download/italy/serie-d-group-e/2025-2026
/api/download/italy/serie-d-group-f/2025-2026
/api/download/italy/serie-d-group-g/2025-2026
/api/download/italy/serie-d-group-h/2025-2026
/api/download/japan/j1-league/2026
/api/download/japan/j2-j3-league/2026
/api/download/japan/j2-league/2025
/api/download/japan/j3-league/2026
/api/download/mexico/liga-de-expansion-mx/2025-2026
/api/download/mexico/liga-mx/2025-2026
/api/download/netherlands/eerste-divisie/2025-2026
/api/download/netherlands/eredivisie/2025-2026
/api/download/netherlands/knvb-beker/2025-2026
/api/download/northern-ireland/nifl-championship/2025-2026
/api/download/northern-ireland/nifl-premiership/2025-2026
/api/download/norway/eliteserien/2026
/api/download/norway/obos-ligaen/2026
/api/download/paraguay/copa-de-primera/2026
/api/download/paraguay/copa-paraguay/2025
/api/download/paraguay/division-intermedia/2026
"""

json_path = r'C:\Users\Gustavo\.gemini\antigravity\scratch\football-backtester\data\futpython_leagues.json'

with open(json_path, 'r', encoding='utf-8') as f:
    leagues = json.load(f)

for line in new_urls.strip().split('\n'):
    if not line: continue
    parts = line.strip().split('/')
    if len(parts) >= 5:
        country = parts[3]
        league_slug = parts[4]
        if country not in leagues:
            leagues[country] = []
        if league_slug not in leagues[country]:
            leagues[country].append(league_slug)

with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(leagues, f, indent=4, ensure_ascii=False)

print("Added new leagues.")
