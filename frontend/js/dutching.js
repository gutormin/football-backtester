// ==========================================================================
// Dutching Pro Module Logic
// ==========================================================================
var dutchingChartInstance = null;
var dutchingRadarAllOpps = [];

function updateDutchingChart(labels, data) {
    const ctx = document.getElementById('dutching-pie-chart');
    const placeholder = document.getElementById('dutching-pie-placeholder');
    if (!ctx) return;
    
    if (dutchingChartInstance) {
        dutchingChartInstance.destroy();
    }
    
    if (data.length === 0) {
        placeholder.style.display = 'block';
        return;
    }
    
    placeholder.style.display = 'none';
    
    dutchingChartInstance = new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: [
                    'rgba(139, 92, 246, 0.7)',
                    'rgba(52, 211, 153, 0.7)',
                    'rgba(245, 158, 11, 0.7)',
                    'rgba(239, 68, 68, 0.7)',
                    'rgba(59, 130, 246, 0.7)',
                    'rgba(236, 72, 153, 0.7)'
                ],
                borderColor: 'rgba(13, 15, 24, 0.9)',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#9ca3af',
                        font: { size: 10 }
                    }
                }
            }
        }
    });
}

function addDutchingRow(name = "", odd = "", modelProb = 0.0) {
    const container = document.getElementById('dutching-rows-container');
    if (!container) return;
    
    const rowId = 'dutching-row-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    const div = document.createElement('div');
    div.id = rowId;
    div.className = 'dutching-input-row';
    div.style = 'display: grid; grid-template-columns: 1fr 0.8fr auto; gap: 10px; align-items: center;';
    
    div.innerHTML = `
        <input type="text" placeholder="Ex: Placar 1-0" value="${name}" class="dutching-input-name" style="width: 100%; background: var(--bg-darker); border: 1px solid var(--border-color); color: var(--text-primary); padding: 8px; border-radius: 4px; outline: none;" oninput="calculateDutching()">
        <input type="number" placeholder="Odd" value="${odd}" step="0.05" min="1.01" class="dutching-input-odd" style="width: 100%; background: var(--bg-darker); border: 1px solid var(--border-color); color: var(--text-primary); padding: 8px; border-radius: 4px; outline: none;" oninput="calculateDutching()">
        <input type="hidden" class="dutching-input-prob" value="${modelProb}">
        <button type="button" class="btn-clear" onclick="removeDutchingRow('${rowId}')" style="color: var(--text-loss); border-color: rgba(239, 68, 68, 0.2); background: rgba(239, 68, 68, 0.05); padding: 8px 10px;"><i class="fa-solid fa-trash-can"></i></button>
    `;
    
    container.appendChild(div);
    calculateDutching();
}

function removeDutchingRow(rowId) {
    const row = document.getElementById(rowId);
    if (row) {
        row.remove();
    }
    calculateDutching();
}

function calculateDutching() {
    const mode = document.getElementById('dutching-mode-select').value;
    const amount = parseFloat(document.getElementById('dutching-amount-input').value) || 0.0;
    const commission = parseFloat(document.getElementById('dutching-commission-input').value) || 0.0;
    const rows = document.querySelectorAll('.dutching-input-row');
    const allocationList = document.getElementById('dutching-allocation-list');
    
    if (!allocationList) return;
    
    const selections = [];
    let sumProbabilityImplied = 0.0;
    let sumProbabilityReal = 0.0;
    
    rows.forEach(row => {
        const nameInput = row.querySelector('.dutching-input-name');
        const oddInput = row.querySelector('.dutching-input-odd');
        const probInput = row.querySelector('.dutching-input-prob');
        
        const name = nameInput.value.trim() || 'Seleção';
        const odd = parseFloat(oddInput.value) || 0.0;
        const prob = parseFloat(probInput ? probInput.value : 0.0) || 0.0;
        
        if (odd > 1.0) {
            let calculationOdd = odd;
            // Se contiver 'betfair' ou 'exchange' no nome, aplica comissão
            if (name.toLowerCase().includes('betfair') || name.toLowerCase().includes('exchange')) {
                calculationOdd = (odd - 1.0) * (1.0 - commission / 100.0) + 1.0;
            }
            selections.push({ name, odd, calculationOdd, prob });
            sumProbabilityImplied += 1.0 / calculationOdd;
            sumProbabilityReal += prob;
        }
    });
    
    if (selections.length === 0 || sumProbabilityImplied <= 0) {
        allocationList.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 15px;">Adicione seleções válidas com odds > 1.00.</td></tr>`;
        if (document.getElementById('dutching-combined-odd-value')) document.getElementById('dutching-combined-odd-value').innerText = '0.00';
        if (document.getElementById('dutching-real-prob-value')) document.getElementById('dutching-real-prob-value').innerText = '0.00%';
        if (document.getElementById('dutching-edge-value')) document.getElementById('dutching-edge-value').innerText = '+0.00%';
        if (document.getElementById('dutching-profit-value')) document.getElementById('dutching-profit-value').innerText = '$0.00';
        updateDutchingChart([], []);
        return;
    }
    
    const targetProfitLabel = document.getElementById('dutching-result-type-label');
    const amountLabel = document.getElementById('dutching-amount-label');
    
    let totalStake = 0.0;
    let targetProfit = 0.0;
    
    if (mode === 'total_stake') {
        amountLabel.innerText = 'Valor da Stake Total ($)';
        targetProfitLabel.innerText = 'Lucro Líquido';
        totalStake = amount;
        targetProfit = totalStake / sumProbabilityImplied - totalStake;
    } else {
        amountLabel.innerText = 'Valor do Lucro Alvo ($)';
        targetProfitLabel.innerText = 'Stake Total Exigida';
        targetProfit = amount;
        totalStake = targetProfit * sumProbabilityImplied;
    }
    
    allocationList.innerHTML = '';
    const labels = [];
    const stakes = [];
    
    selections.forEach(sel => {
        let selStake = 0.0;
        if (mode === 'total_stake') {
            selStake = totalStake * ( (1.0 / sel.calculationOdd) / sumProbabilityImplied );
        } else {
            selStake = (targetProfit + totalStake) / sel.calculationOdd;
        }
        
        labels.push(sel.name);
        stakes.push(parseFloat(selStake.toFixed(2)));
        
        const isBetfair = sel.name.toLowerCase().includes('betfair') || sel.name.toLowerCase().includes('exchange');
        const netProfit = selStake * sel.calculationOdd - totalStake;
        const commissionText = isBetfair ? ` <span style="font-size: 10px; color: var(--text-muted);">(-${commission}%)</span>` : '';
        
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${sel.name}</strong></td>
            <td>
                <span class="badge" style="background: rgba(255,255,255,0.05); color: var(--text-primary); border: 1px solid var(--border-color);">${sel.odd.toFixed(2)}</span>
                ${isBetfair ? `<span style="font-size: 10px; color: #a78bfa; margin-left: 4px;">(${sel.calculationOdd.toFixed(2)} líq)</span>` : ''}
            </td>
            <td style="color: var(--text-primary); font-weight: 600;">$${selStake.toFixed(2)}</td>
            <td><span style="color: #34d399;">+$${netProfit.toFixed(2)}</span>${commissionText}</td>
        `;
        allocationList.appendChild(tr);
    });
    
    const combinedOdd = sumProbabilityImplied > 0 ? (1.0 / sumProbabilityImplied) : 0.0;
    const realProbPercent = sumProbabilityReal * 100;
    const edge = combinedOdd > 0 ? (sumProbabilityReal * combinedOdd - 1.0) : -1.0;
    const edgePercent = edge * 100;

    const combinedOddEl = document.getElementById('dutching-combined-odd-value');
    if (combinedOddEl) combinedOddEl.innerText = combinedOdd.toFixed(2);

    const realProbEl = document.getElementById('dutching-real-prob-value');
    if (realProbEl) realProbEl.innerText = realProbPercent.toFixed(2) + '%';

    const edgeEl = document.getElementById('dutching-edge-value');
    if (edgeEl) {
        edgeEl.innerText = (edgePercent >= 0 ? '+' : '') + edgePercent.toFixed(2) + '%';
        edgeEl.style.color = edgePercent >= 0 ? '#34d399' : '#f87171';
    }
    
    if (mode === 'total_stake') {
        const profitColor = targetProfit >= 0 ? '#34d399' : '#f87171';
        document.getElementById('dutching-profit-value').style.color = profitColor;
        document.getElementById('dutching-profit-value').innerText = `$${targetProfit.toFixed(2)} (ROI: ${((targetProfit / totalStake) * 100).toFixed(1)}%)`;
    } else {
        document.getElementById('dutching-profit-value').style.color = 'var(--text-primary)';
        document.getElementById('dutching-profit-value').innerText = `$${totalStake.toFixed(2)}`;
    }
    
    updateDutchingChart(labels, stakes);
}

async function runDutchingScan() {
    const btn = document.getElementById('btn-scan-dutching');
    if (!btn) return;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-arrows-rotate spinning"></i> Escaneando...';
    
    try {
        const source = document.getElementById('dutching-source-select')?.value || 'odds_api';
        const strategy = document.getElementById('dutching-strategy-select')?.value || 'fav_short';
        const res = await fetch(`${window.API_BASE_URL || window.location.origin}/api/scan_dutching?source=${source}&strategy=${strategy}`);
        if (!res.ok) throw new Error("Dutching scan failed");
        
        const opps = await res.json();
        dutchingRadarAllOpps = opps;
        
        filterDutchingRadar();
        showToast(`Radar de Dutching atualizado! ${opps.length} oportunidades +EV encontradas.`, "success");
    } catch (err) {
        console.error("Dutching scan error:", err);
        showToast("Erro ao escanear oportunidades de Dutching.", "error");
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-satellite-dish"></i> Atualizar Odds Radar';
    }
}

function filterDutchingRadar() {
    const filterVal = document.querySelector('input[name="dutching-bookie-filter"]:checked').value;
    const tbody = document.getElementById('dutching-radar-list');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    const filtered = dutchingRadarAllOpps.filter(opp => {
        if (filterVal === 'best') return true;
        return opp.bookmaker === filterVal;
    });
    
    window.dutchingRadarFilteredOpps = filtered;
    
    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 20px;">Nenhuma oportunidade +EV correspondente encontrada.</td></tr>`;
        return;
    }
    
    filtered.forEach((opp, index) => {
        const tr = document.createElement('tr');
        const selectionsWithOdds = opp.selections.map((sel, idx) => `${sel} (${opp.odds[idx].toFixed(2)})`).join(' | ');
        
        tr.innerHTML = `
            <td>
                <div><strong>${opp.match}</strong></div>
                <div style="font-size: 11px; color: var(--text-muted);"><i class="fa-solid fa-clock"></i> ${opp.date}</div>
            </td>
            <td><span class="badge badge-info" style="font-size: 10px;">${opp.bookmaker}</span></td>
            <td><div style="font-size: 11px; color: var(--text-secondary);">${opp.market}</div></td>
            <td><div style="font-size: 11px; font-family: monospace; color: #a78bfa;">${selectionsWithOdds}</div></td>
            <td><span style="font-weight: 600; color: var(--text-primary); font-size: 13px;">${opp.dutching_odd.toFixed(2)}</span></td>
            <td><span style="color: #a78bfa; font-weight: 500;">${opp.model_prob}</span></td>
            <td><span style="color: #34d399; font-weight: 700; font-size: 13px;">${opp.edge}</span></td>
            <td>
                <button type="button" class="btn-clear" onclick="loadDutchingOpportunityByIndex(${index})" style="padding: 4px 8px; font-size: 10px; color: #a78bfa; border-color: rgba(167,139,250,0.3); background: rgba(167,139,250,0.05); cursor: pointer;">
                    <i class="fa-solid fa-download"></i> Carregar
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function loadDutchingOpportunityByIndex(index) {
    const opp = window.dutchingRadarFilteredOpps && window.dutchingRadarFilteredOpps[index];
    if (!opp) return;
    
    const container = document.getElementById('dutching-rows-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    opp.selections.forEach((sel, i) => {
        const suffix = opp.bookmaker === 'Betfair Exchange' ? ' (Betfair)' : '';
        const prob = (opp.selections_probs && opp.selections_probs[i]) ? opp.selections_probs[i] : 0.0;
        addDutchingRow(sel + suffix, opp.odds[i], prob);
    });

    const altContainer = document.getElementById('dutching-alternatives-container');
    const altList = document.getElementById('dutching-alternatives-list');
    if (altContainer && altList) {
        altList.innerHTML = '';
        if (opp.alternative_scores && opp.alternative_scores.length > 0) {
            altContainer.style.display = 'block';
            opp.alternative_scores.forEach(alt => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn-clear';
                btn.style = 'padding: 6px 12px; font-size: 11px; border-color: rgba(167, 139, 250, 0.3); background: rgba(167, 139, 250, 0.05); color: #c084fc; cursor: pointer; display: flex; align-items: center; gap: 6px; border-radius: 4px; font-weight: 600;';
                btn.innerHTML = `<i class="fa-solid fa-plus-circle"></i> + Cobrir ${alt.name} <span style="font-size: 10px; color: var(--text-muted); font-weight: normal;">(Odd: ${alt.odd.toFixed(2)} | IA: ${(alt.prob * 100).toFixed(1)}%)</span>`;
                btn.onclick = () => {
                    const suffix = opp.bookmaker === 'Betfair Exchange' ? ' (Betfair)' : '';
                    addDutchingRow(alt.name + suffix, alt.odd, alt.prob);
                    btn.remove();
                    if (altList.children.length === 0) altContainer.style.display = 'none';
                };
                altList.appendChild(btn);
            });
        } else {
            altContainer.style.display = 'none';
        }
    }
    
    showToast(`Oportunidade para ${opp.match} carregada na calculadora!`, "success");
}

// Expose to window
window.addDutchingRow = addDutchingRow;
window.removeDutchingRow = removeDutchingRow;
window.calculateDutching = calculateDutching;
window.runDutchingScan = runDutchingScan;
window.filterDutchingRadar = filterDutchingRadar;
window.loadDutchingOpportunityByIndex = loadDutchingOpportunityByIndex;
// Bot configs and API key functions are defined and exposed in app.js



// --- RESTORED LIVE RADAR CODE ---

