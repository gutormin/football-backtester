import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the old script completely
content = re.sub(r'<script>\s*document\.addEventListener\(\'DOMContentLoaded\'.*?</script>', '', content, flags=re.DOTALL)

robust_script = """<script>
// Use Event Delegation so we don't depend on DOMContentLoaded timing or element recreation
document.addEventListener('click', (e) => {
    if (e.target.matches('.multiselect-optgroup')) {
        let nextEl = e.target.nextElementSibling;
        let checkboxes = [];
        while(nextEl && nextEl.classList.contains('multiselect-option-item')) {
            const cb = nextEl.querySelector('input[type="checkbox"]');
            if(cb) checkboxes.push(cb);
            nextEl = nextEl.nextElementSibling;
        }
        if(checkboxes.length > 0) {
            const allChecked = checkboxes.every(cb => cb.checked);
            checkboxes.forEach(cb => { cb.checked = !allChecked; });
            if(typeof onMarketSelectionChange === 'function') onMarketSelectionChange();
        }
    }
});

// Add hover effect via CSS injection
const style = document.createElement('style');
style.innerHTML = '.multiselect-optgroup { cursor: pointer; transition: color 0.2s; } .multiselect-optgroup:hover { color: #8b5cf6; }';
document.head.appendChild(style);
</script>
</body>"""

# Ensure we aren't adding it multiple times
if 'cursor: pointer; transition: color 0.2s;' not in content:
    content = content.replace('</body>', robust_script)

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated index.html with robust event delegation script and CSS')
