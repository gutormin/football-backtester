import codecs
import re

content = """

let currentSteamMode = 'lab';

window.toggleSteamMode = function(mode) {
    currentSteamMode = mode;
    const btnLab = document.getElementById('btn-mode-lab');
    const btnLive = document.getElementById('btn-mode-live');
    const labTable = document.getElementById('steam-table-container');
    const liveTable = document.getElementById('steam-live-table-container');
    
    if (mode === 'lab') {
        btnLab.classList.add('active');
        btnLab.style.background = 'rgba(var(--primary-rgb), 0.2)';
        btnLab.style.color = 'var(--primary)';
        btnLab.style.border = '1px solid rgba(var(--primary-rgb), 0.4)';
        
        btnLive.classList.remove('active');
        btnLive.style.background = 'transparent';
        btnLive.style.color = 'var(--text-secondary)';
        btnLive.style.border = '1px solid transparent';
        
        labTable.style.display = 'block';
        liveTable.style.display = 'none';
        document.getElementById('btn-scan-steam').innerHTML = '<i class="fa-solid fa-flask"></i> Executar Backtest';
    } else {
        btnLive.classList.add('active');
        btnLive.style.background = 'rgba(var(--warning-rgb), 0.2)';
        btnLive.style.color = 'var(--warning)';
        btnLive.style.border = '1px solid rgba(var(--warning-rgb), 0.4)';
        
        btnLab.classList.remove('active');
        btnLab.style.background = 'transparent';
        btnLab.style.color = 'var(--text-secondary)';
        btnLab.style.border = '1px solid transparent';
        
        labTable.style.display = 'none';
        liveTable.style.display = 'block';
        document.getElementById('btn-scan-steam').innerHTML = '<i class="fa-solid fa-radar"></i> Rastrear Quedas Ao Vivo';
    }
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
        
        data.scan_results.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <div style="font-weight: bold; color: var(--text-primary);">${item.match}</div>
                    <div style="font-size: 11px; color: var(--text-muted);">${item.date}</div>
                </td>
                <td><span style="background: rgba(255,255,255,0.05); padding: 3px 8px; border-radius: 4px; font-size: 11px;">${item.bookmaker}</span></td>
                <td><span style="color: var(--primary); font-weight: bold;">${item.market}</span></td>
                <td>@${item.opening_odd.toFixed(2)}</td>
                <td style="color: var(--warning); font-weight: bold;">@${item.current_odd.toFixed(2)}</td>
                <td>
                    <div style="display: inline-block; padding: 4px 8px; background: rgba(var(--warning-rgb), 0.1); color: var(--warning); border-radius: 4px; font-weight: bold; font-size: 12px;">
                        <i class="fa-solid fa-arrow-trend-down"></i> -${item.drop_pct}%
                    </div>
                </td>
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
"""

with codecs.open('app.js', 'a', encoding='utf-8') as f:
    f.write(content)
