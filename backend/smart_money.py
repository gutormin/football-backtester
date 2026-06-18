import pandas as pd
import numpy as np

def estimate_liquidity_tier(league_identifier: str):
    """
    Estima a liquidez da liga baseado em sua sigla/nome.
    Retorna (tier_name, weight) onde:
    - tier_name: 'Alta', 'Média', 'Baixa'
    - weight: 1.0, 0.7, 0.4
    """
    if not league_identifier:
        return 'Baixa', 0.4
    lid = league_identifier.lower().strip()
    
    # Tier 1 - Alta Liquidez (Peso 1.0)
    t1_keys = [
        'e0', 'sp1', 'i1', 'd1', 'f1', 'bra', 
        'premier_league', 'la_liga', 'serie_a', 'bundesliga', 'ligue1', 'campeonato_brasileiro', 'brazil_serie_a'
    ]
    is_t1 = any(k in lid for k in t1_keys)
    if is_t1:
        if 'bundesliga2' in lid or 'bundesliga_2' in lid or 'serie_b' in lid or 'segunda' in lid:
            pass
        else:
            return 'Alta', 1.0
            
    # Tier 2 - Média Liquidez (Peso 0.7)
    t2_keys = [
        'e1', 'sp2', 'i2', 'd2', 'f2', 'n1', 'b1', 'p1', 't1', 'usa', 'jpn',
        'championship', 'segunda', 'serie_b', 'bundesliga2', 'bundesliga_2', 'ligue2', 'eredivisie', 
        'primeira_liga', 'belgium_first_division', 'super_league', 'mls', 'j_league', 'japan_j_league',
        'netherlands_eredivisie', 'portugal_primeira_liga', 'turkey_super_league'
    ]
    if any(k in lid for k in t2_keys):
        return 'Média', 0.7
        
    # Tier 3 - Baixa Liquidez (Peso 0.4)
    return 'Baixa', 0.4

def calculate_confidence_score(drop_pct: float, league_identifier: str):
    """
    Calcula um score de confiança de 0 a 100 com base no drop de odds e na liquidez da liga.
    Formula: Confidence Score = min(100.0, drop_pct * 10.0 * liquidity_weight)
    Retorna (score, confidence_level, liquidity_tier)
    """
    tier_name, weight = estimate_liquidity_tier(league_identifier)
    if drop_pct <= 0:
        return 0.0, 'Baixa', tier_name
        
    score = min(100.0, drop_pct * 10.0 * weight)
    
    if score >= 75.0:
        confidence_level = 'Alta'
    elif score >= 45.0:
        confidence_level = 'Média'
    else:
        confidence_level = 'Baixa'
        
    return round(score, 1), confidence_level, tier_name

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
                score, confidence_level, tier_name = calculate_confidence_score(0.0, league_code)
                results.append({
                    'code': f"{league_code}|{market}",
                    'market_name': market.capitalize(),
                    'total_bets': 0,
                    'net_profit': 0.0,
                    'roi': 0.0,
                    'avg_drop': 0.0,
                    'win_rate': 0.0,
                    'liquidity_tier': tier_name,
                    'confidence_score': score,
                    'confidence_level': confidence_level
                })
                continue
                
            total_bets = len(bets)
            net_profit = sum(b['profit'] for b in bets)
            total_staked = total_bets * stake_value
            roi = (net_profit / total_staked * 100) if total_staked > 0 else 0
            avg_drop = float(np.mean([b['drop_pct'] for b in bets]))
            wins = sum(1 for b in bets if b['won'])
            win_rate = (wins / total_bets * 100) if total_bets > 0 else 0
            
            score, confidence_level, tier_name = calculate_confidence_score(avg_drop, league_code)
            
            results.append({
                'code': f"{league_code}|{market}",
                'market_name': market.capitalize(),
                'total_bets': total_bets,
                'net_profit': round(net_profit, 2),
                'roi': round(roi, 2),
                'avg_drop': round(avg_drop, 2),
                'win_rate': round(win_rate, 1),
                'liquidity_tier': tier_name,
                'confidence_score': score,
                'confidence_level': confidence_level
            })
            
        return results
