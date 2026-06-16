import re

with open('app.js', 'r', encoding='utf-8') as f:
    text = f.read()

# Add the gradient definition
replacement = """const ctxEquity = document.getElementById('equity-chart').getContext('2d');
const gradient = ctxEquity.createLinearGradient(0, 0, 0, 400);
gradient.addColorStop(0, 'rgba(99, 102, 241, 0.4)');
gradient.addColorStop(1, 'rgba(99, 102, 241, 0.0)');"""

text = text.replace(
    "const ctxEquity = document.getElementById('equity-chart').getContext('2d');",
    replacement
)

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(text)

# Also let's update cache buster to v=11
with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

html = html.replace('app.js?v=10', 'app.js?v=11')

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)
