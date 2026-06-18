import re

with open('backend/backtester.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = r'''                  elif staking_rule == 'kelly':
                      p_f_star = (p_prob \* p_odds - 1\.0) / (p_odds - 1\.0)
                      p_f_star = max\(0\.0, p_f_star\)
                      p_stake = state_ref\['bankroll'\] \* p_f_star \* stake_value
                      p_stake = min\(p_stake, state_ref\['bankroll'\] \* 0\.10\)'''

replacement = '''                  elif staking_rule.startswith('kelly'):
                      mult_k = 1.0
                      if staking_rule == 'kelly_half': mult_k = 0.5
                      elif staking_rule == 'kelly_quarter': mult_k = 0.25
                      elif staking_rule == 'kelly_eighth': mult_k = 0.125
                      elif staking_rule == 'kelly': mult_k = stake_value
                      else: mult_k = stake_value
                      
                      p_f_star = (p_prob * p_odds - 1.0) / (p_odds - 1.0)
                      p_f_star = max(0.0, p_f_star)
                      p_stake = state_ref['bankroll'] * p_f_star * mult_k
                      p_stake = min(p_stake, state_ref['bankroll'] * 0.05)'''

content_new = re.sub(target, replacement, content)
with open('backend/backtester.py', 'w', encoding='utf-8') as f:
    f.write(content_new)

print('Replaced target 3')
