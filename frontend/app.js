// Global variables to store Chart instances

let equityChart = null;

let leagueChart = null;

let monthlyChart = null;

let oddsChart = null;

let allBets = []; // Cache for filtering in table

let allTelegramTips = []; // Cache for Telegram tips log

let lastScanResults = null;

let lastScanParams = null;

let lastBacktestSummary = null;

let lastBacktestParams = null;

let appliedOptimizationSuggestions = new Set(); // Track applied suggestions to prevent re-rendering

const API_BASE_URL = window.location.origin;
window.currentDataSource = 'footballdata';
window.futpythonApiKey = 'cmqa6oz0p01i1wq6lzxknltmd';

function handleDataSourceChange() {
    window.currentDataSource = document.getElementById('data-source-select').value;
    const configDiv = document.getElementById('futpython-config');
    if (window.currentDataSource === 'futpython') {
        configDiv.style.display = 'block';
    } else {
        configDiv.style.display = 'none';
    }
    // Reload leagues
    if (typeof loadLeagues === 'function') loadLeagues();
    
    // Also reload if there's a standalone select somewhere
    const selects = document.querySelectorAll('.league-select');
    selects.forEach(s => {
        // Just empty it, it will be refetched
        s.innerHTML = '';
    });
    
    // Also reload calculator leagues
    if (typeof populateCalculatorLeagues === 'function') {
        populateCalculatorLeagues();
    }
}

function saveFutpythonKey(val) {
    window.futpythonApiKey = val;
    localStorage.setItem('futpython_api_key', val);
}


document.addEventListener('DOMContentLoaded', () => {
    // Sync currentDataSource with whatever the browser restored in the select
    const sourceSelect = document.getElementById('data-source-select');
    if (sourceSelect) {
        window.currentDataSource = sourceSelect.value;
        const configDiv = document.getElementById('futpython-config');
        if (window.currentDataSource === 'futpython' && configDiv) {
            configDiv.style.display = 'block';
        }
    }

    // Load FutPythonTrader API Key from LocalStorage
    const savedKey = localStorage.getItem('futpython_api_key');
    if (savedKey) {
        window.futpythonApiKey = savedKey;
        const keyInput = document.getElementById('futpython-api-key');
        if (keyInput) keyInput.value = savedKey;
    }
    
    initApp();
    
    // Close modal when clicking outside of modal container
    const modal = document.getElementById('match-details-modal');
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeMatchDetailsModal();
        }
    });
});

async function initApp() {
    await checkDatabaseStatus();
    await loadLeagues();
    await populateCalculatorLeagues();
    await loadTelegramConfigUi();
    await loadSchedulerConfigUi();
    await loadTelegramTipsLog();
    await loadArbitrageBotConfig();
    toggleStakeLabel();
    onMarketSelectionChange(); // Initialize custom market multiselect label
    updateNotificationUi(); // Initialize notification permission state in UI
    
    // Register Service Worker for PWA
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/service-worker.js')
            .then(() => console.log('Service Worker registrado.'))
            .catch(err => console.error('Service Worker erro:', err));
    }
}

// Display Toast Notifications
function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    const icon = document.getElementById('toast-icon');
    const msgSpan = document.getElementById('toast-message');
    
    // Set icon classes based on type
    icon.className = 'fa-solid';
    if (type === 'success') {
        icon.classList.add('fa-circle-check');
        toast.className = 'toast show success';
    } else if (type === 'error') {
        icon.classList.add('fa-circle-xmark');
        toast.className = 'toast show error';
    } else {
        icon.classList.add('fa-circle-info');
        toast.className = 'toast show info';
    }
    
    msgSpan.innerText = message;
    
    // Hide toast after 4 seconds
    setTimeout(() => {
        toast.classList.remove('show');
    }, 4000);
}

// Fetch database status and update header stats
async function checkDatabaseStatus() {
    const badge = document.getElementById('db-status-badge');
    const timeSpan = document.getElementById('db-update-time');
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/status`);
        if (!res.ok) throw new Error("Status query failed");
        
        const data = await res.json();
        
        if (data.synced && data.files_count > 0) {
            badge.innerText = `${data.files_count} Campeonatos`;
            badge.className = 'badge badge-success';
            timeSpan.innerText = `Último Sync: ${data.last_updated}`;
        } else {
            badge.innerText = 'Sem Dados';
            badge.className = 'badge badge-error';
            timeSpan.innerText = 'Por favor, sincronize os dados.';
            showToast("A base de dados de odds está vazia. Clique em 'Sincronizar'!", "info");
        }
    } catch (err) {
        console.error("Error fetching db status:", err);
        badge.innerText = 'Desconectado';
        badge.className = 'badge badge-error';
        timeSpan.innerText = 'Não foi possível conectar ao servidor.';
    }
}

// Sync database triggers download in backend
async function syncDatabase() {
    const btn = document.getElementById('btn-sync-db');
    btn.classList.add('spinning');
    btn.disabled = true;
    
    const source = document.getElementById('db-sync-source').value || 'csv';
    showToast(`Baixando odds e resultados históricos via ${source === 'api' ? 'API DataFootball' : 'Football-Data'}... Isso pode levar de 1 a 2 minutos.`, "info");
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/sync?source=${source}`, { method: 'POST' });
        if (!res.ok) throw new Error("Sync failed");
        
        showToast("Dados sincronizados com sucesso!", "success");
        await checkDatabaseStatus();
    } catch (err) {
        console.error(err);
        showToast("Falha ao sincronizar dados. Tente novamente.", "error");
    } finally {
        btn.classList.remove('spinning');
        btn.disabled = false;
    }
}

// Fetch available leagues and populate form list
async function loadLeagues() {
    const listContainer = document.getElementById('leagues-checkbox-list');
    listContainer.innerHTML = '';
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/leagues?source=${window.currentDataSource}&t=${Date.now()}`, { cache: 'no-store' });
        if (!res.ok) throw new Error("Failed to load leagues");
        const leagues = await res.json();
        
        window.AVAILABLE_LEAGUES = leagues;
        
        // Sort leagues: European seasonal first, then extra international
        leagues.sort((a, b) => a.name.localeCompare(b.name));
        
        leagues.forEach(league => {
            const item = document.createElement('div');
            item.className = 'league-item';
            
            // Check default major leagues
            const checked = ['E0', 'SP1', 'I1', 'D1', 'F1', 'BRA'].includes(league.code) ? 'checked' : '';
            
            item.innerHTML = `<input type="checkbox" id="league-${league.code}" value="${league.code}" ${checked}><label for="league-${league.code}">${league.name}</label>`;
            listContainer.appendChild(item);
        });
    } catch (err) {
        listContainer.innerHTML = '<div class="text-center text-loss">Falha ao carregar as ligas.</div>';
        showToast("Erro ao carregar a lista de ligas do backend.", "error");
    }
}

function toggleStakeLabel() {
    const rule = document.getElementById('stake-rule').value;
    const label = document.getElementById('stake-value-label');
    const stakeInput = document.getElementById('stake-value');
    const stakeValGroup = document.getElementById('stake-val-group');
    const kellySliderContainer = document.getElementById('kelly-slider-container');
    
    if (rule === 'fixed') {
        label.innerText = 'Valor Fixo ($):';
        if (stakeValGroup) stakeValGroup.style.display = 'block';
        if (kellySliderContainer) kellySliderContainer.style.display = 'none';
    } else if (rule === 'proportional') {
        label.innerText = 'Risco na Banca (%):';
        if (stakeValGroup) stakeValGroup.style.display = 'block';
        if (kellySliderContainer) kellySliderContainer.style.display = 'none';
    } else {
        if (stakeValGroup) stakeValGroup.style.display = 'none';
        if (kellySliderContainer) kellySliderContainer.style.display = 'flex';
    }
}

function updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueStats, monthlyStats, oddsStats, optimizedData) {
    if (equityChart) equityChart.destroy();
    if (leagueChart) leagueChart.destroy();
    if (monthlyChart) monthlyChart.destroy();
    if (oddsChart) oddsChart.destroy();

    const ctxEquity = document.getElementById('equity-chart').getContext('2d');
const gradient = ctxEquity.createLinearGradient(0, 0, 0, 400);
gradient.addColorStop(0, 'rgba(99, 102, 241, 0.4)');
gradient.addColorStop(1, 'rgba(99, 102, 241, 0.0)');
    const rule = document.getElementById('stake-rule').value;
    const stakeValueInput = rule === 'kelly' ? parseFloat(document.getElementById('kelly-fraction').value) || 0.25 : parseFloat(document.getElementById('stake-value').value) || 10;

    const fixedStakeVal = rule === 'fixed' ? stakeValueInput : 10;

    const propStakePct = rule === 'proportional' ? stakeValueInput : 2;

       let kellyFractionText = rule === 'kelly' ? stakeValueInput.toFixed(2) + (stakeValueInput == 1 ? ' (Full)' : ' (' + (1/stakeValueInput).toFixed(0) + ')') : '1/4';

    const datasets = [{

        label: 'Geral (Selecionado) ($)',

        data: bankrolls,

        borderColor: '#6366f1',

        borderWidth: 2.5,

        fill: true,

        backgroundColor: gradient,

        tension: 0.15,

        pointRadius: dates.length > 200 ? 0 : 2,

        pointHoverRadius: 5

    }];

    

    if (fixedData) {

        datasets.push({

            label: `Fixed Staking ($${fixedStakeVal})`,

            data: fixedData,

            borderColor: '#f59e0b',

            borderWidth: 1.5,

            borderDash: [4, 4],

            fill: false,

            tension: 0.15,

            pointRadius: dates.length > 200 ? 0 : 1,

            pointHoverRadius: 4

        });

    }



    if (propData) {

        datasets.push({

            label: `Proportional (${propStakePct}%) ($)`,

            data: propData,

            borderColor: '#06b6d4',

            borderWidth: 1.5,

            borderDash: [4, 4],

            fill: false,

            tension: 0.15,

            pointRadius: dates.length > 200 ? 0 : 1,

            pointHoverRadius: 4

        });

    }



    if (kellyData) {

        datasets.push({

            label: `Kelly Staking (${kellyFractionText}) ($)`,

            data: kellyData,

            borderColor: '#ec4899',

            borderWidth: 1.5,

            borderDash: [4, 4],

            fill: false,

            tension: 0.15,

            pointRadius: dates.length > 200 ? 0 : 1,

            pointHoverRadius: 4

        });

    }

    

    if (optimizedData) {

        datasets.push({

            label: 'Banca Otimizada IA ($)',

            data: optimizedData,

            borderColor: '#10b981',

            borderWidth: 2,

            borderDash: [6, 4],

            fill: false,

            tension: 0.15,

            pointRadius: dates.length > 200 ? 0 : 2,

            pointHoverRadius: 5

        });

    }

    

    equityChart = new Chart(ctxEquity, {

        type: 'line',

        data: {

            labels: dates,

            datasets: datasets

        },

        options: {

            responsive: true,

            maintainAspectRatio: false,

            plugins: {

                legend: {

                    display: true,

                    position: 'top',

                    labels: {

                        color: '#9ca3af',

                        font: { family: 'Outfit', size: 11 },

                        usePointStyle: true,

                        boxWidth: 8

                    }

                }

            },

            scales: {

                x: {

                    grid: { color: 'rgba(255, 255, 255, 0.02)' },

                    ticks: { color: '#9ca3af', font: { size: 10 }, maxTicksLimit: 12 }

                },

                y: {

                    grid: { color: 'rgba(255, 255, 255, 0.04)' },

                    ticks: { color: '#9ca3af', font: { size: 11 } }

                }

            }

        }

    });



    // 2. League Performance Chart (Using friendly league names instead of codes!)

    const ctxLeague = document.getElementById('league-chart').getContext('2d');

    if (leagueChart) leagueChart.destroy();

    

    leagueStats.sort((a, b) => b.profit - a.profit);

    

    const leagueNames = leagueStats.map(item => item.league || item.name || 'Desconhecida'); // Full friendly name!

    const profits = leagueStats.map(item => item.profit);

    const colors = profits.map(val => val >= 0 ? 'rgba(16, 185, 129, 0.75)' : 'rgba(239, 68, 68, 0.75)');

    const borderColors = profits.map(val => val >= 0 ? '#10b981' : '#ef4444');

    

    leagueChart = new Chart(ctxLeague, {

        type: 'bar',

        data: {

            labels: leagueNames,

            datasets: [{

                label: 'Lucro Líquido ($)',

                data: profits,

                backgroundColor: colors,

                borderColor: borderColors,

                borderWidth: 1.5,

                borderRadius: 4

            }]

        },

        options: {

            responsive: true,

            maintainAspectRatio: false,

            plugins: {

                legend: { display: false }

            },

            scales: {

                x: {

                    grid: { display: false },

                    ticks: { color: '#9ca3af', font: { size: 10 } }

                },

                y: {

                    grid: { color: 'rgba(255, 255, 255, 0.04)' },

                    ticks: { color: '#9ca3af', font: { size: 11 } }

                }

            }

        }

    });



    // 3. Monthly Performance Chart

    const ctxMonthly = document.getElementById('monthly-chart').getContext('2d');

    if (monthlyChart) monthlyChart.destroy();

    

    const months = monthlyStats.map(item => item.month);

    const monthlyProfits = monthlyStats.map(item => item.profit);

    const monthlyColors = monthlyProfits.map(val => val >= 0 ? 'rgba(16, 185, 129, 0.75)' : 'rgba(239, 68, 68, 0.75)');

    const monthlyBorderColors = monthlyProfits.map(val => val >= 0 ? '#10b981' : '#ef4444');

    

    monthlyChart = new Chart(ctxMonthly, {

        type: 'bar',

        data: {

            labels: months,

            datasets: [{

                label: 'Lucro por Mês ($)',

                data: monthlyProfits,

                backgroundColor: monthlyColors,

                borderColor: monthlyBorderColors,

                borderWidth: 1.5,

                borderRadius: 4

            }]

        },

        options: {

            responsive: true,

            maintainAspectRatio: false,

            plugins: {

                legend: { display: false }

            },

            scales: {

                x: {

                    grid: { display: false },

                    ticks: { color: '#9ca3af', font: { size: 10 }, maxTicksLimit: 18 }

                },

                y: {

                    grid: { color: 'rgba(255, 255, 255, 0.04)' },

                    ticks: { color: '#9ca3af', font: { size: 11 } }

                }

            }

        }

    });



    // 4. Odds Range Performance Chart

    const ctxOdds = document.getElementById('odds-chart').getContext('2d');

    if (oddsChart) oddsChart.destroy();

    

    const ranges = oddsStats.map(item => item.range);

    const oddsProfits = oddsStats.map(item => item.profit);

    const oddsColors = oddsProfits.map(val => val >= 0 ? 'rgba(16, 185, 129, 0.75)' : 'rgba(239, 68, 68, 0.75)');

    const oddsBorderColors = oddsProfits.map(val => val >= 0 ? '#10b981' : '#ef4444');

    

    oddsChart = new Chart(ctxOdds, {

        type: 'bar',

        data: {

            labels: ranges,

            datasets: [{

                label: 'Lucro por Odds ($)',

                data: oddsProfits,

                backgroundColor: oddsColors,

                borderColor: oddsBorderColors,

                borderWidth: 1.5,

                borderRadius: 4

            }]

        },

        options: {

            responsive: true,

            maintainAspectRatio: false,

            plugins: {

                legend: { display: false }

            },

            scales: {

                x: {

                    grid: { display: false },

                    ticks: { color: '#9ca3af', font: { size: 10 } }

                },

                y: {

                    grid: { color: 'rgba(255, 255, 255, 0.04)' },

                    ticks: { color: '#9ca3af', font: { size: 11 } }

                }

            }

        }

    });

}



function renderRiskManagement(results) {

    if (!results || !results.summary) return;

    

    const summary = results.summary || {};

    const ai = results.ai_analysis || {};

    const mc = ai.monte_carlo || {};

    const bankroll = ai.staking_recommendation || {};



    // 1. Cone de Incerteza (Monte Carlo)

    document.getElementById('gr-ruin-prob').textContent = mc.ruin_probability !== undefined ? mc.ruin_probability.toFixed(1) + '%' : '--';

    document.getElementById('gr-mc-prob-profit').textContent = mc.profit_probability !== undefined ? mc.profit_probability.toFixed(1) + '%' : '--';

    

    // Check if we have money format utility or just format it

    const formatMoney = (val) => {

        if (val === undefined || val === null) return '--';

        return '$' + val.toFixed(2);

    };



    document.getElementById('gr-mc-median-profit').textContent = formatMoney(mc.median_net_profit);

    document.getElementById('gr-mc-p5-profit').textContent = formatMoney(mc.percentile_5_net_profit);

    document.getElementById('gr-mc-p95-profit').textContent = formatMoney(mc.percentile_95_net_profit);



    // 2. Estresse Estatístico

    document.getElementById('gr-max-drawdown').textContent = summary.max_drawdown != null ? summary.max_drawdown.toFixed(2) + '%' : '--';

    document.getElementById('gr-sharpe').textContent = summary.sharpe_ratio != null ? summary.sharpe_ratio.toFixed(2) : '--';

    document.getElementById('gr-sortino').textContent = summary.sortino_ratio != null ? summary.sortino_ratio.toFixed(2) : '--';

    document.getElementById('gr-skewness').textContent = summary.skewness != null ? summary.skewness.toFixed(2) : '--';

    document.getElementById('gr-edge-decay').textContent = summary.edge_decay_pct != null ? summary.edge_decay_pct.toFixed(1) + '%' : '--';

    

    // Format p-value

    let pval = '--';

    if (summary.p_value != null) {

        if (summary.p_value < 0.001) pval = '< 0.001';

        else pval = summary.p_value.toFixed(4);

    }

    document.getElementById('gr-pvalue').textContent = pval;



    // 3. Matriz de Recomendação de Stakes

    if (bankroll.recommended_stake_pct) {

        document.getElementById('gr-rec-stake').textContent = bankroll.recommended_stake_pct.toFixed(2) + '%';

        

        // Also populate the Bankroll detailed card

        const recBox = document.getElementById('gr-rec-stake-box');

        if (recBox) recBox.textContent = bankroll.recommended_stake_pct.toFixed(2) + '%';

        

        const minBank = document.getElementById('gr-min-bankroll');

        if (minBank && bankroll.min_recommended_bankroll) {

            minBank.textContent = bankroll.min_recommended_bankroll.toFixed(1) + ' Unidades';

        }

        

        const justif = document.getElementById('gr-bankroll-justification');

        if (justif && bankroll.justification) {

            justif.textContent = bankroll.justification;

        }

    } else {

        document.getElementById('gr-rec-stake').textContent = '--';

    }



    // 4. Parecer de Risco Institucional

    const adviceEl = document.getElementById('gr-ai-advice');

    let adviceHtml = '';

    

    // Ruin warning

    if (mc.ruin_probability > 5.0) {

        adviceHtml += `<div style="margin-bottom: 10px; color: var(--danger);"><i class="fa-solid fa-triangle-exclamation"></i> <strong>Risco de Quebra Crítico:</strong> A probabilidade de ruína é de ${mc.ruin_probability.toFixed(1)}%. Reduza sua stake imediatamente.</div>`;

    }



    // Drawdown warning

    if (summary.max_drawdown > 30) {

        adviceHtml += `<div style="margin-bottom: 10px; color: var(--warning);"><i class="fa-solid fa-water"></i> <strong>Drawdown Severo:</strong> O rebaixamento histórico de ${summary.max_drawdown.toFixed(1)}% exige preparo psicológico e capital de giro reserva.</div>`;

    } else if (summary.max_drawdown < 15 && summary.max_drawdown > 0) {

        adviceHtml += `<div style="margin-bottom: 10px; color: var(--success);"><i class="fa-solid fa-shield-check"></i> <strong>Drawdown Controlado:</strong> A volatilidade desta estratégia é muito suave (${summary.max_drawdown.toFixed(1)}%), ideal para preservação de capital.</div>`;

    }



    // Shape/Skewness insight

    if (summary.skewness < -1.0) {

        adviceHtml += `<div style="margin-bottom: 10px; color: var(--warning);"><i class="fa-solid fa-arrow-trend-down"></i> <strong>Assimetria Negativa:</strong> Esta estratégia tem pequenos ganhos frequentes, mas sofre perdas severas repentinas (Skewness: ${summary.skewness.toFixed(2)}).</div>`;

    }



    if (adviceHtml === '') {

        adviceHtml = `<div style="color: var(--success);"><i class="fa-solid fa-check"></i> <strong>Perfil Saudável:</strong> O perfil de risco atual é equilibrado e compatível com as stakes utilizadas.</div>`;

    }



    adviceEl.innerHTML = adviceHtml;

}



function renderProbValue(prob, barType) {

    if (prob === undefined || isNaN(prob)) return '-';

    let colorClass = 'bar-draw'; // default

    

    if (['home', 'ht_home', 'over', 'over15', 'over25', 'over35', 'over45', 'over55', 'btts_yes', 'yes', 'ht_over05', 'ht_over15'].includes(barType)) {

        colorClass = 'bar-home';

    } else if (['away', 'ht_away', 'under', 'under25', 'under35', 'under45', 'under55', 'btts_no', 'no', 'ht_under05', 'ht_under15'].includes(barType)) {

        colorClass = 'bar-away';

    } else if (barType.startsWith('cs_')) {

        const scores = barType.replace('cs_', '').split('');

        if (scores.length === 2) {

            const h = parseInt(scores[0]);

            const a = parseInt(scores[1]);

            if (h > a) colorClass = 'bar-home';

            else if (h < a) colorClass = 'bar-away';

            else colorClass = 'bar-draw';

        }

    } else if (barType.startsWith('lay_')) {

        if (barType === 'lay_home') colorClass = 'bar-away';

        else if (barType === 'lay_away') colorClass = 'bar-home';

        else colorClass = 'bar-draw';

    }

    

    return `

        <div class="prob-bar-container" title="${prob.toFixed(1)}%">

            <div class="prob-bar-fill ${colorClass}" style="width: ${prob.toFixed(1)}%"></div>

        </div>

        <span>${prob.toFixed(1)}%</span>

    `;

}



// Populate bets table

function populateBetsTable(bets) {

    const tbody = document.getElementById('bets-table-body');

    tbody.innerHTML = '';

    

    if (bets.length === 0) {

        tbody.innerHTML = `

            <tr>

                <td colspan="10" class="text-center empty-state">

                    <i class="fa-solid fa-face-frown"></i> Nenhuma aposta realizada nesta simulação. Tente ajustar o gatilho de valor EV ou as ligas.

                </td>

            </tr>

        `;

        return;

    }

    

    // Render bets in reverse chronological order (latest first)

    bets.slice().reverse().forEach(bet => {

        const tr = document.createElement('tr');

        const profitClass = bet.profit >= 0 ? 'text-profit' : 'text-loss';

        const winBadge = bet.profit >= 0 ? '<span class="badge-row-win">Green</span>' : '<span class="badge-row-loss">Red</span>';

        

        tr.innerHTML = `

            <td>${bet.date}</td>

            <td><strong>${bet.league}</strong></td>

            <td>${bet.home_team} vs ${bet.away_team}</td>

            <td>${bet.market}</td>

            <td>${bet.odds.toFixed(2)}</td>

            <td>${bet.prob}%</td>

            <td>${bet.ev.toFixed(2)}</td>

            <td>$${bet.stake.toFixed(2)}</td>

            <td class="${profitClass}">${bet.profit >= 0 ? '+' : ''}$${bet.profit.toFixed(2)} ${winBadge}</td>

            <td>$${bet.bankroll.toFixed(2)}</td>

        `;

        

        tr.style.cursor = 'pointer';

        tr.onclick = () => showMatchDetails(bet);

        

        tbody.appendChild(tr);

    });

}



// Simple filter on table by typing team names

function filterTable() {

    const search = document.getElementById('table-search').value.toLowerCase();

    

    const filteredBets = allBets.filter(bet => 

        bet.home_team.toLowerCase().includes(search) || 

        bet.away_team.toLowerCase().includes(search) ||

        bet.league.toLowerCase().includes(search)

    );

    

    populateBetsTable(filteredBets);

}



// ==========================================================================

// Strategy Scanner Logic

// ==========================================================================

async function runScanner(scanType) {

    const btnMarkets = document.getElementById('btn-scan-markets');

    const btnLeagues = document.getElementById('btn-scan-leagues');

    const resultsDiv = document.getElementById('scanner-results');

    

    const activeBtn = scanType === 'markets' ? btnMarkets : btnLeagues;

    const inactiveBtn = scanType === 'markets' ? btnLeagues : btnMarkets;

    

    let selectedLeagues;

    if (scanType === 'leagues') {

        // Scan ALL available leagues in the system

        selectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]'))

            .map(cb => cb.value);

    } else {

        // Scan markets only for checked leagues

        selectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked'))

            .map(cb => cb.value);

            

        if (selectedLeagues.length === 0) {

            showToast("Por favor, selecione pelo menos um campeonato no painel lateral.", "error");

            return;

        }

    }

    

    activeBtn.classList.add('scanning');

    activeBtn.disabled = true;

    activeBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Escaneando...`;

    inactiveBtn.disabled = true;

    

    showToast(`Escaneando ${scanType === 'markets' ? 'todos os mercados' : 'todas as ligas'} (+EV)...`, "info");

    

    const ruleInput = document.getElementById('stake-rule').value;

    let stakingRule = ruleInput;

    let stakeValue = parseFloat(document.getElementById('stake-value').value);

    

    if (ruleInput.startsWith('kelly')) {

        stakingRule = 'kelly';

        if (ruleInput === 'kelly') stakeValue = 1.0;

        else if (ruleInput === 'kelly_half') stakeValue = 0.5;

        else if (ruleInput === 'kelly_quarter') stakeValue = 0.25;

        else if (ruleInput === 'kelly_eighth') stakeValue = 0.125;
        else if (ruleInput === 'kelly_sixteenth') stakeValue = 0.0625;

    }

    

    const requestData = {

        leagues: selectedLeagues,

        startDate: document.getElementById('start-date').value,

        endDate: document.getElementById('end-date').value,

        market: Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value),

        valueThreshold: parseFloat(document.getElementById('val-threshold').value),

        initialBankroll: parseFloat(document.getElementById('init-bankroll').value),

        stakingRule: stakingRule,

        stakeValue: stakeValue,

        oddsSource: document.getElementById('odds-source').value,

        scanType: scanType,

        minOdds: parseFloat(document.getElementById('min-odds').value) || 1.0,

        maxOdds: parseFloat(document.getElementById('max-odds').value) || 50.0,

        use_ml: document.getElementById('use-ml-toggle')?.checked || false,

        data_source: window.currentDataSource,

        futpython_api_key: window.futpythonApiKey

    };

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/scan`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(requestData)

        });

        

        if (!res.ok) {

            const errData = await res.json();

            throw new Error(errData.detail || "Erro ao escanear");

        }

        

        const data = await res.json();

        const results = data.results;

        

        lastScanResults = results;

        lastScanParams = requestData;

        

        showToast("Escaneamento concluído!", "success");

        

        results.sort((a, b) => b.net_profit - a.net_profit);

        

        resultsDiv.innerHTML = '';

        resultsDiv.style.display = 'grid';

        

        if (results.length === 0) {

            resultsDiv.innerHTML = `

                <div class="empty-state text-center" style="grid-column: 1 / -1; width: 100%;">

                    <i class="fa-solid fa-database" style="font-size: 24px; margin-bottom: 8px; color: var(--text-muted);"></i>

                    <p>Nenhum dado encontrado para escanear.</p>

                    <p style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">Certifique-se de que clicou em <strong>Sincronizar</strong> no canto superior direito para baixar a base de dados!</p>

                </div>

            `;

            return;

        }

        

        // Add action bar

        const actionBar = document.createElement('div');

        actionBar.id = 'scanner-action-bar';

        actionBar.style.cssText = "grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; background: rgba(99, 102, 241, 0.05); border: 1px solid rgba(99, 102, 241, 0.15); border-radius: var(--border-radius-md); padding: 12px 20px; margin-bottom: 10px; gap: 15px; flex-wrap: wrap;";

        actionBar.innerHTML = `

            <span style="font-size: 13px; color: var(--text-secondary); display: flex; align-items: center; gap: 8px;">

                <i class="fa-solid fa-list-check" style="color: var(--primary); font-size: 16px;"></i>

                <span>Selecione as opções desejadas e clique para simular juntas:</span>

            </span>

            <div style="display: flex; gap: 10px; flex-wrap: wrap;">

                <button type="button" class="btn-scanner" id="btn-export-scanner" onclick="exportScannerResults()" style="margin-top: 0; padding: 8px 16px; font-size: 13px; background: transparent; border-color: var(--primary); color: var(--primary); white-space: nowrap; height: auto;">

                    <i class="fa-solid fa-download"></i> Exportar Resultados

                </button>

                <button type="button" class="btn-scanner" id="btn-simulate-selected" onclick="simulateSelectedScannerItems()" style="margin-top: 0; padding: 8px 16px; font-size: 13px; background: var(--primary); border-color: var(--primary); box-shadow: 0 4px 15px var(--primary-glow); white-space: nowrap; height: auto;">

                    <i class="fa-solid fa-play"></i> Simular Selecionados Juntos

                </button>

            </div>

        `;

        resultsDiv.appendChild(actionBar);

        

        results.forEach(item => {

            const isProfit = item.net_profit >= 0;

            const profitClass = isProfit ? 'positive' : 'negative';

            const sign = isProfit ? '+' : '';

            const card = document.createElement('div');

            card.className = `scanner-item-card ${profitClass}`;

            

            // Render AI score if available and if we have enough bets

            let aiScoreHtml = '';

            if (item.ai_score !== undefined && item.total_bets >= 20) {

                const score = item.ai_score;

                let scoreClass = 'medium';

                let scoreText = 'Estável';

                if (score >= 65) {

                    scoreClass = 'high';

                    scoreText = 'Sustentável';

                } else if (score < 48) {

                    scoreClass = 'low';

                    scoreText = 'Risco';

                }

                aiScoreHtml = `

                    <div class="scanner-ai-score-container">

                        <span class="scanner-ai-label"><i class="fa-solid fa-robot"></i> Previsão IA:</span>

                        <span class="scanner-ai-val ${scoreClass}">${score.toFixed(1)}% (${scoreText})</span>

                    </div>

                `;

            }

            

            // Auto check if it was profitable (green) (Disabled to default to unchecked)

            const isChecked = '';

            

            card.innerHTML = `

                <div class="scanner-item-header">

                    <div style="display: flex; align-items: center; gap: 8px;">

                        <input type="checkbox" class="scanner-item-cb" value="${item.code}" data-scantype="${scanType}" style="cursor: pointer; width: 16px; height: 16px; accent-color: var(--primary);" ${isChecked}>

                        <span class="scanner-item-title">${item.name}</span>

                    </div>

                    <span class="scanner-item-profit ${profitClass}">${sign}$${item.net_profit.toFixed(2)}</span>

                </div>

                <div class="scanner-item-body">

                    <span>ROI: <strong class="${profitClass}">${sign}${item.roi.toFixed(2)}%</strong></span>

                    <span>Acertos: <strong>${item.win_rate.toFixed(1)}%</strong></span>

                    <span>Apostas: <strong>${item.total_bets}</strong></span>

                </div>

                ${aiScoreHtml}

                ${(function() {

                    const pValAdj = item.p_value_adjusted;

                    let pColor = 'var(--danger)';

                    let pLabel = 'Não Significativo';

                    let pIcon = 'fa-xmark';

                    if (pValAdj !== undefined && pValAdj !== null) {

                        if (pValAdj < 0.01) { pColor = 'var(--success)'; pLabel = 'Altamente Significativo'; pIcon = 'fa-check-double'; }

                        else if (pValAdj < 0.05) { pColor = 'var(--success)'; pLabel = 'Significativo'; pIcon = 'fa-check'; }

                        else if (pValAdj < 0.10) { pColor = 'var(--warning)'; pLabel = 'Marginalmente Significativo'; pIcon = 'fa-minus'; }

                    }

                    return pValAdj !== undefined ? `

                    <div style="display: flex; justify-content: space-between; font-size: 12px; margin-top: 5px; padding-top: 5px; border-top: 1px solid rgba(255,255,255,0.05);" title="p-valor ajustado por FDR (Benjamini-Hochberg). Valores abaixo de 0,05 indicam significância estatística, ou seja, é improvável que o resultado seja fruto do acaso." onclick="showToast(this.title, 'info')">

                        <span style="color: var(--text-muted);">p-valor (FDR):</span>

                        <span style="color: ${pColor}; font-weight: 600;"><i class="fa-solid ${pIcon}"></i> ${pValAdj.toFixed(3)} — ${pLabel}</span>

                    </div>` : '';

                })()}

                <button type="button" class="btn-scanner-apply" onclick="applyScannedStrategy('${scanType}', '${item.code}')">

                    <i class="fa-solid fa-square-check"></i> Aplicar e Simular

                </button>

            `;

            resultsDiv.appendChild(card);

        });

        

    } catch (err) {

        console.error(err);

        showToast(err.message, "error");

    } finally {

        btnMarkets.classList.remove('scanning');

        btnMarkets.disabled = false;

        btnMarkets.innerHTML = `<i class="fa-solid fa-chart-pie"></i> Escanear Mercados`;

        

        btnLeagues.classList.remove('scanning');

        btnLeagues.disabled = false;

        btnLeagues.innerHTML = `<i class="fa-solid fa-ranking-star"></i> Escanear Ligas`;

    }

}



function exportScannerResults() {

    if (!lastScanResults || lastScanResults.length === 0) {

        showToast("Nenhum resultado de escaneamento para exportar.", "error");

        return;

    }



    const params = lastScanParams;

    const results = lastScanResults;



    const escapeCsv = (str) => {

        if (str === null || str === undefined) return '';

        const s = String(str);

        if (s.includes(';') || s.includes('"') || s.includes('\n')) {

            return `"${s.replace(/"/g, '""')}"`;

        }

        return s;

    };



    const formatDate = (dateStr) => {

        if (!dateStr) return '';

        const parts = dateStr.split('-');

        if (parts.length === 3) {

            return `${parts[2]}/${parts[1]}/${parts[0]}`;

        }

        return dateStr;

    };



    let csvRows = [];

    csvRows.push("PARÂMETROS DO ESCANEAMENTO");

    csvRows.push(`Tipo de Escaneamento;${params.scanType === 'markets' ? 'Mercados' : 'Ligas'}`);

    csvRows.push(`Data de Início;${formatDate(params.startDate)}`);

    csvRows.push(`Data de Fim;${formatDate(params.endDate)}`);

    csvRows.push(`Gatilho EV (+);${params.valueThreshold.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Banca Inicial;${params.initialBankroll.toFixed(2).replace('.', ',')}`);

    

    const stakeRuleSelect = document.getElementById('stake-rule');

    const stakeRuleText = stakeRuleSelect.options[stakeRuleSelect.selectedIndex].text;

    csvRows.push(`Gestão de Banca;${escapeCsv(stakeRuleText)}`);

    csvRows.push(`Valor/Multiplicador da Aposta;${params.stakeValue.toString().replace('.', ',')}`);

    

    const oddsSourceSelect = document.getElementById('odds-source');

    const oddsSourceText = oddsSourceSelect.options[oddsSourceSelect.selectedIndex].text;

    csvRows.push(`Fonte de Odds;${escapeCsv(oddsSourceText)}`);

    csvRows.push(`Odds Mínima;${params.minOdds.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Odds Máxima;${params.maxOdds.toFixed(2).replace('.', ',')}`);

    

    const selectedMarkets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked'))

        .map(cb => cb.parentNode.textContent.trim())

        .join(', ');

    csvRows.push(`Mercados Escaneados;${escapeCsv(selectedMarkets || 'Nenhum')}`);

    

    let selectedLeaguesText = '';

    if (params.scanType === 'leagues') {

        selectedLeaguesText = "Todas as Ligas Disponíveis";

    } else {

        selectedLeaguesText = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked'))

            .map(cb => cb.parentNode.querySelector('label').textContent.trim())

            .join(', ');

    }

    csvRows.push(`Ligas Escaneadas;${escapeCsv(selectedLeaguesText || 'Nenhuma')}`);

    

    csvRows.push("");

    

    csvRows.push("RESULTADOS DO ESCANEAMENTO");

    csvRows.push("Nome;Lucro Líquido;ROI (Yield);Taxa de Acerto;Total de Apostas;Previsão IA");



    results.forEach(item => {

        const name = item.name;

        const profit = item.net_profit.toFixed(2).replace('.', ',');

        const roi = item.roi.toFixed(2).replace('.', ',') + "%";

        const winRate = item.win_rate.toFixed(1).replace('.', ',') + "%";

        const bets = item.total_bets;

        

        let aiScore = '';

        if (item.ai_score !== undefined && item.total_bets >= 20) {

            const score = item.ai_score;

            let scoreText = 'Estável';

            if (score >= 65) scoreText = 'Sustentável';

            else if (score < 48) scoreText = 'Risco';

            aiScore = `${score.toFixed(1).replace('.', ',')}% (${scoreText})`;

        } else {

            aiScore = 'N/A';

        }

        

        csvRows.push(`${escapeCsv(name)};${profit};${roi};${winRate};${bets};${escapeCsv(aiScore)}`);

    });



    const csvContent = csvRows.join("\n");

    const today = new Date().toISOString().slice(0,10).split('-').reverse().join('-');

    const filename = `escaneamento_${params.scanType}_${today}.csv`;

    

    const blob = new Blob(["\uFEFF" + csvContent], { type: 'text/csv;charset=utf-8;' });

    const link = document.createElement("a");

    if (link.download !== undefined) {

        const url = URL.createObjectURL(blob);

        link.setAttribute("href", url);

        link.setAttribute("download", filename);

        link.style.visibility = 'hidden';

        document.body.appendChild(link);

        link.click();

        document.body.removeChild(link);

    }

    showToast("Resultados exportados para CSV com sucesso!", "success");

}



function exportBacktestReport() {

    if (!lastBacktestSummary || !lastBacktestSummary.summary) {

        showToast("Nenhum resultado de backtest disponível para exportar. Execute um backtest primeiro!", "error");

        return;

    }



    const params = lastBacktestParams;

    const summary = lastBacktestSummary.summary;

    const summaryFixed = lastBacktestSummary.summary_fixed;

    const summaryProp = lastBacktestSummary.summary_proportional;

    const summaryKelly = lastBacktestSummary.summary_kelly;

    const bets = lastBacktestSummary.bets;



    const escapeCsv = (str) => {

        if (str === null || str === undefined) return '';

        const s = String(str);

        if (s.includes(';') || s.includes('"') || s.includes('\n')) {

            return `"${s.replace(/"/g, '""')}"`;

        }

        return s;

    };



    const formatDate = (dateStr) => {

        if (!dateStr) return '';

        const parts = dateStr.split('-');

        if (parts.length === 3) {

            return `${parts[2]}/${parts[1]}/${parts[0]}`;

        }

        return dateStr;

    };



    let csvRows = [];



    // --- SECTION 1: PARAMETERS ---

    csvRows.push("PARÂMETROS DA SIMULAÇÃO");

    csvRows.push(`Período;${formatDate(params.startDate)} a ${formatDate(params.endDate)}`);

    csvRows.push(`Gatilho EV (+);${params.valueThreshold.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Banca Inicial;${params.initialBankroll.toFixed(2).replace('.', ',')}`);

    

    const stakeRuleSelect = document.getElementById('stake-rule');

    const stakeRuleText = stakeRuleSelect.options[stakeRuleSelect.selectedIndex].text;

    csvRows.push(`Gestão de Banca Selecionada;${escapeCsv(stakeRuleText)}`);

    csvRows.push(`Valor/Multiplicador da Aposta;${params.stakeValue.toString().replace('.', ',')}`);

    

    const oddsSourceSelect = document.getElementById('odds-source');

    const oddsSourceText = oddsSourceSelect.options[oddsSourceSelect.selectedIndex].text;

    csvRows.push(`Fonte de Odds;${escapeCsv(oddsSourceText)}`);

    csvRows.push(`Odds Mínima;${params.minOdds.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Odds Máxima;${params.maxOdds.toFixed(2).replace('.', ',')}`);



    const activeLeagues = params.leagues.map(code => {

        const lbl = document.querySelector(`label[for="league-${code}"]`);

        return lbl ? lbl.innerText : code;

    }).join(', ');

    csvRows.push(`Ligas Selecionadas;${escapeCsv(activeLeagues)}`);



    const activeMarkets = params.market.map(val => {

        const cb = document.querySelector(`#market-checkboxes-container input[value="${val}"]`);

        return cb ? cb.parentNode.textContent.trim() : val;

    }).join(', ');

    csvRows.push(`Mercados Selecionados;${escapeCsv(activeMarkets)}`);

    csvRows.push("");



    // --- SECTION 2: SUMMARY METRICS ---

    csvRows.push("MÉTRICAS GERAIS DO BACKTEST");

    csvRows.push(`Banca Final;${summary.final_bankroll.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Lucro Líquido ($);${summary.net_profit.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Lucro em Stakes (st);${summary.profit_in_stakes.toFixed(2).replace('.', ',')}`);

    csvRows.push(`ROI / Yield (%);${summary.roi.toFixed(2).replace('.', ',')}%`);

    csvRows.push(`Taxa de Acerto (%);${summary.win_rate.toFixed(1).replace('.', ',')}%`);

    csvRows.push(`Total de Apostas;${summary.total_bets}`);

    csvRows.push(`Odd Média;${summary.avg_odds.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Max Drawdown (%);${summary.max_drawdown.toFixed(1).replace('.', ',')}%`);

    csvRows.push("");



    // --- SECTION 3: ADVANCED RISK METRICS ---

    csvRows.push("MÉTRICAS AVANÇADAS DE RISCO");

    csvRows.push(`Índice de Sharpe (Anualizado);${summary.sharpe_ratio.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Índice de Sortino (Risco Queda);${summary.sortino_ratio.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Assimetria de Retornos (Skewness);${summary.skewness.toFixed(2).replace('.', ',')}`);

    csvRows.push(`Maior Seq. de Greens (Acertos);${summary.max_consec_wins}`);

    csvRows.push(`Maior Seq. de Reds (Derrotas);${summary.max_consec_losses}`);

    csvRows.push("");



    // --- SECTION 3b: STATISTICAL VALIDATION ---

    csvRows.push("VALIDAÇÃO ESTATÍSTICA");

    if (summary.brier_score !== undefined) {

        csvRows.push(`Brier Score Modelo;${summary.brier_score.toFixed(3).replace('.', ',')}`);

        csvRows.push(`Brier Score Mercado;${(summary.brier_score_market !== undefined ? summary.brier_score_market.toFixed(3) : 'N/A').replace('.', ',')}`);

    }

    if (summary.bootstrap_roi_ci_lower !== undefined) {

        csvRows.push(`Intervalo Confiança ROI (95%);${summary.bootstrap_roi_ci_lower.toFixed(1).replace('.', ',')}% — ${summary.bootstrap_roi_ci_upper.toFixed(1).replace('.', ',')}%`);

    }

    if (summary.prob_positive_roi !== undefined) {

        csvRows.push(`Prob. ROI Positivo;${(summary.prob_positive_roi * 100).toFixed(1).replace('.', ',')}%`);

    }

    if (summary.min_sample_size !== undefined) {

        csvRows.push(`Amostra Mínima Necessária;${summary.min_sample_size}`);

        csvRows.push(`Amostra Suficiente;${summary.sample_sufficient ? 'Sim' : 'Não'}`);

    }

    if (summary.edge_decay_pct !== undefined) {

        csvRows.push(`Decay do Edge;${summary.edge_decay_pct.toFixed(1).replace('.', ',')}%`);

    }

    csvRows.push("");



    // --- SECTION 4: STAKING COMPARISON ---

    csvRows.push("COMPARATIVO POR GESTÃO DE BANCA");

    csvRows.push("Método;Banca Final;Lucro ($);Apostas;Acerto;ROI;Drawdown");

    

    const fixedLabel = `Stake Fixa ($${params.stakingRule === 'fixed' ? params.stakeValue : 10})`;

    csvRows.push(`${escapeCsv(fixedLabel)};${summaryFixed.final_bankroll.toFixed(2).replace('.', ',')};${summaryFixed.net_profit.toFixed(2).replace('.', ',')};${summaryFixed.total_bets};${summaryFixed.win_rate.toFixed(1).replace('.', ',')}%;${summaryFixed.roi.toFixed(2).replace('.', ',')}%;${summaryFixed.max_drawdown.toFixed(2).replace('.', ',')}%`);

    

    csvRows.push("Stake Proporcional (2%);" + 

                 `${summaryProp.final_bankroll.toFixed(2).replace('.', ',')};` + 

                 `${summaryProp.net_profit.toFixed(2).replace('.', ',')};` + 

                 `${summaryProp.total_bets};` + 

                 `${summaryProp.win_rate.toFixed(1).replace('.', ',')}%;` + 

                 `${summaryProp.roi.toFixed(2).replace('.', ',')}%;` + 

                 `${summaryProp.max_drawdown.toFixed(2).replace('.', ',')}%`);

                 

    let kellyLabel = "Critério Kelly (1/4 de Kelly)";

    if (params.stakingRule === 'kelly') {

        const fracText = params.stakeValue === 1.0 ? "Full Kelly" : `Kelly ${params.stakeValue.toString()}`;

        kellyLabel = `Critério Kelly (${fracText})`;

    }

    csvRows.push(`${escapeCsv(kellyLabel)};${summaryKelly.final_bankroll.toFixed(2).replace('.', ',')};${summaryKelly.net_profit.toFixed(2).replace('.', ',')};${summaryKelly.total_bets};${summaryKelly.win_rate.toFixed(1).replace('.', ',')}%;${summaryKelly.roi.toFixed(2).replace('.', ',')}%;${summaryKelly.max_drawdown.toFixed(2).replace('.', ',')}%`);

    csvRows.push("");



    // --- SECTION 5: HISTÓRICO COMPLETO DE APOSTAS ---

    csvRows.push("HISTÓRICO COMPLETO DE APOSTAS");

    csvRows.push("Data;Liga;Confronto;Mercado;Odd;Probabilidade Modelo;Gatilho EV;Stake;Lucro;Saldo Banca");



    bets.forEach(b => {

        const date = formatDate(b.date);

        const league = b.league;

        const match = `${b.home_team} vs ${b.away_team}`;

        

        let market = b.market;

        const marketCb = document.querySelector(`#market-checkboxes-container input[value="${b.market}"]`);

        if (marketCb) {

            market = marketCb.parentNode.textContent.trim();

        }



        const odds = b.odds.toFixed(2).replace('.', ',');

        const prob = b.prob.toFixed(1).replace('.', ',') + "%";

        const ev = b.ev.toFixed(2).replace('.', ',');

        const stake = b.stake.toFixed(2).replace('.', ',');

        const profit = b.profit.toFixed(2).replace('.', ',');

        const bankroll = b.bankroll.toFixed(2).replace('.', ',');



        csvRows.push(`${escapeCsv(date)};${escapeCsv(league)};${escapeCsv(match)};${escapeCsv(market)};${odds};${prob};${ev};${stake};${profit};${bankroll}`);

    });



    const csvContent = csvRows.join("\n");

    const today = new Date().toISOString().slice(0,10).split('-').reverse().join('-');

    const filename = `relatorio_backtest_${today}.csv`;

    

    const blob = new Blob(["\uFEFF" + csvContent], { type: 'text/csv;charset=utf-8;' });

    const link = document.createElement("a");

    if (link.download !== undefined) {

        const url = URL.createObjectURL(blob);

        link.setAttribute("href", url);

        link.setAttribute("download", filename);

        link.style.visibility = 'hidden';

        document.body.appendChild(link);

        link.click();

        document.body.removeChild(link);

    }

    showToast("Relatório de backtest exportado com sucesso!", "success");

}



function applyScannedStrategy(scanType, code) {

    if (scanType === 'markets') {

        const checkboxes = document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]');

        let marketText = code;

        checkboxes.forEach(cb => {

            if (cb.value === code) {

                cb.checked = true;

                marketText = cb.parentNode.textContent.trim();

            } else {

                cb.checked = false;

            }

        });

        onMarketSelectionChange();

        showToast(`Mercado alterado para "${marketText}". Executando simulação completa...`, "success");

    } else {

        const checkboxes = document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]');

        checkboxes.forEach(cb => {

            cb.checked = (cb.value === code);

        });

        

        const label = document.querySelector(`label[for="league-${code}"]`);

        const leagueName = label ? label.innerText : code;

        showToast(`Filtro de liga alterado para "${leagueName}". Executando simulação completa...`, "success");

    }

    

    runBacktest();

}



function displayAiAnalysis(aiAnalysis, results) {

    const aiPanel = document.getElementById('ai-analytics-panel');

    const optPanel = document.getElementById('ai-optimization-panel');

    if (!aiAnalysis || aiAnalysis.status === 'insufficient_data') {

        aiPanel.style.display = 'none';

        optPanel.style.display = 'none';

        return;

    }

    

    aiPanel.style.display = 'block';

    

    // Fill text and values

    document.getElementById('ai-ml-probability').innerText = `${aiAnalysis.ml_probability.toFixed(1)}%`;

    const mlProgress = document.getElementById('ai-ml-progress');

    mlProgress.style.width = `${aiAnalysis.ml_probability}%`;

    

    document.getElementById('ai-bayesian-confidence').innerText = `${aiAnalysis.bayesian_confidence.toFixed(1)}%`;

    const bayesianProgress = document.getElementById('ai-bayesian-progress');

    bayesianProgress.style.width = `${aiAnalysis.bayesian_confidence}%`;

    

    // Drift

    const driftVal = document.getElementById('ai-drift-value');

    const sign = aiAnalysis.drift_ratio >= 0 ? '+' : '';

    driftVal.innerText = `${sign}${aiAnalysis.drift_ratio.toFixed(1)}%`;

    

    // Color of drift value

    if (aiAnalysis.drift_ratio >= 0) {

        driftVal.className = 'widget-value text-profit';

    } else if (aiAnalysis.drift_ratio < -8) {

        driftVal.className = 'widget-value text-loss';

    } else {

        driftVal.className = 'widget-value'; // neutral or light decay

    }

    

    document.getElementById('ai-roi-first').innerText = `${aiAnalysis.roi_first_half.toFixed(1)}%`;

    document.getElementById('ai-roi-second').innerText = `${aiAnalysis.roi_second_half.toFixed(1)}%`;

    

    // Colors of first/second ROI

    const roiFirstSpan = document.getElementById('ai-roi-first');

    const roiSecondSpan = document.getElementById('ai-roi-second');

    roiFirstSpan.className = aiAnalysis.roi_first_half >= 0 ? 'half-val text-profit' : 'half-val text-loss';

    roiSecondSpan.className = aiAnalysis.roi_second_half >= 0 ? 'half-val text-profit' : 'half-val text-loss';



    // Set Verdict badge and report text

    const badge = document.getElementById('ai-verdict-badge');

    const reportText = document.getElementById('ai-report-text');

    

    // Simple markdown interpreter for report text (converting **bold** to <strong> and newlines to <br>)

    let formattedReport = aiAnalysis.report

        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')

        .replace(/\n/g, '<br>');

        

    reportText.innerHTML = formattedReport;

    

    // Classify badge based on ML probability & Bayesian confidence & Drift

    if (aiAnalysis.ml_probability >= 65 && aiAnalysis.bayesian_confidence >= 70 && aiAnalysis.drift_ratio >= -3) {

        badge.innerText = 'Excelente / Sustentável';

        badge.className = 'badge badge-high';

    } else if (aiAnalysis.ml_probability < 50 && aiAnalysis.bayesian_confidence < 60) {

        badge.innerText = 'Risco Alto / Overfitting';

        badge.className = 'badge badge-low';

    } else if (aiAnalysis.drift_ratio < -8) {

        badge.innerText = 'Alerta de Decaimento';

        badge.className = 'badge badge-medium';

    } else {

        badge.innerText = 'Moderação / Estável';

        badge.className = 'badge badge-medium';

    }

    

    // Fill Monte Carlo statistics

    const mc = aiAnalysis.monte_carlo;

    if (mc) {

        document.getElementById('mc-profit-probability').innerText = `${mc.profit_probability.toFixed(1)}%`;

        const profitProgress = document.getElementById('mc-profit-progress');

        profitProgress.style.width = `${mc.profit_probability}%`;

        

        document.getElementById('mc-ruin-probability').innerText = `${mc.ruin_probability.toFixed(1)}%`;
        const halfRuinEl = document.getElementById('mc-half-ruin-probability');
        if (halfRuinEl && mc.half_ruin_probability !== undefined) {
            halfRuinEl.innerText = `${mc.half_ruin_probability.toFixed(1)}%`;
        }

        const ruinProgress = document.getElementById('mc-ruin-progress');

        ruinProgress.style.width = `${mc.ruin_probability}%`;

        

        const medianProfitSpan = document.getElementById('mc-median-profit');

        medianProfitSpan.innerText = (mc.median_net_profit >= 0 ? '+' : '') + `$${mc.median_net_profit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

        medianProfitSpan.className = mc.median_net_profit >= 0 ? 'widget-value text-profit' : 'widget-value text-loss';

        

        const p5Span = document.getElementById('mc-percentile-5');

        p5Span.innerText = (mc.percentile_5_net_profit >= 0 ? '+' : '') + `$${mc.percentile_5_net_profit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

        p5Span.className = mc.percentile_5_net_profit >= 0 ? 'half-val text-profit' : 'half-val text-loss';

        

        const p95Span = document.getElementById('mc-percentile-95');

        p95Span.innerText = (mc.percentile_95_net_profit >= 0 ? '+' : '') + `$${mc.percentile_95_net_profit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

        p95Span.className = mc.percentile_95_net_profit >= 0 ? 'half-val text-profit' : 'half-val text-loss';

    } else {

        document.getElementById('mc-profit-probability').innerText = '0.0%';

        document.getElementById('mc-profit-progress').style.width = '0%';

        document.getElementById('mc-ruin-probability').innerText = '0.0%';
        const halfRuinEl2 = document.getElementById('mc-half-ruin-probability');
        if (halfRuinEl2) halfRuinEl2.innerText = '0.0%';

        document.getElementById('mc-ruin-progress').style.width = '0%';

        document.getElementById('mc-median-profit').innerText = '+$0.00';

        document.getElementById('mc-median-profit').className = 'widget-value';

        document.getElementById('mc-percentile-5').innerText = '$0.00';

        document.getElementById('mc-percentile-5').className = 'half-val';

        document.getElementById('mc-percentile-95').innerText = '$0.00';

        document.getElementById('mc-percentile-95').className = 'half-val';

    }

    

    // Fill Staking Recommendations

    const rec = aiAnalysis.staking_recommendation;

    const justificationBox = document.getElementById('rec-justification-box');

    if (rec) {

        document.getElementById('rec-stake-size').innerText = `${rec.recommended_stake_pct.toFixed(1)}%`;

        document.getElementById('rec-consec-losses').innerText = rec.max_consecutive_losses;

        document.getElementById('rec-min-bankroll').innerText = `$${rec.min_recommended_bankroll.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

        document.getElementById('rec-justification').innerText = rec.justification;

        justificationBox.style.display = 'block';

    } else {

        document.getElementById('rec-stake-size').innerText = '0.0%';

        document.getElementById('rec-consec-losses').innerText = '0';

        document.getElementById('rec-min-bankroll').innerText = '$0.00';

        document.getElementById('rec-justification').innerText = 'Aguardando a execução do backtest para gerar a análise de banca.';

        justificationBox.style.display = 'none';

    }

    

    // Render validation checklist

    renderChecklist(aiAnalysis, results);

    

    // Render optimization suggestions

    displayOptimizationSuggestions(aiAnalysis.suggestions);

}



function renderChecklist(aiAnalysis, results) {

    const container = document.getElementById('ai-checklist-container');

    if (!container) return;

    

    container.innerHTML = ''; // Clear placeholder

    

    const summary = results.summary;

    const mc = aiAnalysis.monte_carlo;

    

    const checklistItems = [

        {

            title: "Volume de Apostas (Amostra)",

            value: `${summary.total_bets} apostas`,

            desc: summary.total_bets >= 500 ? "Aprovado: Amostra estatisticamente robusta." : 

                  (summary.total_bets >= 200 ? "Alerta: Amostra moderada, sujeita a alguma variância." : "Risco: Amostra muito pequena para garantir consistência."),

            status: summary.total_bets >= 500 ? "success" : (summary.total_bets >= 200 ? "warning" : "danger"),

            icon: summary.total_bets >= 500 ? "fa-circle-check" : (summary.total_bets >= 200 ? "fa-triangle-exclamation" : "fa-circle-xmark")

        },

        {

            title: "Retorno sobre Investimento (ROI)",

            value: `${summary.roi.toFixed(2)}%`,

            desc: summary.roi >= 3.0 ? "Aprovado: Retorno profissional e sustentável." :

                  (summary.roi >= 0.0 ? "Alerta: Margem muito baixa, vulnerável a custos." : "Perigo: Estratégia deficitária no período analisado."),

            status: summary.roi >= 3.0 ? "success" : (summary.roi >= 0.0 ? "warning" : "danger"),

            icon: summary.roi >= 3.0 ? "fa-circle-check" : (summary.roi >= 0.0 ? "fa-triangle-exclamation" : "fa-circle-xmark")

        },

        {

            title: "Previsão de Sucesso ML (Classificador)",

            value: `${aiAnalysis.ml_probability.toFixed(1)}%`,

            desc: aiAnalysis.ml_probability >= 70.0 ? "Aprovado: Alta chance de continuidade nos próximos ciclos." :

                  (aiAnalysis.ml_probability >= 50.0 ? "Alerta: Estabilidade moderada com alguma oscilação prevista." : "Perigo: Alta probabilidade de inversão ou decaimento."),

            status: aiAnalysis.ml_probability >= 70.0 ? "success" : (aiAnalysis.ml_probability >= 50.0 ? "warning" : "danger"),

            icon: aiAnalysis.ml_probability >= 70.0 ? "fa-circle-check" : (aiAnalysis.ml_probability >= 50.0 ? "fa-triangle-exclamation" : "fa-circle-xmark")

        },

        {

            title: "Confiança Bayesiana do Edge",

            value: `${aiAnalysis.bayesian_confidence.toFixed(1)}% de certeza`,

            desc: aiAnalysis.bayesian_confidence >= 80.0 ? "Aprovado: Edge matemático real comprovado cientificamente." :

                  (aiAnalysis.bayesian_confidence >= 60.0 ? "Alerta: Indícios fracos de edge, pode ser ruído estatístico." : "Perigo: Desempenho muito próximo da sorte/azar no longo prazo."),

            status: aiAnalysis.bayesian_confidence >= 80.0 ? "success" : (aiAnalysis.bayesian_confidence >= 60.0 ? "warning" : "danger"),

            icon: aiAnalysis.bayesian_confidence >= 80.0 ? "fa-circle-check" : (aiAnalysis.bayesian_confidence >= 60.0 ? "fa-triangle-exclamation" : "fa-circle-xmark")

        },

        {

            title: "Estabilidade Temporal (Drift de ROI)",

            value: `${aiAnalysis.drift_ratio >= 0 ? '+' : ''}${aiAnalysis.drift_ratio.toFixed(1)}% de desvio`,

            desc: aiAnalysis.drift_ratio >= -3.0 ? "Aprovado: Estratégia muito estável entre a 1ª e 2ª metades." :

                  (aiAnalysis.drift_ratio >= -8.0 ? "Alerta: Leve decaimento de performance detectado." : "Perigo: Forte perda de rendimento recente (decaimento estatístico)."),

            status: aiAnalysis.drift_ratio >= -3.0 ? "success" : (aiAnalysis.drift_ratio >= -8.0 ? "warning" : "danger"),

            icon: aiAnalysis.drift_ratio >= -3.0 ? "fa-circle-check" : (aiAnalysis.drift_ratio >= -8.0 ? "fa-triangle-exclamation" : "fa-circle-xmark")

        }

    ];

    

    if (mc) {

        checklistItems.push({

            title: "Resiliência Monte Carlo (Prob. Lucro)",

            value: `${mc.profit_probability.toFixed(1)}% das simulações`,

            desc: mc.profit_probability >= 90.0 ? "Aprovado: Estratégia altamente resiliente a variações de ordem." :

                  (mc.profit_probability >= 70.0 ? "Alerta: Sensibilidade moderada à sequência dos jogos." : "Perigo: Retornos altamente vulneráveis à ordem dos resultados."),

            status: mc.profit_probability >= 90.0 ? "success" : (mc.profit_probability >= 70.0 ? "warning" : "danger"),

            icon: mc.profit_probability >= 90.0 ? "fa-circle-check" : (mc.profit_probability >= 70.0 ? "fa-triangle-exclamation" : "fa-circle-xmark")

        });

        

        checklistItems.push({

            title: "Risco de Quebra (Risco de Ruína)",

            value: `${mc.ruin_probability.toFixed(1)}% de risco`,

            desc: mc.ruin_probability <= 1.0 ? "Aprovado: Risco de ruína insignificante sob gestão ativa." :

                  (mc.ruin_probability <= 5.0 ? "Alerta: Risco de quebra de banca controlado sob gestão ativa." : "Perigo: Alto risco de quebrar a banca nesta configuração!"),

            status: mc.ruin_probability <= 1.0 ? "success" : (mc.ruin_probability <= 5.0 ? "warning" : "danger"),

            icon: mc.ruin_probability <= 1.0 ? "fa-circle-check" : (mc.ruin_probability <= 5.0 ? "fa-triangle-exclamation" : "fa-circle-xmark")

        });

    }

    

    checklistItems.forEach(item => {

        const div = document.createElement('div');

        div.className = 'checklist-item';

        div.innerHTML = `

            <div class="checklist-status ${item.status}">

                <i class="fa-solid ${item.icon}"></i>

            </div>

            <div class="checklist-info">

                <span class="checklist-title">${item.title}</span>

                <span class="checklist-value">Métrica: <strong>${item.value}</strong></span>

                <span class="checklist-desc">${item.desc}</span>

            </div>

        `;

        container.appendChild(div);

    });

}



function displayOptimizationSuggestions(suggestions) {

    const suggestionsContainer = document.getElementById('ai-optimization-suggestions');

    const optPanel = document.getElementById('ai-optimization-panel');

    

    if (!optPanel || !suggestionsContainer) return;

    

    optPanel.style.display = 'block';

    suggestionsContainer.innerHTML = '';

    

    // Filter out already applied suggestions

    const filteredSuggestions = (suggestions || []).filter(sug => {

        if (sug.type === 'odds_warning' && appliedOptimizationSuggestions.has(sug.value)) return false;

        if (sug.type === 'ev' && appliedOptimizationSuggestions.has(`ev_${sug.value}`)) return false;

        if (sug.type === 'leagues' && appliedOptimizationSuggestions.has(`leagues_${JSON.stringify(sug.exclude_codes)}`)) return false;

        return true;

    });

    

    if (!filteredSuggestions || filteredSuggestions.length === 0) {

        suggestionsContainer.innerHTML = `

            <div style="padding: 20px; text-align: center; color: var(--text-secondary); font-size: 13px; background: rgba(255, 255, 255, 0.01); border: 1px dashed rgba(255, 255, 255, 0.05); border-radius: 8px;">

                <i class="fa-solid fa-circle-check" style="color: var(--success); font-size: 20px; margin-bottom: 10px; display: block;"></i>

                O sistema realizou a varredura em múltiplos ranges de odds e limites de EV+ em segundo plano, mas o seu modelo de estratégia atual já se encontra no ponto ótimo. Nenhuma variação testada obteve ganho de ROI superior a 1.5%.

            </div>

        `;

        return;

    }

    

    filteredSuggestions.forEach((sug) => {

        const div = document.createElement('div');

        let typeClass = sug.type; // 'ev', 'leagues', 'odds_warning'

        let badgeText = '';

        let buttonHtml = '';

        

        if (sug.type === 'ev') {

            badgeText = 'Gatilho EV';

            buttonHtml = `<button class="btn-suggestion-apply" onclick="applyEvSuggestion(${sug.value})"><i class="fa-solid fa-wand-magic"></i> Otimizar EV</button>`;

        } else if (sug.type === 'leagues') {

            badgeText = 'Ligas';

            const codesStr = JSON.stringify(sug.exclude_codes);

            buttonHtml = `<button class="btn-suggestion-apply" onclick='applyLeagueSuggestion(${codesStr})'><i class="fa-solid fa-filter-circle-xmark"></i> Excluir Ligas</button>`;

        } else if (sug.type === 'odds_warning') {

            badgeText = 'Aviso de Odds';

            const escapedValue = sug.value.replace(/'/g, "\\'");

            buttonHtml = `

                <div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-end;">

                    <span class="suggestion-warning-text"><i class="fa-solid fa-triangle-exclamation"></i> Evitar no mercado real</span>

                    <button class="btn-suggestion-apply" onclick="applyOddsSuggestion('${escapedValue}')">

                        <i class="fa-solid fa-wand-magic-sparkles"></i> Otimizar Odds

                    </button>

                </div>

            `;

        }

        

        // Compile side-by-side comparison table if summary data is present

        let comparisonTableHtml = '';

        if (sug.original_summary && sug.optimized_summary) {

            const orig = sug.original_summary;

            const opt = sug.optimized_summary;

            

            const profitDiff = opt.net_profit - orig.net_profit;

            const roiDiff = opt.roi - orig.roi;

            const wrDiff = opt.win_rate - orig.win_rate;

            const ddDiff = opt.max_drawdown - orig.max_drawdown;

            const betsDiff = opt.total_bets - orig.total_bets;

            

            const profitDiffClass = profitDiff >= 0 ? 'positive' : 'negative';

            const roiDiffClass = roiDiff >= 0 ? 'positive' : 'negative';

            const wrDiffClass = wrDiff >= 0 ? 'positive' : 'negative';

            const ddDiffClass = ddDiff <= 0 ? 'positive' : 'negative'; // lower drawdown is good

            

            const profitDiffText = (profitDiff >= 0 ? '+' : '') + `$${profitDiff.toFixed(2)}`;

            const roiDiffText = (roiDiff >= 0 ? '+' : '') + `${roiDiff.toFixed(2)}%`;

            const wrDiffText = (wrDiff >= 0 ? '+' : '') + `${wrDiff.toFixed(1)}%`;

            const ddDiffText = (ddDiff >= 0 ? '+' : '') + `${ddDiff.toFixed(1)}%`;

            const betsDiffText = (betsDiff >= 0 ? '+' : '') + betsDiff;

            

            comparisonTableHtml = `

                <table class="suggestion-comparison-table">

                    <thead>

                        <tr>

                            <th>Métrica</th>

                            <th>Original</th>

                            <th>Otimizado</th>

                            <th>Diferença</th>

                        </tr>

                    </thead>

                    <tbody>

                        <tr>

                            <td class="metric-name">Lucro Líquido</td>

                            <td class="metric-orig">$${orig.net_profit.toFixed(2)}</td>

                            <td class="metric-opt">$${opt.net_profit.toFixed(2)}</td>

                            <td class="metric-diff ${profitDiffClass}">${profitDiffText}</td>

                        </tr>

                        <tr>

                            <td class="metric-name">ROI (Yield)</td>

                            <td class="metric-orig">${orig.roi.toFixed(2)}%</td>

                            <td class="metric-opt">${opt.roi.toFixed(2)}%</td>

                            <td class="metric-diff ${roiDiffClass}">${roiDiffText}</td>

                        </tr>

                        <tr>

                            <td class="metric-name">Taxa de Acerto</td>

                            <td class="metric-orig">${orig.win_rate.toFixed(1)}%</td>

                            <td class="metric-opt">${opt.win_rate.toFixed(1)}%</td>

                            <td class="metric-diff ${wrDiffClass}">${wrDiffText}</td>

                        </tr>

                        <tr>

                            <td class="metric-name">Max Drawdown</td>

                            <td class="metric-orig">${orig.max_drawdown.toFixed(1)}%</td>

                            <td class="metric-opt">${opt.max_drawdown.toFixed(1)}%</td>

                            <td class="metric-diff ${ddDiffClass}">${ddDiffText}</td>

                        </tr>

                        <tr>

                            <td class="metric-name">Total Apostas</td>

                            <td class="metric-orig">${orig.total_bets}</td>

                            <td class="metric-opt">${opt.total_bets}</td>

                            <td class="metric-diff">${betsDiffText}</td>

                        </tr>

                    </tbody>

                </table>

            `;

        }

        

        div.className = `suggestion-item ${typeClass}`;

        div.innerHTML = `

            <div style="display: flex; flex-direction: column; width: 100%;">

                <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">

                    <div class="suggestion-text-container">

                        <span class="suggestion-badge ${typeClass}">${badgeText}</span>

                        <span class="suggestion-text">${sug.text}</span>

                    </div>

                    ${buttonHtml}

                </div>

                ${comparisonTableHtml}

            </div>

        `;

        suggestionsContainer.appendChild(div);

    });

}



function applyEvSuggestion(val) {

    const evInput = document.getElementById('val-threshold');

    if (evInput) {

        evInput.value = val;

        showToast(`Gatilho EV atualizado para ${val}. Rodando nova simulação...`, "success");

        appliedOptimizationSuggestions.add(`ev_${val}`);

        runBacktest();

    }

}



function applyLeagueSuggestion(codes) {

    codes.forEach(code => {

        const cb = document.getElementById(`league-${code}`) || document.querySelector(`input[value="${code}"]`);

        if (cb) cb.checked = false;

    });

    

    showToast(`Ligas problemáticas removidas. Reexecutando backtest...`, "success");

    appliedOptimizationSuggestions.add(`leagues_${JSON.stringify(codes)}`);

    runBacktest();

}



window.toggleCollapsibleSection = function(id) {
    const el = document.getElementById(id);
    const chevron = document.getElementById(id.replace('-filters', '-chevron'));
    if (!el) return;
    if (el.style.display === 'none') {
        el.style.display = 'flex';
        if (chevron) {
            chevron.classList.remove('fa-chevron-down');
            chevron.classList.add('fa-chevron-up');
        }
    } else {
        el.style.display = 'none';
        if (chevron) {
            chevron.classList.remove('fa-chevron-up');
            chevron.classList.add('fa-chevron-down');
        }
    }
};

function applyOddsSuggestion(rangeName) {
    if (rangeName.includes(':')) {
        const parts = rangeName.split(':');
        const field = parts[0];
        const subRange = parts[1];
        
        let minFieldId = '';
        let maxFieldId = '';
        
        if (field === 'odds_h') {
            minFieldId = 'min-odds-h';
            maxFieldId = 'max-odds-h';
        } else if (field === 'odds_d') {
            minFieldId = 'min-odds-d';
            maxFieldId = 'max-odds-d';
        } else if (field === 'odds_a') {
            minFieldId = 'min-odds-a';
            maxFieldId = 'max-odds-a';
        } else if (field === 'odds_over25') {
            minFieldId = 'min-odds-over25';
            maxFieldId = 'max-odds-over25';
        } else if (field === 'odds_under25') {
            minFieldId = 'min-odds-under25';
            maxFieldId = 'max-odds-under25';
        }
        
        const minEl = document.getElementById(minFieldId);
        const maxEl = document.getElementById(maxFieldId);
        
        // Expand collapsible section
        const coll = document.getElementById('advanced-odds-filters');
        if (coll && coll.style.display === 'none') {
            toggleCollapsibleSection('advanced-odds-filters');
        }

        if (subRange.includes('Super Favoritos') || subRange.includes('<=1.50')) {
            if (minEl) minEl.value = "1.50";
        } else if (subRange.includes('Zebras') || subRange.includes('>3.00')) {
            if (maxEl) maxEl.value = "3.00";
        } else if (subRange.includes('Favoritos (1.50-2.00)')) {
            if (minEl) minEl.value = "2.00";
        } else if (subRange.includes('Médios (2.00-3.00)')) {
            if (maxEl) maxEl.value = "2.00";
        } else if (subRange.includes('Baixo (<=3.00)')) {
            if (minEl) minEl.value = "3.00";
        } else if (subRange.includes('Alto (>3.80)')) {
            if (maxEl) maxEl.value = "3.80";
        } else if (subRange.includes('Médio (3.00-3.80)')) {
            if (maxEl) maxEl.value = "3.00";
        } else if (subRange.includes('Favorito (<=1.70)')) {
            if (minEl) minEl.value = "1.70";
        } else if (subRange.includes('Equilibrado (1.70-2.20)')) {
            if (minEl) minEl.value = "2.20";
        } else if (subRange.includes('Zebra (>2.20)')) {
            if (maxEl) maxEl.value = "2.20";
        }
        
        showToast(`Filtro avançado de odds otimizado. Rodando simulação...`, "success");
        appliedOptimizationSuggestions.add(rangeName);
        runBacktest();
        return;
    }

    const minInput = document.getElementById('min-odds');
    const maxInput = document.getElementById('max-odds');
    
    if (rangeName.includes('Super Favoritos') || rangeName.includes('<=1.50')) {
        minInput.value = "1.50";
    } else if (rangeName.includes('Zebras') || rangeName.includes('>3.00')) {
        maxInput.value = "3.00";
    } else if (rangeName.includes('Favoritos (1.50-2.00)')) {
        minInput.value = "2.00";
    } else if (rangeName.includes('Médios (2.00-3.00)')) {
        maxInput.value = "2.00";
    }
    
    showToast(`Filtro de Odds otimizado para excluir ${rangeName}. Rodando simulação...`, "success");
    appliedOptimizationSuggestions.add(rangeName);
    runBacktest();
}



function clearDashboard() {

    // 1. Reset metrics

    document.getElementById('metric-net-profit').innerText = '$0.00';

    document.getElementById('metric-profit-stakes').innerText = '+0.00 st.';

    document.getElementById('metric-roi').innerText = '0.0%';

    document.getElementById('metric-win-rate').innerText = '0.0%';

    document.getElementById('metric-total-bets').innerText = '0';

    document.getElementById('metric-avg-odds').innerText = '1.00';

    document.getElementById('metric-drawdown').innerText = '0.0%';
    const ddDur = document.getElementById('metric-dd-duration');
    if (ddDur) ddDur.innerText = 'Recup: 0 apostas';

    document.getElementById('metric-final-bankroll').innerText = '$0.00';

    document.getElementById('metric-clv').innerText = '0.0%';
    document.getElementById('metric-bcl').innerText = '0.0%';

    // Restore standard panels in case Portfolio was run
    document.getElementById('portfolio-results-panel').style.display = 'none';
    document.getElementById('standard-metrics-grid').style.display = 'grid';
    const mainCharts = document.querySelector('.main-charts');
    if (mainCharts) mainCharts.style.display = 'block';
    const resultsTableSection = document.querySelector('.results-table-section');
    if (resultsTableSection) resultsTableSection.style.display = 'block';
    const chartsGrid = document.querySelector('.charts-grid');
    if (chartsGrid) chartsGrid.style.display = 'grid';

    

    const profitCard = document.getElementById('metric-net-profit').closest('.metric-card');

    const profitStakesCard = document.getElementById('metric-profit-stakes').closest('.metric-card');

    const roiCard = document.getElementById('metric-roi').closest('.metric-card');

    profitCard.className = 'metric-card card-profit';

    profitStakesCard.className = 'metric-card card-stakes';

    roiCard.className = 'metric-card card-roi';

    document.getElementById('metric-clv').closest('.metric-card').className = 'metric-card card-clv';

    document.getElementById('metric-bcl').closest('.metric-card').className = 'metric-card card-bcl';

    

    // Reset advanced metrics

    document.getElementById('metric-sharpe').innerText = '0.00';

    document.getElementById('metric-sortino').innerText = '0.00';

    document.getElementById('metric-skewness').innerText = '0.00';

    document.getElementById('metric-consec-wins').innerText = '0';

    document.getElementById('metric-consec-losses').innerText = '0';

    

    // Reset Portfolio Allocator

    const portfolioPanel = document.getElementById('portfolio-allocator-panel');

    if (portfolioPanel) {

        portfolioPanel.style.display = 'none';

    }

    const allocatorContainer = document.getElementById('allocator-bars-container');

    if (allocatorContainer) {

        allocatorContainer.innerHTML = '';

    }

    document.getElementById('allocator-expected-return').innerText = '+0.00%';

    document.getElementById('allocator-volatility').innerText = '0.00%';

    document.getElementById('allocator-sharpe').innerText = '0.00';

    

    // Clear pre-match calculator bookmakers table

    document.getElementById('calc-bookmakers-tbody').innerHTML = '';

    

    // Hide and reset Quartiles panel

    document.getElementById('quartiles-panel').style.display = 'none';

    document.getElementById('staking-comparison-panel').style.display = 'none';

    

    // Hide and reset EQS Risk panel

    const riskEmpty = document.getElementById('risk-empty-state');

    const riskContent = document.getElementById('risk-content');

    if (riskEmpty && riskContent) {

        riskEmpty.style.display = 'block';

        riskContent.style.display = 'none';

        switchTab('tab-laboratory');

    }



    for (let i = 1; i <= 4; i++) {

        document.getElementById(`q${i}-profit`).innerText = '$0.00';

        document.getElementById(`q${i}-stakes`).innerText = '0.00 st.';

        document.getElementById(`q${i}-roi`).innerText = '0.0%';

        document.getElementById(`q${i}-winrate`).innerText = '0.0%';

        document.getElementById(`q${i}-bets`).innerText = '0';

    }

    

    // 2. Clear charts

    if (equityChart) {

        equityChart.destroy();

        equityChart = null;

    }

    if (leagueChart) {

        leagueChart.destroy();

        leagueChart = null;

    }

    if (monthlyChart) {

        monthlyChart.destroy();

        monthlyChart = null;

    }

    if (oddsChart) {

        oddsChart.destroy();

        oddsChart = null;

    }

    

    // 3. Clear bets cache and table

    allBets = [];

    const tbody = document.getElementById('bets-table-body');

    tbody.innerHTML = `

        <tr>

            <td colspan="10" class="text-center empty-state">

                <i class="fa-solid fa-info-circle"></i> Configure os filtros ao lado e execute o backtest para ver os resultados.

            </td>

        </tr>

    `;

    

    // 4. Hide AI & Optimization panels and reset Monte Carlo UI

    document.getElementById('ai-analytics-panel').style.display = 'none';

    document.getElementById('ai-optimization-panel').style.display = 'none';



    // Hide statistical validation and OOS panels

    const statPanel = document.getElementById('stat-validation-panel');

    if (statPanel) { statPanel.style.display = 'none'; document.getElementById('stat-validation-grid').innerHTML = ''; }

    const oosPanel = document.getElementById('oos-results-panel');

    if (oosPanel) { oosPanel.style.display = 'none'; document.getElementById('oos-metrics-grid').innerHTML = ''; }

    

    const checklistContainer = document.getElementById('ai-checklist-container');

    if (checklistContainer) {

        checklistContainer.innerHTML = `

            <div class="ai-report-text" style="color: var(--text-muted);">

                Aguardando a execução do backtest para gerar o checklist.

            </div>

        `;

    }

    

    document.getElementById('mc-profit-probability').innerText = '0.0%';

    document.getElementById('mc-profit-progress').style.width = '0%';

    document.getElementById('mc-ruin-probability').innerText = '0.0%';
    const halfRuinEl = document.getElementById('mc-half-ruin-probability');
    if (halfRuinEl) halfRuinEl.innerText = '0.0%';

    document.getElementById('mc-ruin-progress').style.width = '0%';

    document.getElementById('mc-median-profit').innerText = '+$0.00';

    document.getElementById('mc-median-profit').className = 'widget-value';

    document.getElementById('mc-percentile-5').innerText = '$0.00';

    document.getElementById('mc-percentile-5').className = 'half-val';

    document.getElementById('mc-percentile-95').innerText = '$0.00';

    document.getElementById('mc-percentile-95').className = 'half-val';

    

    // Reset active strategy banner

    document.getElementById('active-strategy-banner').style.display = 'none';

    document.getElementById('active-leagues-text').innerText = 'N/A';

    document.getElementById('active-market-text').innerText = 'N/A';

    document.getElementById('active-odds-text').innerText = '1.00 - 50.00';

    document.getElementById('active-ev-text').innerText = '1.05';

    

    // Reset Staking Recommendations

    document.getElementById('rec-stake-size').innerText = '0.0%';

    document.getElementById('rec-consec-losses').innerText = '0';

    document.getElementById('rec-min-bankroll').innerText = '$0.00';

    document.getElementById('rec-justification').innerText = 'Aguardando a execução do backtest para gerar a análise de banca.';

    document.getElementById('rec-justification-box').style.display = 'none';

    

    // 5. Clear scanner results

    lastScanResults = null;

    lastScanParams = null;

    lastBacktestSummary = null;

    lastBacktestParams = null;

    const btnExport = document.getElementById('btn-export-backtest');

    if (btnExport) btnExport.style.display = 'none';

    const resultsDiv = document.getElementById('scanner-results');

    resultsDiv.innerHTML = '';

    resultsDiv.style.display = 'none';

    

    // Clear Calculator results

    document.getElementById('calc-results').style.display = 'none';

    document.getElementById('calc-heatmap-container').style.display = 'none';

    document.getElementById('calc-league').value = "";

    document.getElementById('calc-home-team').innerHTML = '<option value="" disabled selected>Selecione...</option>';

    document.getElementById('calc-away-team').innerHTML = '<option value="" disabled selected>Selecione...</option>';

    document.getElementById('calc-home-team').disabled = true;

    document.getElementById('calc-away-team').disabled = true;

    

    showToast("Dashboard limpo! Pronto para uma nova simulação.", "info");

}



// ==========================================================================

// Pre-Match Calculator and Match Details Modal Logic [NEW]

// ==========================================================================



async function populateCalculatorLeagues() {

    const select = document.getElementById('calc-league');

    select.innerHTML = '<option value="" disabled selected>Selecione uma liga...</option>';

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/leagues?source=${window.currentDataSource}&t=${Date.now()}`, { cache: 'no-store' });

        if (!res.ok) throw new Error("Failed to load leagues");

        const leagues = await res.json();

        

        leagues.sort((a, b) => a.name.localeCompare(b.name));

        leagues.forEach(league => {

            const opt = document.createElement('option');

            opt.value = league.code;

            opt.innerText = league.name;

            select.appendChild(opt);

        });

    } catch (err) {

        console.error("Error populating calculator leagues:", err);

    }

}



async function onCalculatorLeagueChange() {

    const leagueCode = document.getElementById('calc-league').value;

    const homeSelect = document.getElementById('calc-home-team');

    const awaySelect = document.getElementById('calc-away-team');

    

    homeSelect.disabled = true;

    awaySelect.disabled = true;

    homeSelect.innerHTML = '<option value="" disabled selected>Carregando...</option>';

    awaySelect.innerHTML = '<option value="" disabled selected>Carregando...</option>';

    

    try {
        const source = document.getElementById('data-source-select').value;
        const apiKey = document.getElementById('futpython-api-key').value;
        const res = await fetch(`${API_BASE_URL}/api/teams?league=${leagueCode}&source=${source}&api_key=${apiKey}`);

        if (!res.ok) throw new Error("Failed to load teams");

        const teams = await res.json();

        

        homeSelect.innerHTML = '<option value="" disabled selected>Selecione...</option>';

        awaySelect.innerHTML = '<option value="" disabled selected>Selecione...</option>';

        

        teams.forEach(team => {

            const optHome = document.createElement('option');

            optHome.value = team;

            optHome.innerText = team;

            

            const optAway = document.createElement('option');

            optAway.value = team;

            optAway.innerText = team;

            

            homeSelect.appendChild(optHome);

            awaySelect.appendChild(optAway);

        });

        

        homeSelect.disabled = false;

        awaySelect.disabled = false;

    } catch (err) {

        console.error("Error loading teams for calculator:", err);

        showToast("Erro ao carregar os times desta liga.", "error");

        homeSelect.innerHTML = '<option value="" disabled selected>Erro</option>';

        awaySelect.innerHTML = '<option value="" disabled selected>Erro</option>';

    }

}



async function runRealtimePrediction() {

    const league = document.getElementById('calc-league').value;

    const homeTeam = document.getElementById('calc-home-team').value;

    const awayTeam = document.getElementById('calc-away-team').value;

    

    if (!league || !homeTeam || !awayTeam) {

        showToast("Selecione o campeonato e ambos os times.", "error");

        return;

    }

    

    if (homeTeam === awayTeam) {

        showToast("O time mandante e visitante não podem ser os mesmos.", "error");

        return;

    }

    

    const btn = document.getElementById('btn-calc-predict');

    const origHtml = btn.innerHTML;

    btn.disabled = true;

    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Calculando...';

    

    try {

        const data_source = document.getElementById('data-source-select').value;
        const futpython_api_key = document.getElementById('futpython-api-key').value;
        const res = await fetch(`${API_BASE_URL}/api/predict`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ league, homeTeam, awayTeam, data_source, futpython_api_key })

        });

        

        if (!res.ok) {

            const err = await res.json();

            throw new Error(err.detail || "Erro ao calcular previsões");

        }

        

        const data = await res.json();

        

        document.getElementById('calc-results').style.display = 'block';

        document.getElementById('calc-heatmap-container').style.display = 'block';

        

        // Expected Goals (lambda)

        document.getElementById('calc-res-home-lambda').innerText = data.expectancy.home_lambda.toFixed(2);

        document.getElementById('calc-res-home-att').innerText = `Ataque: ${data.expectancy.home_att.toFixed(2)} | Defesa: ${data.expectancy.home_def.toFixed(2)}`;

        

        document.getElementById('calc-res-away-lambda').innerText = data.expectancy.away_lambda.toFixed(2);

        document.getElementById('calc-res-away-att').innerText = `Ataque: ${data.expectancy.away_att.toFixed(2)} | Defesa: ${data.expectancy.away_def.toFixed(2)}`;

        

        // Probabilities & Fair Odds Table

        document.getElementById('calc-prob-home').innerHTML = renderProbValue(data.probabilities.home, 'home');

        document.getElementById('calc-odd-home').innerText = data.fair_odds.home.toFixed(2);

        

        document.getElementById('calc-prob-draw').innerHTML = renderProbValue(data.probabilities.draw, 'draw');

        document.getElementById('calc-odd-draw').innerText = data.fair_odds.draw.toFixed(2);

        

        document.getElementById('calc-prob-away').innerHTML = renderProbValue(data.probabilities.away, 'away');

        document.getElementById('calc-odd-away').innerText = data.fair_odds.away.toFixed(2);

        

        document.getElementById('calc-prob-over15').innerHTML = renderProbValue(data.probabilities.over15, 'over');

        document.getElementById('calc-odd-over15').innerText = data.fair_odds.over15.toFixed(2);

        

        document.getElementById('calc-prob-over25').innerHTML = renderProbValue(data.probabilities.over25, 'over');

        document.getElementById('calc-odd-over25').innerText = data.fair_odds.over25.toFixed(2);

        

        document.getElementById('calc-prob-btts-yes').innerHTML = renderProbValue(data.probabilities.btts_yes, 'yes');

        document.getElementById('calc-odd-btts-yes').innerText = data.fair_odds.btts_yes.toFixed(2);

        

        // Heatmap Score Grid

        renderHeatmapGrid('calc-heatmap-grid', data.score_grid);

        

        // Populate pre-match calculator bookmakers table

        const calcBookmakersTbody = document.getElementById('calc-bookmakers-tbody');

        calcBookmakersTbody.innerHTML = '';

        

        const bookmakers = [

            { key: 'Bet365', name: 'Bet365' },

            { key: 'Pinnacle', name: 'Pinnacle' },

            { key: 'Bwin', name: 'Bwin' },

            { key: 'Media', name: 'Média' },

            { key: 'Maxima', name: 'Máxima' }

        ];

        

        let hasCalcOdds = false;

        if (data.odds_comparison) {

            bookmakers.forEach(b => {

                const oddsObj = data.odds_comparison[b.key] || data.odds_comparison[b.key.toLowerCase()];

                if (oddsObj && (oddsObj.H || oddsObj.D || oddsObj.A)) {

                    hasCalcOdds = true;

                    const tr = document.createElement('tr');

                    tr.innerHTML = `

                        <td style="font-weight: 600;">${b.name}</td>

                        <td class="text-center">${oddsObj.H ? oddsObj.H.toFixed(2) : '-'}</td>

                        <td class="text-center">${oddsObj.D ? oddsObj.D.toFixed(2) : '-'}</td>

                        <td class="text-center">${oddsObj.A ? oddsObj.A.toFixed(2) : '-'}</td>

                    `;

                    calcBookmakersTbody.appendChild(tr);

                }

            });

        }

        

        if (!hasCalcOdds) {

            calcBookmakersTbody.innerHTML = `

                <tr>

                    <td colspan="4" class="text-center text-muted">Sem dados comparativos de odds para esta partida.</td>

                </tr>

            `;

        }

        

        showToast("Previsão concluída!", "success");

    } catch (err) {

        console.error(err);

        showToast(err.message, "error");

    } finally {

        btn.disabled = false;

        btn.innerHTML = origHtml;

    }

}



function renderHeatmapGrid(containerId, scoreGrid) {

    const grid = document.getElementById(containerId);

    grid.innerHTML = '';

    

    let maxProb = 0.1;

    scoreGrid.forEach(row => {

        row.forEach(cell => {

            if (cell.prob > maxProb) maxProb = cell.prob;

        });

    });

    

    for (let h = 0; h <= 5; h++) {

        for (let a = 0; a <= 5; a++) {

            const cellData = scoreGrid[h][a];

            const cell = document.createElement('div');

            cell.className = 'heatmap-cell';

            

            const intensity = cellData.prob / maxProb;

            cell.style.background = `rgba(99, 102, 241, ${0.05 + intensity * 0.85})`;

            

            if (intensity > 0.6) {

                cell.style.color = '#ffffff';

            }

            

            cell.innerHTML = `

                <span>${cellData.prob.toFixed(1)}%</span>

                <span class="heatmap-cell-score">${cellData.score}</span>

            `;

            

            cell.title = `Placar ${cellData.score}: ${cellData.prob.toFixed(1)}%`;

            grid.appendChild(cell);

        }

    }

}



async function showMatchDetails(bet) {

    const modal = document.getElementById('match-details-modal');

    modal.style.display = 'flex';

    

    document.getElementById('modal-league-badge').innerText = bet.league;

    document.getElementById('modal-match-teams').innerText = `${bet.home_team} vs ${bet.away_team}`;

    document.getElementById('modal-match-date').innerText = `Data da Partida: ${bet.date} | Placar Final: ${bet.score}`;

    

    document.getElementById('modal-home-team-name').innerText = bet.home_team;

    document.getElementById('modal-away-team-name').innerText = bet.away_team;

    document.getElementById('modal-home-att').innerText = '...';

    document.getElementById('modal-home-def').innerText = '...';

    document.getElementById('modal-home-lambda').innerText = '...';

    document.getElementById('modal-away-att').innerText = '...';

    document.getElementById('modal-away-def').innerText = '...';

    document.getElementById('modal-away-lambda').innerText = '...';

    document.getElementById('modal-league-avg-home').innerText = '...';

    document.getElementById('modal-league-avg-away').innerText = '...';

    

    const tbody = document.getElementById('modal-odds-tbody');

    tbody.innerHTML = '<tr><td colspan="5" class="text-center">Carregando dados estatísticos...</td></tr>';

    document.getElementById('modal-bookmakers-tbody').innerHTML = '<tr><td colspan="4" class="text-center">Carregando comparativo...</td></tr>';

    document.getElementById('modal-heatmap-grid').innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); font-size: 11px; padding: 20px;">Calculando matriz...</div>';

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/predict`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ league: bet.league, homeTeam: bet.home_team, awayTeam: bet.away_team })

        });

        

        if (!res.ok) throw new Error("Failed to calculate parameters");

        const data = await res.json();

        

        document.getElementById('modal-home-att').innerText = data.expectancy.home_att.toFixed(2);

        document.getElementById('modal-home-def').innerText = data.expectancy.home_def.toFixed(2);

        document.getElementById('modal-home-lambda').innerText = data.expectancy.home_lambda.toFixed(2);

        

        document.getElementById('modal-away-att').innerText = data.expectancy.away_att.toFixed(2);

        document.getElementById('modal-away-def').innerText = data.expectancy.away_def.toFixed(2);

        document.getElementById('modal-away-lambda').innerText = data.expectancy.away_lambda.toFixed(2);

        

        document.getElementById('modal-league-avg-home').innerText = data.expectancy.league_avg_home.toFixed(2);

        document.getElementById('modal-league-avg-away').innerText = data.expectancy.league_avg_away.toFixed(2);

        

        tbody.innerHTML = '';

        

        const markets = [

            { key: 'home', name: 'Mandante (1)', label: '1 (Mandante)' },

            { key: 'draw', name: 'Empate (X)', label: 'X (Empate)' },

            { key: 'away', name: 'Visitante (2)', label: '2 (Visitante)' },

            { key: 'over15', name: 'Over 1.5 Gols', label: 'Over 1.5' },

            { key: 'over25', name: 'Over 2.5 Gols', label: 'Over 2.5' },

            { key: 'under25', name: 'Under 2.5 Gols', label: 'Under 2.5' },

            { key: 'over35', name: 'Over 3.5 Gols', label: 'Over 3.5' },

            { key: 'under35', name: 'Under 3.5 Gols', label: 'Under 3.5' },

            { key: 'over45', name: 'Over 4.5 Gols', label: 'Over 4.5' },

            { key: 'under45', name: 'Under 4.5 Gols', label: 'Under 4.5' },

            { key: 'over55', name: 'Over 5.5 Gols', label: 'Over 5.5' },

            { key: 'under55', name: 'Under 5.5 Gols', label: 'Under 5.5' },

            { key: 'ht_home', name: 'HT Mandante', label: 'HT Mandante' },
            { key: 'ht_draw', name: 'HT Empate', label: 'HT Empate' },
            { key: 'ht_away', name: 'HT Visitante', label: 'HT Visitante' },
            { key: 'ht_over05', name: 'HT Over 0.5', label: 'HT Over 0.5' },
            { key: 'ht_under05', name: 'HT Under 0.5', label: 'HT Under 0.5' },
            { key: 'ht_over15', name: 'HT Over 1.5', label: 'HT Over 1.5' },
            { key: 'ht_under15', name: 'HT Under 1.5', label: 'HT Under 1.5' },

            { key: 'lay_home', name: 'Contra Mandante (X2)', label: 'Contra Mandante (X2)' },

            { key: 'lay_away', name: 'Contra Visitante (1X)', label: 'Contra Visitante (1X)' },

            { key: 'lay_draw', name: 'Contra Empate (12)', label: 'Contra Empate (12)' },

            { key: 'btts_yes', name: 'Ambas Marcam (Sim)', label: 'BTTS Sim' },

            { key: 'btts_no', name: 'Ambas Marcam (Não)', label: 'BTTS Não' },

            { key: 'dnb_h', name: 'DNB Mandante', label: 'DNB Mandante' },

            { key: 'dnb_a', name: 'DNB Visitante', label: 'DNB Visitante' },

            { key: 'cs_10', name: 'Placar Exato 1-0', label: 'Placar Exato 1-0' },

            { key: 'cs_20', name: 'Placar Exato 2-0', label: 'Placar Exato 2-0' },

            { key: 'cs_21', name: 'Placar Exato 2-1', label: 'Placar Exato 2-1' },

            { key: 'cs_00', name: 'Placar Exato 0-0', label: 'Placar Exato 0-0' },

            { key: 'cs_11', name: 'Placar Exato 1-1', label: 'Placar Exato 1-1' },

            { key: 'cs_01', name: 'Placar Exato 0-1', label: 'Placar Exato 0-1' },

            { key: 'cs_02', name: 'Placar Exato 0-2', label: 'Placar Exato 0-2' },

            { key: 'cs_12', name: 'Placar Exato 1-2', label: 'Placar Exato 1-2' },

            { key: 'lay_cs_10', name: 'Lay Placar Exato 1-0', label: 'Lay Placar Exato 1-0' },

            { key: 'lay_cs_20', name: 'Lay Placar Exato 2-0', label: 'Lay Placar Exato 2-0' },

            { key: 'lay_cs_21', name: 'Lay Placar Exato 2-1', label: 'Lay Placar Exato 2-1' },

            { key: 'lay_cs_00', name: 'Lay Placar Exato 0-0', label: 'Lay Placar Exato 0-0' },

            { key: 'lay_cs_11', name: 'Lay Placar Exato 1-1', label: 'Lay Placar Exato 1-1' },

            { key: 'lay_cs_01', name: 'Lay Placar Exato 0-1', label: 'Lay Placar Exato 0-1' },

            { key: 'lay_cs_02', name: 'Lay Placar Exato 0-2', label: 'Lay Placar Exato 0-2' },

            { key: 'lay_cs_12', name: 'Lay Placar Exato 1-2', label: 'Lay Placar Exato 1-2' }

        ];

        

        markets.forEach(m => {

            const tr = document.createElement('tr');

            const prob = data.probabilities[m.key];

            const fairOdd = data.fair_odds[m.key];

            

            let bookieOddText = '-';

            let evText = '-';

            let trClass = '';

            

            const isMatch = (bet.market === m.label);

            

            if (isMatch) {

                bookieOddText = bet.odds.toFixed(2);

                evText = bet.ev.toFixed(2);

                trClass = 'ev';

            }

            

            tr.className = trClass;

            tr.innerHTML = `

                <td class="metric-name">${m.name}</td>

                <td>${prob !== undefined ? renderProbValue(prob, m.key) : '-'}</td>

                <td class="metric-opt">${fairOdd !== undefined ? fairOdd.toFixed(2) : '-'}</td>

                <td>${bookieOddText}</td>

                <td class="metric-diff positive">${evText}</td>

            `;

            tbody.appendChild(tr);

        });

        

        // Asian Handicap Home Lines

        if (data.fair_ah_home && Object.keys(data.fair_ah_home).length > 0) {

            Object.keys(data.fair_ah_home).sort((a,b) => parseFloat(a) - parseFloat(b)).forEach(line => {

                const tr = document.createElement('tr');

                const fairOdd = data.fair_ah_home[line];

                

                let bookieOddText = '-';

                let evText = '-';

                let trClass = '';

                

                const isMatch = (bet.market === `AH Casa (${line})` || bet.market === 'ah_home');

                if (isMatch && bet.odds) {

                    bookieOddText = bet.odds.toFixed(2);

                    evText = bet.ev.toFixed(2);

                    trClass = 'ev';

                }

                

                tr.className = trClass;

                tr.innerHTML = `

                    <td class="metric-name">AH Casa (${line})</td>

                    <td>-</td>

                    <td class="metric-opt">${fairOdd.toFixed(2)}</td>

                    <td>${bookieOddText}</td>

                    <td class="metric-diff positive">${evText}</td>

                `;

                tbody.appendChild(tr);

            });

        }

        

        // Asian Handicap Away Lines

        if (data.fair_ah_away && Object.keys(data.fair_ah_away).length > 0) {

            Object.keys(data.fair_ah_away).sort((a,b) => parseFloat(a) - parseFloat(b)).forEach(line => {

                const tr = document.createElement('tr');

                const fairOdd = data.fair_ah_away[line];

                

                let bookieOddText = '-';

                let evText = '-';

                let trClass = '';

                

                const isMatch = (bet.market === `AH Fora (${line})` || bet.market === 'ah_away');

                if (isMatch && bet.odds) {

                    bookieOddText = bet.odds.toFixed(2);

                    evText = bet.ev.toFixed(2);

                    trClass = 'ev';

                }

                

                tr.className = trClass;

                tr.innerHTML = `

                    <td class="metric-name">AH Fora (${line})</td>

                    <td>-</td>

                    <td class="metric-opt">${fairOdd.toFixed(2)}</td>

                    <td>${bookieOddText}</td>

                    <td class="metric-diff positive">${evText}</td>

                `;

                tbody.appendChild(tr);

            });

        }

        

        renderHeatmapGrid('modal-heatmap-grid', data.score_grid);

        

        // Populate odds comparison table in details modal

        const modalBookmakersTbody = document.getElementById('modal-bookmakers-tbody');

        modalBookmakersTbody.innerHTML = '';

        

        const bookmakersList = [

            { key: 'Bet365', name: 'Bet365' },

            { key: 'Pinnacle', name: 'Pinnacle' },

            { key: 'Bwin', name: 'Bwin' },

            { key: 'Media', name: 'Média' },

            { key: 'Maxima', name: 'Máxima' }

        ];

        

        let hasModalOdds = false;

        if (data.odds_comparison) {

            bookmakersList.forEach(b => {

                const oddsObj = data.odds_comparison[b.key] || data.odds_comparison[b.key.toLowerCase()];

                if (oddsObj && (oddsObj.H || oddsObj.D || oddsObj.A)) {

                    hasModalOdds = true;

                    const tr = document.createElement('tr');

                    tr.innerHTML = `

                        <td style="font-weight: 600;">${b.name}</td>

                        <td class="text-center">${oddsObj.H ? oddsObj.H.toFixed(2) : '-'}</td>

                        <td class="text-center">${oddsObj.D ? oddsObj.D.toFixed(2) : '-'}</td>

                        <td class="text-center">${oddsObj.A ? oddsObj.A.toFixed(2) : '-'}</td>

                    `;

                    modalBookmakersTbody.appendChild(tr);

                }

            });

        }

        

        if (!hasModalOdds) {

            modalBookmakersTbody.innerHTML = `

                <tr>

                    <td colspan="4" class="text-center text-muted">Sem dados comparativos de odds para esta partida.</td>

                </tr>

            `;

        }

        

    } catch (err) {

        console.error(err);

        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-loss">Falha ao calcular parâmetros para esta partida.</td></tr>';

    }

}



function closeMatchDetailsModal() {

    document.getElementById('match-details-modal').style.display = 'none';

}



// ==========================================================================

// Telegram Config and Upcoming Tips Logic [NEW]

// ==========================================================================



// Global variable to cache loaded upcoming matches for broadcasting

let currentUpcomingMatches = [];



async function loadTelegramConfigUi() {

    try {

        const res = await fetch(`${API_BASE_URL}/api/telegram/config`);

        if (!res.ok) throw new Error();

        const data = await res.json();

        

        document.getElementById('tg-token').value = data.token || '';

        document.getElementById('tg-chat-id').value = data.chat_id || '';

        document.getElementById('tg-enabled').checked = !!data.enabled;

    } catch (err) {

        console.error("Error loading Telegram config:", err);

    }

}



async function saveTelegramConfig() {

    const token = document.getElementById('tg-token').value;

    const chatId = document.getElementById('tg-chat-id').value;

    const enabled = document.getElementById('tg-enabled').checked;

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/telegram/config`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ token, chat_id: chatId, enabled })

        });

        

        if (!res.ok) throw new Error("Erro ao salvar configuração.");

        showToast("Configurações do Telegram salvas com sucesso!", "success");

    } catch (err) {

        showToast(err.message, "error");

    }

}



async function testTelegramConnection() {

    const btn = document.getElementById('btn-test-tg');

    btn.disabled = true;

    

    // Save current config first

    const token = document.getElementById('tg-token').value;

    const chatId = document.getElementById('tg-chat-id').value;

    const enabled = document.getElementById('tg-enabled').checked;

    

    try {

        await fetch(`${API_BASE_URL}/api/telegram/config`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ token, chat_id: chatId, enabled })

        });

        

        const res = await fetch(`${API_BASE_URL}/api/telegram/test`, { method: 'POST' });

        if (!res.ok) {

            const errData = await res.json();

            throw new Error(errData.detail || "Erro no teste.");

        }

        showToast("Mensagem de teste enviada com sucesso ao Telegram!", "success");

    } catch (err) {

        showToast(err.message, "error");

    } finally {

        btn.disabled = false;

    }

}



async function loadSchedulerConfigUi() {

    try {

        const res = await fetch(`${API_BASE_URL}/api/telegram/scheduler`);

        if (!res.ok) throw new Error();

        const data = await res.json();

        

        document.getElementById('tg-scheduler-enabled').checked = !!data.enabled;

        document.getElementById('tg-scheduler-interval').value = data.check_interval_hours || 6;

        if (data.upcoming_source && document.getElementById('tg-scheduler-source')) {

            document.getElementById('tg-scheduler-source').value = data.upcoming_source;

        }

    } catch (err) {

        console.error("Error loading Telegram scheduler config:", err);

    }

}



async function autoUpdateSchedulerFromBacktest(backtestData) {

    try {

        const resGet = await fetch(`${API_BASE_URL}/api/telegram/scheduler`);

        let currentConfig = {

            enabled: false,

            check_interval_hours: 6,

            upcoming_source: 'api'

        };

        if (resGet.ok) {

            currentConfig = await resGet.json();

        }

        

        const updatedConfig = {

            enabled: currentConfig.enabled,

            check_interval_hours: currentConfig.check_interval_hours,

            leagues: backtestData.leagues,

            market: backtestData.market,

            value_threshold: backtestData.valueThreshold,

            min_odds: backtestData.minOdds || 1.0,

            max_odds: backtestData.maxOdds || 50.0,

            staking_rule: backtestData.stakingRule,

            stake_value: backtestData.stakeValue,

            initial_bankroll: backtestData.initialBankroll,

            upcoming_source: currentConfig.upcoming_source || 'api'

        };

        

        const resPost = await fetch(`${API_BASE_URL}/api/telegram/scheduler`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(updatedConfig)

        });

        

        if (resPost.ok) {

            console.log("Configurações do robô de Telegram sincronizadas com o backtest.");

            await loadSchedulerConfigUi();

        } else {

            console.error("Erro ao sincronizar robô com backtest.");

        }

    } catch (err) {

        console.error("Erro no autoUpdateSchedulerFromBacktest:", err);

    }

}



async function saveSchedulerConfigUi() {

    const enabled = document.getElementById('tg-scheduler-enabled').checked;

    const interval = parseInt(document.getElementById('tg-scheduler-interval').value) || 6;

    

    // Collect active strategy parameters from the sidebar controls

    const selectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked'))

        .map(cb => cb.value);

        

    if (selectedLeagues.length === 0) {

        showToast("Selecione pelo menos um campeonato no formulário lateral para salvar a estratégia do robô.", "error");

        return;

    }

    

    const ruleInput = document.getElementById('stake-rule').value;

    let stakingRule = ruleInput;

    let stakeValue = parseFloat(document.getElementById('stake-value').value);

    

    if (ruleInput.startsWith('kelly')) {

        stakingRule = 'kelly';

        if (ruleInput === 'kelly') stakeValue = 1.0;

        else if (ruleInput === 'kelly_half') stakeValue = 0.5;

        else if (ruleInput === 'kelly_quarter') stakeValue = 0.25;

        else if (ruleInput === 'kelly_eighth') stakeValue = 0.125;
        else if (ruleInput === 'kelly_sixteenth') stakeValue = 0.0625;

    }

    

    const upcomingSource = document.getElementById('tg-scheduler-source') ? document.getElementById('tg-scheduler-source').value : 'api';

    

    const selectedMarkets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);

    

    const requestData = {

        enabled: enabled,

        check_interval_hours: interval,

        leagues: selectedLeagues,

        market: selectedMarkets.length > 0 ? selectedMarkets : ['home'],

        value_threshold: parseFloat(document.getElementById('val-threshold').value),

        min_odds: parseFloat(document.getElementById('min-odds').value) || 1.0,

        max_odds: parseFloat(document.getElementById('max-odds').value) || 50.0,

        staking_rule: stakingRule,

        stake_value: stakeValue,

        initial_bankroll: parseFloat(document.getElementById('init-bankroll').value),

        upcoming_source: upcomingSource

    };

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/telegram/scheduler`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(requestData)

        });

        

        if (!res.ok) throw new Error("Erro ao salvar configuração do robô.");

        showToast("Configurações do Robô Automático salvas!", "success");

    } catch (err) {

        showToast(err.message, "error");

    }

}



async function runSchedulerNow() {

    const btn = document.getElementById('btn-run-scheduler-now');

    const origHtml = btn.innerHTML;

    

    btn.disabled = true;

    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Executando...';

    showToast("Robô rodando varredura em tempo real nas próximas rodadas...", "info");

    

    // Save current scheduler config first

    await saveSchedulerConfigUi();

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/telegram/scheduler/run`, {

            method: 'POST'

        });

        

        if (!res.ok) {

            const errData = await res.json();

            throw new Error(errData.detail || "Erro ao rodar varredura do robô.");

        }

        

        const data = await res.json();

        if (data.status === 'skipped') {

            showToast(data.message, "info");

        } else {

            showToast(`Varredura do Robô: ${data.sent_tips} novas tips enviadas para o Telegram!`, "success");

            await loadTelegramTipsLog();

        }

    } catch (err) {

        showToast(err.message, "error");

    } finally {

        btn.disabled = false;

        btn.innerHTML = origHtml;

    }

}



async function loadUpcomingMatches() {

    const btn = document.getElementById('btn-load-upcoming');

    const container = document.getElementById('upcoming-matches-list');

    

    btn.disabled = true;

    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Atualizando...';

    container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-secondary); font-size: 13px; padding: 40px 0;"><i class="fa-solid fa-spinner fa-spin" style="font-size: 20px; margin-bottom: 10px; display: block;"></i> Baixando calendário e processando estatísticas...</div>';

    

    // Read sidebar parameters

    const ruleInput = document.getElementById('stake-rule').value;

    let stakingRule = ruleInput;

    let stakeValue = parseFloat(document.getElementById('stake-value').value);

    

    if (ruleInput.startsWith('kelly')) {

        stakingRule = 'kelly';

        if (ruleInput === 'kelly') stakeValue = 1.0;

        else if (ruleInput === 'kelly_half') stakeValue = 0.5;

        else if (ruleInput === 'kelly_quarter') stakeValue = 0.25;

        else if (ruleInput === 'kelly_eighth') stakeValue = 0.125;
        else if (ruleInput === 'kelly_sixteenth') stakeValue = 0.0625;

    }

    


    const opMode = document.getElementById('select-operation-mode') ? document.getElementById('select-operation-mode').value : 'manual';
    const upcomingSource = document.getElementById('select-upcoming-source') ? document.getElementById('select-upcoming-source').value : 'api';
    
    let fetchUrl = '';
    
    if (opMode === 'autopilot') {
        fetchUrl = `${API_BASE_URL}/api/autopilot?source=${upcomingSource}`;
    } else {
        const selectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        if (selectedLeagues.length === 0) {
            showToast("Selecione pelo menos uma liga na barra lateral.", "error");
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Atualizar Grade';
            container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-loss); padding: 40px 0;">Nenhuma liga selecionada.</div>`;
            return;
        }
        
        const selectedMarkets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);
        if (selectedMarkets.length === 0) {
            showToast("Selecione pelo menos um mercado na barra lateral.", "error");
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Atualizar Grade';
            container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-loss); padding: 40px 0;">Nenhum mercado selecionado.</div>`;
            return;
        }
        const marketsParam = selectedMarkets.join(',');
        
        const params = new URLSearchParams({
            markets: marketsParam,
            valueThreshold: parseFloat(document.getElementById('val-threshold').value),
            minOdds: parseFloat(document.getElementById('min-odds').value) || 1.0,
            maxOdds: parseFloat(document.getElementById('max-odds').value) || 50.0,
            stakingRule: stakingRule,
            stakeValue: stakeValue,
            initialBankroll: parseFloat(document.getElementById('init-bankroll').value),
            source: upcomingSource
        });
        
        fetchUrl = `${API_BASE_URL}/api/upcoming?${params}`;
    }
    
    try {
        const res = await fetch(fetchUrl);
        const data = await res.json();

        

        // Filter upcoming matches by selected leagues ONLY if in manual mode
        let filteredData = data;
        if (opMode !== 'autopilot') {
            const currentSelectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
            filteredData = data.filter(match => currentSelectedLeagues.includes(match.league_code));
        }

        

        currentUpcomingMatches = filteredData;

        renderUpcomingMatches(filteredData);

        

        // Trigger system notification if permission is granted and there are tips

        if ('Notification' in window && Notification.permission === 'granted') {

            const tips = filteredData.filter(m => m.is_tip);

            if (tips.length === 1) {

                new Notification("Nova Tip (+EV) Encontrada", {

                    body: `${tips[0].home_team} vs ${tips[0].away_team} - Mercado: ${tips[0].market_label} (Odd: ${tips[0].bookie_odds.toFixed(2)})`,

                    icon: "/icons/icon-192.png"

                });

            } else if (tips.length > 1) {

                new Notification(`${tips.length} Novas Tips (+EV) Encontradas`, {

                    body: `Confira os próximos jogos em destaque na grade de jogos futuros!`,

                    icon: "/icons/icon-192.png"

                });

            }

        }

        

        showToast(`Grade de jogos atualizada com sucesso! (${filteredData.length} partidas)`, "success");

    } catch (err) {

        container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-loss); padding: 40px 0;">${err.message}</div>`;

        showToast(err.message, "error");

    } finally {

        btn.disabled = false;

        btn.innerHTML = '<i class="fa-arrows-rotate fa-solid"></i> Atualizar Grade';

    }

}



function renderUpcomingMatches(matches) {

    const container = document.getElementById('upcoming-matches-list');

    container.innerHTML = '';

    

    if (matches.length === 0) {

        container.innerHTML = `

            <div class="empty-state text-center" style="grid-column: 1 / -1; padding: 40px 0; width: 100%;">

                <i class="fa-solid fa-calendar-xmark" style="font-size: 28px; margin-bottom: 10px; color: var(--text-muted);"></i>

                <p>Nenhum jogo futuro agendado encontrado para as ligas ativas no momento.</p>

                <p style="font-size: 11px; color: var(--text-muted); margin-top: 4px;">As ligas brasileiras e americanas rodando em verão são atualizadas regularmente.</p>

            </div>

        `;

        return;

    }

    

    matches.forEach(match => {

        const isTip = match.is_tip;

        const cardClass = isTip ? 'upcoming-match-card is-tip' : 'upcoming-match-card';

        const card = document.createElement('div');

        card.className = cardClass;

        

        let tipBadgeHtml = '';

        let actionBtnClass = 'upcoming-match-action-btn';

        if (isTip) {

            tipBadgeHtml = `<span class="upcoming-tip-badge">Tip (+EV)</span>`;

            actionBtnClass = 'upcoming-match-action-btn tip-btn';

        }

        

        // Parse date for clean display (from DD/MM/YYYY to Brazilian style)

        const dateParts = match.date.split('/');

        const cleanDate = dateParts.length === 3 ? `${dateParts[0]}/${dateParts[1]}` : match.date;

        

        // Stringify the match object safely for onClick

        const safeMatchStr = JSON.stringify(match).replace(/'/g, "\\'").replace(/"/g, '&quot;');

        

        card.innerHTML = `

            ${tipBadgeHtml}

            <div class="upcoming-match-header">

                <span class="badge badge-success" style="padding: 2px 6px; font-size: 10px;">${match.league_name}</span>

                <span class="upcoming-match-date"><i class="fa-regular fa-clock"></i> ${cleanDate} - ${match.time}</span>

            </div>

            

            <div class="upcoming-match-teams">

                ${match.home_team} vs ${match.away_team}

            </div>

            

            <div class="upcoming-strategy-info">

                <div class="upcoming-strategy-values">

                    <span class="upcoming-strategy-label">Mercado: <strong>${match.market_label}</strong></span>

                    <span class="upcoming-strategy-edge" style="color: ${isTip ? 'var(--success)' : 'var(--text-secondary)'};">

                        ${isTip ? `EV Edge: +${((match.ev - 1) * 100).toFixed(1)}%` : `EV: ${match.ev ? match.ev.toFixed(2) : '-'}`}

                    </span>

                </div>

                <div class="upcoming-strategy-values" style="font-size: 11px; color: var(--text-secondary);">

                    <span>Probabilidade IA: <strong>${match.prob}%</strong></span>

                    <span>Odd Mínima: <strong>${match.fair_odds.toFixed(2)}</strong></span>

                </div>

                <div class="upcoming-strategy-values" style="font-size: 11px; color: var(--text-secondary);">

                    <span>Odd Bet365: <strong style="color: var(--warning);">${match.bookie_odds ? match.bookie_odds.toFixed(2) : '-'}</strong></span>

                    <span>Gestão Stake: <strong>${match.stake_pct}%</strong></span>

                </div>

            </div>

            

            <button type="button" class="${actionBtnClass}" onclick="sendIndividualTip(JSON.parse(this.getAttribute('data-match')))" data-match="${safeMatchStr}">

                <i class="fa-solid fa-bullhorn"></i> ${isTip ? 'Enviar Tip p/ Telegram' : 'Enviar Análise p/ Telegram'}

            </button>

        `;

        

        container.appendChild(card);

    });

}



async function sendIndividualTip(match) {

    try {

        const res = await fetch(`${API_BASE_URL}/api/telegram/send_tips`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({

                league_name: match.league_name,

                date_str: match.date,

                time_str: match.time,

                home_team: match.home_team,

                away_team: match.away_team,

                market_label: match.market_label,

                prob: match.prob,

                fair_odds: match.fair_odds,

                bookie_odds: match.bookie_odds,

                ev: match.ev,

                stake_pct: match.stake_pct

            })

        });

        

        if (!res.ok) {

            const errData = await res.json();

            throw new Error(errData.detail || "Erro ao enviar.");

        }

        

        showToast(`Tip para ${match.home_team} vs ${match.away_team} enviada ao Telegram!`, "success");

        await loadTelegramTipsLog();

    } catch (err) {

        showToast(err.message, "error");

    }

}



async function broadcastAllTips() {

    const btn = document.getElementById('btn-broadcast-tips');

    const tips = currentUpcomingMatches.filter(m => m.is_tip);

    

    if (tips.length === 0) {

        showToast("Nenhuma dica (+EV) ativa na grade para transmitir no momento.", "info");

        return;

    }

    

    btn.disabled = true;

    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Transmitindo (${tips.length})...`;

    

    let sentCount = 0;

    let failCount = 0;

    

    for (const match of tips) {

        try {

            const res = await fetch(`${API_BASE_URL}/api/telegram/send_tips`, {

                method: 'POST',

                headers: { 'Content-Type': 'application/json' },

                body: JSON.stringify({

                    league_name: match.league_name,

                    date_str: match.date,

                    time_str: match.time,

                    home_team: match.home_team,

                    away_team: match.away_team,

                    market_label: match.market_label,

                    prob: match.prob,

                    fair_odds: match.fair_odds,

                    bookie_odds: match.bookie_odds,

                    ev: match.ev,

                    stake_pct: match.stake_pct

                })

            });

            if (res.ok) sentCount++;

            else failCount++;

            

            // Short delay to respect Telegram rate limiting

            await new Promise(resolve => setTimeout(resolve, 800));

        } catch (err) {

            failCount++;

        }

    }

    

    if (failCount === 0) {

        showToast(`Todas as ${sentCount} tips foram transmitidas ao Telegram!`, "success");

    } else {

        showToast(`Transmissão concluída: ${sentCount} enviadas, ${failCount} falhas. Verifique o Token e Canal.`, sentCount > 0 ? "info" : "error");

    }

    btn.disabled = false;

    btn.innerHTML = '<i class="fa-solid fa-bullhorn"></i> Transmitir Tips (+EV)';

    await loadTelegramTipsLog();

}



async function loadTelegramTipsLog() {

    const tbody = document.getElementById('telegram-tips-table-body');

    try {

        const res = await fetch(`${API_BASE_URL}/api/telegram/tips`);

        if (!res.ok) throw new Error("Erro ao carregar log de tips.");

        const tips = await res.json();

        

        allTelegramTips = tips; // Cache for Telegram tips log

        filterTipsTable(); // This will apply the active status filter and call renderTelegramTips

    } catch (err) {

        console.error("Error loading tips log:", err);

        tbody.innerHTML = `

            <tr>

                <td colspan="7" class="text-center text-loss">

                    <i class="fa-solid fa-triangle-exclamation"></i> Falha ao carregar o histórico de tips do servidor.

                </td>

            </tr>

        `;

    }

}



async function updateTipStatus(tipId, status) {

    try {

        const res = await fetch(`${API_BASE_URL}/api/telegram/tips/${tipId}`, {

            method: 'PUT',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ status })

        });

        if (!res.ok) throw new Error("Erro ao atualizar status da tip.");

        showToast("Status da tip atualizado!", "success");

        await loadTelegramTipsLog(); // Reload to apply color styling dynamically

    } catch (err) {

        showToast(err.message, "error");

    }

}



async function clearTipsLog() {

    if (!confirm("Tem certeza que deseja limpar todo o histórico de tips enviadas? Esta ação não pode ser desfeita.")) {

        return;

    }

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/telegram/tips`, {

            method: 'DELETE'

        });

        if (!res.ok) throw new Error("Erro ao limpar log.");

        showToast("Histórico de tips limpo!", "success");

        await loadTelegramTipsLog();

    } catch (err) {

        showToast(err.message, "error");

    }

}



function renderTelegramTips(tips) {

    const tbody = document.getElementById('telegram-tips-table-body');

    if (tips.length === 0) {

        const statusFilter = document.getElementById('tips-status-filter').value;

        const msg = statusFilter === 'Todos' 

            ? 'Nenhuma tip enviada ao Telegram registrada no log local.'

            : 'Nenhuma tip encontrada com o status selecionado.';

        tbody.innerHTML = `

            <tr>

                <td colspan="7" class="text-center empty-state">

                    <i class="fa-solid fa-info-circle"></i> ${msg}

                </td>

            </tr>

        `;

        return;

    }

    

    tbody.innerHTML = '';

    // Render tips in reverse chronological order (latest first)

    tips.slice().reverse().forEach(tip => {

        const tr = document.createElement('tr');

        

        // Determine select dropdown class based on status

        let statusClass = 'status-pendente';

        if (tip.status === 'Green') statusClass = 'status-green';

        else if (tip.status === 'Red') statusClass = 'status-red';

        

        tr.innerHTML = `

            <td>${tip.date} ${tip.time || ''}</td>

            <td><strong>${tip.league_name}</strong></td>

            <td>${tip.home_team} vs ${tip.away_team}</td>

            <td>${tip.market}</td>

            <td style="color: var(--warning); font-weight: 600;">${tip.odds.toFixed(2)}</td>

            <td>${tip.stake.toFixed(1)}%</td>

            <td>

                <select class="status-select ${statusClass}" onchange="updateTipStatus('${tip.id}', this.value)">

                    <option value="Pendente" ${tip.status === 'Pendente' ? 'selected' : ''}>Pendente</option>

                    <option value="Green" ${tip.status === 'Green' ? 'selected' : ''}>Green</option>

                    <option value="Red" ${tip.status === 'Red' ? 'selected' : ''}>Red</option>

                </select>

            </td>

        `;

        tbody.appendChild(tr);

    });

}



function filterTipsTable() {

    const statusFilter = document.getElementById('tips-status-filter').value;

    let filtered = allTelegramTips;

    if (statusFilter !== 'Todos') {

        filtered = allTelegramTips.filter(tip => tip.status === statusFilter);

    }

    renderTelegramTips(filtered);

}



function exportTipsToCsv() {

    if (allTelegramTips.length === 0) {

        showToast("Não há tips no log para exportar.", "info");

        return;

    }

    

    // Construct CSV Header (using semicolon delimiter for better compatibility with PT Excel)

    let csvContent = "\uFEFF"; // Prepend UTF-8 BOM

    csvContent += "Data;Liga;Mandante;Visitante;Mercado;Odds;Stake;Status\r\n";

    

    // Rows

    allTelegramTips.forEach(tip => {

        const row = [

            tip.date + (tip.time ? ' ' + tip.time : ''),

            `"${tip.league_name.replace(/"/g, '""')}"`,

            `"${tip.home_team.replace(/"/g, '""')}"`,

            `"${tip.away_team.replace(/"/g, '""')}"`,

            `"${tip.market.replace(/"/g, '""')}"`,

            tip.odds.toFixed(2),

            tip.stake.toFixed(1) + "%",

            tip.status

        ];

        csvContent += row.join(";") + "\r\n";

    });

    

    // Trigger download

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });

    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");

    link.setAttribute("href", url);

    link.setAttribute("download", `tips_telegram_${new Date().toISOString().slice(0,10)}.csv`);

    document.body.appendChild(link);

    link.click();

    document.body.removeChild(link);

}



function renderProbValue(prob, barType) {

    if (prob === undefined || isNaN(prob)) return '-';

    let colorClass = 'bar-draw'; // default

    

    if (['home', 'ht_home', 'over', 'over15', 'over25', 'over35', 'over45', 'over55', 'btts_yes', 'yes', 'ht_over05', 'ht_over15'].includes(barType)) {

        colorClass = 'bar-home';

    } else if (['away', 'ht_away', 'under', 'under25', 'under35', 'under45', 'under55', 'btts_no', 'no', 'ht_under05', 'ht_under15'].includes(barType)) {

        colorClass = 'bar-away';

    } else if (barType.startsWith('cs_')) {

        const scores = barType.replace('cs_', '').split('');

        if (scores.length === 2) {

            const h = parseInt(scores[0]);

            const a = parseInt(scores[1]);

            if (h > a) colorClass = 'bar-home';

            else if (h < a) colorClass = 'bar-away';

            else colorClass = 'bar-draw';

        }

    } else if (barType.startsWith('lay_')) {

        if (barType === 'lay_home') colorClass = 'bar-away';

        else if (barType === 'lay_away') colorClass = 'bar-home';

        else colorClass = 'bar-draw';

    }

    

    return `

        <div class="prob-bar-container" title="${prob.toFixed(1)}%">

            <div class="prob-bar-fill ${colorClass}" style="width: ${prob.toFixed(1)}%"></div>

        </div>

        <span>${prob.toFixed(1)}%</span>

    `;

}



function displayStakingComparison(results) {

    const panel = document.getElementById('staking-comparison-panel');

    const tbody = document.getElementById('staking-comparison-tbody');

    

    if (!results.summary_fixed || !results.summary_proportional || !results.summary_kelly) {

        panel.style.display = 'none';

        return;

    }

    

    panel.style.display = 'block';

    tbody.innerHTML = '';

    

    const rule = document.getElementById('stake-rule').value;

    const stakeValueInput = rule === 'kelly' ? parseFloat(document.getElementById('kelly-fraction').value) || 0.25 : parseFloat(document.getElementById('stake-value').value) || 10;

    

    const fixedStakeVal = rule === 'fixed' ? stakeValueInput : 10;

    const propStakePct = rule === 'proportional' ? stakeValueInput : 2;

    

    let kellyFractionText = rule === 'kelly' ? stakeValueInput.toFixed(2) + (stakeValueInput == 1 ? ' (Full)' : ' (' + (1/stakeValueInput).toFixed(0) + ')') : '1/4 de Kelly';



    

    const methods = [

        { name: `Stake Fixa ($${fixedStakeVal.toLocaleString('en-US')})`, key: 'summary_fixed', color: '#f59e0b' },

        { name: `Stake Proporcional (${propStakePct}%)`, key: 'summary_proportional', color: '#06b6d4' },

        { name: `Critério Kelly (${kellyFractionText})`, key: 'summary_kelly', color: '#ec4899' }

    ];

    

    methods.forEach(m => {

        const sum = results[m.key];

        const tr = document.createElement('tr');

        

        const netProfit = sum.net_profit;

        const profitClass = netProfit >= 0 ? 'text-profit' : 'text-loss';

        const roiClass = sum.roi >= 0 ? 'text-profit' : 'text-loss';

        

        tr.innerHTML = `

            <td style="font-weight: 600; color: ${m.color};">${m.name}</td>

            <td style="font-weight: 600;">$${sum.final_bankroll.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>

            <td class="${profitClass}" style="font-weight: 600;">${netProfit >= 0 ? '+' : ''}$${netProfit.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>

            <td>${sum.total_bets}</td>

            <td>${sum.win_rate.toFixed(1)}%</td>

            <td class="${roiClass}" style="font-weight: 600;">${sum.roi >= 0 ? '+' : ''}${sum.roi.toFixed(2)}%</td>

            <td style="color: var(--danger); font-weight: 600;">${sum.max_drawdown.toFixed(2)}%</td>

        `;

        tbody.appendChild(tr);

    });

}



function toggleMarketDropdown(event) {

    if (event) event.stopPropagation();

    const dropdown = document.getElementById('market-dropdown');

    dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';

}



function selectAllMarkets(val, event) {

    if (event) event.stopPropagation();

    const checkboxes = document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]');

    checkboxes.forEach(cb => {

        cb.checked = val;

    });

    onMarketSelectionChange();

}



function onMarketSelectionChange() {

    const checkedBoxes = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked'));

    const label = document.getElementById('multiselect-label');

    

    if (checkedBoxes.length === 0) {

        label.innerText = 'Nenhum Mercado Selecionado';

    } else if (checkedBoxes.length === 1) {

        label.innerText = checkedBoxes[0].parentNode.textContent.trim();

    } else {

        label.innerText = `${checkedBoxes.length} Mercados Selecionados`;

    }



    // Show exchange commission input if any Lay market is selected

    const selectedMkts = checkedBoxes.map(cb => cb.value);

    const hasLayMarket = selectedMkts.some(m => m.startsWith('lay'));

    const commGroup = document.getElementById('exchange-commission-group');

    if (commGroup) commGroup.style.display = hasLayMarket ? 'block' : 'none';

}



// ==========================================================================

// Web Push Notifications & Portfolio Allocator helper functions

// ==========================================================================

async function requestNotificationPermission() {

    if (!('Notification' in window)) {

        showToast("Notificações de sistema não são suportadas neste navegador.", "error");

        return;

    }

    

    try {

        const permission = await Notification.requestPermission();

        updateNotificationUi();

        if (permission === 'granted') {

            showToast("Notificações ativadas com sucesso!", "success");

        } else if (permission === 'denied') {

            showToast("Notificações foram bloqueadas. Habilite-as nas configurações do site.", "warning");

        }

    } catch (err) {

        console.error("Erro ao solicitar permissão de notificações:", err);

    }

}



function updateNotificationUi() {

    const btnRequest = document.getElementById('btn-request-notifications');

    if (!btnRequest) return;

    

    if (!('Notification' in window)) {

        btnRequest.disabled = true;

        btnRequest.innerHTML = `<i class="fa-solid fa-bell-slash"></i> Não Suportado`;

        return;

    }

    

    if (Notification.permission === 'granted') {

        btnRequest.innerHTML = `<i class="fa-solid fa-circle-check"></i> Notificações Ativas`;

        btnRequest.style.background = 'rgba(16, 185, 129, 0.1)';

        btnRequest.style.borderColor = 'rgba(16, 185, 129, 0.3)';

        btnRequest.style.color = '#34d399';

    } else if (Notification.permission === 'denied') {

        btnRequest.innerHTML = `<i class="fa-solid fa-bell-slash"></i> Bloqueado`;

        btnRequest.style.background = 'rgba(239, 68, 68, 0.1)';

        btnRequest.style.borderColor = 'rgba(239, 68, 68, 0.3)';

        btnRequest.style.color = '#f87171';

    } else {

        btnRequest.innerHTML = `<i class="fa-solid fa-bell"></i> Ativar Notificações`;

        btnRequest.style.background = '';

        btnRequest.style.borderColor = '';

        btnRequest.style.color = '';

    }

}



function testNotificationAlert() {

    if (!('Notification' in window)) {

        showToast("Notificações não suportadas.", "error");

        return;

    }

    

    if (Notification.permission !== 'granted') {

        showToast("Por favor, ative as notificações primeiro clicando em 'Ativar Notificações'.", "warning");

        return;

    }

    

    try {

        new Notification("Sports Betting Backtester Pro", {

            body: "Esta é uma notificação de teste! Você receberá alertas nativos quando novas tips (+EV) forem carregadas.",

            icon: "/icons/icon-192.png"

        });

    } catch (e) {

        console.warn("Notification constructor failed, trying service worker registration notification:", e);

        if (navigator.serviceWorker) {

            navigator.serviceWorker.ready.then(registration => {

                registration.showNotification("Sports Betting Backtester Pro", {

                    body: "Esta é uma notificação de teste! Você receberá alertas nativos quando novas tips (+EV) forem carregadas.",

                    icon: "/icons/icon-192.png"

                });

            });

        }

    }

}



function displayPortfolioOptimization(portfolioOpt) {

    const panel = document.getElementById('portfolio-allocator-panel');

    const container = document.getElementById('allocator-bars-container');

    

    if (!portfolioOpt || !portfolioOpt.weights || Object.keys(portfolioOpt.weights).length === 0) {

        panel.style.display = 'none';

        return;

    }

    

    panel.style.display = 'block';

    container.innerHTML = '';

    

    // Sort markets by weight descending

    const sortedWeights = Object.entries(portfolioOpt.weights).sort((a, b) => b[1] - a[1]);

    

    sortedWeights.forEach(([market, weight]) => {

        const pct = (weight * 100).toFixed(1);

        const div = document.createElement('div');

        div.className = 'allocator-market-row';

        div.innerHTML = `

            <div class="allocator-market-header">

                <span class="allocator-market-name">${market}</span>

                <span class="allocator-market-weight">${pct}%</span>

            </div>

            <div class="allocator-progress-bar">

                <div class="allocator-progress-fill" style="width: ${pct}%"></div>

            </div>

        `;

        container.appendChild(div);

    });

    

    document.getElementById('allocator-expected-return').innerText = `+${portfolioOpt.expected_return_pct.toFixed(2)}%`;

    document.getElementById('allocator-volatility').innerText = `${portfolioOpt.volatility_pct.toFixed(2)}%`;

    

    const sharpe = portfolioOpt.volatility_pct > 0 

        ? (portfolioOpt.expected_return_pct / portfolioOpt.volatility_pct) 

        : 0;

    document.getElementById('allocator-sharpe').innerText = sharpe.toFixed(2);

}



// Global click listener to close the custom markets multiselect dropdown when clicking outside

document.addEventListener('click', function(e) {

    const multiselect = document.getElementById('market-multiselect');

    const dropdown = document.getElementById('market-dropdown');

    if (multiselect && dropdown && !multiselect.contains(e.target)) {

        dropdown.style.display = 'none';

    }

});



// Run a unified simulation with all checked items from the scanner results

function simulateSelectedScannerItems() {

    const checkboxes = document.querySelectorAll('.scanner-item-cb:checked');

    if (checkboxes.length === 0) {

        showToast("Por favor, selecione pelo menos um item para simular.", "error");

        return;

    }

    

    const scanType = checkboxes[0].getAttribute('data-scantype');

    const selectedCodes = Array.from(checkboxes).map(cb => cb.value);

    

    if (scanType === 'markets') {

        const marketCbs = document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]');

        let count = 0;

        marketCbs.forEach(cb => {

            if (selectedCodes.includes(cb.value)) {

                cb.checked = true;

                count++;

            } else {

                cb.checked = false;

            }

        });

        onMarketSelectionChange();

        showToast(`${count} mercado(s) selecionado(s) e aplicado(s) ao painel lateral. Executando simulação...`, "success");

    } else {

        const leagueCbs = document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]');

        let count = 0;

        leagueCbs.forEach(cb => {

            if (selectedCodes.includes(cb.value)) {

                cb.checked = true;

                count++;

            } else {

                cb.checked = false;

            }

        });

        showToast(`${count} liga(s) selecionada(s) e aplicada(s) ao painel lateral. Executando simulação...`, "success");

    }

    

    runBacktest();

}



// ==========================================================================

// Statistical Validation & Out-of-Sample Rendering

// ==========================================================================



function renderStatValidation(summary) {

    const panel = document.getElementById('stat-validation-panel');

    const grid = document.getElementById('stat-validation-grid');

    if (!panel || !grid) return;



    // Only show if at least one stat field exists

    if (summary.brier_score === undefined && summary.bootstrap_roi_ci_lower === undefined && summary.min_sample_size === undefined && summary.edge_decay_pct === undefined) {

        panel.style.display = 'none';

        return;

    }



    panel.style.display = 'block';

    grid.innerHTML = '';



    const fmtNum = (v, d) => v !== undefined && v !== null ? v.toFixed(d).replace('.', ',') : 'N/A';



    // 1. Brier Score

    if (summary.brier_score !== undefined) {

        const bsModel = summary.brier_score;

        const bsMarket = summary.brier_score_market;

        const improv = summary.brier_improvement;

        const isBetter = bsMarket !== undefined && bsModel < bsMarket;

        const bsColor = isBetter ? 'var(--success)' : 'var(--danger)';

        const bsIcon = isBetter ? 'fa-check-circle' : 'fa-times-circle';

        const tooltip = 'O Brier Score mede a precisão das probabilidades do modelo. Quanto menor, melhor. Se o modelo supera o mercado, suas previsões são mais precisas que as das casas de apostas.';

        grid.innerHTML += `

            <div class="stat-card" title="${tooltip}" onclick="showToast(this.title, 'info')">

                <div class="stat-label"><i class="fa-solid fa-bullseye"></i> Brier Score</div>

                <div class="stat-value" style="color: ${bsColor};"><i class="fa-solid ${bsIcon}"></i> ${fmtNum(bsModel, 3)}</div>

                <div class="stat-detail">

                    Mercado: ${bsMarket !== undefined ? fmtNum(bsMarket, 3) : 'N/A'}

                    ${improv !== undefined ? ` · Melhoria: <strong style="color: ${improv > 0 ? 'var(--success)' : 'var(--danger)'}">${improv > 0 ? '+' : ''}${fmtNum(improv, 1)}%</strong>` : ''}

                </div>

            </div>`;

    }



    // 2. Bootstrap ROI Confidence Interval

    if (summary.bootstrap_roi_ci_lower !== undefined) {

        const lower = summary.bootstrap_roi_ci_lower;

        const upper = summary.bootstrap_roi_ci_upper;

        const median = summary.bootstrap_roi_median;

        const probPos = summary.prob_positive_roi;

        const ciColor = lower > 0 ? 'var(--success)' : 'var(--danger)';

        const tooltip = 'Intervalo de confiança de 95% do ROI obtido por reamostragem bootstrap (5.000 simulações). Se o limite inferior for positivo, o edge é estatisticamente robusto.';

        grid.innerHTML += `

            <div class="stat-card" title="${tooltip}" onclick="showToast(this.title, 'info')">

                <div class="stat-label"><i class="fa-solid fa-chart-area"></i> Intervalo de Confiança Bootstrap (ROI)</div>

                <div class="stat-value" style="color: ${ciColor};">${median !== undefined ? fmtNum(median, 1) : '?'}%</div>

                <div class="stat-detail">

                    IC 95%: <strong style="color: ${ciColor};">${fmtNum(lower, 1)}%</strong> — <strong>${fmtNum(upper, 1)}%</strong>

                    ${probPos !== undefined ? ` · Prob. ROI+: <strong style="color: ${probPos >= 0.9 ? 'var(--success)' : probPos >= 0.7 ? 'var(--warning)' : 'var(--danger)'}">${fmtNum(probPos * 100, 1)}%</strong>` : ''}

                </div>

            </div>`;

    }



    // 3. Power Analysis

    if (summary.min_sample_size !== undefined) {

        const totalBets = summary.total_bets || 0;

        const minSample = summary.min_sample_size;

        const sufficient = summary.sample_sufficient;

        const powerRatio = summary.power_ratio;

        const ratio = minSample > 0 ? Math.min(totalBets / minSample, 2.0) : 0;

        const pctWidth = Math.min(ratio * 50, 100);

        let barColor = 'var(--danger)';

        if (sufficient) barColor = 'var(--success)';

        else if (ratio >= 0.7) barColor = 'var(--warning)';

        const tooltip = 'Análise de potência estatística. Indica se o número de apostas é suficiente para confirmar que o ROI observado não é fruto de acaso. Uma razão > 1.0 significa amostra suficiente.';

        grid.innerHTML += `

            <div class="stat-card" title="${tooltip}" onclick="showToast(this.title, 'info')">

                <div class="stat-label"><i class="fa-solid fa-vial"></i> Análise de Potência</div>

                <div class="stat-value" style="color: ${sufficient ? 'var(--success)' : ratio >= 0.7 ? 'var(--warning)' : 'var(--danger)'};">

                    ${totalBets} / ${minSample} apostas

                </div>

                <div class="stat-detail">

                    Razão: <strong>${powerRatio !== undefined ? fmtNum(powerRatio, 2) : fmtNum(ratio, 2)}</strong>

                    · ${sufficient ? '<span style="color: var(--success);"><i class="fa-solid fa-check"></i> Amostra Suficiente</span>' : '<span style="color: var(--warning);"><i class="fa-solid fa-exclamation-triangle"></i> Amostra Insuficiente</span>'}

                </div>

                <div class="stat-power-bar">

                    <div class="stat-power-bar-fill" style="width: ${pctWidth}%; background: ${barColor};"></div>

                </div>

            </div>`;

    }



    // 4. Edge Decay

    if (summary.edge_decay_pct !== undefined) {

        const decay = summary.edge_decay_pct;

        const alert = summary.edge_decay_alert;

        let decayColor = 'var(--success)';

        let decayIcon = 'fa-shield-halved';

        let decayLabel = 'Edge Estável';

        if (Math.abs(decay) > 30) { decayColor = 'var(--danger)'; decayIcon = 'fa-triangle-exclamation'; decayLabel = 'Edge em Declínio Severo'; }

        else if (Math.abs(decay) > 15) { decayColor = 'var(--warning)'; decayIcon = 'fa-exclamation'; decayLabel = 'Edge em Leve Declínio'; }

        const tooltip = 'Compara o ROI dos últimos 100 jogos com a média geral. Uma queda superior a 30% indica que o edge pode estar se esgotando.';

        grid.innerHTML += `

            <div class="stat-card" title="${tooltip}" onclick="showToast(this.title, 'info')">

                <div class="stat-label"><i class="fa-solid fa-chart-line"></i> Decay do Edge</div>

                <div class="stat-value" style="color: ${decayColor};"><i class="fa-solid ${decayIcon}"></i> ${fmtNum(decay, 1)}%</div>

                <div class="stat-detail">

                    ${decayLabel}

                    ${alert ? ` · <span style="color: var(--warning);">${alert}</span>` : ''}

                </div>

            </div>`;

    }

}



function renderOosResults(oosSummary, inSampleSummary) {

    const panel = document.getElementById('oos-results-panel');

    const grid = document.getElementById('oos-metrics-grid');

    const badge = document.getElementById('oos-badge');

    if (!panel || !grid) return;



    if (!oosSummary) {

        panel.style.display = 'none';

        return;

    }



    panel.style.display = 'block';

    grid.innerHTML = '';



    const fmtNum = (v, d) => v !== undefined && v !== null ? v.toFixed(d).replace('.', ',') : 'N/A';

    const isProfit = oosSummary.net_profit >= 0;

    const sign = isProfit ? '+' : '';



    // OOS Metric cards

    grid.innerHTML = `

        <div class="metric-card" style="border-left: 3px solid ${isProfit ? 'var(--success)' : 'var(--danger)'}; padding: 15px;">

            <div class="metric-info">

                <span class="metric-label">Lucro OOS</span>

                <h2 style="font-size: 18px; color: ${isProfit ? '#34d399' : '#f87171'};">${sign}$${oosSummary.net_profit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</h2>

            </div>

        </div>

        <div class="metric-card" style="border-left: 3px solid ${oosSummary.roi >= 0 ? 'var(--success)' : 'var(--danger)'}; padding: 15px;">

            <div class="metric-info">

                <span class="metric-label">ROI OOS</span>

                <h2 style="font-size: 18px; color: ${oosSummary.roi >= 0 ? '#34d399' : '#f87171'};">${oosSummary.roi >= 0 ? '+' : ''}${fmtNum(oosSummary.roi, 2)}%</h2>

            </div>

        </div>

        <div class="metric-card" style="border-left: 3px solid var(--primary); padding: 15px;">

            <div class="metric-info">

                <span class="metric-label">Taxa de Acerto OOS</span>

                <h2 style="font-size: 18px;">${fmtNum(oosSummary.win_rate, 1)}%</h2>

            </div>

        </div>

        <div class="metric-card" style="border-left: 3px solid var(--text-muted); padding: 15px;">

            <div class="metric-info">

                <span class="metric-label">Total Apostas OOS</span>

                <h2 style="font-size: 18px;">${oosSummary.total_bets}</h2>

            </div>

        </div>

    `;



    // Badge comparing OOS ROI vs in-sample ROI

    if (badge && inSampleSummary) {

        const isROI = inSampleSummary.roi;

        const oosROI = oosSummary.roi;

        const sameSign = (isROI >= 0 && oosROI >= 0) || (isROI < 0 && oosROI < 0);

        const degradation = isROI !== 0 ? Math.abs((oosROI - isROI) / Math.abs(isROI)) : 1;



        if (sameSign && degradation <= 0.5) {

            badge.className = 'oos-badge oos-pass';

            badge.innerHTML = '<i class="fa-solid fa-check"></i> Consistente';

        } else if (sameSign) {

            badge.className = 'oos-badge oos-warn';

            badge.innerHTML = '<i class="fa-solid fa-exclamation"></i> Degradado';

        } else {

            badge.className = 'oos-badge oos-fail';

            badge.innerHTML = '<i class="fa-solid fa-xmark"></i> Invertido';

        }

    }

}



// --- Edge Quality Score & Risk Management ---



function switchTab(tabId) {

    // Esconder todas as abas

    document.querySelectorAll('.tab-pane').forEach(el => {

        el.style.display = 'none';

        el.classList.remove('active');

    });

    

    // Remover classe active de todos os botões

    document.querySelectorAll('.tab-btn').forEach(el => {

        el.classList.remove('active');

        el.style.borderBottomColor = 'transparent';

        el.style.color = 'var(--text-muted)';

    });

    

    // Mostrar a aba selecionada

    const targetTab = document.getElementById(tabId);

    if (targetTab) {

        targetTab.style.display = 'block';

        targetTab.classList.add('active');

    }

    

    // Ativar o botão selecionado

    const targetBtn = document.getElementById(`tab-btn-${tabId.replace('tab-', '')}`);

    if (targetBtn) {

        targetBtn.classList.add('active');

        targetBtn.style.borderBottomColor = 'var(--primary)';

        targetBtn.style.color = 'var(--text-primary)';

    }

    

    // Load history if switching to it

    if (tabId === 'tab-history') {

        loadHistory();

    }

    

    // Toggle sidebar filters depending on the tab

    const groupEv = document.getElementById('group-ev');

    const groupDrop = document.getElementById('group-drop');

    if (groupEv && groupDrop) {

        if (tabId === 'tab-radar') {

            groupEv.style.display = 'none';

            groupDrop.style.display = 'block';

        } else {

            groupEv.style.display = 'block';

            groupDrop.style.display = 'none';

        }

    }

}



function renderEdgeQualityScore(eqs) {

    if (!eqs) return;

    

    // Hide empty state, show content

    document.getElementById('risk-empty-state').style.display = 'none';

    document.getElementById('risk-content').style.display = 'block';

    

    // Update Score Circle

    const scoreEl = document.getElementById('eqs-score');

    scoreEl.innerText = eqs.score;

    

    const circle = scoreEl.closest('.score-circle');

    if (eqs.score >= 80) {

        circle.style.borderColor = 'var(--success)';

        scoreEl.style.color = 'var(--success)';

    } else if (eqs.score >= 50) {

        circle.style.borderColor = 'var(--warning)';

        scoreEl.style.color = 'var(--warning)';

    } else {

        circle.style.borderColor = 'var(--danger)';

        scoreEl.style.color = 'var(--danger)';

    }

    

    // Update Verdict

    const verdictEl = document.getElementById('eqs-verdict');

    verdictEl.innerText = eqs.verdict;

    verdictEl.style.color = `var(--${eqs.verdict_color})`;

    

    // Update Recommendation

    document.getElementById('eqs-recommendation').innerText = eqs.risk_recommendation;

    

    // Build Checklist Breakdown

    const breakdownContainer = document.getElementById('eqs-breakdown');

    breakdownContainer.innerHTML = '';

    

    if (eqs.breakdown && eqs.breakdown.length > 0) {

        eqs.breakdown.forEach(item => {

            const pct = (item.points / item.max) * 100;

            let iconColor = 'var(--danger)';

            let iconClass = 'fa-xmark';

            

            if (pct >= 80) {

                iconColor = 'var(--success)';

                iconClass = 'fa-check';

            } else if (pct >= 40) {

                iconColor = 'var(--warning)';

                iconClass = 'fa-exclamation';

            }

            

            const card = document.createElement('div');

            card.className = 'checklist-card';

            card.style.cssText = `

                background: rgba(255,255,255,0.02);

                border: 1px solid rgba(255,255,255,0.05);

                border-radius: var(--border-radius-sm);

                padding: 15px;

                display: flex;

                align-items: center;

                gap: 15px;

            `;

            

            const explanations = {

                'Validação OOS': 'Compara o lucro do teste cego (últimos 20% do histórico) com os primeiros 80%. Se o lucro cair muito, o modelo estava viciado (overfitting).',

                'Bootstrap CI (95%)': 'Simula 1.000 piores cenários possíveis de azar. O limite inferior mostra o lucro mínimo esperado em 95% dessas simulações.',

                'Closing Line Value (CLV)': 'Mede se a cotação que a IA indica é maior do que o preço de fechamento perfeito das casas asiáticas (Pinnacle). O único comprovante real de Edge.',

                'Estabilidade Temporal': 'Verifica se a estratégia está apodrecendo com o tempo. Se o ROI dos últimos meses cair comparado aos primeiros, a casa já ajustou as Odds.',

                'P-Valor Binomial': 'Prova matemática da chance do seu lucro ser Pura Sorte. Um p-valor de 0.000 significa chance zero de ser apenas sorte cega.',

                'Power Analysis (Amostra)': 'Avisa se você tem o histórico de apostas mínimo necessário para a IA ter certeza estatística (acima de 1.0x).',

                'Precisão Brier': 'Compara quem acerta mais: A probabilidade do nosso Robô ou a probabilidade embutida na Odd da Casa de Apostas.'

            };

            const tipText = explanations[item.metric] || '';



            card.innerHTML = `

                <div style="width: 30px; height: 30px; border-radius: 50%; background: ${iconColor}20; color: ${iconColor}; display: flex; align-items: center; justify-content: center; font-size: 14px;">

                    <i class="fa-solid ${iconClass}"></i>

                </div>

                <div style="flex: 1;" title="${tipText}">

                    <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 2px; display: flex; align-items: center; gap: 4px; cursor: help;">

                        ${item.metric}

                        <i class="fa-solid fa-circle-question" style="opacity: 0.5;"></i>

                    </div>

                    <div style="font-size: 14px; color: var(--text-primary);">${item.message}</div>

                </div>

                <div style="text-align: right;">

                    <div style="font-size: 16px; font-weight: bold; font-family: var(--font-heading); color: ${iconColor};">${item.points}<span style="font-size: 12px; color: var(--text-muted);">/${item.max}</span></div>

                </div>

            `;

            

            breakdownContainer.appendChild(card);

        });

    }

}



// --- Global EQS Scanner ---

async function runEqsScanner(scanType) {

    const btnEqsMarkets = document.getElementById('btn-eqs-scan-markets');

    const btnEqsLeagues = document.getElementById('btn-eqs-scan-leagues');

    const btnEqsCombinations = document.getElementById('btn-eqs-scan-combinations');

    

    let activeBtn = btnEqsMarkets;

    if (scanType === 'leagues') activeBtn = btnEqsLeagues;

    if (scanType === 'combinations') activeBtn = btnEqsCombinations;

    

    const allBtns = [btnEqsMarkets, btnEqsLeagues, btnEqsCombinations];

    

    let selectedLeagues;

    if (scanType === 'leagues' || scanType === 'combinations') {

        selectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);

        if (selectedLeagues.length === 0) {

            selectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]')).map(cb => cb.value);

        }

    } else {

        selectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);

        if (selectedLeagues.length === 0) {

            showToast("Por favor, selecione pelo menos um campeonato no painel lateral.", "error");

            return;

        }

    }

    

    activeBtn.classList.add('scanning');

    const originalText = activeBtn.innerHTML;

    activeBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analisando...';

    allBtns.forEach(btn => btn.disabled = true);

    

    showToast(`Escaneando Institucionalmente ${scanType}...`, "info");

    

    const ruleInput = document.getElementById('stake-rule').value;

    let stakingRule = ruleInput;

    let stakeValue = parseFloat(document.getElementById('stake-value').value);

    if (ruleInput.startsWith('kelly')) {

        stakingRule = 'kelly';

        if (ruleInput === 'kelly') stakeValue = 1.0;

        else if (ruleInput === 'kelly_half') stakeValue = 0.5;

        else if (ruleInput === 'kelly_quarter') stakeValue = 0.25;

        else if (ruleInput === 'kelly_eighth') stakeValue = 0.125;
        else if (ruleInput === 'kelly_sixteenth') stakeValue = 0.0625;

    }

    

    const requestData = {

        leagues: selectedLeagues,

        startDate: document.getElementById('start-date').value,

        endDate: document.getElementById('end-date').value,

        market: Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value),

        valueThreshold: parseFloat(document.getElementById('val-threshold').value),

        initialBankroll: parseFloat(document.getElementById('init-bankroll').value),

        stakingRule: stakingRule,

        stakeValue: stakeValue,

        oddsSource: document.getElementById('odds-source').value,

        scanType: scanType,

        minOdds: parseFloat(document.getElementById('min-odds').value) || 1.0,

        maxOdds: parseFloat(document.getElementById('max-odds').value) || 50.0,

        use_ml: document.getElementById('use-ml-toggle')?.checked || false,

        data_source: window.currentDataSource,

        futpython_api_key: window.futpythonApiKey

    };

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/scan`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(requestData)

        });

        

        if (!res.ok) {

            const errData = await res.json();

            throw new Error(errData.detail || "Erro ao escanear");

        }

        

        const data = await res.json();

        const results = data.results;

        

        const sortedResults = results.sort((a, b) => b.eqs_score - a.eqs_score);

        const approvedCount = sortedResults.filter(r => r.eqs_verdict && r.eqs_verdict.toLowerCase().includes('aprovado')).length;

        

        if (approvedCount > 0) {

            showToast(`Escaneamento concluído! ${approvedCount} Aprovados encontrados.`, "success");

        } else {

            showToast(`Nenhum aprovado encontrado. Exibindo resultados reprovados para análise.`, "warning");

        }

        

        renderEqsResults(sortedResults, scanType, requestData);

        switchTab('tab-scanner');

        

    } catch (err) {

        showToast(err.message, "error");

    } finally {

        activeBtn.classList.remove('scanning');

        activeBtn.innerHTML = originalText;

        allBtns.forEach(btn => btn.disabled = false);

    }

}



function renderEqsResults(results, scanType, requestData) {

    const resultsContainer = document.getElementById('global-scanner-results');

    resultsContainer.innerHTML = '';

    

    if (results.length === 0) {

        resultsContainer.innerHTML = `

            <div class="empty-state text-center" style="padding: 60px 20px;">

                <i class="fa-solid fa-triangle-exclamation" style="font-size: 48px; opacity: 0.2; margin-bottom: 15px; display: block; color: var(--warning);"></i>

                <p style="font-size: 16px;">Nenhum ${scanType === 'markets' ? 'mercado' : 'liga'} atendeu aos critérios rigorosos de aprovação Institucional.</p>

                <p style="font-size: 12px; color: var(--text-muted); margin-top: 10px;">Tente ajustar as datas, odd mínima/máxima ou o value threshold.</p>

            </div>

        `;

        return;

    }

    

    let leaguesContextHtml = '';

    if (scanType === 'markets') {

        const leaguesCount = requestData.leagues.length;

        leaguesContextHtml = `

            <div style="margin-bottom: 15px; padding: 10px 15px; background: rgba(0,0,0,0.2); border-left: 3px solid var(--primary); border-radius: 4px;">

                <span style="color: var(--text-muted); font-size: 13px;">

                    <i class="fa-solid fa-earth-americas" style="margin-right: 5px;"></i> 

                    Escaneamento consolidado de <b>${leaguesCount} liga(s)</b>. 

                </span>

            </div>

        `;

    } else if (scanType === 'leagues') {

        const marketsCount = requestData.market.length || 33;

        leaguesContextHtml = `

            <div style="margin-bottom: 15px; padding: 10px 15px; background: rgba(0,0,0,0.2); border-left: 3px solid var(--primary); border-radius: 4px;">

                <span style="color: var(--text-muted); font-size: 13px;">

                    <i class="fa-solid fa-chart-line" style="margin-right: 5px;"></i> 

                    Escaneamento consolidado em <b>${marketsCount} mercado(s)</b>.

                </span>

            </div>

        `;

    } else if (scanType === 'combinations') {

        const leaguesCount = requestData.leagues.length;

        const marketsCount = requestData.market.length || 33;

        const combCount = leaguesCount * marketsCount;

        leaguesContextHtml = `

            <div style="margin-bottom: 15px; padding: 10px 15px; background: rgba(0,0,0,0.2); border-left: 3px solid var(--primary); border-radius: 4px;">

                <span style="color: var(--text-muted); font-size: 13px;">

                    <i class="fa-solid fa-layer-group" style="margin-right: 5px;"></i> 

                    Escaneamento de <b>${combCount} nichos únicos</b> (Cruzamento de ${leaguesCount} ligas com ${marketsCount} mercados).

                </span>

            </div>

        `;

    }

    

    const tableHtml = `

        ${leaguesContextHtml}

        <div class="eqs-legend" style="margin-bottom: 20px; padding: 15px; background: var(--bg-secondary); border-radius: 8px; border: 1px solid rgba(255,255,255,0.05);">

            <h4 style="margin: 0 0 10px 0; font-size: 14px; color: var(--text-primary);"><i class="fa-solid fa-circle-info"></i> Legenda do Edge Quality Score (EQS)</h4>

            <div style="display: flex; gap: 15px; flex-wrap: wrap;">

                <div style="display: flex; align-items: center; gap: 8px;">

                    <span style="width: 12px; height: 12px; border-radius: 50%; background: var(--success);"></span>

                    <span style="font-size: 12px; color: var(--text-muted);"><b>Aprovado (80-100 pts)</b></span>

                </div>

                <div style="display: flex; align-items: center; gap: 8px;">

                    <span style="width: 12px; height: 12px; border-radius: 50%; background: var(--warning);"></span>

                    <span style="font-size: 12px; color: var(--text-muted);"><b>Quarentena (50-79 pts)</b></span>

                </div>

                <div style="display: flex; align-items: center; gap: 8px;">

                    <span style="width: 12px; height: 12px; border-radius: 50%; background: var(--danger);"></span>

                    <span style="font-size: 12px; color: var(--text-muted);"><b>Rejeitado (0-49 pts)</b></span>

                </div>

            </div>

        </div>

        <table class="scanner-table" style="width: 100%; border-collapse: collapse; margin-top: 10px;">

            <thead>

                <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.2);">

                    <th style="padding: 12px 15px; text-align: left; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">${scanType === 'markets' ? 'Mercado' : (scanType === 'leagues' ? 'Liga' : 'Nicho')}</th>

                    <th style="padding: 12px 15px; text-align: center; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">EQS Score</th>

                    <th style="padding: 12px 15px; text-align: center; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Veredito</th>

                    <th style="padding: 12px 15px; text-align: right; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">CLV Médio</th>

                    <th style="padding: 12px 15px; text-align: right; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">ROI</th>

                    <th style="padding: 12px 15px; text-align: right; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Lucro</th>

                    <th style="padding: 12px 15px; text-align: center; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Apostas</th>

                    <th style="padding: 12px 15px; text-align: right; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Ação</th>

                </tr>

            </thead>

            <tbody>

                ${results.map(r => {

                    const isProfit = r.net_profit >= 0;

                    return `

                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: ${r.eqs_color}10;">

                            <td style="padding: 12px 15px; font-weight: 500;">

                                ${scanType === 'markets' ? `<span class="market-badge">${r.name}</span>` : 

                                 (scanType === 'leagues' ? `<span style="display: flex; align-items: center; gap: 8px;">${r.name}</span>` :

                                 `<span style="display: flex; align-items: center; gap: 8px; font-size: 11px;">${r.name.replace(' / ', ' <i class="fa-solid fa-angle-right" style="color:var(--text-muted); font-size:9px;"></i> ')}</span>`)}

                                ${r.opt_range ? `<div style="margin-top: 6px; font-size: 10px; color: var(--warning); background: rgba(245, 158, 11, 0.1); padding: 4px 6px; border-radius: 4px; display: inline-block; border: 1px solid rgba(245, 158, 11, 0.2);"><i class="fa-solid fa-bolt"></i> <b>Otimizado:</b> ${r.opt_range} ➜ EQS ${r.opt_eqs}</div>` : ''}

                            </td>

                            <td style="padding: 12px 15px; text-align: center;">

                                <div style="display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 50%; border: 2px solid ${r.eqs_color}; color: var(--text-primary); font-weight: bold; font-size: 12px;">

                                    ${r.eqs_score}

                                </div>

                            </td>

                            <td style="padding: 12px 15px; text-align: center;">

                                <span style="background: ${r.eqs_color}20; color: ${r.eqs_color}; padding: 4px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; text-transform: uppercase;">

                                    ${r.eqs_verdict}

                                </span>

                            </td>

                            <td style="padding: 12px 15px; text-align: right; color: ${r.avg_clv === null || r.avg_clv === undefined ? 'var(--text-muted)' : (r.avg_clv > 0 ? 'var(--success)' : 'var(--danger)')};">

                                ${r.avg_clv === null || r.avg_clv === undefined ? 'N/A' : (r.avg_clv > 0 ? '+' : '') + r.avg_clv.toFixed(2) + '%'}

                            </td>

                            <td style="padding: 12px 15px; text-align: right; color: ${isProfit ? 'var(--success)' : 'var(--danger)'};">

                                ${r.roi.toFixed(1)}%

                            </td>

                            <td style="padding: 12px 15px; text-align: right; color: ${isProfit ? 'var(--success)' : 'var(--danger)'};">

                                $${r.net_profit.toFixed(2)}

                            </td>

                            <td style="padding: 12px 15px; text-align: center;">

                                ${r.total_bets}

                            </td>

                            <td style="padding: 12px 15px; text-align: right;">

                                <button onclick="runSpecificEqsBacktest('${scanType}', '${r.code}', '${r.opt_range || ''}')" style="background: var(--primary); border: none; color: white; padding: 6px 12px; border-radius: 4px; font-size: 11px; cursor: pointer;">

                                    <i class="fa-solid fa-play"></i> Analisar

                                </button>

                            </td>

                        </tr>

                    `;

                }).join('')}

            </tbody>

        </table>

    `;

    

    resultsContainer.innerHTML = tableHtml;

    window.lastEqsScanParams = requestData;

}



window.runSpecificEqsBacktest = function(scanType, code, optRange) {
    if (!window.lastEqsScanParams) return;
    
    switchTab('tab-laboratory');
    
    // Limpar filtros avançados de odds residuais para não interferir no resultado
    const advancedOddsFields = [
        'min-odds-h', 'max-odds-h',
        'min-odds-d', 'max-odds-d',
        'min-odds-a', 'max-odds-a',
        'min-odds-over25', 'max-odds-over25',
        'min-odds-under25', 'max-odds-under25'
    ];
    advancedOddsFields.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.value = '';
            el.dispatchEvent(new Event('change'));
        }
    });

    document.getElementById('start-date').value = window.lastEqsScanParams.startDate;
    document.getElementById('end-date').value = window.lastEqsScanParams.endDate;

    

    // Configurar min/max odds com base na otimização (se houver)

    let minOdd = window.lastEqsScanParams.minOdds || 1.0;

    let maxOdd = window.lastEqsScanParams.maxOdds || 50.0;

    

    if (optRange) {

        if (optRange.includes('EV > 1.25')) { document.getElementById('val-threshold').value = '1.25'; }

        else if (optRange.includes('EV > 1.15')) { document.getElementById('val-threshold').value = '1.15'; }

        else if (optRange.includes('EV > 1.10')) { document.getElementById('val-threshold').value = '1.10'; }

        else if (optRange.includes('EV > 1.05')) { document.getElementById('val-threshold').value = '1.05'; }

        

        if (optRange.includes('<= 1.50') && !optRange.includes('Excluir')) { minOdd = 1.0; maxOdd = 1.50; }

        else if (optRange.includes('1.50 - 2.00')) { minOdd = 1.50; maxOdd = 2.00; }

        else if (optRange.includes('2.00 - 3.00')) { minOdd = 2.00; maxOdd = 3.00; }

        else if (optRange.includes('> 3.00') && !optRange.includes('<=')) { minOdd = 3.00; maxOdd = 50.0; }

        else if (optRange.includes('<= 3.00')) { minOdd = 1.0; maxOdd = 3.00; }

        else if (optRange.includes('> 1.50') && !optRange.includes('<=')) { minOdd = 1.50; maxOdd = 50.0; }

    } else {
        document.getElementById('val-threshold').value = window.lastEqsScanParams.valueThreshold || '1.05';
    }
    
    document.getElementById('val-threshold').dispatchEvent(new Event('change'));


    

    document.getElementById('min-odds').value = minOdd;

    document.getElementById('max-odds').value = maxOdd;

    

    if (scanType === 'markets') {
        // Seleciona todas as ligas do scan original
        const scanLeagues = window.lastEqsScanParams.leagues || [];
        document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]').forEach(cb => {
            const shouldBeChecked = scanLeagues.includes(cb.value);
            if (cb.checked !== shouldBeChecked) {
                cb.checked = shouldBeChecked;
                cb.dispatchEvent(new Event('change'));
            }
        });
        
        // Seleciona apenas o mercado clicado
        document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]').forEach(cb => {
            const shouldBeChecked = (cb.value === code || cb.value === code.replace('1x2_', ''));
            if (cb.checked !== shouldBeChecked) {
                cb.checked = shouldBeChecked;
                cb.dispatchEvent(new Event('change'));
            }
        });
    } else if (scanType === 'leagues') {
        // Seleciona apenas a liga clicada
        document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]').forEach(cb => {
            const shouldBeChecked = (cb.value === code);
            if (cb.checked !== shouldBeChecked) {
                cb.checked = shouldBeChecked;
                cb.dispatchEvent(new Event('change'));
            }
        });
        
        // Seleciona todos os mercados originais
        const scanMarkets = window.lastEqsScanParams.market || [];
        document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]').forEach(cb => {
            let shouldBeChecked = false;
            if (scanMarkets.length > 0) {
                shouldBeChecked = scanMarkets.includes(cb.value) || scanMarkets.includes(cb.value.replace('1x2_', ''));
            } else {
                shouldBeChecked = true;
            }
            if (cb.checked !== shouldBeChecked) {
                cb.checked = shouldBeChecked;
                cb.dispatchEvent(new Event('change'));
            }
        });
    } else if (scanType === 'combinations') {
        const parts = code.split('|');
        if (parts.length === 2) {
            const leagueCode = parts[0];
            const marketCode = parts[1];
            
            document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]').forEach(cb => {
                const shouldBeChecked = (cb.value === leagueCode);
                if (cb.checked !== shouldBeChecked) {
                    cb.checked = shouldBeChecked;
                    cb.dispatchEvent(new Event('change'));
                }
            });
            document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]').forEach(cb => {
                const shouldBeChecked = (cb.value === marketCode || cb.value === marketCode.replace('1x2_', ''));
                if (cb.checked !== shouldBeChecked) {
                    cb.checked = shouldBeChecked;
                    cb.dispatchEvent(new Event('change'));
                }
            });
        }
    }

    // Força a validação visual do label do multiselect de mercados
    if (typeof onMarketSelectionChange === 'function') {
        onMarketSelectionChange();
    }
    
    // Força a validação OOS (Out-of-Sample) para garantir que o Score de EQS seja o mesmo do Scanner
    const oosToggle = document.getElementById('oos-toggle');
    if (oosToggle && !oosToggle.checked) {
        oosToggle.checked = true;
        oosToggle.dispatchEvent(new Event('change'));
    }
    
    // Rodar backtest principal com um pequeno delay para que os eventos no DOM tenham terminado de propagar
    setTimeout(() => {
        runBacktest();
    }, 150);
    
    // Scroll para o topo
    window.scrollTo({ top: 0, behavior: 'smooth' });

};



// ==========================================================================

// History / Saved Strategies Logic

// ==========================================================================



function openSaveStrategyModal() {

    if (!lastBacktestParams || !lastBacktestSummary) {

        showToast("Rode um backtest primeiro para salvar a estratégia.", "error");

        return;

    }

    document.getElementById('save-strategy-modal').style.display = 'flex';

    

    // Auto-fill a suggested name with current parameters

    const evVal = lastBacktestParams.valueThreshold || '1.05';

    const minO = lastBacktestParams.minOdds || 1.0;

    const maxO = lastBacktestParams.maxOdds || 50.0;

    const suggestedName = `Otimizada (EV: ${evVal} | Odds: ${minO.toFixed(2)}-${maxO.toFixed(2)})`;

    

    document.getElementById('save-strategy-name').value = suggestedName;

    document.getElementById('save-strategy-name').focus();

}



function closeSaveStrategyModal() {

    document.getElementById('save-strategy-modal').style.display = 'none';

}



async function submitSaveStrategy() {

    const nameInput = document.getElementById('save-strategy-name').value.trim();

    const finalName = nameInput || "Estratégia " + new Date().toLocaleDateString('pt-BR');

    

    const payload = {

        name: finalName,

        params: lastBacktestParams,

        summary: lastBacktestSummary.summary

    };



    try {

        const res = await fetch(`${API_BASE_URL}/api/history`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(payload)

        });

        

        if (!res.ok) throw new Error("Erro ao salvar estratégia.");

        

        showToast("Estratégia salva com sucesso no Histórico!", "success");

        closeSaveStrategyModal();

        loadHistoryTab(); // Refresh se já estiver carregado

    } catch (err) {

        console.error(err);

        showToast(err.message, "error");

    }

}



async function loadHistoryTab() {

    const grid = document.getElementById('history-grid');

    const emptyState = document.getElementById('history-empty');

    

    grid.innerHTML = '<div style="text-align:center; grid-column: 1/-1;"><div class="loading-spinner"></div> Carregando histórico...</div>';

    emptyState.style.display = 'none';

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/history`);

        const history = await res.json();

        

        if (!history || history.length === 0) {

            grid.innerHTML = '';

            emptyState.style.display = 'block';

            return;

        }

        

        grid.innerHTML = '';

        

        history.forEach(item => {

            const dateStr = new Date(item.created_at).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });

            const s = item.summary || {};

            const p = item.params || {};

            

            const card = document.createElement('div');

            card.className = 'eval-card glassmorphism';

            card.style.borderLeft = '4px solid var(--primary)';

            card.style.display = 'flex';

            card.style.flexDirection = 'column';

            card.style.justifyContent = 'space-between';

            

            // Leagues format

            let leaguesTxt = "Todas";

            if (p.leagues && p.leagues.length > 0) {

                leaguesTxt = p.leagues.length > 3 ? `${p.leagues.slice(0,3).join(', ')} e +${p.leagues.length - 3}` : p.leagues.join(', ');

            }

            

            card.innerHTML = `

                <div>

                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 15px;">

                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" class="portfolio-checkbox" value="${item.id}" style="width: 18px; height: 18px; cursor: pointer;">
                            <h4 style="margin: 0; color: var(--text-primary); font-size: 16px;">${item.name}</h4>
                        </div>

                        <span style="font-size: 12px; color: var(--text-muted); background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 4px;">${dateStr}</span>

                    </div>

                    

                    <div style="margin-bottom: 15px; font-size: 13px; color: var(--text-secondary);">

                        <div style="margin-bottom: 4px;"><strong>Mercado:</strong> <span style="color:var(--info);">${p.market || 'Desconhecido'}</span></div>

                        <div style="margin-bottom: 4px;"><strong>Ligas:</strong> ${leaguesTxt}</div>

                        <div><strong>Odds:</strong> ${p.minOdds} a ${p.maxOdds}</div>

                    </div>

                    

                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px;">

                        <div>

                            <div style="font-size: 11px; color: var(--text-muted);">Win Rate</div>

                            <div style="font-size: 14px; font-weight: bold; color: ${s.win_rate >= 50 ? 'var(--success)' : 'var(--warning)'};">${s.win_rate !== undefined ? s.win_rate.toFixed(1) + '%' : '--'}</div>

                        </div>

                        <div>

                            <div style="font-size: 11px; color: var(--text-muted);">Lucro</div>

                            <div style="font-size: 14px; font-weight: bold; color: ${s.net_profit >= 0 ? 'var(--success)' : 'var(--danger)'};">$${s.net_profit !== undefined ? s.net_profit.toFixed(2) : '--'}</div>

                        </div>

                        <div>

                            <div style="font-size: 11px; color: var(--text-muted);">ROI</div>

                            <div style="font-size: 14px; font-weight: bold; color: ${s.roi >= 0 ? 'var(--success)' : 'var(--danger)'};">${s.roi !== undefined ? s.roi.toFixed(2) + '%' : '--'}</div>

                        </div>

                        <div>

                            <div style="font-size: 11px; color: var(--text-muted);">Sharpe</div>

                            <div style="font-size: 14px; font-weight: bold; color: ${s.sharpe_ratio >= 1 ? 'var(--success)' : 'var(--text-primary)'};">${s.sharpe_ratio !== undefined ? s.sharpe_ratio.toFixed(2) : '--'}</div>

                        </div>

                    </div>

                </div>

                

                <div style="display: flex; gap: 10px; margin-top: auto;">

                    <button class="btn-clear" onclick="deleteHistoryStrategy('${item.id}')" style="flex: 1; justify-content: center; color: var(--danger); border-color: rgba(239, 68, 68, 0.2);"><i class="fa-solid fa-trash-can"></i> Excluir</button>

                    <button class="btn-scanner" onclick='reloadStrategy(${JSON.stringify(p).replace(/'/g, "&#39;")})' style="flex: 1; justify-content: center;"><i class="fa-solid fa-play"></i> Carregar</button>

                </div>

            `;

            grid.appendChild(card);

        });

        

    } catch (err) {

        console.error(err);

        grid.innerHTML = `<div style="color: var(--danger); padding: 20px;">Erro ao carregar o histórico: ${err.message}</div>`;

    }

}



async function deleteHistoryStrategy(id) {

    if (!confirm("Tem certeza que deseja excluir esta estratégia salva?")) return;

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/history/${id}`, { method: 'DELETE' });

        if (!res.ok) throw new Error("Falha ao excluir.");

        

        showToast("Estratégia excluída.", "success");

        loadHistoryTab();

    } catch (err) {

        showToast(err.message, "error");

    }

}



function reloadStrategy(params) {

    if (!params) return;

    

    // Switch to Laboratory Tab

    switchTab('tab-laboratory');

    

    // Fill basic fields

    if (params.market) {

        document.querySelectorAll('input[name="market-group"]').forEach(cb => {

            cb.checked = (cb.value === params.market);

        });

    }

    

    if (params.minOdds) document.getElementById('min-odds').value = params.minOdds;

    if (params.maxOdds) document.getElementById('max-odds').value = params.maxOdds;

    

    if (params.startDate) document.getElementById('start-date').value = params.startDate;

    if (params.endDate) document.getElementById('end-date').value = params.endDate;

    

    if (params.leagues && Array.isArray(params.leagues)) {

        // Uncheck all first

        document.querySelectorAll('input[name="league-group"]').forEach(cb => cb.checked = false);

        // Check saved

        params.leagues.forEach(code => {

            const cb = document.getElementById(`league-${code}`);

            if (cb) cb.checked = true;

        });

    }

    

    // Run backtest

    showToast("Carregando estratégia...", "info");

    setTimeout(() => {

        runBacktest();

    }, 500);

}







// --- Steam Moves Radar ---
async function runSteamScan() {
    try {
        const tableContainer = document.getElementById('steam-table-container');
        const overlay = document.getElementById('steam-loading-overlay');
        
        // Pegar filtros
        const leagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        const startDate = document.getElementById('start-date').value;
        const endDate = document.getElementById('end-date').value;
        const markets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);
        const minDropPct = parseFloat(document.getElementById('val-drop-pct').value || 5.0);
        const stakeValue = parseFloat(document.getElementById('stake-value').value || 10.0);
        
        if (leagues.length === 0) {
            alert("Por favor, selecione pelo menos uma liga para o Radar de Smart Money.");
            return;
        }

        if (window.currentDataSource === 'futpython') {
            alert("O Backtest de Queda de Odds (Modo Laboratório) requer dados históricos de abertura e fechamento (Max/Avg/Pinnacle) para detectar quedas de cotações.\n\nEsses dados estão disponíveis apenas na base de dados Padrão Global (Football-Data).\n\nA base da FutPythonTrader possui apenas as odds finais. Use o 'Radar Ao Vivo' (abaixo) para monitorar as quedas do dia em tempo real!");
            return;
        }
        
        tableContainer.innerHTML = '';
        overlay.style.display = 'block';
    } catch (e) {
        alert("Erro no código do botão: " + e.message);
        return;
    }
    
    const tableContainer = document.getElementById('steam-table-container');
    const overlay = document.getElementById('steam-loading-overlay');
    const leagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;
    const markets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);
    const minDropPct = parseFloat(document.getElementById('val-drop-pct').value || 5.0);
    const stakeValue = parseFloat(document.getElementById('stake-value').value || 10.0);

    
    try {
        const response = await fetch(`${API_BASE_URL}/api/scan_steam_moves`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                leagues: leagues,
                startDate: startDate,
                endDate: endDate,
                markets: markets.length > 0 ? markets : ['home', 'away', 'draw'],
                minDropPct: minDropPct,
                stakeValue: stakeValue,
                data_source: window.currentDataSource,
                futpython_api_key: window.futpythonApiKey
            })
        });
        
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Erro na API de Steam Moves");
        
        renderSteamTable(data.scan_results || []);
    } catch (err) {
        tableContainer.innerHTML = `<div style="padding:20px; color:var(--danger); text-align:center;">Erro: ${err.message}</div>`;
    } finally {
        overlay.style.display = 'none';
    }
}

function clearSteamScan() {
    document.getElementById('steam-table-container').innerHTML = '';
}

function renderSteamTable(results) {
    const container = document.getElementById('steam-table-container');
    if (!results || results.length === 0) {
        container.innerHTML = `<div class="info-alert" style="padding: 20px; text-align: center; color: var(--text-muted);">
            <i class="fa-solid fa-satellite-dish" style="font-size: 24px; margin-bottom: 10px;"></i>
            <p>Nenhum Steam Move detectado com os filtros atuais.</p>
        </div>`;
        return;
    }
    
    // Sort by profit descending
    results.sort((a, b) => b.net_profit - a.net_profit);
    
    let html = `
        <table class="radar-smart-table" style="width: 100%; margin-top: 15px;">
            <thead>
                <tr>
                    <th style="text-align: left;">Nicho</th>
                    <th>Apostas Feitas</th>
                    <th>Drop Médio (%)</th>
                    <th>Confiança</th>
                    <th>Taxa de Acerto</th>
                    <th>ROI</th>
                    <th>Lucro Líquido</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    results.forEach(r => {
        const isProfit = r.net_profit > 0;
        const codeParts = r.code.split('|');
        const leagueName = (window.AVAILABLE_LEAGUES && window.AVAILABLE_LEAGUES.find(l => l.code === codeParts[0])) ? 
            window.AVAILABLE_LEAGUES.find(l => l.code === codeParts[0]).name : codeParts[0];
            
        let rowGlowClass = '';
        if (r.confidence_level === 'Alta') rowGlowClass = 'radar-row-glow-alta';
        else if (r.confidence_level === 'Média') rowGlowClass = 'radar-row-glow-media';
        else rowGlowClass = 'radar-row-glow-baixa';
            
        let confBorderColor = 'rgba(255, 255, 255, 0.1)';
        let confGlowColor = 'rgba(255, 255, 255, 0.02)';
        let confTextColor = '#9ca3af';
        let confIcon = 'fa-circle-question';
        
        if (r.confidence_level === 'Alta') {
            confBorderColor = '#10b981';
            confGlowColor = 'rgba(16, 185, 129, 0.05)';
            confTextColor = '#10b981';
            confIcon = 'fa-circle-check';
        } else if (r.confidence_level === 'Média') {
            confBorderColor = '#f59e0b';
            confGlowColor = 'rgba(245, 158, 11, 0.05)';
            confTextColor = '#f59e0b';
            confIcon = 'fa-circle-exclamation';
        } else if (r.confidence_level === 'Baixa') {
            confBorderColor = '#ef4444';
            confGlowColor = 'rgba(239, 68, 68, 0.05)';
            confTextColor = '#ef4444';
            confIcon = 'fa-triangle-exclamation';
        }
        
        const confidenceHTML = `
            <div style="display: inline-flex; flex-direction: column; align-items: center; justify-content: center; padding: 6px 14px; border-radius: 12px; border: 1px solid ${confBorderColor}; background: ${confGlowColor}; box-shadow: 0 0 10px ${confGlowColor}; min-width: 140px; box-sizing: border-box;">
                <div style="display: flex; align-items: center; gap: 6px; font-weight: 800; font-size: 11px; color: ${confTextColor}; text-transform: uppercase; letter-spacing: 0.5px;">
                    <i class="fa-solid ${confIcon}"></i>
                    <span>${r.confidence_level || 'BAIXA'}</span>
                </div>
                <div style="font-size: 9px; color: var(--text-muted); font-weight: bold; margin-top: 3px;">
                    Score: ${(r.confidence_score || 0).toFixed(0)}% (${r.confidence_level || 'Baixa'})
                </div>
            </div>
        `;
            
        html += `
            <tr class="${rowGlowClass}">
                <td style="font-weight: 500; font-size: 13px; text-align: left;">
                    <span style="color: var(--text-secondary);">${leagueName}</span>
                    <span style="color: var(--text-muted); margin: 0 5px;"><i class="fa-solid fa-angle-right" style="font-size: 10px;"></i></span>
                    <span style="color: #67e8f9; font-weight: bold;">${r.market_name}</span>
                </td>
                <td style="font-family: var(--font-mono); color: var(--text-primary);">
                    ${r.total_bets}
                </td>
                <td style="color: #f87171; font-family: var(--font-mono); font-weight: bold;">
                    -${r.avg_drop.toFixed(1)}% <span style="font-size: 14px; margin-left: 2px;">&darr;</span>
                </td>
                <td>
                    ${confidenceHTML}
                </td>
                <td style="color: var(--text-secondary);">
                    ${r.win_rate.toFixed(1)}%
                </td>
                <td style="font-family: var(--font-mono); color: ${isProfit ? 'var(--success)' : 'var(--danger)'};">
                    ${r.roi > 0 ? '+' : ''}${r.roi.toFixed(1)}%
                </td>
                <td style="font-family: var(--font-mono); color: ${isProfit ? 'var(--success)' : 'var(--danger)'}; font-weight: bold;">
                    $${r.net_profit.toFixed(2)}
                </td>
            </tr>
        `;
    });
    
    html += `
            </tbody>
        </table>
    `;
    
    container.innerHTML = html;
}

// ============================================
// ARBITRAGE SCANNER LOGIC
// ============================================
let currentArbData = null;

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
        
        tbody.innerHTML = '';
        if (!data || data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #6b7280;">Nenhuma surebet encontrada nas odds atuais. Tente novamente mais tarde.</td></tr>';
            return;
        }
        
        data.forEach((item, idx) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${item.match}</td>
                <td>${item.date}</td>
                <td>${item.market}</td>
                <td style="color: #34d399; font-weight: bold;">+${item.profit_margin}%</td>
                <td><button class="btn-primary" onclick='openArbitrageCalc(${JSON.stringify(item)})'><i class="fa-solid fa-calculator"></i> Calcular Stake</button></td>
            `;
            tbody.appendChild(tr);
        });
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
    const profit = total * (currentArbData.profit_margin / 100);
    profitEl.innerText = `$${profit.toFixed(2)}`;
    
    Object.keys(currentArbData.odds).forEach(outcome => {
        const odd = currentArbData.odds[outcome];
        const prob = 1 / odd;
        const stake = total * (prob / implied);
        const returnVal = stake * odd;
        const bookieName = currentArbData.bookmakers ? currentArbData.bookmakers[outcome] : 'Desconhecida';
        const labelName = (currentArbData.labels && currentArbData.labels[outcome]) ? currentArbData.labels[outcome] : outcome;
        
        distList.innerHTML += `
            <div style="display: flex; justify-content: space-between; padding: 10px; background: rgba(255,255,255,0.05); border-radius: 6px;">
                <div><span style="color: #9ca3af">Seleção:</span> <b>${labelName}</b> <span style="color: #3b82f6; margin-left: 5px;">@${odd.toFixed(2)}</span> <span style="font-size: 11px; background: #374151; padding: 2px 6px; border-radius: 4px; margin-left: 8px;">🏠 ${bookieName}</span></div>
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


// Bookie Filter Local Storage Logic
document.addEventListener('DOMContentLoaded', () => {
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
});

window.selectAllLeagues = function(check) {
    document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]').forEach(cb => {
        cb.checked = check;
    });
};


let currentSteamMode = 'lab';

window.toggleSteamMode = function(mode) {
    currentSteamMode = mode;
    const btnLab = document.getElementById('btn-mode-lab');
    const btnLive = document.getElementById('btn-mode-live');
    const labTable = document.getElementById('steam-table-container');
    const liveTable = document.getElementById('steam-live-table-container');
    
    // Elementos da barra de navegação decorativa do mockup
    const tabDashboard = document.getElementById('radar-tab-nav-dashboard');
    const tabDrops = document.getElementById('radar-tab-nav-drops');
    
    if (mode === 'lab') {
        if (btnLab) {
            btnLab.classList.add('active');
            btnLab.style.background = 'rgba(16, 185, 129, 0.15)';
            btnLab.style.color = '#34d399';
            btnLab.style.border = '1px solid rgba(16, 185, 129, 0.3)';
        }
        if (btnLive) {
            btnLive.classList.remove('active');
            btnLive.style.background = 'transparent';
            btnLive.style.color = 'var(--text-secondary)';
            btnLive.style.border = '1px solid transparent';
        }
        
        if (tabDashboard) tabDashboard.classList.add('active');
        if (tabDrops) tabDrops.classList.remove('active');
        
        if (labTable) labTable.style.display = 'block';
        if (liveTable) liveTable.style.display = 'none';
        
        const btnScan = document.getElementById('btn-scan-steam');
        if (btnScan) btnScan.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest';
    } else {
        if (btnLive) {
            btnLive.classList.add('active');
            btnLive.style.background = 'rgba(16, 185, 129, 0.15)';
            btnLive.style.color = '#34d399';
            btnLive.style.border = '1px solid rgba(16, 185, 129, 0.3)';
        }
        if (btnLab) {
            btnLab.classList.remove('active');
            btnLab.style.background = 'transparent';
            btnLab.style.color = 'var(--text-secondary)';
            btnLab.style.border = '1px solid transparent';
        }
        
        if (tabDrops) tabDrops.classList.add('active');
        if (tabDashboard) tabDashboard.classList.remove('active');
        
        if (labTable) labTable.style.display = 'none';
        if (liveTable) liveTable.style.display = 'block';
        
        const btnScan = document.getElementById('btn-scan-steam');
        if (btnScan) btnScan.innerHTML = '<i class="fa-solid fa-radar"></i> Rastrear Quedas Ao Vivo';
    }
};

window.switchRadarTab = function(mode) {
    window.toggleSteamMode(mode);
};

window.showRadarInsights = function() {
    alert("💡 INSIGHTS ESTRATÉGICOS DO RADAR SMART MONEY:\n\n" +
          "1. Ligas de Tier Alta (ex: Premier League, La Liga, Brasileirão Série A) possuem volumes de negociação gigantescos. Drops nessas ligas representam a entrada de sindicatos asiáticos e possuem ALTÍSSIMA CONFIANÇA.\n\n" +
          "2. Evite seguir drops de odds em ligas de baixa liquidez (Tier Baixa) quando o score de confiança for menor que 45%, pois estes mercados sofrem manipulações de pequenos apostadores locais (ruído).\n\n" +
          "3. O mercado de 'Match Odds' (1X2) e 'Goals (O2.5/U2.5)' são os preferidos dos robôs institucionais. Fique atento a quedas simultâneas nestas linhas.");
};

window.runLiveSteamScan = async function() {
    try {
        const tbody = document.querySelector('#steam-live-table tbody');
        const overlay = document.getElementById('steam-loading-overlay');
        
        const leagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        const markets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);
        const minDropPct = parseFloat(document.getElementById('val-drop-pct').value || 5.0);
        
        if (markets.length === 0) {
            alert("Por favor, selecione pelo menos um mercado.");
            return;
        }

        overlay.style.display = 'block';
        document.getElementById('steam-live-table-container').style.display = 'none';
        
        const reqBody = {
            minDropPct: minDropPct,
            markets: markets,
            leagues: leagues
        };
        
        const response = await fetch(`${API_BASE_URL}/api/live_steam_moves`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(reqBody)
        });
        
        if (!response.ok) {
            throw new Error(`Erro na API: ${response.status}`);
        }
        
        const data = await response.json();
        
        overlay.style.display = 'none';
        document.getElementById('steam-live-table-container').style.display = 'block';
        tbody.innerHTML = '';
        
        if (!data.scan_results || data.scan_results.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #6b7280; padding: 20px;">Nenhuma queda significativa detectada nas odds ao vivo neste momento. O robô atualiza a cada 30 minutos.</td></tr>';
            return;
        }
        
        data.scan_results.forEach((item, idx) => {
            const tr = document.createElement('tr');
            
            if (item.confidence_level === 'Alta') {
                tr.className = 'radar-row-glow-alta';
            } else if (item.confidence_level === 'Média') {
                tr.className = 'radar-row-glow-media';
            } else {
                tr.className = 'radar-row-glow-baixa';
            }
            
            let confBorderColor = 'rgba(255, 255, 255, 0.1)';
            let confGlowColor = 'rgba(255, 255, 255, 0.02)';
            let confTextColor = '#9ca3af';
            let confIcon = 'fa-circle-question';
            
            if (item.confidence_level === 'Alta') {
                confBorderColor = '#10b981';
                confGlowColor = 'rgba(16, 185, 129, 0.05)';
                confTextColor = '#10b981';
                confIcon = 'fa-circle-check';
            } else if (item.confidence_level === 'Média') {
                confBorderColor = '#f59e0b';
                confGlowColor = 'rgba(245, 158, 11, 0.05)';
                confTextColor = '#f59e0b';
                confIcon = 'fa-circle-exclamation';
            } else if (item.confidence_level === 'Baixa') {
                confBorderColor = '#ef4444';
                confGlowColor = 'rgba(239, 68, 68, 0.05)';
                confTextColor = '#ef4444';
                confIcon = 'fa-triangle-exclamation';
            }

            const confidenceHTML = `
                <div style="display: inline-flex; flex-direction: column; align-items: center; justify-content: center; padding: 6px 14px; border-radius: 12px; border: 1px solid ${confBorderColor}; background: ${confGlowColor}; box-shadow: 0 0 10px ${confGlowColor}; min-width: 140px; box-sizing: border-box;">
                    <div style="display: flex; align-items: center; gap: 6px; font-weight: 800; font-size: 11px; color: ${confTextColor}; text-transform: uppercase; letter-spacing: 0.5px;">
                        <i class="fa-solid ${confIcon}"></i>
                        <span>${item.confidence_level || 'BAIXA'}</span>
                    </div>
                    <div style="font-size: 9px; color: var(--text-muted); font-weight: bold; margin-top: 3px;">
                        Score: ${(item.confidence_score || 0).toFixed(0)}% (${item.confidence_level || 'Baixa'})
                    </div>
                </div>
            `;

            let indexCell = `<span style="color: var(--text-muted); font-size: 13px; font-weight: bold; margin-right: 12px; font-family: var(--font-mono);">${idx + 1}.</span>`;
            const teams = item.match.split(' vs ');
            const home = teams[0] || 'Desconhecido';
            const away = teams[1] || 'Desconhecido';
            
            const matchHTML = `
                <div style="display: flex; align-items: center;">
                    ${indexCell}
                    <div style="display: flex; flex-direction: column; gap: 3px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <i class="fa-solid fa-shirt" style="font-size: 11px; color: var(--text-muted);"></i>
                            <span style="font-weight: 700; color: var(--text-primary); font-size: 13px;">${home}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <i class="fa-solid fa-shirt" style="font-size: 11px; color: var(--text-muted); opacity: 0.6;"></i>
                            <span style="font-weight: 700; color: var(--text-secondary); font-size: 13px;">${away}</span>
                        </div>
                        <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px; display: flex; align-items: center; gap: 4px;">
                            <i class="fa-regular fa-clock" style="font-size: 10px;"></i> ${item.date}
                        </div>
                    </div>
                </div>
            `;

            let bookieHTML = '';
            const bName = item.bookmaker.toLowerCase();
            if (bName.includes('365')) {
                bookieHTML = `<span class="radar-bookmaker-badge radar-bookie-bet365" style="font-family: 'Outfit', sans-serif; font-style: italic; font-weight: 900; letter-spacing: -0.5px;"><span style="color: #ffffff;">bet</span><span style="color: #ffdf1b;">365</span></span>`;
            } else if (bName.includes('pinnacle')) {
                bookieHTML = `<span class="radar-bookmaker-badge radar-bookie-pinnacle" style="font-family: 'Outfit', sans-serif; font-weight: 900; letter-spacing: 0.5px;"><span style="color: #ff7020;">PIN</span><span style="color: #ffffff;">NACLE</span></span>`;
            } else if (bName.includes('betfair')) {
                bookieHTML = `<span class="radar-bookmaker-badge radar-bookie-betfair" style="font-family: 'Outfit', sans-serif; font-weight: 900; letter-spacing: -0.5px;"><span style="color: #ffbe00;">bet</span><span style="color: #ffffff;">fair</span></span>`;
            } else {
                bookieHTML = `<span class="radar-bookmaker-badge radar-bookie-neutral">${item.bookmaker}</span>`;
            }
            
            const marketHTML = `<span style="color: #67e8f9; font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">${item.market}</span>`;
            const openingHTML = `<span style="color: var(--text-secondary); font-family: var(--font-mono); font-size: 13px;">@${item.opening_odd.toFixed(2)}</span>`;
            const currentHTML = `<span class="radar-odd-badge-current">@${item.current_odd.toFixed(2)}</span>`;
            const dropHTML = `
                <span class="radar-drop-pct-red">
                    ${item.drop_pct.toFixed(0)}% <span style="font-size: 16px; margin-left: 2px;">&darr;</span>
                </span>
            `;

            tr.innerHTML = `
                <td>${matchHTML}</td>
                <td>${bookieHTML}</td>
                <td>${marketHTML}</td>
                <td>${openingHTML}</td>
                <td>${currentHTML}</td>
                <td>${dropHTML}</td>
                <td>${confidenceHTML}</td>
            `;
            tbody.appendChild(tr);
        });
        
    } catch (e) {
        console.error(e);
        document.getElementById('steam-loading-overlay').style.display = 'none';
        document.getElementById('steam-live-table-container').style.display = 'block';
        document.querySelector('#steam-live-table tbody').innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 20px;">Erro ao buscar dados ao vivo.</td></tr>`;
    }
};

// Hook into existing runSteamScan
const originalRunSteamScan = window.runSteamScan;
window.runSteamScan = function() {
    if (currentSteamMode === 'live') {
        runLiveSteamScan();
    } else {
        originalRunSteamScan();
    }
};


window.runBacktest = async function() {
    // --- Portfolio Fix: Restore standard UI panels ---
    document.getElementById('portfolio-results-panel').style.display = 'none';
    document.getElementById('standard-metrics-grid').style.display = 'grid';
    const mainCharts = document.querySelector('.main-charts');
    if (mainCharts) mainCharts.style.display = 'block';
    const stakingPanel = document.getElementById('staking-comparison-panel');
    if (stakingPanel) stakingPanel.style.display = 'block';
    const quartilesPanel = document.getElementById('quartiles-panel');
    if (quartilesPanel) quartilesPanel.style.display = 'block';
    const resultsTableSection = document.querySelector('.results-table-section');
    if (resultsTableSection) resultsTableSection.style.display = 'block';
    const chartCards = document.querySelectorAll('.chart-card');
    chartCards.forEach(c => {
        if(c.parentElement && c.parentElement.className === 'charts-grid') {
            c.closest('div[style*="display: grid"]').style.display = 'grid';
        }
    });

    const btn = document.getElementById('btn-run-backtest');
    if(btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Rodando...';

    const leagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;
    const markets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);
    
    const valThreshold = parseFloat(document.getElementById('val-threshold').value) || 1.0;
    const initialBankroll = parseFloat(document.getElementById('init-bankroll') ? document.getElementById('init-bankroll').value : 1000.0) || 1000.0;
    const stakeRule = document.getElementById('stake-rule').value;
    const stakeValue = stakeRule === 'kelly' ? parseFloat(document.getElementById('kelly-fraction').value) || 0.25 : parseFloat(document.getElementById('stake-value').value) || 10.0;
    const oddsSource = document.getElementById('odds-source').value || 'B365';
    const minOdds = parseFloat(document.getElementById('min-odds').value) || 1.0;
    const maxOdds = parseFloat(document.getElementById('max-odds').value) || 50.0;
    const exchangeCommission = parseFloat(document.getElementById('exchange-commission') ? document.getElementById('exchange-commission').value : 0.0) || 0.0;
    
    const oosToggle = document.getElementById('oos-toggle');
    const oos = oosToggle ? oosToggle.checked : false;

    const useMLToggle = document.getElementById('use-ml-toggle');
    const useMl = useMLToggle ? useMLToggle.checked : false;

    const minOddsH = document.getElementById('min-odds-h') && document.getElementById('min-odds-h').value ? parseFloat(document.getElementById('min-odds-h').value) : null;
    const maxOddsH = document.getElementById('max-odds-h') && document.getElementById('max-odds-h').value ? parseFloat(document.getElementById('max-odds-h').value) : null;
    const minOddsD = document.getElementById('min-odds-d') && document.getElementById('min-odds-d').value ? parseFloat(document.getElementById('min-odds-d').value) : null;
    const maxOddsD = document.getElementById('max-odds-d') && document.getElementById('max-odds-d').value ? parseFloat(document.getElementById('max-odds-d').value) : null;
    const minOddsA = document.getElementById('min-odds-a') && document.getElementById('min-odds-a').value ? parseFloat(document.getElementById('min-odds-a').value) : null;
    const maxOddsA = document.getElementById('max-odds-a') && document.getElementById('max-odds-a').value ? parseFloat(document.getElementById('max-odds-a').value) : null;
    const minOddsOver25 = document.getElementById('min-odds-over25') && document.getElementById('min-odds-over25').value ? parseFloat(document.getElementById('min-odds-over25').value) : null;
    const maxOddsOver25 = document.getElementById('max-odds-over25') && document.getElementById('max-odds-over25').value ? parseFloat(document.getElementById('max-odds-over25').value) : null;
    const minOddsUnder25 = document.getElementById('min-odds-under25') && document.getElementById('min-odds-under25').value ? parseFloat(document.getElementById('min-odds-under25').value) : null;
    const maxOddsUnder25 = document.getElementById('max-odds-under25') && document.getElementById('max-odds-under25').value ? parseFloat(document.getElementById('max-odds-under25').value) : null;

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
            use_ml: useMl,
            data_source: window.currentDataSource,
            futpython_api_key: window.futpythonApiKey,
            minOddsH: minOddsH,
            maxOddsH: maxOddsH,
            minOddsD: minOddsD,
            maxOddsD: maxOddsD,
            minOddsA: minOddsA,
            maxOddsA: maxOddsA,
            minOddsOver25: minOddsOver25,
            maxOddsOver25: maxOddsOver25,
            minOddsUnder25: minOddsUnder25,
            maxOddsUnder25: maxOddsUnder25
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
            
            const btnSave = document.getElementById('btn-save-strategy');
            if(btnSave) btnSave.style.display = 'inline-block';

            const summary = data.summary;
            if(document.getElementById('metric-net-profit')) document.getElementById('metric-net-profit').innerText = '$' + summary.net_profit.toFixed(2);
            if(document.getElementById('metric-profit-stakes')) document.getElementById('metric-profit-stakes').innerText = (summary.profit_in_stakes > 0 ? '+' : '') + summary.profit_in_stakes.toFixed(2) + ' st.';
            if(document.getElementById('metric-roi')) document.getElementById('metric-roi').innerText = summary.roi.toFixed(1) + '%';
            if(document.getElementById('metric-win-rate')) document.getElementById('metric-win-rate').innerText = summary.win_rate.toFixed(1) + '%';
            if(document.getElementById('metric-avg-odds')) document.getElementById('metric-avg-odds').innerText = summary.avg_odds.toFixed(2);
            if(document.getElementById('metric-max-drawdown')) document.getElementById('metric-max-drawdown').innerText = (summary.max_drawdown || 0).toFixed(1) + '%';
            if(document.getElementById('metric-drawdown')) {
                document.getElementById('metric-drawdown').innerText = (summary.max_drawdown || 0).toFixed(1) + '%';
                const ddDurationEl = document.getElementById('metric-dd-duration');
                if (ddDurationEl) {
                    const dur = summary.max_dd_duration || 0;
                    ddDurationEl.innerText = 'Recup: ' + dur + ' aposta' + (dur !== 1 ? 's' : '');
                }
            }
            if(document.getElementById('metric-total-bets')) document.getElementById('metric-total-bets').innerText = summary.total_bets;
            if(document.getElementById('metric-final-bankroll')) document.getElementById('metric-final-bankroll').innerText = '$' + summary.final_bankroll.toFixed(2);
            if(document.getElementById('metric-sharpe')) document.getElementById('metric-sharpe').innerText = (summary.sharpe_ratio || 0).toFixed(2);
            if(document.getElementById('metric-sortino')) document.getElementById('metric-sortino').innerText = (summary.sortino_ratio || 0).toFixed(2);
            if(document.getElementById('metric-skewness')) document.getElementById('metric-skewness').innerText = (summary.skewness || 0).toFixed(2);
            if(document.getElementById('metric-consec-wins')) document.getElementById('metric-consec-wins').innerText = summary.max_consec_wins || 0;
            if(document.getElementById('metric-consec-losses')) document.getElementById('metric-consec-losses').innerText = summary.max_consec_losses || 0;
            if(document.getElementById('metric-clv')) document.getElementById('metric-clv').innerText = summary.avg_clv != null ? ((summary.avg_clv >= 0 ? '+' : '') + summary.avg_clv.toFixed(1) + '%') : 'N/A';
            if(document.getElementById('metric-bcl')) document.getElementById('metric-bcl').innerText = summary.bcl_percent != null ? (summary.bcl_percent.toFixed(1) + '%') : 'N/A';
            
            const bets = data.bets || [];
            const dates = bets.map((b, i) => b.date ? b.date.substring(0, 10) : i);
            const bankrolls = data.equity_curve ? data.equity_curve.map(e => e.bankroll || e.Bankroll || e) : [];
            const fixedData = data.equity_curve_fixed || [];
            const propData = data.equity_curve_proportional || [];
            const kellyData = data.equity_curve_kelly || [];
            const leagueStats = data.league_stats || [];
            const monthlyStats = data.monthly_stats || [];
            const oddsStats = data.odds_stats || [];
            const optimizedData = data.portfolio_optimization || null;

            if(typeof updateCharts === 'function') {
                updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueStats, monthlyStats, oddsStats, optimizedData);
            }

            if (typeof window.renderLaboratoryPanels === 'function') {
                window.renderLaboratoryPanels(data);
            }

            if (typeof populateBetsTable === 'function') {
                allBets = data.bets || [];
                populateBetsTable(allBets);
            }

            if (typeof autoUpdateSchedulerFromBacktest === 'function') {
                autoUpdateSchedulerFromBacktest(payload);
            }

            const banner = document.getElementById('active-strategy-banner');
            if (banner) banner.style.display = 'flex';
            const leagueNames = leagues.map(code => {
                const lbl = document.querySelector(`label[for="league-${code}"]`) || document.querySelector(`label:has(input[value="${code}"])`);
                return lbl ? lbl.innerText.trim() : code;
            }).join(', ');
            
            const marketNames = markets.map(code => {
                const lbl = document.querySelector(`label:has(input[value="${code}"])`);
                return lbl ? lbl.innerText.trim() : code;
            }).join(', ');
            
            if(document.getElementById('active-leagues-text')) document.getElementById('active-leagues-text').innerText = leagueNames || 'N/A';
            if(document.getElementById('active-market-text')) document.getElementById('active-market-text').innerText = marketNames || 'N/A';
            if(document.getElementById('active-odds-text')) document.getElementById('active-odds-text').innerText = `${minOdds.toFixed(2)} - ${maxOdds.toFixed(2)}`;
            if(document.getElementById('active-ev-text')) document.getElementById('active-ev-text').innerText = valThreshold.toFixed(2);

            const btnExport = document.getElementById('btn-export-backtest');
            if (btnExport) btnExport.style.display = 'inline-flex';

            if(btn) btn.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest';
            if (typeof showToast === 'function') showToast("Backtest concluído!", "success");

        } else {
            alert(data.error || data.detail || "Erro ao executar backtest.");
            if(btn) btn.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest';
        }
    } catch(err) {
        console.error("Backtest error:", err);
        alert("Erro JS: " + err.message + "\nStack: " + err.stack);
        if(btn) btn.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest';
    }
};

window.renderQuartiles = function(q) {
    const panel = document.getElementById('quartiles-panel');
    if (!panel) return;
    
    if (!q || !Array.isArray(q) || q.length < 4) {
        panel.style.display = 'none';
        return;
    }
    
    for (let i = 0; i < 4; i++) {
        const quart = q[i];
        const num = i + 1;
        
        const profitEl = document.getElementById(`q${num}-profit`);
        const stakesEl = document.getElementById(`q${num}-stakes`);
        const roiEl = document.getElementById(`q${num}-roi`);
        const winrateEl = document.getElementById(`q${num}-winrate`);
        const betsEl = document.getElementById(`q${num}-bets`);
        
        if (profitEl) {
            profitEl.textContent = (quart.profit >= 0 ? '+' : '') + '$' + quart.profit.toFixed(2);
            profitEl.style.color = quart.profit >= 0 ? 'var(--success)' : 'var(--danger)';
        }
        if (stakesEl) {
            stakesEl.textContent = quart.stakes.toFixed(2) + ' st.';
        }
        if (roiEl) {
            roiEl.textContent = (quart.roi >= 0 ? '+' : '') + quart.roi.toFixed(1) + '%';
            roiEl.style.color = quart.roi >= 0 ? 'var(--success)' : 'var(--danger)';
        }
        if (winrateEl) {
            winrateEl.textContent = quart.win_rate.toFixed(1) + '%';
        }
        if (betsEl) {
            betsEl.textContent = quart.total_bets;
        }
    }
    
    panel.style.display = 'block';
};





// [window.updateAiAnalysis removido — EQS agora usa renderEdgeQualityScore() com dados reais do backend]


// Global function to toggle groups
window.toggleGroup = function(groupEl) {
    let checkboxes = [];
    let el = groupEl.nextElementSibling;
    while (el && !el.classList.contains('multiselect-optgroup')) {
        if (el.tagName === 'LABEL' || el.classList.contains('multiselect-option-item')) {
            const cb = el.querySelector('input[type="checkbox"]');
            if (cb) checkboxes.push(cb);
        }
        el = el.nextElementSibling;
    }
    
    if (checkboxes.length > 0) {
        const allChecked = checkboxes.every(cb => cb.checked);
        checkboxes.forEach(cb => { 
            cb.checked = !allChecked; 
            cb.dispatchEvent(new Event('change', { bubbles: true }));
        });
        if(typeof onMarketSelectionChange === 'function') {
            onMarketSelectionChange();
        }
    }
};

let clusterChartInstance = null;

async function runClustering() {
    const leagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
    if (leagues.length < 3) {
        showToast("Selecione pelo menos 3 ligas para rodar a clusterização.", "warning");
        return;
    }
    
    const startDate = document.getElementById("start-date").value;
    const endDate = document.getElementById("end-date").value;
    const dataSource = document.getElementById("data-source-select").value;
    const futpythonKey = document.getElementById("futpython-api-key") ? document.getElementById("futpython-api-key").value : "";
    let nClusters = document.getElementById("cluster-count").value;
    nClusters = nClusters === "auto" ? null : parseInt(nClusters);
    
    document.getElementById("clustering-loading").style.display = "block";
    document.getElementById("clustering-results").style.display = "none";
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/cluster_leagues`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                leagues: leagues,
                startDate: startDate,
                endDate: endDate,
                data_source: dataSource,
                futpython_api_key: futpythonKey,
                n_clusters: nClusters
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || "Erro ao executar clusterização.");
        }
        
        renderClusterChart(data.points, data.clusters);
        renderClusterList(data.clusters);
        
        document.getElementById("clustering-loading").style.display = "none";
        document.getElementById("clustering-results").style.display = "block";
        
    } catch (error) {
        console.error(error);
        showToast(error.message, "error");
        document.getElementById("clustering-loading").style.display = "none";
    }
}

function renderClusterChart(points, clusters) {
    const ctx = document.getElementById('clusterChart').getContext('2d');
    
    if (clusterChartInstance) {
        clusterChartInstance.destroy();
    }
    
    // Paleta de cores premium
    const colors = [
        '#3b82f6', // Azul
        '#10b981', // Verde
        '#f59e0b', // Amarelo
        '#ef4444', // Vermelho
        '#8b5cf6', // Roxo
        '#ec4899', // Rosa
        '#06b6d4', // Ciano
    ];
    
    const datasets = clusters.map((c, i) => {
        const clusterPoints = points.filter(p => p.cluster === c.cluster_id);
        const color = colors[i % colors.length];
        
        return {
            label: `Grupo ${c.cluster_id + 1}`,
            data: clusterPoints.map(p => ({
                x: p.pca_x,
                y: p.pca_y,
                league: p.league,
                avg_goals: p.avg_goals,
                btts: p.btts_pct,
                win: p.home_win_pct
            })),
            backgroundColor: color,
            borderColor: color,
            borderWidth: 1,
            pointRadius: 6,
            pointHoverRadius: 9,
        };
    });
    
    clusterChartInstance = new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: { color: '#e5e7eb', font: { family: 'Inter', size: 12 } }
                },
                tooltip: {
                    backgroundColor: 'rgba(11, 14, 20, 0.95)',
                    titleColor: '#34d399',
                    bodyColor: '#e5e7eb',
                    borderColor: 'rgba(52, 211, 153, 0.2)',
                    borderWidth: 1,
                    padding: 12,
                    callbacks: {
                        label: function(context) {
                            const p = context.raw;
                            return [
                                `Liga: ${p.league}`,
                                `Gols/Jogo: ${p.avg_goals.toFixed(2)}`,
                                `Vitória Mandante: ${(p.win * 100).toFixed(1)}%`,
                                `Ambas Marcam: ${(p.btts * 100).toFixed(1)}%`
                            ];
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#9ca3af' },
                    title: { display: true, text: 'Componente Principal 1', color: '#6b7280' }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#9ca3af' },
                    title: { display: true, text: 'Componente Principal 2', color: '#6b7280' }
                }
            }
        }
    });
}

function renderClusterList(clusters) {
    const container = document.getElementById('cluster-list-container');
    container.innerHTML = '';
    
    const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4'];
    
    clusters.forEach((c, i) => {
        const color = colors[i % colors.length];
        
        const card = document.createElement('div');
        card.className = 'glassmorphism';
        card.style.padding = '15px';
        card.style.borderLeft = `4px solid ${color}`;
        
        let suggestedMarkets = "";
        let clusterProfile = "";
        
        if (c.avg_goals >= 2.75 || c.over25_pct >= 0.52) {
            clusterProfile = "Ligas de Gols (Over)";
            suggestedMarkets = "Over 2.5, Ambas Marcam (Sim), Over 0.5 HT";
        } else if (c.avg_goals <= 2.55 || c.over25_pct <= 0.46) {
            clusterProfile = "Ligas Truncadas (Under)";
            suggestedMarkets = "Under 2.5, Under 0.5 HT, Empate HT";
        } else {
            clusterProfile = "Ligas Equilibradas";
            suggestedMarkets = "Match Odds (Mandante/Visitante), Handicap Asiático";
        }
        
        if (c.home_win_pct >= 0.47) {
            suggestedMarkets += ", Back Mandante";
        } else if (c.home_win_pct <= 0.38) {
            suggestedMarkets += ", Dupla Chance Visitante";
        }

        const leaguesList = c.leagues.map(l => `<span style="display:inline-block; background:rgba(255,255,255,0.05); padding:2px 6px; border-radius:4px; margin:2px; font-size:11px;">${l}</span>`).join('');
        
        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h4 style="margin: 0; color: ${color}; font-size: 14px;">Grupo ${c.cluster_id + 1} (${c.count} ligas) - ${clusterProfile}</h4>
                <button type="button" onclick="copyClusterLeagues('${c.leagues.join(',')}')" class="btn-secondary" style="padding: 4px 8px; font-size: 10px;">
                    <i class="fa-solid fa-copy"></i> Copiar Ligas
                </button>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; margin-bottom: 10px; font-size: 11px; color: #9ca3af;">
                <div><i class="fa-solid fa-futbol"></i> Gols: ${c.avg_goals.toFixed(2)}</div>
                <div><i class="fa-solid fa-arrow-up"></i> Over 2.5: ${(c.over25_pct * 100).toFixed(0)}%</div>
                <div><i class="fa-solid fa-house"></i> Home Win: ${(c.home_win_pct * 100).toFixed(0)}%</div>
            </div>
            <div style="margin-bottom: 10px; padding: 6px; background: rgba(255, 255, 255, 0.05); border-left: 2px solid ${color}; font-size: 11px; color: #d1d5db; border-radius: 4px;">
                <strong style="color: ${color};"><i class="fa-solid fa-lightbulb"></i> Mercados Sugeridos para o Scanner:</strong> ${suggestedMarkets}
            </div>
            <div style="max-height: 100px; overflow-y: auto;">
                ${leaguesList}
            </div>
        `;
        
        container.appendChild(card);
    });
}

function copyClusterLeagues(leaguesStr) {
    const leagues = leaguesStr.split(',');
    
    // Uncheck all
    document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]').forEach(cb => {
        cb.checked = false;
    });
    
    // Check the ones in the cluster
    document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]').forEach(cb => {
        if (leagues.includes(cb.value)) {
            cb.checked = true;
        }
    });
    showToast(`${leagues.length} ligas do cluster selecionadas!`, "success");
}

// Cluster AI Alerts Config
async function loadClusterAiConfig() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/telegram/cluster_ai_config`);
        if (res.ok) {
            const config = await res.json();
            const el1 = document.getElementById("toggle-tg-pure-blood");
            const el2 = document.getElementById("toggle-tg-contrarian");
            const el3 = document.getElementById("toggle-tg-dna-shift");
            
            if (el1) el1.checked = config.pure_blood_enabled !== false;
            if (el2) el2.checked = config.contrarian_enabled !== false;
            if (el3) el3.checked = config.dna_shift_enabled !== false;
        }
    } catch (e) {
        console.error("Error loading cluster AI config:", e);
    }
}

async function saveClusterAiConfig() {
    const el1 = document.getElementById("toggle-tg-pure-blood");
    const el2 = document.getElementById("toggle-tg-contrarian");
    const el3 = document.getElementById("toggle-tg-dna-shift");
    
    if (!el1 || !el2 || !el3) return;
    
    const config = {
        enabled: el1.checked || el2.checked || el3.checked,
        pure_blood_enabled: el1.checked,
        contrarian_enabled: el2.checked,
        dna_shift_enabled: el3.checked
    };
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/telegram/cluster_ai_config`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
        if (res.ok) {
            showToast("Configuração de Alertas IA salva com sucesso!", "success");
        }
    } catch (e) {
        console.error("Error saving cluster AI config:", e);
    }
}

window.renderLaboratoryPanels = function(data) {
    const summary = data.summary || {};
    if(document.getElementById('metric-sharpe')) document.getElementById('metric-sharpe').innerText = (summary.sharpe_ratio || 0).toFixed(2);
    if(document.getElementById('metric-sortino')) document.getElementById('metric-sortino').innerText = (summary.sortino_ratio || 0).toFixed(2);
    if(document.getElementById('metric-skewness')) document.getElementById('metric-skewness').innerText = (summary.skewness || 0).toFixed(2);
    if(document.getElementById('metric-consec-wins')) document.getElementById('metric-consec-wins').innerText = summary.max_consec_wins || 0;
    if(document.getElementById('metric-consec-losses')) document.getElementById('metric-consec-losses').innerText = summary.max_consec_losses || 0;
    if(document.getElementById('metric-clv')) document.getElementById('metric-clv').innerText = summary.avg_clv != null ? ((summary.avg_clv >= 0 ? '+' : '') + summary.avg_clv.toFixed(1) + '%') : 'N/A';
    if(document.getElementById('metric-bcl')) document.getElementById('metric-bcl').innerText = summary.bcl_percent != null ? (summary.bcl_percent.toFixed(1) + '%') : 'N/A';

    if (typeof displayAiAnalysis === 'function') {
        displayAiAnalysis(data.ai_analysis, data);
    }

    if (data.ai_analysis && data.ai_analysis.score !== undefined) {
        const eqsData = {
            score: data.ai_analysis.score,
            verdict: data.ai_analysis.verdict || 'Avaliando...',
            verdict_color: data.ai_analysis.verdict_color || 'warning',
            risk_recommendation: data.ai_analysis.risk_recommendation || data.ai_analysis.report || '',
            breakdown: data.ai_analysis.breakdown || []
        };
        if (typeof renderEdgeQualityScore === 'function') {
            renderEdgeQualityScore(eqsData);
        }
    }

    if (typeof renderStatValidation === 'function') {
        renderStatValidation(data.summary);
    }

    if (typeof renderOosResults === 'function' && data.ai_analysis) {
        const oosSum = data.ai_analysis.oos_summary || null;
        renderOosResults(oosSum, data.summary);
    }

    if (typeof renderRiskManagement === 'function') {
        renderRiskManagement(data);
    }

    const stakingPanel = document.getElementById('staking-comparison-panel');
    if (stakingPanel && data.summary_fixed && data.summary_proportional && data.summary_kelly) {
        stakingPanel.style.display = 'block';
        const stakingTbody = document.getElementById('staking-comparison-tbody');
        if (stakingTbody) {
            const sf = data.summary_fixed;
            const sp = data.summary_proportional;
            const sk = data.summary_kelly;
            stakingTbody.innerHTML = `
                <tr>
                    <td>Stake Fixa</td>
                    <td>$${sf.final_bankroll.toFixed(2)}</td>
                    <td style="color:${sf.net_profit>=0?'var(--success)':'var(--danger)'}">${sf.net_profit>=0?'+':''}$${sf.net_profit.toFixed(2)}</td>
                    <td>${sf.total_bets}</td>
                    <td>${sf.win_rate.toFixed(1)}%</td>
                    <td>${sf.roi.toFixed(2)}%</td>
                    <td>${sf.max_drawdown.toFixed(2)}%</td>
                </tr>
                <tr>
                    <td>Stake Proporcional (2%)</td>
                    <td>$${sp.final_bankroll.toFixed(2)}</td>
                    <td style="color:${sp.net_profit>=0?'var(--success)':'var(--danger)'}">${sp.net_profit>=0?'+':''}$${sp.net_profit.toFixed(2)}</td>
                    <td>${sp.total_bets}</td>
                    <td>${sp.win_rate.toFixed(1)}%</td>
                    <td>${sp.roi.toFixed(2)}%</td>
                    <td>${sp.max_drawdown.toFixed(2)}%</td>
                </tr>
                <tr>
                    <td>Kelly Criterion (1/4)</td>
                    <td>$${sk.final_bankroll.toFixed(2)}</td>
                    <td style="color:${sk.net_profit>=0?'var(--success)':'var(--danger)'}">${sk.net_profit>=0?'+':''}$${sk.net_profit.toFixed(2)}</td>
                    <td>${sk.total_bets}</td>
                    <td>${sk.win_rate.toFixed(1)}%</td>
                    <td>${sk.roi.toFixed(2)}%</td>
                    <td>${sk.max_drawdown.toFixed(2)}%</td>
                </tr>
            `;
        }
    }

    if (typeof renderQuartiles === 'function') renderQuartiles(data.quartiles);

    if (typeof displayPortfolioOptimization === 'function') {
        displayPortfolioOptimization(data.portfolio_optimization);
    }
};

// Call load config on startup
setTimeout(loadClusterAiConfig, 2000);


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
    
    const btn = document.querySelector('button[onclick="runPortfolioBacktest()"]');
    if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Processando (Aguarde...)';
        btn.disabled = true;
    }
    
    // Show Loading
    showToast('Rodando Portfólio. Isso pode levar de 30 a 60 segundos...', 'info', 60000);
    
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
        
        if (!res.ok) {
            showToast(data.detail || data.error || 'Erro desconhecido do servidor.', 'error');
            if (btn) { btn.innerHTML = '<i class="fa-solid fa-layer-group"></i> Rodar Portfólio Selecionado'; btn.disabled = false; }
            return;
        }
        
        if (data.error) {
            showToast(data.error, 'error');
            if (btn) { btn.innerHTML = '<i class="fa-solid fa-layer-group"></i> Rodar Portfólio Selecionado'; btn.disabled = false; }
            return;
        }
        
        showToast('Portfólio calculado com sucesso!', 'success');
        if (btn) { btn.innerHTML = '<i class="fa-solid fa-layer-group"></i> Rodar Portfólio Selecionado'; btn.disabled = false; }
        
        // Switch to Laboratory Tab
        switchTab('tab-laboratory');
        
        // Hide standard Laboratory panels
        document.getElementById('standard-metrics-grid').style.display = 'none';
        
        // Find other major containers and hide them if they exist
        const mainCharts = document.querySelector('.main-charts');
        if (mainCharts) mainCharts.style.display = 'none';
        
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
        
        if (typeof window.renderLaboratoryPanels === 'function') {
            window.renderLaboratoryPanels(data);
        }
        
        const bets = data.bets || [];
        const dates = bets.map((b, i) => b.date ? b.date.substring(0, 10) : i);
        const bankrolls = data.equity_curve ? data.equity_curve.map(e => e.bankroll || e.Bankroll || e) : [];
        const fixedData = data.equity_curve_fixed || [];
        const propData = data.equity_curve_proportional || [];
        const kellyData = data.equity_curve_kelly || [];
        const leagueStats = data.league_stats || [];
        const monthlyStats = data.monthly_stats || [];
        const oddsStats = data.odds_stats || [];
        
        if(typeof updateCharts === 'function') {
            updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueStats, monthlyStats, oddsStats, null);
        }
        
        if (typeof populateBetsTable === 'function') {
            allBets = bets;
            populateBetsTable(allBets);
        }
        
    } catch (e) {
        console.error(e);
        showToast('Erro: ' + e.message, 'error');
        const btn = document.querySelector('button[onclick="runPortfolioBacktest()"]');
        if (btn) { btn.innerHTML = '<i class="fa-solid fa-layer-group"></i> Rodar Portfólio Selecionado'; btn.disabled = false; }
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
