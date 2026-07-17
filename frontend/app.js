import './js/dutching.js?v=1';
import './js/steam_live.js';
import './js/state.js';

// Import modular functions
import { showToast, switchTab, toggleGroup, toggleStakeLabel, formatCurrency, formatPct, createAbortController, animateValue } from './js/utils.js';
import { checkDatabaseStatus, syncDatabase, loadLeagues, fetchServerHistory, saveToServer, deleteFromServer, toggleServerActiveState } from './js/api.js';
import { updateCharts, renderPortfolioChart, clearCharts } from './js/charts.js';
// Bind imports to window so index.html and dynamic elements can call them
window.showToast = showToast;
window.switchTab = switchTab;
window.toggleGroup = toggleGroup;
window.toggleStakeLabel = toggleStakeLabel;
window.checkDatabaseStatus = checkDatabaseStatus;
window.syncDatabase = syncDatabase;
window.loadLeagues = loadLeagues;
window.updateCharts = updateCharts;
window.renderPortfolioChart = renderPortfolioChart;
window.clearCharts = clearCharts;

const API_BASE_URL = window.location.origin;
window.API_BASE_URL = API_BASE_URL;
window.currentDataSource = 'footballdata';
window.futpythonApiKey = '';

// ============================================================
// LOCAL STORAGE PERSISTENCE
// Strategies/portfolios are stored in the browser's localStorage
// so they survive server restarts and redeployments automatically.
// The server is kept in sync so the portfolio backtester works.
// ============================================================
const LS_HISTORY_KEY = 'predictive_history_v3';

function lsLoadHistory() {
    try { return JSON.parse(localStorage.getItem(LS_HISTORY_KEY) || '[]'); } catch { return []; }
}
window.lsLoadHistory = lsLoadHistory;

function lsSaveHistory(data) {
    try { localStorage.setItem(LS_HISTORY_KEY, JSON.stringify(data)); } catch {}
}
window.lsSaveHistory = lsSaveHistory;

function lsAddItem(item) {
    const h = lsLoadHistory();
    const idx = h.findIndex(x => x.id === item.id);
    if (idx >= 0) h[idx] = item; else h.unshift(item);
    lsSaveHistory(h);
}
window.lsAddItem = lsAddItem;

function lsDeleteItem(id) {
    lsSaveHistory(lsLoadHistory().filter(x => x.id !== id));
}
window.lsDeleteItem = lsDeleteItem;

async function lsSyncToServer(localItems) {
    // Re-POST any local items not present on server (after Render redeployment)
    // Fire-and-forget: failures are non-fatal; localStorage is the source of truth
    for (const item of localItems) {
        try {
            const res = await fetch(`${API_BASE_URL}/api/history`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(item)
            });
            if (!res.ok) {
                console.warn('lsSyncToServer: POST falhou para', item.id || item.name, 'status', res.status);
            }
        } catch (e) {
            console.warn('lsSyncToServer: servidor indisponível, sync adiada para', item.id || item.name);
        }
    }
}
window.lsSyncToServer = lsSyncToServer;

async function handleDataSourceChange() {
    try {
        window.currentDataSource = document.getElementById('data-source-select').value;
        // Sync topbar data source selector
        const topbarSelect = document.getElementById('topbar-data-source');
        if (topbarSelect) topbarSelect.value = window.currentDataSource;
        // Key is hardcoded — no need to show the input field anymore
        const configDiv = document.getElementById('futpython-config');
        if (configDiv) configDiv.style.display = 'none';
        // Reload leagues
        if (typeof loadLeagues === 'function') {
            await loadLeagues();
        }

        // Also reload if there's a standalone select somewhere
        const selects = document.querySelectorAll('.league-select');
        selects.forEach(s => {
            s.innerHTML = '';
        });

        // Also reload calculator leagues
        if (typeof populateCalculatorLeagues === 'function') {
            await populateCalculatorLeagues();
        }
        updateMarketBadgesUI();
    } catch (e) {
        console.error('handleDataSourceChange error:', e);
    }
}

const MARKET_COLUMN_MAP = {
    'footballdata': {
        'home': 'odds_ft_1',
        'away': 'odds_ft_2',
        'draw': 'odds_ft_x',
        'lay_home': 'odds_doublechance_x2',
        'lay_away': 'odds_doublechance_1x',
        'lay_draw': 'odds_doublechance_12',
        'lay_home_ex': 'odds_doublechance_x2 (Lay)',
        'lay_away_ex': 'odds_doublechance_1x (Lay)',
        'lay_draw_ex': 'odds_doublechance_12 (Lay)',
        'over15': 'odds_ft_over15',
        'over25': 'odds_ft_over25',
        'under25': 'odds_ft_under25',
        'over35': 'odds_ft_over35',
        'under35': 'odds_ft_under35',
        'over45': 'odds_ft_over45',
        'under45': 'odds_ft_under45',
        'over55': 'Poisson (Estimado)',
        'under55': 'Poisson (Estimado)',
        'btts_yes': 'odds_btts_yes',
        'btts_no': 'odds_btts_no',
        'dnb_h': 'odds_dnb_1',
        'dnb_a': 'odds_dnb_2',
        'ah_home': 'Poisson (Estimado)',
        'ah_away': 'Poisson (Estimado)',
        'ht_home': 'odds_1st_half_result_1',
        'ht_draw': 'odds_1st_half_result_x',
        'ht_away': 'odds_1st_half_result_2',
        'ht_over05': 'odds_1st_half_over05',
        'ht_under05': 'odds_1st_half_under05',
        'ht_over15': 'odds_1st_half_over15',
        'ht_under15': 'odds_1st_half_under15',
        'ht_over25': 'odds_1st_half_over25',
        'ht_under25': 'odds_1st_half_under25',
        'ht_over35': 'odds_1st_half_over35',
        'ht_under35': 'odds_1st_half_under35',
        'sh_home': 'odds_2nd_half_result_1',
        'sh_draw': 'odds_2nd_half_result_x',
        'sh_away': 'odds_2nd_half_result_2',
        'sh_over05': 'odds_2nd_half_over05',
        'sh_under05': 'odds_2nd_half_under05',
        'sh_over15': 'odds_2nd_half_over15',
        'sh_under15': 'odds_2nd_half_under15',
        'sh_over25': 'odds_2nd_half_over25',
        'sh_under25': 'odds_2nd_half_under25',
        'sh_over35': 'odds_2nd_half_over35',
        'sh_under35': 'odds_2nd_half_under35',
        'win_to_nil_home': 'odds_win_to_nil_1',
        'win_to_nil_away': 'odds_win_to_nil_2',
        'corners_1': 'odds_corners_1',
        'corners_x': 'odds_corners_x',
        'corners_2': 'odds_corners_2',
        'corners_over_75': 'odds_corners_over_75',
        'corners_under_75': 'odds_corners_under_75',
        'corners_over_85': 'odds_corners_over_85',
        'corners_under_85': 'odds_corners_under_85',
        'corners_over_95': 'odds_corners_over_95',
        'corners_under_95': 'odds_corners_under_95',
        'corners_over_105': 'odds_corners_over_105',
        'corners_under_105': 'odds_corners_under_105',
        'corners_over_115': 'odds_corners_over_115',
        'corners_under_115': 'odds_corners_under_115',
        'cs_10': 'Poisson (Estimado)',
        'cs_20': 'Poisson (Estimado)',
        'cs_21': 'Poisson (Estimado)',
        'cs_00': 'Poisson (Estimado)',
        'cs_11': 'Poisson (Estimado)',
        'cs_01': 'Poisson (Estimado)',
        'cs_02': 'Poisson (Estimado)',
        'cs_12': 'Poisson (Estimado)',
        'lay_cs_10': 'Poisson (Estimado)',
        'lay_cs_20': 'Poisson (Estimado)',
        'lay_cs_21': 'Poisson (Estimado)',
        'lay_cs_00': 'Poisson (Estimado)',
        'lay_cs_11': 'Poisson (Estimado)',
        'lay_cs_01': 'Poisson (Estimado)',
        'lay_cs_02': 'Poisson (Estimado)',
        'lay_cs_12': 'Poisson (Estimado)'
    },
    'futpython': {
        'home': 'Odd_1_FT',
        'away': 'Odd_2_FT',
        'draw': 'Odd_X_FT',
        'lay_home': 'DC_X2',
        'lay_away': 'DC_1X',
        'lay_draw': 'DC_12',
        'lay_home_ex': 'DC_X2 (Lay)',
        'lay_away_ex': 'DC_1X (Lay)',
        'lay_draw_ex': 'DC_12 (Lay)',
        'over15': 'Over_FT_1_5',
        'over25': 'Over_FT_2_5',
        'under25': 'Under_FT_2_5',
        'over35': 'Over_FT_3_5',
        'under35': 'Under_FT_3_5',
        'over45': 'Over_FT_4_5',
        'under45': 'Under_FT_4_5',
        'over55': 'Poisson (Estimado)',
        'under55': 'Poisson (Estimado)',
        'btts_yes': 'BTTS_Yes',
        'btts_no': 'BTTS_No',
        'dnb_h': 'Indisponível',
        'dnb_a': 'Indisponível',
        'ah_home': 'AH_Home_neg/pos_*',
        'ah_away': 'AH_Away_neg/pos_*',
        'ht_home': 'Odd_1_HT',
        'ht_draw': 'Odd_X_HT',
        'ht_away': 'Odd_2_HT',
        'ht_over05': 'Over_HT_0_5',
        'ht_under05': 'Under_HT_0_5',
        'ht_over15': 'Over_HT_1_5',
        'ht_under15': 'Under_HT_1_5',
        'ht_over25': 'Over_HT_2_5',
        'ht_under25': 'Under_HT_2_5',
        'ht_over35': 'Over_HT_3_5',
        'ht_under35': 'Under_HT_3_5',
        'sh_home': 'Indisponível',
        'sh_draw': 'Indisponível',
        'sh_away': 'Indisponível',
        'sh_over05': 'Indisponível',
        'sh_under05': 'Indisponível',
        'sh_over15': 'Indisponível',
        'sh_under15': 'Indisponível',
        'sh_over25': 'Indisponível',
        'sh_under25': 'Indisponível',
        'sh_over35': 'Indisponível',
        'sh_under35': 'Indisponível',
        'win_to_nil_home': 'Indisponível',
        'win_to_nil_away': 'Indisponível',
        'corners_1': 'Indisponível',
        'corners_x': 'Indisponível',
        'corners_2': 'Indisponível',
        'corners_over_75': 'Indisponível',
        'corners_under_75': 'Indisponível',
        'corners_over_85': 'Indisponível',
        'corners_under_85': 'Indisponível',
        'corners_over_95': 'Indisponível',
        'corners_under_95': 'Indisponível',
        'corners_over_105': 'Indisponível',
        'corners_under_105': 'Indisponível',
        'corners_over_115': 'Indisponível',
        'corners_under_115': 'Indisponível',
        'cs_10': 'CS_1_0',
        'cs_20': 'CS_2_0',
        'cs_21': 'CS_2_1',
        'cs_00': 'CS_0_0',
        'cs_11': 'CS_1_1',
        'cs_01': 'CS_0_1',
        'cs_02': 'CS_0_2',
        'cs_12': 'CS_1_2',
        'lay_cs_10': 'CS_1_0 (Lay)',
        'lay_cs_20': 'CS_2_0 (Lay)',
        'lay_cs_21': 'CS_2_1 (Lay)',
        'lay_cs_00': 'CS_0_0 (Lay)',
        'lay_cs_11': 'CS_1_1 (Lay)',
        'lay_cs_01': 'CS_0_1 (Lay)',
        'lay_cs_02': 'CS_0_2 (Lay)',
        'lay_cs_12': 'CS_1_2 (Lay)'
    }
};

function updateMarketBadgesUI() {
    const activeSource = window.currentDataSource;
    const badgesFd = document.querySelectorAll('.mkt-badge-fd');
    const badgesFp = document.querySelectorAll('.mkt-badge-fp');
    
    if (activeSource === 'footballdata') {
        badgesFd.forEach(b => b.classList.remove('mkt-badge-dimmed'));
        badgesFp.forEach(b => b.classList.add('mkt-badge-dimmed'));
    } else if (activeSource === 'futpython') {
        badgesFd.forEach(b => b.classList.add('mkt-badge-dimmed'));
        badgesFp.forEach(b => b.classList.remove('mkt-badge-dimmed'));
    } else {
        badgesFd.forEach(b => b.classList.remove('mkt-badge-dimmed'));
        badgesFp.forEach(b => b.classList.remove('mkt-badge-dimmed'));
    }
    
    // Update dynamic column name display next to each market option
    const options = document.querySelectorAll('.multiselect-option-item');
    options.forEach(opt => {
        const checkbox = opt.querySelector('input[type="checkbox"]');
        if (!checkbox) return;
        const val = checkbox.value;
        const colSpan = opt.querySelector('.mkt-col-name');
        if (!colSpan) return;
        
        const sourceMap = MARKET_COLUMN_MAP[activeSource];
        if (sourceMap && sourceMap[val]) {
            const colName = sourceMap[val];
            if (colName === 'Indisponível') {
                colSpan.textContent = ' (Indisponível)';
                colSpan.style.color = '#ff4a4a';
            } else {
                colSpan.textContent = ` (${colName})`;
                colSpan.style.color = 'var(--text-secondary)';
            }
        } else {
            colSpan.textContent = '';
        }
    });
}


function saveFutpythonKey(val) {
    window.futpythonApiKey = val;
    localStorage.setItem('futpython_api_key', val);
}


function runInitApp() {
    // Sync currentDataSource with whatever the browser restored in the select
    const sourceSelect = document.getElementById('data-source-select');
    if (sourceSelect) {
        window.currentDataSource = sourceSelect.value;
        const topbarSelect = document.getElementById('topbar-data-source');
        if (topbarSelect) topbarSelect.value = window.currentDataSource;
        // Key is hardcoded — no need to show the input field
    }

    // Load FutPythonTrader API Key — default key já vem preenchida
    const defaultFutpythonKey = 'cmqa6oz0p01i1wq6lzxknltmd';
    const savedKey = localStorage.getItem('futpython_api_key');
    const keyInput = document.getElementById('futpython-api-key');
    if (savedKey) {
        window.futpythonApiKey = savedKey;
        if (keyInput) keyInput.value = savedKey;
    } else {
        window.futpythonApiKey = defaultFutpythonKey;
        if (keyInput) keyInput.value = defaultFutpythonKey;
    }
    
    initApp();
    updateMarketBadgesUI();
    
    // Close modal when clicking outside of modal container
    const modal = document.getElementById('match-details-modal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeMatchDetailsModal();
            }
        });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runInitApp);
} else {
    runInitApp();
}

async function initApp() {
    if (window._initAppRunning) return;
    window._initAppRunning = true;
    try {
    await checkDatabaseStatus();
    await loadLeagues();
    await populateCalculatorLeagues();
    await loadTelegramConfigUi();
    await loadSchedulerConfigUi();
    await loadTelegramTipsLog();
    await loadArbitrageBotConfig();
    await loadDutchingBotConfig();
    await loadOddsApiKey();
    toggleStakeLabel();
    onMarketSelectionChange(); // Initialize custom market multiselect label
    updateNotificationUi(); // Initialize notification permission state in UI

    // Register Service Worker for PWA (only once)
    if ('serviceWorker' in navigator && !window._swRegistered) {
        window._swRegistered = true;
        // Unregister any existing service workers to prevent stale cache
        navigator.serviceWorker.getRegistrations().then(regs => {
            regs.forEach(r => r.unregister());
        });
        // Only register in production (not localhost)
        if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
            navigator.serviceWorker.register('/service-worker.js')
                .then(() => console.log('Service Worker registrado.'))
                .catch(err => console.error('Service Worker erro:', err));
        }
    }
    
    // Inicializa a calculadora de Dutching com duas seleções padrão
    setTimeout(() => {
        if (typeof addDutchingRow === 'function') {
            addDutchingRow("Placar 1-0", 6.50);
            addDutchingRow("Placar 2-0", 7.50);
        }
    }, 100);
    } finally {
        window._initAppRunning = false;
    }
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

// currentBetsForPagination imported from state.js
// currentPage imported from state.js
// rowsPerPage imported from state.js
// betsAscending imported from state.js

function populateBetsTable(bets) {
    // Store bets in chronological order (oldest first). Reverse only if user chose newest-first.
    const sorted = bets.slice(); // already oldest-first from backend
    window.currentBetsForPagination = betsAscending ? sorted : sorted.slice().reverse();
    window.currentPage = 1;
    renderBetsPage();
}

function toggleBetsSort() {
    window.betsAscending = !window.betsAscending;
    const btn = document.getElementById('sort-bets-btn');
    if (btn) btn.innerHTML = window.betsAscending
        ? '<i class="fa-solid fa-arrow-up-1-9"></i> Mais Antigo Primeiro'
        : '<i class="fa-solid fa-arrow-down-9-1"></i> Mais Recente Primeiro';
    // Re-sort current data without re-fetching
    window.currentBetsForPagination = window.currentBetsForPagination.slice().reverse();
    window.currentPage = 1;
    renderBetsPage();
}

function renderBetsPage() {
    const tbody = document.getElementById('bets-table-body');
    tbody.innerHTML = '';

    if (window.currentBetsForPagination.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="text-center empty-state">
                    <i class="fa-solid fa-face-frown"></i> Nenhuma aposta realizada nesta simulação. Tente ajustar o gatilho de valor EV ou as ligas.
                </td>
            </tr>
        `;
        document.getElementById('pagination-controls').style.display = 'none';
        return;
    }

    const totalPages = Math.ceil(window.currentBetsForPagination.length / window.rowsPerPage);
    const start = (currentPage - 1) * window.rowsPerPage;
    const end = start + window.rowsPerPage;
    const pageBets = window.currentBetsForPagination.slice(start, end);

    pageBets.forEach(bet => {
        const tr = document.createElement('tr');
        const profitClass = bet.profit >= 0 ? 'text-profit' : 'text-loss';
        const winBadge = bet.profit >= 0 ? '<span class="badge-row-win">Green</span>' : '<span class="badge-row-loss">Red</span>';
        
        tr.innerHTML = `
            <td>${bet.date}</td>
            <td>
                ${bet.strategy_name ? `<span style="font-size:10px; color:var(--primary); text-transform:uppercase; letter-spacing:0.5px;">${bet.strategy_name}</span><br>` : ''}
                <strong>${bet.league}</strong>
            </td>
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

    // Update pagination UI
    if (totalPages > 1) {
        document.getElementById('pagination-controls').style.display = 'flex';
        document.getElementById('page-indicator').innerText = `Página ${window.currentPage} de ${totalPages}`;
        document.getElementById('prev-page-btn').disabled = window.currentPage === 1;
        document.getElementById('next-page-btn').disabled = window.currentPage === totalPages;
    } else {
        document.getElementById('pagination-controls').style.display = 'none';
    }
}

function prevPage() {
    if (window.currentPage > 1) {
        window.currentPage--;
        renderBetsPage();
    }
}

function nextPage() {
    const totalPages = Math.ceil(window.currentBetsForPagination.length / window.rowsPerPage);
    if (window.currentPage < totalPages) {
        window.currentPage++;
        renderBetsPage();
    }
}



// Simple filter on table by typing team names

function filterTable() {

    const search = document.getElementById('table-search').value.toLowerCase();

    

    const filteredBets = window.allBets.filter(bet => 

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
        odds_timing: document.getElementById('odds-timing') ? document.getElementById('odds-timing').value : 'closing',
        scanType: scanType,

        minOdds: parseFloat(document.getElementById('min-odds').value) || 1.0,

        maxOdds: parseFloat(document.getElementById('max-odds').value) || 2.50,

        use_ml: document.getElementById('use-ml-toggle')?.checked || false,
        model_type: document.getElementById('model-type-select')?.value || 'poisson',

        data_source: window.currentDataSource,

        futpython_api_key: window.futpythonApiKey,

        walk_forward_folds: (() => {
            const wfToggle = document.getElementById("wf-toggle");
            const wfFoldsEl = document.getElementById("wf-folds");
            return (wfToggle && wfToggle.checked) ? (wfFoldsEl ? parseInt(wfFoldsEl.value) : 5) : 0;
        })()

    };

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/scan`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(requestData),

            cache: 'no-store'

        });



        if (!res.ok) {

            const errData = await res.json();

            throw new Error(errData.detail || "Erro ao escanear");

        }



        const data = await res.json();

        const results = data.results;



        window.lastScanResults = results;

        window.lastScanParams = requestData;

        

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

                    <span class="scanner-item-profit ${profitClass}">${sign}$${(item.net_profit ?? 0).toFixed(2)}</span>

                </div>

                <div class="scanner-item-body">

                    <span>ROI: <strong class="${profitClass}">${sign}${(item.roi ?? 0).toFixed(2)}%</strong></span>

                    <span>Acertos: <strong>${(item.win_rate ?? 0).toFixed(1)}%</strong></span>

                    <span>Apostas: <strong>${item.total_bets ?? 0}</strong></span>

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

                    return pValAdj !== undefined && pValAdj !== null ? `

                    <div style="display: flex; justify-content: space-between; font-size: 12px; margin-top: 5px; padding-top: 5px; border-top: 1px solid rgba(255,255,255,0.05);" title="p-valor ajustado por FDR (Benjamini-Hochberg). Valores abaixo de 0,05 indicam significância estatística, ou seja, é improvável que o resultado seja fruto do acaso." onclick="showToast(this.title, 'info')">

                        <span style="color: var(--text-muted);">p-valor (FDR):</span>

                        <span style="color: ${pColor}; font-weight: 600;"><i class="fa-solid ${pIcon}"></i> ${(pValAdj ?? 0).toFixed(3)} — ${pLabel}</span>

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

    if (!window.lastScanResults || window.lastScanResults.length === 0) {

        showToast("Nenhum resultado de escaneamento para exportar.", "error");

        return;

    }



    const params = window.lastScanParams;

    const results = window.lastScanResults;



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

    if (!window.lastBacktestSummary || !window.lastBacktestSummary.summary) {

        showToast("Nenhum resultado de backtest disponível para exportar. Execute um backtest primeiro!", "error");

        return;

    }



    const params = window.lastBacktestParams;

    const summary = window.lastBacktestSummary.summary;

    const summaryFixed = window.lastBacktestSummary.summary_fixed;

    const summaryProp = window.lastBacktestSummary.summary_proportional;

    const summaryKelly = window.lastBacktestSummary.summary_kelly;

    const bets = window.lastBacktestSummary.bets;



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

        csvRows.push(`Intervalo Confianca ROI (95%);${summary.bootstrap_roi_ci_lower.toFixed(1).replace('.', ',')}% — ${summary.bootstrap_roi_ci_upper.toFixed(1).replace('.', ',')}%`);

    }

    if (summary.bootstrap_drawdown_ci_lower !== undefined) {

        csvRows.push(`Drawdown Bootstrap Mediana;${summary.bootstrap_drawdown_median.toFixed(1).replace('.', ',')}%`);

        csvRows.push(`Drawdown Bootstrap IC (95%);${summary.bootstrap_drawdown_ci_lower.toFixed(1).replace('.', ',')}% — ${summary.bootstrap_drawdown_ci_upper.toFixed(1).replace('.', ',')}%`);

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



function displayAiAnalysis(aiAnalysis, results, isPortfolio = false) {

    const aiPanel = document.getElementById('ai-analytics-panel');

    const optPanel = document.getElementById('ai-optimization-panel');

    if (!aiAnalysis || aiAnalysis.status === 'insufficient_data') {

        aiPanel.style.display = 'none';

        if (optPanel) optPanel.style.display = 'none';

        if (typeof renderOptimizationTab === 'function') {
            renderOptimizationTab([], null);
        }

        return;

    }

    

    aiPanel.style.display = 'block';

    

    // Fill text and values
    const mlProb = aiAnalysis.ml_probability || 0;
    document.getElementById('ai-ml-probability').innerText = `${mlProb.toFixed(1)}%`;

    const mlProgress = document.getElementById('ai-ml-progress');
    mlProgress.style.width = `${mlProb}%`;

    const bayesConf = aiAnalysis.bayesian_confidence || 0;
    document.getElementById('ai-bayesian-confidence').innerText = `${bayesConf.toFixed(1)}%`;

    const bayesianProgress = document.getElementById('ai-bayesian-progress');
    bayesianProgress.style.width = `${bayesConf}%`;

    // Drift
    const driftVal = document.getElementById('ai-drift-value');
    const driftRatio = aiAnalysis.drift_ratio || 0;
    const sign = driftRatio >= 0 ? '+' : '';
    driftVal.innerText = `${sign}${driftRatio.toFixed(1)}%`;

    // Color of drift value
    if (driftRatio >= 0) {
        driftVal.className = 'widget-value text-profit';
    } else if (driftRatio < -8) {
        driftVal.className = 'widget-value text-loss';
    } else {
        driftVal.className = 'widget-value'; // neutral or light decay
    }

    const roiFirst = aiAnalysis.roi_first_half || 0;
    const roiSecond = aiAnalysis.roi_second_half || 0;
    document.getElementById('ai-roi-first').innerText = `${roiFirst.toFixed(1)}%`;
    document.getElementById('ai-roi-second').innerText = `${roiSecond.toFixed(1)}%`;

    // Colors of first/second ROI
    const roiFirstSpan = document.getElementById('ai-roi-first');
    const roiSecondSpan = document.getElementById('ai-roi-second');
    roiFirstSpan.className = roiFirst >= 0 ? 'half-val text-profit' : 'half-val text-loss';
    roiSecondSpan.className = roiSecond >= 0 ? 'half-val text-profit' : 'half-val text-loss';

    // Set Verdict badge and report text
    const badge = document.getElementById('ai-verdict-badge');
    const reportText = document.getElementById('ai-report-text');

    // Simple markdown interpreter for report text (converting **bold** to <strong> and newlines to <br>)
    let formattedReport = (aiAnalysis.report || '')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');

    reportText.innerHTML = formattedReport;

    

    // Classify badge based on ML probability & Bayesian confidence & Drift
    if (mlProb >= 65 && bayesConf >= 70 && driftRatio >= -3) {
        badge.innerText = 'Excelente / Sustentável';
        badge.className = 'badge badge-high';
    } else if (mlProb < 50 && bayesConf < 60) {
        badge.innerText = 'Risco Alto / Overfitting';
        badge.className = 'badge badge-low';
    } else if (driftRatio < -8) {
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

    displayOptimizationSuggestions(aiAnalysis.suggestions, isPortfolio);
    if (typeof renderOptimizationTab === 'function') {
        renderOptimizationTab(aiAnalysis.suggestions, results);
    }

}



function renderChecklist(aiAnalysis, results) {

    const container = document.getElementById('ai-checklist-container');

    if (!container) return;

    

    container.innerHTML = ''; // Clear placeholder

    

    const summary = results.summary;
    const mc = aiAnalysis.monte_carlo;
    const mlProb = aiAnalysis.ml_probability || 0;
    const bayesConf = aiAnalysis.bayesian_confidence || 0;
    const driftRatio = aiAnalysis.drift_ratio || 0;

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
            value: `${mlProb.toFixed(1)}%`,
            desc: mlProb >= 70.0 ? "Aprovado: Alta chance de continuidade nos próximos ciclos." :
                  (mlProb >= 50.0 ? "Alerta: Estabilidade moderada com alguma oscilação prevista." : "Perigo: Alta probabilidade de inversão ou decaimento."),
            status: mlProb >= 70.0 ? "success" : (mlProb >= 50.0 ? "warning" : "danger"),
            icon: mlProb >= 70.0 ? "fa-circle-check" : (mlProb >= 50.0 ? "fa-triangle-exclamation" : "fa-circle-xmark")
        },
        {
            title: "Confiança Bayesiana do Edge",
            value: `${bayesConf.toFixed(1)}% de certeza`,
            desc: bayesConf >= 80.0 ? "Aprovado: Edge matemático real comprovado cientificamente." :
                  (bayesConf >= 60.0 ? "Alerta: Indícios fracos de edge, pode ser ruído estatístico." : "Perigo: Desempenho muito próximo da sorte/azar no longo prazo."),
            status: bayesConf >= 80.0 ? "success" : (bayesConf >= 60.0 ? "warning" : "danger"),
            icon: bayesConf >= 80.0 ? "fa-circle-check" : (bayesConf >= 60.0 ? "fa-triangle-exclamation" : "fa-circle-xmark")
        },
        {
            title: "Estabilidade Temporal (Drift de ROI)",
            value: `${driftRatio >= 0 ? '+' : ''}${driftRatio.toFixed(1)}% de desvio`,
            desc: driftRatio >= -3.0 ? "Aprovado: Estratégia muito estável entre a 1ª e 2ª metades." :
                  (driftRatio >= -8.0 ? "Alerta: Leve decaimento de performance detectado." : "Perigo: Forte perda de rendimento recente (decaimento estatístico)."),
            status: driftRatio >= -3.0 ? "success" : (driftRatio >= -8.0 ? "warning" : "danger"),
            icon: driftRatio >= -3.0 ? "fa-circle-check" : (driftRatio >= -8.0 ? "fa-triangle-exclamation" : "fa-circle-xmark")
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



function displayOptimizationSuggestions(suggestions, isPortfolio = false) {

    const suggestionsContainer = document.getElementById('ai-optimization-suggestions');

    const optPanel = document.getElementById('ai-optimization-panel');



    if (!optPanel || !suggestionsContainer) return;



    optPanel.style.display = 'block';

    suggestionsContainer.innerHTML = '';



    // Store all suggestions globally (needed by apply* functions)
    window.allOptimizationSuggestions = suggestions || [];

    console.log('[displayOptimizationSuggestions] total suggestions:', (suggestions || []).length, 'applied:', [...window.appliedOptimizationSuggestions]);

    // Filter out already applied suggestions

    const filteredSuggestions = (suggestions || []).filter(sug => {

        if (sug.type === 'odds_warning' && window.appliedOptimizationSuggestions.has(sug.value)) { console.log('[displayOptimizationSuggestions] filtering odds_warning:', sug.value); return false; }

        if (sug.type === 'ev' && window.appliedOptimizationSuggestions.has(`ev_${sug.value}`)) { console.log('[displayOptimizationSuggestions] filtering ev:', sug.value); return false; }

        if (sug.type === 'leagues' && window.appliedOptimizationSuggestions.has(`leagues_${JSON.stringify(sug.exclude_codes)}`)) { console.log('[displayOptimizationSuggestions] filtering leagues:', JSON.stringify(sug.exclude_codes)); return false; }

        return true;

    });

    console.log('[displayOptimizationSuggestions] filtered count:', filteredSuggestions.length);

    

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

        

        if (isPortfolio) {
            buttonHtml = `<span style="font-size:12px;color:var(--text-muted);"><i class="fa-solid fa-info-circle"></i> Otimização deve ser aplicada na edição individual da estratégia.</span>`;
        } else if (sug.type === 'ev') {

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

let optComparisonChart = null;
let currentSelectedSuggestion = null;

// Helper: find a suggestion by type+key across all stored suggestions
function findSuggestion(type, keyMatch) {
    // First check currentSelectedSuggestion
    if (currentSelectedSuggestion && currentSelectedSuggestion.type === type) {
        if (type === 'ev' && currentSelectedSuggestion.value === keyMatch) return currentSelectedSuggestion;
        if (type === 'leagues' && JSON.stringify(currentSelectedSuggestion.exclude_codes) === keyMatch) return currentSelectedSuggestion;
        if (type === 'odds_warning' && currentSelectedSuggestion.value === keyMatch) return currentSelectedSuggestion;
    }
    // Fallback: search all suggestions
    const all = window.allOptimizationSuggestions || [];
    return all.find(s => {
        if (s.type !== type) return false;
        if (type === 'ev') return s.value === keyMatch;
        if (type === 'leagues') return JSON.stringify(s.exclude_codes) === keyMatch;
        if (type === 'odds_warning') return s.value === keyMatch;
        return false;
    });
}

function renderOptimizationTab(suggestions, results) {
    const listContainer = document.getElementById('opt-suggestions-list');
    const tableContainer = document.getElementById('opt-comparison-table-container');

    if (!listContainer) return;

    // Store all suggestions globally (needed by apply* functions)
    window.allOptimizationSuggestions = suggestions || [];

    listContainer.innerHTML = '';

    const filteredSuggestions = (suggestions || []).filter(sug => {
        if (sug.type === 'odds_warning' && window.appliedOptimizationSuggestions.has(sug.value)) return false;
        if (sug.type === 'ev' && window.appliedOptimizationSuggestions.has(`ev_${sug.value}`)) return false;
        if (sug.type === 'leagues' && window.appliedOptimizationSuggestions.has(`leagues_${JSON.stringify(sug.exclude_codes)}`)) return false;
        return true;
    });
    
    if (!filteredSuggestions || filteredSuggestions.length === 0) {
        listContainer.innerHTML = `
            <div style="padding: 30px; text-align: center; color: var(--text-secondary); font-size: 13px; background: rgba(255, 255, 255, 0.01); border: 1px dashed rgba(255, 255, 255, 0.05); border-radius: 8px;">
                <i class="fa-solid fa-circle-check" style="color: var(--success); font-size: 28px; margin-bottom: 12px; display: block;"></i>
                <strong>Tudo Otimizado!</strong><br><br>
                O motor multidimensional varreu todas as combinações de EV+, odds e exclusão de ligas. Sua estratégia atual já se encontra no ponto ótimo.
            </div>
        `;
        if (tableContainer) {
            tableContainer.innerHTML = `
                <div style="text-align: center; padding: 30px; color: var(--text-muted); font-size: 13px;">
                    Nenhum cenário de otimização ativo para comparação.
                </div>
            `;
        }
        if (optComparisonChart) {
            optComparisonChart.destroy();
            optComparisonChart = null;
        }
        return;
    }
    
    // Select the first suggestion by default
    currentSelectedSuggestion = filteredSuggestions[0];
    
    filteredSuggestions.forEach((sug, idx) => {
        const div = document.createElement('div');
        div.className = `optimization-sug-item ${sug === currentSelectedSuggestion ? 'active' : ''}`;
        
        let activeBg = 'rgba(16, 185, 129, 0.08)';
        let activeBorder = 'rgba(16, 185, 129, 0.3)';
        let defaultBg = 'rgba(255, 255, 255, 0.02)';
        let defaultBorder = 'rgba(255, 255, 255, 0.05)';
        
        div.style.cssText = `
            padding: 16px;
            background: ${sug === currentSelectedSuggestion ? activeBg : defaultBg};
            border: 1px solid ${sug === currentSelectedSuggestion ? activeBorder : defaultBorder};
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 15px;
            margin-bottom: 10px;
        `;
        
        // Add hover effects
        div.onmouseover = () => {
            if (sug !== currentSelectedSuggestion) {
                div.style.background = 'rgba(255, 255, 255, 0.04)';
                div.style.borderColor = 'rgba(255, 255, 255, 0.1)';
            }
        };
        div.onmouseout = () => {
            if (sug !== currentSelectedSuggestion) {
                div.style.background = defaultBg;
                div.style.borderColor = defaultBorder;
            }
        };
        
        let iconHtml = '';
        let badgeColor = '';
        let badgeText = '';
        
        if (sug.type === 'ev') {
            iconHtml = '<i class="fa-solid fa-bolt" style="color: #f59e0b;"></i>';
            badgeText = 'EV+';
            badgeColor = 'rgba(245, 158, 11, 0.15); color: #fbbf24';
        } else if (sug.type === 'leagues') {
            iconHtml = '<i class="fa-solid fa-trophy" style="color: #3b82f6;"></i>';
            badgeText = 'Ligas';
            badgeColor = 'rgba(59, 130, 246, 0.15); color: #60a5fa';
        } else {
            iconHtml = '<i class="fa-solid fa-chart-line" style="color: #10b981;"></i>';
            badgeText = 'Odds';
            badgeColor = 'rgba(16, 185, 129, 0.15); color: #34d399';
        }
        
        const infoDiv = document.createElement('div');
        infoDiv.style.flex = '1';
        infoDiv.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                ${iconHtml}
                <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; background: ${badgeColor};">${badgeText}</span>
            </div>
            <p style="margin: 0; font-size: 13px; color: var(--text-primary); line-height: 1.4;">${sug.text}</p>
        `;
        
        let actionBtnHtml = '';
        if (sug.type === 'ev') {
            actionBtnHtml = `<button class="btn-scanner" style="margin: 0; font-size: 12px; padding: 6px 12px; background: linear-gradient(135deg, #10b981 0%, #059669 100%); border-color: #10b981;" onclick="applyEvSuggestion(${sug.value})"><i class="fa-solid fa-wand-magic"></i> Aplicar</button>`;
        } else if (sug.type === 'leagues') {
            const codesStr = JSON.stringify(sug.exclude_codes).replace(/"/g, '&quot;');
            actionBtnHtml = `<button class="btn-scanner" style="margin: 0; font-size: 12px; padding: 6px 12px; background: linear-gradient(135deg, #10b981 0%, #059669 100%); border-color: #10b981;" onclick='applyLeagueSuggestion(` + JSON.stringify(sug.exclude_codes) + `)'><i class="fa-solid fa-filter-circle-xmark"></i> Aplicar</button>`;
        } else {
            const escapedValue = sug.value.replace(/'/g, "\\'");
            actionBtnHtml = `<button class="btn-scanner" style="margin: 0; font-size: 12px; padding: 6px 12px; background: linear-gradient(135deg, #10b981 0%, #059669 100%); border-color: #10b981;" onclick="applyOddsSuggestion('${escapedValue}')"><i class="fa-solid fa-wand-magic-sparkles"></i> Aplicar</button>`;
        }
        
        div.appendChild(infoDiv);
        
        const rightDiv = document.createElement('div');
        rightDiv.style.cssText = 'display: flex; flex-direction: column; align-items: flex-end; gap: 8px;';
        rightDiv.innerHTML = actionBtnHtml;
        div.appendChild(rightDiv);
        
        div.onclick = () => {
            currentSelectedSuggestion = sug;
            document.querySelectorAll('.optimization-sug-item').forEach(el => {
                el.style.background = defaultBg;
                el.style.borderColor = defaultBorder;
            });
            div.style.background = activeBg;
            div.style.borderColor = activeBorder;
            
            updateComparisonDisplay(sug, results);
        };
        
        listContainer.appendChild(div);
    });
    
    updateComparisonDisplay(currentSelectedSuggestion, results);
}

function updateComparisonDisplay(sug, results) {
    if (!sug) return;
    const tableContainer = document.getElementById('opt-comparison-table-container');
    if (!tableContainer) return;
    
    const orig = sug.original_summary;
    const opt = sug.optimized_summary;
    
    const profitDiff = opt.net_profit - orig.net_profit;
    const roiDiff = opt.roi - orig.roi;
    const wrDiff = opt.win_rate - orig.win_rate;
    const ddDiff = opt.max_drawdown - orig.max_drawdown;
    const betsDiff = opt.total_bets - orig.total_bets;
    
    const profitDiffClass = profitDiff >= 0 ? 'text-success' : 'text-danger';
    const roiDiffClass = roiDiff >= 0 ? 'text-success' : 'text-danger';
    const wrDiffClass = wrDiff >= 0 ? 'text-success' : 'text-danger';
    const ddDiffClass = ddDiff <= 0 ? 'text-success' : 'text-danger';
    const betsDiffClass = betsDiff >= 0 ? 'text-success' : 'text-danger';
    
    const profitDiffText = (profitDiff >= 0 ? '+' : '') + `$${profitDiff.toFixed(2)}`;
    const roiDiffText = (roiDiff >= 0 ? '+' : '') + `${roiDiff.toFixed(2)}%`;
    const wrDiffText = (wrDiff >= 0 ? '+' : '') + `${wrDiff.toFixed(1)}%`;
    const ddDiffText = (ddDiff >= 0 ? '+' : '') + `${ddDiff.toFixed(1)}%`;
    const betsDiffText = (betsDiff >= 0 ? '+' : '') + betsDiff;
    
    tableContainer.innerHTML = `
        <table class="suggestion-comparison-table" style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
                <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.1); text-align: left;">
                    <th style="padding: 10px 8px; color: var(--text-secondary);">Métrica</th>
                    <th style="padding: 10px 8px; color: var(--text-secondary);">Original</th>
                    <th style="padding: 10px 8px; color: var(--text-secondary);">Otimizado</th>
                    <th style="padding: 10px 8px; color: var(--text-secondary);">Diferença</th>
                </tr>
            </thead>
            <tbody>
                <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05);">
                    <td style="padding: 12px 8px; font-weight: 500; color: var(--text-primary);">Lucro Líquido</td>
                    <td style="padding: 12px 8px; color: var(--text-secondary);">$${orig.net_profit.toFixed(2)}</td>
                    <td style="padding: 12px 8px; color: #10b981; font-weight: 600;">$${opt.net_profit.toFixed(2)}</td>
                    <td style="padding: 12px 8px; font-weight: 600;" class="${profitDiffClass}">${profitDiffText}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05);">
                    <td style="padding: 12px 8px; font-weight: 500; color: var(--text-primary);">ROI (Yield)</td>
                    <td style="padding: 12px 8px; color: var(--text-secondary);">${orig.roi.toFixed(2)}%</td>
                    <td style="padding: 12px 8px; color: #10b981; font-weight: 600;">${opt.roi.toFixed(2)}%</td>
                    <td style="padding: 12px 8px; font-weight: 600;" class="${roiDiffClass}">${roiDiffText}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05);">
                    <td style="padding: 12px 8px; font-weight: 500; color: var(--text-primary);">Taxa de Acerto</td>
                    <td style="padding: 12px 8px; color: var(--text-secondary);">${orig.win_rate.toFixed(1)}%</td>
                    <td style="padding: 12px 8px; color: var(--text-secondary);">${opt.win_rate.toFixed(1)}%</td>
                    <td style="padding: 12px 8px; font-weight: 600;" class="${wrDiffClass}">${wrDiffText}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05);">
                    <td style="padding: 12px 8px; font-weight: 500; color: var(--text-primary);">Max Drawdown</td>
                    <td style="padding: 12px 8px; color: var(--text-secondary);">${orig.max_drawdown.toFixed(1)}%</td>
                    <td style="padding: 12px 8px; color: #ef4444; font-weight: 600;">${opt.max_drawdown.toFixed(1)}%</td>
                    <td style="padding: 12px 8px; font-weight: 600;" class="${ddDiffClass}">${ddDiffText}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05);">
                    <td style="padding: 12px 8px; font-weight: 500; color: var(--text-primary);">Total Apostas</td>
                    <td style="padding: 12px 8px; color: var(--text-secondary);">${orig.total_bets}</td>
                    <td style="padding: 12px 8px; color: var(--text-secondary);">${opt.total_bets}</td>
                    <td style="padding: 12px 8px; font-weight: 600;" class="${betsDiffClass}">${betsDiffText}</td>
                </tr>
            </tbody>
        </table>
    `;
    
    renderOptComparisonChart(sug, results);
}

function renderOptComparisonChart(sug, results) {
    const ctx = document.getElementById('opt-comparison-chart');
    if (!ctx) return;

    if (optComparisonChart) {
        optComparisonChart.destroy();
    }

    const origCurve = (results && results.equity_curve) || [];
    const optCurve = sug.optimized_curve || [];
    
    const allDates = Array.from(new Set([
        ...origCurve.map(pt => pt.date),
        ...optCurve.map(pt => pt.date)
    ])).sort();
    
    const ctxCanvas = ctx.getContext('2d');
    const gradOrig = ctxCanvas.createLinearGradient(0, 0, 0, 300);
    gradOrig.addColorStop(0, 'rgba(99, 102, 241, 0.15)');
    gradOrig.addColorStop(1, 'rgba(99, 102, 241, 0.0)');
    
    const gradOpt = ctxCanvas.createLinearGradient(0, 0, 0, 300);
    gradOpt.addColorStop(0, 'rgba(16, 185, 129, 0.2)');
    gradOpt.addColorStop(1, 'rgba(16, 185, 129, 0.0)');
    
    optComparisonChart = new Chart(ctxCanvas, {
        type: 'line',
        data: {
            labels: allDates,
            datasets: [
                {
                    label: 'Original Strategy ($)',
                    data: origCurve.map(pt => pt.bankroll),
                    borderColor: 'rgba(99, 102, 241, 0.6)',
                    borderWidth: 1.5,
                    borderDash: [4, 4],
                    fill: true,
                    backgroundColor: gradOrig,
                    tension: 0.15,
                    pointRadius: allDates.length > 200 ? 0 : 1,
                    pointHoverRadius: 4
                },
                {
                    label: 'Optimized Strategy ($)',
                    data: optCurve.map(pt => pt.bankroll),
                    borderColor: '#10b981',
                    borderWidth: 2.5,
                    fill: true,
                    backgroundColor: gradOpt,
                    tension: 0.15,
                    pointRadius: allDates.length > 200 ? 0 : 2,
                    pointHoverRadius: 5
                }
            ]
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
                        font: { family: 'Outfit', size: 12 },
                        usePointStyle: true,
                        boxWidth: 8
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.02)' },
                    ticks: {
                        color: '#9ca3af',
                        font: { family: 'Outfit', size: 10 },
                        maxTicksLimit: 12
                    }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#9ca3af',
                        font: { family: 'Outfit', size: 10 }
                    }
                }
            }
        }
    });
}



// Immediately render pre-computed optimized results into the Laboratory
// (the Optimization tab's optimized_summary comes from ai_predictor.py's
// recalculate_sub_backtest() which simulates flat-staking in-process;
// this is different from the full Poisson backtest engine, so we render
// the optimized numbers right away, then refresh with the real backtest)
function renderOptimizedResultsToLaboratory(sug) {
    if (!sug || !sug.optimized_summary) return;

    const showStandardPanels = () => {
        const pPanel = document.getElementById('portfolio-results-panel');
        if (pPanel) pPanel.style.display = 'none';
        const smGrid = document.getElementById('standard-metrics-grid');
        if (smGrid) smGrid.style.display = 'grid';
        const mainCharts = document.querySelector('.main-charts');
        if (mainCharts) mainCharts.style.display = 'block';
        const stakingPanel = document.getElementById('staking-comparison-panel');
        if (stakingPanel) stakingPanel.style.display = 'block';
        const quartilesPanel = document.getElementById('quartiles-panel');
        if (quartilesPanel) quartilesPanel.style.display = 'block';
        const resultsTable = document.querySelector('.results-table-section');
        if (resultsTable) resultsTable.style.display = 'block';
    };
    showStandardPanels();

    const opt = sug.optimized_summary;
    const orig = sug.original_summary || {};

    // --- KPI Metrics ---
    const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val; };
    const setElColor = (id, val, positiveVal) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerText = val;
        el.style.color = positiveVal ? 'var(--color-success)' : 'var(--color-danger)';
    };

    const netProfit = opt.net_profit || 0;
    const roi = opt.roi || 0;
    const winRate = opt.win_rate || 0;
    const dd = opt.max_drawdown || 0;
    const totalBets = opt.total_bets || 0;

    // Only update metrics that exist in optimized_summary.
    // All other fields (wins, losses, avg_odds, matches_analyzed, seasons,
    // sharpe, sortino, clv, bcl, etc.) are NOT in optimized_summary —
    // they only come from the full Poisson backtest. Don't touch them.
    animateValue(document.getElementById('metric-net-profit'), 0, netProfit, 600, v => (v >= 0 ? '+' : '') + '$' + Math.abs(v).toFixed(2));
    setElColor('metric-roi', roi.toFixed(1) + '%', roi >= 0);
    setElColor('metric-win-rate', winRate.toFixed(1) + '%', winRate >= 50);
    setEl('metric-max-drawdown', dd.toFixed(1) + '%');
    setEl('metric-drawdown', dd.toFixed(1) + '%');
    setEl('metric-total-bets', totalBets);
    setEl('metric-profit-stakes', (opt.profit_in_stakes || 0).toFixed(2) + ' st.');

    // final_bankroll is derivable from original_summary
    const fb = opt.final_bankroll || orig.final_bankroll;
    if (fb) setEl('metric-final-bankroll', '$' + fb.toFixed(2));

    // --- Banner ---
    const banner = document.getElementById('active-strategy-banner');
    if (banner) banner.style.display = 'flex';
    const optBanner = document.getElementById('optimization-active-banner');
    if (!optBanner) {
        const b = document.createElement('div');
        b.id = 'optimization-active-banner';
        b.style.cssText = 'margin:8px 0; padding:8px 14px; border-radius:8px; font-size:12px; background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.25); color:#6ee7b7;';
        b.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> <strong>Otimização aplicada:</strong> Resultados pré-computados. Executando backtest real em segundo plano...';
        const transPanel = document.getElementById('transparency-panel');
        if (transPanel) {
            transPanel.prepend(b);
            transPanel.style.display = 'block';
        }
    } else {
        optBanner.style.display = 'block';
    }

    // --- Equity Curve Chart ---
    const optCurve = sug.optimized_curve || [];
    if (optCurve.length > 0 && typeof updateCharts === 'function') {
        const dates = optCurve.map(pt => pt.date || '');
        const bankrolls = optCurve.map(pt => pt.bankroll || pt.Bankroll || 0);
        updateCharts(dates, bankrolls, [], [], [], [], [], [], null);
    }

    // --- Re-render Optimization Tab immediately (remove applied suggestion) ---
    // Filter the global list in-place so that even if a later backtest response
    // re-populates allOptimizationSuggestions, the re-render functions will still
    // exclude already-applied suggestions (they filter against appliedOptimizationSuggestions Set).
    const allSugs = window.allOptimizationSuggestions || [];
    console.log('[renderOptimizedResultsToLaboratory] allOptimizationSuggestions count:', allSugs.length, 'appliedOptimizationSuggestions:', [...window.appliedOptimizationSuggestions]);
    renderOptimizationTab(allSugs, null);
    displayOptimizationSuggestions(allSugs, false);
    console.log('[renderOptimizedResultsToLaboratory] re-render done');

    // --- Show save button ---
    const btnSave = document.getElementById('btn-save-strategy');
    if (btnSave) btnSave.style.display = 'inline-block';

    // --- Update status ---
    const btnExport = document.getElementById('btn-export-backtest');
    if (btnExport) btnExport.style.display = 'inline-flex';

    // Clear transparency/synthetic banners (they need the full backtest)
    const synthBanner = document.getElementById('synthetic-odds-banner');
    if (synthBanner) synthBanner.style.display = 'none';
    const slippageBanner = document.getElementById('slippage-banner');
    if (slippageBanner) slippageBanner.style.display = 'none';
    const mlBanner = document.getElementById('ml-active-warning-banner');
    if (mlBanner) mlBanner.style.display = 'none';
    const biasBanner = document.getElementById('selection-bias-banner');
    if (biasBanner) biasBanner.style.display = 'none';

    const btnRun = document.getElementById('btn-run-backtest');
    if (btnRun) { btnRun.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest'; btnRun.disabled = false; }
    const btnTopbar = document.getElementById('btn-topbar-run');
    if (btnTopbar) { btnTopbar.innerHTML = '<i class="fa-solid fa-play"></i> Executar'; btnTopbar.disabled = false; }

    // Also update the comparison chart in the Optimization tab
    if (typeof renderOptComparisonChart === 'function') {
        renderOptComparisonChart(sug, { equity_curve: sug.original_curve || [] });
    }
}

function applyEvSuggestion(val) {

    const evInput = document.getElementById('val-threshold');
    if (evInput) {
        evInput.value = val;
        switchTab('tab-laboratory');
        window.appliedOptimizationSuggestions.add(`ev_${val}`);
        console.log('[applyEvSuggestion] appliedOptimizationSuggestions:', [...window.appliedOptimizationSuggestions]);
        // Re-render lists IMMEDIATELY (before async runBacktest overwrites them)
        const allSugs = window.allOptimizationSuggestions || [];
        console.log('[applyEvSuggestion] allSugs count before re-render:', allSugs.length);
        renderOptimizationTab(allSugs, null);
        displayOptimizationSuggestions(allSugs, false);
        // Render pre-computed optimized results immediately
        const sug = findSuggestion('ev', val);
        console.log('[applyEvSuggestion] findSuggestion returned:', !!sug);
        if (sug) renderOptimizedResultsToLaboratory(sug);
        showToast(`Gatilho EV atualizado para ${val}. Rodando nova simulação...`, "success");
        runBacktest();
    }
}



function applyLeagueSuggestion(codes) {
    codes.forEach(code => {
        const cb = document.getElementById(`league-${code}`) || document.querySelector(`input[value="${code}"]`);
        if (cb) cb.checked = false;
    });

    switchTab('tab-laboratory');
    window.appliedOptimizationSuggestions.add(`leagues_${JSON.stringify(codes)}`);
    console.log('[applyLeagueSuggestion] appliedOptimizationSuggestions:', [...window.appliedOptimizationSuggestions]);
    // Re-render lists IMMEDIATELY (before async runBacktest overwrites them)
    const allSugs = window.allOptimizationSuggestions || [];
    console.log('[applyLeagueSuggestion] allSugs count before re-render:', allSugs.length);
    renderOptimizationTab(allSugs, null);
    displayOptimizationSuggestions(allSugs, false);
    // Render pre-computed optimized results immediately
    const sug = findSuggestion('leagues', JSON.stringify(codes));
    console.log('[applyLeagueSuggestion] findSuggestion returned:', !!sug);
    if (sug) renderOptimizedResultsToLaboratory(sug);
    showToast(`Ligas problemáticas removidas. Reexecutando backtest...`, "success");
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
    switchTab('tab-laboratory');
    window.appliedOptimizationSuggestions.add(rangeName);
    console.log('[applyOddsSuggestion] appliedOptimizationSuggestions:', [...window.appliedOptimizationSuggestions]);
    // Re-render lists IMMEDIATELY (before async runBacktest overwrites them)
    const allSugs = window.allOptimizationSuggestions || [];
    console.log('[applyOddsSuggestion] allSugs count before re-render:', allSugs.length);
    renderOptimizationTab(allSugs, null);
    displayOptimizationSuggestions(allSugs, false);
    // Render pre-computed optimized results immediately
    const sug = findSuggestion('odds_warning', rangeName);
    console.log('[applyOddsSuggestion] findSuggestion returned:', !!sug);
    if (sug) renderOptimizedResultsToLaboratory(sug);

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

        // Custom range parser like "1.50-3.00"
        if (subRange.includes('-') && !subRange.includes('Favoritos') && !subRange.includes('Equilibrado') && !subRange.includes('Baixo') && !subRange.includes('Médio')) {
            const bounds = subRange.split('-');
            if (minEl) minEl.value = bounds[0];
            if (maxEl) maxEl.value = bounds[1];
            showToast(`Filtro avançado de odds otimizado para ${bounds[0]} a ${bounds[1]}. Rodando simulação...`, "success");
            runBacktest();
            return;
        }

        if (subRange.includes('Super Favoritos') || subRange.includes('<=1.50')) {
            if (minEl) minEl.value = "1.51";
        } else if (subRange.includes('Zebras') || subRange.includes('>3.00')) {
            if (maxEl) maxEl.value = "3.00";
        } else if (subRange.includes('Favoritos (1.50-2.00)')) {
            if (minEl) minEl.value = "2.01";
        } else if (subRange.includes('Médios (2.00-3.00)')) {
            if (maxEl) maxEl.value = "2.00";
        } else if (subRange.includes('Baixo (<=3.00)')) {
            if (minEl) minEl.value = "3.01";
        } else if (subRange.includes('Alto (>3.80)')) {
            if (maxEl) maxEl.value = "3.80";
        } else if (subRange.includes('Médio (3.00-3.80)')) {
            if (maxEl) maxEl.value = "3.00";
        } else if (subRange.includes('Favorito (<=1.70)')) {
            if (minEl) minEl.value = "1.71";
        } else if (subRange.includes('Equilibrado (1.70-2.20)')) {
            if (minEl) minEl.value = "2.21";
        } else if (subRange.includes('Zebra (>2.20)')) {
            if (maxEl) maxEl.value = "2.20";
        }

        showToast(`Filtro avançado de odds otimizado. Rodando simulação...`, "success");
        runBacktest();
        return;
    }

    const minInput = document.getElementById('min-odds');
    const maxInput = document.getElementById('max-odds');

    // Custom range parser like "1.50-3.00"
    if (rangeName.includes('-') && !rangeName.includes('Favoritos') && !rangeName.includes('Equilibrado') && !rangeName.includes('Baixo') && !rangeName.includes('Médio')) {
        const bounds = rangeName.split('-');
        if (minInput) minInput.value = bounds[0];
        if (maxInput) maxInput.value = bounds[1];
        showToast(`Filtro de Odds otimizado para ${bounds[0]} a ${bounds[1]}. Rodando simulação...`, "success");
        runBacktest();
        return;
    }

    if (rangeName.includes('Super Favoritos') || rangeName.includes('<=1.50')) {
        minInput.value = "1.51";
    } else if (rangeName.includes('Zebras') || rangeName.includes('>3.00')) {
        maxInput.value = "3.00";
    } else if (rangeName.includes('Favoritos (1.50-2.00)')) {
        minInput.value = "2.01";
    } else if (rangeName.includes('Médios (2.00-3.00)')) {
        maxInput.value = "2.00";
    }

    showToast(`Filtro de Odds otimizado para excluir ${rangeName}. Rodando simulação...`, "success");
    runBacktest();
}



function clearDashboard() {
    console.log("clearDashboard() execution started.");
    try {
        const safeSetText = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val; };
        const safeSetVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
        const safeSetDisplay = (id, val) => { const el = document.getElementById(id); if (el) el.style.display = val; };
        const safeSetHTML = (id, val) => { const el = document.getElementById(id); if (el) el.innerHTML = val; };
        const safeSetWidth = (id, val) => { const el = document.getElementById(id); if (el) el.style.width = val; };

        // 1. Reset metrics
        safeSetText('metric-net-profit', '$0.00');
        safeSetText('metric-profit-stakes', '+0.00 st.');
        safeSetText('metric-roi', '0.0%');
        safeSetText('metric-win-rate', '0.0%');
        safeSetText('metric-total-bets', '0');
        safeSetText('metric-avg-odds', '1.00');
        safeSetText('metric-drawdown', '0.0%');
        safeSetText('metric-dd-duration', 'Recup: 0 apostas');
        safeSetText('metric-final-bankroll', '$0.00');
        safeSetText('metric-clv', '0.0%');
        safeSetText('metric-bcl', '0.0%');
        safeSetText('metric-matches-analyzed', '0');
        safeSetText('metric-seasons', '-');

        // Restore standard panels in case Portfolio was run
        safeSetDisplay('portfolio-results-panel', 'none');
        safeSetDisplay('standard-metrics-grid', 'grid');
        const mainCharts = document.querySelector('.main-charts');
        if (mainCharts) mainCharts.style.display = 'block';
        const resultsTableSection = document.querySelector('.results-table-section');
        if (resultsTableSection) resultsTableSection.style.display = 'block';
        const chartsGrid = document.querySelector('.charts-grid');
        if (chartsGrid) chartsGrid.style.display = 'grid';

        // Reset Classes safely
        resetMetricCard('metric-net-profit', 'card-profit');
        resetMetricCard('metric-profit-stakes', 'card-stakes');
        resetMetricCard('metric-roi', 'card-roi');
        resetMetricCard('metric-clv', 'card-clv');
        resetMetricCard('metric-bcl', 'card-bcl');

        function resetMetricCard(h2Id, cardClass) {
            var el = document.getElementById(h2Id);
            if (el) {
                el.style.color = '';
                var card = el.closest('.metric-card');
                if (card) {
                    card.className = 'metric-card ' + cardClass;
                }
            }
        }
        // Reset winrate
        var wrEl = document.getElementById('metric-win-rate');
        if (wrEl) { wrEl.style.color = ''; }
        var wrCard = document.querySelector('.card-winrate');
        if (wrCard) { wrCard.className = 'metric-card card-winrate'; }
        // Reset profit/stakes cards that came through different path
        ['card-profit', 'card-stakes'].forEach(function(cls) {
            var card = document.querySelector('.' + cls);
            if (card) { card.className = 'metric-card ' + cls; }
        });

        // Reset advanced metrics
        safeSetText('metric-sharpe', '0.00');
        safeSetText('metric-sortino', '0.00');
        safeSetText('metric-skewness', '0.00');
        safeSetText('metric-consec-wins', '0');
        safeSetText('metric-consec-losses', '0');

        // Reset Portfolio Allocator
        safeSetDisplay('portfolio-allocator-panel', 'none');
        safeSetHTML('allocator-bars-container', '');
        safeSetText('allocator-expected-return', '+0.00%');
        safeSetText('allocator-volatility', '0.00%');
        safeSetText('allocator-sharpe', '0.00');

        // Clear pre-match calculator bookmakers table
        safeSetHTML('calc-bookmakers-tbody', '');

        // Hide and reset Quartiles panel
        safeSetDisplay('quartiles-panel', 'none');
        safeSetDisplay('staking-comparison-panel', 'none');

        // Hide and reset EQS Risk panel
        const riskEmpty = document.getElementById('risk-empty-state');
        const riskContent = document.getElementById('risk-content');
        if (riskEmpty && riskContent) {
            riskEmpty.style.display = 'block';
            riskContent.style.display = 'none';
            switchTab('tab-laboratory');
        }

        for (let i = 1; i <= 4; i++) {
            safeSetText(`q${i}-profit`, '$0.00');
            safeSetText(`q${i}-stakes`, '0.00 st.');
            safeSetText(`q${i}-roi`, '0.0%');
            safeSetText(`q${i}-winrate`, '0.0%');
            safeSetText(`q${i}-bets`, '0');
        }

        // 2. Clear charts
        clearCharts();

        // 3. Clear bets cache and table
        if (typeof window.allBets !== 'undefined') { window.allBets = []; }
        safeSetHTML('bets-table-body', `<tr><td colspan="10" class="text-center empty-state"><i class="fa-solid fa-info-circle"></i> Configure os filtros ao lado e execute o backtest para ver os resultados.</td></tr>`);

        // 4. Hide AI & Optimization panels and reset Monte Carlo UI
        safeSetDisplay('ai-analytics-panel', 'none');
        safeSetDisplay('ai-optimization-panel', 'none');

        // Hide statistical validation and OOS panels
        const statPanel = document.getElementById('stat-validation-panel');
        if (statPanel) { statPanel.style.display = 'none'; safeSetHTML('stat-validation-grid', ''); }

        const oosPanel = document.getElementById('oos-results-panel');
        if (oosPanel) { oosPanel.style.display = 'none'; safeSetHTML('oos-metrics-grid', ''); }

        const driftPanel = document.getElementById('drift-validation-panel');
        if (driftPanel) { driftPanel.style.display = 'none'; safeSetHTML('drift-validation-content', ''); }

        safeSetHTML('ai-checklist-container', `<div class="ai-report-text" style="color: var(--text-muted);">Aguardando a execução do backtest para gerar o checklist.</div>`);

        safeSetText('mc-profit-probability', '0.0%');
        safeSetWidth('mc-profit-progress', '0%');
        safeSetText('mc-ruin-probability', '0.0%');
        safeSetText('mc-half-ruin-probability', '0.0%');
        safeSetWidth('mc-ruin-progress', '0%');
        safeSetText('mc-median-profit', '+$0.00');
        const mp = document.getElementById('mc-median-profit'); if(mp) mp.className = 'widget-value';
        safeSetText('mc-percentile-5', '$0.00');
        const p5 = document.getElementById('mc-percentile-5'); if(p5) p5.className = 'half-val';
        safeSetText('mc-percentile-95', '$0.00');
        const p95 = document.getElementById('mc-percentile-95'); if(p95) p95.className = 'half-val';

        // Reset active strategy banner
        safeSetDisplay('active-strategy-banner', 'none');
        safeSetText('active-leagues-text', 'N/A');
        safeSetText('active-market-text', 'N/A');
        safeSetText('active-odds-text', '1.00 - 2.50');
        safeSetText('active-ev-text', '1.05');

        // Reset Staking Recommendations
        safeSetText('rec-stake-size', '0.0%');
        safeSetText('rec-consec-losses', '0');
        safeSetText('rec-min-bankroll', '$0.00');
        safeSetText('rec-justification', 'Aguardando a execução do backtest para gerar a análise de banca.');
        safeSetDisplay('rec-justification-box', 'none');

        // 5. Clear backtest state (excluding Scanner)
        if (typeof window.lastBacktestSummary !== 'undefined') { window.lastBacktestSummary = null; }
        if (typeof window.lastBacktestParams !== 'undefined') { window.lastBacktestParams = null; }
        
        safeSetDisplay('btn-export-backtest', 'none');
        safeSetHTML('eqs-table-container', '');

        // Clear Calculator results
        safeSetDisplay('calc-results', 'none');
        safeSetDisplay('calc-heatmap-container', 'none');
        safeSetVal('calc-league', "");
        safeSetHTML('calc-home-team', '<option value="" disabled selected>Selecione...</option>');
        safeSetHTML('calc-away-team', '<option value="" disabled selected>Selecione...</option>');
        const ht = document.getElementById('calc-home-team'); if(ht) ht.disabled = true;
        const at = document.getElementById('calc-away-team'); if(at) at.disabled = true;

        showToast("Dashboard limpo! Pronto para uma nova simulação.", "info");
    } catch (err) {
        console.error("Erro ao limpar dashboard:", err);
        showToast("Dashboard parcialmente limpo.", "warning");
    }
}

function clearScannerResults() {
    try {
        const safeSetHTML = (id, val) => { const el = document.getElementById(id); if (el) el.innerHTML = val; };
        const safeSetDisplay = (id, val) => { const el = document.getElementById(id); if (el) el.style.display = val; };
        
        safeSetHTML('global-scanner-results', '');
        safeSetHTML('eqs-table-container', '');
        safeSetDisplay('scanner-results', 'none');
        
        if (typeof window.lastScanResults !== 'undefined') { window.lastScanResults = null; }
        if (typeof window.lastScanParams !== 'undefined') { window.lastScanParams = null; }
        
        showToast("Resultados do scanner limpos!", "info");
    } catch (err) {
        console.error("Erro ao limpar scanner:", err);
    }
}

function clearClusterResults() {
    try {
        document.getElementById("clustering-loading").style.display = "none";
        document.getElementById("clustering-results").style.display = "none";
        const canvas = document.getElementById('clusterChart');
        if (canvas) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
        const clusterList = document.getElementById('cluster-groups-container');
        if (clusterList) {
            clusterList.innerHTML = '';
        }
        showToast("Resultados de clusterização limpos!", "info");
    } catch (err) {
        console.error("Erro ao limpar clusterização:", err);
    }
}

window.clearScannerResults = clearScannerResults;
window.clearClusterResults = clearClusterResults;



// ==========================================================================

import './js/calculator.js';
import './js/telegram.js';
import './js/history.js?v=4';
import './js/arbitrage.js?v=1';
import './js/clustering.js?v=4';
import './js/state.js';
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

    // 2b. Bootstrap Drawdown Confidence Interval
    if (summary.bootstrap_drawdown_ci_lower !== undefined) {
        const ddLower = summary.bootstrap_drawdown_ci_lower;
        const ddUpper = summary.bootstrap_drawdown_ci_upper;
        const ddMedian = summary.bootstrap_drawdown_median;
        const ddColor = ddUpper < 25 ? 'var(--success)' : ddUpper < 40 ? 'var(--warning)' : 'var(--danger)';
        const ddTooltip = 'Intervalo de confianca de 95% do drawdown maximo obtido por reamostragem bootstrap (5.000 simulacoes).';
        grid.innerHTML += `
            <div class="stat-card" title="${ddTooltip}" onclick="showToast(this.title, 'info')">
                <div class="stat-label"><i class="fa-solid fa-arrow-trend-down"></i> Drawdown Bootstrap (95% IC)</div>
                <div class="stat-value" style="color: ${ddColor};">${ddMedian !== undefined ? fmtNum(ddMedian, 1) : '?'}%</div>
                <div class="stat-detail">
                    IC 95%: <strong style="color: ${ddColor};">${fmtNum(ddLower, 1)}%</strong> — <strong>${fmtNum(ddUpper, 1)}%</strong>
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
    const stressPanel = document.getElementById('robustness-stress-panel');

    if (!panel || !grid) return;

    if (!oosSummary) {
        panel.style.display = 'none';
        if (stressPanel) stressPanel.style.display = 'none';
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

    // Render Robustness & Slippage Stress tables
    const oosTbody = document.getElementById('oos-stress-tbody');
    const slipTbody = document.getElementById('slippage-stress-tbody');
    
    if (stressPanel) {
        if (inSampleSummary && inSampleSummary.oos_robustness_matrix && inSampleSummary.slippage_sensitivity) {
            stressPanel.style.display = 'block';
            
            // Render OOS splits
            if (oosTbody) {
                oosTbody.innerHTML = inSampleSummary.oos_robustness_matrix.map(row => {
                    const activeClass = (row.split_pct === inSampleSummary.oos_split_pct) ? 'style="background: rgba(139, 92, 246, 0.15); font-weight: bold;"' : '';
                    const roiColor = row.roi >= 0 ? '#34d399' : '#f87171';
                    return `
                        <tr ${activeClass}>
                            <td style="padding: 6px;">${row.split_pct}% ${row.split_pct === inSampleSummary.oos_split_pct ? '<b>(Ativo)</b>' : ''}</td>
                            <td style="padding: 6px; text-align: center;">${row.total_bets}</td>
                            <td style="padding: 6px; text-align: right; color: ${row.net_profit >= 0 ? '#34d399' : '#f87171'};">${row.net_profit >= 0 ? '+' : ''}$${row.net_profit.toFixed(2)}</td>
                            <td style="padding: 6px; text-align: right; color: ${roiColor};">${row.roi >= 0 ? '+' : ''}${row.roi.toFixed(2)}%</td>
                            <td style="padding: 6px; text-align: right;">${row.win_rate.toFixed(1)}%</td>
                        </tr>
                    `;
                }).join('');
            }
            
            // Render Slippage scenarios
            if (slipTbody) {
                slipTbody.innerHTML = inSampleSummary.slippage_sensitivity.map(row => {
                    let label = 'N/A';
                    let color = '#888888';
                    const activeSlippage = inSampleSummary.slippage_pct || 0.0;
                    const activeClass = (row.extra_slippage_pct === 0) ? 'style="background: rgba(16, 185, 129, 0.1); font-weight: bold;"' : '';
                    
                    if (row.extra_slippage_pct === 0) {
                        label = `Cenário Base (Slippage: ${activeSlippage}%)`;
                        color = 'var(--text-primary)';
                    } else if (row.extra_slippage_pct === 1) {
                        label = 'Slippage Extra (+1%)';
                        color = 'var(--text-secondary)';
                    } else if (row.extra_slippage_pct === 3) {
                        label = 'Slippage Extra (+3%)';
                        color = 'var(--warning)';
                    } else if (row.extra_slippage_pct === 5) {
                        label = 'Slippage Extra (+5%)';
                        color = '#ef4444';
                    }
                    
                    const roiColor = row.roi >= 0 ? '#34d399' : '#f87171';
                    return `
                        <tr ${activeClass}>
                            <td style="padding: 6px; color: ${color};">${label}</td>
                            <td style="padding: 6px; text-align: center;">+${row.extra_slippage_pct}%</td>
                            <td style="padding: 6px; text-align: right; color: ${roiColor}; font-weight: 600;">${row.roi >= 0 ? '+' : ''}${row.roi.toFixed(2)}%</td>
                        </tr>
                    `;
                }).join('');
            }
        } else {
            stressPanel.style.display = 'none';
        }
    }

    // Badge comparing OOS ROI vs in-sample ROI
    if (badge && inSampleSummary) {
        const isROI = inSampleSummary.roi;
        const oosROI = oosSummary.roi;
        const sameSign = (isROI >= 0 && oosROI >= 0) || (isROI < 0 && oosROI < 0);
        const isImproved = oosROI >= isROI;
        let degradation = 0;

        if (!isImproved && isROI !== 0) {
            degradation = Math.abs((isROI - oosROI) / Math.abs(isROI));
        }

        if (isImproved) {
            badge.className = 'oos-badge oos-pass';
            badge.innerHTML = '<i class="fa-solid fa-circle-arrow-up"></i> Melhorado';
            badge.style.cssText = 'background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);';
        } else if (sameSign && degradation <= 0.5) {
            badge.className = 'oos-badge oos-pass';
            badge.innerHTML = '<i class="fa-solid fa-check"></i> Consistente';
            badge.style.cssText = '';
        } else if (sameSign) {
            badge.className = 'oos-badge oos-warn';
            badge.innerHTML = '<i class="fa-solid fa-exclamation"></i> Degradado';
            badge.style.cssText = '';
        } else {
            badge.className = 'oos-badge oos-fail';
            badge.innerHTML = '<i class="fa-solid fa-xmark"></i> Invertido';
            badge.style.cssText = '';
        }
    }
}

function renderDriftValidation(aiAnalysis, results) {
    const panel = document.getElementById('drift-validation-panel');
    const container = document.getElementById('drift-validation-content');
    if (!panel || !container) return;
    
    if (!aiAnalysis || aiAnalysis.status === 'insufficient_data') {
        panel.style.display = 'none';
        return;
    }
    
    panel.style.display = 'block';
    
    const driftRatio = aiAnalysis.drift_ratio;
    const totalBets = results.summary.total_bets;
    const oosSummary = aiAnalysis.oos_summary;
    const oosRoi = oosSummary ? oosSummary.roi : null;
    const stakeRule = document.getElementById('stake-rule').value;
    
    let verdict = 'NEUTRO';
    let statusClass = 'drift-neutral';
    let badgeStyle = 'background: rgba(156, 163, 175, 0.15); color: #9ca3af; border: 1px solid rgba(156, 163, 175, 0.3);';
    let cenarioTitulo = 'Volume de Amostra Reduzido';
    let recomendacaoText = 'A amostragem de apostas é pequena demais (menos de 120 apostas). O desvio observado na performance de curto prazo pode ser apenas ruído estatístico temporário. Continue acumulando dados.';
    
    if (totalBets >= 120) {
        if (driftRatio >= -3.0) {
            verdict = 'APROVADO';
            statusClass = 'drift-approved';
            badgeStyle = 'background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);';
            cenarioTitulo = 'Estabilidade Temporal Confirmada';
            recomendacaoText = 'Aprovado: O Edge da estratégia é estável e resiliente. O rendimento manteve-se equilibrado entre a primeira e a segunda metades do histórico, indicando que a estratégia não está obsoleta.';
        } else if (oosRoi !== null && oosRoi >= 0.0) {
            verdict = 'APROVADO';
            statusClass = 'drift-warn';
            badgeStyle = 'background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3);';
            cenarioTitulo = 'Distorção de Gestão de Banca Detectada';
            if (stakeRule !== 'fixed') {
                recomendacaoText = 'Aprovado com Cautela: Embora o Drift de ROI consolidado seja negativo devido ao crescimento exponencial das stakes (efeito de compounding do Kelly/Proporcional), a validação Fora-da-Amostra (OOS) permanece altamente lucrativa (+ ' + oosRoi.toFixed(1) + '% ROI). O sinal puro do Edge continua ativo. Recomendamos utilizar 0.5x (metade) da stake padrão para controle de variância.';
            } else {
                recomendacaoText = 'Aprovado com Cautela: A estratégia apresentou uma perda de rendimento na segunda metade do histórico, mas a validação recente Fora-da-Amostra (OOS) manteve-se lucrativa (+ ' + oosRoi.toFixed(1) + '% ROI). O Edge ainda está ativo. Opere com exposição de capital reduzida.';
            }
        } else {
            verdict = 'REJEITADO';
            statusClass = 'drift-rejected';
            badgeStyle = 'background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3);';
            cenarioTitulo = 'Perda de Vantagem Matemática (Edge Decay)';
            recomendacaoText = 'Rejeitado: O mercado se ajustou e a estratégia perdeu o edge matemático. Tanto o histórico recente (Drift) quanto a validação fora da amostra (OOS) estão em declínio. Risco de ruína elevado no longo prazo. Recomendamos não operar com dinheiro real.';
        }
    }
    
    container.innerHTML = `
        <div style="background: rgba(255, 255, 255, 0.01); border: 1px solid rgba(255, 255, 255, 0.04); border-radius: 8px; padding: 18px; display: grid; grid-template-columns: 140px 1fr; gap: 20px; align-items: center;">
            <div style="text-align: center; border-right: 1px solid rgba(255, 255, 255, 0.05); padding-right: 20px;">
                <span style="font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); display: block; margin-bottom: 6px; font-weight: 600;">Veredito do Drift</span>
                <span class="drift-verdict-badge ${statusClass}" style="font-size: 15px; font-weight: bold; padding: 6px 14px; border-radius: 4px; display: inline-block; ${badgeStyle}">${verdict}</span>
            </div>
            <div>
                <h5 style="margin: 0 0 6px 0; font-size: 13.5px; color: var(--text-primary); font-weight: 600; display: flex; align-items: center; gap: 6px;">
                    <i class="fa-solid fa-circle-exclamation" style="font-size: 12px; color: ${statusClass === 'drift-approved' ? '#10b981' : (statusClass === 'drift-warn' ? '#fbbf24' : (statusClass === 'drift-rejected' ? '#ef4444' : '#9ca3af'))};"></i>
                    ${cenarioTitulo}
                </h5>
                <p style="margin: 0; font-size: 12.5px; color: var(--text-secondary); line-height: 1.45;">${recomendacaoText}</p>
            </div>
        </div>
    `;
}

// --- Edge Quality Score & Risk Management ---







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

            const maxVal = item.max || 1;
            const isInsufficient = item.insufficient === true || item.max === 0;
            const pct = isInsufficient ? 0 : (item.points / maxVal) * 100;

            let iconColor = 'var(--danger)';

            let iconClass = 'fa-xmark';

            if (isInsufficient) {

                iconColor = 'var(--text-muted)';

                iconClass = 'fa-minus';

            } else if (pct >= 80) {

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

                    <div style="font-size: 16px; font-weight: bold; font-family: var(--font-heading); color: ${iconColor};">${isInsufficient ? '—' : item.points}<span style="font-size: 12px; color: var(--text-muted);">${isInsufficient ? '' : '/' + item.max}</span></div>

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
    if (scanType === 'staking') activeBtn = document.getElementById('btn-eqs-scan-staking');

    

    const allBtns = [btnEqsMarkets, btnEqsLeagues, btnEqsCombinations, document.getElementById('btn-eqs-scan-staking')];

    

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
        odds_timing: document.getElementById('odds-timing') ? document.getElementById('odds-timing').value : 'closing',
        scanType: scanType,

        minOdds: parseFloat(document.getElementById('min-odds').value) || 1.0,

        maxOdds: parseFloat(document.getElementById('max-odds').value) || 2.50,

        use_ml: document.getElementById('use-ml-toggle')?.checked || false,
        model_type: document.getElementById('model-type-select')?.value || 'poisson',

        data_source: window.currentDataSource,

        futpython_api_key: window.futpythonApiKey

    };

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/scan`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(requestData),

            cache: 'no-store'

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

        

        renderEqsResults(sortedResults, scanType, requestData, data.diagnostics);

        switchTab('tab-scanner');

        

    } catch (err) {

        showToast(err.message, "error");

    } finally {

        activeBtn.classList.remove('scanning');

        activeBtn.innerHTML = originalText;

        allBtns.forEach(btn => btn.disabled = false);

    }

}



function renderEqsResults(results, scanType, requestData, diagnostics) {
    const resultsContainer = document.getElementById('global-scanner-results');
    resultsContainer.innerHTML = '';

    if (results.length === 0) {
        let diagHtml = '';
        if (diagnostics) {
            const leaguesLoaded = Object.entries(diagnostics.leagues_loaded || {}).map(([code, count]) => {
                const isZero = count === 0;
                return `<li style="margin-bottom: 4px; color: ${isZero ? '#ef4444' : 'var(--text-secondary)'};">
                    <b>${code}:</b> ${count} jogos carregados ${isZero ? '⚠️ (API ou Cache vazios!)' : '✅'}
                </li>`;
            }).join('');

            const errorsHtml = (diagnostics.errors || []).map(err => {
                return `<div style="color: #f87171; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); padding: 8px 12px; border-radius: 4px; font-size: 11px; margin-top: 8px; text-align: left;">
                    <i class="fa-solid fa-circle-exclamation"></i> ${err}
                </div>`;
            }).join('');

            diagHtml = `
                <div class="diagnostics-panel" style="margin-top: 25px; padding: 20px; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; max-width: 600px; margin-left: auto; margin-right: auto; text-align: left;">
                    <h4 style="margin-top: 0; color: var(--primary); font-size: 14px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
                        <i class="fa-solid fa-microscope"></i> Relatório de Diagnóstico do Scanner
                    </h4>
                    <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 10px;">
                        Fonte de dados consultada: <span style="color: var(--text-primary); font-weight: bold; text-transform: uppercase;">${diagnostics.data_source || requestData.data_source}</span>
                    </p>
                    <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 12px;">
                        <b>Carregamento por Liga:</b>
                        <ul style="margin: 6px 0 0 0; padding-left: 20px;">
                            ${leaguesLoaded || '<li style="color:var(--text-muted);">Nenhuma liga processada.</li>'}
                        </ul>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 11px; color: var(--text-secondary); border-top: 1px solid rgba(255,255,255,0.05); padding-top: 12px; margin-top: 12px;">
                        <div>Jogos Combinados: <b style="color: var(--text-primary);">${diagnostics.total_combined_matches || 0}</b></div>
                        <div>Jogos no Período Ativo: <b style="color: var(--text-primary);">${diagnostics.total_active_period_matches || 0}</b></div>
                        <div>Apostas Simuladas: <b style="color: var(--text-primary);">${diagnostics.total_bets_placed || 0}</b></div>
                    </div>
                    ${errorsHtml}
                </div>
            `;
        }

        resultsContainer.innerHTML = `
            <div class="empty-state text-center" style="padding: 40px 20px;">
                <i class="fa-solid fa-triangle-exclamation" style="font-size: 48px; opacity: 0.2; margin-bottom: 15px; display: block; color: var(--warning);"></i>
                <p style="font-size: 16px; margin-bottom: 5px;">Nenhum ${scanType === 'markets' ? 'mercado' : 'liga'} atendeu aos critérios rigorosos de aprovação Institucional.</p>
                <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 20px;">Tente ajustar as datas, odd mínima/máxima ou o value threshold.</p>
                ${diagHtml}
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

    } else if (scanType === 'staking') {
        // Staking Comparison Table with sortable columns
        const leaguesCount = requestData.leagues.length;
        const marketsCount = requestData.market.length || 33;
        leaguesContextHtml = `
            <div style="margin-bottom: 15px; padding: 10px 15px; background: rgba(0,0,0,0.2); border-left: 3px solid var(--primary); border-radius: 4px;">
                <span style="color: var(--text-muted); font-size: 13px;">
                    <i class="fa-solid fa-scale-balanced" style="margin-right: 5px;"></i>
                    Comparando Fixed vs Proporcional vs Kelly em <b>${leaguesCount} liga(s) x ${marketsCount} mercado(s)</b>.
                </span>
            </div>
        `;
        const METHOD_LABELS = {
            fixed:       { label: "Fixa ($10)",   color: "#f59e0b" },
            proportional: { label: "Prop (2%)",    color: "#3b82f6" },
            kelly:        { label: "Kelly (1/4)",  color: "#34d399" },
        };

        // Sort state for this staking table
        window._stakingSort = { col: null, asc: true };

        const COLUMNS = [
            { key: 'name',         label: 'Liga / Mercado',  align: 'left',   color: 'var(--text-muted)', sortType: 'str' },
            { key: 'total_bets',   label: 'Apostas',         align: 'center', color: 'var(--text-muted)', sortType: 'num' },
            { key: 'fixed_roi',    label: 'Fixed ROI',       align: 'right',  color: '#f59e0b',             sortType: 'num' },
            { key: 'fixed_dd',     label: 'Fixed DD',        align: 'right',  color: '#f59e0b',             sortType: 'num' },
            { key: 'prop_roi',     label: 'Prop ROI',        align: 'right',  color: '#3b82f6',             sortType: 'num' },
            { key: 'prop_dd',      label: 'Prop DD',         align: 'right',  color: '#3b82f6',             sortType: 'num' },
            { key: 'kelly_roi',    label: 'Kelly ROI',       align: 'right',  color: '#34d399',             sortType: 'num' },
            { key: 'kelly_dd',     label: 'Kelly DD',        align: 'right',  color: '#34d399',             sortType: 'num' },
            { key: 'best_method',  label: 'Melhor Gestao',   align: 'center', color: 'var(--text-muted)', sortType: 'str' },
        ];

        function _extractValue(r, colKey) {
            switch (colKey) {
                case 'name':         return r.name || '';
                case 'total_bets':   return r.total_bets || 0;
                case 'fixed_roi':    return (r.fixed && r.fixed.roi) || 0;
                case 'fixed_dd':     return (r.fixed && r.fixed.max_drawdown) || 0;
                case 'prop_roi':     return (r.proportional && r.proportional.roi) || 0;
                case 'prop_dd':      return (r.proportional && r.proportional.max_drawdown) || 0;
                case 'kelly_roi':    return (r.kelly && r.kelly.roi) || 0;
                case 'kelly_dd':     return (r.kelly && r.kelly.max_drawdown) || 0;
                case 'best_method':  return r.best_method || 'fixed';
                default: return 0;
            }
        }

        function _renderStakingTbody(sortedResults) {
            return sortedResults.map(r => {
                const methods = ['fixed', 'proportional', 'kelly'];
                const best = r.best_method || 'fixed';
                return `
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                        <td style="padding: 10px 15px; font-size: 11px;">
                            ${r.name.replace(' / ', ' <i class="fa-solid fa-angle-right" style="color:var(--text-muted); font-size:9px;"></i> ')}
                        </td>
                        <td style="padding: 10px 15px; text-align: center; font-size: 12px;">${r.total_bets}</td>
                        ${methods.map(m => {
                            const d = r[m] || {};
                            const roiColor = d.roi >= 0 ? 'var(--success)' : 'var(--danger)';
                            const methodColor = METHOD_LABELS[m].color;
                            return `
                                <td style="padding: 10px 15px; text-align: right; color: ${roiColor}; font-weight: 500; font-size: 13px; background: ${best === m ? methodColor + '15' : 'transparent'};">${(d.roi || 0).toFixed(1)}%</td>
                                <td style="padding: 10px 15px; text-align: right; color: var(--danger); font-size: 12px; opacity: ${(d.max_drawdown || 0) > 20 ? 1 : 0.6}; background: ${best === m ? methodColor + '15' : 'transparent'};">-${(d.max_drawdown || 0).toFixed(1)}%</td>
                            `;
                        }).join('')}
                        <td style="padding: 10px 15px; text-align: center;">
                            <span style="background: ${METHOD_LABELS[best].color}20; color: ${METHOD_LABELS[best].color}; padding: 4px 10px; border-radius: 4px; font-size: 10px; font-weight: bold; text-transform: uppercase;">
                                ${METHOD_LABELS[best].label}
                            </span>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        // Store sort helpers on window so inline onclick can reach them
        window._stakingSortData = {
            results,
            COLUMNS,
            METHOD_LABELS,
            _extractValue,
            _renderStakingTbody,
        };
        window._stakingSortClick = function(colKey) {
            const s = window._stakingSort;
            const d = window._stakingSortData;
            if (s.col === colKey) {
                s.asc = !s.asc;
            } else {
                s.col = colKey;
                s.asc = true;
            }
            const colDef = d.COLUMNS.find(c => c.key === colKey);
            const sorted = [...d.results].sort((a, b) => {
                const va = d._extractValue(a, colKey);
                const vb = d._extractValue(b, colKey);
                let cmp;
                if (colDef && colDef.sortType === 'num') {
                    cmp = (va || 0) - (vb || 0);
                } else {
                    cmp = String(va).localeCompare(String(vb));
                }
                return s.asc ? cmp : -cmp;
            });
            const tbody = document.getElementById('staking-comparison-tbody');
            if (tbody) tbody.innerHTML = d._renderStakingTbody(sorted);
            document.querySelectorAll('#staking-comparison-table thead th').forEach(th => {
                const arrow = th.querySelector('.sort-arrow');
                if (arrow) {
                    const thKey = th.getAttribute('data-sort-key');
                    if (thKey === s.col) {
                        arrow.textContent = s.asc ? ' ▲' : ' ▼';
                        arrow.style.opacity = '1';
                    } else {
                        arrow.textContent = ' ▲';
                        arrow.style.opacity = '0.3';
                    }
                }
            });
        };

        const headerCells = COLUMNS.map(c => {
            return `<th data-sort-key="${c.key}" onclick="window._stakingSortClick('${c.key}')" style="padding: 12px 15px; text-align: ${c.align}; font-size: 12px; color: ${c.color}; text-transform: uppercase; cursor: pointer; user-select: none; white-space: nowrap;">${c.label}<span class="sort-arrow" style="opacity: 0.3; font-size: 10px;"> ▲</span></th>`;
        }).join('');

        const stakingHtml = `
            ${leaguesContextHtml}
            <div class="eqs-legend" style="margin-bottom: 20px; padding: 15px; background: var(--bg-secondary); border-radius: 8px; border: 1px solid rgba(255,255,255,0.05);">
                <h4 style="margin: 0 0 10px 0; font-size: 14px; color: var(--text-primary);"><i class="fa-solid fa-scale-balanced"></i> Comparacao de Gestoes de Banca</h4>
                <div style="display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 8px;">
                    ${Object.entries(METHOD_LABELS).map(([k,v]) => `
                        <div style="display: flex; align-items: center; gap: 6px;">
                            <span style="width: 12px; height: 12px; border-radius: 3px; background: ${v.color};"></span>
                            <span style="font-size: 12px; color: var(--text-muted);"><b>${v.label}</b></span>
                        </div>
                    `).join('')}
                </div>
                <span style="font-size: 11px; color: var(--text-muted);"><i class="fa-solid fa-arrow-up-wide-short"></i> Clique nos cabecalhos para ordenar</span>
            </div>
            <table id="staking-comparison-table" class="scanner-table" style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                <thead>
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.2);">
                        ${headerCells}
                    </tr>
                </thead>
                <tbody id="staking-comparison-tbody">
                    ${_renderStakingTbody(results)}
                </tbody>
            </table>
        `;
        window._stakingSort = { col: null, asc: true };
        resultsContainer.innerHTML = stakingHtml;
        window.lastEqsScanParams = requestData;
        return;


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

                <div style="display: flex; align-items: center; gap: 8px; margin-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 8px;">

                    <span style="font-size: 11px; color: var(--text-muted);"><i class="fa-solid fa-sliders"></i> Thresholds adaptativos: amostras pequenas (&lt;80 apostas) usam criterios relaxados de significancia.</span>

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
                                ${r.eqs_percentile_market != null ? `<div style="font-size: 9px; color: var(--primary); margin-top: 3px; white-space: nowrap;"><i class="fa-solid fa-trophy"></i> Top ${100 - r.eqs_percentile_market}% mercado</div>` : ''}
                                ${r.eqs_percentile_bets != null ? `<div style="font-size: 9px; color: var(--text-muted); margin-top: 1px; white-space: nowrap;">Top ${100 - r.eqs_percentile_bets}% ${r.eqs_percentile_bets_label ? r.eqs_percentile_bets_label.replace('Top entre ', '') : ''}</div>` : ''}

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

window.runSpecificEqsBacktest = async function(scanType, code, optRange) {
    try {
        if (!window.lastEqsScanParams) return;

        switchTab('tab-laboratory');

        // Sincroniza a fonte de dados do painel lateral caso seja diferente (apenas visual, para consistência da UI)
        if (window.lastEqsScanParams.data_source && document.getElementById('data-source-select')) {
            const dsSelect = document.getElementById('data-source-select');
            if (dsSelect.value !== window.lastEqsScanParams.data_source) {
                dsSelect.value = window.lastEqsScanParams.data_source;
                window.currentDataSource = window.lastEqsScanParams.data_source;
                const topbarSelect = document.getElementById('topbar-data-source');
                if (topbarSelect) topbarSelect.value = window.lastEqsScanParams.data_source;
            }
        }
        window.currentDataSource = window.lastEqsScanParams.data_source || window.currentDataSource;

        // Constrói overrideParams diretamente — sem manipular DOM checkboxes
        const p = window.lastEqsScanParams;
        const overrideParams = {
            leagues: [],
            startDate: p.startDate,
            endDate: p.endDate,
            market: [],
            valueThreshold: p.valueThreshold !== undefined ? p.valueThreshold : 1.05,
            initialBankroll: p.initialBankroll !== undefined ? p.initialBankroll : 1000.0,
            stakingRule: p.stakingRule || 'fixed',
            stakeValue: p.stakeValue !== undefined ? p.stakeValue : 10.0,
            oddsSource: p.oddsSource || 'B365',
            odds_timing: p.odds_timing || 'closing',
            minOdds: p.minOdds || 1.0,
            maxOdds: p.maxOdds || 2.50,
            exchange_commission: p.exchange_commission !== undefined ? p.exchange_commission : 0.0,
            out_of_sample: true,
            oos_split: p.oos_split !== undefined ? p.oos_split : 20.0,
            slippage: p.slippage !== undefined ? p.slippage : 2.0,
            use_ml: p.use_ml !== undefined ? p.use_ml : false,
            data_source: p.data_source,
            futpython_api_key: p.futpython_api_key,
            minOddsH: p.minOddsH !== undefined ? p.minOddsH : null,
            maxOddsH: p.maxOddsH !== undefined ? p.maxOddsH : null,
            minOddsD: p.minOddsD !== undefined ? p.minOddsD : null,
            maxOddsD: p.maxOddsD !== undefined ? p.maxOddsD : null,
            minOddsA: p.minOddsA !== undefined ? p.minOddsA : null,
            maxOddsA: p.maxOddsA !== undefined ? p.maxOddsA : null,
            minOddsOver25: p.minOddsOver25 !== undefined ? p.minOddsOver25 : null,
            maxOddsOver25: p.maxOddsOver25 !== undefined ? p.maxOddsOver25 : null,
            minOddsUnder25: p.minOddsUnder25 !== undefined ? p.minOddsUnder25 : null,
            maxOddsUnder25: p.maxOddsUnder25 !== undefined ? p.maxOddsUnder25 : null
        };

        // Aplica optRange ao valueThreshold e min/max odds, se houver
        if (optRange) {
            if (optRange.includes('EV > 1.25')) overrideParams.valueThreshold = 1.25;
            else if (optRange.includes('EV > 1.15')) overrideParams.valueThreshold = 1.15;
            else if (optRange.includes('EV > 1.10')) overrideParams.valueThreshold = 1.10;
            else if (optRange.includes('EV > 1.05')) overrideParams.valueThreshold = 1.05;

            if (optRange.includes('<= 1.50') && !optRange.includes('Excluir')) { overrideParams.minOdds = 1.0; overrideParams.maxOdds = 1.50; }
            else if (optRange.includes('1.50 - 2.00')) { overrideParams.minOdds = 1.50; overrideParams.maxOdds = 2.00; }
            else if (optRange.includes('2.00 - 3.00')) { overrideParams.minOdds = 2.00; overrideParams.maxOdds = 3.00; }
            else if (optRange.includes('> 3.00') && !optRange.includes('<=')) { overrideParams.minOdds = 3.00; overrideParams.maxOdds = 50.0; }
            else if (optRange.includes('<= 3.00')) { overrideParams.minOdds = 1.0; overrideParams.maxOdds = 3.00; }
            else if (optRange.includes('> 1.50') && !optRange.includes('<=')) { overrideParams.minOdds = 1.50; overrideParams.maxOdds = 50.0; }
        }

        // Determina ligas e mercados para cada tipo de scan
        if (scanType === 'markets') {
            overrideParams.leagues = p.leagues || [];
            overrideParams.market = [code];
        } else if (scanType === 'leagues') {
            overrideParams.leagues = [code];
            overrideParams.market = p.market && p.market.length > 0 ? p.market : null; // null = all markets
        } else if (scanType === 'combinations') {
            const parts = code.split('|');
            if (parts.length === 2) {
                overrideParams.leagues = [parts[0]];
                overrideParams.market = [parts[1]];
            }
        }

        // Atualiza a sidebar visualmente para refletir o estado (sem disparar eventos que causem fetch)
        document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]').forEach(cb => {
            const shouldBeChecked = overrideParams.leagues.some(l => l.toLowerCase() === cb.value.toLowerCase());
            cb.checked = shouldBeChecked;
        });
        document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]').forEach(cb => {
            const shouldBeChecked = overrideParams.market && overrideParams.market.length > 0
                ? overrideParams.market.some(m => (m || '').toLowerCase() === cb.value.toLowerCase() || (m || '').toLowerCase() === cb.value.replace('1x2_', '').toLowerCase())
                : false;
            cb.checked = shouldBeChecked;
        });
        // Atualiza campos visuais do formulário
        document.getElementById('start-date').value = overrideParams.startDate || '';
        document.getElementById('end-date').value = overrideParams.endDate || '';
        document.getElementById('val-threshold').value = overrideParams.valueThreshold;
        document.getElementById('min-odds').value = overrideParams.minOdds;
        document.getElementById('max-odds').value = overrideParams.maxOdds;
        const oosToggle = document.getElementById('oos-toggle');
        if (oosToggle && oosToggle.checked !== overrideParams.out_of_sample) {
            oosToggle.checked = overrideParams.out_of_sample;
        }

        // Chama runBacktest diretamente com overrideParams — sem setTimeout, sem depender de DOM
        runBacktest(overrideParams);

        window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
        showToast("Erro ao configurar simulação específica: " + err.message, "error");
        console.error(err);
    }
};



// ==========================================================================

window.runBacktest = async function(overrideParams) {
    if (window._backtestRunning) return;
    window._backtestRunning = true;
    if (!window._backtestSeq) window._backtestSeq = 0;
    const mySeq = ++window._backtestSeq;
    let btn = null;
    let topbarBtn = null;
    try {
        // --- Portfolio Fix: Restore standard UI panels ---
        const pPanel = document.getElementById('portfolio-results-panel');
        if (pPanel) pPanel.style.display = 'none';

        const smGrid = document.getElementById('standard-metrics-grid');
        if (smGrid) smGrid.style.display = 'grid';

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
                const parentGrid = c.closest('div[style*="display: grid"]');
                if (parentGrid) parentGrid.style.display = 'grid';
            }
        });

        btn = document.getElementById('btn-run-backtest');
        topbarBtn = document.getElementById('btn-topbar-run');
        if(btn) { btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Rodando...'; btn.disabled = true; }
        if(topbarBtn) { topbarBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; topbarBtn.disabled = true; }

        let leagues, startDate, endDate, markets, valThreshold, initialBankroll, stakeRule, stakeValue, oddsSource, oddsTiming, minOdds, maxOdds, exchangeCommission, oos, useMl;
        let minOddsH, maxOddsH, minOddsD, maxOddsD, minOddsA, maxOddsA, minOddsOver25, maxOddsOver25, minOddsUnder25, maxOddsUnder25;
        let dataSource, API_key;
        let oosSplitVal = 20.0;
        let slippageVal = 2.0;
        let wfFolds = 0;

        if (overrideParams) {
            leagues = overrideParams.leagues || [];
            startDate = overrideParams.startDate;
            endDate = overrideParams.endDate;
            markets = Array.isArray(overrideParams.market) ? overrideParams.market : (overrideParams.market ? [overrideParams.market] : []);
            valThreshold = overrideParams.valueThreshold !== undefined ? overrideParams.valueThreshold : 1.0;
            initialBankroll = overrideParams.initialBankroll !== undefined ? overrideParams.initialBankroll : 1000.0;
            stakeRule = overrideParams.stakingRule || 'fixed';
            stakeValue = overrideParams.stakeValue !== undefined ? overrideParams.stakeValue : 10.0;
            if (stakeRule && stakeRule.startsWith('kelly')) {
                const origRule = stakeRule;
                stakeRule = 'kelly';
                if (origRule === 'kelly_half') stakeValue = 0.5;
                else if (origRule === 'kelly_quarter') stakeValue = 0.25;
                else if (origRule === 'kelly_eighth') stakeValue = 0.125;
                else if (origRule === 'kelly_sixteenth') stakeValue = 0.0625;
            }
            oddsSource = overrideParams.oddsSource || 'B365';
            oddsTiming = overrideParams.odds_timing || 'closing';
            minOdds = overrideParams.minOdds !== undefined ? overrideParams.minOdds : 1.0;
            maxOdds = overrideParams.maxOdds !== undefined ? overrideParams.maxOdds : 2.50;
            exchangeCommission = overrideParams.exchange_commission !== undefined ? overrideParams.exchange_commission : 0.0;
            oos = overrideParams.out_of_sample !== undefined ? overrideParams.out_of_sample : false;
            oosSplitVal = overrideParams.oos_split !== undefined ? overrideParams.oos_split : 20.0;
            slippageVal = overrideParams.slippage !== undefined ? overrideParams.slippage : 2.0;
            useMl = overrideParams.use_ml !== undefined ? overrideParams.use_ml : false;
            minOddsH = overrideParams.minOddsH !== undefined ? overrideParams.minOddsH : null;
            maxOddsH = overrideParams.maxOddsH !== undefined ? overrideParams.maxOddsH : null;
            minOddsD = overrideParams.minOddsD !== undefined ? overrideParams.minOddsD : null;
            maxOddsD = overrideParams.maxOddsD !== undefined ? overrideParams.maxOddsD : null;
            minOddsA = overrideParams.minOddsA !== undefined ? overrideParams.minOddsA : null;
            maxOddsA = overrideParams.maxOddsA !== undefined ? overrideParams.maxOddsA : null;
            minOddsOver25 = overrideParams.minOddsOver25 !== undefined ? overrideParams.minOddsOver25 : null;
            maxOddsOver25 = overrideParams.maxOddsOver25 !== undefined ? overrideParams.maxOddsOver25 : null;
            minOddsUnder25 = overrideParams.minOddsUnder25 !== undefined ? overrideParams.minOddsUnder25 : null;
            maxOddsUnder25 = overrideParams.maxOddsUnder25 !== undefined ? overrideParams.maxOddsUnder25 : null;
            dataSource = overrideParams.data_source || window.currentDataSource;
            API_key = overrideParams.futpython_api_key || window.futpythonApiKey;
        } else {
            leagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
            startDate = document.getElementById('start-date') ? document.getElementById('start-date').value : '';
            endDate = document.getElementById('end-date') ? document.getElementById('end-date').value : '';
            markets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);
            
            valThreshold = parseFloat(document.getElementById('val-threshold') ? document.getElementById('val-threshold').value : 1.0) || 1.0;
            initialBankroll = parseFloat(document.getElementById('init-bankroll') ? document.getElementById('init-bankroll').value : 1000.0) || 1000.0;
            stakeRule = document.getElementById('stake-rule') ? document.getElementById('stake-rule').value : 'fixed';
            stakeValue = stakeRule === 'kelly' ? parseFloat(document.getElementById('kelly-fraction') ? document.getElementById('kelly-fraction').value : 0.25) || 0.25 : parseFloat(document.getElementById('stake-value') ? document.getElementById('stake-value').value : 10.0) || 10.0;
            oddsSource = document.getElementById('odds-source') ? document.getElementById('odds-source').value : 'B365';
            oddsTiming = document.getElementById('odds-timing') ? document.getElementById('odds-timing').value : 'closing';
            minOdds = parseFloat(document.getElementById('min-odds') ? document.getElementById('min-odds').value : 1.0) || 1.0;
            maxOdds = parseFloat(document.getElementById('max-odds') ? document.getElementById('max-odds').value : 2.50) || 2.50;
            exchangeCommission = parseFloat(document.getElementById('exchange-commission') ? document.getElementById('exchange-commission').value : 0.0) || 0.0;
            
            const oosToggle = document.getElementById('oos-toggle');
            oos = oosToggle ? oosToggle.checked : false;
            
            const oosSplitEl = document.getElementById('oos-split-pct');
            oosSplitVal = oosSplitEl ? parseFloat(oosSplitEl.value) : 20.0;

            const wfToggle = document.getElementById('wf-toggle');
            const wfFoldsEl = document.getElementById('wf-folds');
            wfFolds = (wfToggle && wfToggle.checked) ? (wfFoldsEl ? parseInt(wfFoldsEl.value) : 5) : 0;

            const slippageEl = document.getElementById('backtest-slippage');
            slippageVal = slippageEl ? parseFloat(slippageEl.value) : 2.0;

            const useMLToggle = document.getElementById('use-ml-toggle');
            useMl = useMLToggle ? useMLToggle.checked : false;

            minOddsH = document.getElementById('min-odds-h') && document.getElementById('min-odds-h').value ? parseFloat(document.getElementById('min-odds-h').value) : null;
            maxOddsH = document.getElementById('max-odds-h') && document.getElementById('max-odds-h').value ? parseFloat(document.getElementById('max-odds-h').value) : null;
            minOddsD = document.getElementById('min-odds-d') && document.getElementById('min-odds-d').value ? parseFloat(document.getElementById('min-odds-d').value) : null;
            maxOddsD = document.getElementById('max-odds-d') && document.getElementById('max-odds-d').value ? parseFloat(document.getElementById('max-odds-d').value) : null;
            minOddsA = document.getElementById('min-odds-a') && document.getElementById('min-odds-a').value ? parseFloat(document.getElementById('min-odds-a').value) : null;
            maxOddsA = document.getElementById('max-odds-a') && document.getElementById('max-odds-a').value ? parseFloat(document.getElementById('max-odds-a').value) : null;
            minOddsOver25 = document.getElementById('min-odds-over25') && document.getElementById('min-odds-over25').value ? parseFloat(document.getElementById('min-odds-over25').value) : null;
            maxOddsOver25 = document.getElementById('max-odds-over25') && document.getElementById('max-odds-over25').value ? parseFloat(document.getElementById('max-odds-over25').value) : null;
            minOddsUnder25 = document.getElementById('min-odds-under25') && document.getElementById('min-odds-under25').value ? parseFloat(document.getElementById('min-odds-under25').value) : null;
            maxOddsUnder25 = document.getElementById('max-odds-under25') && document.getElementById('max-odds-under25').value ? parseFloat(document.getElementById('max-odds-under25').value) : null;
            dataSource = window.currentDataSource;
            API_key = window.futpythonApiKey;
        }
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
            odds_timing: oddsTiming,
            minOdds: minOdds,
            maxOdds: maxOdds,
            exchange_commission: exchangeCommission,
            out_of_sample: oos,
            oos_split: oosSplitVal,
            walk_forward_folds: wfFolds,
            slippage: slippageVal,
            use_ml: useMl,
            model_type: document.getElementById('model-type-select')?.value || 'poisson',
            data_source: dataSource,
            futpython_api_key: API_key,
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
        console.log("Backtest Request Payload:", JSON.stringify(payload));
        const signal = createAbortController().signal;
        const response = await fetch('/api/backtest', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
            signal: signal
        });
        const data = await response.json();
        console.log("Backtest Response Status:", response.status);
        console.log("Backtest Response Summary:", JSON.stringify(data.summary || {}));
        if (data.error) console.error("Backtest Response Error:", data.error);

        // Discard stale responses from older concurrent requests
        if (mySeq !== window._backtestSeq) {
            console.warn(`Dropping stale backtest response seq=${mySeq}, current=${window._backtestSeq}`);
            return;
        }

        if (response.ok && !data.error) {
            // Check if walk-forward result (different structure from standard backtest)
            if (data.method === 'walk_forward') {
                renderWalkForwardResults(data);
                return;
            }

            window.lastBacktestSummary = data;
            window.lastBacktestParams = payload;
            
            const btnSave = document.getElementById('btn-save-strategy');
            if(btnSave) btnSave.style.display = 'inline-block';

            const summary = data.summary;
            // KPI Hero — animated count-up
            animateValue(document.getElementById('metric-net-profit'), 0, summary.net_profit, 800, v => (v >= 0 ? '+' : '') + '$' + Math.abs(v).toFixed(2));
            if(document.getElementById('metric-profit-stakes')) document.getElementById('metric-profit-stakes').innerText = (summary.profit_in_stakes > 0 ? '+' : '') + summary.profit_in_stakes.toFixed(2) + ' st.';
            animateValue(document.getElementById('metric-roi'), 0, summary.roi, 800, v => v.toFixed(1) + '%');
            animateValue(document.getElementById('metric-win-rate'), 0, summary.win_rate, 800, v => v.toFixed(1) + '%');
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
            if(document.getElementById('metric-matches-analyzed')) document.getElementById('metric-matches-analyzed').innerText = (summary.matches_total_in_file || 0).toLocaleString();
            if(document.getElementById('metric-seasons')) {
                const seasons = summary.seasons_analyzed || [];
                document.getElementById('metric-seasons').innerText = seasons.length > 0 ? seasons.join(', ') : '-';
            }
            if(document.getElementById('metric-wins')) document.getElementById('metric-wins').innerText = summary.wins || 0;
            if(document.getElementById('metric-losses')) document.getElementById('metric-losses').innerText = summary.losses || 0;
            const pushesCard = document.getElementById('metric-pushes-card');
            if (pushesCard && document.getElementById('metric-pushes')) {
                const pushes = summary.pushes || 0;
                if (pushes > 0) {
                    pushesCard.style.display = 'flex';
                    document.getElementById('metric-pushes').innerText = pushes;
                } else {
                    pushesCard.style.display = 'none';
                }
            }
            animateValue(document.getElementById('metric-final-bankroll'), payload.initialBankroll, summary.final_bankroll, 800, v => '$' + v.toFixed(2));
            if(document.getElementById('metric-sharpe')) document.getElementById('metric-sharpe').innerText = (summary.sharpe_ratio || 0).toFixed(2);
            if(document.getElementById('metric-sortino')) document.getElementById('metric-sortino').innerText = (summary.sortino_ratio || 0).toFixed(2);
            if(document.getElementById('metric-skewness')) document.getElementById('metric-skewness').innerText = (summary.skewness || 0).toFixed(2);
            if(document.getElementById('metric-consec-wins')) document.getElementById('metric-consec-wins').innerText = summary.max_consec_wins || 0;
            if(document.getElementById('metric-consec-losses')) document.getElementById('metric-consec-losses').innerText = summary.max_consec_losses || 0;
            if(document.getElementById('metric-clv')) document.getElementById('metric-clv').innerText = summary.avg_clv != null ? ((summary.avg_clv >= 0 ? '+' : '') + summary.avg_clv.toFixed(1) + '%') : 'N/A';
            if(document.getElementById('metric-bcl')) document.getElementById('metric-bcl').innerText = summary.bcl_percent != null ? (summary.bcl_percent.toFixed(1) + '%') : 'N/A';

            // Apply positive/negative classes to metric cards + color h2 values
            function applyMetricColors(summary) {
                var np = parseFloat(summary.net_profit);
                var ps = parseFloat(summary.profit_in_stakes);
                var rr = parseFloat(summary.roi);
                var wr = parseFloat(summary.win_rate);

                function colorCard(h2Id, value, neutralThreshold) {
                    var h2 = document.getElementById(h2Id);
                    if (!h2) return;
                    var card = h2.closest('.metric-card');
                    var isPositive = neutralThreshold !== undefined ? value > neutralThreshold : value >= 0;
                    if (card) {
                        // Clear any leftover inline styles from previous versions
                        card.style.background = '';
                        card.style.borderColor = '';
                        card.style.borderLeftColor = '';
                        card.style.boxShadow = '';
                        card.style.setProperty('border-left', '');
                        card.style.setProperty('--mc-accent', '');
                        var icon = card.querySelector('.metric-icon');
                        if (icon) { icon.style.color = ''; icon.style.background = ''; icon.style.borderColor = ''; icon.style.boxShadow = ''; }
                        var label = card.querySelector('.metric-label');
                        if (label) { label.style.color = ''; }
                        // Apply class
                        card.classList.remove('positive', 'negative');
                        if (isPositive) card.classList.add('positive');
                        else card.classList.add('negative');
                    }
                    h2.style.textShadow = '';
                    h2.style.color = isPositive ? 'var(--color-success)' : 'var(--color-danger)';
                }

                colorCard('metric-net-profit', np);
                colorCard('metric-profit-stakes', ps);
                colorCard('metric-roi', rr, 0);
                colorCard('metric-win-rate', wr, 50);
            }
            applyMetricColors(summary);

            // Populate Transparency Panel (Phase 1)
            const transPanel = document.getElementById('transparency-panel');
            if (transPanel) {
                transPanel.style.display = 'block';
                
                const skippedOddsVal = summary.games_skipped_nan || 0;
                const evaluatedVal = summary.games_evaluated_total || 0;
                const skippedFilterVal = summary.games_skipped_filter || 0;
                const nanPctVal = summary.nan_skipped_pct || 0;
                
                const skippedOddsText = document.getElementById('transparency-skipped-odds');
                if (skippedOddsText) {
                    skippedOddsText.innerText = `${skippedOddsVal} de ${evaluatedVal} (${nanPctVal}%)`;
                    // Highlight red/amber if high selection bias
                    if (nanPctVal > 25) {
                        skippedOddsText.style.color = '#ef4444';
                    } else if (nanPctVal > 10) {
                        skippedOddsText.style.color = '#f59e0b';
                    } else {
                        skippedOddsText.style.color = '#10b981';
                    }
                }
                
                const synthBetsVal = summary.synthetic_bets_count || 0;
                const synthPctVal = summary.synthetic_bets_pct || 0;
                const synthBetsText = document.getElementById('transparency-synthetic-bets');
                const synthPctText = document.getElementById('transparency-synthetic-pct');
                if (synthBetsText) synthBetsText.innerText = synthBetsVal;
                if (synthPctText) {
                    synthPctText.innerText = synthPctVal + '%';
                    if (synthPctVal > 40) {
                        synthPctText.style.color = '#ef4444';
                        if (synthBetsText) synthBetsText.style.color = '#ef4444';
                    } else if (synthPctVal > 15) {
                        synthPctText.style.color = '#f59e0b';
                        if (synthBetsText) synthBetsText.style.color = '#f59e0b';
                    } else {
                        synthPctText.style.color = '#10b981';
                        if (synthBetsText) synthBetsText.style.color = '#10b981';
                    }
                }

                // === SYNTHETIC ODDS WARNING BANNER ===
                let synthBanner = document.getElementById('synthetic-odds-banner');
                if (!synthBanner) {
                    synthBanner = document.createElement('div');
                    synthBanner.id = 'synthetic-odds-banner';
                    synthBanner.style.cssText = 'margin:10px 0; padding:10px 14px; border-radius:8px; font-size:12px; line-height:1.5;';
                    const transPanel = document.getElementById('transparency-panel');
                    if (transPanel) transPanel.appendChild(synthBanner);
                }
                if (synthBanner) {
                    if (synthPctVal > 0) {
                        synthBanner.style.display = 'block';
                        const severity = synthPctVal > 40 ? 'ef4444' : (synthPctVal > 15 ? 'f59e0b' : '10b981');
                        synthBanner.style.background = `rgba(${severity === 'ef4444' ? '239,68,68' : severity === 'f59e0b' ? '245,158,11' : '16,185,129'}, 0.06)`;
                        synthBanner.style.border = `1px solid rgba(${severity === 'ef4444' ? '239,68,68' : severity === 'f59e0b' ? '245,158,11' : '16,185,129'}, 0.2)`;
                        synthBanner.style.color = `#${severity === 'ef4444' ? 'fca5a5' : severity === 'f59e0b' ? 'fcd34d' : '6ee7b7'}`;
                        synthBanner.innerHTML = `<i class="fa-solid fa-calculator" style="color:#${severity};"></i> <strong style="color:#${severity};">Odds Simuladas (${synthPctVal}%):</strong> ${synthBetsVal} apostas usaram odds calculadas matematicamente (Dupla Chance, Handicap Asiático, Lay, Placar Exato) em vez de odds reais do mercado. O ROI desses mercados derivados pode divergir da realidade. Mercados com odds reais (1X2, Over/Under) são mais confiáveis.`;
                    } else {
                        synthBanner.style.display = 'none';
                    }
                }

                // === SLIPPAGE INDICATOR ===
                let slippageBanner = document.getElementById('slippage-banner');
                if (!slippageBanner) {
                    slippageBanner = document.createElement('div');
                    slippageBanner.id = 'slippage-banner';
                    slippageBanner.style.cssText = 'margin:10px 0; padding:10px 14px; border-radius:8px; font-size:12px; line-height:1.5;';
                    const transPanel = document.getElementById('transparency-panel');
                    if (transPanel) transPanel.appendChild(slippageBanner);
                }
                if (slippageBanner) {
                    const slippageApplied = summary.slippage_applied || false;
                    const slippagePct = summary.slippage_pct || 0;
                    if (slippageApplied) {
                        slippageBanner.style.display = 'block';
                        slippageBanner.style.background = 'rgba(139, 92, 246, 0.06)';
                        slippageBanner.style.border = '1px solid rgba(139, 92, 246, 0.2)';
                        slippageBanner.style.color = '#c4b5fd';
                        slippageBanner.innerHTML = `<i class="fa-solid fa-chart-line" style="color:#8b5cf6;"></i> <strong style="color:#8b5cf6;">Slippage Ativo (-${slippagePct}%):</strong> A simulação penaliza as odds de fechamento em ${slippagePct}% para modelar o drift real entre o momento do sinal e o preço de fechamento do mercado. Isso torna o backtest mais conservador e realista.`;
                    } else {
                        slippageBanner.style.display = 'block';
                        slippageBanner.style.background = 'rgba(16, 185, 129, 0.04)';
                        slippageBanner.style.border = '1px solid rgba(16, 185, 129, 0.12)';
                        slippageBanner.style.color = '#6ee7b7';
                        slippageBanner.innerHTML = `<i class="fa-solid fa-circle-check" style="color:#10b981;"></i> <strong style="color:#10b981;">Slippage Não Aplicado:</strong> Usando odds de abertura. Nenhuma penalidade de drift necessária.`;
                    }
                }
                
                const mlAppliedVal = summary.ml_applied_count || 0;
                const mlPctVal = summary.ml_applied_pct || 0;
                const mlAppliedText = document.getElementById('transparency-ml-applied');
                const mlPctText = document.getElementById('transparency-ml-pct');
                if (mlAppliedText) mlAppliedText.innerText = mlAppliedVal;
                if (mlPctText) mlPctText.innerText = mlPctVal + '%';

                // === ML ACTIVE WARNING BANNER ===
                let mlBanner = document.getElementById('ml-active-warning-banner');
                if (!mlBanner) {
                    mlBanner = document.createElement('div');
                    mlBanner.id = 'ml-active-warning-banner';
                    mlBanner.style.cssText = 'margin:10px 0; padding:10px 14px; border-radius:8px; font-size:12px; line-height:1.5;';
                    const transPanel = document.getElementById('transparency-panel');
                    if (transPanel) transPanel.appendChild(mlBanner);
                }
                if (mlBanner) {
                    const useMlEnabled = payload.use_ml || false;
                    if (useMlEnabled) {
                        if (mlAppliedVal === 0) {
                            mlBanner.style.display = 'block';
                            mlBanner.style.background = 'rgba(245, 158, 11, 0.06)';
                            mlBanner.style.border = '1px solid rgba(245, 158, 11, 0.2)';
                            mlBanner.style.color = '#fcd34d';
                            mlBanner.innerHTML = `<i class="fa-solid fa-brain" style="color:#f59e0b;"></i> <strong>ML Inativo (Sem amostras):</strong> O XGBoost foi ativado nas configurações, mas nenhuma aposta pôde ser recalibrada por falta de histórico de dados (requer pelo menos 200 jogos para treinar o ensemble). O sistema usou o Poisson clássico.`;
                        } else {
                            mlBanner.style.display = 'block';
                            mlBanner.style.background = 'rgba(139, 92, 246, 0.05)';
                            mlBanner.style.border = '1px solid rgba(139, 92, 246, 0.15)';
                            mlBanner.style.color = '#c4b5fd';
                            mlBanner.innerHTML = `<i class="fa-solid fa-brain" style="color:#8b5cf6;"></i> <strong>XGBoost Ensemble Ativo:</strong> ${mlAppliedVal} apostas (${mlPctVal}%) foram recalibradas com sucesso usando o modelo híbrido de Machine Learning.`;
                        }
                    } else {
                        mlBanner.style.display = 'none';
                    }
                }

                // ML status badge next to toggle
                const mlBadge = document.getElementById('ml-status-badge');
                if (mlBadge) {
                    const useMlEnabled = payload.use_ml || false;
                    if (!useMlEnabled) {
                        mlBadge.style.display = 'none';
                    } else if (mlAppliedVal > 0) {
                        mlBadge.style.display = 'inline';
                        mlBadge.style.background = 'rgba(16, 185, 129, 0.15)';
                        mlBadge.style.color = '#34d399';
                        mlBadge.style.border = '1px solid rgba(16, 185, 129, 0.3)';
                        mlBadge.textContent = mlAppliedVal + ' recalibradas';
                        mlBadge.title = 'XGBoost treinado com sucesso. ' + mlAppliedVal + ' apostas (' + mlPctVal + '%) foram ajustadas pelo ensemble.';
                    } else {
                        mlBadge.style.display = 'inline';
                        mlBadge.style.background = 'rgba(245, 158, 11, 0.1)';
                        mlBadge.style.color = '#fbbf24';
                        mlBadge.style.border = '1px solid rgba(245, 158, 11, 0.25)';
                        mlBadge.textContent = 'Sem dados para treinar';
                        mlBadge.title = 'XGBoost requer >=200 jogos na janela OOS para treinar. Nenhuma aposta foi recalibrada neste backtest. O sistema usou Poisson classico.';
                    }
                }
                
                const timingText = document.getElementById('transparency-odds-timing-text');
                const timingWarning = document.getElementById('transparency-odds-timing-warning');
                if (timingText) {
                    const isClosing = (payload.odds_timing === 'closing');
                    timingText.innerText = isClosing ? 'Fechamento (Closing)' : 'Abertura (Opening)';
                    timingText.style.color = isClosing ? '#f59e0b' : '#10b981';
                    if (timingWarning) {
                        timingWarning.innerText = isClosing 
                            ? 'Aviso: O drift de mercado (queda de odd) pode reduzir o ROI simulado na vida real.'
                            : 'Excelente: Simulando com a odd de abertura inicial do mercado.';
                    }
                }
                
                const calibText = document.getElementById('transparency-calibration');
                const calibCard = document.getElementById('transparency-calibration-card');
                if (calibText) {
                    const calibSkipped = summary.calibration_skipped;
                    const calibSamples = summary.calibration_samples || 0;
                    if (calibSkipped) {
                        calibText.innerText = `Inativa (${calibSamples} jogos)`;
                        calibText.style.color = '#f59e0b';
                        if (calibCard) calibCard.style.background = 'rgba(245, 158, 11, 0.02)';
                    } else {
                        calibText.innerText = `Ativa (${calibSamples} jogos)`;
                        calibText.style.color = '#10b981';
                        if (calibCard) calibCard.style.background = 'rgba(16, 185, 129, 0.02)';
                    }
                }

                // === SELECTION BIAS WARNING BANNER ===
                const biasBanner = document.getElementById('selection-bias-banner');
                if (!biasBanner) {
                    // Create banner dynamically if it doesn't exist
                    const banner = document.createElement('div');
                    banner.id = 'selection-bias-banner';
                    banner.style.cssText = 'display:none; margin:12px 0; padding:12px 16px; border-radius:8px; font-size:13px; line-height:1.5;';
                    const transPanel = document.getElementById('transparency-panel');
                    if (transPanel) transPanel.appendChild(banner);
                }
                const biasEl = document.getElementById('selection-bias-banner');
                if (biasEl) {
                    const filterPct = evaluatedVal > 0 ? ((skippedFilterVal + skippedOddsVal) / evaluatedVal * 100) : 0;
                    if (filterPct > 25) {
                        biasEl.style.display = 'block';
                        biasEl.style.background = 'rgba(239, 68, 68, 0.08)';
                        biasEl.style.border = '1px solid rgba(239, 68, 68, 0.3)';
                        biasEl.style.color = '#fca5a5';
                        biasEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation" style="color:#ef4444;"></i> <strong style="color:#ef4444;">Alerta de Viés de Seleção (${filterPct.toFixed(1)}%):</strong> Mais de 25% dos jogos foram excluídos do backtest (${skippedOddsVal} sem odds + ${skippedFilterVal} fora do filtro de ${evaluatedVal} avaliados). O ROI reportado pode estar <strong>significativamente inflado</strong> porque os jogos removidos são exatamente aqueles onde o modelo teria dificuldade. Considere usar uma fonte de odds com maior cobertura ou relaxar os filtros.`;
                    } else if (filterPct > 10) {
                        biasEl.style.display = 'block';
                        biasEl.style.background = 'rgba(245, 158, 11, 0.06)';
                        biasEl.style.border = '1px solid rgba(245, 158, 11, 0.2)';
                        biasEl.style.color = '#fcd34d';
                        biasEl.innerHTML = `<i class="fa-solid fa-circle-exclamation" style="color:#f59e0b;"></i> <strong style="color:#f59e0b;">Aviso de Viés Moderado (${filterPct.toFixed(1)}%):</strong> ${skippedOddsVal + skippedFilterVal} de ${evaluatedVal} jogos excluídos do backtest (${nanPctVal}% sem odds registradas). O ROI pode conter um viés otimista leve.`;
                    } else {
                        biasEl.style.display = 'block';
                        biasEl.style.background = 'rgba(16, 185, 129, 0.05)';
                        biasEl.style.border = '1px solid rgba(16, 185, 129, 0.15)';
                        biasEl.style.color = '#6ee7b7';
                        biasEl.innerHTML = `<i class="fa-solid fa-circle-check" style="color:#10b981;"></i> <strong style="color:#10b981;">Amostra Saudável (${filterPct.toFixed(1)}% excluídos):</strong> Baixo risco de viés de seleção. A cobertura de odds é excelente para esta liga.`;
                    }
                }
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
            const optimizedData = data.portfolio_optimization || null;

            if(typeof updateCharts === 'function') {
                updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueStats, monthlyStats, oddsStats, optimizedData);
            }

            if (typeof window.renderLaboratoryPanels === 'function') {
                window.renderLaboratoryPanels(data, false);
            }

            if (data.ai_analysis) {
                displayAiAnalysis(data.ai_analysis, data);
            }

            if (typeof populateBetsTable === 'function') {
                window.allBets = data.bets || [];
                populateBetsTable(window.allBets);
            }

            if (typeof autoUpdateSchedulerFromBacktest === 'function') {
                autoUpdateSchedulerFromBacktest(payload);
            }

            // Apply metric colors at the very end (after ALL DOM updates, banners, text, etc.)
            applyMetricColors(summary);

            const optBanner = document.getElementById('optimization-active-banner');
            if (optBanner) optBanner.style.display = 'none';
            const banner = document.getElementById('active-strategy-banner');
            if (banner) banner.style.display = 'flex';
            const leagueNames = leagues.map(code => {
                const lbl = document.querySelector(`label[for="league-${code}"]`) || document.querySelector(`label:has(input[value="${code}"])`);
                const text = lbl ? (lbl.innerText || lbl.textContent || "") : "";
                return text.trim() ? text.trim() : code;
            }).join(', ');
            
            const marketNames = markets.map(code => {
                const lbl = document.querySelector(`label:has(input[value="${code}"])`);
                const text = lbl ? (lbl.innerText || lbl.textContent || "") : "";
                return text.trim() ? text.trim() : code;
            }).join(', ');
            
            if(document.getElementById('active-leagues-text')) document.getElementById('active-leagues-text').innerText = leagueNames || 'N/A';
            if(document.getElementById('active-market-text')) document.getElementById('active-market-text').innerText = marketNames || 'N/A';
            if(document.getElementById('active-odds-text')) document.getElementById('active-odds-text').innerText = `${minOdds.toFixed(2)} - ${maxOdds.toFixed(2)}`;
            if(document.getElementById('active-ev-text')) document.getElementById('active-ev-text').innerText = valThreshold.toFixed(2);

            const btnExport = document.getElementById('btn-export-backtest');
            if (btnExport) btnExport.style.display = 'inline-flex';

            if (typeof showToast === 'function') showToast("Backtest concluído!", "success");

        } else {
            const errMsg = data.error || data.detail || "Erro ao executar backtest.";
            console.error("Backtest error:", errMsg, data);
            showToast(errMsg, "error");
        }
    } catch(err) {
        console.error("Backtest error:", err);
        if (err.name === 'AbortError') return;
        if (err.message.includes("Unexpected end of JSON input")) {
            showToast("Erro: O servidor encerrou a conexão inesperadamente (possível falta de memória / OOM).", "error");
        } else {
            showToast("Erro: " + err.message, "error");
        }
    } finally {
        window._backtestRunning = false;
        if(btn) { btn.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest'; btn.disabled = false; }
        if(topbarBtn) { topbarBtn.innerHTML = '<i class="fa-solid fa-play"></i> Executar'; topbarBtn.disabled = false; }
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

// --- Portfolio Backtesting ---

function togglePortfolioStakeInput() {
    const method = document.getElementById('portfolio-risk-method').value;
    const stakeInput = document.getElementById('portfolio-fixed-stake');
    if (method === 'fixed') {
        stakeInput.style.display = 'block';
    } else {
        stakeInput.style.display = 'none';
    }
}

async function runPortfolioBacktest(overrideStrategyIds) {
    let strategyIds;
    if (overrideStrategyIds && overrideStrategyIds.length > 0) {
        strategyIds = overrideStrategyIds;
    } else {
        const checkboxes = document.querySelectorAll('.portfolio-checkbox:checked');
        strategyIds = Array.from(checkboxes).map(cb => cb.value);
    }
    
    if (!strategyIds || strategyIds.length === 0) {
        showToast('Selecione pelo menos uma estratégia para rodar o Portfólio.', 'warning');
        return;
    }
    
    window.lastPortfolioStrategyIds = strategyIds;
    
    let riskMethod = document.getElementById('portfolio-risk-method').value;
    if (riskMethod === 'fixed') {
        const pct = document.getElementById('portfolio-fixed-stake').value || "2.0";
        riskMethod = `fixed_${pct}`;
    }
    
    const btn = document.querySelector('button[onclick="runPortfolioBacktest()"]');
    if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sincronizando estratégias...';
        btn.disabled = true;
    }

    showToast('Sincronizando estratégias com o servidor...', 'info', 30000);

    try {
        const history = lsLoadHistory();
        const selectedItems = history.filter(h => strategyIds.includes(h.id));
        if (selectedItems.length > 0) {
            // Fire-and-forget: don't block UI while syncing
            lsSyncToServer(selectedItems).catch(() => {});
        }

        // Switch to Laboratory Tab and show spinner IMMEDIATELY
        switchTab('tab-laboratory');

        if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Processando (Aguarde...)';
            btn.disabled = true;
        }
        showToast('Rodando Portfólio. Pode levar até 2 min no servidor gratuito...', 'info');

        // Hide standard Laboratory panels early so we don't see 0s
        const stdGrid = document.getElementById('standard-metrics-grid');
        if (stdGrid) stdGrid.style.display = 'none';

        const mainCharts = document.querySelector('.main-charts');
        if (mainCharts) mainCharts.style.display = 'none';

        // Show placeholder in portfolio panel while loading
        document.getElementById('portfolio-results-panel').style.display = 'block';
        document.getElementById('port-metric-bankroll').innerText = '---';
        document.getElementById('port-metric-profit').innerText = '---';
        document.getElementById('port-metric-roi').innerText = 'Aguardando...';
        document.getElementById('port-metric-dd').innerText = '---';

        const res = await fetch(`${API_BASE_URL}/api/portfolio_backtest`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                strategy_ids: strategyIds,
                initial_bankroll: parseFloat(document.getElementById('portfolio-bankroll-input')?.value || 1000),
                risk_method: riskMethod,
                strategies_inline: selectedItems  // fallback when DB is empty post-deploy
            })
        });

        const data = await res.json();

        if (!res.ok || data.error) {
            showToast(data.detail || data.error || 'Erro desconhecido do servidor.', 'error');
            if (btn) { btn.innerHTML = '<i class="fa-solid fa-layer-group"></i> Rodar Portfólio Selecionado'; btn.disabled = false; }
            document.getElementById('portfolio-results-panel').style.display = 'block';
            document.getElementById('port-metric-bankroll').innerText = `$0.00`;
            document.getElementById('port-metric-profit').innerText = `$0.00`;
            document.getElementById('port-metric-roi').innerText = `0.00%`;
            document.getElementById('port-metric-dd').innerText = `0.00%`;
            const tbody = document.getElementById('portfolio-bets-body');
            if(tbody) tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted">Nenhuma aposta atendeu aos critérios (odds > 2.50 foram removidas).</td></tr>`;
            return;
        }

        // Show Portfolio Panel
        document.getElementById('portfolio-results-panel').style.display = 'block';

        // Show dedup warnings if any
        if (data.dedup_warnings && data.dedup_warnings.length > 0) {
            const msg = data.dedup_warnings.join('\n');
            showToast(msg, 'warning', 8000);
        }

        // Update top-level Metrics
        document.getElementById('port-metric-bankroll').innerText = `$${data.final_bankroll.toFixed(2)}`;
        document.getElementById('port-metric-profit').innerText = `$${data.net_profit.toFixed(2)}`;
        
        const roiEl = document.getElementById('port-metric-roi');
        roiEl.innerText = `${data.total_roi.toFixed(2)}%`;
        roiEl.style.color = data.total_roi > 0 ? '#10b981' : '#ef4444';
        
        document.getElementById('port-metric-dd').innerText = `${data.max_drawdown.toFixed(2)}%`;

        // Populate extra portfolio summary metrics (same fields as individual backtest)
        const s = data.summary || {};
        const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val; };
        setEl('port-metric-bets',    s.total_bets ?? data.total_bets ?? '-');
        setEl('port-metric-wins',    s.wins ?? '-');
        setEl('port-metric-losses',  s.losses ?? '-');
        setEl('port-metric-winrate', s.win_rate != null ? `${s.win_rate.toFixed(1)}%` : '-');
        setEl('port-metric-avgodd',  s.avg_odds != null ? s.avg_odds.toFixed(2) : '-');
        setEl('port-metric-sharpe',  s.sharpe_ratio != null ? s.sharpe_ratio.toFixed(2) : '-');
        setEl('port-metric-sortino', s.sortino_ratio != null ? s.sortino_ratio.toFixed(2) : '-');
        setEl('port-metric-staked',  s.total_staked != null ? `$${s.total_staked.toFixed(2)}` : '-');
        setEl('port-metric-pvalue',  s.p_value != null ? (s.p_value < 0.001 ? '< 0.001' : s.p_value.toFixed(3)) : '-');
        setEl('port-metric-consec-wins',   s.max_consec_wins ?? '-');
        setEl('port-metric-consec-losses', s.max_consec_losses ?? '-');

        // Also populate shared Laboratório cards (matches, seasons)
        if (document.getElementById('metric-matches-analyzed')) {
            document.getElementById('metric-matches-analyzed').innerText = (data.matches_total_in_file || 0).toLocaleString();
        }
        if (document.getElementById('metric-seasons')) {
            const seasons = data.seasons_analyzed || [];
            document.getElementById('metric-seasons').innerText = seasons.length > 0 ? seasons.join(', ') : '-';
        }

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

        // Show total portfolio exposure footer
        const exposureFooter = document.getElementById('portfolio-exposure-footer');
        const totalExposureEl = document.getElementById('portfolio-total-exposure');
        const maxExposurePctEl = document.getElementById('portfolio-max-exposure-pct');
        if (exposureFooter && data.total_recommended_exposure !== undefined) {
            totalExposureEl.textContent = `$${data.total_recommended_exposure.toFixed(2)}`;
            if (maxExposurePctEl && data.max_portfolio_exposure_pct !== undefined) {
                maxExposurePctEl.textContent = `${data.max_portfolio_exposure_pct}%`;
            }
            exposureFooter.style.display = 'block';
        }
        
        if (typeof window.renderLaboratoryPanels === 'function') {
            window.renderLaboratoryPanels(data, true);
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
            window.allBets = bets;
            populateBetsTable(window.allBets);
        }

        // Reset button after successful run
        if (btn) { btn.innerHTML = '<i class="fa-solid fa-layer-group"></i> Rodar Portfólio Selecionado'; btn.disabled = false; }

    } catch (e) {
        console.error(e);
        showToast('Erro: ' + e.message, 'error');
        const btn = document.querySelector('button[onclick="runPortfolioBacktest()"]');
        if (btn) { btn.innerHTML = '<i class="fa-solid fa-layer-group"></i> Rodar Portfólio Selecionado'; btn.disabled = false; }
    }
}



async function loadPortfolio(id) {
    try {
        // Use lsLoadHistory which is guaranteed to have the merged latest data
        const history = typeof lsLoadHistory === 'function' ? lsLoadHistory() : [];
        let portfolio = history.find(h => h.id === id);
        
        // Fallback to fetch if not found in local (rare edge case)
        if (!portfolio) {
            const res = await fetch(`${API_BASE_URL}/api/history?t=${Date.now()}`, { cache: 'no-store' });
            const serverHistory = await res.json();
            portfolio = serverHistory.find(h => h.id === id);
        }

        if (!portfolio || (portfolio.type !== 'portfolio' && (!portfolio.params || !portfolio.params.strategy_ids))) {
            showToast('Portfólio não encontrado.', 'error');
            return;
        }
        
        window.lastPortfolioStrategyIds = portfolio.params.strategy_ids;
        
        document.querySelectorAll('.history-select-checkbox').forEach(cb => cb.checked = false);
        
        if (portfolio.params && portfolio.params.strategy_ids) {
            let foundCount = 0;
            portfolio.params.strategy_ids.forEach(sid => {
                const cb = document.querySelector(`.history-select-checkbox[value="${sid}"]`);
                if (cb) {
                    cb.checked = true;
                    foundCount++;
                }
            });
            
            if (portfolio.params.risk_method) {
                const rm = document.getElementById('portfolio-risk-method');
                if (rm) {
                    if (portfolio.params.risk_method.startsWith('fixed_')) {
                        rm.value = 'fixed';
                        const pct = portfolio.params.risk_method.split('_')[1];
                        const inp = document.getElementById('portfolio-fixed-stake');
                        if (inp) {
                            inp.value = pct;
                            inp.style.display = 'block';
                        }
                    } else {
                        rm.value = portfolio.params.risk_method;
                        const inp = document.getElementById('portfolio-fixed-stake');
                        if (inp) inp.style.display = 'none';
                    }
                }
            }
            if (portfolio.params.initial_bankroll) {
                const bk = document.getElementById('portfolio-bankroll-input');
                if (bk) bk.value = portfolio.params.initial_bankroll;
            }
            
            if (foundCount > 0) {
                showToast(`${foundCount} estratégias do portfólio selecionadas com sucesso.`, 'success');
            }
            
            // Switch to laboratory tab
            switchTab('tab-laboratory');
            
            // Automatically run the portfolio with the strategy IDs
            runPortfolioBacktest(portfolio.params.strategy_ids);
        }
    } catch (e) {
        console.error(e);
        showToast('Erro ao carregar portfólio.', 'error');
    }
}

async function savePortfolio() {
    let strategyIds = window.lastPortfolioStrategyIds;
    
    if (!strategyIds || strategyIds.length === 0) {
        const checkboxes = document.querySelectorAll('.portfolio-checkbox:checked');
        strategyIds = Array.from(checkboxes).map(cb => cb.value);
    }
    
    if (!strategyIds || strategyIds.length === 0) {
        showToast('Selecione pelo menos uma estratégia para salvar no portfólio.', 'warning');
        return;
    }
    
    const profitEl = document.getElementById('port-metric-profit');
    if (!profitEl || profitEl.innerText.includes('$0.00')) {
        showToast('Rode o portfólio primeiro para salvar seus resultados!', 'warning');
        return;
    }
    
    const name = prompt("Digite um nome para este Portfólio Combinado:");
    if (!name || name.trim() === '') return;
    
    const profitText = document.getElementById('port-metric-profit')?.innerText || '0';
    const roiText = document.getElementById('port-metric-roi')?.innerText || '0';
    const winrateText = document.getElementById('port-metric-winrate')?.innerText || '0';
    const betsText = document.getElementById('port-metric-bets')?.innerText || '0';
    const drawdownText = document.getElementById('port-metric-dd')?.innerText || '0';
    
    let riskMethod = document.getElementById('portfolio-risk-method')?.value || 'kelly_quarter';
    if (riskMethod === 'fixed') {
        const pct = document.getElementById('portfolio-fixed-stake')?.value || '2.0';
        riskMethod = `fixed_${pct}`;
    }
    
    // Sanitize NaN/Infinity values (JSON.stringify throws on them)
    const sanitizeObj = (obj) => {
        if (obj === null || obj === undefined) return obj;
        if (typeof obj === 'number' && (isNaN(obj) || !isFinite(obj))) return 0;
        if (Array.isArray(obj)) return obj.map(sanitizeObj);
        if (typeof obj === 'object' && obj.constructor === Object) {
            const cleaned = {};
            for (const [k, v] of Object.entries(obj)) {
                cleaned[k] = sanitizeObj(v);
            }
            return cleaned;
        }
        return obj;
    };

    const portfolioObj = sanitizeObj({
        name: name,
        type: 'portfolio',
        created_at: new Date().toISOString(),
        params: {
            strategy_ids: strategyIds,
            risk_method: riskMethod,
            initial_bankroll: parseFloat(document.getElementById('portfolio-bankroll-input')?.value || 1000)
        },
        summary: {
            net_profit: parseFloat(profitText.replace(/[^\d.-]/g, '')) || 0,
            roi: parseFloat(roiText.replace(/[^\d.-]/g, '')) || 0,
            win_rate: parseFloat(winrateText.replace(/[^\d.-]/g, '')) || 0,
            total_bets: parseInt(betsText.replace(/[^\d.-]/g, '')) || 0,
            max_drawdown: parseFloat(drawdownText.replace(/[^\d.-]/g, '')) || 0
        },
        is_tg_active: false
    });
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/history`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(portfolioObj)
        });
        
        if (res.ok) {
            const saved = await res.json();
            // Persist to localStorage so it survives Render redeployments
            if (saved && saved.entry) lsAddItem(saved.entry);
            showToast('Portfólio salvo com sucesso no Histórico!', 'success');
            // Switch to history tab and reload so the new card appears immediately
            switchTab('tab-history');
            await loadHistoryTab();
        } else {
            showToast('Falha ao salvar portfólio.', 'error');
        }
    } catch (e) {
        showToast('Erro ao salvar.', 'error');
    }
}

async function toggleActivePortfolio(id) {
    try {
        const res = await fetch(`${API_BASE_URL}/api/history/${id}/toggle_active`, {
            method: 'POST'
        });
        
        if (res.ok) {
            const data = await res.json();
            
            // Synchronize local state and localStorage directly to avoid any caching/timing issues
            const history = lsLoadHistory();
            const target = history.find(x => x.id === id);
            let isPortfolio = true;
            if (target) {
                const newStatus = !!data.is_tg_active;
                target.is_tg_active = newStatus;
                
                isPortfolio = target.type === 'portfolio' || (target.params && !!target.params.strategy_ids);
                
                lsSaveHistory(history);
                window.loadedHistoryStrategies = history;
            }
            
            if (data.is_tg_active) {
                if (isPortfolio) {
                    showToast('Portfólio ativado! O robô do Telegram usará a banca e gestão deste portfólio.', 'success');
                } else {
                    showToast('Estratégia ativada! O robô do Telegram enviará alertas para esta estratégia.', 'success');
                }
            } else {
                showToast(isPortfolio ? 'Portfólio desativado.' : 'Estratégia desativada.', 'success');
            }
            
            // Re-render the grid immediately with the updated local state
            applyHistoryFilters();
        } else {
            showToast('Falha ao alterar o status.', 'error');
        }
    } catch (e) {
        console.error(e);
        showToast('Erro ao alterar status.', 'error');
    }
}

function exportHistory() {
    const history = lsLoadHistory();
    if (!history || history.length === 0) {
        showToast('Nenhum item no histórico para exportar.', 'warning');
        return;
    }
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(history, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    const dateStr = new Date().toISOString().slice(0, 10);
    downloadAnchor.setAttribute("download", `historico_estrategias_${dateStr}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    showToast('Histórico exportado com sucesso!', 'success');
}

function triggerImportHistory() {
    const input = document.getElementById('import-history-file');
    if (input) input.click();
}

async function importHistory(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = async function(e) {
        try {
            const imported = JSON.parse(e.target.result);
            if (!Array.isArray(imported)) {
                showToast('Arquivo inválido. Deve ser um array JSON de estratégias.', 'error');
                return;
            }
            
            // Load current history
            const current = lsLoadHistory();
            
            let addedCount = 0;
            let updatedCount = 0;
            
            for (const item of imported) {
                if (!item.id || !item.name) continue;
                
                // Add to local list
                const idx = current.findIndex(x => x.id === item.id);
                if (idx >= 0) {
                    current[idx] = item;
                    updatedCount++;
                } else {
                    current.unshift(item);
                    addedCount++;
                }
            }
            
            // Save to localStorage
            lsSaveHistory(current);
            window.loadedHistoryStrategies = current;
            
            // Sync all to server
            showToast(`Sincronizando ${addedCount + updatedCount} itens com o servidor...`, 'info');
            await lsSyncToServer(current);
            
            showToast(`Importação concluída: ${addedCount} novos, ${updatedCount} atualizados!`, 'success');
            
            // Reload tab
            await loadHistoryTab();
            
            // Clear file input
            event.target.value = '';
        } catch (err) {
            console.error(err);
            showToast('Erro ao ler ou processar o arquivo JSON.', 'error');
        }
    };
    reader.readAsText(file);
}


// Expose remaining functions to global scope for HTML event handlers
window.filterTable = filterTable;
window.toggleBetsSort = toggleBetsSort;
window.prevPage = prevPage;
window.nextPage = nextPage;
window.togglePortfolioStakeInput = togglePortfolioStakeInput;
window.runPortfolioBacktest = runPortfolioBacktest;
window.exportHistory = exportHistory;
window.triggerImportHistory = triggerImportHistory;
window.importHistory = importHistory;
window.saveFutpythonKey = saveFutpythonKey;
window.handleDataSourceChange = handleDataSourceChange;
window.runScanner = runScanner;
window.exportScannerResults = exportScannerResults;
window.exportBacktestReport = exportBacktestReport;
window.runEqsScanner = runEqsScanner;
window.renderRiskManagement = renderRiskManagement;
window.renderEdgeQualityScore = renderEdgeQualityScore;
window.displayAiAnalysis = displayAiAnalysis;
window.renderStatValidation = renderStatValidation;
window.renderOosResults = renderOosResults;
window.renderDriftValidation = renderDriftValidation;
async function selectAllHistory(checked) {
    document.querySelectorAll('.history-select-checkbox').forEach(cb => {
        cb.checked = checked;
    });
}

async function deleteSelectedHistory() {
    const checked = document.querySelectorAll('.history-select-checkbox:checked');
    if (checked.length === 0) {
        showToast('Nenhum item selecionado para exclusão.', 'warning');
        return;
    }

    if (!confirm(`Tem certeza que deseja excluir os ${checked.length} itens selecionados?`)) {
        return;
    }

    const btn = document.querySelector('button[onclick="deleteSelectedHistory()"]');
    if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Excluindo...';
        btn.disabled = true;
    }

    let successCount = 0;
    let failCount = 0;

    for (const cb of checked) {
        const id = cb.value;
        try {
            const res = await fetch(`${API_BASE_URL}/api/history/${id}`, { method: 'DELETE' });
            if (res.ok) {
                lsDeleteItem(id);
                successCount++;
            } else {
                failCount++;
            }
        } catch (e) {
            // Fallback: local deletion
            lsDeleteItem(id);
            successCount++;
        }
    }

    if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-trash-can"></i> Excluir Selecionados';
        btn.disabled = false;
    }

    showToast(`${successCount} itens excluídos com sucesso.${failCount > 0 ? ` ${failCount} falhas.` : ''}`, 'success');
    loadHistoryTab();
}

window.toggleActivePortfolio = toggleActivePortfolio;
window.selectAllHistory = selectAllHistory;
window.deleteSelectedHistory = deleteSelectedHistory;
window.applyEvSuggestion = applyEvSuggestion;
window.applyLeagueSuggestion = applyLeagueSuggestion;
window.applyOddsSuggestion = applyOddsSuggestion;
window.applyScannedStrategy = applyScannedStrategy;
window.loadPortfolio = loadPortfolio;
window.simulateSelectedScannerItems = simulateSelectedScannerItems;

// Expose missing UI event handlers to global scope
window.clearDashboard = clearDashboard;
window.requestNotificationPermission = requestNotificationPermission;
window.savePortfolio = savePortfolio;
window.testNotificationAlert = testNotificationAlert;


window.updateCacheStatus = function() {
    const backtestCache = JSON.parse(localStorage.getItem('radar_backtest_cache') || '{}');
    const cacheCount = Object.keys(backtestCache).length;
    const cacheStatusEl = document.getElementById('live-cache-status');
    if (cacheStatusEl) {
        cacheStatusEl.innerHTML = cacheCount > 0 ?
            '<span style="color: #34d399; font-weight: bold;"><i class="fa-solid fa-circle-check"></i> Cerebro Conectado:</span> ' + cacheCount + ' nichos em cache.' :
            '<span style="color: #f59e0b;"><i class="fa-solid fa-circle-exclamation"></i> Laboratorio Desconectado:</span> Rode um backtest para ativar filtros.';
    }
};

function renderWalkForwardResults(data) {
    ['transparency-panel', 'stat-validation-panel', 'drift-validation-panel',
     'robustness-stress-panel', 'staking-comparison-panel'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    var panel = document.getElementById('walk-forward-results-panel');
    if (panel) panel.style.display = 'block';

    var tbody = document.getElementById('walk-forward-tbody');
    if (tbody && data.fold_results) {
        tbody.innerHTML = data.fold_results.map(function(f) {
            var roiColor = f.roi >= 0 ? '#34d399' : '#f87171';
            var profitColor = f.net_profit >= 0 ? '#34d399' : '#f87171';
            return '<tr>' +
                '<td style="padding:8px;font-weight:bold;color:#38bdf8;">Fold ' + f.fold + '</td>' +
                '<td style="padding:8px;font-size:10px;color:var(--text-secondary);">' + f.train_start + ' &rarr; ' + f.train_end + '</td>' +
                '<td style="padding:8px;font-size:10px;color:var(--text-secondary);">' + f.test_start + ' &rarr; ' + f.test_end + '</td>' +
                '<td style="padding:8px;text-align:center;">' + f.total_bets + '</td>' +
                '<td style="padding:8px;text-align:right;color:' + profitColor + ';font-weight:bold;">' + (f.net_profit >= 0 ? '+' : '') + '$' + f.net_profit.toFixed(2) + '</td>' +
                '<td style="padding:8px;text-align:right;color:' + roiColor + ';font-weight:bold;">' + (f.roi >= 0 ? '+' : '') + f.roi.toFixed(2) + '%</td>' +
                '<td style="padding:8px;text-align:right;">' + f.win_rate.toFixed(1) + '%</td>' +
                '<td style="padding:8px;text-align:right;color:#f87171;">-' + f.max_drawdown_pct.toFixed(1) + '%</td>' +
                '</tr>';
        }).join('');
    }

    var scoreCard = document.getElementById('walk-forward-score-card');
    if (scoreCard) {
        var meanRoi = data.mean_roi;
        var medianRoi = data.median_roi;
        var cvRoi = data.cv_roi;
        var wfScore = data.walk_forward_score;
        var verdict = data.verdict;
        var positiveFoldsPct = data.positive_folds_pct;
        var meanDD = data.mean_max_drawdown;
        var verdictColor = verdict === 'STRONG' ? '#34d399' : (verdict === 'MODERATE' ? '#f59e0b' : '#ef4444');
        var scoreColor = wfScore >= 70 ? '#34d399' : (wfScore >= 45 ? '#f59e0b' : '#ef4444');
        var cvColor = cvRoi < 1.0 ? '#34d399' : (cvRoi < 2.0 ? '#f59e0b' : '#ef4444');

        scoreCard.innerHTML = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;">' +
            '<div style="background:rgba(56,189,248,0.08);border:1px solid rgba(56,189,248,0.2);padding:12px;border-radius:6px;text-align:center;">' +
                '<div style="font-size:10px;color:var(--text-secondary);margin-bottom:4px;">WF Score</div>' +
                '<div style="font-size:28px;font-weight:bold;color:' + scoreColor + ';">' + wfScore + '</div>' +
                '<div style="font-size:10px;color:' + verdictColor + ';font-weight:bold;margin-top:2px;">' + verdict + '</div>' +
            '</div>' +
            '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);padding:12px;border-radius:6px;text-align:center;">' +
                '<div style="font-size:10px;color:var(--text-secondary);margin-bottom:4px;">ROI Medio</div>' +
                '<div style="font-size:22px;font-weight:bold;color:' + (meanRoi >= 0 ? '#34d399' : '#f87171') + ';">' + (meanRoi >= 0 ? '+' : '') + meanRoi.toFixed(2) + '%</div>' +
                '<div style="font-size:10px;color:var(--text-secondary);">Mediana: ' + (medianRoi >= 0 ? '+' : '') + medianRoi.toFixed(2) + '%</div>' +
            '</div>' +
            '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);padding:12px;border-radius:6px;text-align:center;">' +
                '<div style="font-size:10px;color:var(--text-secondary);margin-bottom:4px;">Estabilidade (CV)</div>' +
                '<div style="font-size:22px;font-weight:bold;color:' + cvColor + ';">' + cvRoi.toFixed(2) + '</div>' +
                '<div style="font-size:10px;color:var(--text-secondary);">Menor = melhor</div>' +
            '</div>' +
            '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);padding:12px;border-radius:6px;text-align:center;">' +
                '<div style="font-size:10px;color:var(--text-secondary);margin-bottom:4px;">Folds Positivos</div>' +
                '<div style="font-size:22px;font-weight:bold;color:' + (positiveFoldsPct >= 60 ? '#34d399' : '#f59e0b') + ';">' + data.positive_folds + '/' + data.n_folds + '</div>' +
                '<div style="font-size:10px;color:var(--text-secondary);">' + positiveFoldsPct.toFixed(0) + '% dos folds</div>' +
            '</div>' +
            '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);padding:12px;border-radius:6px;text-align:center;">' +
                '<div style="font-size:10px;color:var(--text-secondary);margin-bottom:4px;">DD Medio</div>' +
                '<div style="font-size:22px;font-weight:bold;color:#f87171;">-' + meanDD.toFixed(1) + '%</div>' +
                '<div style="font-size:10px;color:var(--text-secondary);">Max DD entre folds</div>' +
            '</div>' +
        '</div>' +
        '<div style="margin-top:10px;padding:8px 12px;background:rgba(56,189,248,0.05);border-left:3px solid #38bdf8;border-radius:4px;font-size:11px;color:var(--text-secondary);">' +
            '<strong style="color:#38bdf8;">Como interpretar:</strong> WF Score >= 70 (STRONG) = robusto. Score < 45 (WEAK) = overfitting. CV baixo = ROI consistente entre folds.' +
        '</div>';
    }

    var totalBetsEl = document.getElementById('metric-total-bets');
    if (totalBetsEl) totalBetsEl.innerText = data.total_oos_bets;
}

window.addEventListener('DOMContentLoaded', () => {
    if (typeof window.updateCacheStatus === 'function') {
        window.updateCacheStatus();
    }
});
