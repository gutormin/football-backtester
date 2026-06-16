import pandas as pd
import numpy as np

class SmartMoneyBacktester:
    def __init__(self, data_loader_fn):
        self.data_loader_fn = data_loader_fn

    def scan_steam_moves(self, league_code, min_drop_pct=5.0, markets=None, start_date='2021-01-01', end_date='2026-01-01', stake_value=10):
        if markets is None:
            markets = ['home', 'away', 'draw', 'over25', 'under25']
            
        df = self.data_loader_fn(league_code, start_date=start_date)
        if df is None or df.empty:
            return []
            
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        mask = (df['Date'] >= pd.to_datetime(start_date)) & (df['Date'] <= pd.to_datetime(end_date))
        df = df.loc[mask].copy()
        
        if df.empty:
            return []

        results = []
        
        for market in markets:
            bets = []
            for _, row in df.iterrows():
                max_odd = None
                closing_odd = None
                won = False
                
                if market == 'home':
                    max_odd = row.get('MaxH')
                    closing_odd = row.get('PSCH')
                    won = row.get('FTR') == 'H'
                elif market == 'draw':
                    max_odd = row.get('MaxD')
                    closing_odd = row.get('PSCD')
                    won = row.get('FTR') == 'D'
                elif market == 'away':
                    max_odd = row.get('MaxA')
                    closing_odd = row.get('PSCA')
                    won = row.get('FTR') == 'A'
                elif market == 'over25':
                    max_odd = row.get('Max>2.5')
                    closing_odd = row.get('P>2.5')
                    # P>2.5 is pinnacle closing for over 2.5
                    total_goals = row.get('FTHG', 0) + row.get('FTAG', 0)
                    won = total_goals > 2.5
                elif market == 'under25':
                    max_odd = row.get('Max<2.5')
                    closing_odd = row.get('P<2.5')
                    total_goals = row.get('FTHG', 0) + row.get('FTAG', 0)
                    won = total_goals < 2.5
                
                # If Pinnacle Closing is not available, fallback to Average Closing
                if pd.isna(closing_odd) or not closing_odd:
                    if market == 'home': closing_odd = row.get('AvgCH')
                    elif market == 'draw': closing_odd = row.get('AvgCD')
                    elif market == 'away': closing_odd = row.get('AvgCA')
                    elif market == 'over25': closing_odd = row.get('AvgC>2.5')
                    elif market == 'under25': closing_odd = row.get('AvgC<2.5')

                # If Max is not available, fallback to Average
                if pd.isna(max_odd) or not max_odd:
                    if market == 'home': max_odd = row.get('AvgH')
                    elif market == 'draw': max_odd = row.get('AvgD')
                    elif market == 'away': max_odd = row.get('AvgA')
                    elif market == 'over25': max_odd = row.get('Avg>2.5')
                    elif market == 'under25': max_odd = row.get('Avg<2.5')
                    
                if pd.isna(max_odd) or pd.isna(closing_odd) or not max_odd or not closing_odd or closing_odd <= 1.0 or max_odd <= 1.0:
                    continue
                    
                drop_pct = (max_odd / closing_odd - 1.0) * 100
                
                if drop_pct >= min_drop_pct:
                    # Found a Steam Move! We bet at the closing odd (conservative) or max odd?
                    # Typically, to be conservative and realistic, we assume we catch it at closing_odd,
                    # or somewhere in between. Let's assume we bet at closing_odd for a worst-case scenario
                    # Wait, if we are "Trend Following", we caught the steam move. We probably got closing_odd.
                    profit = (closing_odd - 1.0) * stake_value if won else -stake_value
                    
                    bets.append({
                        'date': row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else '',
                        'match': f"{row.get('HomeTeam', 'Unknown')} vs {row.get('AwayTeam', 'Unknown')}",
                        'max_odd': max_odd,
                        'closing_odd': closing_odd,
                        'drop_pct': drop_pct,
                        'won': won,
                        'profit': profit
                    })
                    
            if not bets:
                results.append({
                    'code': f"{league_code}|{market}",
                    'market_name': market.capitalize(),
                    'total_bets': 0,
                    'net_profit': 0.0,
                    'roi': 0.0,
                    'avg_drop': 0.0,
                    'win_rate': 0.0
                })
                continue
                
            total_bets = len(bets)
            net_profit = sum(b['profit'] for b in bets)
            total_staked = total_bets * stake_value
            roi = (net_profit / total_staked * 100) if total_staked > 0 else 0
            avg_drop = float(np.mean([b['drop_pct'] for b in bets]))
            wins = sum(1 for b in bets if b['won'])
            win_rate = (wins / total_bets * 100) if total_bets > 0 else 0
            
            results.append({
                'code': f"{league_code}|{market}",
                'market_name': market.capitalize(),
                'total_bets': total_bets,
                'net_profit': round(net_profit, 2),
                'roi': round(roi, 2),
                'avg_drop': round(avg_drop, 2),
                'win_rate': round(win_rate, 1)
            })
            
        return results
