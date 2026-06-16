import re

with open('backend/backtester.py', 'r', encoding='utf-8') as f:
    code = f.read()

search_str = """
        return {
            'summary': summary,
"""

replace_str = """
        # --- Computar EQS Score Dinamicamente ---
        oos_summary = None
        if len(bets_record) >= 20:
            n_oos = max(10, int(len(bets_record) * 0.2))
            oos_bets = bets_record[-n_oos:]
            oos_staked = sum([b['stake'] for b in oos_bets])
            oos_profit = sum([b['profit'] for b in oos_bets])
            oos_roi = (oos_profit / oos_staked * 100) if oos_staked > 0 else 0.0
            oos_wins = sum([1 for b in oos_bets if b['profit'] > 0])
            oos_win_rate = (oos_wins / len(oos_bets) * 100) if oos_bets else 0.0
            oos_summary = {
                'net_profit': round(oos_profit, 2),
                'roi': round(oos_roi, 2),
                'win_rate': round(oos_win_rate, 1),
                'total_bets': len(oos_bets)
            }
        
        eqs_data = compute_edge_quality_score(summary, oos_summary)
        
        if isinstance(ai_res, dict):
            ai_res['score'] = eqs_data.get('score', 0)
            ai_res['breakdown'] = eqs_data.get('details', [])
            score_val = ai_res['score']
            if score_val >= 75:
                ai_res['verdict'] = 'Aprovado'
                ai_res['verdict_color'] = 'success'
            elif score_val >= 50:
                ai_res['verdict'] = 'Atenção'
                ai_res['verdict_color'] = 'warning'
            else:
                ai_res['verdict'] = 'Reprovado'
                ai_res['verdict_color'] = 'danger'

        return {
            'summary': summary,
"""

if search_str in code:
    code = code.replace(search_str, replace_str)
    with open('backend/backtester.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print("Patched successfully!")
else:
    print("Could not find search string in backtester.py!")
