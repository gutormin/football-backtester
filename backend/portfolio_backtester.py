import pandas as pd
import numpy as np
import math
import scipy.stats as stats
from datetime import datetime
from collections import defaultdict
from .backtester import ChronologicalBacktester
from .history_manager import load_history
from .ai_predictor import (predict_strategy_sustainability, compute_brier_score, 
                           compute_bootstrap_ci, compute_power_analysis, compute_rolling_roi, 
                           compute_pvalue_binomial, compute_edge_quality_score)

def run_portfolio(strategy_ids, initial_bankroll=1000.0, risk_method='fixed_1'):
    history = load_history()
    selected_strategies = [s for s in history if s['id'] in strategy_ids]
    
    if not selected_strategies:
        return {"error": "Nenhuma estratégia válida selecionada."}
        
    all_bets = []
    
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
            initial_bankroll=1000.0, 
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
        
        if "error" not in res and "bets" in res:
            for b in res['bets']:
                b['strategy_id'] = s['id']
                b['strategy_name'] = s['name']
                b['profit_factor'] = b['profit'] / b['stake'] if b['stake'] > 0 else 0
                all_bets.append(b)

    if not all_bets:
        return {"error": "Nenhuma aposta gerada pelas estratégias selecionadas."}

    all_bets.sort(key=lambda x: x['date'])
    
    bankroll = initial_bankroll
    peak_bankroll = initial_bankroll
    max_drawdown = 0.0
    max_dd_duration = 0
    current_dd_duration = 0
    
    equity_curve = []
    equity_curve_fixed = []
    equity_curve_prop = []
    equity_curve_kelly = []
    
    current_date = all_bets[0]['date']
    
    # Dummy alternative bankrolls just to feed the charts
    bankroll_f = initial_bankroll
    bankroll_p = initial_bankroll
    bankroll_k = initial_bankroll
    
    strategy_stats = {s['id']: {'name': s['name'], 'bets': 0, 'wins': 0, 'staked': 0.0, 'profit': 0.0, 'recommended_stake': 0.0, 'win_rate': 0.0, 'roi': 0.0} for s in selected_strategies}
    
    league_stats = defaultdict(lambda: {'profit': 0.0, 'bets': 0, 'wins': 0})
    monthly_stats = defaultdict(lambda: {'profit': 0.0, 'bets': 0})
    odds_stats = defaultdict(lambda: {'profit': 0.0, 'bets': 0})
    
    for b in all_bets:
        b_date = b['date']
        
        if b_date != current_date:
            equity_curve.append({'date': current_date, 'bankroll': round(bankroll, 2)})
            equity_curve_fixed.append(round(bankroll_f, 2))
            equity_curve_prop.append(round(bankroll_p, 2))
            equity_curve_kelly.append(round(bankroll_k, 2))
            current_date = b_date
            
        # Main portfolio stake
        stake = 0.0
        if risk_method == 'fixed_1': stake = bankroll * 0.01
        elif risk_method == 'fixed_2': stake = bankroll * 0.02
        elif risk_method == 'kelly_quarter':
            prob = b['prob'] / 100.0
            odds = b['odds']
            if odds > 1.0:
                k_fraction = ((prob * odds) - 1) / (odds - 1)
                k_fraction = max(0.0, min(k_fraction, 0.2))
                stake = bankroll * (k_fraction / 4.0)
        
        if stake < 1.0: stake = 1.0
        if stake > bankroll * 0.1: stake = bankroll * 0.1
            
        profit = stake * b['profit_factor']
        b['stake'] = stake
        b['profit'] = profit
        bankroll += profit
        
        # Alternative bankrolls (for charts)
        # Fixed (1% fixed)
        stake_f = 10.0 # Standard $10 fixed
        profit_f = stake_f * b['profit_factor']
        bankroll_f += profit_f
        
        # Proportional (2%)
        stake_p = bankroll_p * 0.02
        profit_p = stake_p * b['profit_factor']
        bankroll_p += profit_p
        
        # Kelly (1/4)
        prob = b['prob'] / 100.0
        odds = b['odds']
        k_fraction = 0
        if odds > 1.0:
            k_fraction = ((prob * odds) - 1) / (odds - 1)
            k_fraction = max(0.0, min(k_fraction, 0.2))
        stake_k = bankroll_k * (k_fraction / 4.0)
        profit_k = stake_k * b['profit_factor']
        bankroll_k += profit_k
        
        if bankroll > peak_bankroll:
            peak_bankroll = bankroll
            current_dd_duration = 0
        else:
            current_dd_duration += 1
            if current_dd_duration > max_dd_duration: max_dd_duration = current_dd_duration
        
        dd = (peak_bankroll - bankroll) / peak_bankroll * 100 if peak_bankroll > 0 else 0
        if dd > max_drawdown: max_drawdown = dd
            
        sid = b['strategy_id']
        strategy_stats[sid]['bets'] += 1
        strategy_stats[sid]['staked'] += stake
        strategy_stats[sid]['profit'] += profit
        if profit > 0: strategy_stats[sid]['wins'] += 1
        
        # Breakdowns
        league = b.get('league', 'Desconhecida')
        league_stats[league]['bets'] += 1
        league_stats[league]['profit'] += profit
        if profit > 0: league_stats[league]['wins'] += 1
        
        month = b_date[:7]
        monthly_stats[month]['bets'] += 1
        monthly_stats[month]['profit'] += profit
        
        odds_band = f"{math.floor(odds * 2) / 2:.1f} - {math.floor(odds * 2) / 2 + 0.5:.1f}"
        odds_stats[odds_band]['bets'] += 1
        odds_stats[odds_band]['profit'] += profit
            
    equity_curve.append({'date': current_date, 'bankroll': round(bankroll, 2)})
    equity_curve_fixed.append(round(bankroll_f, 2))
    equity_curve_prop.append(round(bankroll_p, 2))
    equity_curve_kelly.append(round(bankroll_k, 2))
    
    for sid, st in strategy_stats.items():
        st['win_rate'] = (st['wins'] / st['bets'] * 100) if st['bets'] > 0 else 0
        st['roi'] = (st['profit'] / st['staked'] * 100) if st['staked'] > 0 else 0
        if risk_method == 'fixed_1': st['recommended_stake'] = bankroll * 0.01
        elif risk_method == 'fixed_2': st['recommended_stake'] = bankroll * 0.02
        elif risk_method == 'kelly_quarter':
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
    
    wins = sum(1 for b in all_bets if b['profit'] > 0)
    profit_in_stakes = sum(b['profit_factor'] for b in all_bets)
    win_rate = (wins / len(all_bets) * 100) if all_bets else 0.0
    avg_odds = np.mean([b['odds'] for b in all_bets]) if all_bets else 0.0
    
    returns = [b['profit'] / b['stake'] for b in all_bets if b['stake'] > 0]
    avg_return = np.mean(returns) if returns else 0.0
    std_return = np.std(returns) if returns else 0.0
    sharpe_ratio = (avg_return / std_return * math.sqrt(250)) if std_return > 0 else 0.0
    downside_returns = [r for r in returns if r < 0]
    downside_std = np.std(downside_returns) if downside_returns else 0.0
    sortino_ratio = (avg_return / downside_std * math.sqrt(250)) if downside_std > 0 else 0.0
    skewness = float(stats.skew(returns)) if len(returns) > 2 else 0.0
    
    max_consec_wins, max_consec_losses = 0, 0
    curr_wins, curr_losses = 0, 0
    for b in all_bets:
        if b['profit'] > 0:
            curr_wins += 1; curr_losses = 0
            if curr_wins > max_consec_wins: max_consec_wins = curr_wins
        else:
            curr_losses += 1; curr_wins = 0
            if curr_losses > max_consec_losses: max_consec_losses = curr_losses
            
    summary = {
            'initial_bankroll': round(initial_bankroll, 2),
            'final_bankroll': round(bankroll, 2),
            'net_profit': round(net_profit, 2),
            'profit_in_stakes': round(profit_in_stakes, 2),
            'total_bets': len(all_bets),
            'wins': wins,
            'losses': len(all_bets) - wins,
            'win_rate': round(win_rate, 1),
            'roi': round(total_roi, 2),
            'max_drawdown': round(max_drawdown * 100, 2) if max_drawdown <= 1.0 else round(max_drawdown, 2),
            'max_dd_duration': max_dd_duration,
            'total_staked': round(total_staked, 2),
            'avg_odds': round(avg_odds, 2),
            'sharpe_ratio': round(sharpe_ratio, 2),
            'sortino_ratio': round(sortino_ratio, 2),
            'skewness': round(skewness, 2),
            'max_consec_wins': max_consec_wins,
            'max_consec_losses': max_consec_losses,
            'avg_clv': round(float(np.mean([b['clv'] for b in all_bets if b.get('clv') is not None])), 2) if any(b.get('clv') is not None for b in all_bets) else None,
            'bcl_percent': round(len([b for b in all_bets if b.get('clv') is not None and b['clv'] > 0]) / len([b for b in all_bets if b.get('clv') is not None]) * 100, 1) if any(b.get('clv') is not None for b in all_bets) else None
    }
    
    if len(all_bets) >= 2:
        summary['p_value'] = compute_pvalue_binomial(wins, len(all_bets), avg_odds)
        try:
            brier = compute_brier_score(all_bets)
            summary['brier_score'] = brier['brier_score']
            summary['brier_score_market'] = brier['brier_score_market']
            summary['brier_improvement'] = brier['brier_improvement']
        except: pass
        try:
            bootstrap = compute_bootstrap_ci(all_bets)
            summary['bootstrap_roi_ci_lower'] = bootstrap['bootstrap_roi_ci_lower']
            summary['bootstrap_roi_ci_upper'] = bootstrap['bootstrap_roi_ci_upper']
            summary['bootstrap_roi_median'] = bootstrap['bootstrap_roi_median']
            summary['prob_positive_roi'] = bootstrap['prob_positive_roi']
        except: pass
        try:
            power = compute_power_analysis(summary['roi'], avg_odds, len(all_bets))
            summary['min_sample_size'] = power['min_sample_size']
            summary['sample_sufficient'] = power['sample_sufficient']
            summary['power_ratio'] = power['power_ratio']
        except: pass
        try:
            rolling = compute_rolling_roi(all_bets)
            summary['rolling_roi'] = rolling['rolling_roi']
            summary['edge_decay_pct'] = rolling['edge_decay_pct']
            summary['edge_decay_alert'] = rolling['edge_decay_alert']
        except: pass
        
    oos_summary = None
    if len(all_bets) >= 20:
        n_oos = max(10, int(len(all_bets) * 0.2))
        oos_bets = all_bets[-n_oos:]
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
    
    ai_staking_rule = 'fixed'
    ai_stake_value = 10.0
    
    if risk_method == 'fixed_1':
        ai_staking_rule = 'proportional'
        ai_stake_value = 1.0
    elif risk_method == 'fixed_2':
        ai_staking_rule = 'proportional'
        ai_stake_value = 2.0
    elif risk_method == 'kelly_quarter':
        ai_staking_rule = 'kelly'
        ai_stake_value = 0.25
        
    ai_res = predict_strategy_sustainability(all_bets, initial_bankroll, 1.05, ai_staking_rule, ai_stake_value, run_monte_carlo=True)
    if isinstance(ai_res, dict):
        ai_res['score'] = eqs_data.get('score', 0)
        ai_res['breakdown'] = eqs_data.get('breakdown', [])
        ai_res['verdict'] = eqs_data.get('verdict', 'Avaliando...')
        ai_res['verdict_color'] = eqs_data.get('verdict_color', 'warning')
        ai_res['risk_recommendation'] = eqs_data.get('risk_recommendation', '')
        ai_res['oos_summary'] = oos_summary
        
    quartiles = []
    if len(all_bets) >= 4:
        chunk_size = len(all_bets) // 4
        for i in range(4):
            start_idx = i * chunk_size
            end_idx = (i + 1) * chunk_size if i < 3 else len(all_bets)
            chunk = all_bets[start_idx:end_idx]
            c_profit = sum(b['profit'] for b in chunk)
            c_staked = sum(b['stake'] for b in chunk)
            c_wins = sum(1 for b in chunk if b['profit'] > 0)
            c_win_rate = (c_wins / len(chunk) * 100) if chunk else 0.0
            c_roi = (c_profit / c_staked * 100) if c_staked > 0 else 0.0
            c_stakes = sum(b['profit_factor'] for b in chunk)
            quartiles.append({
                'profit': round(c_profit, 2),
                'stakes': round(c_stakes, 2),
                'roi': round(c_roi, 2),
                'win_rate': round(c_win_rate, 1),
                'total_bets': len(chunk)
            })
            
    summary_fixed = summary.copy()
    summary_proportional = summary.copy()
    summary_kelly = summary.copy()
    
    l_stats = [{'league': k, 'profit': round(v['profit'], 2), 'bets': v['bets'], 'win_rate': round(v['wins']/v['bets']*100,1) if v['bets']>0 else 0} for k, v in league_stats.items()]
    m_stats = [{'month': k, 'profit': round(v['profit'], 2), 'bets': v['bets']} for k, v in monthly_stats.items()]
    o_stats = [{'odds_band': k, 'profit': round(v['profit'], 2), 'bets': v['bets']} for k, v in odds_stats.items()]
    
    return {
        "status": "success",
        "initial_bankroll": initial_bankroll,
        "final_bankroll": round(bankroll, 2),
        "net_profit": round(net_profit, 2),
        "total_roi": round(total_roi, 2),
        "max_drawdown": round(max_drawdown, 2),
        "total_bets": len(all_bets),
        "equity_curve": equity_curve,
        "equity_curve_fixed": equity_curve_fixed,
        "equity_curve_proportional": equity_curve_prop,
        "equity_curve_kelly": equity_curve_kelly,
        "league_stats": l_stats,
        "monthly_stats": m_stats,
        "odds_stats": o_stats,
        "strategy_breakdown": strategy_stats,
        "summary": summary,
        "summary_fixed": summary_fixed,
        "summary_proportional": summary_proportional,
        "summary_kelly": summary_kelly,
        "ai_analysis": ai_res,
        "quartiles": quartiles,
        "bets": all_bets[-1000:]
    }

