import re

with open('frontend/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Patch loadSchedulerConfigUi
load_old = '''        document.getElementById('tg-scheduler-enabled').checked = !!data.enabled;
        document.getElementById('tg-scheduler-interval').value = data.check_interval_hours || 6;
        if (data.upcoming_source && document.getElementById('tg-scheduler-source')) {
            document.getElementById('tg-scheduler-source').value = data.upcoming_source;
        }'''
load_new = '''        document.getElementById('tg-scheduler-enabled').checked = !!data.enabled;
        document.getElementById('tg-scheduler-interval').value = data.check_interval_hours || 6;
        if (document.getElementById('select-tg-scheduler-mode')) {
            document.getElementById('select-tg-scheduler-mode').value = data.mode || 'manual';
        }
        if (data.upcoming_source && document.getElementById('tg-scheduler-source')) {
            document.getElementById('tg-scheduler-source').value = data.upcoming_source;
        }'''
content = content.replace(load_old, load_new)

# Patch saveSchedulerConfigUi
save_old = '''    const enabled = document.getElementById('tg-scheduler-enabled').checked;
    const interval = parseInt(document.getElementById('tg-scheduler-interval').value) || 6;
    
    // Collect active strategy parameters from the sidebar controls
    const selectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked'))'''
    
save_new = '''    const enabled = document.getElementById('tg-scheduler-enabled').checked;
    const interval = parseInt(document.getElementById('tg-scheduler-interval').value) || 6;
    const mode = document.getElementById('select-tg-scheduler-mode') ? document.getElementById('select-tg-scheduler-mode').value : 'manual';
    
    // Collect active strategy parameters from the sidebar controls
    const selectedLeagues = Array.from(document.querySelectorAll('#leagues-checkbox-list input[type="checkbox"]:checked'))'''
content = content.replace(save_old, save_new)


save_payload_old = '''        const payload = {
            enabled: enabled,
            check_interval_hours: interval,
            leagues: selectedLeagues,
            market: marketsParam,
            value_threshold: parseFloat(document.getElementById('val-threshold').value),
            min_odds: parseFloat(document.getElementById('min-odds').value) || 1.0,
            max_odds: parseFloat(document.getElementById('max-odds').value) || 50.0,
            staking_rule: stakingRule,
            stake_value: stakeValue,
            initial_bankroll: parseFloat(document.getElementById('init-bankroll').value),
            upcoming_source: document.getElementById('tg-scheduler-source') ? document.getElementById('tg-scheduler-source').value : 'api'
        };'''
        
save_payload_new = '''        const payload = {
            enabled: enabled,
            mode: mode,
            check_interval_hours: interval,
            leagues: selectedLeagues,
            market: marketsParam,
            value_threshold: parseFloat(document.getElementById('val-threshold').value),
            min_odds: parseFloat(document.getElementById('min-odds').value) || 1.0,
            max_odds: parseFloat(document.getElementById('max-odds').value) || 50.0,
            staking_rule: stakingRule,
            stake_value: stakeValue,
            initial_bankroll: parseFloat(document.getElementById('init-bankroll').value),
            upcoming_source: document.getElementById('tg-scheduler-source') ? document.getElementById('tg-scheduler-source').value : 'api'
        };'''
content = content.replace(save_payload_old, save_payload_new)


with open('frontend/app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print("App patched config UI successfully")
