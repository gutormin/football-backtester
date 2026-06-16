with open('app.js', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    "const initialBankroll = parseFloat(document.getElementById('bankroll') ? document.getElementById('bankroll').value : 1000.0) || 1000.0;",
    "const initialBankroll = parseFloat(document.getElementById('init-bankroll') ? document.getElementById('init-bankroll').value : 1000.0) || 1000.0;"
)

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(text)
