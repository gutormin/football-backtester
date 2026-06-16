import codecs

content = """

class LiveSteamRequest(BaseModel):
    minDropPct: float = 5.0
    markets: List[str] = ['home']
    leagues: List[str] = []

@app.post("/api/live_steam_moves")
def get_live_steam_moves(req: LiveSteamRequest):
    import json
    import os
    from datetime import datetime, timezone
    
    tracker_file = os.path.join(os.path.dirname(__file__), 'data', 'live_odds_tracker.json')
    if not os.path.exists(tracker_file):
        return {"status": "success", "scan_results": []}
        
    try:
        with open(tracker_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        results = []
        for match_id, match_info in data.items():
            title = match_info.get('title', 'Desconhecido')
            commence_time = match_info.get('commence_time', '')
            
            # Format date beautifully
            try:
                dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                dt_local = dt.astimezone() # convert to server local time
                date_str = dt_local.strftime('%d/%m %H:%M')
            except:
                date_str = commence_time
            
            for bookie, markets_data in match_info.get('bookmakers', {}).items():
                for comp_key, odds_data in markets_data.items():
                    norm_market = odds_data['norm_market']
                    # Filter by requested markets
                    if norm_market not in req.markets:
                        continue
                        
                    opening = odds_data['opening']
                    current = odds_data['current']
                    
                    if opening > 1.0 and current > 0.0 and current < opening:
                        drop_pct = ((opening / current) - 1.0) * 100
                        if drop_pct >= req.minDropPct:
                            results.append({
                                'match': title,
                                'date': date_str,
                                'bookmaker': bookie,
                                'market': norm_market.upper(),
                                'opening_odd': opening,
                                'current_odd': current,
                                'drop_pct': round(drop_pct, 1)
                            })
                            
        # Sort by biggest drop
        results = sorted(results, key=lambda x: x['drop_pct'], reverse=True)
        return {"status": "success", "scan_results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""

with codecs.open('app.py', 'a', encoding='utf-8') as f:
    f.write(content)
