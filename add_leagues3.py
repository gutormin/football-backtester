import json
import os

new_urls = """
/api/download/peru/liga-1/2026
/api/download/peru/liga-2/2026
/api/download/poland/division-1/2025-2026
/api/download/poland/ekstraklasa/2025-2026
/api/download/portugal/league-cup/2025-2026
/api/download/portugal/liga-3/2025-2026
/api/download/portugal/liga-portugal/2025-2026
/api/download/portugal/liga-portugal-2/2025-2026
/api/download/portugal/taca-de-portugal/2025-2026
/api/download/romania/liga-2/2025-2026
/api/download/romania/superliga/2025-2026
/api/download/saudi-arabia/division-1/2025-2026
/api/download/saudi-arabia/saudi-professional-league/2025-2026
/api/download/scotland/championship/2025-2026
/api/download/scotland/league-cup/2025-2026
/api/download/scotland/league-one/2025-2026
/api/download/scotland/league-two/2025-2026
/api/download/scotland/premiership/2025-2026
/api/download/scotland/scottish-cup/2025-2026
/api/download/serbia/mozzart-bet-prva-liga/2025-2026
/api/download/serbia/mozzart-bet-super-liga/2025-2026
/api/download/slovakia/2-liga/2025-2026
/api/download/slovakia/nike-liga/2025-2026
/api/download/slovenia/2-snl/2025-2026
/api/download/slovenia/prva-liga/2025-2026
/api/download/south-africa/betway-premiership/2025-2026
/api/download/south-africa/motsepe-foundation-championship/2025-2026
/api/download/south-america/copa-america/2021|
/api/download/south-america/copa-libertadores/2026
/api/download/south-america/copa-sudamericana/2026
/api/download/south-korea/k-league-1/2026
/api/download/south-korea/k-league-2/2026
/api/download/spain/copa-del-rey/2025-2026
/api/download/spain/laliga/2025-2026
/api/download/spain/laliga2/2025-2026
/api/download/spain/primera-rfef-group-1/2025-2026
/api/download/spain/liga-f-women/2025-2026
/api/download/spain/primera-rfef-group-2/2025-2026
/api/download/spain/segunda-rfef-group-1/2025-2026
/api/download/spain/primera-rfef-group-2/2025-2026
/api/download/spain/segunda-rfef-group-2/2025-2026
/api/download/spain/segunda-rfef-group-3/2025-2026
/api/download/spain/segunda-rfef-group-4/2025-2026
/api/download/spain/segunda-rfef-group-5/2025-2026
/api/download/sweden/allsvenskan/2026
/api/download/sweden/superettan/2026
/api/download/switzerland/challenge-league/2025-2026
/api/download/switzerland/super-league/2025-2026
/api/download/turkey/1-lig/2025-2026
/api/download/turkey/super-lig/2025-2026
/api/download/turkey/turkish-cup/2025-2026
/api/download/ukraine/persha-liga/2025-2026
/api/download/uruguay/liga-auf-uruguaya/2026
/api/download/ukraine/premier-league/2025-2026
/api/download/uruguay/segunda-division/2026
/api/download/usa/mls/2026
/api/download/usa/nwsl-women/2026
/api/download/usa/usl-championship/2026
/api/download/venezuela/liga-futve/2026
/api/download/venezuela/liga-futve/2026
/api/download/wales/cymru-premier/2025-2026
/api/download/wales/fa-cup/2025-2026
/api/download/wales/league-cup/2025-2026
/api/download/world/world-championship/2022
"""

json_path = r'C:\Users\Gustavo\.gemini\antigravity\scratch\football-backtester\data\futpython_leagues.json'

with open(json_path, 'r', encoding='utf-8') as f:
    leagues = json.load(f)

for line in new_urls.strip().split('\n'):
    line = line.strip().replace('|', '')
    if not line: continue
    parts = line.split('/')
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
