import os

target_file = r"backend\app.py"

with open(target_file, 'r', encoding='utf-8') as f:
    content = f.read()

# I will find the mount line
mount_line = 'app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")'

# I will find the block I need to move. It starts after mount_line down to `if __name__ == "__main__":`
if mount_line in content:
    parts = content.split(mount_line)
    top_part = parts[0]
    bottom_part = parts[1]
    
    # Split bottom_part at if __name__ == "__main__":
    if 'if __name__ == "__main__":' in bottom_part:
        bottom_parts = bottom_part.split('if __name__ == "__main__":')
        code_to_move = bottom_parts[0].strip()
        main_block = 'if __name__ == "__main__":' + bottom_parts[1]
        
        # Now reassemble: top_part + code_to_move + mount_line + main_block
        new_content = top_part + "\n" + code_to_move + "\n\n" + mount_line + "\n\n" + main_block
        
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Patched app.py to fix route shadowing.")
    else:
        print("Could not find main block.")
else:
    print("Could not find mount line.")
