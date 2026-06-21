import os

target_file = r"frontend\app.js"

with open(target_file, 'r', encoding='utf-8') as f:
    content = f.read()

# We need to insert a block inside window.runBacktest = async function() {
search_str = "window.runBacktest = async function() {"
insert_str = """
    // --- Portfolio Fix: Restore standard UI panels ---
    document.getElementById('portfolio-results-panel').style.display = 'none';
    document.getElementById('standard-metrics-grid').style.display = 'grid';
    const mainCharts = document.querySelector('.main-charts');
    if (mainCharts) mainCharts.style.display = 'block';
    const stakingPanel = document.getElementById('staking-comparison-panel');
    if (stakingPanel) stakingPanel.style.display = 'block';
    const quartilesPanel = document.getElementById('quartiles-panel');
    if (quartilesPanel) quartilesPanel.style.display = 'block';
    const resultsTableSection = document.querySelector('.results-table-section');
    if (resultsTableSection) resultsTableSection.style.display = 'block';
    const chartCards = document.querySelectorAll('.chart-card');
    chartCards.forEach(c => {
        if(c.parentElement && c.parentElement.className === 'charts-grid') {
            c.closest('div[style*="display: grid"]').style.display = 'grid';
        }
    });
"""

if search_str in content and "Portfolio Fix" not in content:
    content = content.replace(search_str, search_str + insert_str)
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Patched window.runBacktest successfully.")
else:
    print("Could not patch window.runBacktest.")
