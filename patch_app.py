import re

with open('frontend/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

autopilot_code = '''
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
'''

start_idx = content.find('    const selectedLeagues = Array.from(document.querySelectorAll(\'#leagues-checkbox-list input[type="checkbox"]:checked\')).map(cb => cb.value);')
end_idx = content.find('        const data = await res.json();', start_idx)

if start_idx != -1 and end_idx != -1:
    new_content = content[:start_idx] + autopilot_code + content[end_idx:]
    with open('frontend/app.js', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Patched app.js successfully")
else:
    print("Could not find injection points in app.js")
