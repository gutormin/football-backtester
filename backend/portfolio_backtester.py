import pandas as pd
import math
from datetime import datetime
from collections import defaultdict
from .backtester import ChronologicalBacktester
from .history_manager import load_history

def run_portfolio(strategy_ids, initial_bankroll=1000.0, risk_method='fixed_1'):
    history = load_history()
    selected_strategies = [s for s in history if s['id'] in strategy_ids]
    
    if not selected_strategies:
        return {"error": "Nenhuma estratégia válida selecionada."}
        
    all_bets = []
    
    # Run individual backtests to get raw bets
    print(f"[Portfolio] Rodando backtests individuais para {len(selected_strategies)} estratégias...")
    for s in selected_strategies:
        p = s['params']
        bt = ChronologicalBacktester()
        res = bt.run(
            leagues=p.get('leagues', []),
            start_date=p.get('startDate', p.get('start_date', '2021-01-01')),
            end_date=p.get('endDate', p.get('end_date', datetime.today().strftime('%Y-%m-%d'))),
            market=p.get('market'),
            value_threshold=p.get('valueThreshold', p.get('value_threshold', 1.05)),
            initial_bankroll=1000.0, # Dummy initial bankroll just to get raw bets
            staking_rule='fixed',
            stake_value=10.0,
            odds_source=p.get('oddsSource', p.get('odds_source', 'B365')),
            min_odds=p.get('minOdds', 1.0),
            max_odds=p.get('maxOdds', 50.0),
            data_source=p.get('data_source', 'football-data'),
            use_ml=p.get('use_ml', False),
            futpython_api_key=p.get('futpython_api_key', ''),
            min_odds_h=p.get('minOddsH'), max_odds_h=p.get('maxOddsH'),
            min_odds_d=p.get('minOddsD'), max_odds_d=p.get('maxOddsD'),
            min_odds_a=p.get('minOddsA'), max_odds_a=p.get('maxOddsA'),
            min_odds_over25=p.get('minOddsOver25'), max_odds_over25=p.get('maxOddsOver25'),
            min_odds_under25=p.get('minOddsUnder25'), max_odds_under25=p.get('maxOddsUnder25')
        )
        
        if "error" not in res and 'bets' in res:
            for b in res['bets']:
                b['strategy_id'] = s['id']
                b['strategy_name'] = s['name']
                # Calculate the raw multiplier (profit / stake)
                b['profit_factor'] = b['profit'] / b['stake'] if b['stake'] > 0 else 0
                all_bets.append(b)

    if not all_bets:
        return {"error": "Nenhuma aposta gerada pelas estratégias selecionadas."}

    # Sort all bets chronologically
    all_bets.sort(key=lambda x: x['date'])
    
    bankroll = initial_bankroll
    peak_bankroll = initial_bankroll
    max_drawdown = 0.0
    
    equity_curve = []
    current_date = all_bets[0]['date']
    day_profit = 0.0
    
    strategy_stats = {s['id']: {'name': s['name'], 'bets': 0, 'wins': 0, 'staked': 0.0, 'profit': 0.0, 'recommended_stake': 0.0, 'win_rate': 0.0, 'roi': 0.0} for s in selected_strategies}
    
    # Portfolio simulation
    for b in all_bets:
        b_date = b['date']
        
        # Save equity curve daily
        if b_date != current_date:
            equity_curve.append({'date': current_date, 'bankroll': round(bankroll, 2)})
            current_date = b_date
            
        # Calculate stake based on risk_method
        stake = 0.0
        if risk_method == 'fixed_1':
            stake = bankroll * 0.01
        elif risk_method == 'fixed_2':
            stake = bankroll * 0.02
        elif risk_method == 'kelly_quarter':
            prob = b['prob'] / 100.0
            odds = b['odds']
            if odds > 1.0:
                k_fraction = ((prob * odds) - 1) / (odds - 1)
                k_fraction = max(0.0, min(k_fraction, 0.2)) # Cap at 20% max Kelly
                stake = bankroll * (k_fraction / 4.0) # Quarter Kelly
        
        # Floor/Cap stake
        if stake < 1.0:
            stake = 1.0
        if stake > bankroll * 0.1: # Max 10% per bet
            stake = bankroll * 0.1
            
        profit = stake * b['profit_factor']
        bankroll += profit
        
        if bankroll > peak_bankroll:
            peak_bankroll = bankroll
        
        dd = (peak_bankroll - bankroll) / peak_bankroll * 100 if peak_bankroll > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd
            
        # Update strategy stats
        sid = b['strategy_id']
        strategy_stats[sid]['bets'] += 1
        strategy_stats[sid]['staked'] += stake
        strategy_stats[sid]['profit'] += profit
        if profit > 0:
            strategy_stats[sid]['wins'] += 1
            
    # Final day
    equity_curve.append({'date': current_date, 'bankroll': round(bankroll, 2)})
    
    # Calculate final stats and recommended next stakes
    for sid, st in strategy_stats.items():
        st['win_rate'] = (st['wins'] / st['bets'] * 100) if st['bets'] > 0 else 0
        st['roi'] = (st['profit'] / st['staked'] * 100) if st['staked'] > 0 else 0
        
        # Calculate recommended future stake based on final bankroll
        if risk_method == 'fixed_1':
            st['recommended_stake'] = bankroll * 0.01
        elif risk_method == 'fixed_2':
            st['recommended_stake'] = bankroll * 0.02
        elif risk_method == 'kelly_quarter':
            # Use historical win rate and avg odds for this strategy to suggest a baseline Kelly
            # We don't have exact next-match odds, so we estimate based on average
            s_bets = [b for b in all_bets if b['strategy_id'] == sid]
            avg_odds = sum(b['odds'] for b in s_bets) / len(s_bets) if s_bets else 2.0
            prob = st['win_rate'] / 100.0
            if avg_odds > 1.0:
                k_fraction = ((prob * avg_odds) - 1) / (avg_odds - 1)
                k_fraction = max(0.0, min(k_fraction, 0.2))
                st['recommended_stake'] = bankroll * (k_fraction / 4.0)
            else:
                st['recommended_stake'] = 0.0
                
    net_profit = bankroll - initial_bankroll
    total_staked = sum(st['staked'] for st in strategy_stats.values())
    total_roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
    
    return {
        "status": "success",
        "initial_bankroll": initial_bankroll,
        "final_bankroll": round(bankroll, 2),
        "net_profit": round(net_profit, 2),
        "total_roi": round(total_roi, 2),
        "max_drawdown": round(max_drawdown, 2),
        "total_bets": len(all_bets),
        "equity_curve": equity_curve,
        "strategy_breakdown": strategy_stats
    }
