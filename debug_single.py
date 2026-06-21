import json
from backend.backtester import ChronologicalBacktester
from datetime import datetime

p = json.load(open('data/history_strategies.json', encoding='utf-8'))[0]['params']
print("Params:", p)

bt = ChronologicalBacktester()
res = bt.run(
    leagues=p.get('leagues', []),
    start_date=p.get('startDate', p.get('start_date', '2021-01-01')),
    end_date=p.get('endDate', p.get('end_date', datetime.today().strftime('%Y-%m-%d'))),
    market=p.get('market'),
    value_threshold=p.get('valueThreshold', p.get('value_threshold', 1.05)),
    initial_bankroll=1000.0,
    staking_rule='fixed',
    stake_value=10.0,
    odds_source=p.get('oddsSource', p.get('odds_source', 'B365')),
    min_odds=p.get('minOdds', 1.0),
    max_odds=p.get('maxOdds', 50.0),
    data_source=p.get('data_source', 'football-data'),
    use_ml=p.get('use_ml', False),
    futpython_api_key=p.get('futpython_api_key', ''),
    min_odds_h=p.get('minOddsH'), max_odds_h=p.get('maxOddsH'),
    min_odds_d=p.get('minOddsD'), max_odds_d=p.get('maxOddsD'),
    min_odds_a=p.get('minOddsA'), max_odds_a=p.get('maxOddsA'),
    min_odds_over25=p.get('minOddsOver25'), max_odds_over25=p.get('maxOddsOver25'),
    min_odds_under25=p.get('minOddsUnder25'), max_odds_under25=p.get('maxOddsUnder25')
)
if "error" in res:
    print("Error:", res["error"])
else:
    print("Total Bets:", res.get("total_bets"))
    if res.get("total_bets") == 0:
        print("Why 0? Debugging...")
