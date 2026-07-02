import math
import numpy as np
import pandas as pd
from collections import defaultdict
from ..data_loader import get_all_available_leagues
from ..ai_predictor import (predict_strategy_sustainability, compute_brier_score, 
                            compute_bootstrap_ci, compute_power_analysis, compute_rolling_roi, 
                            compute_pvalue_binomial, compute_edge_quality_score)

def safe_mean(values):
    clean_vals = [v for v in values if pd.notna(v)]
    return float(np.mean(clean_vals)) if clean_vals else 0.0

def compile_backtest_summary(bets_record, initial_bankroll, bankroll, total_staked, staking_rule, stake_value, value_threshold,
                             run_monte_carlo, min_odds, max_odds, start_date, end_date,
                             bankroll_fixed, bankroll_proportional, bankroll_kelly,
                             staked_fixed, staked_prop, staked_kelly,
                             wins_fixed, wins_prop, wins_kelly,
                             bets_fixed, bets_prop, bets_kelly,
                             max_dd_fixed, max_dd_prop, max_dd_kelly,
                             max_dd_duration_fixed, max_dd_duration_prop, max_dd_duration_kelly,
                             equity_curve_fixed, equity_curve_proportional, equity_curve_kelly,
                             max_drawdown,
                             oos_split_pct=20.0,
                             slippage_pct=0.0):
    total_bets = len(bets_record)
    wins = sum(1 for b in bets_record if b['profit'] > 0)
    win_rate = (wins / total_bets * 100) if total_bets > 0 else 0.0
    net_profit = bankroll - initial_bankroll
    yield_roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
    profit_in_stakes = sum(b['profit'] / b['stake'] for b in bets_record) if bets_record else 0.0

    # Calculate advanced financial metrics
    daily_profits = defaultdict(float)
    for b in bets_record:
        daily_profits[b['date']] += b['profit']
        
    daily_returns = [profit / initial_bankroll for date, profit in daily_profits.items()]
    
    sharpe_ratio = 0.0
    sortino_ratio = 0.0
    skewness = 0.0
    
    if len(daily_returns) > 1:
        mean_ret = np.mean(daily_returns)
        std_ret = np.std(daily_returns)
        
        if std_ret > 0:
            sharpe_ratio = float((mean_ret / std_ret) * math.sqrt(252))
            
        downside_returns = [r for r in daily_returns if r < 0]
        if downside_returns:
            downside_std = np.std(downside_returns)
            if downside_std > 0:
                sortino_ratio = float((mean_ret / downside_std) * math.sqrt(252))
        else:
            sortino_ratio = sharpe_ratio
            
        if std_ret > 0:
            skewness = float(np.mean((np.array(daily_returns) - mean_ret)**3) / (std_ret**3))
            
    # Consecutive wins / losses runs
    max_consec_wins = 0
    max_consec_losses = 0
    current_wins = 0
    current_losses = 0
    
    for b in bets_record:
        if b['profit'] > 0:
            current_wins += 1
            max_consec_wins = max(max_consec_wins, current_wins)
            current_losses = 0
        elif b['profit'] < 0:
            current_losses += 1
            max_consec_losses = max(max_consec_losses, current_losses)
            current_wins = 0

    # Markowitz Portfolio Monte Carlo Optimization
    portfolio_opt = None
    unique_bets_markets = list(set(b['market'] for b in bets_record))
    if len(unique_bets_markets) > 1 and len(bets_record) >= 10:
        try:
            unique_dates_list = list(set(b['date'] for b in bets_record))
            unique_dates_list.sort()
            
            market_indices = {mkt: i for i, mkt in enumerate(unique_bets_markets)}
            date_indices = {dt: i for i, dt in enumerate(unique_dates_list)}
            
            R = np.zeros((len(unique_dates_list), len(unique_bets_markets)))
            for b in bets_record:
                r_idx = date_indices[b['date']]
                c_idx = market_indices[b['market']]
                R[r_idx, c_idx] += b['profit'] / initial_bankroll
                
            mean_returns = np.mean(R, axis=0)
            cov_matrix = np.atleast_2d(np.cov(R, rowvar=False))
            
            best_sharpe = -999.0
            best_weights = None
            
            np.random.seed(42)
            for _ in range(1000):
                w = np.random.random(len(unique_bets_markets))
                w /= np.sum(w)
                
                p_ret = np.sum(mean_returns * w)
                p_var = np.dot(w.T, np.dot(cov_matrix, w))
                p_std = math.sqrt(p_var) if p_var > 0 else 0.0
                
                p_sharpe = p_ret / p_std if p_std > 0 else 0.0
                if p_sharpe > best_sharpe:
                    best_sharpe = p_sharpe
                    best_weights = w
                    
            if best_weights is not None:
                portfolio_opt = {
                    'weights': {unique_bets_markets[i]: round(float(best_weights[i]), 3) for i in range(len(unique_bets_markets))},
                    'expected_return_pct': round(float(np.sum(mean_returns * best_weights) * 100), 2),
                    'volatility_pct': round(float(math.sqrt(np.dot(best_weights.T, np.dot(cov_matrix, best_weights))) * 100), 2)
                }
        except Exception as e:
            print(f"[Markowitz Error] {e}")
    
    # Group by league for performance breakdowns
    league_performance = defaultdict(float)
    league_bets = defaultdict(int)
    for b in bets_record:
        league_performance[b['league']] += b['profit']
        league_bets[b['league']] += 1
        
    # Resolve league names dynamically
    all_leagues = get_all_available_leagues()
    code_to_name = {l['code']: l['name'] for l in all_leagues}

    league_stats = []
    for l_code, l_profit in league_performance.items():
        l_name = code_to_name.get(l_code, l_code)
        l_bets = league_bets[l_code]
        league_stats.append({
            'code': l_code,
            'name': l_name,
            'bets': l_bets,
            'profit': round(l_profit, 2)
        })

    # Group by odds range
    odds_ranges = {
        'super_fav': {'name': 'Super Favs (<=1.50)', 'profit': 0.0, 'bets': 0},
        'fav': {'name': 'Favs (1.50-2.00)', 'profit': 0.0, 'bets': 0},
        'med': {'name': 'Med (2.00-3.00)', 'profit': 0.0, 'bets': 0},
        'dog': {'name': 'Zebras (>3.00)', 'profit': 0.0, 'bets': 0}
    }
    
    # Group by month
    monthly_data = defaultdict(lambda: {'profit': 0.0, 'bets': 0})
    
    for b in bets_record:
        odd = b['odds']
        if odd <= 1.50:
            key = 'super_fav'
        elif odd <= 2.00:
            key = 'fav'
        elif odd <= 3.00:
            key = 'med'
        else:
            key = 'dog'
        odds_ranges[key]['profit'] += b['profit']
        odds_ranges[key]['bets'] += 1
        
        month_key = b['date'][:7]
        monthly_data[month_key]['profit'] += b['profit']
        monthly_data[month_key]['bets'] += 1
        
    odds_stats = []
    for key, val in odds_ranges.items():
        odds_stats.append({
            'range': val['name'],
            'profit': round(val['profit'], 2),
            'bets': val['bets']
        })
        
    monthly_stats = []
    for m_key in sorted(monthly_data.keys()):
        monthly_stats.append({
            'month': m_key,
            'profit': round(monthly_data[m_key]['profit'], 2),
            'bets': monthly_data[m_key]['bets']
        })
        
    # Group by month for equity curve charting
    equity_curve = []
    if bets_record:
        equity_curve.append({'date': start_date, 'bankroll': round(initial_bankroll, 2)})
        for b in bets_record:
            equity_curve.append({'date': b['date'], 'bankroll': b['bankroll']})
    else:
        equity_curve.append({'date': start_date, 'bankroll': round(initial_bankroll, 2)})
        equity_curve.append({'date': end_date, 'bankroll': round(initial_bankroll, 2)})
        
    # Compute AI sustainability analysis
    ai_res = predict_strategy_sustainability(bets_record, initial_bankroll, value_threshold, staking_rule, stake_value, run_monte_carlo=run_monte_carlo, min_odds=min_odds, max_odds=max_odds)
    
    # Calculate quartiles (4 chronological blocks of 25% of bets)
    quartiles = []
    if total_bets >= 4:
        chunk_size = total_bets // 4
        for i in range(4):
            start_idx = i * chunk_size
            end_idx = (i + 1) * chunk_size if i < 3 else total_bets
            
            chunk = bets_record[start_idx:end_idx]
            c_profit = sum(b['profit'] for b in chunk)
            c_staked = sum(b['stake'] for b in chunk)
            c_wins = sum(1 for b in chunk if b['profit'] > 0)
            
            c_win_rate = (c_wins / len(chunk) * 100) if chunk else 0.0
            c_roi = (c_profit / c_staked * 100) if c_staked > 0 else 0.0
            c_stakes = sum(b['profit'] / b['stake'] for b in chunk) if chunk else 0.0
            
            quartiles.append({
                'profit': round(c_profit, 2),
                'stakes': round(c_stakes, 2),
                'roi': round(c_roi, 2),
                'win_rate': round(c_win_rate, 1),
                'total_bets': len(chunk)
            })
    else:
        for _ in range(4):
            quartiles.append({
                'profit': 0.0,
                'stakes': 0.0,
                'roi': 0.0,
                'win_rate': 0.0,
                'total_bets': 0
            })
    
    summary_fixed = {
        'final_bankroll': round(bankroll_fixed, 2),
        'net_profit': round(bankroll_fixed - initial_bankroll, 2),
        'total_bets': bets_fixed,
        'win_rate': round((wins_fixed / bets_fixed * 100) if bets_fixed > 0 else 0.0, 1),
        'roi': round(((bankroll_fixed - initial_bankroll) / staked_fixed * 100) if staked_fixed > 0 else 0.0, 2),
        'max_drawdown': round(max_dd_fixed * 100, 2),
        'max_dd_duration': max_dd_duration_fixed
    }
    
    summary_proportional = {
        'final_bankroll': round(bankroll_proportional, 2),
        'net_profit': round(bankroll_proportional - initial_bankroll, 2),
        'total_bets': bets_prop,
        'win_rate': round((wins_prop / bets_prop * 100) if bets_prop > 0 else 0.0, 1),
        'roi': round(((bankroll_proportional - initial_bankroll) / staked_prop * 100) if staked_prop > 0 else 0.0, 2),
        'max_drawdown': round(max_dd_prop * 100, 2),
        'max_dd_duration': max_dd_duration_prop
    }
    
    summary_kelly = {
        'final_bankroll': round(bankroll_kelly, 2),
        'net_profit': round(bankroll_kelly - initial_bankroll, 2),
        'total_bets': bets_kelly,
        'win_rate': round((wins_kelly / bets_kelly * 100) if bets_kelly > 0 else 0.0, 1),
        'roi': round(((bankroll_kelly - initial_bankroll) / staked_kelly * 100) if staked_kelly > 0 else 0.0, 2),
        'max_drawdown': round(max_dd_kelly * 100, 2),
        'max_dd_duration': max_dd_duration_kelly
    }
    
    summary = {
        'initial_bankroll': round(initial_bankroll, 2),
        'final_bankroll': round(bankroll, 2),
        'net_profit': round(net_profit, 2),
        'profit_in_stakes': round(profit_in_stakes, 2),
        'total_bets': total_bets,
        'wins': wins,
        'losses': total_bets - wins,
        'win_rate': round(win_rate, 1),
        'roi': round(yield_roi, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'max_dd_duration': max_dd_duration_fixed if staking_rule == 'fixed' else (max_dd_duration_prop if staking_rule == 'proportional' else max_dd_duration_kelly),
        'total_staked': round(total_staked, 2),
        'avg_odds': round(safe_mean([b['odds'] for b in bets_record]), 2),
        'sharpe_ratio': round(sharpe_ratio, 2),
        'sortino_ratio': round(sortino_ratio, 2),
        'skewness': round(skewness, 2),
        'max_consec_wins': max_consec_wins,
        'max_consec_losses': max_consec_losses,
        'avg_clv': round(safe_mean([b['clv'] for b in bets_record if b.get('clv') is not None]), 2) if any(pd.notna(b.get('clv')) for b in bets_record) else None,
        'bcl_percent': round(len([b for b in bets_record if b.get('clv') is not None and pd.notna(b['clv']) and b['clv'] > 0]) / len([b for b in bets_record if b.get('clv') is not None and pd.notna(b['clv'])]) * 100, 1) if any(pd.notna(b.get('clv')) for b in bets_record) else None
    }

    if bets_record and total_bets >= 2:
        avg_odds = summary['avg_odds']
        summary['p_value'] = compute_pvalue_binomial(wins, total_bets, avg_odds)
        try:
            brier = compute_brier_score(bets_record)
            summary['brier_score'] = brier['brier_score']
            summary['brier_score_market'] = brier['brier_score_market']
            summary['brier_improvement'] = brier['brier_improvement']
        except Exception:
            summary['brier_score'] = None
            summary['brier_score_market'] = None
            summary['brier_improvement'] = None

        try:
            bootstrap = compute_bootstrap_ci(bets_record)
            summary['bootstrap_roi_ci_lower'] = bootstrap['bootstrap_roi_ci_lower']
            summary['bootstrap_roi_ci_upper'] = bootstrap['bootstrap_roi_ci_upper']
            summary['bootstrap_roi_median'] = bootstrap['bootstrap_roi_median']
            summary['prob_positive_roi'] = bootstrap['prob_positive_roi']
        except Exception:
            summary['bootstrap_roi_ci_lower'] = None
            summary['bootstrap_roi_ci_upper'] = None
            summary['bootstrap_roi_median'] = None
            summary['prob_positive_roi'] = None

        try:
            power = compute_power_analysis(summary['roi'], summary.get('avg_odds', 2.0), summary['total_bets'])
            summary['min_sample_size'] = power['min_sample_size']
            summary['sample_sufficient'] = power['sample_sufficient']
            summary['power_ratio'] = power['power_ratio']
        except Exception:
            summary['min_sample_size'] = None
            summary['sample_sufficient'] = None
            summary['power_ratio'] = None

        try:
            rolling = compute_rolling_roi(bets_record)
            summary['rolling_roi'] = rolling['rolling_roi']
            summary['edge_decay_pct'] = rolling['edge_decay_pct']
            summary['edge_decay_alert'] = rolling['edge_decay_alert']
        except Exception:
            summary['rolling_roi'] = []
            summary['edge_decay_pct'] = None
            summary['edge_decay_alert'] = None

    # EQS Score Dinamicamente
    oos_summary = None
    if len(bets_record) >= 20 and oos_split_pct > 0:
        n_oos = max(10, int(len(bets_record) * (oos_split_pct / 100.0)))
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

    # OOS Robustness Matrix (Stress Test)
    oos_robustness_matrix = []
    if len(bets_record) >= 20:
        for split in [15, 20, 30, 40]:
            n_split = max(10, int(len(bets_record) * (split / 100.0)))
            split_bets = bets_record[-n_split:]
            split_staked = sum([b['stake'] for b in split_bets])
            split_profit = sum([b['profit'] for b in split_bets])
            split_roi = (split_profit / split_staked * 100) if split_staked > 0 else 0.0
            split_wins = sum([1 for b in split_bets if b['profit'] > 0])
            split_win_rate = (split_wins / len(split_bets) * 100) if split_bets else 0.0
            oos_robustness_matrix.append({
                'split_pct': split,
                'total_bets': len(split_bets),
                'net_profit': round(split_profit, 2),
                'roi': round(split_roi, 2),
                'win_rate': round(split_win_rate, 1)
            })

    # Slippage Sensitivity Report (Stress Test)
    def calc_degraded_roi(bets, extra_slippage_pct):
        factor = 1.0 - (extra_slippage_pct / 100.0)
        total_staked = 0.0
        total_profit = 0.0
        for b in bets:
            stake = b['stake']
            profit = b['profit']
            total_staked += stake
            if profit > 0:
                total_profit += profit * factor
            else:
                total_profit += profit
        return (total_profit / total_staked * 100.0) if total_staked > 0 else 0.0

    slippage_sensitivity = []
    if bets_record:
        for extra in [0, 1, 3, 5]:
            simulated_roi = calc_degraded_roi(bets_record, extra)
            slippage_sensitivity.append({
                'extra_slippage_pct': extra,
                'roi': round(simulated_roi, 2)
            })

    summary['slippage_applied'] = slippage_pct > 0
    summary['slippage_pct'] = slippage_pct
    summary['oos_split_pct'] = oos_split_pct
    summary['oos_robustness_matrix'] = oos_robustness_matrix
    summary['slippage_sensitivity'] = slippage_sensitivity
    
    eqs_data = compute_edge_quality_score(summary, oos_summary)
    
    if isinstance(ai_res, dict):
        ai_res['score'] = eqs_data.get('score', 0)
        ai_res['breakdown'] = eqs_data.get('breakdown', [])
        ai_res['verdict'] = eqs_data.get('verdict', 'Avaliando...')
        ai_res['verdict_color'] = eqs_data.get('verdict_color', 'warning')
        ai_res['risk_recommendation'] = eqs_data.get('risk_recommendation', '')
        ai_res['oos_summary'] = oos_summary

    return {
        'summary': summary,
        'summary_fixed': summary_fixed,
        'summary_proportional': summary_proportional,
        'summary_kelly': summary_kelly,
        'league_stats': league_stats,
        'odds_stats': odds_stats,
        'monthly_stats': monthly_stats,
        'equity_curve': equity_curve,
        'equity_curve_fixed': equity_curve_fixed,
        'equity_curve_proportional': equity_curve_proportional,
        'equity_curve_kelly': equity_curve_kelly,
        'bets': bets_record,
        'ai_analysis': ai_res,
        'quartiles': quartiles,
        'portfolio_optimization': portfolio_opt
    }

def compile_parallel_scan_summary(states, initial_bankroll, value_threshold, staking_rule, stake_value):
    summaries = {}
    for key, state in states.items():
        net_profit = state['bankroll'] - initial_bankroll
        roi = (net_profit / state['total_staked'] * 100) if state['total_staked'] > 0 else 0.0
        win_rate = (state['wins'] / state['total_bets'] * 100) if state['total_bets'] > 0 else 0.0
        
        # Compute AI score if we have enough bets
        ai_score = 0.0
        if len(state['bets_for_ai']) >= 20:
            try:
                ai_res = predict_strategy_sustainability(
                    state['bets_for_ai'],
                    initial_bankroll=initial_bankroll,
                    value_threshold=value_threshold,
                    staking_rule=staking_rule,
                    stake_value=stake_value,
                    run_monte_carlo=False
                )
                ai_score = ai_res.get('ml_probability', 0.0)
            except Exception as e:
                print(f"Error computing AI score for {key}: {e}")
                
        # Calcular p-value para significância estatística
        avg_odds = 2.0
        avg_expected_value = 0.0
        if state['bets_for_ai']:
            avg_odds = float(np.mean([float(b['odds']) for b in state['bets_for_ai']]))
            avg_expected_value = float(np.mean([float(b.get('ev', 1.0)) for b in state['bets_for_ai']]))
        p_value = compute_pvalue_binomial(state['wins'], state['total_bets'], avg_odds)

        # --- Out-of-Sample (OOS) Summary for EQS ---
        oos_summary = None
        if len(state['bets_for_ai']) >= 20:
            n_oos = max(10, int(len(state['bets_for_ai']) * 0.2))
            oos_bets = state['bets_for_ai'][-n_oos:]
            
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

        # Simular o max_drawdown (simplificado)
        max_drawdown = 0.0
        peak = initial_bankroll
        current_bank = initial_bankroll
        for b in state['bets_for_ai']:
            current_bank += b['profit']
            if current_bank > peak:
                peak = current_bank
            dd = (peak - current_bank) / peak if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd
                
        # --- Advanced Metrics for EQS ---
        brier_improvement = None
        power_ratio = None
        bootstrap_roi_ci_lower = None
        edge_decay_pct = None

        if len(state['bets_for_ai']) >= 20:
            power_res = compute_power_analysis(roi, avg_odds, state['total_bets'])
            power_ratio = power_res.get('power_ratio')

            brier_res = compute_brier_score(state['bets_for_ai'])
            brier_improvement = brier_res.get('improvement_pct')

            boot_res = compute_bootstrap_ci(state['bets_for_ai'], n_resamples=100)
            bootstrap_roi_ci_lower = boot_res.get('bootstrap_roi_ci_lower')

            window = max(10, min(100, int(len(state['bets_for_ai']) * 0.2)))
            roll_res = compute_rolling_roi(state['bets_for_ai'], window=window)
            edge_decay_pct = roll_res.get('edge_decay_pct')
            
        valid_clvs = [b.get('clv') for b in state['bets_for_ai'] if b.get('clv') is not None]
        avg_clv = float(np.mean(valid_clvs)) if valid_clvs else None
        bcl_percent = round(len([clv for clv in valid_clvs if clv > 0]) / len(valid_clvs) * 100, 1) if valid_clvs else None

        summaries[key] = {
            'net_profit': round(net_profit, 2),
            'roi': round(roi, 2),
            'win_rate': round(win_rate, 1),
            'total_bets': state['total_bets'],
            'ai_score': ai_score,
            'p_value': p_value,
            'avg_odds': round(avg_odds, 2),
            'avg_expected_value': round(avg_expected_value, 3),
            'max_drawdown': round(max_drawdown * 100, 2),
            'oos_summary': oos_summary,
            'power_ratio': power_ratio,
            'brier_improvement': brier_improvement,
            'bootstrap_roi_ci_lower': bootstrap_roi_ci_lower,
            'edge_decay_pct': edge_decay_pct,
            'avg_clv': round(avg_clv, 2) if avg_clv is not None else None,
            'bcl_percent': bcl_percent
        }
        
        # --- Nível 2: Otimização de Faixa de Odds ---
        base_summary = summaries[key]
        base_eqs_data = compute_edge_quality_score(base_summary, oos_summary)
        base_eqs_score = base_eqs_data.get('score', 0)
        
        best_opt_score = base_eqs_score
        best_opt_range = None
        
        if len(state['bets_for_ai']) >= 30:
            odds_slices = {
                'Qualquer Odd': lambda b: True,
                'Super Favoritos (<= 1.50)': lambda b: b['odds'] <= 1.50,
                'Favoritos (1.50 - 2.00)': lambda b: 1.50 < b['odds'] <= 2.00,
                'Odds Médias (2.00 - 3.00)': lambda b: 2.00 < b['odds'] <= 3.00,
                'Zebras (> 3.00)': lambda b: b['odds'] > 3.00,
                'Excluir Zebras (<= 3.00)': lambda b: b['odds'] <= 3.00,
                'Excluir Super Favs (> 1.50)': lambda b: b['odds'] > 1.50
            }
            
            ev_slices = {
                '': lambda b: True,
                ' + Gatilho EV > 1.05': lambda b: b.get('ev', 1.0) > 1.05,
                ' + Gatilho EV > 1.10': lambda b: b.get('ev', 1.0) > 1.10,
                ' + Gatilho EV > 1.15': lambda b: b.get('ev', 1.0) > 1.15,
                ' + Gatilho EV > 1.25': lambda b: b.get('ev', 1.0) > 1.25
            }
            
            slices = {}
            for o_name, o_func in odds_slices.items():
                for e_name, e_func in ev_slices.items():
                    if o_name == 'Qualquer Odd' and e_name == '':
                        continue
                    name = o_name + e_name
                    slices[name] = lambda b, o=o_func, e=e_func: o(b) and e(b)
            
            for s_name, s_func in slices.items():
                s_bets = [b for b in state['bets_for_ai'] if s_func(b)]
                if len(s_bets) >= 20:
                    s_staked = sum([b['stake'] for b in s_bets])
                    s_profit = sum([b['profit'] for b in s_bets])
                    s_roi = (s_profit / s_staked * 100) if s_staked > 0 else 0.0
                    
                    if s_roi > 0 and s_roi > base_summary['roi'] + 2.0:
                        s_wins = sum([1 for b in s_bets if b['profit'] > 0])
                        s_avg_odds = float(np.mean([b['odds'] for b in s_bets]))
                        s_avg_ev = float(np.mean([b.get('ev', 1.0) for b in s_bets]))
                        
                        s_oos_summary = None
                        n_oos = max(10, int(len(s_bets) * 0.2))
                        s_oos_bets = s_bets[-n_oos:]
                        s_oos_staked = sum([b['stake'] for b in s_oos_bets])
                        s_oos_profit = sum([b['profit'] for b in s_oos_bets])
                        if s_oos_staked > 0:
                            s_oos_roi = (s_oos_profit / s_oos_staked * 100)
                            s_oos_wins = sum([1 for b in s_oos_bets if b['profit'] > 0])
                            s_oos_summary = {
                                'roi': round(s_oos_roi, 2),
                                'win_rate': round((s_oos_wins / len(s_oos_bets) * 100), 1)
                            }
                            
                        s_p_value = compute_pvalue_binomial(s_wins, len(s_bets), s_avg_odds)
                        s_power = compute_power_analysis(s_roi, s_avg_odds, len(s_bets)).get('power_ratio')
                        s_brier = compute_brier_score(s_bets).get('improvement_pct')
                        s_boot = compute_bootstrap_ci(s_bets, n_resamples=100).get('bootstrap_roi_ci_lower')
                        s_decay = compute_rolling_roi(s_bets, window=max(10, int(len(s_bets)*0.2))).get('edge_decay_pct')
                        
                        s_valid_clvs = [b.get('clv') for b in s_bets if b.get('clv') is not None]
                        s_avg_clv = float(np.mean(s_valid_clvs)) if s_valid_clvs else None
                        
                        s_summary = {
                            'roi': s_roi,
                            'bootstrap_roi_ci_lower': s_boot,
                            'avg_clv': s_avg_clv,
                            'edge_decay_pct': s_decay,
                            'p_value': s_p_value,
                            'power_ratio': s_power,
                            'brier_improvement': s_brier
                        }
                        
                        s_eqs_data = compute_edge_quality_score(s_summary, s_oos_summary)
                        s_eqs_score = s_eqs_data.get('score', 0)
                        
                        if s_eqs_score > best_opt_score and s_eqs_score >= 60:
                            best_opt_score = s_eqs_score
                            best_opt_range = s_name

        if best_opt_range and best_opt_score >= base_eqs_score + 5:
            summaries[key]['optimized_odds_range'] = best_opt_range
            summaries[key]['optimized_eqs_score'] = best_opt_score

    return summaries
