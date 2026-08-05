"""
Multi-League Dutching Backtest & Analysis
==========================================
Runs DutchingBacktester across 20 leagues, saves per-league results,
and generates an interactive HTML dashboard with Plotly.js.

Usage:
    python scripts/run_dutching_analysis.py

Output:
    data/dutching_analysis/<LEAGUE>.json   — per-league raw results
    data/dutching_analysis/results.json    — aggregated results
    data/dutching_analysis/report.html     — interactive dashboard
"""

import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.backtest.dutching_backtester import DutchingBacktester
from backend.probability_pipeline import MODEL_NEGATIVE_BINOMIAL

# ── Configuration ────────────────────────────────────────────────────────

LEAGUES = [
    'USA_MLS', 'JAPAN_J2_LEAGUE', 'BRAZIL_SERIE_A', 'BRAZIL_SERIE_B',
    'JAPAN_J1_LEAGUE', 'ARGENTINA_PRIMERA_DIVISIN', 'CHILE_PRIMERA_DIVISIN',
    'URUGUAY_PRIMERA_DIVISIN', 'NORWAY_ELITESERIEN', 'SWEDEN_ALLSVENSKAN',
    'CHINA_CHINESE_SUPER_LEAGUE', 'SOUTH_KOREA_K_LEAGUE_1',
    'SOUTH_KOREA_K_LEAGUE_2', 'PARAGUAY_DIVISION_PROFESIONAL',
    'AUSTRIA_BUNDESLIGA', 'USA_USL_CHAMPIONSHIP',
]
# NOTE: POLAND_EKSTRAKLASA, ROMANIA_LIGA_I, SERBIA_SUPERLIGA, DENMARK_SUPERLIGA
# are skipped due to Unicode team names causing NumPy dtype errors in
# probability_pipeline.compute_all() (add.reduce dtype incompatibility).

STRATEGIES = ['auto_ia', 'under', 'over', 'draw']
START_DATE = '2023-01-01'
END_DATE = '2025-06-01'
INITIAL_BANKROLL = 10000.0
STAKE_VALUE = 100.0
STAKING_RULE = 'fixed'

OUTPUT_DIR = PROJECT_ROOT / 'data' / 'dutching_analysis'

STRATEGY_LABELS = {
    'auto_ia': 'IA Auto (Perfil)',
    'dynamic': 'Dinâmico (Top Probs)',
    'home_fav': 'Favorito Mandante',
    'away_fav': 'Favorito Visitante',
    'draw': 'Empate',
    'under': 'Under / Jogo Truncado',
    'over': 'Over / Goleada',
}

LEAGUE_NAMES = {
    'USA_MLS': 'MLS (EUA)',
    'JAPAN_J2_LEAGUE': 'J2 League (Japão)',
    'BRAZIL_SERIE_A': 'Brasileirão Série A',
    'BRAZIL_SERIE_B': 'Brasileirão Série B',
    'JAPAN_J1_LEAGUE': 'J1 League (Japão)',
    'ARGENTINA_PRIMERA_DIVISIN': 'Primera División (ARG)',
    'CHILE_PRIMERA_DIVISIN': 'Primera División (CHI)',
    'URUGUAY_PRIMERA_DIVISIN': 'Primera División (URU)',
    'NORWAY_ELITESERIEN': 'Eliteserien (NOR)',
    'SWEDEN_ALLSVENSKAN': 'Allsvenskan (SUE)',
    'CHINA_CHINESE_SUPER_LEAGUE': 'Super League (CHN)',
    'SOUTH_KOREA_K_LEAGUE_1': 'K League 1 (COR)',
    'SOUTH_KOREA_K_LEAGUE_2': 'K League 2 (COR)',
    'POLAND_EKSTRAKLASA': 'Ekstraklasa (POL)',
    'ROMANIA_LIGA_I': 'Liga I (ROM)',
    'SERBIA_SUPERLIGA': 'Superliga (SER)',
    'PARAGUAY_DIVISION_PROFESIONAL': 'División Profesional (PAR)',
    'AUSTRIA_BUNDESLIGA': 'Bundesliga (AUT)',
    'DENMARK_SUPERLIGA': 'Superliga (DIN) [encoding issue - skipped]',
    'USA_USL_CHAMPIONSHIP': 'USL Championship (EUA)',
}


# ── Main ─────────────────────────────────────────────────────────────────

def run_single_league(league_code: str) -> dict | None:
    """Run Dutching backtest for a single league. Returns result dict or None on failure."""
    print(f"\n{'='*60}")
    print(f"  {LEAGUE_NAMES.get(league_code, league_code)} ({league_code})")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        backtester = DutchingBacktester(model_type=MODEL_NEGATIVE_BINOMIAL)
        result = backtester.run(
            leagues=[league_code],
            start_date=START_DATE,
            end_date=END_DATE,
            strategies=STRATEGIES,
            initial_bankroll=INITIAL_BANKROLL,
            stake_value=STAKE_VALUE,
            staking_rule=STAKING_RULE,
            min_edge=0.0,
            max_overround=0.92,
            max_legs=8,
            min_selections=3,
            data_source='auto',
        )
        elapsed = time.time() - t0
    except Exception as e:
        print(f"  [ERRO]: {e}")
        import traceback
        traceback.print_exc()
        return None

    if "error" in result:
        print(f"  [ERRO]: {result['error']}")
        return None

    summary = result.get('summary', {})
    n_bets = summary.get('total_bets', 0)
    roi = summary.get('roi', 0)
    win_rate = summary.get('win_rate', 0)
    profit = summary.get('net_profit', 0)

    print(f"  [OK] {n_bets} apostas | Win Rate: {win_rate}% | ROI: {roi}% | Profit: R${profit:.2f} | {elapsed:.0f}s")

    # Print per-strategy breakdown
    for s in STRATEGIES:
        sb = result.get('strategy_breakdown', {}).get(s, {})
        if sb.get('total_bets', 0) > 0:
            print(f"     {STRATEGY_LABELS.get(s, s):25s}: {sb['total_bets']:4d} bets | "
                  f"Win: {sb['win_rate']}% | ROI: {sb['roi']}% | P&L: R${sb['net_profit']:.2f}")

    return result


def aggregate_results(all_results: dict) -> dict:
    """Aggregate per-league results into a single summary structure for the dashboard."""
    leagues_data = []
    all_bets_flat = []
    equity_by_strategy = {s: [] for s in STRATEGIES}
    quality_buckets = {'0-20': [], '20-40': [], '40-60': [], '60-80': [], '80-100': []}

    total_bets_all = 0
    total_wins_all = 0
    total_profit_all = 0.0
    total_staked_all = 0.0

    for league_code, result in all_results.items():
        summary = result.get('summary', {})
        league_total_bets = summary.get('total_bets', 0)
        league_profit = summary.get('net_profit', 0)

        total_bets_all += league_total_bets
        total_wins_all += summary.get('total_wins', 0)
        total_profit_all += league_profit
        total_staked_all += summary.get('total_staked', 0)

        # Per-strategy for this league
        strategy_stats = {}
        best_strat = None
        best_strat_roi = -999
        worst_strat = None
        worst_strat_roi = 999

        for s in STRATEGIES:
            sb = result.get('strategy_breakdown', {}).get(s, {})
            n = sb.get('total_bets', 0)
            if n > 0:
                strategy_stats[s] = {
                    'bets': n,
                    'win_rate': sb.get('win_rate', 0),
                    'roi': sb.get('roi', 0),
                    'profit': sb.get('net_profit', 0),
                }
                if sb.get('roi', -999) > best_strat_roi:
                    best_strat_roi = sb['roi']
                    best_strat = s
                if sb.get('roi', 999) < worst_strat_roi:
                    worst_strat_roi = sb['roi']
                    worst_strat = s

            # Collect equity curve
            for point in sb.get('equity_curve', []):
                equity_by_strategy[s].append({
                    'league': league_code,
                    'date': point.get('date', ''),
                    'bankroll': point.get('bankroll', 0),
                })

        # League-level aggregate
        max_dd = 0
        sharpe = 0
        for s in STRATEGIES:
            sb = result.get('strategy_breakdown', {}).get(s, {})
            max_dd = max(max_dd, sb.get('max_drawdown', 0))
            if sb.get('sharpe_ratio', 0) != 0:
                sharpe = sb.get('sharpe_ratio', 0)

        leagues_data.append({
            'league_code': league_code,
            'league_name': LEAGUE_NAMES.get(league_code, league_code),
            'total_bets': league_total_bets,
            'win_rate': summary.get('win_rate', 0),
            'roi': summary.get('roi', 0),
            'profit': league_profit,
            'max_drawdown': max_dd,
            'sharpe': sharpe,
            'best_strategy': STRATEGY_LABELS.get(best_strat, best_strat or ''),
            'worst_strategy': STRATEGY_LABELS.get(worst_strat, worst_strat or ''),
            'strategy_stats': strategy_stats,
        })

        # Collect all bets for scatter plots
        for bet in result.get('bets', []):
            bet['league_name'] = LEAGUE_NAMES.get(league_code, league_code)
            all_bets_flat.append(bet)

            # Quality score bucket
            qs = bet.get('quality_score', 0)
            if qs < 20:
                quality_buckets['0-20'].append(bet)
            elif qs < 40:
                quality_buckets['20-40'].append(bet)
            elif qs < 60:
                quality_buckets['40-60'].append(bet)
            elif qs < 80:
                quality_buckets['60-80'].append(bet)
            else:
                quality_buckets['80-100'].append(bet)

    # Quality score analysis
    quality_data = []
    for bucket_label in ['0-20', '20-40', '40-60', '60-80', '80-100']:
        bets_in_bucket = quality_buckets[bucket_label]
        n = len(bets_in_bucket)
        if n > 0:
            wins = sum(1 for b in bets_in_bucket if b.get('won'))
            profit = sum(b.get('profit', 0) for b in bets_in_bucket)
            staked = sum(b.get('total_stake', 0) for b in bets_in_bucket)
            quality_data.append({
                'bucket': bucket_label,
                'bets': n,
                'win_rate': round(wins / n * 100, 1),
                'roi': round(profit / staked * 100, 1) if staked > 0 else 0,
                'profit': round(profit, 1),
            })
        else:
            quality_data.append({
                'bucket': bucket_label,
                'bets': 0,
                'win_rate': 0,
                'roi': 0,
                'profit': 0,
            })

    overall_roi = (total_profit_all / total_staked_all * 100) if total_staked_all > 0 else 0
    overall_win_rate = (total_wins_all / total_bets_all * 100) if total_bets_all > 0 else 0

    # Best overall strategy
    strat_agg = {}
    for s in STRATEGIES:
        s_bets = sum(ld['strategy_stats'].get(s, {}).get('bets', 0) for ld in leagues_data)
        s_profit = sum(ld['strategy_stats'].get(s, {}).get('profit', 0) for ld in leagues_data)
        s_staked = sum(
            ld['strategy_stats'].get(s, {}).get('bets', 0) * STAKE_VALUE
            for ld in leagues_data
        )
        strat_agg[s] = {
            'bets': s_bets,
            'profit': round(s_profit, 1),
            'roi': round(s_profit / s_staked * 100, 1) if s_staked > 0 else 0,
        }

    best_overall = max(strat_agg.items(), key=lambda x: x[1]['roi']) if strat_agg else (None, {'roi': 0})

    return {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'config': {
            'leagues': LEAGUES,
            'strategies': STRATEGIES,
            'start_date': START_DATE,
            'end_date': END_DATE,
            'leagues_completed': len(all_results),
            'leagues_total': len(LEAGUES),
        },
        'overall': {
            'total_bets': total_bets_all,
            'total_wins': total_wins_all,
            'win_rate': round(overall_win_rate, 1),
            'roi': round(overall_roi, 1),
            'net_profit': round(total_profit_all, 1),
            'best_strategy': STRATEGY_LABELS.get(best_overall[0], ''),
            'best_strategy_roi': best_overall[1]['roi'],
        },
        'leagues': sorted(leagues_data, key=lambda x: x['roi'], reverse=True),
        'strategy_aggregate': {s: strat_agg[s] for s in STRATEGIES},
        'quality_analysis': quality_data,
        'all_bets': all_bets_flat,
    }


# ── HTML Generator ────────────────────────────────────────────────────────

def generate_html_report(aggregated: dict, output_path: Path):
    """Generate a standalone interactive HTML dashboard."""
    data_json = json.dumps(aggregated, ensure_ascii=False, default=str)

    html = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dutching Backtest — Análise Multi-Liga</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
.header {{ text-align: center; margin-bottom: 32px; }}
.header h1 {{ font-size: 28px; color: #38bdf8; margin-bottom: 4px; }}
.header p {{ color: #94a3b8; font-size: 14px; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }}
.kpi-card {{ background: #1e293b; border-radius: 12px; padding: 20px; text-align: center; border: 1px solid #334155; }}
.kpi-card .value {{ font-size: 28px; font-weight: 700; margin-bottom: 4px; }}
.kpi-card .label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi-card .value.positive {{ color: #34d399; }}
.kpi-card .value.negative {{ color: #f87171; }}
.kpi-card .value.neutral {{ color: #fbbf24; }}
.section {{ background: #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid #334155; }}
.section h2 {{ font-size: 18px; color: #38bdf8; margin-bottom: 16px; }}
.chart {{ width: 100%; min-height: 400px; }}
.chart-sm {{ width: 100%; min-height: 350px; }}
.chart-lg {{ width: 100%; min-height: 500px; }}
.row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
@media (max-width: 900px) {{ .row {{ grid-template-columns: 1fr; }} }}
.footer {{ text-align: center; margin-top: 32px; color: #64748b; font-size: 12px; }}
</style>
</head>
<body>

<div class="header">
  <h1>⚽ Dutching Backtest — Análise Multi-Liga</h1>
  <p>Gerado em {aggregated['generated_at']} • {aggregated['config']['leagues_completed']}/{aggregated['config']['leagues_total']} ligas • {aggregated['config']['start_date']} a {aggregated['config']['end_date']}</p>
</div>

<div class="kpi-grid" id="kpi-cards"></div>

<div class="section"><h2>📊 Performance por Liga</h2><div id="chart-league-table" class="chart"></div></div>

<div class="row">
  <div class="section"><h2>📈 Performance por Estratégia</h2><div id="chart-strategy-bars" class="chart-sm"></div></div>
  <div class="section"><h2>🔥 ROI Heatmap: Liga × Estratégia</h2><div id="chart-heatmap" class="chart-sm"></div></div>
</div>

<div class="section"><h2>🎯 Edge Calibration (Previsto vs Realizado)</h2><div id="chart-edge-cal" class="chart-lg"></div></div>

<div class="section"><h2>⭐ Quality Score Analysis</h2><div id="chart-quality" class="chart-sm"></div></div>

<div class="section"><h2>💰 Equity Curves Agregadas</h2><div id="chart-equity" class="chart-lg"></div></div>

<div class="section"><h2>🏆 Top 20 Melhores Apostas</h2><div id="chart-top-bets" class="chart"></div></div>

<div class="footer">Dutching Backtester &bull; {len(aggregated['config']['strategies'])} estrategias &bull; Staking: Fixo R${STAKE_VALUE:.0f}</div>

<script>
const DATA = {data_json};

// ── KPI Cards ──
(function() {{
  const ov = DATA.overall;
  const cards = [
    {{ value: ov.total_bets, label: 'Total de Apostas', cls: 'neutral' }},
    {{ value: ov.win_rate + '%', label: 'Win Rate', cls: 'neutral' }},
    {{ value: (ov.roi >= 0 ? '+' : '') + ov.roi + '%', label: 'ROI Médio', cls: ov.roi >= 0 ? 'positive' : 'negative' }},
    {{ value: 'R$' + ov.net_profit.toLocaleString(), label: 'Profit Total', cls: ov.net_profit >= 0 ? 'positive' : 'negative' }},
    {{ value: DATA.config.leagues_completed, label: 'Ligas Analisadas', cls: 'neutral' }},
    {{ value: ov.best_strategy, label: 'Melhor Estratégia', cls: 'positive' }},
  ];
  document.getElementById('kpi-cards').innerHTML = cards.map(c =>
    `<div class="kpi-card"><div class="value ${{c.cls}}">${{c.value}}</div><div class="label">${{c.label}}</div></div>`
  ).join('');
}})();

// ── League Table ──
(function() {{
  const leagues = DATA.leagues;
  const header = ['Liga','Apostas','Win Rate','ROI %','Profit','Max DD %','Sharpe','Melhor Estratégia'];
  const cells = [
    leagues.map(l => l.league_name),
    leagues.map(l => l.total_bets),
    leagues.map(l => l.win_rate),
    leagues.map(l => l.roi),
    leagues.map(l => l.profit),
    leagues.map(l => l.max_drawdown),
    leagues.map(l => l.sharpe),
    leagues.map(l => l.best_strategy),
  ];
  const colors = leagues.map(l => l.roi >= 0 ? '#34d399' : '#f87171');

  Plotly.newPlot('chart-league-table', [{{
    type: 'table',
    header: {{ values: header, font: {{ color: '#e2e8f0', size: 12 }}, fill: {{ color: '#334155' }}, align: 'center' }},
    cells: {{ values: cells, font: {{ color: [colors, null, null, colors, colors, null, null, null], size: 12 }},
      fill: {{ color: ['#1e293b', '#1e293b', '#1e293b', '#1e293b', '#1e293b', '#1e293b', '#1e293b', '#1e293b'] }},
      align: ['left','center','center','center','center','center','center','left'],
      format: [null, null, null, null, [',.0f'], [',.1f'], [',.2f'], null],
    }}
  }}], {{
    margin: {{ t: 0, b: 0, l: 0, r: 0 }},
    paper_bgcolor: '#1e293b',
  }});
}})();

// ── Strategy Bars ──
(function() {{
  const strats = {json.dumps(STRATEGIES)};
  const labels = strats.map(s => {json.dumps(STRATEGY_LABELS)}[s] || s);
  const agg = DATA.strategy_aggregate;
  const roiVals = strats.map(s => agg[s] ? agg[s].roi : 0);
  const wrVals = strats.map(s => agg[s] ? (agg[s].bets > 0 ? Math.round(agg[s].profit > 0 ? 25 : 15) : 0) : 0);

  const trace1 = {{
    x: labels, y: roiVals, type: 'bar', name: 'ROI %',
    marker: {{ color: roiVals.map(v => v >= 0 ? '#34d399' : '#f87171') }},
    text: roiVals.map(v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%'),
    textposition: 'outside', textfont: {{ color: '#e2e8f0' }},
  }};

  Plotly.newPlot('chart-strategy-bars', [trace1], {{
    margin: {{ t: 10, b: 80, l: 50, r: 20 }},
    paper_bgcolor: '#1e293b', plot_bgcolor: '#1e293b',
    font: {{ color: '#94a3b8' }},
    xaxis: {{ tickangle: -25 }},
    yaxis: {{ title: 'ROI %', gridcolor: '#334155', zerolinecolor: '#475569' }},
    showlegend: false,
  }});
}})();

// ── Heatmap ──
(function() {{
  const strats = {json.dumps(STRATEGIES)};
  const stratLabels = strats.map(s => {json.dumps(STRATEGY_LABELS)}[s] || s);
  const leagues = DATA.leagues.map(l => l.league_name);
  const zData = [];
  const textData = [];
  for (let i = 0; i < strats.length; i++) {{
    zData.push(DATA.leagues.map(l => {{
      const ss = l.strategy_stats[strats[i]];
      return ss ? ss.roi : null;
    }}));
    textData.push(DATA.leagues.map(l => {{
      const ss = l.strategy_stats[strats[i]];
      return ss ? (ss.roi >= 0 ? '+' : '') + ss.roi.toFixed(1) + '% (' + ss.bets + ' bets)' : 'N/A';
    }}));
  }}

  Plotly.newPlot('chart-heatmap', [{{
    type: 'heatmap',
    z: zData, x: leagues, y: stratLabels,
    text: textData, hoverinfo: 'text',
    colorscale: [[0, '#f87171'], [0.5, '#1e293b'], [1, '#34d399']],
    zmid: 0, showscale: true,
    colorbar: {{ title: 'ROI %', titlefont: {{ color: '#94a3b8' }}, tickfont: {{ color: '#94a3b8' }} }},
  }}], {{
    margin: {{ t: 10, b: 100, l: 120, r: 30 }},
    paper_bgcolor: '#1e293b', plot_bgcolor: '#1e293b',
    font: {{ color: '#94a3b8', size: 11 }},
    xaxis: {{ tickangle: -45 }},
  }});
}})();

// ── Edge Calibration Scatter ──
(function() {{
  const bets = DATA.all_bets;
  // Group by league for color
  const leagueSet = [...new Set(bets.map(b => b.league_name))];
  const colors = ['#38bdf8','#34d399','#fbbf24','#f87171','#a78bfa','#fb923c','#f472b6','#2dd4bf',
                  '#818cf8','#e879f9','#4ade80','#facc15','#fb7185','#67e8f9','#c084fc'];

  const traces = leagueSet.map((lname, i) => {{
    const lb = bets.filter(b => b.league_name === lname && b.predicted_edge);
    return {{
      x: lb.map(b => b.predicted_edge * 100),
      y: lb.map(b => b.profit / b.total_stake * 100),
      text: lb.map(b => b.home_team + ' vs ' + b.away_team + '<br>' + b.actual_score +
        '<br>Edge: ' + (b.predicted_edge*100).toFixed(2) + '%<br>P&L: R$' + b.profit.toFixed(2)),
      hoverinfo: 'text',
      mode: 'markers', type: 'scatter', name: lname,
      marker: {{ size: 6, opacity: 0.6, color: colors[i % colors.length] }},
    }};
  }});

  // Perfect calibration line
  const maxVal = Math.max(...bets.map(b => Math.abs(b.predicted_edge * 100)), 30);
  traces.push({{
    x: [-maxVal, maxVal], y: [-maxVal, maxVal],
    mode: 'lines', name: 'Calibração Perfeita',
    line: {{ dash: 'dash', color: '#64748b', width: 1 }},
    showlegend: true,
  }});

  Plotly.newPlot('chart-edge-cal', traces, {{
    margin: {{ t: 10, b: 50, l: 60, r: 20 }},
    paper_bgcolor: '#1e293b', plot_bgcolor: '#1e293b',
    font: {{ color: '#94a3b8' }},
    xaxis: {{ title: 'Edge Previsto (%)', gridcolor: '#334155', zerolinecolor: '#475569' }},
    yaxis: {{ title: 'ROI Realizado (%)', gridcolor: '#334155', zerolinecolor: '#475569' }},
    legend: {{ font: {{ size: 10 }}, orientation: 'h', y: 1.15 }},
  }});
}})();

// ── Quality Score Analysis ──
(function() {{
  const qd = DATA.quality_analysis;
  const trace1 = {{
    x: qd.map(d => d.bucket), y: qd.map(d => d.roi),
    type: 'bar', name: 'ROI %',
    marker: {{ color: qd.map(d => d.roi >= 0 ? '#34d399' : '#f87171') }},
    text: qd.map(d => (d.roi >= 0 ? '+' : '') + d.roi.toFixed(1) + '%'),
    textposition: 'outside', textfont: {{ color: '#e2e8f0', size: 12 }},
  }};
  const trace2 = {{
    x: qd.map(d => d.bucket), y: qd.map(d => d.bets),
    type: 'bar', name: '# Apostas', yaxis: 'y2',
    marker: {{ color: '#38bdf8', opacity: 0.5 }},
    text: qd.map(d => d.bets + ' bets'), textposition: 'outside',
    textfont: {{ color: '#94a3b8', size: 11 }},
  }};

  Plotly.newPlot('chart-quality', [trace1, trace2], {{
    margin: {{ t: 10, b: 50, l: 60, r: 60 }},
    paper_bgcolor: '#1e293b', plot_bgcolor: '#1e293b',
    font: {{ color: '#94a3b8' }},
    xaxis: {{ title: 'Quality Score', gridcolor: '#334155' }},
    yaxis: {{ title: 'ROI %', gridcolor: '#334155', zerolinecolor: '#475569' }},
    yaxis2: {{ title: '# Apostas', overlaying: 'y', side: 'right', gridcolor: 'transparent' }},
    legend: {{ orientation: 'h', y: 1.1 }},
    barmode: 'group',
  }});
}})();

// ── Equity Curves (aggregated, normalized) ──
(function() {{
  const strats = {json.dumps(STRATEGIES)};
  const stratLabels = strats.map(s => {json.dumps(STRATEGY_LABELS)}[s] || s);
  const colors = ['#38bdf8','#34d399','#fbbf24','#f87171','#a78bfa','#fb923c','#f472b6'];

  // Build cumulative equity by date across leagues
  const traces = strats.map((s, i) => {{
    const bets = DATA.all_bets.filter(b => b.strategy === s);
    if (!bets.length) return null;
    bets.sort((a,b) => a.date.localeCompare(b.date));

    let cumProfit = 0;
    const dates = [], equity = [];
    for (const b of bets) {{
      cumProfit += b.profit;
      dates.push(b.date);
      equity.push(10000 + cumProfit);
    }}

    return {{
      x: dates, y: equity, type: 'scatter', mode: 'lines',
      name: stratLabels[i],
      line: {{ color: colors[i % colors.length], width: 2 }},
    }};
  }}).filter(Boolean);

  Plotly.newPlot('chart-equity', traces, {{
    margin: {{ t: 10, b: 50, l: 70, r: 20 }},
    paper_bgcolor: '#1e293b', plot_bgcolor: '#1e293b',
    font: {{ color: '#94a3b8' }},
    xaxis: {{ title: 'Data', gridcolor: '#334155' }},
    yaxis: {{ title: 'Banca (R$)', gridcolor: '#334155', zerolinecolor: '#475569' }},
    legend: {{ orientation: 'h', y: 1.1 }},
  }});
}})();

// ── Top 20 Best Bets ──
(function() {{
  const bets = [...DATA.all_bets].sort((a,b) => b.profit - a.profit);
  const top20 = bets.filter(b => b.covered).slice(0, 20);

  const header = ['Data','Liga','Jogo','Placar','Perfil','Odd Média','Edge %','QS','Profit'];
  const cells = [
    top20.map(b => b.date),
    top20.map(b => b.league_name),
    top20.map(b => b.home_team + ' vs ' + b.away_team),
    top20.map(b => b.actual_score),
    top20.map(b => b.game_profile || ''),
    top20.map(b => b.dutching_odd),
    top20.map(b => (b.predicted_edge * 100).toFixed(2) + '%'),
    top20.map(b => b.quality_score),
    top20.map(b => 'R$' + b.profit.toFixed(2)),
  ];

  Plotly.newPlot('chart-top-bets', [{{
    type: 'table',
    header: {{ values: header, font: {{ color: '#e2e8f0', size: 11 }}, fill: {{ color: '#334155' }}, align: 'center' }},
    cells: {{ values: cells,
      font: {{ color: '#34d399', size: 11 }},
      fill: {{ color: '#1e293b' }},
      align: ['center','left','left','center','center','center','center','center','center'],
    }}
  }}], {{
    margin: {{ t: 0, b: 0, l: 0, r: 0 }},
    paper_bgcolor: '#1e293b',
  }});
}})();
</script>
</body>
</html>'''

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding='utf-8')
    print(f"\n[DONE] Dashboard gerado: {output_path}")
    print(f"   Abra no browser: file:///{output_path}")


# ── Entry Point ──────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Dutching Multi-League Backtest & Analysis")
    print("=" * 60)
    print(f"  Ligas: {len(LEAGUES)}")
    print(f"  Estratégias: {len(STRATEGIES)} ({', '.join(STRATEGIES)})")
    print(f"  Período: {START_DATE} a {END_DATE}")
    print(f"  Output: {OUTPUT_DIR}")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_results = {}
    failed = []
    skipped = 0

    for i, league_code in enumerate(LEAGUES):
        print(f"\n[{i+1}/{len(LEAGUES)}] {LEAGUE_NAMES.get(league_code, league_code)}")

        output_file = OUTPUT_DIR / f"{league_code}.json"

        # Resume: skip if already completed
        if output_file.exists():
            try:
                existing = json.loads(output_file.read_text(encoding='utf-8'))
                if existing.get('status') == 'success':
                    all_results[league_code] = existing
                    summary = existing.get('summary', {})
                    print(f"  [SKIP] Ja concluido — {summary.get('total_bets', 0)} apostas, "
                          f"ROI {summary.get('roi', 0)}%")
                    skipped += 1
                    continue
            except Exception:
                print(f"  [WARN] Arquivo corrompido, reexecutando...")

        result = run_single_league(league_code)

        if result is None:
            failed.append(league_code)
            # Save a failed marker so we don't retry forever
            output_file.write_text(json.dumps({"status": "failed", "league": league_code},
                                              ensure_ascii=False), encoding='utf-8')
            continue

        # Save partial result
        output_file.write_text(json.dumps(result, ensure_ascii=False, default=str), encoding='utf-8')
        all_results[league_code] = result

    # ── Aggregate and generate report ──
    print(f"\n{'='*60}")
    print(f"  Agregando resultados...")
    print(f"{'='*60}")

    if not all_results:
        print("[ERRO] Nenhuma liga completada com sucesso!")
        if failed:
            print(f"   Falhas: {', '.join(failed)}")
        return

    aggregated = aggregate_results(all_results)

    # Save aggregated JSON
    agg_path = OUTPUT_DIR / 'results.json'
    agg_path.write_text(json.dumps(aggregated, ensure_ascii=False, default=str), encoding='utf-8')
    print(f"[DATA] Resultados agregados: {agg_path}")

    # Generate HTML report
    report_path = OUTPUT_DIR / 'report.html'
    generate_html_report(aggregated, report_path)

    # ── Final Summary ──
    ov = aggregated['overall']
    print(f"\n{'='*60}")
    print(f"  [RESUMO FINAL]")
    print(f"{'='*60}")
    print(f"  Ligas completadas: {len(all_results)}/{len(LEAGUES)}")
    if failed:
        print(f"  Falhas: {', '.join(failed)}")
    if skipped:
        print(f"  Já estavam prontas (resume): {skipped}")
    print(f"  Total de apostas: {ov['total_bets']}")
    print(f"  Win Rate: {ov['win_rate']}%")
    print(f"  ROI: {ov['roi']}%")
    print(f"  Profit: R${ov['net_profit']:,.2f}")
    print(f"  Melhor estratégia: {ov['best_strategy']} ({ov['best_strategy_roi']}%)")
    print()
    print(f"  [REPORT] Dashboard: {report_path}")
    print(f"  [BROWSER] Abra no browser para visualizar os graficos interativos")


if __name__ == '__main__':
    main()
