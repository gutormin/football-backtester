// ==========================================================================
// Dutching Pro Module Logic
// ==========================================================================
var dutchingChartInstance = null;
var dutchingRadarAllOpps = [];
var dutchingSortKey = 'edge';
var dutchingSortAsc = false;
// Sync with window so demo and live scan share the same reference
window.dutchingRadarAllOpps = dutchingRadarAllOpps;

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

    // ── Kelly stake recommendation ──
    renderKellyRecommendation(combinedOdd, realProbPercent, edge, selections);
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
        window.dutchingRadarAllOpps = opps;

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
    const checkedRadio = document.querySelector('input[name="dutching-bookie-filter"]:checked');
    const filterVal = checkedRadio ? checkedRadio.value : 'best';
    const searchInput = document.getElementById('dutching-search-input');
    const searchQuery = searchInput ? searchInput.value.trim().toLowerCase() : '';
    const tbody = document.getElementById('dutching-radar-list');
    if (!tbody) return;

    tbody.innerHTML = '';

    // Always read from window to pick up demo data and live scan data
    const allOpps = window.dutchingRadarAllOpps || dutchingRadarAllOpps;
    const totalOpps = allOpps.length;

    // Quality Score minimum filter
    const minQualityEl = document.getElementById('dutching-min-quality');
    const minQuality = minQualityEl ? parseInt(minQualityEl.value) : 0;

    // Only real odds filter
    const onlyRealEl = document.getElementById('dutching-only-real');
    const onlyReal = onlyRealEl ? onlyRealEl.checked : false;

    let filtered = allOpps.filter(opp => {
        // Bookmaker filter
        if (filterVal !== 'best' && opp.bookmaker !== filterVal) return false;
        // Quality score filter
        const qs = opp.quality_score;
        if (minQuality > 0 && (qs === undefined || qs === null || qs < minQuality)) return false;
        // Only real CS odds filter
        if (onlyReal && opp.odds_source_type !== 'real') return false;
        return true;
    });

    // Update count label
    const countEl = document.getElementById('dutching-quality-count');
    if (countEl && totalOpps > 0) {
        const shown = filtered.length;
        let filters = [];
        if (minQuality > 0) filters.push(`score ≥ ${minQuality}`);
        if (onlyReal) filters.push('só reais');
        const filterStr = filters.length > 0 ? ` (${filters.join(', ')})` : '';
        countEl.textContent = `${shown} de ${totalOpps} partidas${filterStr}`;
    }

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
        tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 20px;">${msg}</td></tr>`;
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
            <td><span class="badge badge-info" style="font-size: 11px;">${opp.bookmaker}</span>${opp.odds_source_type === 'real' ? ' <span style="font-size: 9px; padding: 1px 4px; border-radius: 2px; background: rgba(52,211,153,0.15); color: #34d399; font-weight: 700;" title="Odds reais de Correct Score desta casa — apostáveis diretamente">CS REAL</span>' : ' <span style="font-size: 9px; padding: 1px 4px; border-radius: 2px; background: rgba(245,158,11,0.12); color: #f59e0b;" title="Odds de CS estimadas pelo modelo a partir do mercado Over/Under 2.5 desta casa. NÃO são odds reais de Correct Score — a casa pode ter valores diferentes.">EST (base O/U)</span>'}</td>
            <td><div style="font-size: 12px; color: var(--text-secondary);">${opp.market}</div></td>
            <td><div style="font-size: 11px; font-family: monospace; color: #a78bfa;">${selectionsWithOdds}</div></td>
            <td><span style="font-weight: 600; color: var(--text-primary); font-size: 13px;">${opp.dutching_odd.toFixed(2)}</span></td>
            <td><span style="color: #a78bfa; font-weight: 500; font-size: 13px;">${opp.model_prob}</span></td>
            <td><span style="color: #34d399; font-weight: 700; font-size: 13px;">${opp.edge}</span></td>
            <td style="text-align: center;">
                ${opp.quality_verdict ? `<span style="font-size: 10px; padding: 2px 8px; border-radius: 3px; font-weight: 700; background: ${opp.quality_verdict_color || '#f87171'}20; color: ${opp.quality_verdict_color || '#f87171'}; border: 1px solid ${opp.quality_verdict_color || '#f87171'}40;" title="${opp.quality_verdict_label || ''} | Score: ${opp.quality_score}/100">${opp.quality_verdict_icon || ''} ${opp.quality_score || '—'}</span>` : '<span style="color: var(--text-muted); font-size: 10px;">—</span>'}
            </td>
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

    // ── Alternatives with decision badges ──
    const altContainer = document.getElementById('dutching-alternatives-container');
    const altList = document.getElementById('dutching-alternatives-list');
    if (altContainer && altList) {
        altList.innerHTML = '';
        if (opp.alternative_scores && opp.alternative_scores.length > 0) {
            altContainer.style.display = 'block';
            opp.alternative_scores.forEach(alt => {
                const rec = alt.recommendation || 'neutral';
                const badgeColors = {
                    'add':     { bg: 'rgba(52,211,153,0.12)', border: 'rgba(52,211,153,0.3)', text: '#34d399', icon: 'fa-circle-plus', label: 'ADD' },
                    'neutral': { bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.3)', text: '#f59e0b', icon: 'fa-circle', label: 'NEUTRO' },
                    'skip':    { bg: 'rgba(248,113,113,0.06)', border: 'rgba(248,113,113,0.15)', text: 'rgba(248,113,113,0.45)', icon: 'fa-circle-minus', label: 'PULAR' },
                };
                const bc = badgeColors[rec] || badgeColors['neutral'];
                const edgeChangeStr = alt.edge_change != null ? `${alt.edge_change >= 0 ? '+' : ''}${(alt.edge_change * 100).toFixed(1)}%` : '';
                const opacity = rec === 'skip' ? '0.55' : '1';

                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn-clear';
                btn.style = `padding: 6px 12px; font-size: 11px; border: 1px solid ${bc.border}; background: ${bc.bg}; color: ${bc.text}; cursor: pointer; display: flex; align-items: center; gap: 6px; border-radius: 4px; font-weight: 600; opacity: ${opacity}; transition: opacity 0.2s;`;
                btn.title = alt.reason || `Edge change: ${edgeChangeStr}`;
                btn.innerHTML = `<i class="fa-solid ${bc.icon}"></i> + Cobrir ${alt.name} <span style="font-size: 10px; font-weight: normal;">(Odd: ${alt.odd.toFixed(2)} | IA: ${(alt.prob * 100).toFixed(1)}%)</span><span style="font-size: 9px; padding: 1px 5px; border-radius: 3px; background: ${bc.border}; color: ${bc.text}; margin-left: 2px;">${bc.label} ${edgeChangeStr}</span>`;
                btn.onclick = () => {
                    const suffix = opp.bookmaker === 'Betfair Exchange' ? ' (Betfair)' : '';
                    addDutchingRow(alt.name + suffix, alt.odd, alt.prob);
                    btn.remove();
                    if (altList.children.length === 0) altContainer.style.display = 'none';
                };
                btn.onmouseenter = () => { btn.style.opacity = '1'; };
                btn.onmouseleave = () => { btn.style.opacity = opacity; };
                altList.appendChild(btn);
            });
        } else {
            altContainer.style.display = 'none';
        }
    }

    // ── Quality Score card ──
    renderDutchingQualityCard(opp);

    // Guardar oportunidade carregada para recálculo com odds editadas
    window.currentDutchingOpp = opp;
    // Esconder resultado de recálculo anterior
    const recalcEl = document.getElementById('dutching-recalc-result');
    if (recalcEl) recalcEl.style.display = 'none';

    showToast(`Oportunidade para ${opp.match} carregada na calculadora!`, "success");
}

// ── Recalcular Quality Score com odds editadas pelo usuário ──
async function recalculateDutchingQuality() {
    const resultEl = document.getElementById('dutching-recalc-result');
    if (!resultEl) return;

    // Ler as linhas atuais da calculadora
    const rows = document.querySelectorAll('.dutching-input-row');
    const selections = [];
    const odds = [];
    rows.forEach(row => {
        const nameInput = row.querySelector('.dutching-input-name');
        const oddInput = row.querySelector('.dutching-input-odd');
        const name = nameInput ? nameInput.value.trim().replace(' (Betfair)', '') : '';
        const odd = oddInput ? parseFloat(oddInput.value) : 0;
        if (odd > 1.0 && name) {
            selections.push(name);
            odds.push(odd);
        }
    });

    if (odds.length < 2) {
        resultEl.style.display = 'block';
        resultEl.innerHTML = '<div style="background: rgba(248,113,113,0.1); border: 1px solid rgba(248,113,113,0.3); padding: 12px; border-radius: 6px; color: #f87171; font-size: 12px;">⚠️ Adicione ao menos 2 seleções com odds válidas (> 1.00).</div>';
        return;
    }

    const opp = window.currentDutchingOpp || {};

    // Montar probs por seleção (mapear pelas seleções originais quando possível)
    let selectionsProbs = null;
    if (opp.selections && opp.selections_probs) {
        selectionsProbs = selections.map(sel => {
            const idx = opp.selections.indexOf(sel);
            if (idx >= 0 && opp.selections_probs[idx] != null) return opp.selections_probs[idx];
            // Placar novo adicionado — buscar nos alternativos
            if (opp.alternative_scores) {
                const alt = opp.alternative_scores.find(a => a.name === sel);
                if (alt) return alt.prob;
            }
            return null;
        });
        // Se algum placar não tem prob, invalidar o array (usa fallback)
        if (selectionsProbs.some(p => p == null)) selectionsProbs = null;
    }

    const minQualityEl = document.getElementById('dutching-min-quality');
    const minQuality = minQualityEl ? parseInt(minQualityEl.value) : 60;

    resultEl.style.display = 'block';
    resultEl.innerHTML = '<div style="color: #a78bfa; font-size: 12px; padding: 8px;"><i class="fa-solid fa-arrows-rotate spinning"></i> Recalculando...</div>';

    try {
        const res = await fetch(`${window.API_BASE_URL || window.location.origin}/api/recalculate_dutching_quality`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                selections,
                odds,
                selections_probs: selectionsProbs,
                real_prob: selectionsProbs ? null : (opp.raw_edge != null && opp.dutching_odd ? (opp.raw_edge + 1) / opp.dutching_odd : null),
                profile_confidence: opp.profile_confidence || 0.0,
                market_divergence: opp.market_divergence || 0.0,
                has_real_odds: opp.odds_source_type === 'real',
                hours_to_kickoff: opp.hours_to_kickoff || null,
                min_quality: minQuality,
                min_edge: 0.0,
            }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Erro HTTP ${res.status}`);
        }

        const data = await res.json();
        renderRecalcResult(data);
    } catch (err) {
        resultEl.innerHTML = `<div style="background: rgba(248,113,113,0.1); border: 1px solid rgba(248,113,113,0.3); padding: 12px; border-radius: 6px; color: #f87171; font-size: 12px;">Erro: ${err.message}</div>`;
    }
}
window.recalculateDutchingQuality = recalculateDutchingQuality;

function renderRecalcResult(data) {
    const resultEl = document.getElementById('dutching-recalc-result');
    if (!resultEl) return;

    const passes = data.passes_filter;
    const edgeColor = data.edge >= 0 ? '#34d399' : '#f87171';
    const scoreColor = data.quality_score >= 70 ? '#34d399' : (data.quality_score >= 55 ? '#a78bfa' : '#f59e0b');
    const verdictColor = data.quality_verdict_color || '#f87171';

    const bannerBg = passes ? 'rgba(52,211,153,0.1)' : 'rgba(248,113,113,0.1)';
    const bannerBorder = passes ? 'rgba(52,211,153,0.35)' : 'rgba(248,113,113,0.35)';
    const bannerColor = passes ? '#34d399' : '#f87171';
    const bannerIcon = passes ? 'fa-circle-check' : 'fa-circle-xmark';
    const bannerText = passes
        ? `✅ PASSA NO FILTRO — Score ${data.quality_score} ≥ ${data.min_quality}. Vale a pena apostar!`
        : `❌ NÃO PASSA — Score ${data.quality_score} < ${data.min_quality}. Melhor não apostar com essas odds.`;

    resultEl.innerHTML = `
        <div style="background: ${bannerBg}; border: 1px solid ${bannerBorder}; padding: 12px 16px; border-radius: 8px; margin-bottom: 10px; display: flex; align-items: center; gap: 10px;">
            <i class="fa-solid ${bannerIcon}" style="color: ${bannerColor}; font-size: 20px;"></i>
            <span style="color: ${bannerColor}; font-weight: 700; font-size: 13px;">${bannerText}</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;">
            <div style="background: rgba(139,92,246,0.08); border: 1px solid rgba(139,92,246,0.2); padding: 12px; border-radius: 6px; text-align: center;">
                <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px;">Odd Combinada</div>
                <div style="font-size: 20px; font-weight: 700; color: #c084fc;">${data.dutching_odd.toFixed(2)}</div>
            </div>
            <div style="background: rgba(52,211,153,0.08); border: 1px solid rgba(52,211,153,0.2); padding: 12px; border-radius: 6px; text-align: center;">
                <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px;">Edge</div>
                <div style="font-size: 20px; font-weight: 700; color: ${edgeColor};">${data.edge_pct >= 0 ? '+' : ''}${data.edge_pct.toFixed(1)}%</div>
            </div>
            <div style="background: rgba(167,139,250,0.08); border: 1px solid rgba(167,139,250,0.2); padding: 12px; border-radius: 6px; text-align: center;">
                <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px;">Quality Score</div>
                <div style="font-size: 20px; font-weight: 700; color: ${scoreColor};">${data.quality_score}</div>
            </div>
            <div style="background: rgba(255,255,255,0.02); border: 1px solid ${verdictColor}40; padding: 12px; border-radius: 6px; text-align: center;">
                <div style="font-size: 10px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px;">Veredito</div>
                <div style="font-size: 13px; font-weight: 700; color: ${verdictColor};">${data.quality_verdict_icon || ''} ${data.quality_verdict_label || '—'}</div>
            </div>
        </div>
        ${data.quality_breakdown ? `<div style="margin-top: 10px; font-size: 10px; color: var(--text-muted);">
            Componentes: Edge ${data.quality_breakdown.edge_sharpe || 0} · Robustez ${data.quality_breakdown.bootstrap_robustness || 0} · Perfil ${data.quality_breakdown.profile_confidence || 0} · Odd ${data.quality_breakdown.odd_quality || 0} · Mercado ${data.quality_breakdown.market_divergence || 0} · Diversidade ${data.quality_breakdown.selection_diversity || 0}
        </div>` : ''}
    `;
}

function renderDutchingQualityCard(opp) {
    const card = document.getElementById('dutching-quality-card');
    if (!card) return;

    const qs = opp.quality_score;
    const qv = opp.quality_verdict;
    const qvl = opp.quality_verdict_label;
    const qvc = opp.quality_verdict_color;
    const qvi = opp.quality_verdict_icon;
    const qb = opp.quality_breakdown;

    if (qs == null) {
        card.style.display = 'none';
        return;
    }

    card.style.display = 'block';

    // Score bar color
    let barColor = '#f87171';
    if (qs >= 70) barColor = '#34d399';
    else if (qs >= 55) barColor = '#f59e0b';
    else if (qs >= 40) barColor = '#f97316';

    card.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
            <span style="font-size: 24px;">${qvi || ''}</span>
            <div>
                <div style="font-size: 14px; font-weight: 700; color: var(--text-primary);">Quality Score: <span style="color: ${barColor};">${qs}/100</span></div>
                <div style="font-size: 12px; font-weight: 600; color: ${qvc || '#f87171'};">${qvl || 'SKIP'}</div>
            </div>
        </div>
        <div style="background: rgba(255,255,255,0.04); border-radius: 4px; height: 8px; overflow: hidden; margin-bottom: 12px;">
            <div style="background: ${barColor}; height: 100%; width: ${qs}%; border-radius: 4px; transition: width 0.5s ease;"></div>
        </div>
        ${qb ? `
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; font-size: 10px; color: var(--text-muted);">
            <div><span style="color: var(--text-secondary);">Edge Sharpe:</span> ${qb.edge_sharpe}</div>
            <div><span style="color: var(--text-secondary);">Robustez:</span> ${qb.bootstrap_robustness}</div>
            <div><span style="color: var(--text-secondary);">Perfil:</span> ${qb.profile_confidence}</div>
            <div><span style="color: var(--text-secondary);">Odds:</span> ${qb.odd_quality}</div>
            <div><span style="color: var(--text-secondary);">Mercado:</span> ${qb.market_divergence}</div>
            <div><span style="color: var(--text-secondary);">Diversidade:</span> ${qb.selection_diversity}</div>
        </div>
        ` : ''}
        <div style="margin-top: 6px; font-size: 9px; color: var(--text-muted);">
            <span style="color: #a78bfa;">Fonte odds:</span> ${opp.odds_source_type === 'real' ? '🟢 CS Real (API)' : '🟡 Estimada (O/U 2.5)'}
        </div>
        <div style="margin-top: 8px; font-size: 10px; color: var(--text-muted);">
            <span style="color: #a78bfa;">Perfil IA:</span> ${opp.game_profile || '—'}
            ${opp.edge_prob_positive != null ? ` · <span style="color: #a78bfa;">P(edge&gt;0):</span> ${(opp.edge_prob_positive * 100).toFixed(0)}%` : ''}
        </div>
    `;
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

// ── Kelly Criterion recommendation ──────────────────────────────────

function renderKellyRecommendation(dutchingOdd, modelProbPct, edge, selections) {
    const card = document.getElementById('dutching-kelly-card');
    if (!card) return;

    if (edge <= 0 || dutchingOdd <= 1.01 || selections.length === 0) {
        card.style.display = 'none';
        return;
    }

    card.style.display = 'block';

    const bankrollInput = document.getElementById('dutching-bankroll-input');
    const bankroll = parseFloat(bankrollInput?.value) || 1000.0;
    const kellyFracInput = document.getElementById('dutching-kelly-fraction');
    const kellyFraction = parseFloat(kellyFracInput?.value) || 0.25;
    const maxExposureInput = document.getElementById('dutching-max-exposure');
    const maxExposure = parseFloat(maxExposureInput?.value) || 5.0;

    // Full Kelly
    const fullKelly = edge / (dutchingOdd - 1.0);
    const fracKelly = fullKelly * kellyFraction;
    const cappedKelly = Math.min(fracKelly, maxExposure / 100);

    // Get edge_prob_positive from quality card if available
    const edgeProbEl = document.getElementById('dutching-quality-card');
    let confMult = 1.0;
    if (edgeProbEl) {
        const text = edgeProbEl.textContent || '';
        const match = text.match(/P\(edge>0\):\s*(\d+)%/);
        if (match) {
            const pPos = parseInt(match[1]) / 100;
            if (pPos < 0.65) confMult = 0;
            else if (pPos < 0.80) confMult = 0.5;
            else if (pPos < 0.90) confMult = 0.75;
            else confMult = 1.0;
        }
    }

    const adjKelly = cappedKelly * confMult;
    const stake = bankroll * adjKelly;

    // Risk level
    const exposurePct = (stake / bankroll * 100);
    let riskLevel, riskColor;
    if (exposurePct <= 1.0) { riskLevel = 'Conservador'; riskColor = '#34d399'; }
    else if (exposurePct <= 2.5) { riskLevel = 'Moderado'; riskColor = '#f59e0b'; }
    else if (exposurePct <= 5.0) { riskLevel = 'Agressivo'; riskColor = '#f97316'; }
    else { riskLevel = 'Máximo'; riskColor = '#f87171'; }

    const selectionsAllocation = [];
    const overround = selections.reduce((s, sel) => s + 1.0 / sel.calculationOdd, 0);
    selections.forEach(sel => {
        const selStake = stake * (1.0 / sel.calculationOdd) / overround;
        selectionsAllocation.push({ name: sel.name, stake: selStake });
    });

    card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 13px; font-weight: 700; color: var(--text-primary);"><i class="fa-solid fa-coins" style="color: #f59e0b;"></i> Gestão de Banca (Kelly)</span>
            <span style="font-size: 11px; padding: 2px 8px; border-radius: 3px; font-weight: 700; color: ${riskColor}; background: ${riskColor}15; border: 1px solid ${riskColor}40;">${riskLevel}</span>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px;">
            <div style="background: rgba(255,255,255,0.02); padding: 8px; border-radius: 4px; text-align: center;">
                <div style="font-size: 9px; color: var(--text-muted);">Stake Recomendada</div>
                <div style="font-size: 18px; font-weight: 700; color: #f59e0b;">$${stake.toFixed(2)}</div>
                <div style="font-size: 9px; color: var(--text-muted);">${exposurePct.toFixed(2)}% da banca</div>
            </div>
            <div style="background: rgba(255,255,255,0.02); padding: 8px; border-radius: 4px; text-align: center;">
                <div style="font-size: 9px; color: var(--text-muted);">Kelly Cheio</div>
                <div style="font-size: 16px; font-weight: 700; color: var(--text-primary);">${(fullKelly * 100).toFixed(1)}%</div>
                <div style="font-size: 9px; color: var(--text-muted);">1/${(1/kellyFraction).toFixed(0)} Kelly = ${(fracKelly * 100).toFixed(1)}%</div>
            </div>
            <div style="background: rgba(255,255,255,0.02); padding: 8px; border-radius: 4px; text-align: center;">
                <div style="font-size: 9px; color: var(--text-muted);">Lucro Esperado</div>
                <div style="font-size: 16px; font-weight: 700; color: #34d399;">+$${(stake * edge).toFixed(2)}</div>
                <div style="font-size: 9px; color: var(--text-muted);">EV +${(edge * 100).toFixed(2)}%</div>
            </div>
        </div>
        <details style="font-size: 10px; color: var(--text-muted); margin-top: 5px;">
            <summary style="cursor: pointer; color: var(--text-secondary);">Alocação por seleção</summary>
            <div style="margin-top: 5px; display: flex; flex-wrap: wrap; gap: 4px;">
                ${selectionsAllocation.map(s => `<span style="padding: 2px 6px; background: rgba(255,255,255,0.03); border-radius: 3px;">${s.name}: <strong>$${s.stake.toFixed(2)}</strong></span>`).join('')}
            </div>
        </details>
    `;
}

// ── Dutching Backtest ──────────────────────────────────────────────────

var dutchingBtChartInstance = null;

async function loadDutchingBtLeagues() {
    const container = document.getElementById('dutching-bt-leagues-container');
    if (!container) return;
    try {
        // Load leagues from both sources
        const [resFP, resDF] = await Promise.allSettled([
            fetch(`${window.API_BASE_URL || window.location.origin}/api/leagues?source=futpython`),
            fetch(`${window.API_BASE_URL || window.location.origin}/api/leagues?source=footballdata`),
        ]);

        let leagues = [];
        const seenNames = new Set();

        // FutPython first (has real CS odds) — priority
        if (resFP.status === 'fulfilled' && resFP.value.ok) {
            const fpLeagues = await resFP.value.json();
            fpLeagues.forEach(l => {
                const normName = (l.name || l.code).toLowerCase().replace(/[^a-z0-9]/g, '');
                if (!seenNames.has(normName)) {
                    seenNames.add(normName);
                    leagues.push({ ...l, source: 'futpython', badge: '🟢' });
                }
            });
        }

        // Then FootballData (estimated CS odds) — only add if not already covered
        if (resDF.status === 'fulfilled' && resDF.value.ok) {
            const fdLeagues = await resDF.value.json();
            fdLeagues.forEach(l => {
                const normName = (l.name || l.code).toLowerCase().replace(/[^a-z0-9]/g, '');
                if (!seenNames.has(normName)) {
                    seenNames.add(normName);
                    leagues.push({ ...l, source: 'footballdata', badge: '🟡' });
                }
            });
        }

        if (leagues.length === 0) return;

        // Sort: FutPython first, then alphabetically
        leagues.sort((a, b) => {
            if (a.source !== b.source) return a.source === 'futpython' ? -1 : 1;
            return (a.name || a.code).localeCompare(b.name || b.code);
        });

        container.innerHTML = leagues.map(l => `
            <label style="display:flex;align-items:center;gap:5px;padding:3px 6px;border-radius:4px;cursor:pointer;font-size:11px;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${l.name || l.code} (${l.source === 'futpython' ? 'CS Real — FutPython' : 'CS Estimado — FootballData'})">
                <input type="checkbox" value="${l.code}" data-source="${l.source || ''}" style="accent-color:${l.source === 'futpython' ? '#34d399' : '#8b5cf6'};width:14px;height:14px;flex-shrink:0;">
                <span style="font-size:10px;">${l.badge || ''}</span> ${l.name || l.code}
            </label>
        `).join('');
    } catch (e) {
        console.warn('Failed to load Dutching BT leagues:', e);
    }
}

// Store all bets for filtering
var dutchingBtAllBets = [];

async function runDutchingBacktest() {
    const btn = document.getElementById('btn-run-dutching-bt');
    const statusEl = document.getElementById('dutching-bt-status');
    const resultsEl = document.getElementById('dutching-bt-results');

    if (!btn || !statusEl) return;

    const selectedLeagues = Array.from(
        document.querySelectorAll('#dutching-bt-leagues-container input[type="checkbox"]:checked')
    ).map(cb => cb.value);
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

    // Validar datas
    const today = new Date().toISOString().split('T')[0];
    if (startDate > today || endDate > today) {
        statusEl.innerHTML = '<span style="color: #f87171;">⚠️ Datas não podem ser no futuro.</span>';
        return;
    }
    // Avisar sobre off-season (jun-ago na Europa)
    const endMonth = parseInt(endDate.split('-')[1]);
    const endYear = parseInt(endDate.split('-')[0]);
    if (endMonth >= 6 && endMonth <= 8 && endYear >= 2026) {
        statusEl.innerHTML = '<span style="color: #f59e0b;">⚠️ Jun-Ago é off-season na maioria das ligas europeias. Use set/2025 a mai/2026 para melhores resultados.</span>';
    }

    const stakeValue = parseFloat(document.getElementById('dutching-bt-stake').value) || 50;
    const minEdgePct = parseFloat(document.getElementById('dutching-bt-edge').value) || 0;
    const stakingMode = document.getElementById('dutching-bt-staking').value;
    const initialBankroll = parseFloat(document.getElementById('dutching-bt-bankroll').value) || 1000;

    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-arrows-rotate spinning"></i> Rodando...';
    if (resultsEl) resultsEl.style.display = 'none';

    // Build list of staking runs
    const runs = [];
    if (stakingMode === 'both') {
        runs.push({ rule: 'fixed', label: 'Stake Fixa' });
        runs.push({ rule: 'kelly_quarter', label: '1/4 Kelly' });
    } else {
        runs.push({ rule: stakingMode, label: stakingMode === 'fixed' ? 'Stake Fixa' : '1/4 Kelly' });
    }

    try {
        const allResults = {};

        for (const run of runs) {
            // ── Process ONE league at a time to avoid Render 30s timeout ──
            let mergedBets = [];
            let mergedEquity = {};
            let errors = [];

            for (let i = 0; i < selectedLeagues.length; i++) {
                const league = selectedLeagues[i];
                statusEl.innerHTML = `<span style="color: #a78bfa;"><i class="fa-solid fa-arrows-rotate spinning"></i> ${run.label} — liga ${i + 1}/${selectedLeagues.length}: <strong>${league}</strong></span>`;

                const payload = {
                    leagues: [league],   // UMA liga por vez
                    startDate,
                    endDate,
                    strategies: selectedStrategies,
                    initialBankroll,
                    stakeValue,
                    stakingRule: run.rule,
                    minEdge: minEdgePct / 100.0,
                    maxOverround: 0.92,
                    maxLegs: 8,
                    minSelections: 3,
                };

                try {
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 min per league
                    const res = await fetch(`${window.API_BASE_URL || window.location.origin}/api/backtest_dutching`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                        signal: controller.signal,
                    });
                    clearTimeout(timeoutId);

                    if (!res.ok) {
                        // Render 502 returns HTML, not JSON
                        const contentType = res.headers.get('content-type') || '';
                        if (contentType.includes('application/json')) {
                            const errData = await res.json().catch(() => ({}));
                            errors.push(`${league}: ${errData.detail || 'Erro HTTP ' + res.status}`);
                        } else {
                            errors.push(`${league}: Timeout do servidor (${res.status}). Tente com menos ligas ou período menor.`);
                        }
                        continue;
                    }

                    const data = await res.json();
                    if (data.error) {
                        errors.push(`${league}: ${data.error}`);
                        continue;
                    }

                    // Merge bets
                    if (data.bets) mergedBets = mergedBets.concat(data.bets);

                    // Merge equity curves
                    for (const [key, curve] of Object.entries(data.equity_curves || {})) {
                        if (!mergedEquity[key]) mergedEquity[key] = [];
                        mergedEquity[key] = mergedEquity[key].concat(curve);
                    }

                } catch (fetchErr) {
                    if (fetchErr.name === 'AbortError') {
                        errors.push(`${league}: Timeout — a liga demorou demais.`);
                    } else {
                        errors.push(`${league}: ${fetchErr.message}`);
                    }
                }
            }

            // ── Sort bets by date and recalculate bankroll ──
            mergedBets.sort((a, b) => (a.date || '').localeCompare(b.date || ''));
            let bankroll = initialBankroll;
            let totalStaked = 0;
            let wins = 0;
            mergedBets.forEach(b => {
                bankroll += (b.profit || 0);
                b.bankroll = bankroll;
                totalStaked += (b.total_stake || 0);
                if (b.won || b.covered) wins++;
            });

            const netProfit = bankroll - initialBankroll;
            const roi = totalStaked > 0 ? (netProfit / totalStaked * 100) : 0;
            const winRate = mergedBets.length > 0 ? (wins / mergedBets.length * 100) : 0;

            // Build merged result
            const mergedResult = {
                summary: {
                    total_bets: mergedBets.length,
                    total_wins: wins,
                    win_rate: Math.round(winRate * 10) / 10,
                    net_profit: Math.round(netProfit * 100) / 100,
                    roi: Math.round(roi * 10) / 10,
                    total_staked: Math.round(totalStaked * 100) / 100,
                    initial_bankroll: initialBankroll,
                    final_bankroll: Math.round(bankroll * 100) / 100,
                },
                bets: mergedBets,
                equity_curves: mergedEquity,
                strategy_breakdown: _buildStrategyBreakdown(mergedBets, initialBankroll, selectedStrategies),
            };

            allResults[run.rule] = { data: mergedResult, label: run.label };

            if (errors.length > 0) {
                console.warn('Dutching BT errors:', errors);
            }
        }

        // Check if we got any bets at all
        const primaryKey = allResults['fixed'] ? 'fixed' : Object.keys(allResults)[0];
        const primary = allResults[primaryKey]?.data;
        if (!primary || primary.summary.total_bets === 0) {
            statusEl.innerHTML = '<span style="color: #f59e0b;">⚠️ Nenhuma aposta encontrada no período. Tente ampliar o período ou reduzir o edge mínimo.</span>';
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-play"></i> Rodar Backtest';
            return;
        }

        renderDutchingBacktestResults(allResults, stakingMode);
        statusEl.innerHTML = `<span style="color: #34d399;"><i class="fa-solid fa-circle-check"></i> Backtest concluído! ${primary.summary.total_bets} apostas analisadas.</span>`;
        showToast('Backtest Dutching concluído!', 'success');
    } catch (err) {
        console.error('Dutching backtest error:', err);
        statusEl.innerHTML = `<span style="color: #f87171;"><i class="fa-solid fa-circle-exclamation"></i> ${err.message}</span>`;
        showToast('Erro no backtest: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-play"></i> Rodar Backtest';
    }
}

// Helper: rebuild strategy breakdown from merged bets
function _buildStrategyBreakdown(bets, initialBankroll, strategies) {
    const breakdown = {};
    const LABELS = {
        'auto_ia': 'IA Auto (Perfil)',
        'dynamic': 'Dinâmico (Top Probs)',
        'home_fav': 'Favorito Mandante',
        'away_fav': 'Favorito Visitante',
        'draw': 'Empate',
        'under': 'Under / Jogo Truncado',
        'over': 'Over / Goleada',
    };

    for (const strat of strategies) {
        const sBets = bets.filter(b => (b.resolved_strategy || b.strategy) === strat || strat === 'auto_ia');
        if (sBets.length === 0) continue;

        let bankroll = initialBankroll;
        let peak = initialBankroll;
        let maxDD = 0;
        let totalStaked = 0;
        let wins = 0;
        let profits = [];
        let edgePredicted = [];
        const monthlyMap = {};
        const leagueMap = {};

        sBets.forEach(b => {
            const profit = b.profit || 0;
            bankroll += profit;
            totalStaked += (b.total_stake || 0);
            if (b.won || b.covered) wins++;
            if (bankroll > peak) peak = bankroll;
            const dd = peak > 0 ? ((peak - bankroll) / peak * 100) : 0;
            if (dd > maxDD) maxDD = dd;
            profits.push(profit);
            if (b.edge_predicted) edgePredicted.push(b.edge_predicted * 100);

            // Monthly
            const month = (b.date || '').substring(0, 7);
            if (month) {
                if (!monthlyMap[month]) monthlyMap[month] = { bets: 0, wins: 0, profit: 0, staked: 0 };
                monthlyMap[month].bets++;
                if (b.won || b.covered) monthlyMap[month].wins++;
                monthlyMap[month].profit += profit;
                monthlyMap[month].staked += (b.total_stake || 0);
            }

            // League
            const lg = b.league || 'Unknown';
            if (!leagueMap[lg]) leagueMap[lg] = { bets: 0, wins: 0, profit: 0, staked: 0 };
            leagueMap[lg].bets++;
            if (b.won || b.covered) leagueMap[lg].wins++;
            leagueMap[lg].profit += profit;
            leagueMap[lg].staked += (b.total_stake || 0);
        });

        const netProfit = bankroll - initialBankroll;
        const roi = totalStaked > 0 ? (netProfit / totalStaked * 100) : 0;
        const winRate = sBets.length > 0 ? (wins / sBets.length * 100) : 0;
        const avgProfit = profits.length > 0 ? profits.reduce((a, b) => a + b, 0) / profits.length : 0;
        const stdProfit = profits.length > 1 ? Math.sqrt(profits.map(p => Math.pow(p - avgProfit, 2)).reduce((a, b) => a + b, 0) / (profits.length - 1)) : 1;
        const sharpe = stdProfit > 0 ? (avgProfit / stdProfit) : 0;

        const monthly = Object.entries(monthlyMap).sort(([a], [b]) => a.localeCompare(b)).map(([month, m]) => ({
            month,
            bets: m.bets,
            win_rate: m.bets > 0 ? Math.round(m.wins / m.bets * 1000) / 10 : 0,
            profit: Math.round(m.profit * 100) / 100,
            roi: m.staked > 0 ? Math.round(m.profit / m.staked * 1000) / 10 : 0,
        }));

        const leagueBreakdown = Object.entries(leagueMap).sort(([, a], [, b]) => b.profit - a.profit).map(([league, l]) => ({
            league,
            bets: l.bets,
            win_rate: l.bets > 0 ? Math.round(l.wins / l.bets * 1000) / 10 : 0,
            profit: Math.round(l.profit * 100) / 100,
            roi: l.staked > 0 ? Math.round(l.profit / l.staked * 1000) / 10 : 0,
        }));

        // Coverage analysis
        const hitCounts = {};
        const missCounts = {};
        sBets.forEach(b => {
            (b.selections || []).forEach(sc => {
                if (sc === b.actual_score) {
                    hitCounts[sc] = (hitCounts[sc] || 0) + 1;
                } else {
                    missCounts[sc] = (missCounts[sc] || 0) + 1;
                }
            });
        });

        breakdown[strat] = {
            label: LABELS[strat] || strat,
            total_bets: sBets.length,
            total_wins: wins,
            win_rate: Math.round(winRate * 10) / 10,
            net_profit: Math.round(netProfit * 100) / 100,
            roi: Math.round(roi * 10) / 10,
            max_drawdown: Math.round(maxDD * 10) / 10,
            sharpe_ratio: Math.round(sharpe * 100) / 100,
            avg_edge_predicted: edgePredicted.length > 0 ? Math.round(edgePredicted.reduce((a, b) => a + b, 0) / edgePredicted.length * 10) / 10 : 0,
            monthly_breakdown: monthly,
            league_breakdown: leagueBreakdown,
            coverage_analysis: {
                most_hit_scores: Object.entries(hitCounts).sort(([, a], [, b]) => b - a).map(([score, hits]) => ({ score, hits })),
                most_missed_scores: Object.entries(missCounts).sort(([, a], [, b]) => b - a).map(([score, misses]) => ({ score, misses })),
            },
        };
    }

    return breakdown;
}

function renderDutchingBacktestResults(allResults, stakingMode) {
    const resultsEl = document.getElementById('dutching-bt-results');
    if (!resultsEl) return;
    resultsEl.style.display = 'block';

    // Use primary result (fixed or first available)
    const primaryKey = allResults['fixed'] ? 'fixed' : Object.keys(allResults)[0];
    const primary = allResults[primaryKey].data;
    const summary = primary.summary || {};
    const breakdown = primary.strategy_breakdown || {};

    // ── KPI Cards (6 cards) ──
    const summaryEl = document.getElementById('dutching-bt-summary');
    const profitColor = (summary.net_profit || 0) >= 0 ? '#34d399' : '#f87171';
    const roiColor = (summary.roi || 0) >= 0 ? '#34d399' : '#f87171';

    // If both modes, show Kelly profit alongside
    let kellyProfitHtml = '';
    if (allResults['kelly_quarter']) {
        const ks = allResults['kelly_quarter'].data.summary || {};
        const kc = (ks.net_profit || 0) >= 0 ? '#34d399' : '#f87171';
        kellyProfitHtml = `
        <div style="background: rgba(167,139,250,0.1); border: 1px solid rgba(167,139,250,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">Lucro 1/4 Kelly</div>
            <div style="font-size: 28px; font-weight: 700; color: ${kc};">$${(ks.net_profit || 0).toFixed(2)}</div>
            <div style="font-size: 11px; color: ${kc};">ROI ${(ks.roi || 0) >= 0 ? '+' : ''}${(ks.roi || 0).toFixed(1)}%</div>
        </div>`;
    }

    // Avg edge predicted from breakdown
    let avgEdgePred = 0;
    const bvals = Object.values(breakdown);
    if (bvals.length > 0) avgEdgePred = bvals[0].avg_edge_predicted || 0;

    summaryEl.innerHTML = `
        <div style="background: rgba(139,92,246,0.1); border: 1px solid rgba(139,92,246,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">Total de Bets</div>
            <div style="font-size: 28px; font-weight: 700; color: var(--text-primary);">${summary.total_bets || 0}</div>
            <div style="font-size: 11px; color: var(--text-muted);">${summary.total_wins || 0} acertos</div>
        </div>
        <div style="background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">Win Rate</div>
            <div style="font-size: 28px; font-weight: 700; color: #34d399;">${summary.win_rate || 0}%</div>
            <div style="font-size: 11px; color: var(--text-muted);">dos dutchings acertaram</div>
        </div>
        <div style="background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">Lucro Stake Fixa</div>
            <div style="font-size: 28px; font-weight: 700; color: ${profitColor};">$${(summary.net_profit || 0).toFixed(2)}</div>
            <div style="font-size: 11px; color: ${profitColor};">ROI ${(summary.roi || 0) >= 0 ? '+' : ''}${(summary.roi || 0).toFixed(1)}%</div>
        </div>
        ${kellyProfitHtml || `<div style="background: rgba(59,130,246,0.1); border: 1px solid rgba(59,130,246,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">ROI</div>
            <div style="font-size: 28px; font-weight: 700; color: ${roiColor};">${(summary.roi || 0) >= 0 ? '+' : ''}${(summary.roi || 0).toFixed(1)}%</div>
        </div>`}
        <div style="background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">Edge Previsto IA</div>
            <div style="font-size: 28px; font-weight: 700; color: #f59e0b;">+${avgEdgePred.toFixed(1)}%</div>
            <div style="font-size: 11px; color: var(--text-muted);">média por aposta</div>
        </div>
        <div style="background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">Total Apostado</div>
            <div style="font-size: 28px; font-weight: 700; color: var(--text-primary);">$${(summary.total_staked || 0).toFixed(0)}</div>
            <div style="font-size: 11px; color: var(--text-muted);">volume total</div>
        </div>
    `;

    // ── Strategy breakdown table ──
    const tbody = document.getElementById('dutching-bt-strategy-tbody');
    tbody.innerHTML = '';

    // Show both fixed and kelly rows if both available
    const rulesWithData = Object.entries(allResults);
    for (const [rule, { data: rdata, label: rlabel }] of rulesWithData) {
        const rBreakdown = rdata.strategy_breakdown || {};
        for (const [key, s] of Object.entries(rBreakdown)) {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong style="color: #a78bfa;">${s.label || key}</strong><span style="font-size: 9px; color: var(--text-muted); margin-left: 4px;">(${rlabel})</span></td>
                <td>${s.total_bets}</td>
                <td style="color: ${s.win_rate >= 25 ? '#34d399' : '#f87171'};">${s.win_rate}%</td>
                <td style="color: ${s.net_profit >= 0 ? '#34d399' : '#f87171'}; font-weight: 600;">$${s.net_profit.toFixed(2)}</td>
                <td style="color: ${s.roi >= 0 ? '#34d399' : '#f87171'};">${s.roi >= 0 ? '+' : ''}${s.roi}%</td>
                <td style="color: #f87171;">${s.max_drawdown}%</td>
                <td style="color: ${s.sharpe_ratio >= 0 ? '#34d399' : '#f87171'};">${s.sharpe_ratio}</td>
            `;
            tbody.appendChild(tr);
        }
    }

    // ── Equity chart (all runs + strategies) ──
    const allBreakdowns = {};
    for (const [rule, { data: rdata, label: rlabel }] of Object.entries(allResults)) {
        for (const [key, s] of Object.entries(rdata.strategy_breakdown || {})) {
            allBreakdowns[`${s.label} (${rlabel})`] = s;
        }
    }
    renderDutchingBtEquityChart(allBreakdowns);

    // ── Monthly breakdown (primary, first strategy) ──
    const monthlyEl = document.getElementById('dutching-bt-monthly');
    if (monthlyEl) {
        const firstStrategy = bvals[0];
        const monthly = firstStrategy?.monthly_breakdown || [];
        if (monthly.length > 0) {
            monthlyEl.innerHTML = `<table class="table-styled" style="width:100%;font-size:11px;">
                <thead><tr><th>Mês</th><th>Bets</th><th>Win%</th><th>Lucro</th><th>ROI%</th></tr></thead>
                <tbody>${monthly.map(m => `<tr>
                    <td>${m.month}</td>
                    <td>${m.bets}</td>
                    <td style="color:${m.win_rate >= 25 ? '#34d399' : '#f87171'};">${m.win_rate}%</td>
                    <td style="color:${m.profit >= 0 ? '#34d399' : '#f87171'}; font-weight:600;">$${m.profit.toFixed(2)}</td>
                    <td style="color:${m.roi >= 0 ? '#34d399' : '#f87171'};">${m.roi >= 0 ? '+' : ''}${m.roi}%</td>
                </tr>`).join('')}</tbody>
            </table>`;
        } else {
            monthlyEl.innerHTML = '<span style="color:var(--text-muted);font-size:11px;">Sem dados mensais.</span>';
        }
    }

    // ── League breakdown ──
    const leagueEl = document.getElementById('dutching-bt-league');
    if (leagueEl) {
        const firstStrategy = bvals[0];
        const leagues = firstStrategy?.league_breakdown || [];
        if (leagues.length > 0) {
            leagueEl.innerHTML = `<table class="table-styled" style="width:100%;font-size:11px;">
                <thead><tr><th>Liga</th><th>Bets</th><th>Win%</th><th>Lucro</th><th>ROI%</th></tr></thead>
                <tbody>${leagues.map(l => `<tr>
                    <td style="font-size:10px;">${l.league}</td>
                    <td>${l.bets}</td>
                    <td style="color:${l.win_rate >= 25 ? '#34d399' : '#f87171'};">${l.win_rate}%</td>
                    <td style="color:${l.profit >= 0 ? '#34d399' : '#f87171'}; font-weight:600;">$${l.profit.toFixed(2)}</td>
                    <td style="color:${l.roi >= 0 ? '#34d399' : '#f87171'};">${l.roi >= 0 ? '+' : ''}${l.roi}%</td>
                </tr>`).join('')}</tbody>
            </table>`;
        } else {
            leagueEl.innerHTML = '<span style="color:var(--text-muted);font-size:11px;">Sem dados por liga.</span>';
        }
    }

    // ── Coverage Analysis ──
    const coverageEl = document.getElementById('dutching-bt-coverage');
    let hasCoverage = false;
    for (const [key, s] of Object.entries(breakdown)) {
        const cov = s.coverage_analysis;
        if (cov && (cov.most_hit_scores?.length > 0 || cov.most_missed_scores?.length > 0)) {
            document.getElementById('dutching-bt-top-hits').innerHTML = cov.most_hit_scores.slice(0, 8).map(
                sc => `<span style="display:inline-block;margin:2px;padding:3px 8px;background:rgba(52,211,153,0.08);border:1px solid rgba(52,211,153,0.2);border-radius:4px;">${sc.score} <strong style="color:#34d399;">${sc.hits}x</strong></span>`
            ).join('') || '<span style="color:var(--text-muted);">Nenhum acerto</span>';
            document.getElementById('dutching-bt-top-misses').innerHTML = cov.most_missed_scores.slice(0, 8).map(
                sc => `<span style="display:inline-block;margin:2px;padding:3px 8px;background:rgba(248,113,113,0.08);border:1px solid rgba(248,113,113,0.2);border-radius:4px;">${sc.score} <strong style="color:#f87171;">${sc.misses}x</strong></span>`
            ).join('') || '<span style="color:var(--text-muted);">Nenhum erro</span>';
            hasCoverage = true;
            break;
        }
    }
    if (coverageEl) coverageEl.style.display = hasCoverage ? 'block' : 'none';

    // ── Bets detail table ──
    dutchingBtAllBets = primary.bets || [];
    renderDutchingBtBetsTable(dutchingBtAllBets);
}

function renderDutchingBtBetsTable(bets) {
    const tbody = document.getElementById('dutching-bt-bets-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (bets.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:15px;">Nenhuma aposta registrada.</td></tr>';
        return;
    }

    bets.forEach(b => {
        const tr = document.createElement('tr');
        const won = b.won || b.covered;
        const profitColor = b.profit >= 0 ? '#34d399' : '#f87171';
        const resultIcon = won ? '✅' : '❌';
        const selectionsStr = (b.selections || []).slice(0, 4).join(', ') + (b.selections?.length > 4 ? '...' : '');
        tr.innerHTML = `
            <td style="white-space:nowrap;color:var(--text-muted);">${b.date}</td>
            <td style="font-size:11px;font-weight:600;">${b.home_team} vs ${b.away_team}</td>
            <td style="font-size:10px;color:var(--text-muted);">${b.league}</td>
            <td style="font-size:10px;color:#a78bfa;">${b.market_label || b.resolved_strategy || b.strategy}</td>
            <td style="font-family:monospace;font-size:10px;color:#a78bfa;">${selectionsStr}</td>
            <td style="font-weight:700;">${resultIcon} ${b.actual_score}</td>
            <td>$${(b.total_stake || 0).toFixed(2)}</td>
            <td style="font-weight:700;color:${profitColor};">${b.profit >= 0 ? '+' : ''}$${(b.profit || 0).toFixed(2)}</td>
            <td style="color:var(--text-secondary);">$${(b.bankroll || 0).toFixed(2)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function filterDutchingBtTable() {
    const search = (document.getElementById('dutching-bt-search')?.value || '').toLowerCase();
    const resultFilter = document.getElementById('dutching-bt-filter-result')?.value || 'all';

    let filtered = dutchingBtAllBets.filter(b => {
        const matchText = `${b.home_team} ${b.away_team} ${b.date} ${b.league}`.toLowerCase();
        if (search && !matchText.includes(search)) return false;
        if (resultFilter === 'won' && !(b.won || b.covered)) return false;
        if (resultFilter === 'lost' && (b.won || b.covered)) return false;
        return true;
    });

    renderDutchingBtBetsTable(filtered);
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

function initDutchingBtDates() {
    const startEl = document.getElementById('dutching-bt-start');
    const endEl = document.getElementById('dutching-bt-end');
    if (startEl && endEl) {
        if (!startEl.value || startEl._initialized !== true) {
            startEl.value = '2025-09-01';
            startEl._initialized = true;
        }
        if (!endEl.value || endEl._initialized !== true) {
            endEl.value = '2026-05-25';
            endEl._initialized = true;
        }
    }
    // Modo tips: padrão últimos 30 dias
    const tipsStart = document.getElementById('dutching-tips-start');
    const tipsEnd = document.getElementById('dutching-tips-end');
    if (tipsStart && tipsEnd && tipsStart._initialized !== true) {
        const today = new Date();
        const monthAgo = new Date(today);
        monthAgo.setDate(monthAgo.getDate() - 30);
        tipsEnd.value = today.toISOString().split('T')[0];
        tipsStart.value = monthAgo.toISOString().split('T')[0];
        tipsStart._initialized = true;
    }
}

// Load leagues on Dutching tab switch (attach to existing switchTab or init)
(function() {
    const origSwitchTab = window.switchTab;
    if (origSwitchTab) {
        window.switchTab = function(tabId) {
            origSwitchTab(tabId);
            if (tabId === 'tab-dutching') {
                loadDutchingBtLeagues();
                initDutchingBtDates();
            }
        };
    }
    // Also try loading on page init
    window.addEventListener('load', function() {
        setTimeout(() => {
            loadDutchingBtLeagues();
            initDutchingBtDates();
        }, 2000);
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
async function selectAllDutchingBtLeagues() {
    const container = document.getElementById('dutching-bt-leagues-container');
    if (!container) return;
    if (container.querySelectorAll('input[type="checkbox"]').length === 0) await loadDutchingBtLeagues();
    container.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
}

function clearDutchingBtLeagues() {
    document.querySelectorAll('#dutching-bt-leagues-container input[type="checkbox"]').forEach(cb => cb.checked = false);
}

function selectDutchingBtLeaguesBySource(source) {
    const container = document.getElementById('dutching-bt-leagues-container');
    if (!container) return;
    container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.checked = cb.dataset.source === source;
    });
}

window.selectDutchingBtLeaguesBySource = selectDutchingBtLeaguesBySource;

// ── Toggle entre modo Sugestões Reais e Simulação Histórica ──
function setDutchingBtMode(mode) {
    const tipsMode = document.getElementById('dutching-bt-tips-mode');
    const histMode = document.getElementById('dutching-bt-historical-mode');
    const btnTips = document.getElementById('dutching-bt-mode-tips');
    const btnHist = document.getElementById('dutching-bt-mode-historical');

    const activeStyle = 'linear-gradient(135deg, #8b5cf6, #a78bfa)';
    if (mode === 'tips') {
        if (tipsMode) tipsMode.style.display = 'block';
        if (histMode) histMode.style.display = 'none';
        if (btnTips) { btnTips.style.background = activeStyle; btnTips.style.color = 'white'; }
        if (btnHist) { btnHist.style.background = 'transparent'; btnHist.style.color = 'var(--text-muted)'; }
    } else {
        if (tipsMode) tipsMode.style.display = 'none';
        if (histMode) histMode.style.display = 'block';
        if (btnHist) { btnHist.style.background = activeStyle; btnHist.style.color = 'white'; }
        if (btnTips) { btnTips.style.background = 'transparent'; btnTips.style.color = 'var(--text-muted)'; }
        loadDutchingBtLeagues();
        initDutchingBtDates();
    }
}
window.setDutchingBtMode = setDutchingBtMode;

// ── Backtest de Sugestões Reais ──
async function runDutchingTipsBacktest() {
    const statusEl = document.getElementById('dutching-tips-status');
    const resultsEl = document.getElementById('dutching-tips-results');
    if (!statusEl) return;

    const startDate = document.getElementById('dutching-tips-start').value || null;
    const endDate = document.getElementById('dutching-tips-end').value || null;
    const bankroll = parseFloat(document.getElementById('dutching-tips-bankroll').value) || 1000;
    const stake = parseFloat(document.getElementById('dutching-tips-stake').value) || 50;

    statusEl.innerHTML = '<span style="color: #a78bfa;"><i class="fa-solid fa-arrows-rotate spinning"></i> Analisando sugestões enviadas...</span>';
    if (resultsEl) resultsEl.style.display = 'none';

    try {
        const res = await fetch(`${window.API_BASE_URL || window.location.origin}/api/backtest_dutching_tips`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ startDate, endDate, initialBankroll: bankroll, stakeValue: stake, stakingRule: 'fixed' }),
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `Erro HTTP ${res.status}`);
        }

        const data = await res.json();
        renderDutchingTipsResults(data);
        statusEl.innerHTML = `<span style="color: #34d399;"><i class="fa-solid fa-circle-check"></i> ${data.summary.resolved} sugestões analisadas.</span>`;
    } catch (err) {
        console.error('Tips backtest error:', err);
        statusEl.innerHTML = `<span style="color: #f87171;"><i class="fa-solid fa-circle-exclamation"></i> ${err.message}</span>`;
    }
}
// ── Atualiza o label do slider de Quality Score ──
function updateMinQualityLabel() {
    const slider = document.getElementById('dutching-min-quality');
    const label = document.getElementById('dutching-min-quality-label');
    if (!slider || !label) return;
    const val = parseInt(slider.value);
    label.textContent = val === 0 ? 'Todas' : `≥ ${val}`;
    // Cor do label conforme o nível
    if (val === 0) label.style.color = 'var(--text-muted)';
    else if (val >= 70) label.style.color = '#34d399';
    else if (val >= 55) label.style.color = '#a78bfa';
    else label.style.color = '#f59e0b';
}
window.updateMinQualityLabel = updateMinQualityLabel;

window.runDutchingTipsBacktest = runDutchingTipsBacktest;

// ── Importar sugestões antigas coladas do Telegram ──
async function importDutchingTips() {
    const textEl = document.getElementById('dutching-tips-import-text');
    const statusEl = document.getElementById('dutching-tips-import-status');
    if (!textEl || !statusEl) return;

    const fullText = textEl.value.trim();
    if (!fullText) {
        statusEl.innerHTML = '<span style="color: #f87171;">Cole ao menos uma mensagem.</span>';
        return;
    }

    // Separar múltiplas mensagens por linha em branco dupla ou pelo header do alerta
    let messages = fullText.split(/\n\s*\n/).filter(m => m.trim());
    // Se não separou, tentar pelo emoji de alerta
    if (messages.length === 1 && (fullText.match(/ALERTA DE DUTCHING/g) || []).length > 1) {
        messages = fullText.split(/(?=🤖\s*ALERTA)/).filter(m => m.trim());
    }

    statusEl.innerHTML = '<span style="color: #a78bfa;">Importando...</span>';

    let imported = 0, duplicates = 0, failed = 0;

    for (const msg of messages) {
        try {
            const res = await fetch(`${window.API_BASE_URL || window.location.origin}/api/import_dutching_tip`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: msg }),
            });
            if (res.ok) {
                const data = await res.json();
                if (data.status === 'success') imported++;
                else if (data.status === 'duplicate') duplicates++;
            } else {
                failed++;
            }
        } catch (e) {
            failed++;
        }
    }

    let parts = [];
    if (imported > 0) parts.push(`${imported} importada(s)`);
    if (duplicates > 0) parts.push(`${duplicates} já existia(m)`);
    if (failed > 0) parts.push(`${failed} falhou(ram)`);

    statusEl.innerHTML = `<span style="color: ${imported > 0 ? '#34d399' : '#f59e0b'};">✓ ${parts.join(', ')}. Agora clique em "Analisar Sugestões".</span>`;
    if (imported > 0) textEl.value = '';
}
window.importDutchingTips = importDutchingTips;

function renderDutchingTipsResults(data) {
    const resultsEl = document.getElementById('dutching-tips-results');
    if (!resultsEl) return;
    resultsEl.style.display = 'block';

    const s = data.summary;
    const profitColor = s.net_profit >= 0 ? '#34d399' : '#f87171';

    document.getElementById('dutching-tips-summary').innerHTML = `
        <div style="background: rgba(139,92,246,0.1); border: 1px solid rgba(139,92,246,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">Sugestões Analisadas</div>
            <div style="font-size: 28px; font-weight: 700; color: var(--text-primary);">${s.resolved}</div>
            <div style="font-size: 11px; color: var(--text-muted);">${s.unresolved} sem resultado</div>
        </div>
        <div style="background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">Win Rate</div>
            <div style="font-size: 28px; font-weight: 700; color: #34d399;">${s.win_rate}%</div>
            <div style="font-size: 11px; color: var(--text-muted);">${s.total_wins} acertos</div>
        </div>
        <div style="background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.2); padding: 16px; border-radius: 8px; text-align: center;">
            <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 6px;">Lucro / Prejuízo</div>
            <div style="font-size: 28px; font-weight: 700; color: ${profitColor};">$${s.net_profit.toFixed(2)}</div>
            <div style="font-size: 11px; color: ${profitColor};">ROI ${s.roi >= 0 ? '+' : ''}${s.roi}%</div>
        </div>
    `;

    const tbody = document.getElementById('dutching-tips-tbody');
    tbody.innerHTML = '';
    (data.bets || []).forEach(b => {
        const tr = document.createElement('tr');
        let statusIcon, scoreDisplay, profitDisplay;
        if (b.status === 'resolvido') {
            statusIcon = b.won ? '✅' : '❌';
            scoreDisplay = `${statusIcon} ${b.actual_score}`;
            profitDisplay = `<span style="color:${b.profit >= 0 ? '#34d399' : '#f87171'};font-weight:700;">${b.profit >= 0 ? '+' : ''}$${b.profit.toFixed(2)}</span>`;
        } else {
            scoreDisplay = `<span style="color:var(--text-muted);">${b.status === 'pendente' ? '⏳ pendente' : '— sem dados'}</span>`;
            profitDisplay = '<span style="color:var(--text-muted);">—</span>';
        }
        tr.innerHTML = `
            <td style="white-space:nowrap;color:var(--text-muted);">${b.date}</td>
            <td style="font-size:11px;font-weight:600;">${b.match}</td>
            <td style="font-size:10px;color:#a78bfa;">${b.market || '—'}</td>
            <td style="font-family:monospace;font-size:10px;color:#a78bfa;">${(b.selections || []).join(', ')}</td>
            <td style="font-weight:700;">${scoreDisplay}</td>
            <td>$${(b.total_stake || 0).toFixed(2)}</td>
            <td>${profitDisplay}</td>
            <td style="color:var(--text-secondary);">$${(b.bankroll || 0).toFixed(2)}</td>
        `;
        tbody.appendChild(tr);
    });
}

window.runDutchingBacktest = runDutchingBacktest;
window.loadDutchingBtLeagues = loadDutchingBtLeagues;
window.loadDemoOpportunity = loadDemoOpportunity;
window.filterDutchingBtTable = filterDutchingBtTable;
window.selectAllDutchingBtLeagues = selectAllDutchingBtLeagues;
window.clearDutchingBtLeagues = clearDutchingBtLeagues;

// ── Demo opportunity (shows all new features without API key) ─────

function loadDemoOpportunity() {
    const demoOpp = {
        match: 'Flamengo vs Palmeiras',
        date: '27/07/2026 16:00',
        bookmaker: 'Bet365',
        market: 'IA Favorito Mandante',
        selections: ['1-0', '2-0', '2-1', '3-0', '3-1'],
        selections_probs: [0.18, 0.14, 0.12, 0.09, 0.08],
        odds: [7.00, 8.50, 9.00, 13.0, 15.0],
        dutching_odd: 2.45,
        model_prob: '61.00%',
        edge: '+15.3%',
        raw_edge: 0.153,
        game_profile: 'home_fav',
        profile_confidence: 0.42,
        edge_ci_95: [0.045, 0.28],
        edge_prob_positive: 0.93,
        quality_score: 68.5,
        quality_verdict: 'BET',
        quality_verdict_label: 'OK: Apostar',
        quality_verdict_color: '#f59e0b',
        quality_verdict_icon: '\u{1F7E1}',
        quality_breakdown: {
            edge_sharpe: 21.2,
            bootstrap_robustness: 17.5,
            profile_confidence: 6.3,
            odd_quality: 10.0,
            market_divergence: 8.5,
            selection_diversity: 5.0,
        },
        alternative_scores: [
            { name: '3-2', prob: 0.045, odd: 22.0, recommendation: 'add', edge_change: 0.003, reason: 'Adicionar melhora edge em +0.3%' },
            { name: '4-0', prob: 0.025, odd: 35.0, recommendation: 'neutral', edge_change: -0.002, reason: 'Neutro (-0.2% edge), +2.5% cobertura' },
            { name: '4-1', prob: 0.018, odd: 45.0, recommendation: 'skip', edge_change: -0.015, reason: 'Dilui edge em -1.5% - não recomendado' },
            { name: '1-1', prob: 0.07, odd: 7.50, recommendation: 'skip', edge_change: -0.022, reason: 'Dilui edge em -2.2% - não recomendado' },
            { name: '0-0', prob: 0.05, odd: 10.0, recommendation: 'skip', edge_change: -0.018, reason: 'Dilui edge em -1.8% - não recomendado' },
            { name: '0-1', prob: 0.04, odd: 14.0, recommendation: 'skip', edge_change: -0.025, reason: 'Dilui edge em -2.5% - não recomendado' },
        ],
        odds_source_type: 'estimated',
    };

    // Populate radar table with demo row (sync both local var and window)
    dutchingRadarAllOpps.length = 0;
    dutchingRadarAllOpps.push(demoOpp);
    window.dutchingRadarAllOpps = dutchingRadarAllOpps;
    window.dutchingRadarFilteredOpps = [demoOpp];
    filterDutchingRadar();

    // Load into calculator
    loadDutchingOpportunityByIndex(0);

    // Set default bankroll
    const bankrollInput = document.getElementById('dutching-bankroll-input');
    if (bankrollInput && !bankrollInput.value) bankrollInput.value = '2000';
    calculateDutching();

    showToast('Demonstração carregada! Explore o Quality Score, Kelly e badges nos alternativos.', 'success');
}
// Bot configs and API key functions are defined and exposed in app.js



// --- RESTORED LIVE RADAR CODE ---

