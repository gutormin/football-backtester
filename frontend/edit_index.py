import codecs
import re

with codecs.open('index.html', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''        <div class="scanner-header-wrapper">
            <div class="scanner-title">
                <h3><i class="fa-solid fa-satellite-dish text-glow" style="color: var(--warning);"></i> Radar Smart Money (Dropping Odds)</h3>
                <p>Detecte movimentações violentas de dinheiro institucional e acompanhe o fluxo contra ou a favor do mercado.</p>
            </div>'''

replacement = '''        <div class="scanner-header-wrapper">
            <div class="scanner-title">
                <h3><i class="fa-solid fa-satellite-dish text-glow" style="color: var(--warning);"></i> Radar Smart Money (Dropping Odds)</h3>
                <p>Detecte movimentações violentas de dinheiro institucional e acompanhe o fluxo contra ou a favor do mercado.</p>
            </div>
            
            <div class="steam-mode-toggle" style="display: flex; gap: 10px; margin-bottom: 10px; margin-top: 10px;">
                <button id="btn-mode-lab" class="action-button active" onclick="toggleSteamMode('lab')" style="padding: 8px 15px; font-size: 13px;">
                    <i class="fa-solid fa-flask"></i> Modo Laboratório (Backtest)
                </button>
                <button id="btn-mode-live" class="action-button" onclick="toggleSteamMode('live')" style="padding: 8px 15px; font-size: 13px; background: rgba(var(--warning-rgb), 0.1); color: var(--warning); border: 1px solid rgba(var(--warning-rgb), 0.3);">
                    <i class="fa-solid fa-broadcast-tower"></i> Radar Ao Vivo
                </button>
            </div>'''

content = content.replace(target, replacement)

target2 = '''    <div id="steam-table-container" style="margin-top: 20px;"></div>'''

replacement2 = '''    <div id="steam-table-container" style="margin-top: 20px;"></div>
    <div id="steam-live-table-container" style="margin-top: 20px; display: none;">
        <table class="data-table" id="steam-live-table">
            <thead>
                <tr>
                    <th>JOGO / DATA</th>
                    <th>CASA</th>
                    <th>MERCADO</th>
                    <th>ABERTURA</th>
                    <th>ATUAL</th>
                    <th>QUEDA</th>
                </tr>
            </thead>
            <tbody>
                <!-- Populated dynamically -->
            </tbody>
        </table>
    </div>'''

content = content.replace(target2, replacement2)

with codecs.open('index.html', 'w', encoding='utf-8') as f:
    f.write(content)
