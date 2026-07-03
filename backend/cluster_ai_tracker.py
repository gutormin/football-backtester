import asyncio
import os
import json
import pandas as pd
from datetime import datetime

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
    if not config.get("enabled"):
        return
        
    print("[Cluster AI] Iniciando varredura...")
    
    # 1. Obter todos os clusters atuais
    all_leagues = get_all_available_leagues()
    league_codes = [l['code'] for l in all_leagues]
    
    features_list = []
    for lg in league_codes:
        df = load_league_data(lg, start_date="2021-01-01", data_source=auto_detect_data_source(lg), api_key="")
        feat = extract_league_features(lg, df)
        if feat:
            features_list.append(feat)
            
    if len(features_list) < 3:
        return
        
    clusters = cluster_leagues(features_list, n_clusters=3)
    if 'error' in clusters:
        print(f"[Cluster AI] Erro na clusterização: {clusters['error']}")
        return
        
    # Mapear ligas para clusters
    league_to_cluster = {}
    for c in clusters.get('clusters', []):
        profile = get_cluster_profile(c)
        for lg in c['leagues']:
            league_to_cluster[lg] = {
                'profile': profile,
                'avg_goals': c['avg_goals'],
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
                        msg = format_dna_shift_alert(
                            lg, 
                            old_data['profile'], 
                            current_data['profile'], 
                            ", ".join(current_data['markets'])
                        )
                        send_telegram_message(msg)
                        save_sent_alert(alert_key)
                        
        with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(league_to_cluster, f, indent=4)
            
    # Checar Pure Blood e Contrarian usando Autopilot
    if config.get("pure_blood_enabled") or config.get("contrarian_enabled"):
        from .api.router_scanner import get_autopilot_predictions
        auto_matches = get_autopilot_predictions("api")
        if isinstance(auto_matches, dict) and auto_matches.get("status") == "error":
            print(f"[Cluster AI] Erro ao buscar predições: {auto_matches.get('message')}")
            return
            
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
                        msg = format_pure_blood_tip(
                            lg, match_key.replace('_vs_', ' vs '), m['date'], m['time'], 
                            market, prob, ev, c_data['desc'], c_data['avg_goals']
                        )
                        send_telegram_message(msg)
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
                        msg = format_contrarian_tip(
                            lg, match_key.replace('_vs_', ' vs '), m['date'], m['time'],
                            market, bookie_odd, c_data['desc'], action
                        )
                        send_telegram_message(msg)
                        save_sent_alert(alert_key)
                        
    print("[Cluster AI] Varredura concluída.")

async def run_cluster_ai_alerts_loop():
    while True:
        try:
            await run_cluster_ai_alerts()
        except Exception as e:
            print(f"[Cluster AI Loop Error] {e}")
        await asyncio.sleep(3600) # 1 hour
