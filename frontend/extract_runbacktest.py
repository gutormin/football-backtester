import json
import re

log_path = r"C:\Users\Gustavo\.gemini\antigravity\brain\4173b0ce-7ff7-472b-a85f-254991361a62\.system_generated\logs\transcript_full.jsonl"

with open(log_path, 'r', encoding='utf-8') as f:
    content = f.read()
    
    matches = re.finditer(r'(async function runBacktest\(\).*?})\s*(?:\n|\\n)*?async function', content, re.DOTALL)
    for match in matches:
        text = match.group(1)
        if len(text) > 500:
            text = text.replace('\\n', '\n').replace('\\"', '"')
            with open('restored_runBacktest.js', 'w', encoding='utf-8') as out:
                out.write(text)
            print('Extracted successfully!')
            break
