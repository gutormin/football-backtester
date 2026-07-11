// Auto-extracted from app.js — Arbitrage scanner, bot configs, bookie init
import { showToast, switchTab, formatCurrency, formatPct } from './utils.js';
import { fetchServerHistory, saveToServer, deleteFromServer, toggleServerActiveState, API_BASE_URL } from './api.js';

// ARBITRAGE SCANNER LOGIC
// ============================================
let currentArbData = null;

function renderArbitrageRows(tbody, items, rowType) {
    // rowType: 'opportunity' | 'near_miss' | 'edge'
    items.forEach((item) => {
        const tr = document.createElement('tr');

        // Quality score
        const qs = item.quality_score || 0;
        let qsColor = '#ef4444', qsBg = 'rgba(239, 68, 68, 0.15)';
        if (qs >= 70) { qsColor = '#34d399'; qsBg = 'rgba(52, 211, 153, 0.15)'; }
        else if (qs >= 50) { qsColor = '#f59e0b'; qsBg = 'rgba(245, 158, 11, 0.15)'; }
        else if (qs >= 30) { qsColor = '#f97316'; qsBg = 'rgba(249, 115, 22, 0.12)'; }

        const netProfit = item.profit_margin_net !== undefined ? item.profit_margin_net : item.profit_margin;
        const netColor = netProfit >= 2.0 ? '#34d399' : netProfit >= 1.0 ? '#f59e0b' : '#ef4444';
        const grossColor = (item.profit_margin || 0) >= 2.0 ? '#34d399' : '#f59e0b';
        const kickoffHTML = item.hours_to_kickoff != null ? `${item.hours_to_kickoff}h` : 'N/A';

        // Styling by row type
        const isDiagnostic = rowType !== 'opportunity';
        const rowStyle = isDiagnostic ? 'opacity:0.65;' : '';

        let badgeHTML = '';
        let actionHTML = '';
        let qualityHTML = '';

        if (rowType === 'near_miss') {
            badgeHTML = `<span style="display:inline-block;padding:2px 6px;border-radius:4px;background:rgba(239,68,68,0.2);color:#f87171;font-size:10px;margin-left:4px;" title="Motivo da rejeição">${item.fail_reason || 'rejeitado'}</span>`;
            actionHTML = '<span style="font-size:11px;color:#6b7280;">Inviável</span>';
            qualityHTML = '-';
        } else if (rowType === 'edge') {
            const implied = item.implied_prob || 0;
            const impliedColor = implied < 100 ? '#34d399' : implied < 103 ? '#f59e0b' : '#f87171';
            badgeHTML = `<span style="display:inline-block;padding:2px 6px;border-radius:4px;background:rgba(245,158,11,0.15);color:${impliedColor};font-size:10px;margin-left:4px;" title="Soma das probabilidades implícitas">${implied.toFixed(1)}%</span>`;
            actionHTML = '<span style="font-size:11px;color:#6b7280;">Diagnóstico</span>';
            qualityHTML = `<span style="color:${impliedColor};font-weight:600;">${implied.toFixed(0)}%</span>`;
        } else {
            actionHTML = `<button class="btn-primary" onclick='openArbitrageCalc(${JSON.stringify(item).replace(/'/g, "&#39;")})'><i class="fa-solid fa-calculator"></i> Calcular Stake</button>`;
            qualityHTML = qs.toFixed(0);
        }

        tr.innerHTML = `
            <td style="${rowStyle}">
                <div><strong>${item.match}</strong>${badgeHTML}</div>
                <div style="font-size: 11px; color: var(--text-muted);"><i class="fa-regular fa-clock"></i> Kick-off em ${kickoffHTML}</div>
            </td>
            <td style="${rowStyle}">${item.date}</td>
            <td style="${rowStyle}"><span style="font-size: 12px;">${item.market}</span></td>
            <td style="color: ${grossColor}; font-weight: bold; ${rowStyle}">${(item.profit_margin || 0).toFixed(2)}%</td>
            <td style="color: ${netColor}; font-weight: bold; ${rowStyle}">${netProfit.toFixed(2)}%</td>
            <td style="${rowStyle}">
                <span style="display:inline-block;padding:3px 8px;border-radius:6px;background:${qsBg};color:${qsColor};font-weight:700;font-size:12px;">
                    ${qualityHTML}
                </span>
            </td>
            <td>${actionHTML}</td>
        `;
        tbody.appendChild(tr);
    });
}

async function runArbitrageScan() {
    const btn = document.getElementById('btn-scan-arbitrage');
    const tbody = document.querySelector('#arbitrage-table tbody');
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Buscando...';
    btn.disabled = true;
    
    const selectedBookies = Array.from(document.querySelectorAll('.bookie-cb:checked')).map(cb => cb.value);
    const bookiesQuery = selectedBookies.length > 0 ? `?bookies=${encodeURIComponent(selectedBookies.join(','))}` : '';
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/scan_arbitrage${bookiesQuery}`);
        const data = await res.json();

        // Detect API error responses (backend returns error objects when API key is missing)
        if (Array.isArray(data) && data.length === 1 && data[0].error) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: #f87171; padding: 20px;">
                <i class="fa-solid fa-key" style="font-size:24px;display:block;margin-bottom:8px;"></i>
                ${data[0].message}
            </td></tr>`;
            showToast(data[0].message, "error");
            return;
        }

        // Handle new format
        const opportunities = Array.isArray(data) ? data : (data.opportunities || []);
        const nearMisses = Array.isArray(data) ? [] : (data.near_misses || []);
        const edgeOpps = Array.isArray(data) ? [] : (data.edge_opportunities || []);
        const pipeline = data.pipeline || null;

        tbody.innerHTML = '';

        // ── Remove previous summary div if exists ──
        const oldSummary = document.getElementById('arb-pipeline-summary');
        if (oldSummary) oldSummary.remove();

        // ── Show pipeline summary always ──
        if (pipeline) {
            let summaryHTML = '';
            if (pipeline.within_7d !== undefined) {
                summaryHTML += `<strong>${pipeline.within_7d}</strong> jogos próximos (≤7d) de <strong>${pipeline.total_matches}</strong> total | `;
            } else {
                summaryHTML += `<strong>${pipeline.total_matches}</strong> jogos analisados | `;
            }
            summaryHTML += `<strong style="color:#f59e0b">${pipeline.raw_opps}</strong> opp. brutas | `;
            summaryHTML += `<strong style="color:#ef4444">${pipeline.failed_net}</strong> descartadas (lucro &lt;${pipeline.min_profit_pct}%)`;
            if (pipeline.failed_quality > 0) {
                summaryHTML += ` | ${pipeline.failed_quality} qualidade &lt;${pipeline.min_quality}`;
            }
            if (pipeline.credits_remaining) {
                summaryHTML += ` | <span style="color:#34d399">${pipeline.credits_remaining}</span> créditos`;
            }
            const summaryDiv = document.createElement('div');
            summaryDiv.id = 'arb-pipeline-summary';
            summaryDiv.style.cssText = 'margin-bottom:8px;color:#9ca3af;font-size:12px;';
            summaryDiv.innerHTML = summaryHTML;
            tbody.parentNode.parentNode.insertBefore(summaryDiv, tbody.parentNode);
        }

        if (opportunities.length === 0) {
            const hasNear = nearMisses.length > 0;
            const hasEdge = edgeOpps.length > 0;

            if (!hasNear && !hasEdge) {
                if (pipeline && pipeline.within_7d === 0) {
                    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: #6b7280; padding: 20px;">
                        <i class="fa-regular fa-calendar-xmark" style="font-size:24px;display:block;margin-bottom:8px;"></i>
                        Nenhum jogo nos próximos 7 dias.<br>
                        <span style="font-size:12px;color:#4b5563;">${pipeline.total_matches} jogos encontrados, todos a mais de uma semana — odds ainda não confiáveis.</span>
                    </td></tr>`;
                } else {
                    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: #6b7280;">
                        <i class="fa-solid fa-circle-info"></i> Nenhuma oportunidade de arbitragem encontrada. Tente novamente mais tarde.
                    </td></tr>`;
                }
                showToast("Nenhuma oportunidade de arbitragem encontrada. Configure THE_ODDS_API_KEY para ativar.", "warning");
                return;
            }

            // Warning header
            const warnRow = document.createElement('tr');
            warnRow.innerHTML = `<td colspan="7" style="text-align:center;background:rgba(239,68,68,0.08);color:#f87171;padding:8px;font-size:13px;">
                <i class="fa-solid fa-triangle-exclamation"></i> Nenhuma surebet lucrativa (após slippage + comissão Betfair).<br>
                <span style="color:#9ca3af;font-size:11px;">Dados abaixo para diagnóstico — não representam oportunidades executáveis.</span>
            </td>`;
            tbody.appendChild(warnRow);

            // Show near-misses (failed profit filter)
            if (hasNear) {
                const headerRow = document.createElement('tr');
                headerRow.innerHTML = `<td colspan="7" style="text-align:center;background:rgba(239,68,68,0.05);color:#f87171;padding:6px;font-size:12px;font-weight:600;">
                    <i class="fa-solid fa-xmark"></i> Oportunidades rejeitadas (lucro líquido < ${pipeline?.min_profit_pct || 1}%)
                </td>`;
                tbody.appendChild(headerRow);
                renderArbitrageRows(tbody, nearMisses, 'near_miss');
            }

            // Show edge opportunities (closest to arbitrage)
            if (hasEdge) {
                const edgeHeader = document.createElement('tr');
                edgeHeader.innerHTML = `<td colspan="7" style="text-align:center;background:rgba(245,158,11,0.05);color:#f59e0b;padding:6px;font-size:12px;font-weight:600;">
                    <i class="fa-solid fa-magnifying-glass-chart"></i> Top ${edgeOpps.length} jogos mais próximos de arbitragem (menor implied %)
                </td>`;
                tbody.appendChild(edgeHeader);
                renderArbitrageRows(tbody, edgeOpps, 'edge');
            }

            return;
        }

        // Published opportunities
        renderArbitrageRows(tbody, opportunities, 'opportunity');

        // Also show edge opportunities below published ones for context
        if (edgeOpps.length > 0) {
            const edgeHeader = document.createElement('tr');
            edgeHeader.innerHTML = `<td colspan="7" style="text-align:center;background:rgba(245,158,11,0.05);color:#f59e0b;padding:6px;font-size:12px;font-weight:600;">
                <i class="fa-solid fa-magnifying-glass-chart"></i> Top ${edgeOpps.length} jogos mais próximos de arbitragem (menor implied %)
            </td>`;
            tbody.appendChild(edgeHeader);
            renderArbitrageRows(tbody, edgeOpps, 'edge');
        }
    } catch (e) {
        console.error(e);
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #ef4444;">Erro ao buscar oportunidades na API.</td></tr>';
    } finally {
        btn.innerHTML = '<i class="fa-solid fa-radar"></i> Rastrear Oportunidades';
        btn.disabled = false;
    }
}

window.openArbitrageCalc = function(item) {
    currentArbData = item;
    document.getElementById('arbitrage-calculator').style.display = 'block';
    // Scroll down to the calculator smoothly
    document.getElementById('arbitrage-calculator').scrollIntoView({ behavior: 'smooth', block: 'end' });
    recalcArbitrage();
};

window.recalcArbitrage = function() {
    if (!currentArbData) return;
    const total = parseFloat(document.getElementById('arb-total-invest').value) || 1000;
    const profitEl = document.getElementById('arb-profit-value');
    const distList = document.getElementById('arb-distribution-list');

    distList.innerHTML = '';

    const implied = currentArbData.implied_prob / 100;
    const netMargin = currentArbData.profit_margin_net !== undefined
        ? currentArbData.profit_margin_net
        : currentArbData.profit_margin;
    const grossMargin = currentArbData.profit_margin || 0;
    const slippagePct = currentArbData.slippage_pct !== undefined
        ? currentArbData.slippage_pct
        : 1.5;

    const grossProfit = total * (grossMargin / 100);
    const netProfit = total * (netMargin / 100);

    profitEl.innerHTML = `
        <div>Lucro Bruto: <span style="color:#f59e0b;">$${grossProfit.toFixed(2)}</span></div>
        <div style="font-size: 20px; margin-top: 4px;">Lucro Líquido: <span style="color:#34d399;">$${netProfit.toFixed(2)}</span></div>
        <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">
            Após slippage (~${slippagePct}%) e comissões
        </div>
    `;

    Object.keys(currentArbData.odds).forEach(outcome => {
        const odd = currentArbData.odds[outcome];
        const prob = 1 / odd;
        const stake = total * (prob / implied);
        const returnVal = stake * odd;
        const bookieName = currentArbData.bookmakers ? currentArbData.bookmakers[outcome] : 'Desconhecida';
        const labelName = (currentArbData.labels && currentArbData.labels[outcome]) ? currentArbData.labels[outcome] : outcome;

        const isBetfair = /betfair/i.test(bookieName);
        const commNote = isBetfair ? '<span style="font-size:10px;color:#f59e0b;margin-left:4px;">(comissão 2-5%)</span>' : '';

        distList.innerHTML += `
            <div style="display: flex; justify-content: space-between; padding: 10px; background: rgba(255,255,255,0.05); border-radius: 6px; flex-wrap: wrap; gap: 8px;">
                <div><span style="color: #9ca3af">Seleção:</span> <b>${labelName}</b> <span style="color: #3b82f6; margin-left: 5px;">@${odd.toFixed(2)}</span> <span style="font-size: 11px; background: #374151; padding: 2px 6px; border-radius: 4px; margin-left: 8px;">${bookieName}${commNote}</span></div>
                <div>Apostar: <b style="color: #34d399">$${stake.toFixed(2)}</b></div>
                <div style="font-size: 13px; color: #6b7280; padding-top: 2px;">Retorno bruto: $${returnVal.toFixed(2)}</div>
            </div>
        `;
    });
};

async function loadArbitrageBotConfig() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/arbitrage_scheduler/config`);
        if(res.ok) {
            const config = await res.json();
            document.getElementById('arb-bot-enabled').checked = config.enabled || false;
            document.getElementById('arb-bot-interval').value = config.check_interval_hours || 1.0;
            document.getElementById('arb-bot-profit').value = config.min_profit_pct || 0.5;
        }
    } catch(e) {
        console.error("Erro ao carregar config de arbitragem", e);
    }
}

async function saveArbitrageBotConfig() {
    const enabled = document.getElementById('arb-bot-enabled').checked;
    const interval = parseFloat(document.getElementById('arb-bot-interval').value);
    const profit = parseFloat(document.getElementById('arb-bot-profit').value);
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/arbitrage_scheduler/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                enabled: enabled, 
                check_interval_hours: isNaN(interval) ? 1.0 : interval, 
                min_profit_pct: isNaN(profit) ? 0.5 : profit 
            })
        });
        
        if (res.ok) {
            showToast("Configuração do Robô de Arbitragem salva com sucesso!", "success");
        } else {
            showToast("Erro ao salvar configuração.", "danger");
        }
    } catch (e) {
        showToast("Erro de conexão com API.", "danger");
    }
}

async function testArbitrageTelegramAlert() {
    try {
        showToast("Enviando mensagem de teste...", "info");
        const res = await fetch("/api/telegram/test_arbitrage", { method: 'POST' });
        const data = await res.json();
        
        if (res.ok && data.status === 'success') {
            showToast("Mensagem de teste enviada com sucesso! Verifique seu Telegram.", "success");
        } else {
            showToast("Falha ao enviar: " + (data.detail || data.message), "error");
        }
    } catch (e) {
        showToast("Erro de conexo ao tentar enviar teste.", "error");
    }
}

async function loadDutchingBotConfig() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/telegram/dutching_config`);
        if (res.ok) {
            const config = await res.json();
            document.getElementById('dutch-bot-enabled').checked = config.enabled || false;
            document.getElementById('dutch-bot-interval').value = config.check_interval_hours || 1.0;
            document.getElementById('dutch-bot-edge').value = config.min_edge_pct || 1.0;
            document.getElementById('dutch-bot-hours').value = config.min_hours_before || 2.0;
        }
    } catch (e) {
        console.error("Erro ao carregar config de dutching telegram", e);
    }
}

async function saveDutchingBotConfig() {
    const enabled = document.getElementById('dutch-bot-enabled').checked;
    const interval = parseFloat(document.getElementById('dutch-bot-interval').value);
    const edge = parseFloat(document.getElementById('dutch-bot-edge').value);
    const hours = parseFloat(document.getElementById('dutch-bot-hours').value);
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/telegram/dutching_config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                enabled: enabled, 
                check_interval_hours: isNaN(interval) ? 1.0 : interval, 
                min_edge_pct: isNaN(edge) ? 1.0 : edge,
                min_hours_before: isNaN(hours) ? 2.0 : hours
            })
        });
        
        if (res.ok) {
            showToast("Configuração do Robô de Dutching salva com sucesso!", "success");
        } else {
            showToast("Erro ao salvar configuração.", "danger");
        }
    } catch (e) {
        showToast("Erro de conexão com API.", "danger");
    }
}

async function testDutchingTelegramAlert() {
    try {
        showToast("Enviando alerta de teste do Dutching...", "info");
        const res = await fetch("/api/telegram/test_dutching", { method: 'POST' });
        const data = await res.json();
        
        if (res.ok && data.status === 'success') {
            showToast("Alerta de teste enviado com sucesso! Verifique seu Telegram.", "success");
        } else {
            showToast("Falha ao enviar: " + (data.detail || data.message), "error");
        }
    } catch (e) {
        showToast("Erro de conexão ao tentar enviar teste de Dutching.", "error");
    }
}

async function loadOddsApiKey() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/telegram/odds_api_config`);
        if (res.ok) {
            const data = await res.json();
            document.getElementById('dutch-odds-api-key').value = data.api_key || '';
        }
    } catch (e) {
        console.error("Erro ao carregar chave da Odds API", e);
    }
}

async function saveOddsApiKey() {
    const keyInput = document.getElementById('dutch-odds-api-key');
    const key = keyInput.value ? keyInput.value.trim() : '';
    try {
        const res = await fetch(`${API_BASE_URL}/api/telegram/odds_api_config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: key })
        });
        if (res.ok) {
            showToast("Chave da The Odds API salva com sucesso!", "success");
        } else {
            showToast("Erro ao salvar chave da Odds API.", "danger");
        }
    } catch (e) {
        showToast("Erro de conexão ao salvar chave da Odds API.", "danger");
    }
}


function runBookieInit() {
    const savedBookies = localStorage.getItem('arbBookies');
    if (savedBookies) {
        const bookieArray = JSON.parse(savedBookies);
        document.querySelectorAll('.bookie-cb').forEach(cb => {
            cb.checked = bookieArray.includes(cb.value);
        });
    }
    
    document.querySelectorAll('.bookie-cb').forEach(cb => {
        cb.addEventListener('change', () => {
            const selectedBookies = Array.from(document.querySelectorAll('.bookie-cb:checked')).map(c => c.value);
            localStorage.setItem('arbBookies', JSON.stringify(selectedBookies));
        });
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runBookieInit);
} else {
    runBookieInit();
}

window.selectAllLeagues = function(check) {
    document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]').forEach(cb => {
        cb.checked = check;
    });
};

window.showRadarInsights = function() {
    alert("💡 INSIGHTS ESTRATÉGICOS DO RADAR SMART MONEY:\n\n" +
          "1. Ligas de Tier Alta (ex: Premier League, La Liga, Brasileirão Série A) possuem volumes de negociação gigantescos. Drops nessas ligas representam a entrada de sindicatos asiáticos e possuem ALTÍSSIMA CONFIANÇA.\n\n" +
          "2. Evite seguir drops de odds em ligas de baixa liquidez (Tier Baixa) quando o score de confiança for menor que 45%, pois estes mercados sofrem manipulações de pequenos apostadores locais (ruído).\n\n" +
          "3. O mercado de 'Match Odds' (1X2) e 'Goals (O2.5/U2.5)' são os preferidos dos robôs institucionais. Fique atento a quedas simultâneas nestas linhas.");
};

// window.runLiveSteamScan = async function() {
//     try {
//         const tbody = document.querySelector('#steam-live-table tbody');
//         const overlay = document.getElementById('steam-loading-overlay');
//         
//         const leagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
//         const markets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);
//         const minDropPct = parseFloat(document.getElementById('val-drop-pct').value || 5.0);
//         
//         if (markets.length === 0) {
//             alert("Por favor, selecione pelo menos um mercado.");
//             return;
//         }
// 
//         overlay.style.display = 'block';
//         document.getElementById('steam-live-table-container').style.display = 'none';
//         
//         const reqBody = {
//             minDropPct: minDropPct,
//             markets: markets,
//             leagues: leagues
//         };
//         
//         const response = await fetch(`${API_BASE_URL}/api/live_steam_moves`, {
//             method: 'POST',
//             headers: { 'Content-Type': 'application/json' },
//             body: JSON.stringify(reqBody)
//         });
//         
//         if (!response.ok) {
//             throw new Error(`Erro na API: ${response.status}`);
//         }
//         
//         const data = await response.json();
//         
//         overlay.style.display = 'none';
//         document.getElementById('steam-live-table-container').style.display = 'block';
//         tbody.innerHTML = '';
//         
//         if (!data.scan_results || data.scan_results.length === 0) {
//             tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #6b7280; padding: 20px;">Nenhuma queda significativa detectada nas odds ao vivo neste momento. O robô atualiza a cada 30 minutos.</td></tr>';
//             return;
//         }
//         
//         data.scan_results.forEach((item, idx) => {
//             const tr = document.createElement('tr');
//             
//             if (item.confidence_level === 'Alta') {
//                 tr.className = 'radar-row-glow-alta';
//             } else if (item.confidence_level === 'Média') {
//                 tr.className = 'radar-row-glow-media';
//             } else {
//                 tr.className = 'radar-row-glow-baixa';
//             }
//             
//             let confBorderColor = 'rgba(255, 255, 255, 0.1)';
//             let confGlowColor = 'rgba(255, 255, 255, 0.02)';
//             let confTextColor = '#9ca3af';
//             let confIcon = 'fa-circle-question';
//             
//             if (item.confidence_level === 'Alta') {
//                 confBorderColor = '#10b981';
//                 confGlowColor = 'rgba(16, 185, 129, 0.05)';
//                 confTextColor = '#10b981';
//                 confIcon = 'fa-circle-check';
//             } else if (item.confidence_level === 'Média') {
//                 confBorderColor = '#f59e0b';
//                 confGlowColor = 'rgba(245, 158, 11, 0.05)';
//                 confTextColor = '#f59e0b';
//                 confIcon = 'fa-circle-exclamation';
//             } else if (item.confidence_level === 'Baixa') {
//                 confBorderColor = '#ef4444';
//                 confGlowColor = 'rgba(239, 68, 68, 0.05)';
//                 confTextColor = '#ef4444';
//                 confIcon = 'fa-triangle-exclamation';
//             }
// 
//             const confidenceHTML = `
//                 <div style="display: inline-flex; flex-direction: column; align-items: center; justify-content: center; padding: 6px 14px; border-radius: 12px; border: 1px solid ${confBorderColor}; background: ${confGlowColor}; box-shadow: 0 0 10px ${confGlowColor}; min-width: 140px; box-sizing: border-box;">
//                     <div style="display: flex; align-items: center; gap: 6px; font-weight: 800; font-size: 11px; color: ${confTextColor}; text-transform: uppercase; letter-spacing: 0.5px;">
//                         <i class="fa-solid ${confIcon}"></i>
//                         <span>${item.confidence_level || 'BAIXA'}</span>
//                     </div>
//                     <div style="font-size: 9px; color: var(--text-muted); font-weight: bold; margin-top: 3px;">
//                         Score: ${(item.confidence_score || 0).toFixed(0)}% (${item.confidence_level || 'Baixa'})
//                     </div>
//                 </div>
//             `;
// 
//             let indexCell = `<span style="color: var(--text-muted); font-size: 13px; font-weight: bold; margin-right: 12px; font-family: var(--font-mono);">${idx + 1}.</span>`;
//             const teams = item.match.split(' vs ');
//             const home = teams[0] || 'Desconhecido';
//             const away = teams[1] || 'Desconhecido';
//             
//             const matchHTML = `
//                 <div style="display: flex; align-items: center;">
//                     ${indexCell}
//                     <div style="display: flex; flex-direction: column; gap: 3px;">
//                         <div style="display: flex; align-items: center; gap: 8px;">
//                             <i class="fa-solid fa-shirt" style="font-size: 11px; color: var(--text-muted);"></i>
//                             <span style="font-weight: 700; color: var(--text-primary); font-size: 13px;">${home}</span>
//                         </div>
//                         <div style="display: flex; align-items: center; gap: 8px;">
//                             <i class="fa-solid fa-shirt" style="font-size: 11px; color: var(--text-muted); opacity: 0.6;"></i>
//                             <span style="font-weight: 700; color: var(--text-secondary); font-size: 13px;">${away}</span>
//                         </div>
//                         <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px; display: flex; align-items: center; gap: 4px;">
//                             <i class="fa-regular fa-clock" style="font-size: 10px;"></i> ${item.date}
//                         </div>
//                     </div>
//                 </div>
//             `;
// 
//             let bookieHTML = '';
//             const bName = item.bookmaker.toLowerCase();
//             if (bName.includes('365')) {
//                 bookieHTML = `<span class="radar-bookmaker-badge radar-bookie-bet365" style="font-family: 'Outfit', sans-serif; font-style: italic; font-weight: 900; letter-spacing: -0.5px;"><span style="color: #ffffff;">bet</span><span style="color: #ffdf1b;">365</span></span>`;
//             } else if (bName.includes('pinnacle')) {
//                 bookieHTML = `<span class="radar-bookmaker-badge radar-bookie-pinnacle" style="font-family: 'Outfit', sans-serif; font-weight: 900; letter-spacing: 0.5px;"><span style="color: #ff7020;">PIN</span><span style="color: #ffffff;">NACLE</span></span>`;
//             } else if (bName.includes('betfair')) {
//                 bookieHTML = `<span class="radar-bookmaker-badge radar-bookie-betfair" style="font-family: 'Outfit', sans-serif; font-weight: 900; letter-spacing: -0.5px;"><span style="color: #ffbe00;">bet</span><span style="color: #ffffff;">fair</span></span>`;
//             } else {
//                 bookieHTML = `<span class="radar-bookmaker-badge radar-bookie-neutral">${item.bookmaker}</span>`;
//             }
//             
//             const marketHTML = `<span style="color: #67e8f9; font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">${item.market}</span>`;
//             const openingHTML = `<span style="color: var(--text-secondary); font-family: var(--font-mono); font-size: 13px;">@${item.opening_odd.toFixed(2)}</span>`;
//             const currentHTML = `<span class="radar-odd-badge-current">@${item.current_odd.toFixed(2)}</span>`;
//             const dropHTML = `
//                 <span class="radar-drop-pct-red">
//                     ${item.drop_pct.toFixed(0)}% <span style="font-size: 16px; margin-left: 2px;">&darr;</span>
//                 </span>
//             `;
// 
//             tr.innerHTML = `
//                 <td>${matchHTML}</td>
//                 <td>${bookieHTML}</td>
//                 <td>${marketHTML}</td>
//                 <td>${openingHTML}</td>
//                 <td>${currentHTML}</td>
//                 <td>${dropHTML}</td>
//                 <td>${confidenceHTML}</td>
//             `;
//             tbody.appendChild(tr);
//         });
//         
//     } catch (e) {
//         console.error(e);
//         document.getElementById('steam-loading-overlay').style.display = 'none';
//         document.getElementById('steam-live-table-container').style.display = 'block';
//         document.querySelector('#steam-live-table tbody').innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 20px;">Erro ao buscar dados ao vivo.</td></tr>`;
//     }
// };
// 



// Window bindings for HTML onclick handlers
window.runArbitrageScan = runArbitrageScan;
window.loadArbitrageBotConfig = loadArbitrageBotConfig;
window.saveArbitrageBotConfig = saveArbitrageBotConfig;
window.testArbitrageTelegramAlert = testArbitrageTelegramAlert;
window.loadDutchingBotConfig = loadDutchingBotConfig;
window.saveDutchingBotConfig = saveDutchingBotConfig;
window.testDutchingTelegramAlert = testDutchingTelegramAlert;
window.loadOddsApiKey = loadOddsApiKey;
window.saveOddsApiKey = saveOddsApiKey;
window.runBookieInit = runBookieInit;
