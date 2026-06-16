with open('app.js', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('if (proportionalData)', 'if (propData)')
text = text.replace('data: proportionalData,', 'data: propData,')

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(text)

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()
html = html.replace('app.js?v=12', 'app.js?v=13')
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)
