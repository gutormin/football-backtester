// Charts configuration and rendering (Chart.js)

let equityChart = null;
let leagueChart = null;
let monthlyChart = null;
let oddsChart = null;
let portfolioEquityChart = null;

export function updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueStats, monthlyStats, oddsStats, optimizedData) {
    if (equityChart) equityChart.destroy();
    if (leagueChart) leagueChart.destroy();
    if (monthlyChart) monthlyChart.destroy();
    if (oddsChart) oddsChart.destroy();

    const ctxEquity = document.getElementById('equity-chart').getContext('2d');
    const gradient = ctxEquity.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, 'rgba(99, 102, 241, 0.4)');
    gradient.addColorStop(1, 'rgba(99, 102, 241, 0.0)');
    
    const rule = document.getElementById('stake-rule').value;
    const stakeValueInput = rule === 'kelly' ? parseFloat(document.getElementById('kelly-fraction').value) || 0.25 : parseFloat(document.getElementById('stake-value').value) || 10;

    const fixedStakeVal = rule === 'fixed' ? stakeValueInput : 10;
    const propStakePct = rule === 'proportional' ? stakeValueInput : 2;
    let kellyFractionText = rule === 'kelly' ? stakeValueInput.toFixed(2) + (stakeValueInput == 1 ? ' (Full)' : ' (' + (1/stakeValueInput).toFixed(0) + ')') : '1/4';

    const datasets = [{
        label: 'Geral (Selecionado) ($)',
        data: bankrolls,
        borderColor: '#6366f1',
        borderWidth: 2.5,
        fill: true,
        backgroundColor: gradient,
        tension: 0.15,
        pointRadius: dates.length > 200 ? 0 : 2,
        pointHoverRadius: 5
    }];

    if (fixedData) {
        datasets.push({
            label: `Fixed Staking ($${fixedStakeVal})`,
            data: fixedData,
            borderColor: '#f59e0b',
            borderWidth: 1.5,
            borderDash: [4, 4],
            fill: false,
            tension: 0.15,
            pointRadius: dates.length > 200 ? 0 : 1,
            pointHoverRadius: 4
        });
    }

    if (propData) {
        datasets.push({
            label: `Proportional (${propStakePct}%) ($)`,
            data: propData,
            borderColor: '#06b6d4',
            borderWidth: 1.5,
            borderDash: [4, 4],
            fill: false,
            tension: 0.15,
            pointRadius: dates.length > 200 ? 0 : 1,
            pointHoverRadius: 4
        });
    }

    if (kellyData) {
        datasets.push({
            label: `Kelly Staking (${kellyFractionText}) ($)`,
            data: kellyData,
            borderColor: '#ec4899',
            borderWidth: 1.5,
            borderDash: [4, 4],
            fill: false,
            tension: 0.15,
            pointRadius: dates.length > 200 ? 0 : 1,
            pointHoverRadius: 4
        });
    }
    
    if (optimizedData) {
        datasets.push({
            label: 'Banca Otimizada IA ($)',
            data: optimizedData,
            borderColor: '#10b981',
            borderWidth: 2,
            borderDash: [6, 4],
            fill: false,
            tension: 0.15,
            pointRadius: dates.length > 200 ? 0 : 2,
            pointHoverRadius: 5
        });
    }
    
    equityChart = new Chart(ctxEquity, {
        type: 'line',
        data: {
            labels: dates,
            datasets: datasets
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
                        font: { family: 'Outfit', size: 11 },
                        usePointStyle: true,
                        boxWidth: 8
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.02)' },
                    ticks: { color: '#9ca3af', font: { size: 10 }, maxTicksLimit: 12 }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#9ca3af', font: { size: 11 } }
                }
            }
        }
    });

    // 2. League Performance Chart
    const ctxLeague = document.getElementById('league-chart').getContext('2d');
    if (leagueChart) leagueChart.destroy();
    
    leagueStats.sort((a, b) => b.profit - a.profit);
    
    const leagueNames = leagueStats.map(item => item.league || item.name || 'Desconhecida');
    const profits = leagueStats.map(item => item.profit);
    const colors = profits.map(val => val >= 0 ? 'rgba(16, 185, 129, 0.75)' : 'rgba(239, 68, 68, 0.75)');
    const borderColors = profits.map(val => val >= 0 ? '#10b981' : '#ef4444');
    
    leagueChart = new Chart(ctxLeague, {
        type: 'bar',
        data: {
            labels: leagueNames,
            datasets: [{
                label: 'Lucro Líquido ($)',
                data: profits,
                backgroundColor: colors,
                borderColor: borderColors,
                borderWidth: 1.5,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#9ca3af', font: { size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#9ca3af', font: { size: 11 } }
                }
            }
        }
    });

    // 3. Monthly Performance Chart
    const ctxMonthly = document.getElementById('monthly-chart').getContext('2d');
    if (monthlyChart) monthlyChart.destroy();
    
    const months = monthlyStats.map(item => item.month);
    const monthlyProfits = monthlyStats.map(item => item.profit);
    const monthlyColors = monthlyProfits.map(val => val >= 0 ? 'rgba(16, 185, 129, 0.75)' : 'rgba(239, 68, 68, 0.75)');
    const monthlyBorderColors = monthlyProfits.map(val => val >= 0 ? '#10b981' : '#ef4444');
    
    monthlyChart = new Chart(ctxMonthly, {
        type: 'bar',
        data: {
            labels: months,
            datasets: [{
                label: 'Lucro por Mês ($)',
                data: monthlyProfits,
                backgroundColor: monthlyColors,
                borderColor: monthlyBorderColors,
                borderWidth: 1.5,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#9ca3af', font: { size: 10 }, maxTicksLimit: 18 }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#9ca3af', font: { size: 11 } }
                }
            }
        }
    });

    // 4. Odds Range Performance Chart
    const ctxOdds = document.getElementById('odds-chart').getContext('2d');
    if (oddsChart) oddsChart.destroy();
    
    const ranges = oddsStats.map(item => item.odds_band || item.range || item.label || 'N/A');
    const oddsProfits = oddsStats.map(item => item.profit);
    const oddsColors = oddsProfits.map(val => val >= 0 ? 'rgba(16, 185, 129, 0.75)' : 'rgba(239, 68, 68, 0.75)');
    const oddsBorderColors = oddsProfits.map(val => val >= 0 ? '#10b981' : '#ef4444');
    
    oddsChart = new Chart(ctxOdds, {
        type: 'bar',
        data: {
            labels: ranges,
            datasets: [{
                label: 'Lucro por Odds ($)',
                data: oddsProfits,
                backgroundColor: oddsColors,
                borderColor: oddsBorderColors,
                borderWidth: 1.5,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#9ca3af', font: { size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#9ca3af', font: { size: 11 } }
                }
            }
        }
    });
}

export function renderPortfolioChart(equityCurve) {
    const ctx = document.getElementById('portfolio-equity-chart').getContext('2d');
    
    if (portfolioEquityChart) {
        portfolioEquityChart.destroy();
    }
    
    const dates = equityCurve.map(e => e.date);
    const bankrolls = equityCurve.map(e => e.bankroll);
    
    portfolioEquityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                label: 'Banca Total do Portfólio',
                data: bankrolls,
                borderColor: '#8b5cf6',
                backgroundColor: 'rgba(139, 92, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                pointRadius: 0,
                pointHoverRadius: 4,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true, labels: { color: '#e2e8f0' } },
                tooltip: { mode: 'index', intersect: false }
            },
            scales: {
                x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });
}

export function clearCharts() {
    if (equityChart) { equityChart.destroy(); equityChart = null; }
    if (leagueChart) { leagueChart.destroy(); leagueChart = null; }
    if (monthlyChart) { monthlyChart.destroy(); monthlyChart = null; }
    if (oddsChart) { oddsChart.destroy(); oddsChart = null; }
    if (portfolioEquityChart) { portfolioEquityChart.destroy(); portfolioEquityChart = null; }
}
