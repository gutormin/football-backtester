// Auto-extracted from app.js — History tab, save/load strategies, import/export
import { showToast, switchTab, formatCurrency, formatPct } from './utils.js';
import { fetchServerHistory, saveToServer, deleteFromServer, toggleServerActiveState, API_BASE_URL } from './api.js';

// Safe wrappers for localStorage functions defined in app.js.
// app.js may not have finished loading when this module executes,
// so we guard every call to avoid "is not defined" errors on Render.
function safeLsLoadHistory() {
    if (typeof window.lsLoadHistory === 'function') return window.lsLoadHistory();
    try { return JSON.parse(localStorage.getItem('predictive_history_v3') || '[]'); } catch { return []; }
}
function safeLsSaveHistory(data) {
    if (typeof window.lsSaveHistory === 'function') { window.lsSaveHistory(data); return; }
    try { localStorage.setItem('predictive_history_v3', JSON.stringify(data)); } catch {}
}
function safeLsSyncToServer(items) {
    if (typeof window.lsSyncToServer === 'function') return window.lsSyncToServer(items);
    return Promise.resolve();
}
function safeLsAddItem(item) {
    if (typeof window.lsAddItem === 'function') { window.lsAddItem(item); return; }
    const h = safeLsLoadHistory();
    const idx = h.findIndex(x => x.id === item.id);
    if (idx >= 0) h[idx] = item; else h.unshift(item);
    safeLsSaveHistory(h);
}
function safeLsDeleteItem(id) {
    if (typeof window.lsDeleteItem === 'function') { window.lsDeleteItem(id); return; }
    safeLsSaveHistory(safeLsLoadHistory().filter(x => x.id !== id));
}

// History / Saved Strategies Logic

// ==========================================================================



function openSaveStrategyModal() {

    if (!window.lastBacktestParams || !window.lastBacktestSummary) {

        showToast("Rode um backtest primeiro para salvar a estratégia.", "error");

        return;

    }

    document.getElementById('save-strategy-modal').style.display = 'flex';

    

    // Auto-fill strategy name using the live banner displayed in the header
    const leagueText  = (document.getElementById('active-leagues-text') || {}).innerText || '';
    const marketText  = (document.getElementById('active-market-text')  || {}).innerText || '';
    const oddsText    = (document.getElementById('active-odds-text')    || {}).innerText || '';
    const evText      = (document.getElementById('active-ev-text')      || {}).innerText || '';

    // Build a clean name from the visible pieces, skipping empty parts
    const nameParts = [];
    if (leagueText && leagueText !== 'N/A') nameParts.push(leagueText.trim());
    if (marketText && marketText !== 'N/A') {
        // Strip internal codes like "(odds_ft_under45)FD √FP" — keep only human label
        const cleanMarket = marketText.split('(')[0].trim();
        if (cleanMarket) nameParts.push(cleanMarket);
    }
    if (oddsText) nameParts.push('Odds: ' + oddsText.trim());
    if (evText)   nameParts.push('EV: '   + evText.trim());

    // Fallback to parameter-based name if banner is empty
    const evVal = window.lastBacktestParams.valueThreshold || '1.05';
    const minO  = window.lastBacktestParams.minOdds || 1.0;
    const maxO  = window.lastBacktestParams.maxOdds || 2.50;
    const suggestedName = nameParts.length > 0
        ? nameParts.join(' | ')
        : `Estratégia (EV: ${evVal} | Odds: ${minO.toFixed(2)}-${maxO.toFixed(2)})`;

    document.getElementById('save-strategy-name').value = suggestedName;

    document.getElementById('save-strategy-name').focus();

}



function closeSaveStrategyModal() {

    document.getElementById('save-strategy-modal').style.display = 'none';

}



async function submitSaveStrategy() {

    const nameInput = document.getElementById('save-strategy-name').value.trim();

    const finalName = nameInput || "Estratégia " + new Date().toLocaleDateString('pt-BR');

    // Sanitize NaN/Infinity values (JSON doesn't support them)
    const sanitize = (obj) => {
        if (obj === null || obj === undefined) return obj;
        if (typeof obj === 'number' && (isNaN(obj) || !isFinite(obj))) return null;
        if (Array.isArray(obj)) return obj.map(sanitize);
        if (typeof obj === 'object') {
            const cleaned = {};
            for (const [k, v] of Object.entries(obj)) {
                cleaned[k] = sanitize(v);
            }
            return cleaned;
        }
        return obj;
    };

    const payload = sanitize({
        name: finalName,
        params: window.lastBacktestParams,
        summary: window.lastBacktestSummary.summary,
        created_at: new Date().toISOString()
    });



    try {

        const res = await fetch(`${API_BASE_URL}/api/history`, {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify(payload)

        });

        

        if (!res.ok) throw new Error("Erro ao salvar estratégia.");

        // Persist to localStorage so it survives server restarts
        const saved = await res.json();
        if (saved && saved.entry) safeLsAddItem(saved.entry);

        showToast("Estratégia salva com sucesso no Histórico!", "success");

        closeSaveStrategyModal();

        await loadHistoryTab();

    } catch (err) {

        console.error(err);

        showToast(err.message, "error");

    }

}



async function loadHistoryTab() {

    const grid = document.getElementById('history-grid');

    const emptyState = document.getElementById('history-empty');

    // Visual feedback: disable refresh button and show spinner
    const refreshBtn = document.querySelector('#tab-history .btn-clear i.fa-rotate-right');
    const refreshBtnParent = refreshBtn ? refreshBtn.closest('button') : null;
    if (refreshBtnParent) {
        refreshBtnParent.disabled = true;
        refreshBtnParent.style.opacity = '0.6';
        refreshBtn.className = 'fa-solid fa-spinner fa-spin';
    }
    showToast('Sincronizando histórico com o servidor...', 'info', 3000);

    grid.innerHTML = '<div style="text-align:center; grid-column: 1/-1;"><div class="loading-spinner"></div> Carregando histórico...</div>';

    emptyState.style.display = 'none';



    // ── 1. Show localStorage data IMMEDIATELY — never block the grid on server availability ──
    const localHistory = safeLsLoadHistory();
    if (localHistory.length > 0) {
        window.loadedHistoryStrategies = localHistory;
        applyHistoryFilters();
    }

    // ── 2. Fetch from server in background (non-blocking) ──
    try {
        let serverHistory = [];
        try {
            const res = await fetch(`${API_BASE_URL}/api/history?t=${Date.now()}`, { cache: 'no-store' });
            if (res.ok) {
                serverHistory = await res.json();
            }
        } catch (fetchErr) {
            // Server unreachable — keep showing localStorage data, no error to user
            console.warn('loadHistoryTab: servidor indisponível, usando dados locais apenas.', fetchErr.message);
        }

        if (serverHistory.length === 0 && localHistory.length > 0) {
            // Grid already rendered from localStorage above — nothing more to do
            return;
        }

        // Find items in localStorage that the server doesn't have (lost after redeploy)
        const serverIds = new Set(serverHistory.map(x => x.id));
        const localOnly = localHistory.filter(x => !serverIds.has(x.id));

        // For items that exist on both sides, check if is_tg_active status differs.
        // If they differ, the local state (user setting stored in browser) wins, and we update/sync it to the server.
        const serverMap = new Map(serverHistory.map(x => [x.id, x]));
        const itemsToUpdateOnServer = [];
        for (const localItem of localHistory) {
            const serverItem = serverMap.get(localItem.id);
            if (serverItem) {
                const localActive = !!localItem.is_tg_active;
                const serverActive = !!serverItem.is_tg_active;
                if (localActive !== serverActive) {
                    serverItem.is_tg_active = localActive;
                    itemsToUpdateOnServer.push(serverItem);
                }
            }
        }

        // Sync missing items back to server (fire-and-forget — don't block grid render)
        const syncItems = [...localOnly, ...itemsToUpdateOnServer];
        if (syncItems.length > 0) {
            safeLsSyncToServer(syncItems);  // fire-and-forget, don't await
        }

        // Merge: localOnly items + server items (deduped)
        const merged = [...localOnly, ...serverHistory];

        // Keep localStorage up-to-date with the merged set
        safeLsSaveHistory(merged);
        window.loadedHistoryStrategies = merged;

        applyHistoryFilters();

    } catch (err) {

        console.error('loadHistoryTab error:', err);

        // Fallback: if we haven't rendered anything yet, try localStorage
        if (!window.loadedHistoryStrategies || window.loadedHistoryStrategies.length === 0) {
            const fallback = safeLsLoadHistory();
            if (fallback.length > 0) {
                window.loadedHistoryStrategies = fallback;
                applyHistoryFilters();
            } else {
                grid.innerHTML = `<div style="color: var(--danger); padding: 20px;">Erro ao carregar o histórico: ${err.message}</div>`;
            }
        }
    } finally {
        // Restore refresh button
        const rb = document.querySelector('#tab-history .btn-clear i.fa-spinner');
        const rbp = rb ? rb.closest('button') : null;
        if (rbp) {
            rbp.disabled = false;
            rbp.style.opacity = '1';
            rb.className = 'fa-solid fa-rotate-right';
        }
        const count = (window.loadedHistoryStrategies || []).length;
        showToast(`Histórico sincronizado: ${count} itens carregados.`, 'success', 3000);
    }

}

function applyHistoryFilters() {
    if (!window.loadedHistoryStrategies) return;

    let items = [...window.loadedHistoryStrategies];

    // 1. Filter by Type
    const filterType = document.getElementById('history-filter-type')?.value || 'all';
    if (filterType === 'strategy') {
        items = items.filter(x => x.type !== 'portfolio' && (!x.params || !x.params.strategy_ids));
    } else if (filterType === 'portfolio') {
        items = items.filter(x => x.type === 'portfolio' || (x.params && x.params.strategy_ids));
    }

    // 2. Filter by Market
    const filterMarket = document.getElementById('history-filter-market')?.value || 'all';
    if (filterMarket !== 'all') {
        items = items.filter(x => {
            const p = x.params || {};
            if (x.type === 'portfolio' || p.strategy_ids) {
                // If it is a portfolio, check if any strategy in loaded history matches
                const subIds = p.strategy_ids || [];
                const subStrategies = window.loadedHistoryStrategies.filter(sub => subIds.includes(sub.id));
                return subStrategies.some(sub => {
                    const subMarket = sub.params?.market;
                    if (Array.isArray(subMarket)) return subMarket.includes(filterMarket);
                    return subMarket === filterMarket;
                });
            } else {
                const mk = p.market;
                if (Array.isArray(mk)) return mk.includes(filterMarket);
                return mk === filterMarket;
            }
        });
    }

    // 3. Filter by Search Query (name / league / market)
    const searchQuery = document.getElementById('history-filter-search')?.value.toLowerCase().trim() || '';
    if (searchQuery) {
        items = items.filter(x => {
            const name = (x.name || '').toLowerCase();
            const p = x.params || {};
            
            // Check leagues
            let leaguesStr = '';
            if (p.leagues && p.leagues.length > 0) {
                leaguesStr = p.leagues.map(code => {
                    const found = window.AVAILABLE_LEAGUES ? window.AVAILABLE_LEAGUES.find(l => l.code === code) : null;
                    return found ? found.name : code;
                }).join(', ').toLowerCase();
            }

            // Check markets
            let marketsStr = '';
            if (p.market) {
                marketsStr = (Array.isArray(p.market) ? p.market.join(', ') : p.market).toLowerCase();
            }

            // Check sub-strategies leagues/markets if portfolio
            if (x.type === 'portfolio' || p.strategy_ids) {
                const subIds = p.strategy_ids || [];
                const subStrategies = window.loadedHistoryStrategies.filter(sub => subIds.includes(sub.id));
                const subLeagues = subStrategies.map(sub => {
                    if (sub.params?.leagues) {
                        return sub.params.leagues.map(code => {
                            const found = window.AVAILABLE_LEAGUES ? window.AVAILABLE_LEAGUES.find(l => l.code === code) : null;
                            return found ? found.name : code;
                        }).join(' ');
                    }
                    return '';
                }).join(' ').toLowerCase();
                
                const subMarkets = subStrategies.map(sub => {
                    if (sub.params?.market) {
                        return Array.isArray(sub.params.market) ? sub.params.market.join(' ') : sub.params.market;
                    }
                    return '';
                }).join(' ').toLowerCase();

                return name.includes(searchQuery) || subLeagues.includes(searchQuery) || subMarkets.includes(searchQuery);
            }

            return name.includes(searchQuery) || leaguesStr.includes(searchQuery) || marketsStr.includes(searchQuery);
        });
    }

    // 4. Sort By
    const sortBy = document.getElementById('history-sort-by')?.value || 'date-desc';
    items.sort((a, b) => {
        const sA = a.summary || {};
        const sB = b.summary || {};
        
        switch (sortBy) {
            case 'date-desc':
                return new Date(b.created_at || 0) - new Date(a.created_at || 0);
            case 'date-asc':
                return new Date(a.created_at || 0) - new Date(b.created_at || 0);
            case 'name-asc':
                return (a.name || '').localeCompare(b.name || '');
            case 'profit-desc':
                return (sB.net_profit || 0) - (sA.net_profit || 0);
            case 'winrate-desc':
                return (sB.win_rate || 0) - (sA.win_rate || 0);
            case 'roi-desc':
                return (sB.roi || 0) - (sA.roi || 0);
            default:
                return 0;
        }
    });

    renderHistoryGrid(items);
}

function renderHistoryGrid(history) {
    const grid = document.getElementById('history-grid');
    const emptyState = document.getElementById('history-empty');
    if (!grid) return;

    if (!history || history.length === 0) {
        grid.innerHTML = '';
        emptyState.style.display = 'block';
        return;
    }
    emptyState.style.display = 'none';
    grid.innerHTML = '';

    history.forEach(item => {
        // Guarantee correct timezone parsing if it comes from the python backend without Z
        let dtStr = item.created_at;
        if (dtStr && !dtStr.endsWith('Z') && !dtStr.includes('+')) {
            // If it contains a timezone-naive ISO string from Python, append 'Z' to treat as UTC
            dtStr += 'Z';
        }
        const dateStr = new Date(dtStr).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });

        const s = item.summary || {};
        const p = item.params || {};

        const card = document.createElement('div');
        card.className = 'eval-card glassmorphism';
        card.style.display = 'flex';
        card.style.flexDirection = 'column';
        card.style.justifyContent = 'space-between';

        if (item.type === 'portfolio' || (p && p.strategy_ids)) {
            // Portfolio Card with premium distinct purple styling
            card.style.borderLeft = '5px solid #a78bfa'; // Glowing purple border
            card.style.background = 'linear-gradient(135deg, rgba(139, 92, 246, 0.12) 0%, rgba(20, 15, 45, 0.6) 100%)';
            card.style.borderColor = 'rgba(139, 92, 246, 0.3)';
            card.style.boxShadow = '0 8px 32px 0 rgba(139, 92, 246, 0.08), inset 0 1px 0 0 rgba(255, 255, 255, 0.05)';
            
            const isActive = item.is_tg_active === true;
            const activeBadge = isActive ? `<span style="font-size: 11px; background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 3px 6px; border-radius: 4px; border: 1px solid rgba(16, 185, 129, 0.3);"><i class="fa-brands fa-telegram"></i> Ativo no Robô</span>` : '';
            const btnActiveHtml = isActive ? 
                `<button class="btn-clear" onclick="toggleActivePortfolio('${item.id}')" style="flex: 1; padding: 6px; font-size: 13px; color: var(--text-primary); background: rgba(255,255,255,0.05);"><i class="fa-solid fa-bell-slash"></i> Desativar</button>` :
                `<button class="btn-scanner" onclick="toggleActivePortfolio('${item.id}')" style="flex: 1; padding: 6px; font-size: 13px; margin: 0; background: rgba(16, 185, 129, 0.2); border-color: #10b981; color: #10b981;"><i class="fa-brands fa-telegram"></i> Ativar no Robô</button>`;

            card.innerHTML = `
                <div>
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 15px;">
                        <div style="display: flex; flex-direction: column; gap: 5px;">
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <input type="checkbox" class="history-select-checkbox" data-type="portfolio" value="${item.id}" style="width: 18px; height: 18px; cursor: pointer;">
                                <i class="fa-solid fa-layer-group" style="color: #c084fc; font-size: 18px;"></i>
                                <h4 style="margin: 0; color: #f3e8ff; font-size: 16px; font-weight: 700;">${item.name}</h4>
                            </div>
                            <div>${activeBadge}</div>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 5px;">
                            <span style="font-size: 10px; font-weight: 800; text-transform: uppercase; color: #e9d5ff; background: rgba(168, 85, 247, 0.3); border: 1px solid rgba(168, 85, 247, 0.5); padding: 2px 6px; border-radius: 4px; letter-spacing: 0.8px;">Portfólio</span>
                            <span style="font-size: 12px; color: var(--text-muted); background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 4px;">${dateStr}</span>
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 15px; font-size: 13px; color: #e9d5ff;">
                        <div style="margin-bottom: 4px;"><strong>Tipo:</strong> <span style="color:#c084fc; font-weight: 600;">Portfólio Combinado</span></div>
                        <div style="margin-bottom: 4px;"><strong>Estratégias:</strong> ${p.strategy_ids ? p.strategy_ids.length : 0} combinadas</div>
                    </div>
                    
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px; background: rgba(139, 92, 246, 0.05); border: 1px solid rgba(139, 92, 246, 0.15); padding: 10px; border-radius: 8px;">
                        <div>
                            <div style="font-size: 11px; color: #d8b4fe; text-transform: uppercase;">Win Rate</div>
                            <div style="font-size: 15px; font-weight: 700; color: ${s.win_rate > 50 ? 'var(--success)' : 'var(--text-primary)'};">${s.win_rate}%</div>
                        </div>
                        <div>
                            <div style="font-size: 11px; color: #d8b4fe; text-transform: uppercase;">Lucro</div>
                            <div style="font-size: 15px; font-weight: 700; color: ${s.net_profit > 0 ? 'var(--success)' : 'var(--danger)'};">$${s.net_profit}</div>
                        </div>
                        <div>
                            <div style="font-size: 11px; color: #d8b4fe; text-transform: uppercase;">ROI</div>
                            <div style="font-size: 15px; font-weight: 700; color: ${s.roi > 0 ? 'var(--success)' : 'var(--danger)'};">${s.roi}%</div>
                        </div>
                        <div>
                            <div style="font-size: 11px; color: #d8b4fe; text-transform: uppercase;">Drawdown</div>
                            <div style="font-size: 15px; font-weight: 700; color: var(--danger);">${s.max_drawdown}%</div>
                        </div>
                    </div>
                </div>
                <div style="display: flex; gap: 10px; border-top: 1px solid rgba(139, 92, 246, 0.15); padding-top: 15px; flex-wrap: wrap;">
                    <button class="btn-clear" onclick="deleteHistoryStrategy('${item.id}')" style="flex: 1; padding: 6px; font-size: 13px; color: var(--danger);"><i class="fa-solid fa-trash"></i> Excluir</button>
                    <button class="btn-scanner" onclick="loadPortfolio('${item.id}')" style="flex: 1; padding: 6px; font-size: 13px; margin: 0; background: rgba(168, 85, 247, 0.25); border-color: #a855f7; color: #fff;"><i class="fa-solid fa-check-square"></i> Abrir</button>
                    ${btnActiveHtml}
                </div>
            `;
            grid.appendChild(card);
            return;
        }

        card.style.borderLeft = '4px solid var(--primary)';

        // Leagues format
        let leaguesTxt = "Todas";
        if (p.leagues && p.leagues.length > 0) {
            const names = p.leagues.map(code => {
                const found = window.AVAILABLE_LEAGUES ? window.AVAILABLE_LEAGUES.find(l => l.code === code) : null;
                return found ? found.name : code;
            });
            leaguesTxt = names.length > 3 ? `${names.slice(0,3).join(', ')} e +${names.length - 3}` : names.join(', ');
        }

        let ruleText = "Desconhecida";
        if (p.stakingRule === 'fixed') {
            ruleText = `Fixo ($${p.stakeValue || 10.0})`;
        } else if (p.stakingRule === 'proportional') {
            ruleText = `Proporcional (${p.stakeValue || 2.0}%)`;
        } else if (p.stakingRule === 'kelly') {
            const frac = p.stakeValue || 0.25;
            let fracName = "";
            if (frac === 1) fracName = "Full";
            else {
                const inv = 1 / frac;
                fracName = `1/${inv.toFixed(0)}`;
            }
            ruleText = `Kelly (${fracName} - ${frac * 100}%)`;
        }

        let sourceText = "Football-Data CSV";
        if (p.data_source === 'futpython') {
            sourceText = "Futpython API";
        }

        const isActive = item.is_tg_active === true;
        const activeBadge = isActive ? `<span style="font-size: 11px; background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 3px 6px; border-radius: 4px; border: 1px solid rgba(16, 185, 129, 0.3);"><i class="fa-brands fa-telegram"></i> Ativo no Robô</span>` : '';
        const btnActiveHtml = isActive ? 
            `<button class="btn-clear" onclick="toggleActivePortfolio('${item.id}')" style="flex: 1; padding: 6px; font-size: 13px; color: var(--text-primary); background: rgba(255,255,255,0.05);"><i class="fa-solid fa-bell-slash"></i> Desativar</button>` :
            `<button class="btn-scanner" onclick="toggleActivePortfolio('${item.id}')" style="flex: 1; padding: 6px; font-size: 13px; margin: 0; background: rgba(16, 185, 129, 0.2); border-color: #10b981; color: #10b981;"><i class="fa-brands fa-telegram"></i> Ativar no Robô</button>`;

        card.innerHTML = `
            <div>
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 15px;">
                    <div style="display: flex; flex-direction: column; gap: 5px;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <input type="checkbox" class="portfolio-checkbox history-select-checkbox" data-type="strategy" value="${item.id}" style="width: 18px; height: 18px; cursor: pointer;">
                            <h4 style="margin: 0; color: var(--text-primary); font-size: 16px;">${item.name}</h4>
                        </div>
                        <div>${activeBadge}</div>
                    </div>
                    <span style="font-size: 12px; color: var(--text-muted); background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 4px;">${dateStr}</span>
                </div>
                
                <div style="margin-bottom: 15px; font-size: 13px; color: var(--text-secondary); display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px;">
                    <div><strong>Mercado:</strong> <span style="color:var(--info);">${p.market || 'Desconhecido'}</span></div>
                    <div><strong>Fonte:</strong> <span style="color:#a78bfa;">${sourceText}</span></div>
                    <div style="grid-column: 1 / -1;"><strong>Ligas:</strong> ${leaguesTxt}</div>
                    <div><strong>Odds:</strong> ${p.minOdds} a ${p.maxOdds}</div>
                    <div><strong>Gestão:</strong> <span style="color:#fbbf24;">${ruleText}</span></div>
                </div>
                
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 15px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px;">
                    <div>
                        <div style="font-size: 11px; color: var(--text-muted);">Win Rate</div>
                        <div style="font-size: 14px; font-weight: bold; color: ${s.win_rate != null && s.win_rate >= 50 ? 'var(--success)' : 'var(--warning)'};">${s.win_rate != null ? s.win_rate.toFixed(1) + '%' : '--'}</div>
                    </div>
                    <div>
                        <div style="font-size: 11px; color: var(--text-muted);">Lucro</div>
                        <div style="font-size: 14px; font-weight: bold; color: ${s.net_profit != null && s.net_profit >= 0 ? 'var(--success)' : 'var(--danger)'};">${s.net_profit != null ? '$' + s.net_profit.toFixed(2) : '--'}</div>
                    </div>
                    <div>
                        <div style="font-size: 11px; color: var(--text-muted);">ROI</div>
                        <div style="font-size: 14px; font-weight: bold; color: ${s.roi != null && s.roi >= 0 ? 'var(--success)' : 'var(--danger)'};">${s.roi != null ? s.roi.toFixed(2) + '%' : '--'}</div>
                    </div>
                    <div>
                        <div style="font-size: 11px; color: var(--text-muted);">Drawdown</div>
                        <div style="font-size: 14px; font-weight: bold; color: var(--danger);">${s.max_drawdown != null ? s.max_drawdown.toFixed(1) + '%' : '--'}</div>
                    </div>
                    <div>
                        <div style="font-size: 11px; color: var(--text-muted);">Sharpe</div>
                        <div style="font-size: 14px; font-weight: bold; color: ${s.sharpe_ratio != null && s.sharpe_ratio >= 1 ? 'var(--success)' : 'var(--text-primary)'};">${s.sharpe_ratio != null ? s.sharpe_ratio.toFixed(2) : '--'}</div>
                    </div>
                    <div>
                        <div style="font-size: 11px; color: var(--text-muted);">Apostas</div>
                        <div style="font-size: 14px; font-weight: bold; color: var(--text-primary);">${s.total_bets != null ? s.total_bets : '--'}</div>
                    </div>
                </div>
            </div>
            
            <div style="display: flex; gap: 10px; margin-top: auto; flex-wrap: wrap;">
                <button class="btn-clear" onclick="deleteHistoryStrategy('${item.id}')" style="flex: 1; justify-content: center; color: var(--danger); border-color: rgba(239, 68, 68, 0.2); padding: 6px; font-size: 13px;"><i class="fa-solid fa-trash-can"></i> Excluir</button>
                <button class="btn-scanner" onclick="reloadStrategyById('${item.id}')" style="flex: 1; justify-content: center; padding: 6px; font-size: 13px;"><i class="fa-solid fa-play"></i> Carregar</button>
                ${btnActiveHtml}
            </div>
        `;
        grid.appendChild(card);
    });
}

async function deleteHistoryStrategy(id) {

    if (!confirm("Tem certeza que deseja excluir esta estratégia salva?")) return;

    

    try {

        const res = await fetch(`${API_BASE_URL}/api/history/${id}`, { method: 'DELETE' });

        if (!res.ok) throw new Error("Falha ao excluir.");

        

        // Remove from localStorage too
        safeLsDeleteItem(id);
        showToast("Estratégia excluída.", "success");
        loadHistoryTab();

    } catch (err) {
        // Even if server fails, remove from localStorage
        safeLsDeleteItem(id);
        loadHistoryTab();
        showToast(err.message, "error");
    }
}



async function reloadStrategyById(id) {
    try {
        console.log("reloadStrategyById called with id:", id);
        let strategy = null;
        if (window.loadedHistoryStrategies) {
            strategy = window.loadedHistoryStrategies.find(s => s.id === id);
        }
        if (!strategy) {
            const local = safeLsLoadHistory();
            strategy = local.find(s => s.id === id);
        }
        if (!strategy) {
            throw new Error("Estratégia não encontrada no histórico.");
        }
        console.log("Found strategy params:", strategy.params);
        await reloadStrategy(strategy.params);
    } catch (err) {
        console.error("Erro ao carregar estratégia por ID:", err);
        showToast("Erro ao carregar estratégia: " + err.message, "error");
    }
}

window.reloadStrategyById = reloadStrategyById;
window.reloadStrategy = reloadStrategy;


async function reloadStrategy(params) {

    if (!params) {
        console.warn("reloadStrategy called without params");
        return;
    }

    try {
        console.log("reloadStrategy executing with params:", params);

        // Switch to Laboratory Tab
        switchTab('tab-laboratory');

        // Fill data source first and wait for leagues to load
        if (params.data_source && document.getElementById('data-source-select')) {
            const dsSelect = document.getElementById('data-source-select');
            console.log("Setting data source to:", params.data_source);
            if (dsSelect.value !== params.data_source) {
                dsSelect.value = params.data_source;
                if (typeof handleDataSourceChange === 'function') {
                    await handleDataSourceChange();
                }
            }
        }

        // Force-load leagues if the checkboxes container is currently empty
        const leaguesList = document.getElementById('leagues-checkbox-list');
        const hasLeaguesLoaded = leaguesList && leaguesList.querySelectorAll('input[type="checkbox"]').length > 0;
        if (!hasLeaguesLoaded && typeof loadLeagues === 'function') {
            console.log("Leagues not loaded in DOM, calling loadLeagues");
            await loadLeagues();
        }

        // Fill basic fields
        if (params.market) {
            const marketsToSelect = Array.isArray(params.market) ? params.market : [params.market];
            const marketCheckboxes = document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]');
            if (marketCheckboxes.length > 0) {
                marketCheckboxes.forEach(cb => {
                    cb.checked = marketsToSelect.includes(cb.value);
                });
            }
            if (typeof onMarketSelectionChange === 'function') {
                onMarketSelectionChange();
            }
        }
        
        if (params.minOdds !== undefined) document.getElementById('min-odds').value = params.minOdds;
        if (params.maxOdds !== undefined) document.getElementById('max-odds').value = params.maxOdds;
        
        if (params.startDate) document.getElementById('start-date').value = params.startDate;
        if (params.endDate) document.getElementById('end-date').value = params.endDate;
        
        if (params.leagues && Array.isArray(params.leagues)) {
            // Uncheck all first
            document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"], input[name="league-group"]').forEach(cb => cb.checked = false);
            // Check saved
            params.leagues.forEach(code => {
                let cb = document.getElementById('league-' + code);
                if (!cb) {
                    try {
                        cb = document.querySelector(`#leagues-checkbox-list input[value="${code}"], input[name="league-group"][value="${code}"]`);
                    } catch (e) {
                        const allCbs = document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"], input[name="league-group"]');
                        for (const input of allCbs) {
                            if (input.value === code || input.id === 'league-' + code) {
                                cb = input;
                                break;
                            }
                        }
                    }
                }
                if (cb) cb.checked = true;
            });
            if (typeof updateLeagueLabel === 'function') updateLeagueLabel();
        }
        
        // Fill EV and Gestão fields
        if (params.valueThreshold !== undefined && document.getElementById('val-threshold')) document.getElementById('val-threshold').value = params.valueThreshold;
        if (params.initialBankroll !== undefined && document.getElementById('init-bankroll')) document.getElementById('init-bankroll').value = params.initialBankroll;
        
        if (params.stakingRule) {
            const srEl = document.getElementById('stake-rule');
            if (srEl) {
                let mappedRule = params.stakingRule;
                let mappedFraction = params.stakeValue;
                
                if (params.stakingRule.startsWith('kelly')) {
                    mappedRule = 'kelly';
                    if (params.stakingRule === 'kelly_half') mappedFraction = 0.5;
                    else if (params.stakingRule === 'kelly_quarter') mappedFraction = 0.25;
                    else if (params.stakingRule === 'kelly_eighth') mappedFraction = 0.125;
                    else if (params.stakingRule === 'kelly_sixteenth') mappedFraction = 0.0625;
                }
                
                srEl.value = mappedRule;
                srEl.dispatchEvent(new Event('change'));
                
                if (mappedRule === 'kelly' && document.getElementById('kelly-fraction')) {
                    const kf = document.getElementById('kelly-fraction');
                    kf.value = mappedFraction;
                    // Fire input event to trigger UI text update next to slider
                    kf.dispatchEvent(new Event('input'));
                } else if (document.getElementById('stake-value')) {
                    document.getElementById('stake-value').value = mappedFraction;
                }
            }
        }
        
        if (params.oddsSource && document.getElementById('odds-source')) document.getElementById('odds-source').value = params.oddsSource;
        if (params.odds_timing && document.getElementById('odds-timing')) document.getElementById('odds-timing').value = params.odds_timing;
        if (params.exchange_commission !== undefined && document.getElementById('exchange-commission')) document.getElementById('exchange-commission').value = params.exchange_commission;
        
        if (params.out_of_sample !== undefined && document.getElementById('oos-toggle')) document.getElementById('oos-toggle').checked = params.out_of_sample;
        if (params.use_ml !== undefined && document.getElementById('use-ml-toggle')) document.getElementById('use-ml-toggle').checked = params.use_ml;
        if (params.model_type && document.getElementById('model-type-select')) document.getElementById('model-type-select').value = params.model_type;

        // Clean & set sub-market odds filters (minOddsH, maxOddsH, etc.)
        const subOddsFields = [
            { param: 'minOddsH', id: 'min-odds-h' },
            { param: 'maxOddsH', id: 'max-odds-h' },
            { param: 'minOddsD', id: 'min-odds-d' },
            { param: 'maxOddsD', id: 'max-odds-d' },
            { param: 'minOddsA', id: 'min-odds-a' },
            { param: 'maxOddsA', id: 'max-odds-a' },
            { param: 'minOddsOver25', id: 'min-odds-over25' },
            { param: 'maxOddsOver25', id: 'max-odds-over25' },
            { param: 'minOddsUnder25', id: 'min-odds-under25' },
            { param: 'maxOddsUnder25', id: 'max-odds-under25' }
        ];
        subOddsFields.forEach(f => {
            const el = document.getElementById(f.id);
            if (el) {
                el.value = (params[f.param] !== undefined && params[f.param] !== null) ? params[f.param] : '';
            }
        });

        // Run backtest
        showToast("Carregando estratégia...", "info");

        setTimeout(() => {
            runBacktest(params);
        }, 100);

    } catch (err) {
        console.error("Erro ao preencher parâmetros da estratégia:", err);
        showToast("Erro ao carregar parâmetros da estratégia: " + err.message, "error");
    }
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
            showToast("Por favor, selecione pelo menos uma liga para o Radar de Smart Money.", "warning");
            return;
        }

        if (window.currentDataSource === 'futpython') {
            showToast("Backtest de Queda de Odds: requer dados históricos (Football-Data). Use 'Radar Ao Vivo' com FutPython.", "warning");
            return;
        }
        
        tableContainer.innerHTML = '';
        overlay.style.display = 'block';
    } catch (e) {
        showToast("Erro: " + e.message, "error");
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
                futpython_api_key: window.futpythonApiKey,
                detectionMode: 'model_edge'
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
                    ${(r.n_model_edge > 0 || r.n_odds_movement > 0) ? `
                    <span style="display: block; margin-top: 3px; font-size: 9px; color: var(--text-muted);">
                        ${r.n_odds_movement > 0 ? `<span style="color: #34d399; font-weight: 600;" title="Steam Moves reais (odds temporal)"><i class="fa-solid fa-bolt"></i> ${r.n_odds_movement} real</span>` : ''}
                        ${r.n_model_edge > 0 && r.n_odds_movement > 0 ? ' | ' : ''}
                        ${r.n_model_edge > 0 ? `<span title="Value bets do modelo (edge vs bookmaker)"><i class="fa-solid fa-calculator"></i> ${r.n_model_edge} value</span>` : ''}
                    </span>` : ''}
                </td>
                <td style="font-family: var(--font-mono); color: var(--text-primary);">
                    ${r.total_bets}
                </td>
                <td style="font-family: var(--font-mono); font-weight: bold; color: ${r.avg_drop >= 0 ? '#34d399' : '#f87171'};">
                    ${r.avg_drop >= 0 ? '+' : ''}${r.avg_drop.toFixed(1)}% <span style="font-size: 14px; margin-left: 2px;">${r.avg_drop >= 0 ? '&uarr;' : '&darr;'}</span>
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
    
        if (results && results.length > 0) {
        const backtestCache = {};
        results.forEach(r => {
            backtestCache[r.code] = {
                roi: r.roi,
                winRate: r.win_rate,
                totalBets: r.total_bets,
                netProfit: r.net_profit
            };
        });
        localStorage.setItem('radar_backtest_cache', JSON.stringify(backtestCache));
        if (typeof window.updateCacheStatus === 'function') window.updateCacheStatus();
    }
    container.innerHTML = html;
}

// ============================================

// Window bindings for HTML onclick handlers
window.runSteamScan = runSteamScan;
window.clearSteamScan = clearSteamScan;
window.openSaveStrategyModal = openSaveStrategyModal;
window.closeSaveStrategyModal = closeSaveStrategyModal;
window.submitSaveStrategy = submitSaveStrategy;
window.loadHistoryTab = loadHistoryTab;
window.applyHistoryFilters = applyHistoryFilters;
window.renderHistoryGrid = renderHistoryGrid;
window.deleteHistoryStrategy = deleteHistoryStrategy;

