import re

with open('backend/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

autopilot_match = re.search(r"@app\.get\('/api/autopilot'\)[\s\S]*?(?=\n\nif __name__ == \"__main__\":)", content)

if autopilot_match:
    autopilot_code = autopilot_match.group(0)
    
    # Remove the autopilot code from its current place
    content_without_autopilot = content.replace(autopilot_code, '')
    
    # Find where to place it: BEFORE the static mount
    mount_idx = content_without_autopilot.find('app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")')
    if mount_idx != -1:
        # Go backwards to find the start of the `if os.path.exists` block or just place it right before
        # Let's just place it before `if os.path.exists(frontend_dir):`
        if_exists_idx = content_without_autopilot.rfind('if os.path.exists(frontend_dir):', 0, mount_idx)
        
        insert_idx = if_exists_idx if if_exists_idx != -1 else mount_idx
        
        new_content = content_without_autopilot[:insert_idx] + autopilot_code + '\n\n' + content_without_autopilot[insert_idx:]
        
        with open('backend/app.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Moved autopilot BEFORE static mount")
    else:
        print("Could not find static mount")
else:
    print("Could not find autopilot route")
