import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

robust_script = """<script>
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
const style = document.createElement('style');
style.innerHTML = '.multiselect-optgroup { cursor: pointer; transition: color 0.2s; } .multiselect-optgroup:hover { color: #8b5cf6; }';
document.head.appendChild(style);
</script>
</body>"""

# Let's fix it if nextElementSibling fails, by iterating differently.
robust_script2 = """<script>
document.addEventListener('click', (e) => {
    if (e.target.matches('.multiselect-optgroup')) {
        let currentNode = e.target.nextSibling;
        let checkboxes = [];
        
        while(currentNode) {
            if (currentNode.nodeType === 1) { // Element node
                if (currentNode.classList.contains('multiselect-option-item')) {
                    const cb = currentNode.querySelector('input[type="checkbox"]');
                    if(cb) checkboxes.push(cb);
                } else if (currentNode.classList.contains('multiselect-optgroup')) {
                    break; // Stop at next group
                }
            }
            currentNode = currentNode.nextSibling;
        }
        
        if(checkboxes.length > 0) {
            const allChecked = checkboxes.every(cb => cb.checked);
            checkboxes.forEach(cb => { cb.checked = !allChecked; });
            if(typeof onMarketSelectionChange === 'function') onMarketSelectionChange();
        }
    }
});
const style = document.createElement('style');
style.innerHTML = '.multiselect-optgroup { cursor: pointer; transition: color 0.2s; user-select: none; } .multiselect-optgroup:hover { color: #8b5cf6; }';
document.head.appendChild(style);
</script>
</body>"""

content = re.sub(r'<script>.*?// Use Event Delegation.*?</script>\s*</body>', robust_script2, content, flags=re.DOTALL)
content = re.sub(r'<script>.*?\/\* Add hover effect \*\/.*?</script>\s*</body>', robust_script2, content, flags=re.DOTALL)
content = re.sub(r'<script>\s*document\.addEventListener\(\'click\'.*?</script>\s*</body>', robust_script2, content, flags=re.DOTALL)

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated index.html with new robust traversal logic')
