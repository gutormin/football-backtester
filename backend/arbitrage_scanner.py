import os
import requests
from datetime import datetime

def fetch_arbitrage_opportunities(allowed_bookies=None):
    API_KEY = '26ced02b008e91c1acdea04181df12ff'
    SPORT = 'upcoming' # Puxar os próximos jogos do mundo (para gastar 1 crédito e ter volume)
    REGIONS = 'eu,uk,us'
    MARKETS = 'h2h,spreads,totals'
    
    url = f'https://api.the-odds-api.com/v4/sports/{SPORT}/odds/?apiKey={API_KEY}&regions={REGIONS}&markets={MARKETS}'
    response = requests.get(url)
    
    if response.status_code != 200:
        print("API Error:", response.text)
        return []
        
    data = response.json()
    opportunities = []
    
    if not allowed_bookies:
        allowed_bookies = ['Bet365', 'Pinnacle', 'Betfair Exchange', 'Betfair', 'Betano', '1xBet', 'Sportingbet', 'Betsson', 'Marathon Bet', '888sport', 'William Hill', 'Bovada']
    
    # Normalizar nomes para facilitar a checagem (case insensitive opcional)
    allowed_bookies_lower = [b.lower() for b in allowed_bookies]
    
    for match in data:
        home_team = match.get('home_team')
        away_team = match.get('away_team')
        match_name = f"{home_team} vs {away_team}"
        
        # Format date and filter live matches
        dt = match.get('commence_time')
        if dt:
            try:
                from datetime import timezone
                match_time = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                # Pular jogos ao vivo para evitar odds atrasadas (Ghost Arb)
                if match_time < datetime.now(timezone.utc):
                    continue
                match_date = match_time.strftime("%d/%m/%Y %H:%M")
            except:
                match_date = dt
        else:
            match_date = "Unknown"
        
        # Variáveis para H2H (1X2)
        best_home = {'price': 0.0, 'bookmaker': ''}
        best_draw = {'price': 0.0, 'bookmaker': ''}
        best_away = {'price': 0.0, 'bookmaker': ''}
        
        # Variáveis para Totals (Over/Under)
        # Formato: { "2.5": {"Over": {"price": 0, "bookie": ""}, "Under": {"price": 0, "bookie": ""}} }
        best_totals = {}
        
        # Variáveis para Spreads (Handicap)
        # Usaremos o valor absoluto do point (ex: 1.5) e mapearemos Home (-1.5) e Away (+1.5)
        # Formato: { "1.5": {"Home_Minus": {"price": 0, "bookie": ""}, "Away_Plus": {"price": 0, "bookie": ""}} }
        best_spreads = {}
        
        for bookie in match.get('bookmakers', []):
            bookie_name = bookie.get('title', 'Unknown')
            
            # Checar se a casa de apostas está na lista permitida do usuário
            if bookie_name.lower() not in allowed_bookies_lower:
                continue
                
            for market in bookie.get('markets', []):
                # 1. MARKET H2H (Match Odds)
                if market.get('key') == 'h2h':
                    for outcome in market.get('outcomes', []):
                        price = outcome.get('price', 0.0)
                        name = outcome.get('name')
                        
                        if name == home_team and price > best_home['price']:
                            best_home = {'price': price, 'bookmaker': bookie_name}
                        elif name == away_team and price > best_away['price']:
                            best_away = {'price': price, 'bookmaker': bookie_name}
                        elif name == 'Draw' and price > best_draw['price']:
                            best_draw = {'price': price, 'bookmaker': bookie_name}
                            
                # 2. MARKET TOTALS (Over / Under)
                elif market.get('key') == 'totals':
                    for outcome in market.get('outcomes', []):
                        price = outcome.get('price', 0.0)
                        name = outcome.get('name')
                        point = str(outcome.get('point', '0'))
                        
                        if point not in best_totals:
                            best_totals[point] = {
                                'Over': {'price': 0.0, 'bookmaker': ''},
                                'Under': {'price': 0.0, 'bookmaker': ''}
                            }
                            
                        if name == 'Over' and price > best_totals[point]['Over']['price']:
                            best_totals[point]['Over'] = {'price': price, 'bookmaker': bookie_name}
                        elif name == 'Under' and price > best_totals[point]['Under']['price']:
                            best_totals[point]['Under'] = {'price': price, 'bookmaker': bookie_name}
                            
                # 3. MARKET SPREADS (Handicap)
                elif market.get('key') == 'spreads':
                    for outcome in market.get('outcomes', []):
                        price = outcome.get('price', 0.0)
                        name = outcome.get('name')
                        point = outcome.get('point', 0.0)
                        
                        # Criar uma chave única para o Handicap (ex: "Home -1.5 / Away +1.5")
                        # Para facilitar o match, vamos armazenar as duas pontas.
                        # Uma aposta no Home com point X é oposta ao Away com point -X.
                        if name == home_team:
                            key = f"H{point}_A{-point}"
                            side = 'Home'
                        elif name == away_team:
                            key = f"H{-point}_A{point}"
                            side = 'Away'
                        else:
                            continue
                            
                        if key not in best_spreads:
                            best_spreads[key] = {
                                'Home': {'price': 0.0, 'bookmaker': '', 'point': 0},
                                'Away': {'price': 0.0, 'bookmaker': '', 'point': 0}
                            }
                            
                        if side == 'Home' and price > best_spreads[key]['Home']['price']:
                            best_spreads[key]['Home'] = {'price': price, 'bookmaker': bookie_name, 'point': point}
                        elif side == 'Away' and price > best_spreads[key]['Away']['price']:
                            best_spreads[key]['Away'] = {'price': price, 'bookmaker': bookie_name, 'point': point}
        
        # ---------------- Check Arbitrage (H2H - 3 Way) ----------------
        mh, md, ma = best_home['price'], best_draw['price'], best_away['price']
        if mh > 1 and md > 1 and ma > 1:
            implied = (1/mh) + (1/md) + (1/ma)
            if implied < 1.0:
                profit_pct = (1.0 - implied) / implied * 100
                if profit_pct > 0 and profit_pct <= 15.0:
                    opportunities.append({
                        'match': match_name,
                        'date': match_date,
                        'market': 'Match Odds (1X2)',
                        'odds': {'1': mh, 'X': md, '2': ma},
                        'bookmakers': {'1': best_home['bookmaker'], 'X': best_draw['bookmaker'], '2': best_away['bookmaker']},
                        'implied_prob': round(implied * 100, 2),
                        'profit_margin': round(profit_pct, 2)
                    })
                    
        # ---------------- Check Arbitrage (Totals - 2 Way) ----------------
        for point, out in best_totals.items():
            po, pu = out['Over']['price'], out['Under']['price']
            if po > 1 and pu > 1:
                implied = (1/po) + (1/pu)
                if implied < 1.0:
                    profit_pct = (1.0 - implied) / implied * 100
                    if profit_pct > 0 and profit_pct <= 15.0:
                        opportunities.append({
                            'match': match_name,
                            'date': match_date,
                            'market': f'Over/Under ({point})',
                            'odds': {'1': po, '2': pu}, # Reusing '1' and '2' keys for frontend compatibility
                            'bookmakers': {'1': out['Over']['bookmaker'], '2': out['Under']['bookmaker']},
                            'implied_prob': round(implied * 100, 2),
                            'profit_margin': round(profit_pct, 2),
                            'is_2_way': True,
                            'labels': {'1': f'Over {point}', '2': f'Under {point}'}
                        })
                        
        # ---------------- Check Arbitrage (Spreads - 2 Way) ----------------
        for key, out in best_spreads.items():
            ph, pa = out['Home']['price'], out['Away']['price']
            if ph > 1 and pa > 1:
                implied = (1/ph) + (1/pa)
                if implied < 1.0:
                    profit_pct = (1.0 - implied) / implied * 100
                    if profit_pct > 0 and profit_pct <= 15.0:
                        h_point = out['Home']['point']
                        a_point = out['Away']['point']
                        opportunities.append({
                            'match': match_name,
                            'date': match_date,
                            'market': 'Handicap (Spreads)',
                            'odds': {'1': ph, '2': pa},
                            'bookmakers': {'1': out['Home']['bookmaker'], '2': out['Away']['bookmaker']},
                            'implied_prob': round(implied * 100, 2),
                            'profit_margin': round(profit_pct, 2),
                            'is_2_way': True,
                            'labels': {'1': f'Home {h_point:+g}', '2': f'Away {a_point:+g}'}
                        })
                    
    opportunities = sorted(opportunities, key=lambda x: x['profit_margin'], reverse=True)
    return opportunities
