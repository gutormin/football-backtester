import sys

js_code = """
// --- Steam Moves Radar ---
async function runSteamScan() {
    const tableContainer = document.getElementById('steam-table-container');
    const overlay = document.getElementById('steam-loading-overlay');
    
    // Pegar filtros
    const leagues = getSelectedLeagues();
    const startDate = document.getElementById('date-start').value;
    const endDate = document.getElementById('date-end').value;
    const markets = getSelectedMarkets();
    const minDropPct = parseFloat(document.getElementById('val-drop-pct').value || 5.0);
    const stakeValue = parseFloat(document.getElementById('stake-value').value || 10.0);
    
    if (leagues.length === 0) {
        alert("Por favor, selecione pelo menos uma liga para o Radar de Smart Money.");
        return;
    }
    
    tableContainer.innerHTML = '';
    overlay.style.display = 'block';
    
    try {
        const response = await fetch('/api/scan_steam_moves', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                leagues: leagues,
                startDate: startDate,
                endDate: endDate,
                markets: markets.length > 0 ? markets : ['home', 'away', 'draw'],
                minDropPct: minDropPct,
                stakeValue: stakeValue
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
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
            <thead>
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                    <th style="padding: 12px 15px; text-align: left; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Nicho</th>
                    <th style="padding: 12px 15px; text-align: center; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Apostas Feitas</th>
                    <th style="padding: 12px 15px; text-align: right; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Drop Médio (%)</th>
                    <th style="padding: 12px 15px; text-align: center; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Taxa de Acerto</th>
                    <th style="padding: 12px 15px; text-align: right; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">ROI</th>
                    <th style="padding: 12px 15px; text-align: right; font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Lucro Líquido</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    results.forEach(r => {
        const isProfit = r.net_profit > 0;
        const codeParts = r.code.split('|');
        const leagueName = (window.AVAILABLE_LEAGUES && window.AVAILABLE_LEAGUES.find(l => l.code === codeParts[0])) ? 
            window.AVAILABLE_LEAGUES.find(l => l.code === codeParts[0]).name : codeParts[0];
            
        html += `
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); transition: background-color 0.2s;">
                <td style="padding: 12px 15px; font-weight: 500; font-size: 13px;">
                    <span style="color: var(--text-secondary);">${leagueName}</span>
                    <span style="color: var(--text-muted); margin: 0 5px;"><i class="fa-solid fa-angle-right" style="font-size: 10px;"></i></span>
                    <span style="color: var(--text-primary);">${r.market_name}</span>
                </td>
                <td style="padding: 12px 15px; text-align: center; font-family: var(--font-mono); color: var(--text-primary);">
                    ${r.total_bets}
                </td>
                <td style="padding: 12px 15px; text-align: right; color: var(--info); font-family: var(--font-mono); font-weight: bold;">
                    -${r.avg_drop.toFixed(1)}% <i class="fa-solid fa-arrow-trend-down" style="font-size: 10px; margin-left: 2px;"></i>
                </td>
                <td style="padding: 12px 15px; text-align: center; color: var(--text-secondary);">
                    ${r.win_rate.toFixed(1)}%
                </td>
                <td style="padding: 12px 15px; text-align: right; font-family: var(--font-mono); color: ${isProfit ? 'var(--success)' : 'var(--danger)'};">
                    ${r.roi > 0 ? '+' : ''}${r.roi.toFixed(1)}%
                </td>
                <td style="padding: 12px 15px; text-align: right; font-family: var(--font-mono); color: ${isProfit ? 'var(--success)' : 'var(--danger)'}; font-weight: bold;">
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
"""

with open('frontend/app.js', 'a', encoding='utf-8') as f:
    f.write(js_code)
print('Success writing js')
