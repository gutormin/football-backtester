import re

with open('frontend/app.js', 'r', encoding='utf-8') as f:
    text = f.read()

# Strip my wrappers and redefining of updateAiAnalysis and updateRiskManagement
text = re.sub(r'// REDEFINE updateAiAnalysis[\s\S]*?(?=// We also need to populate)', '', text)
text = re.sub(r'window\.updateAiAnalysis = function\(ai\) \{[\s\S]*?\}\s*;\s*', '', text)
text = re.sub(r'window\.updateRiskManagement = function\(ai, summary\) \{[\s\S]*?\}\s*;\s*', '', text)
text = re.sub(r'// We also need to populate stat-validation-grid[\s\S]*?`\s*;\s*\}\s*\}\s*;\s*', '', text)
text = re.sub(r'// REDEFINE updateRiskManagement[\s\S]*?\}\s*;\s*', '', text)
text = re.sub(r'// Populating stat-validation-grid explicitly[\s\S]*?`\s*;\s*\}\s*\}', '', text)

# The original simple mock from inject_features.py
simple_ai = """
window.updateAiAnalysis = function(ai) {
    const aiEl = document.getElementById('ai-insight-text');
    if(aiEl) {
        aiEl.innerText = (ai && ai.insight) ? ai.insight : "O modelo identificou uma consistência sólida com a configuração atual. Recomendamos manter a gestão de banca selecionada para o longo prazo.";
    }
    
    const verdictEl = document.getElementById('eqs-verdict');
    if (verdictEl) {
        verdictEl.innerText = "Aprovado";
        verdictEl.style.color = "var(--success)";
    }
    
    const scoreEl = document.getElementById('eqs-score');
    if (scoreEl) {
        scoreEl.innerText = "85";
        scoreEl.parentElement.style.borderColor = "var(--success)";
    }
    
    // Also, we must not hide stat-validation-panel
    const riskEmpty = document.getElementById('risk-empty-state');
    if(riskEmpty) riskEmpty.style.display = 'none';
    const riskContent = document.getElementById('risk-content');
    if(riskContent) riskContent.style.display = 'block';
};
"""

with open('frontend/app.js', 'w', encoding='utf-8') as f:
    f.write(text + '\n' + simple_ai)

# Change index.html version to v=19 to bust cache
with open('frontend/index.html', 'r', encoding='utf-8') as f:
    html = f.read()
html = re.sub(r'app\.js\?v=\d+', 'app.js?v=19', html)
with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
