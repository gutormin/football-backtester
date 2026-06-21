import os

target_file = r"frontend\app.js"
portfolio_js = """

// --- Portfolio Backtesting ---
let portfolioEquityChart = null;

async function runPortfolioBacktest() {
    const checkboxes = document.querySelectorAll('.portfolio-checkbox:checked');
    const strategyIds = Array.from(checkboxes).map(cb => cb.value);
    
    if (strategyIds.length === 0) {
        showToast('Selecione pelo menos uma estratégia para rodar o Portfólio.', 'warning');
        return;
    }
    
    const riskMethod = document.getElementById('portfolio-risk-method').value;
    
    // Show Loading
    showToast('Rodando Portfólio. Isso pode levar alguns segundos...', 'info');
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/portfolio_backtest`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                strategy_ids: strategyIds,
                initial_bankroll: 1000.0,
                risk_method: riskMethod
            })
        });
        
        const data = await res.json();
        
        if (data.error) {
            showToast(data.error, 'error');
            return;
        }
        
        showToast('Portfólio calculado com sucesso!', 'success');
        
        // Switch to Laboratory Tab
        switchTab('tab-laboratory');
        
        // Hide standard Laboratory panels
        document.getElementById('standard-metrics-grid').style.display = 'none';
        
        // Find other major containers and hide them if they exist
        const mainCharts = document.querySelector('.main-charts');
        if (mainCharts) mainCharts.style.display = 'none';
        
        const stakingPanel = document.getElementById('staking-comparison-panel');
        if (stakingPanel) stakingPanel.style.display = 'none';
        
        const quartilesPanel = document.getElementById('quartiles-panel');
        if (quartilesPanel) quartilesPanel.style.display = 'none';
        
        const resultsTableSection = document.querySelector('.results-table-section');
        if (resultsTableSection) resultsTableSection.style.display = 'none';
        
        // Find other generic grid wrappers around charts
        const chartCards = document.querySelectorAll('.chart-card');
        chartCards.forEach(c => {
            if(c.parentElement && c.parentElement.style.display !== 'none' && c.parentElement.id !== 'portfolio-results-panel') {
                // If it's part of a generic layout, we just hide the parent
                if (c.parentElement.tagName === 'DIV' && c.parentElement.className === 'metrics-grid') {
                    // ignore, handled
                } else if (!c.closest('#portfolio-results-panel')) {
                     c.closest('div[style*="display: grid"]').style.display = 'none';
                }
            }
        });

        // Show Portfolio Panel
        document.getElementById('portfolio-results-panel').style.display = 'block';
        
        // Update Metrics
        document.getElementById('port-metric-bankroll').innerText = `$${data.final_bankroll.toFixed(2)}`;
        document.getElementById('port-metric-profit').innerText = `$${data.net_profit.toFixed(2)}`;
        
        const roiEl = document.getElementById('port-metric-roi');
        roiEl.innerText = `${data.total_roi.toFixed(2)}%`;
        roiEl.style.color = data.total_roi > 0 ? '#10b981' : '#ef4444';
        
        document.getElementById('port-metric-dd').innerText = `${data.max_drawdown.toFixed(2)}%`;
        
        // Render Chart
        renderPortfolioChart(data.equity_curve);
        
        // Render Table
        const tbody = document.getElementById('portfolio-breakdown-tbody');
        tbody.innerHTML = '';
        
        Object.values(data.strategy_breakdown).forEach(st => {
            const tr = document.createElement('tr');
            
            const stakeVal = st.recommended_stake;
            let stakeBadge = `<span style="color:var(--text-muted)">Aguarde Sinal</span>`;
            if (stakeVal > 0) {
                stakeBadge = `<span style="background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 4px 8px; border-radius: 4px; font-weight: bold;">$${stakeVal.toFixed(2)}</span>`;
            }
            
            tr.innerHTML = `
                <td><strong style="color:var(--text-primary)">${st.name}</strong><br><span style="font-size:11px;color:var(--text-muted)">Apostas: ${st.bets} | Lucro Histórico: $${st.profit.toFixed(2)}</span></td>
                <td><span style="color: ${st.win_rate >= 50 ? '#10b981' : '#ef4444'}">${st.win_rate.toFixed(1)}%</span></td>
                <td>${stakeBadge}</td>
            `;
            tbody.appendChild(tr);
        });
        
    } catch (e) {
        console.error(e);
        showToast('Erro ao rodar Portfólio', 'error');
    }
}

function renderPortfolioChart(equityCurve) {
    const ctx = document.getElementById('portfolio-equity-chart').getContext('2d');
    
    if (portfolioEquityChart) {
        portfolioEquityChart.destroy();
    }
    
    const dates = equityCurve.map(e => e.date);
    const bankrolls = equityCurve.map(e => e.bankroll);
    
    portfolioEquityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                label: 'Banca Total do Portfólio',
                data: bankrolls,
                borderColor: '#8b5cf6',
                backgroundColor: 'rgba(139, 92, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                pointRadius: 0,
                pointHoverRadius: 4,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true, labels: { color: '#e2e8f0' } },
                tooltip: { mode: 'index', intersect: false }
            },
            scales: {
                x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });
}
"""

with open(target_file, "a", encoding="utf-8") as f:
    f.write(portfolio_js)

print("Appended JS logic successfully.")
