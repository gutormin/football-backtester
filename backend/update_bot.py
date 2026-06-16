import os

# Update telegram_bot.py
bot_path = r"backend\telegram_bot.py"
with open(bot_path, "r", encoding="utf-8") as f:
    bot_content = f.read()

bot_target = """def format_telegram_arbitrage_tip(match_name, match_date, bookies_dict, profit_margin):
    # Formats a beautiful alert for surebets
    message = (
        f"<b>🚨 OPORTUNIDADE DE ARBITRAGEM DETECTADA (SUREBET)</b>\\n\\n"
        f"⚔️ <b>Jogo:</b> {match_name}\\n"
        f"📅 <b>Data:</b> {match_date}\\n\\n"
        f"⚖️ <b>Lucro Garantido Estimado:</b> <b>+{profit_margin}%</b>\\n\\n"
        f"🎯 <b>ODDS PARA COMBINAR (1X2):</b>\\n"
        f"🔹 <b>Mandante (1):</b> {bookies_dict['1']}\\n"
        f"🔹 <b>Empate (X):</b> {bookies_dict['X']}\\n"
        f"🔹 <b>Visitante (2):</b> {bookies_dict['2']}\\n\\n"
        f"💡 <i>Lembre-se: As odds mudam rápido! Verifique em cada casa de apostas antes de confirmar a entrada. Divida sua banca proporcionalmente para garantir o lucro.</i>\\n\\n"
        f"🤖 <i>Sports Betting Pro Bot - Scanner de Arbitragem</i>"
    )
    return message"""

bot_replacement = """def format_telegram_arbitrage_tip(match_name, match_date, bookies_dict, profit_margin, market_name="Match Odds (1X2)", is_2_way=False, labels_dict=None):
    # Formats a beautiful alert for surebets
    message = (
        f"<b>🚨 OPORTUNIDADE DE ARBITRAGEM DETECTADA (SUREBET)</b>\\n\\n"
        f"⚔️ <b>Jogo:</b> {match_name}\\n"
        f"📅 <b>Data:</b> {match_date}\\n\\n"
        f"⚖️ <b>Lucro Garantido Estimado:</b> <b>+{profit_margin}%</b>\\n\\n"
        f"🎯 <b>ODDS PARA COMBINAR ({market_name}):</b>\\n"
    )
    if is_2_way and labels_dict:
        message += f"🔹 <b>{labels_dict['1']}:</b> {bookies_dict['1']}\\n"
        message += f"🔹 <b>{labels_dict['2']}:</b> {bookies_dict['2']}\\n\\n"
    else:
        message += f"🔹 <b>Mandante (1):</b> {bookies_dict['1']}\\n"
        message += f"🔹 <b>Empate (X):</b> {bookies_dict['X']}\\n"
        message += f"🔹 <b>Visitante (2):</b> {bookies_dict['2']}\\n\\n"
        
    message += (
        f"💡 <i>Lembre-se: As odds mudam rápido! Verifique em cada casa de apostas antes de confirmar a entrada. Divida sua banca proporcionalmente para garantir o lucro.</i>\\n\\n"
        f"🤖 <i>Sports Betting Pro Bot - Scanner de Arbitragem</i>"
    )
    return message"""

if "def format_telegram_arbitrage_tip(" in bot_content:
    bot_content = bot_content.replace(bot_target, bot_replacement)
    with open(bot_path, "w", encoding="utf-8") as f:
        f.write(bot_content)
    print("Updated telegram_bot.py")

# Update app.py
app_path = r"backend\app.py"
with open(app_path, "r", encoding="utf-8") as f:
    app_content = f.read()

app_target = """        msg_text = format_telegram_arbitrage_tip(
            match_name="Palmeiras vs Flamengo",
            match_date="15/06/2026 16:00",
            bookies_dict={"1": "Betfair", "X": "Pinnacle", "2": "Bet365"},
            profit_margin=2.45
        )"""

app_replacement = """        msg_text = format_telegram_arbitrage_tip(
            match_name="Palmeiras vs Flamengo",
            match_date="15/06/2026 16:00",
            bookies_dict={"1": "Betfair", "X": "Pinnacle", "2": "Bet365"},
            profit_margin=2.45
        )""" # No change needed for test alert since it's 3-way

# Update scheduler.py
sched_path = r"backend\scheduler.py"
with open(sched_path, "r", encoding="utf-8") as f:
    sched_content = f.read()

sched_target = """        msg_text = format_telegram_arbitrage_tip(
            match_name=op['match'],
            match_date=op['date'],
            bookies_dict=op['bookmakers'],
            profit_margin=op['profit_margin']
        )"""

sched_replacement = """        msg_text = format_telegram_arbitrage_tip(
            match_name=op['match'],
            match_date=op['date'],
            bookies_dict=op['bookmakers'],
            profit_margin=op['profit_margin'],
            market_name=op.get('market', 'Match Odds (1X2)'),
            is_2_way=op.get('is_2_way', False),
            labels_dict=op.get('labels', None)
        )"""

if sched_target in sched_content:
    sched_content = sched_content.replace(sched_target, sched_replacement)
    with open(sched_path, "w", encoding="utf-8") as f:
        f.write(sched_content)
    print("Updated scheduler.py")
