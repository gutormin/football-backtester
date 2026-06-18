import re

with open('frontend/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

card_old = '''        card.innerHTML = `
            ${tipBadgeHtml}
            <div class="upcoming-match-header">'''
card_new = '''        card.innerHTML = `
            ${tipBadgeHtml}
            <div class="upcoming-match-header" style="flex-wrap: wrap; gap: 4px;">
                ${match.strategy_name ? `<span class="badge badge-success" style="background: var(--primary); padding: 2px 6px; font-size: 10px;"><i class="fa-solid fa-robot"></i> ${match.strategy_name}</span>` : ''}'''

content = content.replace(card_old, card_new)

with open('frontend/app.js', 'w', encoding='utf-8') as f:
    f.write(content)
print("Card patched")
