import json
log_path = r"C:\Users\Gustavo\.gemini\antigravity\brain\4173b0ce-7ff7-472b-a85f-254991361a62\.system_generated\logs\transcript_full.jsonl"

found_block = ""
with open(log_path, 'r', encoding='utf-8') as f:
    for line in f:
        if 'window.runBacktest = async function' in line or 'async function runBacktest' in line:
            obj = json.loads(line)
            for tc in obj.get('tool_calls', []):
                args_str = json.dumps(tc['args'])
                idx = args_str.find('async function runBacktest')
                if idx == -1:
                    idx = args_str.find('window.runBacktest = async function')
                if idx != -1:
                    found_block = args_str[idx:idx+15000]
                    break
        if found_block:
            break

if found_block:
    found_block = found_block.replace('\\n', '\n').replace('\\"', '"')
    with open('restored_runBacktest.js', 'w', encoding='utf-8') as out:
        out.write(found_block)
    print("Found and saved!")
else:
    print("Not found.")
