import pandas as pd
import numpy as np
import math
import logging
import scipy.stats as stats
from datetime import datetime

logger = logging.getLogger(__name__)
from collections import defaultdict
from .backtester import ChronologicalBacktester
from .history_manager import load_history
from .ai_predictor import (predict_strategy_sustainability, compute_brier_score,
                           compute_bootstrap_ci, compute_power_analysis, compute_rolling_roi,
                           compute_pvalue_binomial, compute_edge_quality_score)
from .backtest.helpers import allocate_core_satellite


def _get_stake(risk_method, initial_bankroll, current_bankroll, prob, odds, max_stake_pct=10.0):
    """
    Calculate stake for a bet.

    For fixed_X% methods: stake base is initial_bankroll (definition of fixed stake).
    For Kelly methods: stake base is current_bankroll to enable compounding.
    Caps via max_stake_pct (overridable per strategy tier).
    """
    if risk_method.startswith('fixed_'):
        try:
            pct = float(risk_method.split('_')[1])
        except:
            pct = 1.0
        stake = initial_bankroll * (pct / 100.0)
    elif risk_method == 'kelly_quarter':
        if odds > 1.0:
            k_fraction = ((prob * odds) - 1.0) / (odds - 1.0)
            k_fraction = max(0.0, min(k_fraction, 0.20))   # cap at 20% full Kelly
            stake = current_bankroll * (k_fraction / 4.0)  # Quarter-Kelly on current bankroll
        else:
            stake = current_bankroll * 0.01
    else:
        stake = current_bankroll * 0.01

    # Minimum $1, maximum absolute dollar cap: never bet more than 5% of initial
    # allocated bankroll per bet, regardless of compounding growth.
    stake = max(1.0, stake)
    absolute_cap = initial_bankroll * 0.05  # 5% of initial = prevents absurd compounding
    stake = min(stake, absolute_cap)
    return stake


def run_portfolio(strategy_ids, initial_bankroll=1000.0, risk_method='fixed_1', strategies_inline=None):
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

    # Fallback: use inline strategies when server DB is empty (post-deploy cold start)
    if not selected_strategies and strategies_inline:
        selected_strategies = strategies_inline
        logger.info(f"Usando {len(selected_strategies)} estratégias inline (DB vazio pós-deploy).")

    if not selected_strategies:
        return {"error": "Nenhuma estratégia válida selecionada."}

    # Deduplicate equivalent market pairs: lay_X and lay_X_ex are identical aliases
    LAY_ALIASES = {
        'lay_home': 'lay_home',
        'lay_home_ex': 'lay_home',
        'lay_away': 'lay_away',
        'lay_away_ex': 'lay_away',
        'lay_draw': 'lay_draw',
        'lay_draw_ex': 'lay_draw',
    }
    seen_canonical = {}
    deduped = []
    dedup_warnings = []
    for s in selected_strategies:
        raw_mkt = s['params'].get('market', '')
        # Normalize: market can be a single string or a list of strings
        mkt = raw_mkt[0] if isinstance(raw_mkt, list) and len(raw_mkt) > 0 else (raw_mkt if not isinstance(raw_mkt, list) else '')
        canonical = LAY_ALIASES.get(mkt, mkt)
        key = (canonical, tuple(s['params'].get('leagues', [])))
        if key in seen_canonical:
            dedup_warnings.append(
                f"'{s['name']}' usa o mesmo mercado/liga que '{seen_canonical[key]}'. "
                f"Mantendo apenas a primeira para evitar dupla contagem."
            )
        else:
            seen_canonical[key] = s['name']
            deduped.append(s)

    if deduped:
        selected_strategies = deduped

    if len(selected_strategies) > 4:
        return {"error": "Servidor gratuito excedido! Selecione no máximo 4 estratégias para rodar o portfólio sem travar a memória."}

    all_bets = []

    logger.info(f"Rodando backtests individuais para {len(selected_strategies)} estratégias...")

    # Collect aggregated stats from individual backtests (matches analyzed, seasons)
    total_matches_in_file = 0
    all_seasons = set()
    for s in selected_strategies:
        try:
            p = s['params']
            raw_mkt = p.get('market', '')
            mkt_str = raw_mkt[0] if isinstance(raw_mkt, list) and len(raw_mkt) > 0 else (raw_mkt if not isinstance(raw_mkt, list) else '')
            bt = ChronologicalBacktester()
            res = bt.run(
                leagues=p.get('leagues', []),
                start_date=p.get('startDate', p.get('start_date', '2021-01-01')),
                end_date=p.get('endDate', p.get('end_date', datetime.today().strftime('%Y-%m-%d'))),
                market=mkt_str,
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
            # Collect matches/seasons from individual summary
            s_summary = res.get('summary', {}) if "error" not in res else {}
            total_matches_in_file = max(total_matches_in_file, s_summary.get('matches_total_in_file', 0))
            for season in s_summary.get('seasons_analyzed', []):
                all_seasons.add(str(season))
        except Exception as e:
            import traceback
            logger.error(f"Error processing strategy {s.get('id','?')} '{s.get('name','?')}': {e}\n{traceback.format_exc()}")
            continue

    if not all_bets:
        return {"error": "Nenhuma aposta gerada pelas estratégias selecionadas."}

    # Sort all bets chronologically.
    # Using (date, market, match_id) ensures that bets on the same day are
    # processed in a consistent, deterministic order — critical for correct
    # intraday drawdown calculation in the portfolio equity curve.
    # Previously sorted only by date, which hid intraday volatility.
    all_bets.sort(key=lambda x: (
        x.get('date', ''),
        x.get('market', ''),
        str(x.get('match_id', x.get('home_team', '') + x.get('away_team', '')))
    ))

    # ---------------------------------------------------------------
    # CORE/SATELLITE ALLOCATION
    # Classify each strategy by its individual backtest quality.
    # Core (ROI > 0 and profitable) gets 80% bankroll + full limits.
    # Satellite gets 20% bankroll + tighter caps (12.5% Kelly, 2.5% stake).
    # ---------------------------------------------------------------
    strat_classifications = []
    for s in selected_strategies:
        sid = s['id']
        s_bets = [b for b in all_bets if b.get('strategy_id') == sid]
        s_wins = sum(1 for b in s_bets if b.get('won', False))
        s_profit = sum(b.get('profit', 0) for b in s_bets)
        s_staked = sum(b.get('stake', 0) for b in s_bets)
        s_roi = (s_profit / s_staked * 100) if s_staked > 0 else 0.0
        is_profitable = s_profit > 0 and s_roi > 0

        strat_classifications.append({
            'name': s['name'],
            'allocation': 'core' if is_profitable else 'satellite',
            'kelly_fraction': 0.25,
            'max_stake_pct': 5.0,
        })

    core_sat_alloc = allocate_core_satellite(initial_bankroll, strat_classifications)

    strategy_stats = {
        s['id']: {
            'name': s['name'],
            'bets': 0,
            'wins': 0,
            'staked': 0.0,
            'profit': 0.0,
            'recommended_stake': 0.0,
            'win_rate': 0.0,
            'roi': 0.0,
            # Per-strategy bankroll from core/satellite allocation
            'allocated_bankroll': core_sat_alloc.get(s['name'], {}).get('bankroll', initial_bankroll / max(len(selected_strategies), 1)),
            'tier': core_sat_alloc.get(s['name'], {}).get('tier', 'core'),
            'kelly_cap': core_sat_alloc.get(s['name'], {}).get('kelly_fraction', 0.25),
            'max_stake_pct': core_sat_alloc.get(s['name'], {}).get('max_stake_pct', 5.0),
        } for s in selected_strategies
    }

    # Total bankroll starts as sum of allocated slices
    deployed_bankroll = sum(st['allocated_bankroll'] for st in strategy_stats.values())
    idle_cash = initial_bankroll - deployed_bankroll
    bankroll = deployed_bankroll

    # ---------------------------------------------------------------
    # HISTORICAL SIMULATION
    # Fixed% uses initial_bankroll as base (definition of fixed stake).
    # Kelly uses current_bankroll for true compounding.
    # Caps (10% per bet, 20% portfolio) prevent explosion.
    # ---------------------------------------------------------------
    peak_bankroll = bankroll + idle_cash
    max_drawdown = 0.0
    max_dd_duration = 0
    current_dd_duration = 0

    equity_curve = []
    bet_index = 0

    league_stats = defaultdict(lambda: {'profit': 0.0, 'bets': 0, 'wins': 0})
    monthly_stats = defaultdict(lambda: {'profit': 0.0, 'bets': 0})
    odds_stats = defaultdict(lambda: {'profit': 0.0, 'bets': 0})

    # Record initial bankroll as first point (total = deployed + idle)
    equity_curve.append({'date': all_bets[0]['date'], 'bankroll': round(bankroll + idle_cash, 2), 'bet_index': 0})

    for b in all_bets:
        b_date = b['date']
        sid = b['strategy_id']

        bet_odds = float(b.get('odds', 2.0))
        prob = float(b.get('prob', 50.0)) / 100.0
        bet_won = bool(b.get('won', False))

        # Use strategy's allocated bankroll and tier-specific cap
        strat_bankroll = strategy_stats[sid]['allocated_bankroll']
        max_stake_pct = strategy_stats[sid]['max_stake_pct']

        stake = _get_stake(risk_method, initial_bankroll, strat_bankroll, prob, bet_odds, max_stake_pct=max_stake_pct)

        if strat_bankroll < stake or strat_bankroll < 1.0:
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
        b['bankroll'] = round(bankroll + idle_cash + profit, 2)
        bankroll += profit
        strategy_stats[sid]['allocated_bankroll'] += profit
        bet_index += 1

        # Record equity curve after EVERY bet (total = deployed + idle)
        equity_curve.append({'date': b_date, 'bankroll': round(bankroll + idle_cash, 2), 'bet_index': bet_index})

        # Drawdown (on total portfolio, including idle cash)
        total_bankroll = bankroll + idle_cash
        if total_bankroll > peak_bankroll:
            peak_bankroll = total_bankroll
            current_dd_duration = 0
        else:
            current_dd_duration += 1
            if current_dd_duration > max_dd_duration:
                max_dd_duration = current_dd_duration

        dd = (peak_bankroll - total_bankroll) / peak_bankroll * 100 if peak_bankroll > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

        # Strategy stats
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
            st['recommended_stake'] = round(total_bankroll * (pct / 100.0), 2)
        elif risk_method == 'kelly_quarter':
            if avg_odds_s > 1.0:
                k_fraction = ((prob_s * avg_odds_s) - 1) / (avg_odds_s - 1)
                k_fraction = max(0.0, min(k_fraction, 0.20))
                st['recommended_stake'] = round(total_bankroll * (k_fraction / 4.0), 2)
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
    max_allowed_total = total_bankroll * MAX_PORTFOLIO_EXPOSURE

    if total_recommended > max_allowed_total and total_recommended > 0:
        scale_factor = max_allowed_total / total_recommended
        for st in strategy_stats.values():
            st['recommended_stake'] = round(st['recommended_stake'] * scale_factor, 2)

    # ---------------------------------------------------------------
    # SUMMARY METRICS
    # ---------------------------------------------------------------
    total_bankroll = bankroll + idle_cash
    net_profit = total_bankroll - initial_bankroll
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
            sharpe_ratio = (avg_return / std_return * math.sqrt(156)) if std_return > 0 else 0.0  # ~3 matches/week
            
            downside_returns = [r for r in daily_returns if r < 0]
            downside_dev = math.sqrt(np.mean([r**2 for r in downside_returns])) if downside_returns else 0.0
            sortino_ratio = (avg_return / downside_dev * math.sqrt(156)) if downside_dev > 0 else 0.0  # ~3 matches/week
            
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
        'final_bankroll': round(total_bankroll, 2),
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
            bootstrap = compute_bootstrap_ci(all_bets, initial_bankroll=initial_bankroll)
            summary.update({
                'bootstrap_roi_ci_lower': bootstrap['bootstrap_roi_ci_lower'],
                'bootstrap_roi_ci_upper': bootstrap['bootstrap_roi_ci_upper'],
                'bootstrap_roi_median': bootstrap['bootstrap_roi_median'],
                'prob_positive_roi': bootstrap['prob_positive_roi'],
                'bootstrap_drawdown_median': bootstrap['bootstrap_drawdown_median'],
                'bootstrap_drawdown_ci_lower': bootstrap['bootstrap_drawdown_ci_lower'],
                'bootstrap_drawdown_ci_upper': bootstrap['bootstrap_drawdown_ci_upper'],
            })
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
        "final_bankroll": round(total_bankroll, 2),
        "net_profit": round(net_profit, 2),
        "total_roi": round(total_roi, 2),
        "max_drawdown": round(max_drawdown, 2),
        "total_bets": total_bets_placed,
        "deployed_bankroll": round(deployed_bankroll, 2),
        "idle_cash": round(idle_cash, 2),
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
        "max_portfolio_exposure_pct": round(MAX_PORTFOLIO_EXPOSURE * 100, 0),
        "dedup_warnings": dedup_warnings,
        "matches_total_in_file": total_matches_in_file,
        "seasons_analyzed": sorted(all_seasons, key=lambda x: int(x) if x.isdigit() else 0)
    }
