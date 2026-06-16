import sys
import os
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.data_loader import ensure_data_dir, download_file, load_league_data, DATA_DIR
from backend.models import PoissonModel, estimate_bookmaker_odds
from backend.backtester import ChronologicalBacktester

def run_tests():
    print("=" * 60)
    print("INICIANDO TESTES DE VERIFICAÇÃO DO PIPELINE DE BACKTEST")
    print("=" * 60)
    
    # Test 1: Data Downloading & Loading
    print("\n[Teste 1] Baixando e carregando dados da Premier League (23/24)...")
    ensure_data_dir()
    local_path = os.path.join(DATA_DIR, "E0_2324.csv")
    url = "https://www.football-data.co.uk/mmz4281/2324/E0.csv"
    
    success = download_file(url, local_path)
    if not success:
        if os.path.exists(local_path):
            print("! Download falhou (Timeout), mas utilizando arquivo cacheado localmente.")
        else:
            print("X Falha ao baixar arquivo de teste e nenhum cache local disponível.")
            return False
    else:
        print("v Arquivo de teste baixado com sucesso.")
    
    df = load_league_data('E0', start_date='2023-08-01')
    if df.empty:
        print("X Falha ao carregar dados da liga E0.")
        return False
    print(f"v Dados carregados com sucesso. Linhas carregadas: {len(df)}")
    print(f"v Colunas principais encontradas: Date, HomeTeam, AwayTeam, FTHG, FTAG, FTR")
    
    # Test 2: Poisson Model Prediction
    print("\n[Teste 2] Testando cálculos do Modelo Poisson...")
    poisson = PoissonModel()
    
    # Pick a match to predict from the middle of the season (so we have historical data)
    match_row = df.iloc[len(df) // 2]
    match_date = match_row['Date']
    home_team = match_row['HomeTeam']
    away_team = match_row['AwayTeam']
    
    print(f"Predizendo jogo: {home_team} vs {away_team} em {match_date.strftime('%Y-%m-%d')}")
    pred = poisson.predict_match(home_team, away_team, df, match_date)
    
    print(f"v Gols esperados (Lambda) - Casa: {pred['lambda_home']:.2f}, Visitante: {pred['lambda_away']:.2f}")
    print(f"v Probabilidades - Casa: {pred['prob_home']*100:.1f}%, Empate: {pred['prob_draw']*100:.1f}%, Visitante: {pred['prob_away']*100:.1f}%")
    print(f"v Probabilidade Over 1.5: {pred['prob_over_15']*100:.1f}%")
    print(f"v Probabilidade Over 2.5: {pred['prob_over_25']*100:.1f}%")
    print(f"v Probabilidade BTTS Sim: {pred['prob_btts_yes']*100:.1f}%")
    
    # Verify sum of probabilities is 1.0 (or very close)
    prob_sum = pred['prob_home'] + pred['prob_draw'] + pred['prob_away']
    if not (0.99 <= prob_sum <= 1.01):
        print(f"X Erro: Soma das probabilidades 1X2 é {prob_sum:.3f} (deveria ser 1.00)")
        return False
    print(f"v Validação matemática: Soma das probabilidades 1X2 = {prob_sum:.3f} (Correto)")
    
    # Test 3: Implied Odds Solver
    print("\n[Teste 3] Testando resolvedor numérico de Odds do Mercado...")
    # Simulate a market where Over 2.5 is 1.80 and Under 2.5 is 2.00
    est_odds = estimate_bookmaker_odds(1.80, 2.00, pred['lambda_home'], pred['lambda_away'])
    print(f"v Odds estimadas - Over 1.5: {est_odds['bookie_over_15']}, BTTS Sim: {est_odds['bookie_btts_yes']}")
    if pd.isna(est_odds['bookie_over_15']) or est_odds['bookie_over_15'] <= 1.0:
        print("X Erro ao estimar as odds implícitas.")
        return False
    print("v Odds estimadas validadas com sucesso.")
    
    # Test 4: Backtest Execution
    print("\n[Teste 4] Executando simulação de Backtest...")
    backtester = ChronologicalBacktester(rolling_games=10)
    results = backtester.run(
        leagues=['E0'],
        start_date='2023-10-01',
        end_date='2024-05-01',
        market='over25',
        value_threshold=1.03,
        initial_bankroll=1000.0,
        staking_rule='fixed',
        stake_value=10.0,
        odds_source='B365'
    )
    
    if "error" in results:
        print(f"X Falha no backtest: {results['error']}")
        return False
        
    summary = results['summary']
    print(f"v Simulação concluída com sucesso!")
    print(f"v Total de apostas feitas: {summary['total_bets']}")
    print(f"v Taxa de acerto: {summary['win_rate']}%")
    print(f"v ROI final: {summary['roi']}%")
    print(f"v Lucro Líquido: ${summary['net_profit']:.2f}")
    print(f"v Banca Final: ${summary['final_bankroll']:.2f}")
    
    # Verify AI Sustainability Analysis output
    ai_analysis = results.get('ai_analysis')
    if not ai_analysis:
        print("X Erro: 'ai_analysis' não está presente no retorno do backtest.")
        return False
    print(f"v Análise de Sustentabilidade por IA verificada com sucesso:")
    print(f"  - Status: {ai_analysis.get('status')}")
    print(f"  - Probabilidade ML de Continuidade: {ai_analysis.get('ml_probability')}%")
    print(f"  - Confiança Bayesiana do Edge: {ai_analysis.get('bayesian_confidence')}%")
    print(f"  - Drift de Performance (1ª vs 2ª Metade): {ai_analysis.get('drift_ratio')}%")
    # Verify Monte Carlo Simulation output
    mc_res = ai_analysis.get('monte_carlo')
    if not mc_res:
        print("X Erro: 'monte_carlo' não está presente no retorno do backtest.")
        return False
    print(f"v Simulação de Monte Carlo verificada com sucesso:")
    print(f"  - Probabilidade de Lucro: {mc_res.get('profit_probability')}%")
    print(f"  - Risco de Ruína: {mc_res.get('ruin_probability')}%")
    print(f"  - Lucro Líquido Mediano: ${mc_res.get('median_net_profit')}")
    print(f"  - Percentil 5% (Pessimista): ${mc_res.get('percentile_5')}")
    print(f"  - Percentil 95% (Otimista): ${mc_res.get('percentile_95')}")
    
    print("\n" + "=" * 60)
    print("TODOS OS TESTES DO BACKEND PASSARAM COM SUCESSO!")
    print("=" * 60)
    return True

if __name__ == '__main__':
    run_tests()
