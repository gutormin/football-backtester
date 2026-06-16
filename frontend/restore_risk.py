import re

with open('app.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

impl_script = """

// REDEFINE updateRiskManagement
window.updateRiskManagement = function(ai, summary) {
    if (!ai || !summary) return;
    
    const formatDollar = (val) => {
        if (val === undefined || val === null) return '--';
        const sign = val < 0 ? '-' : '';
        return sign + '$' + Math.abs(val).toFixed(2);
    };

    // Risco de Ruína
    const ruinProb = ai.monte_carlo && ai.monte_carlo.ruin_probability !== undefined 
        ? ai.monte_carlo.ruin_probability.toFixed(1) + '%' 
        : '--';
    const elRuin = document.getElementById('gr-ruin-prob');
    if (elRuin) {
        elRuin.innerText = ruinProb;
        if (ai.monte_carlo && ai.monte_carlo.ruin_probability > 5) {
            elRuin.style.color = 'var(--danger)';
        } else {
            elRuin.style.color = 'var(--success)';
        }
    }
    
    // Drawdown Máximo
    const elDd = document.getElementById('gr-max-drawdown');
    if (elDd) {
        elDd.innerText = summary.max_drawdown !== undefined ? summary.max_drawdown.toFixed(1) + '%' : '--';
        if (summary.max_drawdown > 20) {
            elDd.style.color = 'var(--danger)';
        } else {
            elDd.style.color = 'var(--warning)';
        }
    }
    
    // Sharpe Ratio
    const elSharpe = document.getElementById('gr-sharpe');
    if (elSharpe) {
        elSharpe.innerText = summary.sharpe_ratio !== undefined ? summary.sharpe_ratio.toFixed(2) : '--';
        if (summary.sharpe_ratio > 1) {
            elSharpe.style.color = 'var(--success)';
        } else {
            elSharpe.style.color = 'var(--text-primary)';
        }
    }
    
    // Stake Recomendada
    let recStake = '--';
    if (ai.staking_recommendation && ai.staking_recommendation.recommended_stake_pct) {
        recStake = ai.staking_recommendation.recommended_stake_pct.toFixed(1) + '%';
    }
    const elRecStake = document.getElementById('gr-rec-stake');
    if (elRecStake) {
        elRecStake.innerText = recStake;
        elRecStake.style.color = 'var(--success)';
    }
    const elRecBox = document.getElementById('gr-rec-stake-box');
    if (elRecBox) elRecBox.innerText = recStake !== '--' ? recStake + ' da Banca' : '--';
    
    // Monte Carlo Probabilities
    if (ai.monte_carlo) {
        const mc1 = document.getElementById('gr-mc-prob-profit');
        if (mc1) mc1.innerText = ai.monte_carlo.profit_probability !== undefined ? ai.monte_carlo.profit_probability.toFixed(1) + '%' : '--';
        
        const mc2 = document.getElementById('gr-mc-median-profit');
        if (mc2) mc2.innerText = formatDollar(ai.monte_carlo.median_net_profit);
        
        const mc3 = document.getElementById('gr-mc-p5-profit');
        if (mc3) mc3.innerText = formatDollar(ai.monte_carlo.percentile_5_net_profit);
        
        const mc4 = document.getElementById('gr-mc-p95-profit');
        if (mc4) mc4.innerText = formatDollar(ai.monte_carlo.percentile_95_net_profit);
    }
    
    // Advanced Stats
    const s1 = document.getElementById('gr-sortino');
    if (s1) s1.innerText = summary.sortino_ratio !== undefined ? summary.sortino_ratio.toFixed(2) : '--';
    
    const s2 = document.getElementById('gr-skewness');
    if (s2) s2.innerText = summary.skewness !== undefined ? summary.skewness.toFixed(2) : '--';
    
    const s3 = document.getElementById('gr-edge-decay');
    if (s3) s3.innerText = summary.edge_decay_pct !== undefined && summary.edge_decay_pct !== null ? summary.edge_decay_pct.toFixed(1) + '%' : '--';
    
    const s4 = document.getElementById('gr-pvalue');
    if (s4) s4.innerText = summary.p_value !== undefined && summary.p_value !== null ? summary.p_value.toFixed(4) : '--';
    
    // AI Advice
    const ai1 = document.getElementById('gr-ai-advice');
    if (ai1) ai1.innerText = ai.risk_recommendation || 'Execução bem-sucedida. Recomenda-se cautela.';
    
    // Bankroll Advice
    if (ai.staking_recommendation) {
        const b1 = document.getElementById('gr-min-bankroll');
        if (b1) b1.innerText = formatDollar(ai.staking_recommendation.min_recommended_bankroll);
        
        const b2 = document.getElementById('gr-bankroll-justification');
        if (b2) b2.innerText = ai.staking_recommendation.justification || '';
    }
};

const originalRunBacktestForRisk = window.runBacktest;
window.runBacktest = async function() {
    await originalRunBacktestForRisk.apply(this, arguments);
    
    // Execute risk management update
    if (window.lastBacktestSummary && window.lastBacktestSummary.ai_analysis && window.lastBacktestSummary.summary) {
        window.updateRiskManagement(window.lastBacktestSummary.ai_analysis, window.lastBacktestSummary.summary);
    }
};

"""

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(app_js + impl_script)

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()
html = html.replace('app.js?v=16', 'app.js?v=17')
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)
