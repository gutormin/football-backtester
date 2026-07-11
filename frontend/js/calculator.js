// Auto-extracted from app.js — Pre-match calculator, heatmap, match details
import { showToast, switchTab, formatCurrency, formatPct } from './utils.js';
import { fetchServerHistory, saveToServer, deleteFromServer, toggleServerActiveState, API_BASE_URL } from './api.js';

// Pre-Match Calculator and Match Details Modal Logic [NEW]

// ==========================================================================



async function populateCalculatorLeagues() {

    const select = document.getElementById('calc-league');
    if (!select) return;

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


// Window bindings for HTML onclick handlers
window.populateCalculatorLeagues = populateCalculatorLeagues;
window.onCalculatorLeagueChange = onCalculatorLeagueChange;
window.runRealtimePrediction = runRealtimePrediction;
window.renderHeatmapGrid = renderHeatmapGrid;
window.showMatchDetails = showMatchDetails;
window.closeMatchDetailsModal = closeMatchDetailsModal;
