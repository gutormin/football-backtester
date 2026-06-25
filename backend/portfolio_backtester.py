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


def _get_stake(risk_method, initial_bankroll, current_bankroll, prob, odds):
    """
    Calculate stake for a bet.

    For the HISTORICAL simulation, we use the initial_bankroll as the base
    for proportional/Kelly calculations to prevent compounding explosion.
    The current_bankroll is only used to ensure we don't bet more than available.

    This gives realistic results while still showing meaningful differences
    between risk methods.
    """
    if risk_method.startswith('fixed_'):
        try:
            pct = float(risk_method.split('_')[1])
        except:
            pct = 1.0
        stake = initial_bankroll * (pct / 100.0)
    elif risk_method == 'kelly_quarter':
        # Kelly fraction calculated per-bet using prob/odds, but applied to initial_bankroll
        # This shows realistic per-bet Kelly stakes without compounding explosion
        if odds > 1.0:
            k_fraction = ((prob * odds) - 1.0) / (odds - 1.0)
            k_fraction = max(0.0, min(k_fraction, 0.20))   # cap at 20% full Kelly
            stake = initial_bankroll * (k_fraction / 4.0)  # Quarter-Kelly on initial
        else:
            stake = initial_bankroll * 0.01
    else:
        stake = initial_bankroll * 0.01

    # Minimum $1, maximum 10% of current available bankroll
    stake = max(1.0, stake)
    stake = min(stake, current_bankroll * 0.10)
    return stake


def run_portfolio(strategy_ids, initial_bankroll=1000.0, risk_method='fixed_1'):
    """
    Runs a combined portfolio backtest across multiple saved strategies.

    HOW IT WORKS:
    - Historical simulation: stakes are calculated using your chosen risk method
      applied to your INITIAL bankroll (not compounding). This shows realistic
      P/L without exponential distortion.
      Example: $1000 bankroll, 2% fixed => every bet = $20.
      Example: $1000 bankroll, Kelly 1/4 => each bet = Kelly_fraction × $250.
    - 'Apostar' column: recommended stake for your NEXT real bet, using Kelly
      applied to the current (post-simulation) bankroll.
    """
    history = load_history()
    selected_strategies = [s for s in history if s['id'] in strategy_ids]

    if not selected_strategies:
        return {"error": "Nenhuma estratégia válida selecionada."}

    if len(selected_strategies) > 4:
        return {"error": "Servidor gratuito excedido! Selecione no máximo 4 estratégias para rodar o portfólio sem travar a memória."}

    all_bets = []

    print(f"[Portfolio] Rodando backtests individuais para {len(selected_strategies)} estratégias...")
    
    for s in selected_strategies:
        try:
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
                min_odds=p.get('minOdds', p.get('min_odds', 1.0)),
                max_odds=p.get('maxOdds', p.get('max_odds', 50.0)),
                data_source=p.get('data_source', 'football-data'),
                use_ml=p.get('use_ml', False),
                futpython_api_key=p.get('futpython_api_key', ''),
                min_odds_h=p.get('minOddsH', p.get('min_odds_h')), max_odds_h=p.get('maxOddsH', p.get('max_odds_h')),
                min_odds_d=p.get('minOddsD', p.get('min_odds_d')), max_odds_d=p.get('maxOddsD', p.get('max_odds_d')),
                min_odds_a=p.get('minOddsA', p.get('min_odds_a')), max_odds_a=p.get('maxOddsA', p.get('max_odds_a')),
                min_odds_over25=p.get('minOddsOver25', p.get('min_odds_over25')), max_odds_over25=p.get('maxOddsOver25', p.get('max_odds_over25')),
                min_odds_under25=p.get('minOddsUnder25', p.get('min_odds_under25')), max_odds_under25=p.get('maxOddsUnder25', p.get('max_odds_under25'))
            )
            if "error" not in res and "bets" in res:
                for b in res['bets']:
                    b['strategy_id'] = s['id']
                    b['strategy_name'] = s['name']
                    all_bets.append(b)
        except Exception as e:
            print(f"Error processing strategy {s['id']}: {e}")
            continue

    if not all_bets:
        return {"error": "Nenhuma aposta gerada pelas estratégias selecionadas."}

    all_bets.sort(key=lambda x: x['date'])

    # ---------------------------------------------------------------
    # HISTORICAL SIMULATION
    # Stakes use chosen risk method applied to INITIAL bankroll.
    # This is realistic: Kelly/proportional differences ARE visible,
    # but the base never explodes because it's always anchored to initial_bankroll.
    # ---------------------------------------------------------------
    bankroll = initial_bankroll
    peak_bankroll = initial_bankroll
    max_drawdown = 0.0
    max_dd_duration = 0
    current_dd_duration = 0

    equity_curve = []
    current_date = all_bets[0]['date']

    strategy_stats = {
        s['id']: {
            'name': s['name'],
            'bets': 0,
            'wins': 0,
            'staked': 0.0,
            'profit': 0.0,
            'recommended_stake': 0.0,
            'win_rate': 0.0,
            'roi': 0.0
        } for s in selected_strategies
    }

    league_stats = defaultdict(lambda: {'profit': 0.0, 'bets': 0, 'wins': 0})
    monthly_stats = defaultdict(lambda: {'profit': 0.0, 'bets': 0})
    odds_stats = defaultdict(lambda: {'profit': 0.0, 'bets': 0})

    for b in all_bets:
        b_date = b['date']

        if b_date != current_date:
            equity_curve.append({'date': current_date, 'bankroll': round(bankroll, 2)})
            current_date = b_date

        bet_odds = float(b.get('odds', 2.0))
        prob = float(b.get('prob', 50.0)) / 100.0
        bet_won = bool(b.get('won', False))

        # Stake uses initial_bankroll as base to prevent compounding explosion
        stake = _get_stake(risk_method, initial_bankroll, bankroll, prob, bet_odds)

        if bankroll < stake or bankroll < 1.0:
            b['stake'] = 0.0
            b['profit'] = 0.0
            continue

        # Correct profit calculation: outcome × odds
        if bet_won:
            profit = stake * (bet_odds - 1.0)
        else:
            profit = -stake

        b['stake'] = round(stake, 2)
        b['profit'] = round(profit, 2)
        b['bankroll'] = round(bankroll + profit, 2)
        bankroll += profit

        # Drawdown
        if bankroll > peak_bankroll:
            peak_bankroll = bankroll
            current_dd_duration = 0
        else:
            current_dd_duration += 1
            if current_dd_duration > max_dd_duration:
                max_dd_duration = current_dd_duration

        dd = (peak_bankroll - bankroll) / peak_bankroll * 100 if peak_bankroll > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

        # Strategy stats
        sid = b['strategy_id']
        strategy_stats[sid]['bets'] += 1
        strategy_stats[sid]['staked'] += stake
        strategy_stats[sid]['profit'] += profit
        if bet_won:
            strategy_stats[sid]['wins'] += 1

        # Breakdowns
        league = b.get('league', 'Desconhecida')
        league_stats[league]['bets'] += 1
        league_stats[league]['profit'] += profit
        if bet_won:
            league_stats[league]['wins'] += 1

        month = b_date[:7]
        monthly_stats[month]['bets'] += 1
        monthly_stats[month]['profit'] += profit

        odds_band = f"{math.floor(bet_odds * 2) / 2:.1f} - {math.floor(bet_odds * 2) / 2 + 0.5:.1f}"
        odds_stats[odds_band]['bets'] += 1
        odds_stats[odds_band]['profit'] += profit

    equity_curve.append({'date': current_date, 'bankroll': round(bankroll, 2)})

    # ---------------------------------------------------------------
    # RECOMMENDED STAKE ('Apostar' column)
    # This IS the forward-looking Kelly / proportional recommendation.
    # Applied to the CURRENT portfolio bankroll (after simulation).
    # This is what the user should actually bet NOW.
    # ---------------------------------------------------------------
    for sid, st in strategy_stats.items():
        st['win_rate'] = round((st['wins'] / st['bets'] * 100) if st['bets'] > 0 else 0, 1)
        st['roi'] = round((st['profit'] / st['staked'] * 100) if st['staked'] > 0 else 0, 2)

        s_bets_for_kelly = [b for b in all_bets if b.get('strategy_id') == sid]
        avg_odds_s = sum(b['odds'] for b in s_bets_for_kelly) / len(s_bets_for_kelly) if s_bets_for_kelly else 2.0
        prob_s = st['win_rate'] / 100.0

        if risk_method.startswith('fixed_'):
            try:
                pct = float(risk_method.split('_')[1])
            except:
                pct = 1.0
            st['recommended_stake'] = round(initial_bankroll * (pct / 100.0), 2)
        elif risk_method == 'kelly_quarter':
            if avg_odds_s > 1.0:
                k_fraction = ((prob_s * avg_odds_s) - 1) / (avg_odds_s - 1)
                k_fraction = max(0.0, min(k_fraction, 0.20))
                st['recommended_stake'] = round(initial_bankroll * (k_fraction / 4.0), 2)
            else:
                st['recommended_stake'] = 0.0

    # ---------------------------------------------------------------
    # PORTFOLIO KELLY NORMALIZATION
    # The Kelly criterion assumes sequential bets on a single bankroll.
    # When multiple strategies fire simultaneously, the total exposure can
    # exceed the bankroll. We cap total exposure at MAX_PORTFOLIO_EXPOSURE
    # and scale all stakes down proportionally, preserving relative sizing.
    #
    # Example: 8 strategies recommend $150 each = $1200 on $1000 bankroll.
    # With cap at 20% = $200 total → each strategy gets scaled to ~$25.
    # ---------------------------------------------------------------
    MAX_PORTFOLIO_EXPOSURE = 0.20  # Never risk more than 20% of bankroll across all simultaneous bets

    total_recommended = sum(st['recommended_stake'] for st in strategy_stats.values())
    max_allowed_total = initial_bankroll * MAX_PORTFOLIO_EXPOSURE

    if total_recommended > max_allowed_total and total_recommended > 0:
        scale_factor = max_allowed_total / total_recommended
        for st in strategy_stats.values():
            st['recommended_stake'] = round(st['recommended_stake'] * scale_factor, 2)

    # ---------------------------------------------------------------
    # SUMMARY METRICS
    # ---------------------------------------------------------------
    net_profit = bankroll - initial_bankroll
    total_staked = sum(st['staked'] for st in strategy_stats.values())
    total_roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0

    wins = sum(st['wins'] for st in strategy_stats.values())
    total_bets_placed = sum(st['bets'] for st in strategy_stats.values())
    win_rate = (wins / total_bets_placed * 100) if total_bets_placed > 0 else 0.0
    avg_odds = float(np.mean([b['odds'] for b in all_bets])) if all_bets else 0.0

    # Calculate Daily Returns for accurate Sharpe and Sortino
    if all_bets:
        daily_df = pd.DataFrame(all_bets)
        daily_df['date'] = pd.to_datetime(daily_df['date'])
        daily_profit = daily_df.groupby(daily_df['date'].dt.date)['profit'].sum()
        daily_staked = daily_df.groupby(daily_df['date'].dt.date)['stake'].sum()
        daily_returns = []
        for dt, p in daily_profit.items():
            s = daily_staked.get(dt, 0)
            if s > 0:
                daily_returns.append(p / s)
        
        if len(daily_returns) > 1:
            avg_return = float(np.mean(daily_returns))
            std_return = float(np.std(daily_returns))
            sharpe_ratio = (avg_return / std_return * math.sqrt(252)) if std_return > 0 else 0.0
            
            downside_returns = [r for r in daily_returns if r < 0]
            downside_dev = math.sqrt(np.mean([r**2 for r in downside_returns])) if downside_returns else 0.0
            sortino_ratio = (avg_return / downside_dev * math.sqrt(252)) if downside_dev > 0 else 0.0
            
            skewness = float(stats.skew(daily_returns)) if len(daily_returns) > 2 else 0.0
        else:
            sharpe_ratio, sortino_ratio, skewness = 0.0, 0.0, 0.0
    else:
        sharpe_ratio, sortino_ratio, skewness = 0.0, 0.0, 0.0

    max_consec_wins, max_consec_losses = 0, 0
    curr_wins, curr_losses = 0, 0
    for b in all_bets:
        if b.get('won', False):
            curr_wins += 1; curr_losses = 0
            if curr_wins > max_consec_wins: max_consec_wins = curr_wins
        else:
            curr_losses += 1; curr_wins = 0
            if curr_losses > max_consec_losses: max_consec_losses = curr_losses

    # Profit in units of stake (normalized)
    ref_stake = _get_stake(risk_method, initial_bankroll, initial_bankroll, 0.5, 2.0)
    profit_in_units = round(net_profit / ref_stake, 2) if ref_stake > 0 else 0.0

    summary = {
        'initial_bankroll': round(initial_bankroll, 2),
        'final_bankroll': round(bankroll, 2),
        'net_profit': round(net_profit, 2),
        'profit_in_stakes': profit_in_units,
        'total_bets': total_bets_placed,
        'wins': wins,
        'losses': total_bets_placed - wins,
        'win_rate': round(win_rate, 1),
        'roi': round(total_roi, 2),
        'max_drawdown': round(max_drawdown, 2),
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

    if total_bets_placed >= 2:
        summary['p_value'] = compute_pvalue_binomial(wins, total_bets_placed, avg_odds)
        try:
            brier = compute_brier_score(all_bets)
            summary.update({'brier_score': brier['brier_score'], 'brier_score_market': brier['brier_score_market'], 'brier_improvement': brier['brier_improvement']})
        except: pass
        try:
            bootstrap = compute_bootstrap_ci(all_bets)
            summary.update({'bootstrap_roi_ci_lower': bootstrap['bootstrap_roi_ci_lower'], 'bootstrap_roi_ci_upper': bootstrap['bootstrap_roi_ci_upper'], 'bootstrap_roi_median': bootstrap['bootstrap_roi_median'], 'prob_positive_roi': bootstrap['prob_positive_roi']})
        except: pass
        try:
            power = compute_power_analysis(summary['roi'], avg_odds, total_bets_placed)
            summary.update({'min_sample_size': power['min_sample_size'], 'sample_sufficient': power['sample_sufficient'], 'power_ratio': power['power_ratio']})
        except: pass
        try:
            rolling = compute_rolling_roi(all_bets)
            summary.update({'rolling_roi': rolling['rolling_roi'], 'edge_decay_pct': rolling['edge_decay_pct'], 'edge_decay_alert': rolling['edge_decay_alert']})
        except: pass

    oos_summary = None
    if total_bets_placed >= 20:
        n_oos = max(10, int(total_bets_placed * 0.2))
        oos_bets = all_bets[-n_oos:]
        oos_staked = sum(b.get('stake', 0) for b in oos_bets)
        oos_profit = sum(b.get('profit', 0) for b in oos_bets)
        oos_roi = (oos_profit / oos_staked * 100) if oos_staked > 0 else 0.0
        oos_wins = sum(1 for b in oos_bets if b.get('won', False))
        oos_win_rate = (oos_wins / len(oos_bets) * 100) if oos_bets else 0.0
        oos_summary = {'net_profit': round(oos_profit, 2), 'roi': round(oos_roi, 2), 'win_rate': round(oos_win_rate, 1), 'total_bets': len(oos_bets)}

    eqs_data = compute_edge_quality_score(summary, oos_summary)

    ai_staking_rule = 'proportional'
    ai_stake_value = 1.0
    if risk_method.startswith('fixed_'):
        try:
            ai_stake_value = float(risk_method.split('_')[1])
        except:
            ai_stake_value = 1.0
    elif risk_method == 'kelly_quarter': ai_staking_rule = 'kelly'; ai_stake_value = 0.25

    ai_res = predict_strategy_sustainability(all_bets, initial_bankroll, 1.05, ai_staking_rule, ai_stake_value, run_monte_carlo=True)
    if isinstance(ai_res, dict):
        ai_res['score'] = eqs_data.get('score', 0)
        ai_res['breakdown'] = eqs_data.get('breakdown', [])
        ai_res['verdict'] = eqs_data.get('verdict', 'Avaliando...')
        ai_res['verdict_color'] = eqs_data.get('verdict_color', 'warning')
        ai_res['risk_recommendation'] = eqs_data.get('risk_recommendation', '')
        ai_res['oos_summary'] = oos_summary

    quartiles = []
    if total_bets_placed >= 4:
        chunk_size = total_bets_placed // 4
        for i in range(4):
            chunk = all_bets[i * chunk_size: (i + 1) * chunk_size if i < 3 else len(all_bets)]
            c_profit = sum(b.get('profit', 0) for b in chunk)
            c_staked = sum(b.get('stake', 0) for b in chunk)
            c_wins = sum(1 for b in chunk if b.get('won', False))
            c_win_rate = (c_wins / len(chunk) * 100) if chunk else 0.0
            c_roi = (c_profit / c_staked * 100) if c_staked > 0 else 0.0
            quartiles.append({'profit': round(c_profit, 2), 'stakes': round(c_staked, 2), 'roi': round(c_roi, 2), 'win_rate': round(c_win_rate, 1), 'total_bets': len(chunk)})

    summary_fixed = summary.copy()
    summary_proportional = summary.copy()
    summary_kelly = summary.copy()

    l_stats = [{'league': k, 'profit': round(v['profit'], 2), 'bets': v['bets'], 'win_rate': round(v['wins'] / v['bets'] * 100, 1) if v['bets'] > 0 else 0} for k, v in league_stats.items()]
    m_stats = [{'month': k, 'profit': round(v['profit'], 2), 'bets': v['bets']} for k, v in monthly_stats.items()]
    o_stats = [{'odds_band': k, 'profit': round(v['profit'], 2), 'bets': v['bets']} for k, v in odds_stats.items()]

    eq_bankrolls = [p['bankroll'] for p in equity_curve]

    return {
        "status": "success",
        "initial_bankroll": initial_bankroll,
        "final_bankroll": round(bankroll, 2),
        "net_profit": round(net_profit, 2),
        "total_roi": round(total_roi, 2),
        "max_drawdown": round(max_drawdown, 2),
        "total_bets": total_bets_placed,
        "equity_curve": equity_curve,
        "equity_curve_fixed": eq_bankrolls,
        "equity_curve_proportional": eq_bankrolls,
        "equity_curve_kelly": eq_bankrolls,
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
        "bets": all_bets,
        "total_recommended_exposure": round(sum(st['recommended_stake'] for st in strategy_stats.values()), 2),
        "max_portfolio_exposure_pct": round(MAX_PORTFOLIO_EXPOSURE * 100, 0)
    }
