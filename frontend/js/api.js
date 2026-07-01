import { showToast } from './utils.js';

export const API_BASE_URL = window.API_BASE_URL || window.location.origin;

export async function checkDatabaseStatus() {
    const badge = document.getElementById('db-status-badge');
    const timeSpan = document.getElementById('db-update-time');
    if (!badge || !timeSpan) return;
    
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

export async function syncDatabase() {
    const btn = document.getElementById('btn-sync-db');
    if (!btn) return;
    btn.classList.add('spinning');
    btn.disabled = true;
    
    const mainSelector = document.getElementById('data-source-select');
    const source = (mainSelector && mainSelector.value === 'futpython') ? 'api' : 'csv';
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

export async function loadLeagues() {
    const listContainer = document.getElementById('leagues-checkbox-list');
    if (!listContainer) return;
    listContainer.innerHTML = '';
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/leagues?source=${window.currentDataSource || 'footballdata'}&t=${Date.now()}`, { cache: 'no-store' });
        if (!res.ok) throw new Error("Failed to load leagues");
        const leagues = await res.json();
        
        window.AVAILABLE_LEAGUES = leagues;
        
        leagues.sort((a, b) => a.name.localeCompare(b.name));
        
        leagues.forEach(league => {
            const item = document.createElement('div');
            item.className = 'league-item';
            
            const checked = ['E0', 'SP1', 'I1', 'D1', 'F1', 'BRA'].includes(league.code) ? 'checked' : '';
            
            item.innerHTML = `<input type="checkbox" id="league-${league.code}" value="${league.code}" ${checked}><label for="league-${league.code}">${league.name}</label>`;
            listContainer.appendChild(item);
        });
    } catch (err) {
        listContainer.innerHTML = '<div class="text-center text-loss">Falha ao carregar as ligas.</div>';
        showToast("Erro ao carregar a lista de ligas do backend.", "error");
    }
}

export async function fetchServerHistory() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/history`);
        if (!res.ok) throw new Error("Failed to load server history");
        return await res.json();
    } catch (err) {
        console.error("Error loading server history:", err);
        return [];
    }
}

export async function saveToServer(payload) {
    const res = await fetch(`${API_BASE_URL}/api/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error("Failed to save item on server");
    return await res.json();
}

export async function deleteFromServer(id) {
    const res = await fetch(`${API_BASE_URL}/api/history/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error("Failed to delete item from server");
    return await res.json();
}

export async function toggleServerActiveState(id) {
    const res = await fetch(`${API_BASE_URL}/api/history/${id}/toggle_active`, { method: 'POST' });
    if (!res.ok) throw new Error("Failed to toggle state on server");
    return await res.json();
}
