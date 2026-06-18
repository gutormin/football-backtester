with open('backend/app.py', 'a', encoding='utf-8') as f:
    f.write('''
@app.get('/api/autopilot')
def get_autopilot_predictions(source: str = 'api'):
    try:
        import pandas as pd
        from datetime import datetime
        import numpy as np
        from .history_manager import load_history
        from .ai_predictor import PoissonModel
        from .models import estimate_bookmaker_odds
        
        history = load_history()
        # Filter strategies that have positive net_profit
        valid_strategies = []
        for s in history:
            net_profit = s.get('summary', {}).get('net_profit', 0)
            if net_profit > 0:
                valid_strategies.append(s)
                
        if not valid_strategies:
            return []
            
        df_fixtures = pd.DataFrame()
        if source == 'api':
            token = get_api_token()
            if token:
                df_fixtures = load_upcoming_from_api(token)
                
        if df_fixtures.empty:
            sync_fixtures(force=False)
            import os
            fixtures_path = os.path.join(DATA_DIR, 'fixtures.csv')
            if os.path.exists(fixtures_path):
                df_fixtures = pd.read_csv(fixtures_path, encoding='latin1')
                df_fixtures.columns = [c.replace('ï»¿', '').replace('\\ufeff', '').strip() for c in df_fixtures.columns]
            else:
                return []
                
        all_leagues = get_all_available_leagues()
        league_codes = [l['code'] for l in all_leagues]
        poisson = PoissonModel()
        league_cache = {}
        elo_cache = {}
        
        autopilot_matches = []
        
        for row in df_fixtures.to_dict('records'):
            league_code = row.get('Div')
            if not league_code or league_code not in league_codes:
                continue
                
            home_team = row.get('HomeTeam')
            away_team = row.get('AwayTeam')
            if pd.isna(home_team) or pd.isna(away_team):
                continue
                
            if league_code not in league_cache:
                hist = load_league_data(league_code, start_date='2020-08-01')
                league_cache[league_code] = hist
                elo_cache[league_code] = build_elo_tracker_from_history(hist)
                
            hist_df = league_cache[league_code]
            elo_tracker = elo_cache[league_code]
            if hist_df.empty:
                continue
                
            try:
                match_date = pd.to_datetime(row.get('Date'), dayfirst=True)
            except:
                match_date = datetime.now()
                
            pred = poisson.predict_match(home_team, away_team, hist_df, match_date, elo_tracker=elo_tracker)
            
            odds_h = float(row.get('B365H', np.nan))
            odds_d = float(row.get('B365D', np.nan))
            odds_a = float(row.get('B365A', np.nan))
            odds_over25 = float(row.get('B365>2.5', np.nan))
            odds_under25 = float(row.get('B365<2.5', np.nan))
            
            est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, pred['lambda_home'], pred['lambda_away'])
            
            for strategy in valid_strategies:
                p = strategy.get('params', {})
                s_leagues = p.get('leagues', [])
                if league_code not in s_leagues:
                    continue
                    
                # Market parameter support in saved strategies could be 'market' or 'markets' (comma separated)
                s_markets_str = p.get('markets')
                s_market_str = p.get('market', 'home')
                s_markets = [m.strip() for m in s_markets_str.split(',')] if s_markets_str else [s_market_str]
                
                s_min = float(p.get('minOdds', 1.0))
                s_max = float(p.get('maxOdds', 50.0))
                s_val = float(p.get('valThreshold', 1.05))
                stakingRule = p.get('stakingRule', 'fixed')
                stakeValue = float(p.get('stakeValue', 10.0))
                initialBankroll = float(p.get('initialBankroll', 1000.0))
                
                for s_m in s_markets:
                    market_prob = 0.0
                    bookie_odds = np.nan
                    market_label = ''
                    
                    if s_m == 'home': market_prob = pred['prob_home']; bookie_odds = odds_h; market_label = '1 (Mandante)'
                    elif s_m == 'away': market_prob = pred['prob_away']; bookie_odds = odds_a; market_label = '2 (Visitante)'
                    elif s_m == 'draw': market_prob = pred['prob_draw']; bookie_odds = odds_d; market_label = 'X (Empate)'
                    elif s_m == 'btts_yes': market_prob = pred['prob_btts_yes']; bookie_odds = est_odds.get('bookie_btts_yes', np.nan); market_label = 'BTTS Sim'
                    elif s_m == 'btts_no': market_prob = pred['prob_btts_no']; bookie_odds = est_odds.get('bookie_btts_no', np.nan); market_label = 'BTTS Não'
                    elif s_m == 'over15': market_prob = pred['prob_over_15']; bookie_odds = est_odds.get('bookie_over_15', np.nan); market_label = 'Over 1.5'
                    elif s_m == 'over25': market_prob = pred['prob_over_25']; bookie_odds = odds_over25; market_label = 'Over 2.5'
                    elif s_m == 'under25': market_prob = pred['prob_under_25']; bookie_odds = odds_under25; market_label = 'Under 2.5'
                    elif s_m.startswith('cs_'): market_prob = pred.get(f"prob_{s_m}", 0.0); bookie_odds = est_odds.get(f"bookie_{s_m}", np.nan); market_label = f"Placar Exato {s_m[3]}-{s_m[4]}"
                    elif s_m == 'lay_home': market_prob = pred['prob_draw'] + pred['prob_away']; bookie_odds = 1.0 / (1.0/odds_d + 1.0/odds_a) if (odds_d > 1.0 and odds_a > 1.0) else np.nan; market_label = "Contra Mandante (X2)"
                    elif s_m == 'lay_away': market_prob = pred['prob_home'] + pred['prob_draw']; bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_d) if (odds_h > 1.0 and odds_d > 1.0) else np.nan; market_label = "Contra Visitante (1X)"
                    elif s_m == 'lay_draw': market_prob = pred['prob_home'] + pred['prob_away']; bookie_odds = 1.0 / (1.0/odds_h + 1.0/odds_a) if (odds_h > 1.0 and odds_a > 1.0) else np.nan; market_label = "Contra Empate (12)"

                    if pd.isna(bookie_odds) or bookie_odds <= 1.0:
                        continue
                        
                    ev = market_prob * bookie_odds
                    if ev >= s_val and s_min <= bookie_odds <= s_max:
                        stake_pct = 0.0
                        if stakingRule.startswith('kelly'):
                            mult_k = 1.0
                            if stakingRule == 'kelly_half': mult_k = 0.5
                            elif stakingRule == 'kelly_quarter': mult_k = 0.25
                            elif stakingRule == 'kelly_eighth': mult_k = 0.125
                            elif stakingRule == 'kelly': mult_k = stakeValue
                            else: mult_k = stakeValue
                            f_star = (market_prob * bookie_odds - 1.0) / (bookie_odds - 1.0)
                            stake_pct = max(0.0, f_star) * mult_k * 100.0
                            stake_pct = min(stake_pct, 5.0)
                        elif stakingRule == 'proportional':
                            stake_pct = stakeValue
                        else:
                            stake_pct = (stakeValue / initialBankroll) * 100.0
                            
                        from .data_loader import LEAGUES_SEASONAL
                        league_name = row.get('LeagueName') or LEAGUES_SEASONAL.get(league_code, league_code)
                        
                        def clean_odd(val):
                            try:
                                v = float(val)
                                return round(v, 2) if not pd.isna(v) and v > 0 else None
                            except:
                                return None
                                
                        odds_comp = {
                            'Bet365': {'H': clean_odd(row.get('B365H')), 'D': clean_odd(row.get('B365D')), 'A': clean_odd(row.get('B365A'))}
                        }
                        
                        autopilot_matches.append({
                            'league_code': league_code,
                            'league_name': league_name,
                            'date': str(row.get('Date')),
                            'time': str(row.get('Time')) if not pd.isna(row.get('Time')) else '00:00',
                            'home_team': home_team,
                            'away_team': away_team,
                            'market_label': market_label,
                            'prob': round(market_prob * 100, 1),
                            'fair_odds': round(1.0 / market_prob, 2) if market_prob > 0.001 else 99.0,
                            'bookie_odds': round(bookie_odds, 2),
                            'ev': round(ev, 2),
                            'is_tip': True,
                            'stake_pct': round(stake_pct, 1),
                            'odds_comparison': odds_comp,
                            'strategy_name': strategy.get('name', 'Autopilot Strategy')
                        })
                    
        # Sort and return
        autopilot_matches.sort(key=lambda x: (x['date'], x['time']))
        return autopilot_matches
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
''')
