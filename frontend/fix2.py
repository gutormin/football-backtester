with open('index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

insertion = '''            </div>

<!-- Tab: Radar Smart Money -->
<div class="tab-pane" id="tab-radar" style="display: none;">
    <div class="scanner-card" style="margin-bottom: 20px;">
        <div class="scanner-header-wrapper">
            <div class="scanner-title">
                <h3><i class="fa-solid fa-satellite-dish text-glow" style="color: var(--warning);"></i> Radar Smart Money (Dropping Odds)</h3>
                <p>Detecte movimentações violentas de dinheiro institucional e acompanhe o fluxo contra ou a favor do mercado.</p>
            </div>
            
            <div class="steam-mode-toggle" style="display: flex; gap: 10px; margin-bottom: 10px; margin-top: 10px; align-items: center; width: 100%;">
                <button id="btn-mode-lab" class="action-button active" onclick="toggleSteamMode('lab')" style="padding: 8px 15px; font-size: 13px; background: rgba(var(--primary-rgb), 0.2); color: var(--primary); border: 1px solid rgba(var(--primary-rgb), 0.4);">
                    <i class="fa-solid fa-flask"></i> Modo Laboratório (Backtest)
                </button>
                <button id="btn-mode-live" class="action-button" onclick="toggleSteamMode('live')" style="padding: 8px 15px; font-size: 13px; background: transparent; color: var(--text-secondary); border: 1px solid transparent;">
                    <i class="fa-solid fa-broadcast-tower"></i> Radar Ao Vivo
                </button>
            </div>

            <div class="scanner-buttons" style="display: flex; flex-wrap: wrap; gap: 10px;">
                <button id="btn-scan-steam" class="action-button active" onclick="runSteamScan()">
                    <i class="fa-solid fa-flask"></i> Executar Backtest
                </button>
'''

lines.insert(367, insertion)

with open('index.html', 'w', encoding='utf-8') as f:
    f.writelines(lines)
