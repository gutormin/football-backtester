with open('index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, l in enumerate(lines):
    l_strip = l.strip()
    if 'id="tab-history"' in l_strip or 'Estratégias Favoritas' in l_strip:
        print(f"{i+1}: {l_strip}")
