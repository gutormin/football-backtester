with open('index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, l in enumerate(lines):
    if 'id="tab-scanner"' in l or 'class="tab-pane"' in l or 'class="tab-pane active"' in l:
        print(f"{i+1}: {l.strip()}")
