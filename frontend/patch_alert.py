with open('app.js', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    'alert("Erro na requisição. Verifique os logs.");',
    'alert("Erro JS: " + err.message + "\\nStack: " + err.stack);'
)

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(text)

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()
html = html.replace('app.js?v=11', 'app.js?v=12')
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)
