// ==========================================================================
// Dutching Pro Module Logic
// ==========================================================================
var dutchingChartInstance = null;
var dutchingRadarAllOpps = [];
var dutchingSortKey = 'edge';
var dutchingSortAsc = false;

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
        const strategy = document.getElementById('dutching-strategy-select')?.value || 'auto_ia';
        const res = await fetch(`${window.API_BASE_URL || window.location.origin}/api/scan_dutching?source=${source}&strategy=${strategy}`);
        if (!res.ok) throw new Error("Dutching scan failed");

        const opps = await res.json();
        dutchingRadarAllOpps = opps;

        // Detect API error responses (backend returns error objects instead of opportunities)
        if (opps.length === 1 && opps[0].error) {
            showToast(opps[0].message, "error");
            filterDutchingRadar();
            return;
        }

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
    const searchInput = document.getElementById('dutching-search-input');
    const searchQuery = searchInput ? searchInput.value.trim().toLowerCase() : '';
    const tbody = document.getElementById('dutching-radar-list');
    if (!tbody) return;

    tbody.innerHTML = '';

    let filtered = dutchingRadarAllOpps.filter(opp => {
        if (filterVal === 'best') return true;
        return opp.bookmaker === filterVal;
    });

    // Apply text search filter
    if (searchQuery) {
        filtered = filtered.filter(opp => {
            return opp.match.toLowerCase().includes(searchQuery) ||
                   (opp.date && opp.date.toLowerCase().includes(searchQuery)) ||
                   (opp.market && opp.market.toLowerCase().includes(searchQuery)) ||
                   (opp.bookmaker && opp.bookmaker.toLowerCase().includes(searchQuery));
        });
    }
    
    // Apply sorting
    filtered.sort((a, b) => {
        let valA, valB;
        if (dutchingSortKey === 'match') {
            // Sort by date then time, then by match name as tiebreaker
            valA = (a.match_date_sort || '') + 'T' + (a.match_time_sort || '00:00');
            valB = (b.match_date_sort || '') + 'T' + (b.match_time_sort || '00:00');
            if (valA === valB) {
                valA = a.match.toLowerCase();
                valB = b.match.toLowerCase();
            }
        } else if (dutchingSortKey === 'bookmaker') {
            valA = (a.bookmaker || '').toLowerCase();
            valB = (b.bookmaker || '').toLowerCase();
        } else if (dutchingSortKey === 'odd') {
            valA = a.dutching_odd;
            valB = b.dutching_odd;
        } else if (dutchingSortKey === 'prob') {
            valA = parseFloat(a.model_prob) || 0;
            valB = parseFloat(b.model_prob) || 0;
        } else if (dutchingSortKey === 'edge') {
            valA = a.raw_edge;
            valB = b.raw_edge;
        } else {
            return 0;
        }
        
        if (valA < valB) return dutchingSortAsc ? -1 : 1;
        if (valA > valB) return dutchingSortAsc ? 1 : -1;
        return 0;
    });
    
    window.dutchingRadarFilteredOpps = filtered;
    
    if (filtered.length === 0) {
        const msg = searchQuery
            ? `Nenhum resultado encontrado para "${searchQuery}".`
            : 'Nenhuma oportunidade +EV correspondente encontrada.';
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 20px;">${msg}</td></tr>`;
        return;
    }

    filtered.forEach((opp, index) => {
        const tr = document.createElement('tr');
        const selectionsWithOdds = opp.selections.map((sel, idx) => `${sel} (${opp.odds[idx].toFixed(2)})`).join(' | ');
        const homeTeam = opp.match.split(' vs ')[0] || '—';

        tr.innerHTML = `
            <td>
                <div style="font-size: 14px; font-weight: 700; color: var(--text-primary);">${opp.match}</div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 2px;"><i class="fa-solid fa-clock"></i> ${opp.date}</div>
            </td>
            <td><span style="font-size: 12px; font-weight: 500; color: var(--text-secondary);">${homeTeam}</span></td>
            <td><span class="badge badge-info" style="font-size: 11px;">${opp.bookmaker}</span></td>
            <td><div style="font-size: 12px; color: var(--text-secondary);">${opp.market}</div></td>
            <td><div style="font-size: 11px; font-family: monospace; color: #a78bfa;">${selectionsWithOdds}</div></td>
            <td><span style="font-weight: 600; color: var(--text-primary); font-size: 13px;">${opp.dutching_odd.toFixed(2)}</span></td>
            <td><span style="color: #a78bfa; font-weight: 500; font-size: 13px;">${opp.model_prob}</span></td>
            <td><span style="color: #34d399; font-weight: 700; font-size: 13px;">${opp.edge}</span></td>
            <td>
                <button type="button" class="btn-clear" onclick="loadDutchingOpportunityByIndex(${index})" style="padding: 6px 10px; font-size: 11px; color: #a78bfa; border-color: rgba(167,139,250,0.3); background: rgba(167,139,250,0.05); cursor: pointer;">
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

function sortDutchingRadar(key) {
    if (dutchingSortKey === key) {
        dutchingSortAsc = !dutchingSortAsc;
    } else {
        dutchingSortKey = key;
        dutchingSortAsc = (key === 'match') ? true : false;
    }

    // Update header sort indicators
    const table = document.getElementById('dutching-radar-table');
    if (table) {
        table.querySelectorAll('th.sortable').forEach(th => {
            th.classList.remove('sorted-asc', 'sorted-desc');
        });
        const activeTh = table.querySelector(`th[data-sort-key="${key}"]`);
        if (activeTh) {
            activeTh.classList.add(dutchingSortAsc ? 'sorted-asc' : 'sorted-desc');
        }
    }

    filterDutchingRadar();
}

function toggleDutchingGuide() {
    const guide = document.getElementById('dutching-strategies-guide');
    if (guide) {
        guide.style.display = guide.style.display === 'none' ? 'block' : 'none';
    }
}

// ── Dutching Backtest ──────────────────────────────────────────────────

var dutchingBtChartInstance = null;

async function loadDutchingBtLeagues() {
    const select = document.getElementById('dutching-bt-leagues');
    if (!select) return;
    try {
        const res = await fetch(`${window.API_BASE_URL || window.location.origin}/api/leagues?source=footballdata`);
        if (!res.ok) return;
        const leagues = await res.json();
        select.innerHTML = '';
        leagues.forEach(l => {
            const opt = document.createElement('option');
            opt.value = l.code;
            opt.textContent = l.name || l.code;
            // Pre-select common leagues
            if (['BRAZIL_SERIE_A', 'BRAZIL_SERIE_B', 'E0', 'SP1', 'ARG'].includes(l.code)) {
                opt.selected = true;
            }
            select.appendChild(opt);
        });
    } catch (e) {
        console.warn('Failed to load Dutching BT leagues:', e);
    }
}

async function runDutchingBacktest() {
    const btn = document.getElementById('btn-run-dutching-bt');
    const statusEl = document.getElementById('dutching-bt-status');
    const resultsEl = document.getElementById('dutching-bt-results');

    if (!btn || !statusEl) return;

    const leagueSelect = document.getElementById('dutching-bt-leagues');
    const selectedLeagues = Array.from(leagueSelect.selectedOptions).map(o => o.value);
    if (selectedLeagues.length === 0) {
        statusEl.innerHTML = '<span style="color: #f87171;">Selecione pelo menos 1 liga.</span>';
        return;
    }

    const strategySelect = document.getElementById('dutching-bt-strategies');
    const selectedStrategies = Array.from(strategySelect.selectedOptions).map(o => o.value);
    if (selectedStrategies.length === 0) {
        statusEl.innerHTML = '<span style="color: #f87171;">Selecione pelo menos 1 estratégia.</span>';
        return;
    }

    const startDate = document.getElementById('dutching-bt-start').value;
    const endDate = document.getElementById('dutching-bt-end').value;
    const stakeValue = parseFloat(document.getElementById('dutching-bt-stake').value) || 100;
    const minEdgePct = parseFloat(document.getElementById('dutching-bt-edge').value) || 0;
    const stakingRule = document.getElementById('dutching-bt-staking').value;
    const initialBankroll = parseFloat(document.getElementById('dutching-bt-bankroll').value) || 10000;

    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-arrows-rotate spinning"></i> Rodando...';
    statusEl.innerHTML = '<span style="color: #a78bfa;">Processando backtest cronológico... Isso pode levar até 2 minutos.</span>';
    resultsEl.style.display = 'none';

    try {
        const payload = {
            leagues: selectedLeagues,
            startDate: startDate,
            endDate: endDate,
            strategies: selectedStrategies,
            initialBankroll: initialBankroll,
            stakeValue: stakeValue,
            stakingRule: stakingRule,
            minEdge: minEdgePct / 100.0,
            maxOverround: 0.92,
            maxLegs: 8,
            minSelections: 3,
        };

        const res = await fetch(`${window.API_BASE_URL || window.location.origin}/api/backtest_dutching`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Erro desconhecido' }));
            throw new Error(err.detail || 'Backtest failed');
        }

        const data = await res.json();
        if (data.error) {
            throw new Error(data.error);
        }

        renderDutchingBacktestResults(data);
        statusEl.innerHTML = '<span style="color: #34d399;"><i class="fa-solid fa-circle-check"></i> Backtest concluído!</span>';
        showToast('Backtest Dutching concluído!', 'success');
    } catch (err) {
        console.error('Dutching backtest error:', err);
        statusEl.innerHTML = `<span style="color: #f87171;"><i class="fa-solid fa-circle-exclamation"></i> ${err.message}</span>`;
        showToast('Erro no backtest Dutching: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-play"></i> Rodar Backtest Dutching';
    }
}

function renderDutchingBacktestResults(data) {
    const resultsEl = document.getElementById('dutching-bt-results');
    if (!resultsEl) return;
    resultsEl.style.display = 'block';

    // Summary cards
    const summary = data.summary || {};
    const summaryEl = document.getElementById('dutching-bt-summary');
    summaryEl.innerHTML = `
        <div style="background: rgba(139,92,246,0.1); border: 1px solid rgba(139,92,246,0.2); padding: 12px; border-radius: 6px; text-align: center;">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Total de Dutchings</div>
            <div style="font-size: 20px; font-weight: 700; color: var(--text-primary);">${summary.total_bets || 0}</div>
        </div>
        <div style="background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2); padding: 12px; border-radius: 6px; text-align: center;">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Win Rate</div>
            <div style="font-size: 20px; font-weight: 700; color: #34d399;">${summary.win_rate || 0}%</div>
        </div>
        <div style="background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.2); padding: 12px; border-radius: 6px; text-align: center;">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">Lucro Total</div>
            <div style="font-size: 20px; font-weight: 700; color: ${(summary.net_profit || 0) >= 0 ? '#34d399' : '#f87171'};">
                $${(summary.net_profit || 0).toFixed(2)}
            </div>
        </div>
        <div style="background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.2); padding: 12px; border-radius: 6px; text-align: center;">
            <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase;">ROI</div>
            <div style="font-size: 20px; font-weight: 700; color: ${(summary.roi || 0) >= 0 ? '#34d399' : '#f87171'};">
                ${(summary.roi || 0) >= 0 ? '+' : ''}${(summary.roi || 0).toFixed(1)}%
            </div>
        </div>
    `;

    // Strategy breakdown table
    const tbody = document.getElementById('dutching-bt-strategy-tbody');
    tbody.innerHTML = '';
    const breakdown = data.strategy_breakdown || {};
    for (const [key, s] of Object.entries(breakdown)) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong style="color: #a78bfa;">${s.label || key}</strong></td>
            <td>${s.total_bets}</td>
            <td style="color: ${s.win_rate >= 25 ? '#34d399' : '#f87171'};">${s.win_rate}%</td>
            <td style="color: ${s.net_profit >= 0 ? '#34d399' : '#f87171'}; font-weight: 600;">$${s.net_profit.toFixed(2)}</td>
            <td style="color: ${s.roi >= 0 ? '#34d399' : '#f87171'};">${s.roi >= 0 ? '+' : ''}${s.roi}%</td>
            <td style="color: var(--text-muted);">${s.avg_edge_realized >= 0 ? '+' : ''}${s.avg_edge_realized}%</td>
            <td style="color: #f87171;">${s.max_drawdown}%</td>
        `;
        tbody.appendChild(tr);
    }

    // Equity curve chart
    renderDutchingBtEquityChart(breakdown);

    // Coverage analysis (from first strategy with data)
    const coverageEl = document.getElementById('dutching-bt-coverage');
    let hasCoverage = false;
    for (const [key, s] of Object.entries(breakdown)) {
        const cov = s.coverage_analysis;
        if (cov && (cov.most_hit_scores?.length > 0 || cov.most_missed_scores?.length > 0)) {
            const hitsEl = document.getElementById('dutching-bt-top-hits');
            const missesEl = document.getElementById('dutching-bt-top-misses');

            hitsEl.innerHTML = cov.most_hit_scores.slice(0, 8).map(
                sc => `<span style="display: inline-block; margin: 2px; padding: 3px 8px; background: rgba(52,211,153,0.08); border: 1px solid rgba(52,211,153,0.2); border-radius: 4px;">${sc.score} <strong style="color: #34d399;">${sc.hits}x</strong></span>`
            ).join('') || '<span style="color: var(--text-muted);">Nenhum acerto registrado</span>';

            missesEl.innerHTML = cov.most_missed_scores.slice(0, 8).map(
                sc => `<span style="display: inline-block; margin: 2px; padding: 3px 8px; background: rgba(248,113,113,0.08); border: 1px solid rgba(248,113,113,0.2); border-radius: 4px;">${sc.score} <strong style="color: #f87171;">errou ${sc.misses}x</strong></span>`
            ).join('') || '<span style="color: var(--text-muted);">Nenhum erro registrado</span>';

            hasCoverage = true;
            break;
        }
    }
    if (coverageEl) coverageEl.style.display = hasCoverage ? 'block' : 'none';
}

function renderDutchingBtEquityChart(breakdown) {
    const ctx = document.getElementById('dutching-bt-equity-chart');
    if (!ctx) return;

    if (dutchingBtChartInstance) {
        dutchingBtChartInstance.destroy();
    }

    const colors = ['#a78bfa', '#34d399', '#f59e0b', '#3b82f6', '#ec4899', '#10b981', '#06b6d4'];
    const datasets = [];
    let ci = 0;

    for (const [key, s] of Object.entries(breakdown)) {
        const curve = s.equity_curve || [];
        if (curve.length < 2) continue;

        const color = colors[ci % colors.length];
        datasets.push({
            label: s.label || key,
            data: curve.map((p, i) => ({ x: i, y: p.bankroll })),
            borderColor: color,
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.2,
        });
        ci++;
    }

    if (datasets.length === 0) return;

    dutchingBtChartInstance = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'linear',
                    title: { display: true, text: 'Aposta #', color: '#9ca3af', font: { size: 10 } },
                    ticks: { color: '#9ca3af', font: { size: 9 } },
                    grid: { color: 'rgba(255,255,255,0.03)' },
                },
                y: {
                    title: { display: true, text: 'Bankroll ($)', color: '#9ca3af', font: { size: 10 } },
                    ticks: { color: '#9ca3af', font: { size: 9 } },
                    grid: { color: 'rgba(255,255,255,0.03)' },
                },
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { color: '#9ca3af', font: { size: 10 }, boxWidth: 12, padding: 8 },
                },
            },
        },
    });
}

// Load leagues on Dutching tab switch (attach to existing switchTab or init)
(function() {
    const origSwitchTab = window.switchTab;
    if (origSwitchTab) {
        window.switchTab = function(tabId) {
            origSwitchTab(tabId);
            if (tabId === 'tab-dutching') {
                loadDutchingBtLeagues();
            }
        };
    }
    // Also try loading on page init
    window.addEventListener('load', function() {
        setTimeout(loadDutchingBtLeagues, 2000);
    });
})();

// Expose to window
window.addDutchingRow = addDutchingRow;
window.removeDutchingRow = removeDutchingRow;
window.calculateDutching = calculateDutching;
window.runDutchingScan = runDutchingScan;
window.filterDutchingRadar = filterDutchingRadar;
window.loadDutchingOpportunityByIndex = loadDutchingOpportunityByIndex;
window.sortDutchingRadar = sortDutchingRadar;
window.toggleDutchingGuide = toggleDutchingGuide;
window.runDutchingBacktest = runDutchingBacktest;
window.loadDutchingBtLeagues = loadDutchingBtLeagues;
// Bot configs and API key functions are defined and exposed in app.js



// --- RESTORED LIVE RADAR CODE ---

