import codecs

content = '''
def format_telegram_smart_money_tip(match_name, match_date, bookmaker, market, opening_odd, current_odd, drop_pct):
    # Formats a beautiful alert for smart money drops
    message = (
        f"<b>🚨 ALERTA DE SMART MONEY DETECTADO</b>\\n\\n"
        f"⚽ <b>Jogo:</b> {match_name}\\n"
        f"📅 <b>Data:</b> {match_date}\\n"
        f"🎯 <b>Mercado Afetado:</b> {market}\\n"
        f"🏦 <b>Casa Afetada:</b> {bookmaker}\\n\\n"
        f"📉 <b>Esmagamento da Odd:</b>\\n"
        f"Abertura: @{opening_odd:.2f} ➡️ Atual: <b>@{current_odd:.2f}</b>\\n"
        f"💥 <b>Queda Total: -{drop_pct:.1f}%</b>\\n\\n"
        f"⚠️ <i>Atenção: O dinheiro institucional entrou pesado nessa seleção. Se a sua casa de aposta ainda não acompanhou a queda, há enorme valor!</i>"
    )
    return message
'''
with codecs.open('telegram_bot.py', 'a', encoding='utf-8') as f:
    f.write(content)
