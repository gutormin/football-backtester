import re

with open('backend/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the block starting with if __name__ == "__main__":
match = re.search(r'if __name__ == "__main__":[\s\S]*', content)
if match:
    main_block = match.group(0)
    
    # Check if @app.get('/api/autopilot') is inside the main block
    autopilot_idx = main_block.find("@app.get('/api/autopilot')")
    if autopilot_idx != -1:
        autopilot_code = main_block[autopilot_idx:]
        clean_main = main_block[:autopilot_idx].strip()
        
        new_content = content[:match.start()] + autopilot_code + '\n\n' + clean_main + '\n'
        with open('backend/app.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Fixed placement")
    else:
        print("Not found in main block")
else:
    print("Main block not found")
