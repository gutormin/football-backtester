import sys
import codecs

with codecs.open('C:\\Users\\Gustavo\\.gemini\\antigravity\\scratch\\football-backtester\\backend\\telegram_bot.py', 'r', 'utf-8') as f:
    lines = f.readlines()

out_lines = []
in_func = False
for line in lines:
    if line.startswith("def format_telegram_arbitrage_tip("):
        in_func = True
        
        # Inject the new function
        new_func = """def format_telegram_arbitrage_tip(match_name, match_date, bookies_dict, profit_margin, market_name="Match Odds (1X2)", is_2_way=False, labels_dict=None, odds_dict=None):
    # Calculate stakes for a R$ 100 total investment
    stakes_str = ""
    if odds_dict:
        try:
            total_implied = sum(1.0 / float(o) for o in odds_dict.values() if float(o) > 0)
            total_return = 100.0 / total_implied
            stakes = {k: round(total_return / float(v), 2) for k, v in odds_dict.items() if float(v) > 0}
            
            stakes_str = "\\n💰 <b>SUGESTÃO DE ENTRADA (Banca Total: R$ 100)</b>:\\n"
            if is_2_way and labels_dict:
                stakes_str += f"🔸 <b>{labels_dict.get('1', 'Seleção 1')}</b>: Aposte R$ {stakes.get('1', 0):.2f}\\n"
                stakes_str += f"🔸 <b>{labels_dict.get('2', 'Seleção 2')}</b>: Aposte R$ {stakes.get('2', 0):.2f}\\n"
            else:
                stakes_str += f"🔸 <b>Mandante (1)</b>: Aposte R$ {stakes.get('1', 0):.2f}\\n"
                stakes_str += f"🔸 <b>Empate (X)</b>: Aposte R$ {stakes.get('X', 0):.2f}\\n"
                stakes_str += f"🔸 <b>Visitante (2)</b>: Aposte R$ {stakes.get('2', 0):.2f}\\n"
            stakes_str += f"<i>(Retorno Bruto: R$ {total_return:.2f} | Lucro Líquido: R$ {total_return - 100.0:.2f})</i>\\n\\n"
        except Exception:
            pass

    # Formats a beautiful alert for surebets
    message = (
        f"<b>🚨 OPORTUNIDADE DE ARBITRAGEM DETECTADA (SUREBET)</b>\\n\\n"
        f"⚔️ <b>Jogo:</b> {match_name}\\n"
        f"📅 <b>Data:</b> {match_date}\\n\\n"
        f"⚖️ <b>Lucro Garantido Estimado:</b> <b>+{profit_margin}%</b>\\n\\n"
        f"🎯 <b>ODDS PARA COMBINAR ({market_name}):</b>\\n"
    )
    if is_2_way and labels_dict:
        o1 = f" (@{odds_dict.get('1')})" if odds_dict and '1' in odds_dict else ""
        o2 = f" (@{odds_dict.get('2')})" if odds_dict and '2' in odds_dict else ""
        message += f"🔹 <b>{labels_dict.get('1', 'Seleção 1')}:</b> {bookies_dict.get('1', '-')}{o1}\\n"
        message += f"🔹 <b>{labels_dict.get('2', 'Seleção 2')}:</b> {bookies_dict.get('2', '-')}{o2}\\n\\n"
    else:
        o1 = f" (@{odds_dict.get('1')})" if odds_dict and '1' in odds_dict else ""
        ox = f" (@{odds_dict.get('X')})" if odds_dict and 'X' in odds_dict else ""
        o2 = f" (@{odds_dict.get('2')})" if odds_dict and '2' in odds_dict else ""
        message += f"🔹 <b>Mandante (1):</b> {bookies_dict.get('1', '-')}{o1}\\n"
        message += f"🔹 <b>Empate (X):</b> {bookies_dict.get('X', '-')}{ox}\\n"
        message += f"🔹 <b>Visitante (2):</b> {bookies_dict.get('2', '-')}{o2}\\n\\n"
        
    if stakes_str:
        message += stakes_str

    message += (
        f"💡 <i>Lembre-se: As odds mudam rápido! Verifique em cada casa de apostas antes de confirmar a entrada.</i>\\n\\n"
        f"🤖 <i>Sports Betting Pro Bot - Scanner de Arbitragem</i>"
    )
    return message\n"""
        out_lines.append(new_func)
        continue
        
    if in_func:
        if line.startswith("def ") or line.startswith("TIPS_LOG_PATH"):
            in_func = False
        else:
            continue
            
    if not in_func:
        out_lines.append(line)

with codecs.open('C:\\Users\\Gustavo\\.gemini\\antigravity\\scratch\\football-backtester\\backend\\telegram_bot.py', 'w', 'utf-8') as f:
    f.writelines(out_lines)
print('Done!')
