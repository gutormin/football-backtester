import re

with open('app.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

# First, remove my hacky wrappers from the bottom of app.js
app_js = re.sub(r'const originalRunBacktestForRisk = window\.runBacktest;[\s\S]*$', '', app_js)

# Second, find updateAiAnalysis call inside runBacktest and inject the logic
inject_code = """
            updateAiAnalysis(data.ai_analysis);
            if (window.renderBetsTable) window.renderBetsTable(data.bets);
            if (window.updateMonteCarlo) window.updateMonteCarlo(data.summary);
            if (window.renderStrategyAllocator && data.portfolio_optimization) window.renderStrategyAllocator(data.portfolio_optimization);
            if (window.updateRiskManagement) window.updateRiskManagement(data.ai_analysis, data.summary);
            
            // Populating stat-validation-grid explicitly
            if (data.summary) {
                const s = data.summary;
                const panel = document.getElementById('stat-validation-panel');
                const grid = document.getElementById('stat-validation-grid');
                if (panel && grid) {
                    panel.style.display = 'block';
                    grid.innerHTML = `
                        <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                            <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Índice de Sharpe</div>
                            <div style="font-size: 18px; font-weight: bold; color: ${s.sharpe_ratio > 1 ? 'var(--success)' : 'var(--text-primary)'}">${s.sharpe_ratio !== undefined ? s.sharpe_ratio.toFixed(2) : 0}</div>
                        </div>
                        <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                            <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Índice de Sortino</div>
                            <div style="font-size: 18px; font-weight: bold; color: ${s.sortino_ratio > 1.5 ? 'var(--success)' : 'var(--text-primary)'}">${s.sortino_ratio !== undefined ? s.sortino_ratio.toFixed(2) : 0}</div>
                        </div>
                        <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                            <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Skewness (Assimetria)</div>
                            <div style="font-size: 18px; font-weight: bold;">${s.skewness !== undefined ? s.skewness.toFixed(2) : 0}</div>
                        </div>
                        <div style="background: rgba(255,255,255,0.02); padding: 15px; border-radius: var(--border-radius);">
                            <div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 5px;">Max Drawdown</div>
                            <div style="font-size: 18px; font-weight: bold; color: var(--danger);">${s.max_drawdown !== undefined ? s.max_drawdown.toFixed(1) : 0}%</div>
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
"""

if 'updateAiAnalysis(data.ai_analysis);' in app_js:
    app_js = app_js.replace('updateAiAnalysis(data.ai_analysis);', inject_code)

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(app_js)

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()
html = html.replace('app.js?v=17', 'app.js?v=18')
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)
