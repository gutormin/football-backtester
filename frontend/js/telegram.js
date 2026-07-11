// Auto-extracted from app.js — Telegram bot, scheduler, and tips
import { showToast, switchTab, formatCurrency, formatPct } from './utils.js';
import { fetchServerHistory, saveToServer, deleteFromServer, toggleServerActiveState, API_BASE_URL } from './api.js';

// Telegram Config and Upcoming Tips Logic [NEW]

// ==========================================================================



// Global variable to cache loaded upcoming matches for broadcasting

window.currentUpcomingMatches = [];



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

            max_odds: backtestData.maxOdds || 2.50,

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

        max_odds: parseFloat(document.getElementById('max-odds').value) || 2.50,

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
            maxOdds: parseFloat(document.getElementById('max-odds').value) || 2.50,
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

        

        window.currentUpcomingMatches = filteredData;

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

    const tips = window.currentUpcomingMatches.filter(m => m.is_tip);

    

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

        

        window.allTelegramTips = tips; // Cache for Telegram tips log

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

    let filtered = window.allTelegramTips;

    if (statusFilter !== 'Todos') {

        filtered = window.allTelegramTips.filter(tip => tip.status === statusFilter);

    }

    renderTelegramTips(filtered);

}



function exportTipsToCsv() {

    if (window.allTelegramTips.length === 0) {

        showToast("Não há tips no log para exportar.", "info");

        return;

    }

    

    // Construct CSV Header (using semicolon delimiter for better compatibility with PT Excel)

    let csvContent = "\uFEFF"; // Prepend UTF-8 BOM

    csvContent += "Data;Liga;Mandante;Visitante;Mercado;Odds;Stake;Status\r\n";

    

    // Rows

    window.allTelegramTips.forEach(tip => {

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


// Window bindings for HTML onclick handlers
window.toggleMarketDropdown = toggleMarketDropdown;
window.selectAllMarkets = selectAllMarkets;
window.onMarketSelectionChange = onMarketSelectionChange;
window.loadTelegramConfigUi = loadTelegramConfigUi;
window.saveTelegramConfig = saveTelegramConfig;
window.testTelegramConnection = testTelegramConnection;
window.loadSchedulerConfigUi = loadSchedulerConfigUi;
window.autoUpdateSchedulerFromBacktest = autoUpdateSchedulerFromBacktest;
window.saveSchedulerConfigUi = saveSchedulerConfigUi;
window.runSchedulerNow = runSchedulerNow;
window.loadUpcomingMatches = loadUpcomingMatches;
window.renderUpcomingMatches = renderUpcomingMatches;
window.sendIndividualTip = sendIndividualTip;
window.broadcastAllTips = broadcastAllTips;
window.loadTelegramTipsLog = loadTelegramTipsLog;
window.updateTipStatus = updateTipStatus;
window.clearTipsLog = clearTipsLog;
window.renderTelegramTips = renderTelegramTips;
window.filterTipsTable = filterTipsTable;
window.exportTipsToCsv = exportTipsToCsv;
