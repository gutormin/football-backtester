import os
import json
import urllib.request
import urllib.parse
from .data_loader import DATA_DIR

CONFIG_PATH = os.path.join(DATA_DIR, 'telegram_config.json')

def get_telegram_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"token": "", "chat_id": "", "enabled": False}

def save_telegram_config(token, chat_id, enabled=True):
    config = {
        "token": token.strip(),
        "chat_id": chat_id.strip(),
        "enabled": bool(enabled)
    }
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    return config

def send_telegram_message(message):
    config = get_telegram_config()
    token = config.get("token")
    chat_id = config.get("chat_id")
    enabled = config.get("enabled", False)
    
    if not token or not chat_id:
        return False, "Token do bot ou Chat ID não configurados."
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0'
            }
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            if res_data.get("ok"):
                return True, "Mensagem enviada com sucesso!"
            else:
                return False, f"Erro do Telegram: {res_data.get('description')}"
    except Exception as e:
        return False, f"Erro de conexão com API do Telegram: {str(e)}"

def send_test_message():
    message = (
        "<b>🔔 Sports Betting Backtester Pro</b>\n\n"
        "✅ Seu robô de tips foi conectado com sucesso!\n"
        "Pronto para transmitir os alertas de entradas automáticas."
    )
    return send_telegram_message(message)

def format_telegram_tip(league_name, date_str, time_str, home_team, away_team, market_label, prob, fair_odds, bookie_odds, ev, stake_pct):
    # Formats a beautiful alert for tips
    message = (
        f"<b>🔔 NOVA ENTRADA SUGERIDA (+EV)</b>\n\n"
        f"🏆 <b>Liga:</b> {league_name}\n"
        f"⚔️ <b>Jogo:</b> {home_team} vs {away_team}\n"
        f"📅 <b>Data/Hora:</b> {date_str} às {time_str}\n\n"
        f"🎯 <b>Entrada:</b> <u>{market_label}</u>\n"
        f"📊 <b>Probabilidade IA:</b> {prob:.1f}%\n"
        f"📈 <b>Odd Mínima (Justa):</b> {fair_odds:.2f}\n"
        f"🚀 <b>Odd Encontrada:</b> {bookie_odds:.2f} (Edge EV: +{((ev-1)*100):.1f}%)\n"
        f"💰 <b>Gestão Sugerida:</b> Stake de <b>{stake_pct:.1f}%</b> da banca\n\n"
        f"🤖 <i>Sports Betting Pro Bot - Tips Inteligentes</i>"
    )
    return message

def format_telegram_arbitrage_tip(match_name, match_date, bookies_dict, profit_margin, market_name="Match Odds (1X2)", is_2_way=False, labels_dict=None):
    # Formats a beautiful alert for surebets
    message = (
        f"<b>🚨 OPORTUNIDADE DE ARBITRAGEM DETECTADA (SUREBET)</b>\n\n"
        f"⚔️ <b>Jogo:</b> {match_name}\n"
        f"📅 <b>Data:</b> {match_date}\n\n"
        f"⚖️ <b>Lucro Garantido Estimado:</b> <b>+{profit_margin}%</b>\n\n"
        f"🎯 <b>ODDS PARA COMBINAR ({market_name}):</b>\n"
    )
    if is_2_way and labels_dict:
        message += f"🔹 <b>{labels_dict.get('1', 'Seleção 1')}:</b> {bookies_dict.get('1', '-')}\n"
        message += f"🔹 <b>{labels_dict.get('2', 'Seleção 2')}:</b> {bookies_dict.get('2', '-')}\n\n"
    else:
        message += f"🔹 <b>Mandante (1):</b> {bookies_dict.get('1', '-')}\n"
        message += f"🔹 <b>Empate (X):</b> {bookies_dict.get('X', '-')}\n"
        message += f"🔹 <b>Visitante (2):</b> {bookies_dict.get('2', '-')}\n\n"
        
    message += (
        f"💡 <i>Lembre-se: As odds mudam rápido! Verifique em cada casa de apostas antes de confirmar a entrada. Divida sua banca proporcionalmente para garantir o lucro.</i>\n\n"
        f"🤖 <i>Sports Betting Pro Bot - Scanner de Arbitragem</i>"
    )
    return message

TIPS_LOG_PATH = os.path.join(DATA_DIR, 'telegram_tips_sent.json')

def get_telegram_tips():
    if os.path.exists(TIPS_LOG_PATH):
        try:
            with open(TIPS_LOG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_telegram_tips(tips):
    os.makedirs(os.path.dirname(TIPS_LOG_PATH), exist_ok=True)
    with open(TIPS_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(tips, f, indent=4, ensure_ascii=False)
    return tips

import uuid
from datetime import datetime

def add_telegram_tip(league_name, date_str, time_str, home_team, away_team, market_label, bookie_odds, stake_pct):
    tips = get_telegram_tips()
    new_tip = {
        "id": str(uuid.uuid4()),
        "league_name": league_name,
        "date": date_str,
        "time": time_str,
        "home_team": home_team,
        "away_team": away_team,
        "market": market_label,
        "odds": float(bookie_odds) if bookie_odds else 0.0,
        "stake": float(stake_pct) if stake_pct else 0.0,
        "status": "Pendente",
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    tips.append(new_tip)
    save_telegram_tips(tips)
    return new_tip

def update_telegram_tip_status(tip_id, status):
    tips = get_telegram_tips()
    updated = False
    for t in tips:
        if t["id"] == tip_id:
            t["status"] = status
            updated = True
            break
    if updated:
        save_telegram_tips(tips)
    return tips

def clear_telegram_tips():
    return save_telegram_tips([])

ARB_TIPS_LOG_PATH = os.path.join(DATA_DIR, 'telegram_arbitrage_tips_sent.json')

def get_telegram_arbitrage_tips():
    if os.path.exists(ARB_TIPS_LOG_PATH):
        try:
            with open(ARB_TIPS_LOG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_telegram_arbitrage_tips(tips):
    os.makedirs(os.path.dirname(ARB_TIPS_LOG_PATH), exist_ok=True)
    with open(ARB_TIPS_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(tips, f, indent=4, ensure_ascii=False)
    return tips

def add_telegram_arbitrage_tip(match_name, match_date, profit_margin):
    tips = get_telegram_arbitrage_tips()
    new_tip = {
        "id": str(uuid.uuid4()),
        "match": match_name,
        "date": match_date,
        "profit_margin": float(profit_margin),
        "status": "Pendente",
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    tips.append(new_tip)
    save_telegram_arbitrage_tips(tips)
    return new_tip


def format_telegram_smart_money_tip(match_name, match_date, bookmaker, market, opening_odd, current_odd, drop_pct):
    # Formats a beautiful alert for smart money drops
    message = (
        f"<b>🚨 ALERTA DE SMART MONEY DETECTADO</b>\n\n"
        f"⚽ <b>Jogo:</b> {match_name}\n"
        f"📅 <b>Data:</b> {match_date}\n"
        f"🎯 <b>Mercado Afetado:</b> {market}\n"
        f"🏦 <b>Casa Afetada:</b> {bookmaker}\n\n"
        f"📉 <b>Esmagamento da Odd:</b>\n"
        f"Abertura: @{opening_odd:.2f} ➡️ Atual: <b>@{current_odd:.2f}</b>\n"
        f"💥 <b>Queda Total: -{drop_pct:.1f}%</b>\n\n"
        f"⚠️ <i>Atenção: O dinheiro institucional entrou pesado nessa seleção. Se a sua casa de aposta ainda não acompanhou a queda, há enorme valor!</i>"
    )
    return message
