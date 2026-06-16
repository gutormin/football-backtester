import re

# Fix app.js
with open('app.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

impl_script = """

// REDEFINE updateAiAnalysis
window.updateAiAnalysis = function(ai) {
    if (!ai) return;

    // Se existe status de erro (e.g., insufficient_data), apenas mostramos uma msg
    if (ai.status === 'insufficient_data') {
        document.getElementById('risk-empty-state').style.display = 'none';
        document.getElementById('risk-content').style.display = 'block';
        document.getElementById('eqs-score').innerText = '--';
        document.getElementById('eqs-score').parentElement.style.borderColor = 'var(--text-muted)';
        document.getElementById('eqs-verdict').innerText = 'Dados Insuficientes';
        document.getElementById('eqs-verdict').style.color = 'var(--text-muted)';
        document.getElementById('eqs-recommendation').innerText = ai.report || ai.message;
        document.getElementById('eqs-breakdown').innerHTML = '';
        return;
    }

    document.getElementById('risk-empty-state').style.display = 'none';
    document.getElementById('risk-content').style.display = 'block';
    
    document.getElementById('eqs-score').innerText = Math.round(ai.score || 0);
    
    let colorHex = 'var(--success)';
    if (ai.verdict_color === 'warning') colorHex = 'var(--warning)';
    if (ai.verdict_color === 'danger') colorHex = 'var(--danger)';
    
    document.getElementById('eqs-score').parentElement.style.borderColor = colorHex;
    document.getElementById('eqs-verdict').innerText = ai.verdict || 'Avaliando...';
    document.getElementById('eqs-verdict').style.color = colorHex;
    document.getElementById('eqs-recommendation').innerText = ai.risk_recommendation || '';
    
    const bd = document.getElementById('eqs-breakdown');
    bd.innerHTML = '';
    if (ai.breakdown && Array.isArray(ai.breakdown)) {
        ai.breakdown.forEach(metric => {
            let mColor = 'var(--success)';
            if (metric.color === 'warning') mColor = 'var(--warning)';
            if (metric.color === 'danger') mColor = 'var(--danger)';
            
            const div = document.createElement('div');
            div.className = 'breakdown-card';
            div.style.background = 'rgba(0,0,0,0.2)';
            div.style.padding = '15px';
            div.style.borderRadius = 'var(--border-radius)';
            div.style.borderLeft = `3px solid ${mColor}`;
            
            div.innerHTML = `
                <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); margin-bottom: 5px;">${metric.name || ''}</div>
                <div style="font-size: 16px; font-weight: bold; margin-bottom: 5px;">${metric.value || ''}</div>
                <div style="font-size: 12px; color: var(--text-secondary);">${metric.desc || ''}</div>
            `;
            bd.appendChild(div);
        });
    }
};

// We also need to populate stat-validation-grid, let's inject it into runBacktest
const originalRunBacktest = window.runBacktest;
window.runBacktest = async function() {
    // let's wrap it to populate stat-validation-grid after it finishes
    await originalRunBacktest.apply(this, arguments);
    
    // Check if summary is available in lastBacktestSummary
    if (window.lastBacktestSummary && window.lastBacktestSummary.summary) {
        const s = window.lastBacktestSummary.summary;
        const panel = document.getElementById('stat-validation-panel');
        const grid = document.getElementById('stat-validation-grid');
        if (panel && grid) {
            panel.style.display = 'block';
            grid.innerHTML = `
                <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                    <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Índice de Sharpe</div>
                    <div style="font-size: 18px; font-weight: bold; color: ${s.sharpe_ratio > 1 ? 'var(--success)' : 'var(--text-primary)'}">${s.sharpe_ratio || 0}</div>
                </div>
                <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                    <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Índice de Sortino</div>
                    <div style="font-size: 18px; font-weight: bold; color: ${s.sortino_ratio > 1.5 ? 'var(--success)' : 'var(--text-primary)'}">${s.sortino_ratio || 0}</div>
                </div>
                <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                    <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Skewness (Assimetria)</div>
                    <div style="font-size: 18px; font-weight: bold;">${s.skewness || 0}</div>
                </div>
                <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                    <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Max Drawdown</div>
                    <div style="font-size: 18px; font-weight: bold; color: var(--danger);">${s.max_drawdown || 0}%</div>
                </div>
                <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                    <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Máx. Redes Consecutivos</div>
                    <div style="font-size: 18px; font-weight: bold; color: var(--danger);">${s.max_consec_losses || 0}</div>
                </div>
                <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                    <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Máx. Greens Consecutivos</div>
                    <div style="font-size: 18px; font-weight: bold; color: var(--success);">${s.max_consec_wins || 0}</div>
                </div>
            `;
        }
    }
};

"""

# Remove old window.updateAiAnalysis definition before appending to avoid confusion
app_js = re.sub(
    r'window\.updateAiAnalysis = function\(ai\) \{[\s\S]*?\}\s*;\s*',
    '',
    app_js
)

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(app_js + impl_script)

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()
html = html.replace('app.js?v=15', 'app.js?v=16')
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)
