import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

foolproof_script = """<script>
document.addEventListener('click', (e) => {
    if (e.target.matches('.multiselect-optgroup')) {
        let checkboxes = [];
        // Start from the clicked element and go forward
        let el = e.target.nextElementSibling;
        while (el && !el.classList.contains('multiselect-optgroup')) {
            if (el.tagName === 'LABEL' || el.classList.contains('multiselect-option-item')) {
                const cb = el.querySelector('input[type="checkbox"]');
                if (cb) checkboxes.push(cb);
            }
            el = el.nextElementSibling;
        }
        
        if (checkboxes.length > 0) {
            const allChecked = checkboxes.every(cb => cb.checked);
            checkboxes.forEach(cb => { 
                cb.checked = !allChecked; 
            });
            if(typeof onMarketSelectionChange === 'function') {
                onMarketSelectionChange();
            }
        }
    }
});
const style = document.createElement('style');
style.innerHTML = '.multiselect-optgroup { cursor: pointer; transition: color 0.2s; user-select: none; } .multiselect-optgroup:hover { color: #8b5cf6; }';
document.head.appendChild(style);
</script>
</body>"""

# Strip out old versions
content = re.sub(r'<script>.*?</script>\s*</body>', '</body>', content, flags=re.DOTALL)

# Inject new
content = content.replace('</body>', foolproof_script)

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated index.html with foolproof traversal logic')
