import codecs
import re

with codecs.open('app.js', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

pattern = r"const bookieName = currentArbData.bookmakers \? currentArbData.bookmakers\[outcome\] : 'Desconhecida';\s*distList\.innerHTML \+= `\s*<div style=\"display: flex; justify-content: space-between; padding: 10px; background: rgba\(255,255,255,0\.05\); border-radius: 6px;\">\s*<div><span style=\"color: #9ca3af\">Seleção:</span> <b>\$\{outcome\}</b>"

replacement = """const bookieName = currentArbData.bookmakers ? currentArbData.bookmakers[outcome] : 'Desconhecida';
        const labelName = (currentArbData.labels && currentArbData.labels[outcome]) ? currentArbData.labels[outcome] : outcome;
        
        distList.innerHTML += `
            <div style="display: flex; justify-content: space-between; padding: 10px; background: rgba(255,255,255,0.05); border-radius: 6px;">
                <div><span style="color: #9ca3af">Seleção:</span> <b>${labelName}</b>"""

if re.search(pattern, content):
    content = re.sub(pattern, replacement, content)
    with codecs.open('app.js', 'w', encoding='utf-8', errors='ignore') as f:
        f.write(content)
    print('Updated app.js recalcArbitrage successfully.')
else:
    print('Target not found in app.js')
