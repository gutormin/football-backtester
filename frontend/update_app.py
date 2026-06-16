import codecs
import re

with codecs.open('app.js', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

pattern = r"async function runArbitrageScan\(\) \{[\s\S]*?const res = await fetch\(`\$\{API_BASE_URL\}/api/scan_arbitrage`\);\s*const data = await res.json\(\);"

replacement = """async function runArbitrageScan() {
    const btn = document.getElementById('btn-scan-arbitrage');
    const tbody = document.querySelector('#arbitrage-table tbody');
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Buscando...';
    btn.disabled = true;
    
    const selectedBookies = Array.from(document.querySelectorAll('.bookie-cb:checked')).map(cb => cb.value);
    const bookiesQuery = selectedBookies.length > 0 ? `?bookies=${encodeURIComponent(selectedBookies.join(','))}` : '';
    
    try {
        const res = await fetch(`${API_BASE_URL}/api/scan_arbitrage${bookiesQuery}`);
        const data = await res.json();"""

if re.search(pattern, content):
    content = re.sub(pattern, replacement, content)
    
    local_storage_logic = """
// Bookie Filter Local Storage Logic
document.addEventListener('DOMContentLoaded', () => {
    const savedBookies = localStorage.getItem('arbBookies');
    if (savedBookies) {
        const bookieArray = JSON.parse(savedBookies);
        document.querySelectorAll('.bookie-cb').forEach(cb => {
            cb.checked = bookieArray.includes(cb.value);
        });
    }
    
    document.querySelectorAll('.bookie-cb').forEach(cb => {
        cb.addEventListener('change', () => {
            const selectedBookies = Array.from(document.querySelectorAll('.bookie-cb:checked')).map(c => c.value);
            localStorage.setItem('arbBookies', JSON.stringify(selectedBookies));
        });
    });
});
"""
    content += '\n' + local_storage_logic
    
    with codecs.open('app.js', 'w', encoding='utf-8', errors='ignore') as f:
        f.write(content)
    print('Updated app.js successfully.')
else:
    print('Target not found in app.js')
