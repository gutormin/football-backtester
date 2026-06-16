with open('index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, l in enumerate(lines):
    l_strip = l.strip()
    if '<main' in l_strip or '</main>' in l_strip or '<aside' in l_strip or '</aside>' in l_strip or 'app-container' in l_strip:
        print(f"{i+1}: {l_strip}")
