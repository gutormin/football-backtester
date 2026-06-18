import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

script = """<script>
document.addEventListener('DOMContentLoaded', () => {
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
                checkboxes.forEach(cb => { cb.checked = !allChecked; });
                if(typeof onMarketSelectionChange === 'function') onMarketSelectionChange();
            }
        });
    });
});
</script>
</body>"""

if '<script>' not in script:
    print("Script invalid")

if '</body>' in content and 'Clique para marcar/desmarcar' not in content:
    content = content.replace('</body>', script)
    with open('frontend/index.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Patched index.html with inline script')
else:
    print('Could not find target or already patched')
