import os
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
    Ligas de alta liquidez exigem menos variação para serem de alta confiança.
    Ligas de baixa liquidez exigem variações violentas para mitigar ruídos de baixo volume.
    Retorna (score, confidence_level, liquidity_tier)
    """
    tier_name, weight = estimate_liquidity_tier(league_identifier)
    if drop_pct <= 0:
        return 0.0, 'Baixa', tier_name
        
    if tier_name == 'Alta':
        score = min(100.0, 35.0 + (drop_pct * 12.0))
    elif tier_name == 'Média':
        score = min(100.0, 15.0 + (drop_pct * 8.0))
    else: # Baixa
        score = min(100.0, drop_pct * 5.0)
        
    if score >= 75.0:
        confidence_level = 'Alta'
    elif score >= 45.0:
        confidence_level = 'Média'
    else:
        confidence_level = 'Baixa'
        
    return round(score, 1), confidence_level, tier_name

class SmartMoneyBacktester:
    def __init__(self, data_loader_fn=None):
        self.data_loader_fn = data_loader_fn
        self.history_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'live_steam_moves_history.json')

    def scan_steam_moves(self, league_code=None, min_drop_pct=5.0, markets=None, start_date='2021-01-01', end_date='2026-01-01', stake_value=10):
        import os
        import json
        
        if markets is None:
            markets = ['home', 'away', 'draw']
            
        # Default list of niches to display if history is empty, matching user's main leagues
        default_leagues = ['BRA', 'E0', 'F1', 'D1', 'I1', 'SP1']
        
        # Load real history alerts from json
        history_alerts = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history_alerts = json.load(f)
            except Exception:
                pass
                
        # Group alerts by niche (league_code | market)
        niche_groups = {}
        
        # Pre-populate with defaults to avoid empty screens
        leagues_to_populate = [league_code] if league_code else default_leagues
        for lcode in leagues_to_populate:
            for mkt in markets:
                niche_key = f"{lcode}|{mkt}"
                niche_groups[niche_key] = []
                
        # Populate with real alerts if they match filters
        for alert in history_alerts:
            lcode = alert.get('league_code')
            mkt = alert.get('market', '').lower()
            if not lcode or not mkt:
                continue
                
            # Filter by dates
            alert_date_str = alert.get('date', '')
            try:
                # Expecting 'YYYY-MM-DD' or 'DD/MM HH:MM'
                # Simplistic filter: check if start_date in string or basic ISO parse
                alert_dt = pd.to_datetime(alert_date_str, errors='coerce')
                if pd.notna(alert_dt):
                    if alert_dt < pd.to_datetime(start_date) or alert_dt > pd.to_datetime(end_date):
                        continue
            except:
                pass
                
            # Filter by league selection if requested
            if league_code and lcode != league_code:
                continue
                
            if mkt not in markets:
                continue
                
            if alert.get('drop_pct', 0.0) < min_drop_pct:
                continue
                
            niche_key = f"{lcode}|{mkt}"
            if niche_key not in niche_groups:
                niche_groups[niche_key] = []
            niche_groups[niche_key].append(alert)
            
        results = []
        for niche_key, bets in niche_groups.items():
            lcode, mkt = niche_key.split('|')
            
            # Estimate league info
            tier_name, weight = estimate_liquidity_tier(lcode)
            
            if not bets:
                score, confidence_level, tier_name = calculate_confidence_score(0.0, lcode)
                results.append({
                    'code': niche_key,
                    'market_name': mkt.capitalize(),
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
            net_profit = sum(b.get('profit', 0.0) for b in bets)
            total_staked = sum(b.get('stake_value', stake_value) for b in bets)
            roi = (net_profit / total_staked * 100) if total_staked > 0 else 0
            avg_drop = float(np.mean([b.get('drop_pct', 0.0) for b in bets]))
            
            # Count wins
            wins = sum(1 for b in bets if b.get('won') == True)
            win_rate = (wins / total_bets * 100) if total_bets > 0 else 0
            
            score, confidence_level, tier_name = calculate_confidence_score(avg_drop, lcode)
            
            results.append({
                'code': niche_key,
                'market_name': mkt.capitalize(),
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
