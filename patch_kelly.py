import os

def patch_file(filepath, old_str, new_str):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    if old_str in content:
        content = content.replace(old_str, old_str + new_str)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Patched {filepath}")
    else:
        print(f"Could not find target in {filepath}")

# 1. index.html
patch_file(
    'frontend/index.html',
    '<option value="kelly_eighth">Kelly Criterion (1/8)</option>',
    '\n                            <option value="kelly_sixteenth">Kelly Criterion (1/16)</option>'
)

# 2. app.js
patch_file(
    'frontend/app.js',
    "else if (ruleInput === 'kelly_eighth') stakeValue = 0.125;",
    "\n        else if (ruleInput === 'kelly_sixteenth') stakeValue = 0.0625;"
)

patch_file(
    'frontend/app.js',
    "else if (rule === 'kelly_eighth') kellyFractionText = '1/8';",
    "\n        else if (rule === 'kelly_sixteenth') kellyFractionText = '1/16';"
)

patch_file(
    'frontend/app.js',
    "else if (rule === 'kelly_eighth') kellyFractionText = '1/8 de Kelly';",
    "\n        else if (rule === 'kelly_sixteenth') kellyFractionText = '1/16 de Kelly';"
)

# 3. backend/app.py
patch_file(
    'backend/app.py',
    "elif stakingRule == 'kelly_eighth': mult_k = 0.125",
    "\n                        elif stakingRule == 'kelly_sixteenth': mult_k = 0.0625"
)

# 4. backend/backtester.py
patch_file(
    'backend/backtester.py',
    "elif staking_rule == 'kelly_eighth': mult_k = 0.125",
    "\n                                elif staking_rule == 'kelly_sixteenth': mult_k = 0.0625"
)
