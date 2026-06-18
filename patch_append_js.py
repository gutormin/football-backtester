import os

js_code = """
// Global function to toggle groups
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
    }
};
"""

with open('frontend/app.js', 'a', encoding='utf-8') as f:
    f.write('\n' + js_code)
print('Appended JS')
