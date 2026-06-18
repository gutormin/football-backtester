import re

with open('frontend/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

js_to_add = """
    // Select all optgroups in multiselects to make them clickable for mass-toggling
    document.querySelectorAll('.multiselect-optgroup').forEach(optgroup => {
        optgroup.style.cursor = 'pointer';
        optgroup.title = 'Clique para marcar/desmarcar todos';
        optgroup.addEventListener('click', (e) => {
            let nextEl = e.target.nextElementSibling;
            let checkboxes = [];
            while(nextEl && nextEl.classList.contains('multiselect-option-item')) {
                const cb = nextEl.querySelector('input[type="checkbox"]');
                if(cb) checkboxes.push(cb);
                nextEl = nextEl.nextElementSibling;
            }
            
            if(checkboxes.length > 0) {
                const allChecked = checkboxes.every(cb => cb.checked);
                checkboxes.forEach(cb => {
                    cb.checked = !allChecked;
                });
                if(typeof onMarketSelectionChange === 'function') onMarketSelectionChange();
            }
        });
    });
"""

target = "document.addEventListener('DOMContentLoaded', () => {"
if target in content:
    content = content.replace(target, target + js_to_add, 1)
    with open('frontend/app.js', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Added mass-toggle script to app.js')
else:
    print('Could not find target')
