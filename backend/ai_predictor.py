import numpy as np
import pandas as pd
import math
import logging

logger = logging.getLogger(__name__)

def beta_posterior_probability(alpha, beta_param, threshold):
    """
    Computes P(p > threshold) for a Beta(alpha, beta_param) distribution.
    Uses log-space calculations to avoid overflow/underflow for large inputs,
    and integrates numerically using a Riemann sum.
    """
    # 2000 points for integration
    x = np.linspace(0.0, 1.0, 2000)
    
    # Avoid log(0)
    x_clipped = np.clip(x, 1e-12, 1.0 - 1e-12)
    
    # Calculate Beta PDF kernel in log-space: (alpha-1)*log(x) + (beta-1)*log(1-x)
    log_kernel = (alpha - 1.0) * np.log(x_clipped) + (beta_param - 1.0) * np.log(1.0 - x_clipped)
    
    # Subtract max to normalize for exp (prevent overflow)
    max_log = np.max(log_kernel)
    kernel = np.exp(log_kernel - max_log)
    
    total_area = np.sum(kernel)
    if total_area == 0:
        return 0.5
        
    above_threshold_area = np.sum(kernel[x > threshold])
    return float(above_threshold_area / total_area)

def predict_strategy_sustainability(bets_record, initial_bankroll=1000.0, value_threshold=1.05, staking_rule='fixed', stake_value=10.0, run_monte_carlo=True, min_odds=1.0, max_odds=50.0):
    """
    Evaluates the sustainability of a backtested strategy.
    
    Uses:
    1. A Walk-Forward Logistic Regression Classifier (pure NumPy with L2 regularization)
       to predict future profitability (next window of bets will have ROI > 0).
    2. A Beta-Binomial Bayesian conjugate prior to evaluate if the win rate is 
       statistically greater than the break-even win rate (1/avg_odds).
    3. Performance drift analysis (comparing the ROI of the 1st vs 2nd half).
    """
    total_bets = len(bets_record)
    
    # Minimum bets to run predictive AI
    if total_bets < 20:
        return {
            "status": "insufficient_data",
            "message": "Mínimo de 20 apostas necessárias para análise preditiva por IA.",
            "ml_probability": 0.0,
            "bayesian_confidence": 0.0,
            "drift_ratio": 0.0,
            "roi_first_half": 0.0,
            "roi_second_half": 0.0,
            "report": "Dados insuficientes no backtest para executar os modelos de IA. Continue acumulando dados ou estenda o período de teste.",
            "monte_carlo": None
        }
        
    # Chronological dataframe for processing
    df = pd.DataFrame(bets_record)
    df['profit'] = df['profit'].astype(float)
    df['stake'] = df['stake'].astype(float)
    df['odds'] = df['odds'].astype(float)
    df['ev'] = df['ev'].astype(float)
    
    # 1. Feature Extraction
    # Dynamic window size: larger history allows larger window, capped between 5 and 20
    K = max(5, min(20, total_bets // 5))
    
    features = []
    labels = []
    
    # Pre-calculate bankroll drawdowns for rolling metrics
    bankrolls = df['bankroll'].values
    profits = df['profit'].values
    stakes = df['stake'].values
    odds_arr = df['odds'].values
    evs = df['ev'].values
    
    for i in range(K - 1, total_bets):
        # Calculate features using fast numpy slices
        prof_slice = profits[i - K + 1 : i + 1]
        stake_slice = stakes[i - K + 1 : i + 1]
        
        total_profit = np.sum(prof_slice)
        total_staked = np.sum(stake_slice)
        roi = (total_profit / total_staked) if total_staked > 0 else 0.0
        
        wins = np.sum(prof_slice > 0)
        win_rate = wins / K
        
        avg_odds = np.mean(odds_arr[i - K + 1 : i + 1])
        avg_ev = np.mean(evs[i - K + 1 : i + 1])
        
        # Volatility of profit
        std_profit = np.std(prof_slice)
        if pd.isna(std_profit):
            std_profit = 0.0
            
        # Drawdown in this window
        window_br = bankrolls[i - K + 1 : i + 1]
        peak = window_br[0]
        max_dd = 0.0
        for br in window_br:
            if br > peak:
                peak = br
            dd = (peak - br) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                
        feat = [roi, win_rate, avg_odds, std_profit, max_dd, avg_ev]
        features.append(feat)
        
        # Label: Is the FUTURE window of size K profitable?
        if i + K < total_bets:
            future_profit = np.sum(profits[i + 1 : i + 1 + K])
            labels.append(1.0 if future_profit > 0 else 0.0)
            
    # Convert to NumPy arrays
    X_all = np.array(features)
    # Number of training samples is len(labels)
    M_samples = len(labels)
    
    if M_samples < 5:
        # Fallback if too few samples to train ML
        ml_prob = 0.5
        model_confidence = 0.5
    else:
        X_train_full = X_all[:M_samples]
        y_train_full = np.array(labels)
        
        # Normalize features (Standard Scaling)
        mean_cols = np.mean(X_train_full, axis=0)
        std_cols = np.std(X_train_full, axis=0)
        std_cols[std_cols < 1e-6] = 1.0  # Avoid division by zero
        
        X_scaled = (X_train_full - mean_cols) / std_cols
        
        # Add column of ones for intercept
        X_scaled_intercept = np.hstack((np.ones((M_samples, 1)), X_scaled))
        
        # Chronological train/test split (70% train, 30% test)
        split = int(0.7 * M_samples)
        if split < 4:
            split = M_samples  # Train on all if dataset too small
            
        X_train, y_train = X_scaled_intercept[:split], y_train_full[:split]
        X_test, y_test = X_scaled_intercept[split:], y_train_full[split:]
        
        # Logistic Regression with L2 Regularization using Gradient Descent
        D_features = X_train.shape[1] - 1
        w = np.zeros(D_features + 1)
        learning_rate = 0.05
        epochs = 800
        lambda_reg = 1.0  # Keep regularization relatively high to prevent overfitting
        
        for _ in range(epochs):
            z = np.dot(X_train, w)
            z = np.clip(z, -15, 15)  # Prevent exp overflow
            y_hat = 1.0 / (1.0 + np.exp(-z))
            
            error = y_hat - y_train
            grad = np.dot(X_train.T, error) / len(y_train)
            
            # L2 penalty (do not regularize intercept)
            reg_term = (lambda_reg / len(y_train)) * w
            reg_term[0] = 0.0
            grad += reg_term
            
            w -= learning_rate * grad
            
        # Evaluate on Test Set
        if len(y_test) > 0:
            z_test = np.dot(X_test, w)
            z_test = np.clip(z_test, -15, 15)
            y_test_hat = 1.0 / (1.0 + np.exp(-z_test))
            y_test_pred = (y_test_hat >= 0.5).astype(float)
            model_confidence = float(np.mean(y_test_pred == y_test))
        else:
            model_confidence = 0.65  # Default baseline
            
        # Predict sustainability score for the CURRENT state
        # The current state features are the very last entry in X_all
        current_feat = X_all[-1]
        current_feat_scaled = (current_feat - mean_cols) / std_cols
        current_feat_intercept = np.insert(current_feat_scaled, 0, 1.0)
        
        z_curr = np.dot(current_feat_intercept, w)
        z_curr = np.clip(z_curr, -15, 15)
        ml_prob = float(1.0 / (1.0 + np.exp(-z_curr)))
        
    # 2. Bayesian Confidence (Beta-Binomial Conjugate Prior)
    total_wins = int(df[df['profit'] > 0].shape[0])
    total_losses = total_bets - total_wins
    
    avg_odds = float(df['odds'].mean())
    p_break_even = 1.0 / avg_odds if avg_odds > 1.0 else 0.5
    
    # Prior Beta(1, 1). Posterior Beta(1 + wins, 1 + losses)
    alpha = 1.0 + total_wins
    beta_param = 1.0 + total_losses
    
    bayesian_conf = beta_posterior_probability(alpha, beta_param, p_break_even)
    
    # 3. Performance Drift Analysis (First Half vs Second Half ROI)
    half_idx = total_bets // 2
    first_half = df.iloc[:half_idx]
    second_half = df.iloc[half_idx:]
    
    roi_first = float((first_half['profit'].sum() / first_half['stake'].sum() * 100)) if first_half['stake'].sum() > 0 else 0.0
    roi_second = float((second_half['profit'].sum() / second_half['stake'].sum() * 100)) if second_half['stake'].sum() > 0 else 0.0
    
    drift = roi_second - roi_first
    
    # 4. Generate AI Report / Verdict
    report = generate_ai_report(ml_prob, bayesian_conf, drift, total_bets, roi_first, roi_second)
    
    # 5. Run strategy optimization suggestions
    suggestions = optimize_strategy_parameters(bets_record, value_threshold, initial_bankroll, staking_rule, stake_value, min_odds=min_odds, max_odds=max_odds)
    
    # 6. Run Monte Carlo Simulation
    mc_res = run_monte_carlo_simulation(bets_record, initial_bankroll, staking_rule, stake_value) if run_monte_carlo else None
    
    # 7. Generate Bankroll Management Recommendations
    total_wins_float = float(total_wins)
    wr = total_wins_float / total_bets if total_bets > 0 else 0.0
    
    # Expected longest run of losses (IID Bernoulli formula)
    # Apply 2× safety factor: real betting sequences exhibit serial dependence
    # (form cycles, model miscalibration clusters) that produce streaks
    # 1.5-2× longer than the IID theoretical value.
    if wr > 0.0 and wr < 1.0:
        consec_losses = int(math.ceil(math.log(total_bets) / -math.log(1.0 - wr)))
        consec_losses = max(3, min(30, consec_losses * 2))
    else:
        consec_losses = 10  # Default fallback
        
    # Calculate Kelly Criterion
    b_kelly = avg_odds - 1.0
    if b_kelly > 0.01:
        p_kelly = wr
        q_kelly = 1.0 - p_kelly
        f_star = (p_kelly * b_kelly - q_kelly) / b_kelly
        f_star = max(0.0, f_star)
    else:
        f_star = 0.0
        
    # Recommended stake percentage (1/4 Kelly, capped between 0.5% and 5.0%)
    if df['profit'].sum() > 0.0 and f_star > 0.0:
        rec_stake_pct = min(5.0, max(0.5, f_star * 0.25 * 100.0))
        justification = f"Com base na assertividade de {wr*100:.1f}% e odds médias de {avg_odds:.2f}, o Kelly Criterion Fracionário (1/4) recomenda stakes de {rec_stake_pct:.1f}% da banca para otimizar o crescimento com risco de ruína controlado."
    else:
        rec_stake_pct = 0.5  # Survive mode
        justification = "A estratégia apresentou retorno negativo ou nulo no histórico. Recomenda-se não operar com dinheiro real (stake de 0.0%) ou usar stakes mínimas de teste (0.5%) para validação de dados."
        
    # Calculate minimum recommended bankroll for a $10 stake (or proportional to current stake)
    current_stake_val = float(stake_value)
    if staking_rule == 'fixed':
        min_rec_bankroll = current_stake_val / (rec_stake_pct / 100.0)
    else:
        min_rec_bankroll = 10.0 / (rec_stake_pct / 100.0)
        
    min_rec_bankroll = round(max(100.0, min_rec_bankroll), 2)
    
    staking_recommendation = {
        "recommended_stake_pct": round(rec_stake_pct, 1),
        "max_consecutive_losses": consec_losses,
        "min_recommended_bankroll": min_rec_bankroll,
        "justification": justification
    }
    
    return {
        "status": "success",
        "message": "Análise preditiva por IA concluída.",
        "ml_probability": round(ml_prob * 100, 1),
        "bayesian_confidence": round(bayesian_conf * 100, 1),
        "drift_ratio": round(drift, 1),
        "roi_first_half": round(roi_first, 1),
        "roi_second_half": round(roi_second, 1),
        "report": report,
        "suggestions": suggestions,
        "monte_carlo": mc_res,
        "staking_recommendation": staking_recommendation
    }

def generate_ai_report(ml_prob, bayesian_conf, drift, total_bets, roi_first, roi_second):
    """Generates a professional diagnosis in Portuguese explaining the AI metrics."""
    # 1. Summary of ML probability
    ml_eval = ""
    if ml_prob >= 0.70:
        ml_eval = "O modelo de Machine Learning aponta excelente consistência recente, com alta probabilidade de a estratégia continuar lucrativa no próximo ciclo de apostas."
    elif ml_prob >= 0.50:
        ml_eval = "O modelo de Machine Learning indica estabilidade moderada, mostrando que a estratégia mantém uma propensão favorável no curto prazo."
    else:
        ml_eval = "Atenção: A IA detectou uma perda de padrão estatístico recente (decaimento de sinal), indicando risco elevado de reversão para prejuízo."

    # 2. Summary of Bayesian confidence
    bayesian_eval = ""
    if bayesian_conf >= 0.80:
        bayesian_eval = f"Há uma confiança estatística altíssima ({round(bayesian_conf*100)}%) de que o seu win rate médio supera a barreira de break-even das odds médias, confirmando a existência de um edge matemático real."
    elif bayesian_conf >= 0.60:
        bayesian_eval = f"A confiança estatística é moderada ({round(bayesian_conf*100)}%). A lucratividade observada provavelmente contém um edge real, mas ainda está vulnerável à variância natural do mercado."
    else:
        bayesian_eval = f"A confiança estatística é baixa ({round(bayesian_conf*100)}%). Há alta probabilidade de que os resultados positivos passados tenham sido causados por sorte temporária (ruído estatístico) e não por uma vantagem matemática de longo prazo."

    # 3. Summary of Drift
    drift_eval = ""
    if drift < -8:
        drift_eval = f"Detectamos um forte decaimento de performance (Drift de {round(drift, 1)}% entre as metades do teste). O ROI caiu de {round(roi_first, 1)}% no início para {round(roi_second, 1)}% na metade final, sinalizando que a estratégia pode estar obsoleta ou sofrendo forte ajuste de mercado."
    elif drift < -3:
        drift_eval = f"Há um leve decaimento de performance (Drift de {round(drift, 1)}% de ROI). Embora ainda positiva, a estratégia apresentou rentabilidade menor no período recente."
    else:
        drift_eval = f"A estratégia mostra consistência temporal exemplar (Drift de {round(drift, 1)}% de ROI). A performance na segunda metade ({round(roi_second, 1)}%) é equivalente ou superior à primeira ({round(roi_first, 1)}%), sugerindo resiliência."

    # 4. Final Verdict and Recommendation
    verdict = ""
    # Highly sustainable
    if ml_prob >= 0.65 and bayesian_conf >= 0.70 and drift >= -3:
        verdict = "VEREDITO: Altamente Recomendada (Sustentável). Os três indicadores alinham-se positivamente. Sugere-se operar com gestão de banca padrão (Ex: Proporcional 2.0% ou Kelly Criterion Fracionário de 0.25)."
    # Good, but decaying
    elif ml_prob >= 0.50 and bayesian_conf >= 0.60 and drift < -8:
        verdict = "VEREDITO: Operar com Cautela (Alerta de Decaimento). A estratégia possui edge histórico, mas a rentabilidade recente está caindo rapidamente. Recomenda-se reduzir o tamanho da stake padrão pela metade (1.0%)."
    # Overfitted/Lucky
    elif ml_prob < 0.50 and bayesian_conf < 0.60:
        verdict = "VEREDITO: Não Recomendada (Alto Risco de Overfitting). A estratégia demonstra perda de tração recente e baixa significância estatística. Os lucros passados têm alto risco de não se repetirem."
    # Moderate
    elif ml_prob >= 0.50 and bayesian_conf >= 0.50:
        verdict = "VEREDITO: Neutra / Observação. A estratégia apresenta edge modesto. Recomendável monitorar sem alocação agressiva de capital."
    else:
        verdict = "VEREDITO: Cautela Geral. Indicadores divergentes. A estratégia possui volatilidade incomum e requer maior amostragem antes de operar com dinheiro real."

    return f"{ml_eval} {bayesian_eval} {drift_eval} \n\n**{verdict}**"

def optimize_strategy_parameters(bets_record, current_val_threshold, initial_bankroll=1000.0, staking_rule='fixed', stake_value=10.0, min_odds=1.0, max_odds=50.0):
    """
    Simulates counterfactual scenarios on backtest results to identify
    potential optimizations in odds ranges, EV threshold, and league selection.
    For each valid optimization, computes the full optimized equity curve and metrics.
    """
    if not bets_record or len(bets_record) < 20:
        return []
        
    df = pd.DataFrame(bets_record)
    df['profit'] = df['profit'].astype(float)
    df['stake'] = df['stake'].astype(float)
    df['odds'] = df['odds'].astype(float)
    df['ev'] = df['ev'].astype(float)
    
    baseline_profit = df['profit'].sum()
    baseline_staked = df['stake'].sum()
    baseline_roi = (baseline_profit / baseline_staked * 100) if baseline_staked > 0 else 0.0
    baseline_wins = sum(1 for p in df['profit'] if p > 0)
    baseline_win_rate = (baseline_wins / len(df) * 100) if len(df) > 0 else 0.0
    
    # Calculate baseline max drawdown
    bankrolls = df['bankroll'].values
    peak = bankrolls[0]
    baseline_dd = 0.0
    for br in bankrolls:
        if br > peak:
            peak = br
        dd = (peak - br) / peak if peak > 0 else 0.0
        if dd > baseline_dd:
            baseline_dd = dd
            
    original_summary = {
        'net_profit': round(baseline_profit, 2),
        'roi': round(baseline_roi, 2),
        'win_rate': round(baseline_win_rate, 1),
        'max_drawdown': round(baseline_dd * 100, 2),
        'total_bets': len(df)
    }
    
    suggestions = []
    
    # 1. MDO Grid Search: EV + Odds ranges (to maximize signal efficiency using Flat Staking)
    best_ev_thresh = current_val_threshold
    best_min_odds = float(df['odds'].min())
    best_max_odds = float(df['odds'].max())
    best_fitness = -9999.0
    best_flat_res = None
    best_sub_df = df
    
    # Helper to evaluate flat staking ($10 stakes)
    def evaluate_flat_staking(df_sub):
        if len(df_sub) == 0:
            return {'roi': -100.0, 'max_drawdown': 1.0, 'net_profit': -1000.0, 'total_bets': 0}
        stake = 10.0
        bankroll = 1000.0
        peak_bankroll = 1000.0
        max_drawdown = 0.0
        wins = 0
        total_staked = 0.0
        
        for row in df_sub.to_dict('records'):
            odds = float(row['odds'])
            won = float(row['profit']) > 0
            total_staked += stake
            if won:
                wins += 1
                profit = stake * (odds - 1.0)
                bankroll += profit
            else:
                profit = -stake
                bankroll += profit
            
            if bankroll > peak_bankroll:
                peak_bankroll = bankroll
            dd = (peak_bankroll - bankroll) / peak_bankroll if peak_bankroll > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd
        
        net_profit = bankroll - 1000.0
        roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0
        return {
            'roi': roi,
            'max_drawdown': max_drawdown,
            'net_profit': net_profit,
            'total_bets': len(df_sub)
        }

    # Baseline flat staking evaluation
    flat_baseline = evaluate_flat_staking(df)
    
    def get_fitness(flat_res):
        if flat_res['total_bets'] < 15:
            return -9999.0
        dd_val = max(1.0, flat_res['max_drawdown'] * 100.0)
        import math
        return (flat_res['roi'] / dd_val) * math.log(flat_res['total_bets'])

    baseline_fitness = get_fitness(flat_baseline)
    best_fitness = baseline_fitness
    best_flat_res = flat_baseline
    
    # Search grid
    ev_grid = [round(current_val_threshold + offset, 4) for offset in [0.0, 0.02, 0.04, 0.06, 0.08, 0.10]]
    min_o_grid = [1.0, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0]
    max_o_grid = [2.5, 3.0, 4.0, 5.0, 8.0, 15.0, 50.0]
    
    for ev_t in ev_grid:
        for min_o in min_o_grid:
            for max_o in max_o_grid:
                if min_o >= max_o:
                    continue
                ev_t_val = round(ev_t, 4)
                min_o_val = round(min_o, 4)
                max_o_val = round(max_o, 4)
                # filter subset with floating-point tolerance
                df_sub = df[(df['ev'] >= ev_t_val - 1e-9) & (df['odds'] >= min_o_val - 1e-9) & (df['odds'] <= max_o_val + 1e-9)]
                
                # Check significance: must have at least 15 bets and at least 15% of total bets
                if len(df_sub) < max(15, int(len(df) * 0.15)):
                    continue
                
                flat_res = evaluate_flat_staking(df_sub)
                fitness = get_fitness(flat_res)
                
                if fitness > best_fitness:
                    best_fitness = fitness
                    best_ev_thresh = ev_t
                    best_min_odds = min_o
                    best_max_odds = max_o
                    best_flat_res = flat_res
                    best_sub_df = df_sub
                    logger.debug(f"Grid Update: ev={ev_t}, min={min_o}, max={max_o}, fitness={fitness:.4f}, bets={flat_res['total_bets']}")

    # Let's check if we found a better setup
    improved = best_fitness > baseline_fitness + 0.05
    logger.debug(f"MDO: improved={improved}, best_ev={best_ev_thresh}, best_min={best_min_odds}, best_max={best_max_odds}, baseline_fit={baseline_fitness:.3f}, best_fit={best_fitness:.3f}, best_roi={best_flat_res['roi']:.2f}%, best_dd={best_flat_res['max_drawdown']*100:.2f}%, best_bets={best_flat_res['total_bets']}")
    
    # 1. EV trigger optimization suggestion
    if improved and best_ev_thresh > current_val_threshold:
        opt_res = recalculate_sub_backtest(df[df['ev'] >= best_ev_thresh], initial_bankroll, staking_rule, stake_value)
        if opt_res:
            opt_roi = opt_res['summary']['roi']
            roi_diff = opt_roi - baseline_roi
            dd_diff = opt_res['summary']['max_drawdown'] - (baseline_dd * 100.0)
            dd_note = f" e reduziria o Drawdown Máximo em {abs(dd_diff):.1f}pp" if dd_diff < -2 else ""
            
            suggestions.append({
                "type": "ev",
                "text": f"Subir o Gatilho EV de {current_val_threshold:.2f} para {best_ev_thresh:.2f} (otimização pura de sinal). Isso eleva o ROI para {opt_roi:.1f}% (+{roi_diff:.1f}%){dd_note} com base em {opt_res['summary']['total_bets']} apostas de maior qualidade.",
                "warning": "Resultados exploratórios — otimização post-hoc na mesma amostra. Aplicar correção Bonferroni (~300 candidatos). Validar em OOS independente.",
                "value": round(best_ev_thresh, 2),
                "original_summary": original_summary,
                "optimized_summary": opt_res['summary'],
                "optimized_curve": opt_res['equity_curve']
            })
            
    # 2. Primary odds range suggestion
    if improved and (best_min_odds > min_odds + 0.05 or best_max_odds < max_odds - 0.5):
        sub_odds = df[(df['odds'] >= best_min_odds) & (df['odds'] <= best_max_odds)]
        if len(sub_odds) >= 15:
            opt_res = recalculate_sub_backtest(sub_odds, initial_bankroll, staking_rule, stake_value)
            if opt_res:
                opt_roi = opt_res['summary']['roi']
                roi_diff = opt_roi - baseline_roi
                dd_diff = opt_res['summary']['max_drawdown'] - (baseline_dd * 100.0)
                dd_note = f" e reduziria o Drawdown Máximo em {abs(dd_diff):.1f}pp" if dd_diff < -2 else ""
                
                suggestions.append({
                    "type": "odds_warning",
                    "text": f"Limitar as odds ao intervalo de {best_min_odds:.2f} a {best_max_odds:.2f} (otimização pura de sinal). Filtra ruídos extremos de odds baixas ou variância alta. ROI previsto de {opt_roi:.1f}% (+{roi_diff:.1f}%){dd_note}.",
                    "warning": "Resultados exploratórios — otimização post-hoc na mesma amostra. Aplicar correção Bonferroni (~300 candidatos). Validar em OOS independente.",
                    "value": f"{best_min_odds:.2f}-{best_max_odds:.2f}",
                    "original_summary": original_summary,
                    "optimized_summary": opt_res['summary'],
                    "optimized_curve": opt_res['equity_curve']
                })
                
    # 3. League Exclusions (using flat net profit logic)
    leagues_present = df['league'].unique()
    if len(leagues_present) >= 3:
        league_stats = []
        for l in leagues_present:
            sub_l = df[df['league'] == l]
            flat_l = evaluate_flat_staking(sub_l)
            league_stats.append((l, flat_l['net_profit'], len(sub_l)))
            
        bad_leagues = [l for l, profit, count in league_stats if profit < -5.0 and count >= 5]
        
        if bad_leagues and len(bad_leagues) < len(leagues_present):
            sub_ex = df[~df['league'].isin(bad_leagues)]
            if len(sub_ex) >= 15:
                opt_res = recalculate_sub_backtest(sub_ex, initial_bankroll, staking_rule, stake_value)
                if opt_res:
                    opt_roi = opt_res['summary']['roi']
                    opt_profit = opt_res['summary']['net_profit']
                    profit_improvement = opt_profit - baseline_profit
                    
                    if profit_improvement > 10.0 or opt_roi > baseline_roi + 1.0:
                        suggestions.append({
                            "type": "leagues",
                            "text": f"Excluir os campeonatos {', '.join(bad_leagues)} (identificados com retorno negativo plano no laboratório). Eleva o lucro líquido real em +${profit_improvement:.2f} e o ROI para {opt_roi:.1f}%.",
                            "warning": "Resultados exploratórios — otimização post-hoc na mesma amostra. Aplicar correção Bonferroni (~300 candidatos). Validar em OOS independente.",
                            "exclude_codes": bad_leagues,
                            "original_summary": original_summary,
                            "optimized_summary": opt_res['summary'],
                            "optimized_curve": opt_res['equity_curve']
                        })
            
    # 4. Cross-market Odds Range Optimization
    cross_markets = [
        ('odds_h', 'Mandante (1X2)', {
            'Super Favoritos (<=1.50)': lambda x: x <= 1.50,
            'Favoritos (1.50-2.00)': lambda x: 1.50 < x <= 2.00,
            'Médios (2.00-3.00)': lambda x: 2.00 < x <= 3.00,
            'Zebras (>3.00)': lambda x: x > 3.00
        }),
        ('odds_d', 'Empate (1X2)', {
            'Baixo (<=3.00)': lambda x: x <= 3.00,
            'Médio (3.00-3.80)': lambda x: 3.00 < x <= 3.80,
            'Alto (>3.80)': lambda x: x > 3.80
        }),
        ('odds_a', 'Visitante (1X2)', {
            'Super Favoritos (<=1.50)': lambda x: x <= 1.50,
            'Favoritos (1.50-2.00)': lambda x: 1.50 < x <= 2.00,
            'Médios (2.00-3.00)': lambda x: 2.00 < x <= 3.00,
            'Zebras (>3.00)': lambda x: x > 3.00
        }),
        ('odds_over25', 'Over 2.5 Gols', {
            'Favorito (<=1.70)': lambda x: x <= 1.70,
            'Equilibrado (1.70-2.20)': lambda x: 1.70 < x <= 2.20,
            'Zebra (>2.20)': lambda x: x > 2.20
        }),
        ('odds_under25', 'Under 2.5 Gols', {
            'Favorito (<=1.70)': lambda x: x <= 1.70,
            'Equilibrado (1.70-2.20)': lambda x: 1.70 < x <= 2.20,
            'Zebra (>2.20)': lambda x: x > 2.20
        })
    ]

    linear_exclude_mappers = {
        # Mandante
        ('odds_h', 'Super Favoritos (<=1.50)'): lambda df: df[df['odds_h'] > 1.50],
        ('odds_h', 'Favoritos (1.50-2.00)'): lambda df: df[df['odds_h'] > 2.00],
        ('odds_h', 'Médios (2.00-3.00)'): lambda df: df[df['odds_h'] <= 2.00],
        ('odds_h', 'Zebras (>3.00)'): lambda df: df[df['odds_h'] <= 3.00],
        # Empate
        ('odds_d', 'Baixo (<=3.00)'): lambda df: df[df['odds_d'] > 3.00],
        ('odds_d', 'Médio (3.00-3.80)'): lambda df: df[df['odds_d'] <= 3.00],
        ('odds_d', 'Alto (>3.80)'): lambda df: df[df['odds_d'] <= 3.80],
        # Visitante
        ('odds_a', 'Super Favoritos (<=1.50)'): lambda df: df[df['odds_a'] > 1.50],
        ('odds_a', 'Favoritos (1.50-2.00)'): lambda df: df[df['odds_a'] > 2.00],
        ('odds_a', 'Médios (2.00-3.00)'): lambda df: df[df['odds_a'] <= 2.00],
        ('odds_a', 'Zebras (>3.00)'): lambda df: df[df['odds_a'] <= 3.00],
        # Over 2.5
        ('odds_over25', 'Favorito (<=1.70)'): lambda df: df[df['odds_over25'] > 1.70],
        ('odds_over25', 'Equilibrado (1.70-2.20)'): lambda df: df[df['odds_over25'] > 2.20],
        ('odds_over25', 'Zebra (>2.20)'): lambda df: df[df['odds_over25'] <= 2.20],
        # Under 2.5
        ('odds_under25', 'Favorito (<=1.70)'): lambda df: df[df['odds_under25'] > 1.70],
        ('odds_under25', 'Equilibrado (1.70-2.20)'): lambda df: df[df['odds_under25'] > 2.20],
        ('odds_under25', 'Zebra (>2.20)'): lambda df: df[df['odds_under25'] <= 2.20],
    }

    for field, mkt_name, ranges in cross_markets:
        if field not in df.columns:
            continue
        for r_name, condition_fn in ranges.items():
            mask = df[field].apply(lambda x: condition_fn(x) if (pd.notna(x) and x is not None) else False)
            sub_in_range = df[mask]
            
            if len(sub_in_range) > 0:
                r_profit = sub_in_range['profit'].sum()
                if r_profit < -15.0:
                    # Simulate excluding this range using the exact linear filter from frontend
                    exclude_fn = linear_exclude_mappers.get((field, r_name))
                    if exclude_fn:
                        sub_exclude = exclude_fn(df)
                    else:
                        sub_exclude = df[~mask]
                        
                    if len(sub_exclude) >= 15:
                        opt_res = recalculate_sub_backtest(sub_exclude, initial_bankroll, staking_rule, stake_value)
                        if opt_res:
                            opt_roi = opt_res['summary']['roi']
                            opt_profit = opt_res['summary']['net_profit']
                            if opt_roi > baseline_roi + 1.0 or opt_profit > baseline_profit + 10.0:
                                sug = {
                                    "type": "odds_warning",
                                    "text": f"Evitar apostas quando o mercado de {mkt_name} estiver na faixa {r_name}. Ela gerou um prejuízo acumulado de -${abs(r_profit):.2f} no histórico, puxando o ROI geral para baixo.",
                                    "warning": "Resultados exploratórios — otimização post-hoc na mesma amostra. Aplicar correção Bonferroni (~300 candidatos). Validar em OOS independente.",
                                    "value": f"{field}:{r_name}"
                                }
                                sug["original_summary"] = original_summary
                                sug["optimized_summary"] = opt_res['summary']
                                sug["optimized_curve"] = opt_res['equity_curve']
                                suggestions.append(sug)
            
    return suggestions


def recalculate_sub_backtest(df_sub, initial_bankroll, staking_rule, stake_value):
    """
    Calculates performance metrics for a filtered subset of bets.
    Always uses the user's current staking configuration — never reuses
    historical stakes from the CSV (which may be from a different staking rule).
    """
    if len(df_sub) == 0:
        return None

    # Always recalculate with the user's current stake_value.
    # The CSV may contain stakes from a previous backtest (e.g. Kelly),
    # but the optimization preview must reflect the user's chosen staking rule.
    bankroll = initial_bankroll
    peak_bankroll = initial_bankroll
    max_drawdown = 0.0
    total_staked = 0.0
    wins = 0
    profit_in_stakes = 0.0
    total_bets = len(df_sub)
    dates = df_sub['date'].values
    equity_curve = [{'date': str(dates[0]), 'bankroll': round(initial_bankroll, 2)}]

    for row in df_sub.to_dict('records'):
        stake = float(stake_value)
        bet_won = float(row['profit']) > 0
        bookie_odds = float(row['odds'])
        if stake > 0.01 and bankroll >= stake:
            total_staked += stake
            if bet_won:
                wins += 1
                profit = stake * (bookie_odds - 1.0)
                bankroll += profit
                profit_in_stakes += (bookie_odds - 1.0)
            else:
                profit = -stake
                bankroll += profit
                profit_in_stakes += -1.0
            if bankroll > peak_bankroll:
                peak_bankroll = bankroll
            dd = (peak_bankroll - bankroll) / peak_bankroll if peak_bankroll > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd
            equity_curve.append({'date': str(row['date']), 'bankroll': round(bankroll, 2)})

    win_rate = (wins / total_bets * 100) if total_bets > 0 else 0.0
    net_profit = bankroll - initial_bankroll
    roi = (net_profit / total_staked * 100) if total_staked > 0 else 0.0

    losses = total_bets - wins
    return {
        'summary': {
            'net_profit': round(net_profit, 2),
            'profit_in_stakes': round(profit_in_stakes, 2),
            'roi': round(roi, 2),
            'win_rate': round(win_rate, 1),
            'max_drawdown': round(max_drawdown * 100, 2),
            'total_bets': total_bets,
            'wins': wins,
            'losses': losses
        },
        'equity_curve': equity_curve
    }




def _build_daily_blocks(df):
    """
    Groups bets by calendar day in chronological order.
    Returns a list of dict arrays, one per day, each with keys: odds, prob, won.
    Falls back to individual-bet blocks if date parsing fails.
    """
    try:
        dates = pd.to_datetime(df['date'], errors='coerce')
        if dates.isna().any():
            raise ValueError("Unparseable dates in bet record")
        order = np.argsort(dates)
        sorted_dates = dates.iloc[order]
        sorted_odds = df['odds'].values[order].astype(float)
        sorted_probs = df['prob'].values[order].astype(float)
        sorted_won = df['won'].values[order].astype(bool)
        daily_blocks = []
        i = 0
        while i < len(sorted_dates):
            day = sorted_dates.iloc[i]
            j = i
            while j < len(sorted_dates) and sorted_dates.iloc[j] == day:
                j += 1
            daily_blocks.append({
                'odds': sorted_odds[i:j],
                'prob': sorted_probs[i:j],
                'won': sorted_won[i:j],
            })
            i = j
        return daily_blocks
    except Exception:
        return [{'odds': np.array([o]), 'prob': np.array([p]), 'won': np.array([w])}
                for o, p, w in zip(df['odds'].values, df['prob'].values, df['won'].values)]


def _simulate_path_dependent(day_blocks, n_bets, initial_bankroll, staking_rule, stake_value):
    """
    Simulate a single path with path-dependent stakes.
    Block-bootstrap whole days with replacement until n_bets accumulated,
    computing stakes from current bankroll at each step.
    Returns (trajectory, ruined, half_ruined).
    """
    n_days = len(day_blocks)
    if n_days == 0:
        return [initial_bankroll], False, False

    rng = np.random.default_rng()
    bankroll = initial_bankroll
    ruined = False
    half_ruined = False
    trajectory = [initial_bankroll]
    collected = 0

    while collected < n_bets:
        day = day_blocks[rng.integers(0, n_days)]
        day_odds = day['odds']
        day_prob = day['prob']
        day_won = day['won']
        take = min(len(day_odds), n_bets - collected)

        for i in range(take):
            odds_i = day_odds[i]
            prob_i = day_prob[i]
            won_i = day_won[i]

            if staking_rule == 'fixed':
                stake = stake_value
            elif staking_rule == 'proportional':
                stake = bankroll * (stake_value / 100.0)
            elif staking_rule == 'kelly':
                mult_k = stake_value
                if odds_i > 1.0:
                    f_star = (prob_i * odds_i - 1.0) / (odds_i - 1.0)
                    f_star = max(0.0, min(f_star, 0.20))
                    stake = bankroll * f_star * mult_k
                else:
                    stake = 0.0
            else:
                stake = 0.0

            stake = min(stake, bankroll * 0.10)

            if stake > 0.01 and bankroll >= stake:
                profit = stake * (odds_i - 1.0) if won_i else -stake
                bankroll += profit

            if bankroll < initial_bankroll * 0.10:
                ruined = True
            if bankroll < initial_bankroll * 0.50:
                half_ruined = True

            trajectory.append(bankroll)

        collected += take

    return trajectory, ruined, half_ruined


def run_monte_carlo_simulation(bets_record, initial_bankroll=1000.0, staking_rule='fixed', stake_value=10.0, runs=1000):
    """
    Runs a Monte Carlo simulation (block bootstrap) to assess strategy reliability.

    For fixed staking: uses fast vectorized path (stakes don't depend on bankroll).
    For proportional/kelly: simulates each path individually with path-dependent
    stakes computed from current bankroll at each step.
    """
    if not bets_record or len(bets_record) < 10:
        return None

    df = pd.DataFrame(bets_record)
    df['odds'] = df['odds'].astype(float)
    df['prob'] = df['prob'].astype(float) / 100.0
    df['won'] = df['profit'].astype(float) > 0.0

    n_bets = len(df)

    # Build daily blocks (preserves within-day correlation)
    daily_blocks = _build_daily_blocks(df)

    if staking_rule == 'fixed':
        # Fast path: stakes are constant, pre-compute profits
        profits = np.zeros(n_bets)
        for i in range(n_bets):
            stake = min(stake_value, initial_bankroll * 0.10)
            if stake > 0.01:
                profits[i] = stake * (df['odds'].values[i] - 1.0) if df['won'].values[i] else -stake

        # Convert daily blocks to profit arrays for fast bootstrap
        try:
            profit_blocks = []
            for block in daily_blocks:
                block_profits = np.zeros(len(block['odds']))
                for i in range(len(block['odds'])):
                    stake_f = min(stake_value, initial_bankroll * 0.10)
                    if stake_f > 0.01:
                        block_profits[i] = stake_f * (block['odds'][i] - 1.0) if block['won'][i] else -stake_f
                profit_blocks.append(block_profits)
        except Exception:
            profit_blocks = [np.array([p]) for p in profits]

        # Fast block bootstrap with pre-computed profits
        n_days = len(profit_blocks)
        if n_days > 0:
            rng = np.random.default_rng()
            sampled = np.zeros((runs, n_bets))
            for run in range(runs):
                collected = 0
                while collected < n_bets:
                    day_idx = rng.integers(0, n_days)
                    day_profits = profit_blocks[day_idx]
                    room = n_bets - collected
                    take = min(len(day_profits), room)
                    sampled[run, collected:collected + take] = day_profits[:take]
                    collected += take
            trajectories = initial_bankroll + np.cumsum(sampled, axis=1)
        else:
            trajectories = np.full((runs, n_bets), initial_bankroll)

        ruined_mask = np.any(trajectories < (initial_bankroll * 0.10), axis=1)
        half_ruined_mask = np.any(trajectories < (initial_bankroll * 0.50), axis=1)
        final_bankrolls = trajectories[:, -1]
        final_bankrolls[ruined_mask] = 0.0
        ruined_runs = int(np.sum(ruined_mask))
        half_ruined_runs = int(np.sum(half_ruined_mask))
        profitable_runs = int(np.sum(final_bankrolls > initial_bankroll))
        p95 = float(np.percentile(final_bankrolls, 95))
        p50 = float(np.percentile(final_bankrolls, 50))
        p5 = float(np.percentile(final_bankrolls, 5))
        avg_final = float(np.mean(final_bankrolls))
    else:
        # Path-dependent simulation for proportional and Kelly staking
        ruined_runs = 0
        half_ruined_runs = 0
        profitable_runs = 0
        final_bankrolls_list = []

        for _ in range(runs):
            trajectory, ruined, half_ruined = _simulate_path_dependent(
                daily_blocks, n_bets, initial_bankroll, staking_rule, stake_value
            )
            final = trajectory[-1]
            if ruined:
                final_bankrolls_list.append(0.0)
            else:
                final_bankrolls_list.append(final)
            if ruined:
                ruined_runs += 1
            if half_ruined:
                half_ruined_runs += 1
            if final > initial_bankroll:
                profitable_runs += 1

        final_bankrolls = np.array(final_bankrolls_list)
        p95 = float(np.percentile(final_bankrolls, 95))
        p50 = float(np.percentile(final_bankrolls, 50))
        p5 = float(np.percentile(final_bankrolls, 5))
        avg_final = float(np.mean(final_bankrolls))

    profit_prob = float(profitable_runs / runs * 100.0)
    ruin_prob = float(ruined_runs / runs * 100.0)
    half_ruin_prob = float(half_ruined_runs / runs * 100.0)

    return {
        "runs": runs,
        "profit_probability": round(profit_prob, 1),
        "ruin_probability": round(ruin_prob, 1),
        "half_ruin_probability": round(half_ruin_prob, 1),
        "median_final_bankroll": round(p50, 2),
        "mean_final_bankroll": round(avg_final, 2),
        "percentile_5": round(p5, 2),
        "percentile_95": round(p95, 2),
        "median_net_profit": round(p50 - initial_bankroll, 2),
        "percentile_5_net_profit": round(p5 - initial_bankroll, 2),
        "percentile_95_net_profit": round(p95 - initial_bankroll, 2)
    }


def compute_brier_score(bets_history):
    """
    Calcula o Brier Score do modelo e do mercado (probabilidade implícita das odds).
    Quanto menor o Brier Score, melhor a calibração probabilística.
    """
    if not bets_history or len(bets_history) < 2:
        return {'brier_score': None, 'brier_score_market': None, 'brier_improvement': None}

    n = len(bets_history)
    bs_model = 0.0
    bs_market = 0.0

    for b in bets_history:
        prob_model = float(b.get('prob', 50.0)) / 100.0  # prob is stored as percentage
        odds = float(b.get('odds', 2.0))
        outcome = 1.0 if float(b.get('profit', 0)) > 0 else 0.0

        bs_model += (prob_model - outcome) ** 2

        # Probabilidade implícita do mercado com correção de overround
        prob_raw = 1.0 / odds if odds > 1.0 else 0.5

        # Estimate overround from available odds when possible, otherwise use typical margin
        odds_h = b.get('odds_h')
        odds_d = b.get('odds_d')
        odds_a = b.get('odds_a')
        if odds_h and odds_d and odds_a and all(not pd.isna(x) and x > 1.0 for x in [odds_h, odds_d, odds_a]):
            overround = (1.0 / odds_h + 1.0 / odds_d + 1.0 / odds_a)
        else:
            overround = 1.065  # typical football bookmaker margin ~6.5%

        prob_market = prob_raw / overround if odds > 1.0 else 0.5
        bs_market += (prob_market - outcome) ** 2

    bs_model /= n
    bs_market /= n

    # Melhoria percentual do modelo sobre o mercado (negativo = modelo pior)
    if bs_market > 0:
        brier_improvement = ((bs_market - bs_model) / bs_market) * 100.0
    else:
        brier_improvement = 0.0

    return {
        'brier_score': round(bs_model, 4),
        'brier_score_market': round(bs_market, 4),
        'brier_improvement': round(brier_improvement, 2)
    }


def compute_bootstrap_ci(bets_history, n_resamples=5000, initial_bankroll=None):
    """
    Calcula intervalo de confianca de 95% para ROI e Drawdown via bootstrap.
    Retorna mediana, limites do IC e probabilidade de ROI positivo,
    mais CI para drawdown maximo.
    """
    if not bets_history or len(bets_history) < 5:
        return {
            'bootstrap_roi_median': None,
            'bootstrap_roi_ci_lower': None,
            'bootstrap_roi_ci_upper': None,
            'prob_positive_roi': None,
            'bootstrap_drawdown_median': None,
            'bootstrap_drawdown_ci_lower': None,
            'bootstrap_drawdown_ci_upper': None,
        }

    profits = np.array([float(b.get('profit', 0)) for b in bets_history])
    stakes = np.array([float(b.get('stake', 1)) for b in bets_history])
    n = len(profits)
    avg_stake = np.mean(stakes)

    if avg_stake <= 0:
        avg_stake = 1.0

    # Estimate initial bankroll if not provided
    if initial_bankroll is None:
        initial_bankroll = max(float(np.sum(stakes)) * 1.5, 500.0)

    # Bootstrap vetorizado: gera todos os indices de uma vez
    rng = np.random.default_rng(seed=42)
    indices = rng.choice(n, size=(n_resamples, n), replace=True)

    # Calcula ROI para cada resample
    resampled_profits = profits[indices]  # shape: (n_resamples, n)
    roi_samples = np.sum(resampled_profits, axis=1) / (n * avg_stake) * 100.0

    roi_median = float(np.median(roi_samples))
    ci_lower = float(np.percentile(roi_samples, 2.5))
    ci_upper = float(np.percentile(roi_samples, 97.5))
    prob_positive = float(np.mean(roi_samples > 0))

    # Drawdown bootstrap: max peak-to-trough decline per resample
    cum_equity = initial_bankroll + np.cumsum(resampled_profits, axis=1)
    peak_equity = np.maximum.accumulate(cum_equity, axis=1)
    dd_samples = np.max((peak_equity - cum_equity) / np.maximum(peak_equity, 1.0), axis=1) * 100.0

    dd_median = float(np.median(dd_samples))
    dd_ci_lower = float(np.percentile(dd_samples, 2.5))
    dd_ci_upper = float(np.percentile(dd_samples, 97.5))

    return {
        'bootstrap_roi_median': round(roi_median, 2),
        'bootstrap_roi_ci_lower': round(ci_lower, 2),
        'bootstrap_roi_ci_upper': round(ci_upper, 2),
        'prob_positive_roi': round(prob_positive, 4),
        'bootstrap_drawdown_median': round(dd_median, 2),
        'bootstrap_drawdown_ci_lower': round(dd_ci_lower, 2),
        'bootstrap_drawdown_ci_upper': round(dd_ci_upper, 2),
    }


def compute_power_analysis(roi_pct, odds_mean, n_bets):
    """
    Calcula o tamanho mínimo de amostra necessário para detectar o ROI observado
    com 80% de poder estatístico e alpha=0.05.
    """
    if roi_pct == 0 or n_bets == 0 or odds_mean <= 1.0:
        return {
            'min_sample_size': 99999,
            'sample_sufficient': False,
            'power_ratio': 0.0
        }

    sigma = math.sqrt(odds_mean)  # Desvio padrão dos retornos por unidade apostada
    z_alpha = 1.96   # Para alpha = 0.05 (bicaudal)
    z_beta = 0.84    # Para poder = 0.80
    effect = roi_pct / 100.0  # Converter percentual para proporção

    if abs(effect) < 0.005:  # ROI < 0.5% is practically zero effect, requiring an infinite sample
        return {
            'min_sample_size': 99999,
            'sample_sufficient': False,
            'power_ratio': 0.0
        }

    n_min = ((z_alpha + z_beta) * sigma / effect) ** 2
    if n_min > 99999 or math.isnan(n_min) or math.isinf(n_min):
        n_min = 99999
    else:
        n_min = max(1, int(math.ceil(n_min)))

    power_ratio = n_bets / n_min if n_min > 0 else 0.0

    return {
        'min_sample_size': n_min,
        'sample_sufficient': n_bets >= n_min,
        'power_ratio': round(power_ratio, 2)
    }


def compute_rolling_roi(bets_history, window=None):
    """
    Calcula o ROI em janelas deslizantes proporcionais ao tamanho da liga (20% do histórico).
    Detecta decaimento de edge comparando a última janela com a média geral.
    """
    if not bets_history:
        return {
            'rolling_roi': [],
            'edge_decay_pct': None,
            'edge_decay_alert': None
        }
        
    if window is None:
        # Janela dinâmica: 20% do tamanho da amostra, fixando entre 10 e 100
        window = max(10, min(100, int(len(bets_history) * 0.2)))

    if len(bets_history) < window:
        return {
            'rolling_roi': [],
            'edge_decay_pct': None,
            'edge_decay_alert': None
        }

    profits = np.array([float(b.get('profit', 0)) for b in bets_history])
    stakes = np.array([float(b.get('stake', 1)) for b in bets_history])
    n = len(profits)

    rolling_roi = []
    roi_values = []

    for i in range(window - 1, n):
        window_profits = profits[i - window + 1: i + 1]
        window_stakes = stakes[i - window + 1: i + 1]
        total_staked = np.sum(window_stakes)
        if total_staked > 0:
            roi = float(np.sum(window_profits) / total_staked * 100.0)
        else:
            roi = 0.0
        rolling_roi.append({'bet_index': i, 'roi': round(roi, 2)})
        roi_values.append(roi)

    roi_values = np.array(roi_values)
    avg_roi = float(np.mean(roi_values)) if len(roi_values) > 0 else 0.0
    last_roi = roi_values[-1] if len(roi_values) > 0 else 0.0

    # Calcular decaimento do edge
    # Só faz sentido calcular decaimento se a média histórica for positiva (havia um edge inicial)
    if avg_roi > 0.1:
        edge_decay_pct = ((avg_roi - last_roi) / avg_roi) * 100.0
        # Limitar o decaimento em caso de divisões por números muito pequenos
        edge_decay_pct = max(-999.0, min(999.0, edge_decay_pct))
    else:
        edge_decay_pct = 0.0

    edge_decay_alert = None
    if edge_decay_pct > 30.0:
        edge_decay_alert = (
            f"⚠️ Alerta de Decaimento: O edge da estratégia decaiu {edge_decay_pct:.1f}% "
            f"na última janela de {window} apostas em relação à média histórica. "
            f"ROI médio: {avg_roi:.1f}% → ROI recente: {last_roi:.1f}%."
        )

    return {
        'rolling_roi': rolling_roi,
        'edge_decay_pct': round(edge_decay_pct, 2),
        'edge_decay_alert': edge_decay_alert
    }


def compute_pvalue_binomial(wins, total, odds_mean):
    """
    Calcula o p-value unilateral para testar se o win rate observado é
    significativamente superior ao break-even (1/odds_mean).
    Usa aproximação normal à binomial com CDF via numpy.erf.
    """
    if total <= 0 or odds_mean <= 1.0:
        return 1.0

    p0 = 1.0 / odds_mean  # Probabilidade de break-even
    p_hat = wins / total

    # Denominador da estatística z
    denom = math.sqrt(p0 * (1.0 - p0) / total)
    if denom < 1e-12:
        return 1.0

    z = (p_hat - p0) / denom

    # CDF da normal padrão: Phi(z) = 0.5 * (1 + erf(z / sqrt(2)))
    phi_z = 0.5 * (1.0 + float(math.erf(z / np.sqrt(2.0))))

    # p-value unilateral (H1: p > p0)
    p_value = 1.0 - phi_z
    return round(p_value, 6)


def apply_fdr_correction(p_values):
    """
    Aplica correção de Benjamini-Hochberg (FDR) a uma lista de p-values.
    Retorna p-values ajustados na ordem original.
    """
    if not p_values:
        return []

    m = len(p_values)
    if m == 1:
        return [min(1.0, p_values[0])]

    # Indexar e ordenar
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * m

    # Calcular p-values ajustados
    prev_adj = 1.0
    for rank_idx in range(m - 1, -1, -1):
        orig_idx, pval = indexed[rank_idx]
        rank = rank_idx + 1  # Rank 1-indexed
        adj_p = pval * m / rank
        adj_p = min(adj_p, prev_adj)  # Monotonia: cada ajustado <= o próximo
        adj_p = min(adj_p, 1.0)       # Limitar a 1.0
        adjusted[orig_idx] = round(adj_p, 6)
        prev_adj = adj_p

    return adjusted

# Default EQS weights — calibrated against known strategy performance patterns.
# Updated via calibrate_equity_weights() when >= 5 strategies with OOS data are available.
DEFAULT_EQS_WEIGHTS = {
    'oos': 25, 'bootstrap': 20, 'clv': 15, 'decay': 12,
    'pvalue': 13, 'power': 10, 'brier': 5,
}

def _get_sample_tier(total_bets):
    """Classifica o tamanho da amostra para thresholds adaptativos."""
    if total_bets < 30: return 'tiny'
    if total_bets < 80: return 'small'
    if total_bets < 200: return 'medium'
    return 'large'

def _get_eqt_thresholds(tier):
    """Retorna thresholds por tier para cada métrica do EQS.

    Cada entry: (full_pts_threshold, partial_pts_threshold, zero_pts_threshold, partial_fraction)
    partial_fraction é a fração dos pontos máximos dada no nível parcial.
    """
    return {
        'pvalue': {
            'tiny':    (0.15, 0.30, 4/13),
            'small':   (0.10, 0.20, 4/13),
            'medium':  (0.05, 0.10, 4/13),
            'large':   (0.01, 0.05, 9/13),
        },
        'power': {
            'tiny':    (0.15, 0.30, 5/10),
            'small':   (0.30, 0.50, 5/10),
            'medium':  (0.50, 1.00, 5/10),
            'large':   (1.00, None, None),
        },
        'bootstrap': {
            'tiny':    (-5.0, -10.0, 8/20),
            'small':   (-2.0, -5.0, 8/20),
            'medium':  (0.0, -2.0, 8/20),
            'large':   (1.0, 0.0, 15/20),
        },
        'decay': {
            'tiny':    (-35.0, -50.0, 6/12),
            'small':   (-25.0, -40.0, 6/12),
            'medium':  (-15.0, -25.0, 6/12),
            'large':   (-10.0, -25.0, 6/12),
        },
        'oos': {
            'tiny':    (0.20, 0.10, 8/25),
            'small':   (0.30, 0.15, 8/25),
            'medium':  (0.40, 0.20, 8/25),
            'large':   (0.80, 0.40, 17/25),
        },
    }

def _redistribute_weights(w, missing_keys):
    """Rateia o peso das métricas ausentes entre as métricas ativas.

    Retorna (adjusted_weights_dict, redistributed_max_per_metric_dict).
    """
    active = {k: v for k, v in w.items() if k not in missing_keys}
    missing_weight = sum(w.get(k, 0) for k in missing_keys)
    total_active = sum(active.values())

    if total_active == 0 or missing_weight == 0:
        return dict(w), dict(w)

    adjusted = {}
    redist_max = {}
    for k, base in active.items():
        bonus = round((base / total_active) * missing_weight)
        adjusted[k] = base + bonus
        redist_max[k] = base + bonus

    for k in missing_keys:
        adjusted[k] = w.get(k, 0)
        redist_max[k] = 0

    return adjusted, redist_max


def _pearson_r(x, y):
    """Pure-numpy Pearson correlation (avoids scipy dependency)."""
    x, y = np.array(x, dtype=float), np.array(y, dtype=float)
    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < 3:
        return 0.0
    x, y = x[mask], y[mask]
    xm, ym = x - x.mean(), y - y.mean()
    denom = np.sqrt((xm * xm).sum() * (ym * ym).sum())
    return float((xm * ym).sum() / denom) if denom > 1e-15 else 0.0


def _eqs_metric_scores(summary, oos_summary=None, tier='large'):
    """Compute normalized (0-1) scores for each EQS metric from a single strategy summary.

    Returns dict with keys matching DEFAULT_EQS_WEIGHTS, each value in [0, 1].
    Uses adaptive thresholds from _get_eqt_thresholds when tier != 'large'.
    """
    scores = {}
    thresholds = _get_eqt_thresholds(tier)

    # 1. OOS
    if oos_summary:
        in_sample_roi = summary.get('roi', 0)
        oos_roi = oos_summary.get('roi', 0)
        t = thresholds['oos'][tier]
        if in_sample_roi > 0 and oos_roi > 0:
            ratio = oos_roi / max(in_sample_roi, 0.001)
            if ratio >= t[0]:
                scores['oos'] = 1.0
            elif ratio >= t[1]:
                scores['oos'] = t[2]
            else:
                scores['oos'] = max(0.05, t[2] * 0.4)
        elif oos_roi > 0:
            scores['oos'] = 5 / 25
        else:
            scores['oos'] = 0.0
    else:
        scores['oos'] = 0.0

    # 2. Bootstrap CI
    ci_lower = summary.get('bootstrap_roi_ci_lower')
    if ci_lower is not None:
        t = thresholds['bootstrap'][tier]
        if ci_lower > t[0]:
            scores['bootstrap'] = 1.0
        elif ci_lower > t[1]:
            scores['bootstrap'] = t[2]
        else:
            scores['bootstrap'] = 0.0
    else:
        scores['bootstrap'] = 0.0

    # 3. CLV
    avg_clv = summary.get('avg_clv')
    if avg_clv is not None:
        if avg_clv > 2.0:
            scores['clv'] = 1.0
        elif avg_clv > 0.5:
            scores['clv'] = 10 / 15
        elif avg_clv > 0.0:
            scores['clv'] = 5 / 15
        else:
            scores['clv'] = 0.0
    else:
        scores['clv'] = 0.0

    # 4. Edge Decay
    decay = summary.get('edge_decay_pct')
    if decay is not None:
        t = thresholds['decay'][tier]
        if decay > t[0]:
            scores['decay'] = 1.0
        elif decay > t[1]:
            scores['decay'] = t[2]
        else:
            scores['decay'] = 0.0
    else:
        scores['decay'] = 0.0

    # 5. P-Value
    wins = summary.get('wins', 0)
    total = summary.get('total_bets', 1)
    avg_odds = summary.get('avg_odds', 2.0)
    try:
        p_val = compute_pvalue_binomial(wins, total, avg_odds)
        t = thresholds['pvalue'][tier]
        if p_val < t[0]:
            scores['pvalue'] = 1.0
        elif p_val < t[1]:
            scores['pvalue'] = t[2]
        else:
            scores['pvalue'] = 0.0
    except Exception:
        scores['pvalue'] = 0.0

    # 6. Power Ratio
    pr = summary.get('power_ratio')
    if pr is not None:
        t = thresholds['power'][tier]
        if t[0] is not None and pr >= t[0]:
            scores['power'] = 1.0
        elif t[1] is not None and pr >= t[1]:
            scores['power'] = t[2]
        else:
            scores['power'] = 0.0
    else:
        scores['power'] = 0.0

    # 7. Brier
    brier_imp = summary.get('brier_improvement')
    if brier_imp is not None:
        if brier_imp > 2.0:
            scores['brier'] = 1.0
        elif brier_imp > 0.0:
            scores['brier'] = 3 / 5
        else:
            scores['brier'] = 0.0
    else:
        scores['brier'] = 0.0

    return scores


def calibrate_equity_weights(strategy_results, min_strategies=5):
    """Learn EQS weights from strategy performance data via correlation with OOS ROI.

    Args:
        strategy_results: list of dicts, each with 'summary' and optional 'oos_summary'
        min_strategies: minimum number of strategies required to override defaults

    Returns:
        dict of {metric_name: weight_pct} summing to 100.
        Falls back to DEFAULT_EQS_WEIGHTS if insufficient data or no signal.
    """
    if len(strategy_results) < min_strategies:
        logger.info(f"EQS calibration: {len(strategy_results)} strategies < {min_strategies}, using defaults")
        return dict(DEFAULT_EQS_WEIGHTS)

    metrics = list(DEFAULT_EQS_WEIGHTS.keys())
    # Collect normalized scores and OOS ROI for each strategy
    rows = {m: [] for m in metrics}
    oos_rois = []

    for sr in strategy_results:
        summary = sr.get('summary', {})
        oos = sr.get('oos_summary')
        tier = _get_sample_tier(summary.get('total_bets', 0))
        scores = _eqs_metric_scores(summary, oos, tier)
        oos_roi = (oos or {}).get('roi', summary.get('roi', 0))
        oos_rois.append(oos_roi)
        for m in metrics:
            rows[m].append(scores[m])

    # Pearson correlation of each metric with OOS ROI
    correlations = {}
    for m in metrics:
        r = _pearson_r(rows[m], oos_rois)
        correlations[m] = abs(r)

    total_corr = sum(correlations.values())
    if total_corr < 1e-10:
        logger.info("EQS calibration: all correlations near zero, using defaults")
        return dict(DEFAULT_EQS_WEIGHTS)

    # Normalize to sum to 100
    calibrated = {m: round(correlations[m] / total_corr * 100) for m in metrics}
    # Fix rounding so it sums exactly to 100
    diff = 100 - sum(calibrated.values())
    if diff != 0:
        # Adjust the largest weight
        largest = max(calibrated, key=calibrated.get)
        calibrated[largest] += diff

    logger.info(f"EQS weights calibrated from {len(strategy_results)} strategies: {calibrated}")
    return calibrated


def compute_edge_quality_score(summary, oos_summary=None, weights=None, total_bets=None, min_oos_bets=10):
    """Computes a composite Edge Quality Score (0-100) based on statistical metrics.

    Args:
        summary: dict with backtest summary metrics
        oos_summary: optional OOS validation summary
        weights: optional custom weight dict from calibrate_equity_weights().
                 If None, uses DEFAULT_EQS_WEIGHTS.
        total_bets: optional int — used to determine sample-size tier for adaptive thresholds.
                    Defaults to summary['total_bets'] if not provided.
        min_oos_bets: minimum OOS bets required before the OOS metric is counted.
                      Below this, OOS is marked "insufficient" and excluded from scoring.

    Phase 2: The OOS section now receives true out-of-sample data (models frozen after cutoff date)
    rather than a simple chronological tail slice, eliminating data leakage from the calibration/ML pipeline.

    Phase 3: Adaptive thresholds per sample-size tier, weight redistribution for missing metrics,
    and OOS partial-credit with insufficient-data state.
    """
    w = weights if weights is not None else DEFAULT_EQS_WEIGHTS
    if total_bets is None:
        total_bets = summary.get('total_bets', 0)
    tier = _get_sample_tier(total_bets)
    thresholds = _get_eqt_thresholds(tier)

    score = 0.0
    details = []

    # --- Collect missing metrics for weight redistribution ---
    w_oos = w.get('oos', 25)
    w_bs = w.get('bootstrap', 20)
    w_clv = w.get('clv', 15)
    w_decay = w.get('decay', 12)
    w_pv = w.get('pvalue', 13)
    w_pwr = w.get('power', 10)
    w_brier = w.get('brier', 5)

    missing = set()
    oos_insufficient = False

    avg_clv = summary.get('avg_clv')
    if avg_clv is None:
        missing.add('clv')

    ci_lower = summary.get('bootstrap_roi_ci_lower')
    if ci_lower is None:
        missing.add('bootstrap')

    decay = summary.get('edge_decay_pct')
    if decay is None:
        missing.add('decay')

    pr = summary.get('power_ratio')
    if pr is None:
        missing.add('power')

    brier_imp = summary.get('brier_improvement')
    if brier_imp is None:
        missing.add('brier')

    # Check OOS insufficiency before handling
    oos_bets_count = oos_summary.get('total_bets', 0) if oos_summary else 0
    if oos_summary is None or oos_bets_count < min_oos_bets:
        oos_insufficient = True
        missing.add('oos')

    # Redistribute weights of missing metrics across active ones
    adj_w, redist_max = _redistribute_weights(w, missing)

    # --- 1. Out-of-Sample (OOS) ---
    t_oos = thresholds['oos'][tier]
    effective_w_oos = adj_w.get('oos', 0)

    if oos_insufficient:
        pts = None  # sentinel: excluded from score
        if oos_summary is None:
            msg = f"OOS: Não calculado (requer min {min_oos_bets} apostas)"
        else:
            msg = f"OOS: Amostra insuficiente ({oos_bets_count}/{min_oos_bets} apostas)"
    elif oos_summary:
        in_sample_roi = summary.get('roi', 0)
        oos_roi = oos_summary.get('roi', 0)
        if in_sample_roi > 0 and oos_roi > 0:
            ratio = oos_roi / max(in_sample_roi, 0.001)
            if ratio >= t_oos[0]:
                pts = effective_w_oos
                msg = f"OOS Excelente: ROI {oos_roi:.1f}% (Mantido)"
            elif ratio >= t_oos[1]:
                pts = int(round(effective_w_oos * t_oos[2]))
                msg = f"OOS Bom: ROI {oos_roi:.1f}% (Degradado)"
            else:
                pts = max(1, int(round(effective_w_oos * t_oos[2] * 0.4)))
                msg = f"OOS Fraco: ROI {oos_roi:.1f}% (Queda forte)"
        elif oos_roi > 0:
            pts = int(round(effective_w_oos * 5 / 25))
            msg = f"OOS Positivo ({oos_roi:.1f}%), mas In-Sample Negativo"
        else:
            pts = 0
            msg = f"OOS Falhou: ROI negativo {oos_roi:.1f}%"
    else:
        pts = None
        msg = f"OOS: Dados indisponiveis"

    if pts is not None:
        score += pts
    display_max_oos = effective_w_oos if not oos_insufficient and oos_summary is not None else 0
    details.append({'metric': 'Validação OOS', 'points': pts if pts is not None else 0,
                    'max': display_max_oos, 'message': msg,
                    'insufficient': oos_insufficient})

    # --- 2. Bootstrap CI Lower Bound ---
    t_bs = thresholds['bootstrap'][tier]
    effective_w_bs = adj_w.get('bootstrap', 0)

    if ci_lower is not None:
        if ci_lower > t_bs[0]:
            pts = effective_w_bs
            msg = f"Limite Inferior Forte: {ci_lower:.1f}%"
        elif ci_lower > t_bs[1]:
            pts = int(round(effective_w_bs * t_bs[2]))
            msg = f"Limite Inferior Positivo: {ci_lower:.1f}%"
        else:
            pts = 0
            msg = f"Risco Alto de Ruina: {ci_lower:.1f}%"
    else:
        pts = 0
        msg = "CI Nao Calculado"

    score += pts
    details.append({'metric': 'Bootstrap CI (95%)', 'points': pts,
                    'max': adj_w.get('bootstrap', 0), 'message': msg})

    # --- 3. Closing Line Value (CLV) ---
    effective_w_clv = adj_w.get('clv', 0)

    if avg_clv is not None:
        if avg_clv > 2.0:
            pts = effective_w_clv
            msg = f"CLV Excelente: +{avg_clv:.1f}% (Bate a Linha de Fechamento)"
        elif avg_clv > 0.5:
            pts = int(round(effective_w_clv * 10 / 15))
            msg = f"CLV Positivo: +{avg_clv:.1f}% (Edge Confirmado)"
        elif avg_clv > 0.0:
            pts = int(round(effective_w_clv * 5 / 15))
            msg = f"CLV Marginal: +{avg_clv:.1f}%"
        else:
            pts = 0
            msg = f"CLV Negativo: {avg_clv:.1f}% (Sem Vantagem vs Mercado)"
    else:
        pts = 0
        msg = "CLV Indisponivel (peso redistribuido)"

    score += pts
    details.append({'metric': 'Closing Line Value (CLV)', 'points': pts,
                    'max': effective_w_clv if avg_clv is not None else 0, 'message': msg})

    # --- 4. Edge Decay ---
    t_decay = thresholds['decay'][tier]
    effective_w_decay = adj_w.get('decay', 0)

    if decay is not None:
        if decay > t_decay[0]:
            pts = effective_w_decay
            msg = f"Edge Estavel ({decay:.1f}%)"
        elif decay > t_decay[1]:
            pts = int(round(effective_w_decay * t_decay[2]))
            msg = f"Decaimento Leve ({decay:.1f}%)"
        else:
            pts = 0
            msg = f"Decaimento Severo ({decay:.1f}%)"
    else:
        pts = 0
        msg = "Decay Nao Calculado"

    score += pts
    details.append({'metric': 'Estabilidade Temporal', 'points': pts,
                    'max': adj_w.get('decay', 0), 'message': msg})

    # --- 5. P-Value ---
    t_pv = thresholds['pvalue'][tier]
    effective_w_pv = adj_w.get('pvalue', 0)
    wins = summary.get('wins', 0)
    total = summary.get('total_bets', 1)
    avg_odds = summary.get('avg_odds', 2.0)

    try:
        p_val = compute_pvalue_binomial(wins, total, avg_odds)
        if p_val < t_pv[0]:
            pts = effective_w_pv
            msg = f"Significancia Alta (p={p_val:.3f})"
        elif p_val < t_pv[1]:
            pts = int(round(effective_w_pv * t_pv[2]))
            msg = f"Significancia Boa (p={p_val:.3f})"
        else:
            pts = 0
            msg = f"Resultado Aleatorio (p={p_val:.3f})"
    except Exception:
        pts = 0
        msg = "P-Valor Indisponivel"

    score += pts
    details.append({'metric': 'P-Valor Binomial', 'points': pts,
                    'max': effective_w_pv, 'message': msg})

    # --- 6. Power Ratio ---
    t_pwr = thresholds['power'][tier]
    effective_w_pwr = adj_w.get('power', 0)

    if pr is not None:
        if t_pwr[0] is not None and pr >= t_pwr[0]:
            pts = effective_w_pwr
            msg = f"Amostra Suficiente ({pr:.1f}x)"
        elif t_pwr[1] is not None and pr >= t_pwr[1]:
            pts = int(round(effective_w_pwr * t_pwr[2]))
            msg = f"Amostra Parcial ({pr:.1f}x)"
        else:
            pts = 0
            msg = f"Amostra Insuficiente ({pr:.1f}x)"
    else:
        pts = 0
        msg = "Power Ratio Nao Calculado"

    score += pts
    details.append({'metric': 'Power Analysis (Amostra)', 'points': pts,
                    'max': adj_w.get('power', 0), 'message': msg})

    # --- 7. Brier Score Improvement ---
    effective_w_brier = adj_w.get('brier', 0)

    if brier_imp is not None:
        if brier_imp > 2.0:
            pts = effective_w_brier
            msg = f"Supera Mercado ({brier_imp:.1f}%)"
        elif brier_imp > 0.0:
            pts = int(round(effective_w_brier * 3 / 5))
            msg = f"Ligeira Vantagem ({brier_imp:.1f}%)"
        else:
            pts = 0
            msg = f"Perde pro Mercado ({brier_imp:.1f}%)"
    else:
        pts = 0
        msg = "Brier Nao Calculado"

    score += pts
    details.append({'metric': 'Precisao Brier', 'points': pts,
                    'max': adj_w.get('brier', 0), 'message': msg})

    # --- Final Verdict & Risk Recommendation ---
    # Calculate max possible points: sum of adjusted weights for active metrics
    # (metrics with insufficient data already had their weights redistributed)
    max_pts = sum(adj_w.values())
    # Zero out max for completely absent metrics to avoid frontend confusion
    max_pts_active = sum(
        adj_w.get(k, 0) for k in ['oos', 'bootstrap', 'clv', 'decay', 'pvalue', 'power', 'brier']
        if k not in missing
    )
    if max_pts_active == 0:
        max_pts_active = max_pts

    total_score = int(round((score / max_pts_active) * 100)) if max_pts_active > 0 else 0

    # Tier-specific verdict caveat
    tier_note = ''
    if tier == 'tiny':
        tier_note = f' [Amostra minuscula: {total_bets} apostas — thresholds relaxados. Valide com mais dados.]'
    elif tier == 'small':
        tier_note = f' [Amostra pequena: {total_bets} apostas — thresholds relaxados.]'

    if total_score >= 80:
        verdict = "Aprovado para Dinheiro Real"
        verdict_color = "success"
        kelly_mult = 1.0
        risk_msg = "Sinal Verde. Recomendamos utilizar 1x (Full) ou 0.5x (Half) da fracao de Kelly, respeitando seu limite maximo por aposta (ex: 2%)."
    elif total_score >= 50:
        verdict = "Quarentena / Risco Moderado"
        verdict_color = "warning"
        kelly_mult = 0.25
        risk_msg = "Sinal Amarelo. O modelo tem lucro, mas apresenta falhas de robustez. Recomendamos usar Quarter Kelly (0.25x) ou reduzir sua stake fixa pela metade."
    else:
        verdict = "Rejeitado / Artefato Estatistico"
        verdict_color = "danger"
        kelly_mult = 0.0
        risk_msg = "Sinal Vermelho. O edge e ilusorio ou instavel. Operar apenas em Paper Trading (Apostas Virtuais) ate que o modelo prove consistencia fora da amostra."

    if tier_note:
        risk_msg = tier_note + ' ' + risk_msg

    return {
        'score': total_score,
        'verdict': verdict,
        'verdict_color': verdict_color,
        'kelly_multiplier': kelly_mult,
        'risk_recommendation': risk_msg,
        'breakdown': details,
        'sample_tier': tier,
    }
