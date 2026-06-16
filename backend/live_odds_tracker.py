import os
import json
import requests
from datetime import datetime, timedelta, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
TRACKER_FILE = os.path.join(DATA_DIR, 'live_odds_tracker.json')

API_KEY = '26ced02b008e91c1acdea04181df12ff'
SPORT = 'upcoming'
REGIONS = 'eu,uk,us'
MARKETS = 'h2h,spreads,totals'

def load_tracker_data():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    if not os.path.exists(TRACKER_FILE):
        return {}
    try:
        with open(TRACKER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_tracker_data(data):
    try:
        with open(TRACKER_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving live odds tracker: {e}")

def cleanup_old_matches(data):
    now = datetime.now(timezone.utc)
    to_delete = []
    for match_id, match_data in data.items():
        try:
            commence_time = datetime.fromisoformat(match_data['commence_time'].replace('Z', '+00:00'))
            # If match started more than 12 hours ago, remove it
            if now > commence_time + timedelta(hours=12):
                to_delete.append(match_id)
        except:
            to_delete.append(match_id)
            
    for md in to_delete:
        del data[md]

def normalize_market_key(market_key, outcome_name, home_team, away_team):
    # Converts API market structure to our standard names
    if market_key == 'h2h':
        if outcome_name == home_team: return 'home'
        elif outcome_name == away_team: return 'away'
        else: return 'draw'
    elif market_key == 'totals':
        if outcome_name.lower() == 'over': return 'over25' # Simplified
        elif outcome_name.lower() == 'under': return 'under25'
    elif market_key == 'spreads':
        if outcome_name == home_team: return 'home_spread'
        elif outcome_name == away_team: return 'away_spread'
    return outcome_name

def fetch_and_update_live_odds():
    print("[Live Odds Tracker] Iniciando varredura The Odds API...")
    url = f'https://api.the-odds-api.com/v4/sports/{SPORT}/odds/?apiKey={API_KEY}&regions={REGIONS}&markets={MARKETS}'
    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            print(f"[Live Odds Tracker] API Error: {response.text}")
            return
            
        matches = response.json()
        data = load_tracker_data()
        cleanup_old_matches(data)
        
        updated_count = 0
        new_count = 0
        
        now_str = datetime.now(timezone.utc).isoformat()
        
        for match in matches:
            match_id = match['id']
            home_team = match['home_team']
            away_team = match['away_team']
            sport_key = match['sport_key']
            commence_time = match['commence_time']
            
            # Skip non-soccer for simplicity if we only want soccer
            if 'soccer' not in sport_key.lower():
                continue
                
            if match_id not in data:
                data[match_id] = {
                    'title': f"{home_team} vs {away_team}",
                    'sport': sport_key,
                    'commence_time': commence_time,
                    'bookmakers': {}
                }
                new_count += 1
                
            match_entry = data[match_id]
            
            for bookie in match.get('bookmakers', []):
                bookie_name = bookie['title']
                if bookie_name not in match_entry['bookmakers']:
                    match_entry['bookmakers'][bookie_name] = {}
                    
                bookie_entry = match_entry['bookmakers'][bookie_name]
                
                for market in bookie.get('markets', []):
                    market_key = market['key'] # h2h, totals, spreads
                    
                    for outcome in market.get('outcomes', []):
                        outcome_name = outcome['name']
                        price = outcome['price']
                        
                        norm_market = normalize_market_key(market_key, outcome_name, home_team, away_team)
                        
                        # Use a composite key for market + outcome
                        # e.g., "h2h_home", "totals_over", "spreads_home_spread"
                        comp_key = f"{market_key}_{norm_market}"
                        
                        if comp_key not in bookie_entry:
                            bookie_entry[comp_key] = {
                                'market_type': market_key,
                                'outcome_name': outcome_name,
                                'norm_market': norm_market,
                                'opening': price,
                                'current': price,
                                'last_updated': now_str,
                                'telegram_sent': False
                            }
                        else:
                            # Update current price
                            if bookie_entry[comp_key]['current'] != price:
                                bookie_entry[comp_key]['current'] = price
                                bookie_entry[comp_key]['last_updated'] = now_str
                                updated_count += 1
                                
                                # Telegram Smart Money Check
                                opening = bookie_entry[comp_key]['opening']
                                if opening > 1.0 and price > 0.0 and price < opening:
                                    drop_pct = ((opening / price) - 1.0) * 100
                                    if drop_pct >= 5.0 and not bookie_entry[comp_key].get('telegram_sent', False):
                                        try:
                                            from backend.telegram_bot import send_telegram_message, format_telegram_smart_money_tip
                                            
                                            commence_time = match_entry.get('commence_time', '')
                                            try:
                                                from datetime import datetime, timezone
                                                dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                                                dt_local = dt.astimezone()
                                                date_str = dt_local.strftime('%d/%m %H:%M')
                                            except:
                                                date_str = commence_time
                                                
                                            msg = format_telegram_smart_money_tip(
                                                match_entry.get('title', 'Desconhecido'),
                                                date_str,
                                                bookie_name,
                                                norm_market.upper(),
                                                opening,
                                                price,
                                                drop_pct
                                            )
                                            send_telegram_message(msg)
                                            bookie_entry[comp_key]['telegram_sent'] = True
                                            print(f"[Live Odds Tracker] Telegram alert sent for {match_entry.get('title')} ({drop_pct:.1f}%)")
                                        except Exception as e:
                                            print(f"[Live Odds Tracker] Erro ao enviar telegram: {e}")
                                
        save_tracker_data(data)
        print(f"[Live Odds Tracker] Finalizado. {new_count} novos jogos. {updated_count} odds atualizadas.")
        
    except Exception as e:
        print(f"[Live Odds Tracker] Exceção durante varredura: {e}")

if __name__ == '__main__':
    fetch_and_update_live_odds()
