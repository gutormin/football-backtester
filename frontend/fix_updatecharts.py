with open('app.js', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix updateCharts signature
text = text.replace(
    'function updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueData, monthlyData, oddsData, optimizedData)',
    'function updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueStats, monthlyStats, oddsStats, optimizedData)'
)

# Fix runBacktest assignments and call
text = text.replace(
    'const leagueData = data.league_stats || {};',
    'const leagueStats = data.league_stats || [];'
)
text = text.replace(
    'const monthlyData = data.monthly_stats || {};',
    'const monthlyStats = data.monthly_stats || [];'
)
text = text.replace(
    'const oddsData = data.odds_stats || {};',
    'const oddsStats = data.odds_stats || [];'
)
text = text.replace(
    'updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueData, monthlyData, oddsData, optimizedData);',
    'updateCharts(dates, bankrolls, fixedData, propData, kellyData, leagueStats, monthlyStats, oddsStats, optimizedData);'
)

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(text)

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()
html = html.replace('app.js?v=13', 'app.js?v=14')
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)
