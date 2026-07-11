import os
import json
import requests
from .data_loader import DATA_DIR
from .api_utils import retry_with_backoff

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
    
    @retry_with_backoff(max_retries=2, base_delay=1.0)
    def _send():
        return requests.post(url, json=payload, timeout=10,
                             headers={'User-Agent': 'Mozilla/5.0'})

    try:
        response = _send()
        if response.status_code == 200 and response.json().get("ok"):
            return True, "Mensagem enviada com sucesso!"
        else:
            res_data = response.json()
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
    # Formats the alert exactly as requested by the user
    message = (
        f"<b>🔔 NOVA ENTRADA SUGERIDA (+EV)</b>\n\n"
        f"🎯 <b>Entrada:</b> {market_label}\n"
        f"⚔️ <b>Jogo:</b> {home_team} x {away_team} - {time_str} ({date_str})\n"
        f"📊 <b>Probabilidade IA:</b> {prob:.1f}%\n"
        f"📈 <b>Odd Mínima (Justa):</b> {fair_odds:.2f}\n"
        f"🚀 <b>Odd Encontrada:</b> {bookie_odds:.2f}\n"
        f"📈 <b>(Edge EV: +{((ev-1)*100):.1f}%)</b>\n"
        f"💰 <b>Gestão Sugerida:</b> Stake de <b>{stake_pct:.1f}%</b> da banca\n\n"
        f"🤖 <i>Sports Betting Pro Bot</i>"
    )
    return message

def format_telegram_arbitrage_tip(match_name, match_date, bookies_dict, profit_margin, market_name="Match Odds (1X2)", is_2_way=False, labels_dict=None, odds_dict=None, net_profit=None, quality_score=None, sport_key=''):
    # Calculate stakes for a R$ 100 total investment
    stakes_str = ""
    if odds_dict:
        try:
            total_implied = sum(1.0 / float(o) for o in odds_dict.values() if float(o) > 0)
            total_return = 100.0 / total_implied
            stakes = {k: round(total_return / float(v), 2) for k, v in odds_dict.items() if float(v) > 0}

            stakes_str = "\n💰 <b>SUGESTÃO DE ENTRADA (Banca Total: R$ 100)</b>:\n"
            if is_2_way and labels_dict:
                stakes_str += f"🔸 <b>{labels_dict.get('1', 'Seleção 1')}</b>: Aposte R$ {stakes.get('1', 0):.2f}\n"
                stakes_str += f"🔸 <b>{labels_dict.get('2', 'Seleção 2')}</b>: Aposte R$ {stakes.get('2', 0):.2f}\n"
            else:
                stakes_str += f"🔸 <b>Mandante (1)</b>: Aposte R$ {stakes.get('1', 0):.2f}\n"
                stakes_str += f"🔸 <b>Empate (X)</b>: Aposte R$ {stakes.get('X', 0):.2f}\n"
                stakes_str += f"🔸 <b>Visitante (2)</b>: Aposte R$ {stakes.get('2', 0):.2f}\n"
            stakes_str += f"<i>(Retorno Bruto: R$ {total_return:.2f} | Lucro Líquido: R$ {total_return - 100.0:.2f})</i>\n\n"
        except Exception:
            pass

    # Betfair commission warning
    bf_warning = ""
    for bookie_name in bookies_dict.values():
        if 'betfair' in str(bookie_name).lower():
            bf_warning = "\n⚠️ <b>Betfair Exchange detectada!</b> Lembre-se da comissão de 2-5% sobre o lucro.\n"
            break

    # Net profit line
    net_line = ""
    if net_profit is not None:
        net_line = f"\n📊 <b>Lucro Líquido Estimado (após custos):</b> <b>+{net_profit}%</b>"

    # Quality score
    qs_line = ""
    if quality_score is not None:
        qs_emoji = "🟢" if quality_score >= 70 else "🟡" if quality_score >= 50 else "🟠"
        qs_line = f"\n🏷️ <b>Score de Qualidade:</b> {qs_emoji} {quality_score}/100"

    # League info
    league_line = ""
    if sport_key:
        league_name = sport_key.replace('soccer_', '').replace('_', ' ').title()
        league_line = f"\n🏟️ <b>Liga:</b> {league_name}"

    # Formats a beautiful alert for surebets
    message = (
        f"<b>🚨 OPORTUNIDADE DE ARBITRAGEM DETECTADA (SUREBET)</b>\n\n"
        f"⚔️ <b>Jogo:</b> {match_name}\n"
        f"📅 <b>Data:</b> {match_date}{league_line}\n\n"
        f"⚖️ <b>Lucro Bruto Estimado:</b> <b>+{profit_margin}%</b>{net_line}{qs_line}{bf_warning}\n\n"
        f"🎯 <b>ODDS PARA COMBINAR ({market_name}):</b>\n"
    )
    if is_2_way and labels_dict:
        o1 = f" (@{odds_dict.get('1')})" if odds_dict and '1' in odds_dict else ""
        o2 = f" (@{odds_dict.get('2')})" if odds_dict and '2' in odds_dict else ""
        message += f"🔹 <b>{labels_dict.get('1', 'Seleção 1')}:</b> {bookies_dict.get('1', '-')}{o1}\n"
        message += f"🔹 <b>{labels_dict.get('2', 'Seleção 2')}:</b> {bookies_dict.get('2', '-')}{o2}\n\n"
    else:
        o1 = f" (@{odds_dict.get('1')})" if odds_dict and '1' in odds_dict else ""
        ox = f" (@{odds_dict.get('X')})" if odds_dict and 'X' in odds_dict else ""
        o2 = f" (@{odds_dict.get('2')})" if odds_dict and '2' in odds_dict else ""
        message += f"🔹 <b>Mandante (1):</b> {bookies_dict.get('1', '-')}{o1}\n"
        message += f"🔹 <b>Empate (X):</b> {bookies_dict.get('X', '-')}{ox}\n"
        message += f"🔹 <b>Visitante (2):</b> {bookies_dict.get('2', '-')}{o2}\n\n"

    if stakes_str:
        message += stakes_str

    message += (
        f"💡 <i>Lembre-se: As odds mudam rápido! Verifique em cada casa de apostas antes de confirmar a entrada.</i>\n\n"
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
from datetime import datetime, timedelta

MAX_TIPS_AGE_DAYS = 30
MAX_TIPS_COUNT = 500

def _prune_old_tips(tips, max_age_days=MAX_TIPS_AGE_DAYS, max_count=MAX_TIPS_COUNT):
    cutoff = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d %H:%M:%S')
    pruned = [t for t in tips if t.get('created_at', '') >= cutoff]
    if len(pruned) > max_count:
        pruned = pruned[-max_count:]
    return pruned

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
    tips = _prune_old_tips(tips)
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
    tips = _prune_old_tips(tips, max_age_days=MAX_TIPS_AGE_DAYS, max_count=MAX_TIPS_COUNT)
    save_telegram_arbitrage_tips(tips)
    return new_tip


def format_telegram_smart_money_tip(match_name, match_date, bookmaker, market, opening_odd, current_odd, drop_pct, confidence_score=None, confidence_level=None, liquidity_tier=None, sharpness_score=None, profile_type=None, velocity=None, acceleration_ratio=None, acceleration_text=None, is_in_play=False, elapsed_minutes=0, adjusted_drop_pct=0.0):
    # Formats a beautiful alert for smart money drops
    confidence_str = ""
    if confidence_level and confidence_score is not None:
        emoji = "🟢" if confidence_level == "Alta" else ("🟡" if confidence_level == "Média" else "🔴")
        confidence_str = f"ℹ️ <b>Índice de Confiança:</b> {emoji} <b>{confidence_level}</b> ({confidence_score:.0f}%)\n💧 <b>Liquidez da Liga:</b> {liquidity_tier}\n"
        if profile_type:
            p_emoji = "🧠" if profile_type == "Sharps" else "📢"
            p_name = "Sharps (Dinheiro Inteligente)" if profile_type == "Sharps" else "Squares (Público/Tipster)"
            confidence_str += f"{p_emoji} <b>Perfil do Drop:</b> {p_name} - {sharpness_score:.0f}%\n"
        
        if velocity is not None and acceleration_ratio is not None:
            acc_emoji = "➡️"
            if acceleration_text == "Aceleração Forte":
                acc_emoji = "🚀"
            elif acceleration_text == "Acelerando":
                acc_emoji = "📈"
            elif acceleration_text == "Desacelerando":
                acc_emoji = "📉"
            confidence_str += f"⚡ <b>Velocidade do Drop:</b> -{velocity:.1f}%/h\n"
            confidence_str += f"{acc_emoji} <b>Aceleração:</b> +{acceleration_ratio:.1f}x ({acceleration_text})\n"
            
        confidence_str += "\n"

    in_play_header = ""
    drop_info_str = f"💥 <b>Queda Total: -{drop_pct:.1f}%</b>\n\n"
    if is_in_play:
        in_play_header = f"🔴 <b>AO VIVO - {elapsed_minutes:.0f}' MINUTOS</b>\n⚠️ <i>Partida em andamento. Odds de gols e empate têm decaimento natural.</i>\n\n"
        drop_info_str = (
            f"💥 <b>Queda Real (Nominal): -{drop_pct:.1f}%</b>\n"
            f"📉 <b>Queda Ajustada (Time Decay): -{adjusted_drop_pct:.1f}%</b>\n\n"
        )

    message = (
        f"<b>🚨 ALERTA DE SMART MONEY DETECTADO</b>\n\n"
        f"{in_play_header}"
        f"⚽ <b>Jogo:</b> {match_name}\n"
        f"📅 <b>Data:</b> {match_date}\n"
        f"🎯 <b>Mercado Afetado:</b> {market}\n"
        f"🏦 <b>Casa Afetada:</b> {bookmaker}\n\n"
        f"{confidence_str}"
        f"📉 <b>Esmagamento da Odd:</b>\n"
        f"Abertura: @{opening_odd:.2f} ➡️ Atual: <b>@{current_odd:.2f}</b>\n"
        f"{drop_info_str}"
        f"⚠️ <i>Atenção: O dinheiro institucional entrou pesado nessa seleção. Se a sua casa de aposta ainda não acompanhou a queda, há enorme valor!</i>"
    )
    return message


def format_pure_blood_tip(league_name, match_name, match_date, time_str, market_label, prob, ev_pct, cluster_desc, avg_goals):
    min_odd = 1.05 / (prob / 100.0) if prob > 0 else 0
    message = (
        f"🚨 <b>SINAL PURO-SANGUE CONFIRMADO!</b> 🚨\n\n"
        f"🏆 <b>Liga:</b> {league_name}\n"
        f"⚽ <b>Jogo:</b> {match_name}\n"
        f"📅 <b>Data:</b> {match_date} às {time_str}\n\n"
        f"📊 <b>Mercado Indicado:</b> {market_label}\n"
        f"📈 <b>Probabilidade Real (Scanner):</b> {prob:.1f}%\n"
        f"🧬 <b>Validação IA (Cluster):</b> Aprovado!\n"
        f"<i>A liga pertence ao {cluster_desc} (Média: {avg_goals:.2f} gols). O edge é real e estatisticamente comprovado.</i>\n\n"
        f"💰 <b>Odd Mínima de Entrada (+5% EV):</b> @{min_odd:.2f}\n"
        f"<i>(Se a casa oferecer odd maior ou igual a essa, você tem vantagem matemática garantida a longo prazo!)</i>\n"
    )
    return message

def format_contrarian_tip(league_name, match_name, match_date, time_str, market_label, bookie_odd, cluster_desc, recommended_action):
    message = (
        f"⚠️ <b>ANOMALIA DE ODD ENCONTRADA!</b> ⚠️\n\n"
        f"🏆 <b>Liga:</b> {league_name}\n"
        f"⚽ <b>Jogo:</b> {match_name}\n"
        f"📅 <b>Data:</b> {match_date} às {time_str}\n\n"
        f"🧬 <b>DNA do Campeonato:</b> {cluster_desc}\n"
        f"📉 <b>Odd da Casa de Apostas:</b> {market_label} pagando absurdos <b>@{bookie_odd:.2f}</b>!\n\n"
        f"💡 <b>Análise:</b> A casa de apostas está precificando uma expectativa de jogo que contradiz completamente o comportamento histórico (Cluster) dessa liga.\n\n"
        f"🤖 <b>Ação Recomendada (Contrarian):</b> {recommended_action}\n"
        f"<i>Há um EV (Valor Esperado) gigantesco em ir contra a manada aqui!</i>\n"
    )
    return message

def _compute_min_odds_for_market(market, stats, ev_threshold=0.05):
    """Given a market label and cluster stats, return the minimum odds for EV+ threshold."""
    prob = None
    m = market.lower()

    if 'over 2.5' in m or m == 'over 2.5':
        prob = stats.get('over25_pct', 0.5)
    elif 'under 2.5' in m or m == 'under 2.5':
        prob = 1.0 - stats.get('over25_pct', 0.5)
    elif 'over 0.5 ht' in m or m == 'over 0.5 ht':
        prob = min(0.80, max(0.55, stats.get('avg_goals', 2.5) / 4.0))
    elif 'under 0.5 ht' in m or m == 'under 0.5 ht':
        prob_ht = min(0.80, max(0.55, stats.get('avg_goals', 2.5) / 4.0))
        prob = 1.0 - prob_ht
    elif 'btts yes' in m or m == 'btts yes' or 'ambas marcam' in m:
        prob = stats.get('btts_pct', 0.5)
    elif 'back home' in m or m == 'back home' or 'back mandante' in m:
        prob = stats.get('home_win_pct', 0.4)
    elif 'lay home' in m or m == 'lay home':
        prob = 1.0 - stats.get('home_win_pct', 0.4)
    elif 'empate ht' in m or m == 'empate ht':
        prob = stats.get('draw_pct', 0.28)
    elif 'handicap' in m:
        prob = stats.get('home_win_pct', 0.4)
    elif 'match odds' in m:
        return None  # too complex for a single odd line

    if prob is None or prob <= 0 or prob >= 1:
        return None
    min_odd = round((1.0 + ev_threshold) / prob, 2)
    return min_odd


def format_dna_shift_alert(league_name, old_cluster_desc, new_cluster_desc, markets, stats):
    # Build per-market odds lines
    odds_lines = []
    for mkt in markets:
        min_odd = _compute_min_odds_for_market(mkt, stats)
        if min_odd:
            odds_lines.append(f"  • {mkt}: <b>@≥{min_odd:.2f}</b>")
        else:
            odds_lines.append(f"  • {mkt}")

    message = (
        f"🔄 <b>MUDANÇA DE COMPORTAMENTO DETECTADA!</b> 🔄\n\n"
        f"🏆 <b>Liga:</b> {league_name}\n"
        f"📊 <b>Gols/Jogo:</b> {stats.get('avg_goals', '?')}\n\n"
        f"O motor de IA detectou que esta liga sofreu uma mutação matemática nesta temporada:\n"
        f"📉 <b>Saiu de:</b> {old_cluster_desc}\n"
        f"📈 <b>Entrou em:</b> {new_cluster_desc}\n\n"
        f"💡 <b>Dica da IA:</b> Os robôs das casas de aposta demoram semanas para corrigir seus modelos de preço após uma mudança de cluster.\n\n"
        f"🎯 <b>Mercados com Odds Mínimas (EV+5%):</b>\n"
        + "\n".join(odds_lines) + "\n\n"
        f"<i>Foque o Scanner nestes mercados com odds >= às listadas para as próximas rodadas!</i>\n"
    )
    return message

DUTCHING_TIPS_LOG_PATH = os.path.join(DATA_DIR, 'telegram_dutching_tips_sent.json')

def get_telegram_dutching_tips():
    if os.path.exists(DUTCHING_TIPS_LOG_PATH):
        try:
            with open(DUTCHING_TIPS_LOG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_telegram_dutching_tips(tips):
    os.makedirs(os.path.dirname(DUTCHING_TIPS_LOG_PATH), exist_ok=True)
    with open(DUTCHING_TIPS_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(tips, f, indent=4, ensure_ascii=False)
    return tips

def add_telegram_dutching_tip(match_name, match_date, edge):
    tips = get_telegram_dutching_tips()
    new_tip = {
        "id": str(uuid.uuid4()),
        "match": match_name,
        "date": match_date,
        "edge": float(edge),
        "status": "Enviado",
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    tips.append(new_tip)
    save_telegram_dutching_tips(tips)
    return new_tip

def format_telegram_dutching_tip(match_name, match_date, bookmaker, market, selections, odds, dutching_odd, model_prob, edge):
    sel_lines = "\n".join([f"🔹 <b>{sel}</b>: Odd @{odds[i]:.2f}" for i, sel in enumerate(selections)])
    message = (
        f"<b>🤖 ALERTA DE DUTCHING PRO DETECTADO</b>\n\n"
        f"⚽ <b>Jogo:</b> {match_name}\n"
        f"📅 <b>Data/Hora:</b> {match_date}\n"
        f"🏦 <b>Casa Recomendada:</b> {bookmaker}\n"
        f"🧠 <b>Estratégia Recomendada:</b> {market}\n\n"
        f"📋 <b>Seleções e Odds:</b>\n"
        f"{sel_lines}\n\n"
        f"📊 <b>Métricas de Valor:</b>\n"
        f"📉 <b>Odd Combinada Dutching:</b> @{dutching_odd:.2f}\n"
        f"📈 <b>Probabilidade Real (IA):</b> {model_prob}\n"
        f"🔥 <b>Edge (+EV):</b> <b>{edge}</b>\n\n"
        f"⚠️ <i>Distribua suas stakes usando a Calculadora de Dutching do seu painel!</i>"
    )
    return message
