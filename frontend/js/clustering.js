// Auto-extracted from app.js — Clustering engine and AI config
import { showToast, switchTab, formatCurrency, formatPct } from './utils.js';
import { fetchServerHistory, saveToServer, deleteFromServer, toggleServerActiveState, API_BASE_URL } from './api.js';

let clusterChartInstance = null;
window.clusterChartInstance = clusterChartInstance;

function resolveLeagueName(code) {
    const leagues = window.AVAILABLE_LEAGUES || [];
    const found = leagues.find(l => l.code === code);
    if (found) return found.name;
    // Fallback: format pais/liga codes nicely
    if (code.includes('/')) {
        const parts = code.split('/');
        return parts.map(p => p.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())).join(' — ');
    }
    return code;
}

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
                league: resolveLeagueName(p.league),
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

        const leaguesList = c.leagues.map(l => `<span style="display:inline-block; background:rgba(255,255,255,0.05); padding:2px 6px; border-radius:4px; margin:2px; font-size:11px;">${resolveLeagueName(l)}</span>`).join('');
        
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

window.renderLaboratoryPanels = function(data, isPortfolio = false) {
    const summary = data.summary || {};
    if(document.getElementById('metric-sharpe')) document.getElementById('metric-sharpe').innerText = (summary.sharpe_ratio || 0).toFixed(2);
    if(document.getElementById('metric-sortino')) document.getElementById('metric-sortino').innerText = (summary.sortino_ratio || 0).toFixed(2);
    if(document.getElementById('metric-skewness')) document.getElementById('metric-skewness').innerText = (summary.skewness || 0).toFixed(2);
    if(document.getElementById('metric-consec-wins')) document.getElementById('metric-consec-wins').innerText = summary.max_consec_wins || 0;
    if(document.getElementById('metric-consec-losses')) document.getElementById('metric-consec-losses').innerText = summary.max_consec_losses || 0;
    if(document.getElementById('metric-clv')) document.getElementById('metric-clv').innerText = summary.avg_clv != null ? ((summary.avg_clv >= 0 ? '+' : '') + summary.avg_clv.toFixed(1) + '%') : 'N/A';
    if(document.getElementById('metric-bcl')) document.getElementById('metric-bcl').innerText = summary.bcl_percent != null ? (summary.bcl_percent.toFixed(1) + '%') : 'N/A';

    if (typeof displayAiAnalysis === 'function') {
        displayAiAnalysis(data.ai_analysis, data, isPortfolio);
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

    if (typeof renderDriftValidation === 'function') {
        renderDriftValidation(data.ai_analysis, data);
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



async function testClusterAlerts() {
    const btn = document.getElementById('btn-test-cluster-alerts');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Enviando...'; }

    try {
        const res = await fetch(`${API_BASE_URL}/api/telegram/cluster_ai_test`, { method: 'POST' });
        const data = await res.json();

        if (data.status === 'success' || data.status === 'partial') {
            const d = data.diagnostics || {};
            const parts = [
                `Ligas analisadas: ${d.leagues_with_features || 0}`,
                `Clusters: ${d.clusters || 0}`,
                `DNA Shifts: ${d.dna_shifts || 0}`,
                `Pure Blood: ${d.pure_blood || 0}`,
                `Contrarian: ${d.contrarian || 0}`,
                `Autopilot matches: ${d.autopilot_matches || 0}`,
                `Erros: ${(d.errors || []).length}`,
            ];
            showToast(`Cluster AI: ${parts.join(' | ')}`, data.status === 'success' ? 'success' : 'warning');
            if (d.errors && d.errors.length > 0) {
                console.warn('Cluster AI errors:', d.errors);
            }
        } else {
            showToast(data.message || 'Erro ao testar alertas', 'error');
        }
    } catch (e) {
        console.error(e);
        showToast('Erro ao conectar com o servidor', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-brands fa-telegram"></i> Testar Alertas Telegram'; }
    }
}

// Window bindings for HTML onclick handlers
window.runClustering = runClustering;
window.testClusterAlerts = testClusterAlerts;
window.renderClusterChart = renderClusterChart;
window.renderClusterList = renderClusterList;
window.copyClusterLeagues = copyClusterLeagues;
window.loadClusterAiConfig = loadClusterAiConfig;
window.saveClusterAiConfig = saveClusterAiConfig;
