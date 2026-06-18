import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

script = """<script>
window.toggleGroup = function(groupEl) {
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
        
        // Visual feedback that it ran!
        groupEl.style.color = '#10b981'; // Green
        setTimeout(() => { groupEl.style.color = ''; }, 500);
    }
};
</script>
</body>"""

# Ensure we don't have multiple
content = re.sub(r'<script>\s*window\.toggleGroup = function\(groupEl\).*?</script>\s*</body>', '</body>', content, flags=re.DOTALL)

content = content.replace('</body>', script)

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Injected toggleGroup directly into index.html')
