import codecs
import re

with codecs.open('C:\\Users\\Gustavo\\.gemini\\antigravity\\scratch\\football-backtester\\backend\\backtester.py', 'r', 'utf-8') as f:
    content = f.read()

# Replacement 1 for run()
old_btts_run = """                elif mkt == 'btts_yes':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = prob_btts_yes
                    bookie_odds = est_odds['bookie_btts_yes']
                    bet_won = (fthg > 0 and ftag > 0)
                    market_label = "BTTS Sim"
                elif mkt == 'btts_no':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = 1.0 - prob_btts_yes
                    bookie_odds = est_odds['bookie_btts_no']
                    bet_won = (fthg == 0 or ftag == 0)
                    market_label = "BTTS Não\""""

new_btts_run = """                elif mkt == 'btts_yes':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = prob_btts_yes
                    
                    actual_odd = row.get('BTTS_Yes', np.nan)
                    try:
                        parsed_odd = float(str(actual_odd).replace(',', '.')) if not pd.isna(actual_odd) else np.nan
                        bookie_odds = parsed_odd if parsed_odd > 1.0 else est_odds['bookie_btts_yes']
                    except Exception:
                        bookie_odds = est_odds['bookie_btts_yes']
                        
                    bet_won = (fthg > 0 and ftag > 0)
                    market_label = "BTTS Sim"
                elif mkt == 'btts_no':
                    if est_odds is None: est_odds = estimate_bookmaker_odds(odds_over25, odds_under25, lambda_home, lambda_away)
                    model_prob = 1.0 - prob_btts_yes
                    
                    actual_odd = row.get('BTTS_No', np.nan)
                    try:
                        parsed_odd = float(str(actual_odd).replace(',', '.')) if not pd.isna(actual_odd) else np.nan
                        bookie_odds = parsed_odd if parsed_odd > 1.0 else est_odds['bookie_btts_no']
                    except Exception:
                        bookie_odds = est_odds['bookie_btts_no']
                        
                    bet_won = (fthg == 0 or ftag == 0)
                    market_label = "BTTS Não\""""

content = content.replace(old_btts_run, new_btts_run)

# Replacement 2 for run_parallel_scan()
old_btts_scan = """                    elif mkt == 'btts_yes':
                        model_prob = prob_btts_yes
                        bookie_odds = est_odds['bookie_btts_yes']
                        bet_won = (fthg > 0 and ftag > 0)
                    elif mkt == 'btts_no':
                        model_prob = 1.0 - prob_btts_yes
                        bookie_odds = est_odds['bookie_btts_no']
                        bet_won = (fthg == 0 or ftag == 0)\""""

new_btts_scan = """                    elif mkt == 'btts_yes':
                        model_prob = prob_btts_yes
                        actual_odd = row.get('BTTS_Yes', np.nan)
                        try:
                            parsed_odd = float(str(actual_odd).replace(',', '.')) if not pd.isna(actual_odd) else np.nan
                            bookie_odds = parsed_odd if parsed_odd > 1.0 else est_odds['bookie_btts_yes']
                        except Exception:
                            bookie_odds = est_odds['bookie_btts_yes']
                        bet_won = (fthg > 0 and ftag > 0)
                    elif mkt == 'btts_no':
                        model_prob = 1.0 - prob_btts_yes
                        actual_odd = row.get('BTTS_No', np.nan)
                        try:
                            parsed_odd = float(str(actual_odd).replace(',', '.')) if not pd.isna(actual_odd) else np.nan
                            bookie_odds = parsed_odd if parsed_odd > 1.0 else est_odds['bookie_btts_no']
                        except Exception:
                            bookie_odds = est_odds['bookie_btts_no']
                        bet_won = (fthg == 0 or ftag == 0)\""""

content = content.replace(old_btts_scan, new_btts_scan)

with codecs.open('C:\\Users\\Gustavo\\.gemini\\antigravity\\scratch\\football-backtester\\backend\\backtester.py', 'w', 'utf-8') as f:
    f.write(content)
print('Done!')
