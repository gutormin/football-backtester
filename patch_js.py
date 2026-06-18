import re

with open('frontend/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

old_code = '''        // Filter upcoming matches by selected leagues ALWAYS, regardless of source

        let filteredData = data.filter(match => selectedLeagues.includes(match.league_code));'''

new_code = '''        // Filter upcoming matches by selected leagues ONLY if in manual mode
        let filteredData = data;
        if (opMode !== 'autopilot') {
            const currentSelectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked')).map(cb => cb.value);
            filteredData = data.filter(match => currentSelectedLeagues.includes(match.league_code));
        }'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open('frontend/app.js', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed selectedLeagues scope bug')
else:
    print('Could not find the target codeblock block')
