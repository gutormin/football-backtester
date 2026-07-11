import { API_BASE_URL } from './api.js';

window.runLiveSteamScan = async function() {
    try {
        const tbody = document.querySelector('#steam-live-table tbody');
        const overlay = document.getElementById('steam-loading-overlay');
        
        const leagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
        const markets = Array.from(document.querySelectorAll('#market-checkboxes-container input[type="checkbox"]:checked')).map(cb => cb.value);
        const minDropPct = parseFloat(document.getElementById('val-drop-pct').value || 5.0);
        const profileFilter = document.getElementById('val-drop-profile') ? document.getElementById('val-drop-profile').value : 'all';
        
        if (markets.length === 0) {
            showToast("Por favor, selecione pelo menos um mercado.", "warning");
            return;
        }

        overlay.style.display = 'block';
        document.getElementById('steam-live-table-container').style.display = 'none';
        
        const reqBody = {
            minDropPct: minDropPct,
            markets: markets,
            leagues: leagues,
            profileFilter: profileFilter
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
        
        // Save data to window for re-filtering
        window.lastLiveSteamData = data.scan_results || [];
        
        // Render table
        window.renderLiveSteamTable(window.lastLiveSteamData);
        
    } catch (e) {
        console.error(e);
        document.getElementById('steam-loading-overlay').style.display = 'none';
        document.getElementById('steam-live-table-container').style.display = 'block';
        document.querySelector('#steam-live-table tbody').innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--danger); padding: 20px;">Erro ao buscar dados ao vivo.</td></tr>`;
    }
};

// ─────────────────────────────────────────────────────────────────────────
//  Normalização canônica de mercado (frontend).
//  Reduz qualquer rótulo vindo do backend (HOME, OVER25, OVER 2.5, OVER_2.5,
//  Over 2.5 etc.) ao MESMO código que o Laboratório usa como chave de cache:
//  'home' | 'away' | 'draw' | 'over25' | 'under25'.
//  Isto garante que a chave `${league_code}|${market}` do Radar Ao Vivo bata
//  com a chave gravada pelo backtest, evitando que drops sumam por
//  divergência de string.
// ─────────────────────────────────────────────────────────────────────────
window.canonicalMarketCode = function(market) {
    if (!market) return '';
    // Remove espaços, pontos e underscores e caixa: 'OVER 2.5' -> 'over25'
    let m = String(market).toLowerCase().replace(/[\s._]/g, '');
    if (m === 'home' || m === '1') return 'home';
    if (m === 'away' || m === '2') return 'away';
    if (m === 'draw' || m === 'x') return 'draw';
    if (m === 'over25' || m === 'o25' || m === 'over') return 'over25';
    if (m === 'under25' || m === 'u25' || m === 'under') return 'under25';
    if (m === 'bttsyes' || m === 'am' || m === 'ambasmarcam') return 'btts_yes';
    if (m === 'bttsno') return 'btts_no';
    if (m === 'homednb' || m === 'dnbhome') return 'home_dnb';
    if (m === 'awaydnb' || m === 'dnbaway') return 'away_dnb';
    return m; // fallback: já normalizado sem separadores
};

window.renderLiveSteamTable = function(results) {
    const tbody = document.querySelector('#steam-live-table tbody');
    tbody.innerHTML = '';
    
    if (typeof window.updateCacheStatus === 'function') window.updateCacheStatus();
    if (!results || results.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #6b7280; padding: 20px;">Nenhuma queda significativa detectada nas odds ao vivo neste momento. O robô atualiza a cada 30 minutos.</td></tr>';
        return;
    }
    
    const filterProfitableOnly = document.getElementById('filter-profitable-only') && document.getElementById('filter-profitable-only').checked;
    const backtestCache = JSON.parse(localStorage.getItem('radar_backtest_cache') || '{}');
    
    // Update cache status text
    const cacheCount = Object.keys(backtestCache).length;
    const cacheStatusEl = document.getElementById('live-cache-status');
    if (cacheStatusEl) {
        cacheStatusEl.innerHTML = cacheCount > 0 ? 
            `<span style="color: #34d399; font-weight: bold;"><i class="fa-solid fa-circle-check"></i> Cérebro Conectado:</span> ${cacheCount} nichos em cache.` : 
            `<span style="color: #f59e0b;"><i class="fa-solid fa-circle-exclamation"></i> Laboratório Desconectado:</span> Rode um backtest para ativar filtros.`;
    }

    let renderedCount = 0;
    results.forEach((item, idx) => {
        // Normaliza o mercado para o MESMO código canônico que o Laboratório
        // grava no cache (home/away/draw/over25/under25). O backend live envia
        // norm_market.upper() ('HOME', 'OVER25'...) e o histórico usa minúsculas;
        // esta função reduz todas as variações a um único código estável.
        const marketCode = window.canonicalMarketCode(item.market);

        const cacheKey = `${item.league_code}|${marketCode}`;
        const cacheInfo = backtestCache[cacheKey];
        
        // Apply profitable filter
        if (filterProfitableOnly && (!cacheInfo || cacheInfo.roi <= 0)) {
            return;
        }
        
        renderedCount++;
        
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
                    Score: ${(item.confidence_score || 0).toFixed(0)}%
                </div>
            </div>
        `;

        let indexCell = `<span style="color: var(--text-muted); font-size: 13px; font-weight: bold; margin-right: 12px; font-family: var(--font-mono);">${idx + 1}.</span>`;
        const teams = item.match.split(' vs ');
        const home = teams[0] || 'Desconhecido';
        const away = teams[1] || 'Desconhecido';
        
        // Find league name
        const lFound = window.AVAILABLE_LEAGUES ? window.AVAILABLE_LEAGUES.find(l => l.code === item.league_code) : null;
        const leagueName = lFound ? lFound.name : item.league_code;
        
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
                    <div style="font-size: 11px; color: var(--text-muted); margin-top: 4px; display: flex; align-items: center; gap: 4px; flex-wrap: wrap;">
                        <span style="color: var(--text-secondary); font-weight: 500;">${leagueName}</span>
                        <span style="color: rgba(255,255,255,0.08);">|</span>
                        <i class="fa-regular fa-clock" style="font-size: 10px;"></i> ${item.date}
                        ${item.is_in_play ? `<span class="badge" style="display:inline-flex; align-items:center; font-size:9px; font-weight:800; padding:2px 6px; border-radius:4px; background:rgba(239, 68, 68, 0.15); border:1px solid rgba(239, 68, 68, 0.4); color:#ef4444; gap:3px; margin-left: 2px;"><span style="width:4px; height:4px; border-radius:50%; background:#ef4444; display:inline-block; animation: blink 1.2s infinite;"></span>AO VIVO ${item.elapsed_minutes}'</span>` : ''}
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
        
        // Build ROI Badge HTML
        let roiBadgeHTML = '';
        if (cacheInfo) {
            const roiColor = cacheInfo.roi > 0 ? '#10b981' : '#ef4444';
            const roiBg = cacheInfo.roi > 0 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.08)';
            const roiBorder = cacheInfo.roi > 0 ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.2)';
            const sign = cacheInfo.roi > 0 ? '+' : '';
            roiBadgeHTML = `<span style="display: inline-flex; align-items: center; font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px; background: ${roiBg}; border: 1px solid ${roiBorder}; color: ${roiColor}; margin-left: 6px;" title="ROI Histórico no Laboratório (${cacheInfo.totalBets} apostas)"><i class="fa-solid fa-chart-line" style="margin-right: 3px;"></i>ROI: ${sign}${cacheInfo.roi.toFixed(1)}%</span>`;
        } else {
            roiBadgeHTML = `<span style="display: inline-flex; align-items: center; font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); color: var(--text-muted); margin-left: 6px;" title="Este nicho não foi testado no Laboratório"><i class="fa-solid fa-circle-question" style="margin-right: 3px;"></i>ROI: --</span>`;
        }
        
        const marketHTML = `<span style="color: #67e8f9; font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">${item.market}</span>${roiBadgeHTML}`;
        const openingHTML = `<span style="color: var(--text-secondary); font-family: var(--font-mono); font-size: 13px;">@${item.opening_odd.toFixed(2)}</span>`;
        const currentHTML = `<span class="radar-odd-badge-current">@${item.current_odd.toFixed(2)}</span>`;
        
        let dropHTML = '';
        if (item.is_in_play) {
            dropHTML = `
                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px;">
                    <span class="radar-drop-pct-red" style="font-size: 13px;" title="Queda Real/Nominal">
                        ${item.drop_pct.toFixed(0)}% <span style="font-size: 13px;">&darr;</span>
                    </span>
                    <span style="font-size: 9px; color: #6ee7b7; font-weight: 700; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.25); padding: 1px 4px; border-radius: 4px;" title="Queda Ajustada (Time Decay)">
                        -${item.adjusted_drop_pct.toFixed(0)}% (Aj.)
                    </span>
                </div>
            `;
        } else {
            dropHTML = `
                <span class="radar-drop-pct-red">
                    ${item.drop_pct.toFixed(0)}% <span style="font-size: 13px;">&darr;</span>
                </span>
            `;
        }

        let profileHTML = '';
        if (item.profile_type === 'Sharps') {
            profileHTML = `<div style="display:flex; align-items:center; gap:4px; font-size:9px; font-weight:800; color:#34d399; background:rgba(52, 211, 153, 0.1); padding:2px 6px; border-radius:4px; text-transform:uppercase;"><i class="fa-solid fa-user-ninja"></i> Sharps (Sindicato)</div>`;
        } else if (item.profile_type === 'Squares') {
            profileHTML = `<div style="display:flex; align-items:center; gap:4px; font-size:9px; font-weight:800; color:#f87171; background:rgba(248, 113, 113, 0.1); padding:2px 6px; border-radius:4px; text-transform:uppercase;"><i class="fa-solid fa-users"></i> Squares (Público)</div>`;
        } else {
            profileHTML = `<div style="display:flex; align-items:center; gap:4px; font-size:9px; font-weight:800; color:#9ca3af; background:rgba(156, 163, 175, 0.1); padding:2px 6px; border-radius:4px; text-transform:uppercase;"><i class="fa-solid fa-user-secret"></i> Desconhecido</div>`;
        }

        const velocity = item.velocity || 0;
        const accelRatio = item.acceleration_ratio || 1;
        let accelText = 'Normal';
        let accelIcon = 'fa-arrow-trend-up';
        let accelColor = '#a78bfa';
        
        if (accelRatio > 2) {
            accelText = 'Ataque Institucional';
            accelIcon = 'fa-meteor';
            accelColor = '#f59e0b';
        } else if (accelRatio < 0.5) {
            accelText = 'Resfriando';
            accelIcon = 'fa-arrow-trend-down';
            accelColor = '#f87171';
        }

        let dynamicsHTML = `
            <div style="margin-top: 5px; display: flex; flex-direction: column; gap: 2px; font-size: 10px; font-weight: 600; text-align: left; padding-left: 2px;">
                <div style="color: var(--text-secondary); display: flex; align-items: center; gap: 4px;">
                    <i class="fa-solid fa-gauge-high" style="color: #67e8f9; width: 12px; font-size: 9px;"></i>
                    <span>Vel: <span style="font-family: monospace; color: #67e8f9;">-${velocity.toFixed(1)}%/h</span></span>
                </div>
                <div style="color: ${accelColor}; display: flex; align-items: center; gap: 4px;" title="Fator de Aceleração: ${accelRatio.toFixed(1)}x (${accelText})">
                    <i class="fa-solid ${accelIcon}" style="width: 12px; font-size: 9px;"></i>
                    <span>Acel: <span style="font-family: monospace;">+${accelRatio.toFixed(1)}x</span></span>
                </div>
            </div>
        `;

        tr.innerHTML = `
            <td>${matchHTML}</td>
            <td>${bookieHTML}</td>
            <td>${marketHTML}</td>
            <td>${openingHTML}</td>
            <td>${currentHTML}</td>
            <td>${dropHTML}</td>
            <td>${confidenceHTML}</td>
            <td>
                <div style="display: flex; flex-direction: column; align-items: flex-start; justify-content: center; gap: 2px;">
                    ${profileHTML}
                    ${dynamicsHTML}
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
    
    if (renderedCount === 0 && results.length > 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #6b7280; padding: 20px;">Nenhum alerta ao vivo possui ROI histórico positivo sob a configuração atual.</td></tr>';
    }
};

let currentSteamMode = 'lab';

window.toggleSteamMode = function(mode) {
    currentSteamMode = mode;
    const btnLab = document.getElementById('btn-mode-lab');
    const btnLive = document.getElementById('btn-mode-live');
    const labTable = document.getElementById('steam-table-container');
    const liveTable = document.getElementById('steam-live-table-container');
    
    const tabDrops = document.getElementById('radar-tab-nav-drops');
    const tabDashboard = document.getElementById('radar-tab-nav-dashboard');

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
        
        if (tabDrops) tabDrops.classList.add('active');
        if (tabDashboard) tabDashboard.classList.remove('active');

        if (labTable) labTable.style.display = 'block';
        if (liveTable) liveTable.style.display = 'none';
        
        const btnScan = document.getElementById('btn-scan-steam');
        if (btnScan) btnScan.innerHTML = '<i class="fa-solid fa-flask"></i> Executar Value Scanner';
    } else {
        if (btnLive) {
            btnLive.classList.add('active');
            btnLive.style.background = 'rgba(56, 189, 248, 0.15)';
            btnLive.style.color = '#38bdf8';
            btnLive.style.border = '1px solid rgba(56, 189, 248, 0.3)';
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

    if (typeof window.updateCacheStatus === 'function') window.updateCacheStatus();
};

window.switchRadarTab = function(mode) {
    window.toggleSteamMode(mode);
};

// Intercept runSteamScan so the lab/live toggle routes to the correct function.
// history.js sets window.runSteamScan after it loads, which may happen AFTER this module.
// Poll until it's available, then wrap it.
(function installInterceptor() {
    if (typeof window.runSteamScan === 'function') {
        const originalRunSteamScan = window.runSteamScan;
        window.runSteamScan = function () {
            if (currentSteamMode === 'live') {
                return window.runLiveSteamScan();
            } else if (typeof originalRunSteamScan === 'function') {
                return originalRunSteamScan();
            }
        };
        return;
    }
    // Not ready yet — poll every 50ms until history.js sets it
    const interval = setInterval(() => {
        if (typeof window.runSteamScan === 'function') {
            clearInterval(interval);
            const originalRunSteamScan = window.runSteamScan;
            window.runSteamScan = function () {
                if (currentSteamMode === 'live') {
                    return window.runLiveSteamScan();
                } else if (typeof originalRunSteamScan === 'function') {
                    return originalRunSteamScan();
                }
            };
        }
    }, 50);
})();

