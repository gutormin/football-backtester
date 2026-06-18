import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Add onclick to every optgroup
content = re.sub(r'<div class="multiselect-optgroup">', r'<div class="multiselect-optgroup" onclick="toggleGroup(this)">', content)

script = """<script>
function toggleGroup(groupEl) {
    let checkboxes = [];
    let el = groupEl.nextElementSibling;
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
            cb.dispatchEvent(new Event('change', { bubbles: true }));
        });
        if(typeof onMarketSelectionChange === 'function') {
            onMarketSelectionChange();
        }
    }
}
</script>
</body>"""

# Remove old scripts we added
content = re.sub(r'<script>\s*document\.addEventListener\(\'click\'.*?</script>\s*</body>', '</body>', content, flags=re.DOTALL)
content = re.sub(r'<script>\s*function toggleGroup.*?</script>\s*</body>', '</body>', content, flags=re.DOTALL)

content = content.replace('</body>', script)

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated index.html to use direct onclick attributes')
