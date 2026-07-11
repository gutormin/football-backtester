import asyncio
import os
import json
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

from .data_loader import DATA_DIR, load_upcoming_from_api, get_api_token, get_all_available_leagues, load_league_data, auto_detect_data_source
from .ml_clustering import extract_league_features, cluster_leagues
from .telegram_bot import (
    send_telegram_message, 
    format_pure_blood_tip, 
    format_contrarian_tip, 
    format_dna_shift_alert
)

CONFIG_PATH = os.path.join(DATA_DIR, 'cluster_ai_config.json')
HISTORY_PATH = os.path.join(DATA_DIR, 'cluster_history.json')
SENT_ALERTS_PATH = os.path.join(DATA_DIR, 'telegram_cluster_alerts_sent.json')

def get_cluster_ai_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        "enabled": True,
        "pure_blood_enabled": True,
        "contrarian_enabled": True,
        "dna_shift_enabled": True
    }

def save_cluster_ai_config(config):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)

def get_sent_alerts():
    if os.path.exists(SENT_ALERTS_PATH):
        try:
            with open(SENT_ALERTS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []

def save_sent_alert(alert_key):
    alerts = get_sent_alerts()
    if alert_key not in alerts:
        alerts.append(alert_key)
        with open(SENT_ALERTS_PATH, 'w', encoding='utf-8') as f:
            json.dump(alerts, f)

def get_cluster_profile(c):
    if c['avg_goals'] >= 2.75 or c['over25_pct'] >= 0.52:
        return "Ligas de Gols (Over)"
    elif c['avg_goals'] <= 2.55 or c['over25_pct'] <= 0.46:
        return "Ligas Truncadas (Under)"
    return "Ligas Equilibradas"

def get_suggested_markets(profile, c):
    markets = []
    if profile == "Ligas de Gols (Over)":
        markets = ["Over 2.5", "BTTS Yes", "Over 0.5 HT"]
    elif profile == "Ligas Truncadas (Under)":
        markets = ["Under 2.5", "Under 0.5 HT", "Empate HT"]
    else:
        markets = ["Match Odds", "Handicap"]
        
    if c['home_win_pct'] >= 0.47:
        markets.append("Back Home")
    elif c['home_win_pct'] <= 0.38:
        markets.append("Lay Home")
    return markets

async def run_cluster_ai_alerts():
    config = get_cluster_ai_config()
    diag = {"enabled": config.get("enabled"), "clusters": 0, "dna_shifts": 0, "pure_blood": 0, "contrarian": 0, "errors": []}

    if not config.get("enabled"):
        diag["errors"].append("Cluster AI alerts disabled in config")
        return diag

    logger.info("Iniciando varredura...")

    # 1. Obter todos os clusters atuais
    all_leagues = get_all_available_leagues()
    league_codes = [l['code'] for l in all_leagues]
    code_to_name = {l['code']: l['name'] for l in all_leagues}
    diag["leagues_total"] = len(league_codes)

    features_list = []
    for lg in league_codes:
        try:
            df = load_league_data(lg, start_date="2021-01-01", data_source=auto_detect_data_source(lg), api_key="")
            feat = extract_league_features(lg, df)
            if feat:
                features_list.append(feat)
        except Exception as e:
            diag["errors"].append(f"Erro ao carregar {lg}: {e}")

    diag["leagues_with_features"] = len(features_list)

    if len(features_list) < 3:
        diag["errors"].append(f"Apenas {len(features_list)} ligas com dados. Preciso de >= 3.")
        return diag

    clusters = cluster_leagues(features_list, n_clusters=3)
    if 'error' in clusters:
        diag["errors"].append(f"Erro na clusterizacao: {clusters['error']}")
        return diag

    diag["clusters"] = len(clusters.get("clusters", []))

    # Mapear ligas para clusters
    league_to_cluster = {}
    for c in clusters.get('clusters', []):
        profile = get_cluster_profile(c)
        for lg in c['leagues']:
            league_to_cluster[lg] = {
                'profile': profile,
                'avg_goals': c['avg_goals'],
                'over25_pct': c.get('over25_pct', 0.5),
                'btts_pct': c.get('btts_pct', 0.5),
                'home_win_pct': c.get('home_win_pct', 0.4),
                'draw_pct': c.get('draw_pct', 0.28),
                'markets': get_suggested_markets(profile, c),
                'desc': f"Grupo {c['cluster_id']+1} - {profile}"
            }

    # Checar DNA Shift
    if config.get("dna_shift_enabled"):
        if os.path.exists(HISTORY_PATH):
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                history = json.load(f)

            for lg, current_data in league_to_cluster.items():
                old_data = history.get(lg)
                if old_data and old_data['profile'] != current_data['profile']:
                    alert_key = f"dna_shift_{lg}_{datetime.now().strftime('%Y-%W')}"
                    if alert_key not in get_sent_alerts():
                        league_display = code_to_name.get(lg, lg)
                        msg = format_dna_shift_alert(
                            league_display,
                            old_data['profile'],
                            current_data['profile'],
                            current_data['markets'],
                            current_data
                        )
                        ok, resp = send_telegram_message(msg)
                        diag["dna_shifts"] += 1
                        if not ok:
                            diag["errors"].append(f"Falha ao enviar DNA shift {lg}: {resp}")
                        else:
                            save_sent_alert(alert_key)

        with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(league_to_cluster, f, indent=4)

    # Checar Pure Blood e Contrarian usando Autopilot
    if config.get("pure_blood_enabled") or config.get("contrarian_enabled"):
        from .api.router_scanner import get_autopilot_predictions
        auto_matches = get_autopilot_predictions("api")
        if isinstance(auto_matches, dict) and auto_matches.get("status") == "error":
            diag["errors"].append(f"Erro ao buscar predicoes: {auto_matches.get('message')}")
        elif not isinstance(auto_matches, list):
            diag["errors"].append(f"get_autopilot_predictions retornou tipo inesperado: {type(auto_matches)}")
        else:
            diag["autopilot_matches"] = len(auto_matches)

            for m in auto_matches:
                if not isinstance(m, dict): continue
                lg = m.get('league_name', '')
                if lg not in league_to_cluster:
                    continue

                c_data = league_to_cluster[lg]
                market = m['market_label']
                ev = m['ev']
                prob = m['prob']
                bookie_odd = m['bookie_odds']

                match_key = f"{m['home_team']}_vs_{m['away_team']}_{m['date']}"

                # Pure Blood
                if config.get("pure_blood_enabled") and ev >= 5.0:
                    # Checa se o mercado bate com o cluster
                    is_pure_blood = False
                    if c_data['profile'] == "Ligas de Gols (Over)" and "Over" in market:
                        is_pure_blood = True
                    elif c_data['profile'] == "Ligas Truncadas (Under)" and "Under" in market:
                        is_pure_blood = True

                    if is_pure_blood:
                        alert_key = f"pure_blood_{match_key}_{market}"
                        if alert_key not in get_sent_alerts():
                            league_display = code_to_name.get(lg, lg)
                            msg = format_pure_blood_tip(
                                league_display, match_key.replace('_vs_', ' vs '), m['date'], m['time'],
                                market, prob, ev, c_data['desc'], c_data['avg_goals']
                            )
                            ok, resp = send_telegram_message(msg)
                            diag["pure_blood"] += 1
                            if not ok:
                                diag["errors"].append(f"Falha ao enviar Pure Blood: {resp}")
                            else:
                                save_sent_alert(alert_key)

                # Contrarian (Anomalia)
                if config.get("contrarian_enabled"):
                    # Se odd do Under 2.5 > 2.00 mas a liga é Under
                    is_anomaly = False
                    action = ""
                    if c_data['profile'] == "Ligas Truncadas (Under)" and "Under 2.5" in market and bookie_odd >= 2.00:
                        is_anomaly = True
                        action = "Apostar no Under 2.5 (A casa está subestimando a defesa da liga)"
                    elif c_data['profile'] == "Ligas de Gols (Over)" and "Over 2.5" in market and bookie_odd >= 2.00:
                        is_anomaly = True
                        action = "Apostar no Over 2.5 (A casa está subestimando o ataque da liga)"

                    if is_anomaly:
                        alert_key = f"contrarian_{match_key}_{market}"
                        if alert_key not in get_sent_alerts():
                            league_display = code_to_name.get(lg, lg)
                            msg = format_contrarian_tip(
                                league_display, match_key.replace('_vs_', ' vs '), m['date'], m['time'],
                                market, bookie_odd, c_data['desc'], action
                            )
                            ok, resp = send_telegram_message(msg)
                            diag["contrarian"] += 1
                            if not ok:
                                diag["errors"].append(f"Falha ao enviar Contrarian: {resp}")
                            else:
                                save_sent_alert(alert_key)

    diag["sent_alerts_count"] = len(get_sent_alerts())
    logger.info("Varredura concluída.")
    return diag

async def run_cluster_ai_alerts_loop():
    while True:
        try:
            await run_cluster_ai_alerts()
        except Exception as e:
            logger.error(f"Loop Error: {e}", exc_info=True)
        await asyncio.sleep(3600) # 1 hour
