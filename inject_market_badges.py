import re

market_status = {
    'home':      (True,  True),
    'away':      (True,  True),
    'draw':      (True,  True),
    'lay_home':  (False, True),
    'lay_away':  (False, True),
    'lay_draw':  (False, True),
    'over15':    (False, True),
    'over25':    (True,  True),
    'under25':   (True,  True),
    'over35':    (False, True),
    'under35':   (False, True),
    'over45':    (False, True),
    'under45':   (False, True),
    'over55':    (False, False),
    'under55':   (False, False),
    'btts_yes':  (False, True),
    'btts_no':   (False, True),
    'dnb_h':     (False, False),
    'dnb_a':     (False, False),
    'ht_home':   (False, True),
    'ht_draw':   (False, True),
    'ht_away':   (False, True),
    'ht_over05': (True,  True),
    'ht_under05':(True,  True),
    'ht_over15': (True,  True),
    'ht_under15':(True,  True),
    'ah_home':   (True,  True),
    'ah_away':   (True,  True),
    'cs_10':     (False, True),
    'cs_20':     (False, True),
    'cs_21':     (False, True),
    'cs_00':     (False, True),
    'cs_11':     (False, True),
    'cs_01':     (False, True),
    'cs_02':     (False, True),
    'cs_12':     (False, True),
    'lay_cs_10': (False, False),
    'lay_cs_20': (False, False),
    'lay_cs_21': (False, False),
    'lay_cs_00': (False, False),
    'lay_cs_11': (False, False),
    'lay_cs_01': (False, False),
    'lay_cs_02': (False, False),
    'lay_cs_12': (False, False),
}

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Inject legend block if not already there
legend_html = """<div class="mkt-badge-legend">
                                    <span>Legenda:</span>
                                    <span><span class="mkt-badge mkt-real">\u2713</span> Real</span>
                                    <span><span class="mkt-badge mkt-est">\u007e</span> Estimado</span>
                                    <span style="margin-left:auto; font-weight:600; font-size: 8.5px; color:var(--text-muted);">FD: FootballData | FP: FutPython</span>
                                </div>"""

target_container = '<div class="multiselect-options" id="market-checkboxes-container">'
if legend_html not in content and target_container in content:
    content = content.replace(target_container, legend_html + '\n                                ' + target_container)
    print("Injected legend block.")

# 2. Inject badges using regex to put them right before </label>
count = 0
for market, (fd_real, fp_real) in market_status.items():
    fd_cls = 'mkt-real' if fd_real else 'mkt-est'
    fd_txt = 'FD \u2713' if fd_real else 'FD \u007e'
    fd_tip = 'Football-Data: Odds Reais' if fd_real else 'Football-Data: Estimado (Poisson)'
    fp_cls = 'mkt-real' if fp_real else 'mkt-est'
    fp_txt = 'FP \u2713' if fp_real else 'FP \u007e'
    fp_tip = 'FutPythonTrader: Odds Reais' if fp_real else 'FutPythonTrader: Estimado (Poisson)'

    badges = (
        '<span class="mkt-status-badges">'
        '<span class="mkt-badge mkt-badge-fd ' + fd_cls + '" title="' + fd_tip + '">' + fd_txt + '</span>'
        '<span class="mkt-badge mkt-badge-fp ' + fp_cls + '" title="' + fp_tip + '">' + fp_txt + '</span>'
        '</span>'
    )

    # Regex pattern to match the input element and the text, placing badges before closing label tag.
    pattern = re.compile(
        r'(<input[^>]*value="' + re.escape(market) + r'"[^>]*/>\s*)([^<]*?)(\s*</label>)',
        re.IGNORECASE
    )

    def repl(match):
        return match.group(1) + match.group(2).strip() + ' ' + badges + match.group(3)

    new_content, num_subs = pattern.subn(repl, content)
    if num_subs > 0:
        content = new_content
        count += num_subs
    else:
        print('NOT FOUND OR ALREADY CONTAINS BADGES: ' + market)

print('Replaced ' + str(count) + ' market label(s)')

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('DONE')
