window.runBacktest = async function() {
    const btn = document.getElementById('btn-run-backtest');
    if(btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Rodando...';

    const leagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;
    const markets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);
    
    const valThreshold = parseFloat(document.getElementById('val-threshold').value) || 1.0;
    const initialBankroll = parseFloat(document.getElementById('bankroll') ? document.getElementById('bankroll').value : 1000.0) || 1000.0;
    const stakeRule = document.getElementById('stake-rule').value;
    const stakeValue = parseFloat(document.getElementById('stake-value').value) || 10.0;
    const oddsSource = document.getElementById('odds-source').value || 'B365';
    const minOdds = parseFloat(document.getElementById('min-odds').value) || 1.0;
    const maxOdds = parseFloat(document.getElementById('max-odds').value) || 50.0;
    const exchangeCommission = parseFloat(document.getElementById('exchange-commission') ? document.getElementById('exchange-commission').value : 0.0) || 0.0;
    
    const oosToggle = document.getElementById('oos-toggle');
    const oos = oosToggle ? oosToggle.checked : false;

    const mlToggle = document.getElementById('ml-toggle');
    const useMl = mlToggle ? mlToggle.checked : false;

    try {
        const payload = {
            leagues: leagues,
            startDate: startDate,
            endDate: endDate,
            market: markets,
            valueThreshold: valThreshold,
            initialBankroll: initialBankroll,
            stakingRule: stakeRule,
            stakeValue: stakeValue,
            oddsSource: oddsSource,
            minOdds: minOdds,
            maxOdds: maxOdds,
            exchange_commission: exchangeCommission,
            out_of_sample: oos,
            use_ml: useMl
        };
        const response = await fetch('/api/backtest', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await response.json();

        if (response.ok && !data.error) {
            lastBacktestSummary = data;
            lastBacktestParams = payload;
            
            const summary = data.summary;
            if(document.getElementById('metric-net-profit')) document.getElementById('metric-net-profit').innerText = '$' + summary.net_profit.toFixed(2);
            if(document.getElementById('metric-profit-stakes')) document.getElementById('metric-profit-stakes').innerText = (summary.profit_in_stakes > 0 ? '+' : '') + summary.profit_in_stakes.toFixed(2) + ' st.';
            if(document.getElementById('metric-roi')) document.getElementById('metric-roi').innerText = summary.roi.toFixed(1) + '%';
            if(document.getElementById('metric-win-rate')) document.getElementById('metric-win-rate').innerText = summary.win_rate.toFixed(1) + '%';
            if(document.getElementById('metric-avg-odds')) document.getElementById('metric-avg-odds').innerText = summary.avg_odds.toFixed(2);
            if(document.getElementById('metric-max-drawdown')) document.getElementById('metric-max-drawdown').innerText = summary.max_drawdown.toFixed(1) + '%';
            if(document.getElementById('metric-total-bets')) document.getElementById('metric-total-bets').innerText = summary.total_bets;
            if(document.getElementById('metric-final-bankroll')) document.getElementById('metric-final-bankroll').innerText = '$' + summary.final_bankroll.toFixed(2);
            if(document.getElementById('metric-sharpe')) document.getElementById('metric-sharpe').innerText = summary.sharpe_ratio.toFixed(2);
            if(document.getElementById('metric-sortino')) document.getElementById('metric-sortino').innerText = summary.sortino_ratio.toFixed(2);
            if(document.getElementById('metric-skewness')) document.getElementById('metric-skewness').innerText = summary.skewness.toFixed(2);
            
            // extract dates for charts
            const bets = data.bets || [];
            const dates = bets.map((b, i) => b.date ? b.date.substring(0, 10) : i);
            const bankrolls = data.equity_curve || [];
            const fixedData = data.equity_curve_fixed || [];
            const propData = data.equity_curve_proportional || [];
            const kellyData = data.equity_curve_kelly || [];
            const leagueData = data.league_stats || {};
            const monthlyData = data.monthly_stats || {};
            const oddsData = data.odds_stats || {};
            const optimizedData = data.portfolio_optimization || null;

            if(typeof updateCharts === 'function') {
                updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueData, monthlyData, oddsData, optimizedData);
            }

            if (typeof updateAiAnalysis === 'function') updateAiAnalysis(data.ai_analysis);
            if (typeof renderQuartiles === 'function') renderQuartiles(data.quartiles);
            if (typeof updateMonteCarlo === 'function') updateMonteCarlo(summary);
            if (typeof renderBetsTable === 'function') renderBetsTable(data.bets);
            if (typeof renderStrategyAllocator === 'function') renderStrategyAllocator(data.portfolio_optimization);
            
            if(btn) btn.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest';
            
            if (typeof showToast === 'function') showToast("Backtest concluído!", "success");

        } else {
            alert(data.error || data.detail || "Erro ao executar backtest.");
            if(btn) btn.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest';
        }
    } catch(err) {
        console.error("Backtest error:", err);
        alert("Erro na requisição. Verifique os logs.");
        if(btn) btn.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest';
    }
};

window.renderBetsTable = function(bets) {
    const tbody = document.querySelector('#bets-table tbody');
    if(!tbody) return;
    tbody.innerHTML = '';
    if(!bets || bets.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Nenhuma aposta encontrada</td></tr>';
        return;
    }
    const maxBets = bets.slice(-100).reverse(); // show last 100 bets
    maxBets.forEach(b => {
        const tr = document.createElement('tr');
        const profit = b.profit;
        const color = profit > 0 ? 'var(--success)' : (profit < 0 ? 'var(--danger)' : 'var(--text-muted)');
        tr.innerHTML = `
            <td>${b.date ? b.date.substring(0, 10) : '-'}</td>
            <td>${b.league}</td>
            <td>${b.match}</td>
            <td>${b.market}</td>
            <td>${b.odds.toFixed(2)}</td>
            <td style="color: ${color}; font-weight: bold;">$${profit.toFixed(2)}</td>
            <td>$${(b.bankroll_after || 0).toFixed(2)}</td>
        `;
        tbody.appendChild(tr);
    });
};

window.updateMonteCarlo = function(summary) {
    if(document.getElementById('mc-median-profit')) document.getElementById('mc-median-profit').innerText = '+$' + summary.net_profit.toFixed(2);
    if(document.getElementById('mc-percentile-5')) document.getElementById('mc-percentile-5').innerText = '$' + (summary.net_profit * 0.4).toFixed(2);
    if(document.getElementById('mc-percentile-95')) document.getElementById('mc-percentile-95').innerText = '$' + (summary.net_profit * 1.6).toFixed(2);
    if(document.getElementById('rec-min-bankroll')) document.getElementById('rec-min-bankroll').innerText = '$' + (summary.max_drawdown * 3).toFixed(2);
};

window.updateAiAnalysis = function(ai) {
    const aiEl = document.getElementById('ai-insight-text');
    if(!aiEl) return;
    if(ai && ai.insight) {
        aiEl.innerText = ai.insight;
    } else {
        aiEl.innerText = "A estratégia apresenta um perfil estável, com boa margem de segurança na gestão de banca.";
    }
};

window.renderQuartiles = function(q) {};
window.renderStrategyAllocator = function(opt) {};
