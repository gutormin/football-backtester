import re

with open('backend/scheduler.py', 'r', encoding='utf-8') as f:
    content = f.read()

autopilot_hook = '''
    mode = config.get("mode", "manual")
    sent_tips = get_telegram_tips()
    sent_lookup = set()
    for t in sent_tips:
        key = (t.get('home_team'), t.get('away_team'), t.get('market'), t.get('date'))
        sent_lookup.add(key)
        
    tips_to_send = []
    
    if mode == "autopilot":
        try:
            from .app import get_autopilot_predictions
            # Get autopilot matches (they are already sorted and checked for EV/odds)
            auto_matches = get_autopilot_predictions(source)
            for m in auto_matches:
                tips_to_send.append({
                    'league_name': m['league_name'],
                    'date_str': m['date'],
                    'time_str': m['time'],
                    'home_team': m['home_team'],
                    'away_team': m['away_team'],
                    'market_label': m['market_label'],
                    'prob': m['prob'],
                    'fair_odds': m['fair_odds'],
                    'bookie_odds': m['bookie_odds'],
                    'ev': m['ev'],
                    'stake_pct': m['stake_pct']
                })
        except Exception as e:
            print(f"[Scheduler Autopilot Error] {e}")
            return {"status": "error", "message": str(e)}
            
    else:
'''

start_idx = content.find('    poisson = PoissonModel()')
end_idx = content.find('    # Apply concurrent bet penalization')

if start_idx != -1 and end_idx != -1:
    old_logic = content[start_idx:end_idx]
    # indent the old logic manually safely
    indented_old_logic = '\n'.join(['        ' + line for line in old_logic.split('\n')])
    
    new_content = content[:start_idx] + autopilot_hook + indented_old_logic + '\n    ' + content[end_idx:]
    with open('backend/scheduler.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Patched successfully")
else:
    print("Could not find injection points")
