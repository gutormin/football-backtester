import asyncio
import sys

# Import functions from our backend
from backend.telegram_bot import (
    send_telegram_message,
    format_pure_blood_tip,
    format_contrarian_tip,
    format_dna_shift_alert
)

def run_test():
    print("Iniciando Teste de Alertas IA no Telegram...")

    # 1. Teste Puro Sangue
    msg1 = format_pure_blood_tip(
        league_name="Italy Serie B",
        match_name="Palermo vs Brescia",
        match_date="Hoje",
        time_str="15:00",
        market_label="Under 2.5",
        prob=65.5,
        ev_pct=12.4,
        cluster_desc="Ligas Truncadas (Under)",
        avg_goals=2.15
    )
    ok1, res1 = send_telegram_message(msg1)
    print(f"Alerta Puro Sangue: {'Sucesso' if ok1 else 'Falha - ' + res1}")

    # 2. Teste Contrarian
    msg2 = format_contrarian_tip(
        league_name="Germany Bundesliga",
        match_name="Bayern Munich vs Dortmund",
        match_date="Hoje",
        time_str="10:30",
        market_label="Over 2.5",
        bookie_odd=2.10,
        cluster_desc="Ligas de Gols (Over)",
        recommended_action="Apostar no Over 2.5 (A casa está subestimando o ataque da liga e oferecendo uma odd alta num campeonato historicamente over)"
    )
    ok2, res2 = send_telegram_message(msg2)
    print(f"Alerta Contrarian: {'Sucesso' if ok2 else 'Falha - ' + res2}")

    # 3. Teste DNA Shift
    msg3 = format_dna_shift_alert(
        league_name="Portugal Primeira Liga",
        old_cluster_desc="Ligas Equilibradas",
        new_cluster_desc="Ligas Truncadas (Under)",
        recommended_markets="Under 2.5, Under 0.5 HT, Empate HT"
    )
    ok3, res3 = send_telegram_message(msg3)
    print(f"Alerta DNA Shift: {'Sucesso' if ok3 else 'Falha - ' + res3}")

if __name__ == "__main__":
    run_test()
