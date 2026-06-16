import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.data_loader import get_all_available_leagues, load_league_data
from backend.backtester import ChronologicalBacktester

def test():
    print("Iniciando teste de Scanner de Ligas...")
    backtester = ChronologicalBacktester()
    all_leagues = get_all_available_leagues()
    
    successful_scans = 0
    errors = 0
    empty_data = 0
    
    for league in all_leagues:
        code = league['code']
        # Try loading data first
        df = load_league_data(code, start_date='2020-08-01')
        if df.empty:
            empty_data += 1
            print(f"Liga {code} ({league['name']}) - SEM DADOS")
            continue
            
        res = backtester.run(
            leagues=[code],
            start_date='2021-01-01',
            end_date='2026-06-01',
            market='away',
            value_threshold=1.05,
            initial_bankroll=1000.0,
            staking_rule='fixed',
            stake_value=10.0,
            odds_source='B365'
        )
        
        if "error" in res:
            errors += 1
            print(f"Liga {code} - ERRO: {res['error']}")
        else:
            successful_scans += 1
            summary = res['summary']
            print(f"Liga {code} ({league['name']}) - OK: Lucro={summary['net_profit']}, Apostas={summary['total_bets']}")
            
    print("\n" + "=" * 50)
    print(f"Sucessos: {successful_scans}")
    print(f"Erros: {errors}")
    print(f"Sem dados: {empty_data}")
    print("=" * 50)

if __name__ == '__main__':
    test()
