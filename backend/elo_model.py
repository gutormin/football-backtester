"""
Módulo de modelo Elo dinâmico para futebol.

Implementa um sistema de rating Elo adaptativo para times de futebol,
incluindo ajuste de vantagem do mandante e estimação do parâmetro rho
de Dixon-Coles via Máxima Verossimilhança.
"""

from __future__ import annotations

import os
import pickle
import hashlib

class EloRatingsDict(dict):
    """Pickle-serializable dict subclass that mimics defaultdict(lambda: initial_rating)"""
    def __init__(self, initial_rating: float):
        super().__init__()
        self.initial_rating = initial_rating

    def __missing__(self, key):
        self[key] = self.initial_rating
        return self.initial_rating


class EloTracker:
    """Rastreador de ratings Elo dinâmicos para times de futebol.

    Mantém e atualiza ratings Elo para cada time, considerando
    vantagem do mandante e fator K configurável.

    Attributes:
        k_factor: Fator de sensibilidade das atualizações de rating.
        home_advantage: Bônus em pontos Elo para o time mandante.
        initial_rating: Rating inicial atribuído a times desconhecidos.
        ratings: Dicionário de ratings por time.
    """

    def __init__(
        self,
        k_factor: float = 20,
        home_advantage: float = 65,
        initial_rating: float = 1500,
    ) -> None:
        """Inicializa o rastreador Elo.

        Args:
            k_factor: Fator K que controla a magnitude das atualizações.
            home_advantage: Pontos de vantagem adicionados ao mandante.
            initial_rating: Rating padrão para times sem histórico.
        """
        self.k_factor = k_factor
        self.home_advantage = home_advantage
        self.initial_rating = initial_rating
        self.ratings = EloRatingsDict(self.initial_rating)

    def get_rating(self, team: str) -> float:
        """Retorna o rating Elo atual de um time.

        Args:
            team: Nome do time.

        Returns:
            Rating Elo atual (ou initial_rating se o time for desconhecido).
        """
        return self.ratings[team]

    def expected_score(self, home_team: str, away_team: str) -> float:
        """Calcula o placar esperado (0-1) para o time mandante.

        Utiliza a fórmula Elo padrão com ajuste de vantagem do mandante:
            E = 1 / (1 + 10^((Ra - Rh - H) / 400))

        Args:
            home_team: Nome do time mandante.
            away_team: Nome do time visitante.

        Returns:
            Probabilidade esperada de vitória do mandante (entre 0 e 1).
        """
        home_rating = self.ratings[home_team]
        away_rating = self.ratings[away_team]
        exponent = (away_rating - home_rating - self.home_advantage) / 400.0
        return 1.0 / (1.0 + 10.0 ** exponent)

    def update(
        self,
        home_team: str,
        away_team: str,
        home_goals: int,
        away_goals: int,
    ) -> None:
        """Atualiza os ratings de ambos os times após uma partida.

        O resultado real é codificado como:
            - 1.0 para vitória do mandante
            - 0.5 para empate
            - 0.0 para derrota do mandante

        A variação de rating é K * (resultado_real - resultado_esperado).

        Args:
            home_team: Nome do time mandante.
            away_team: Nome do time visitante.
            home_goals: Gols marcados pelo mandante.
            away_goals: Gols marcados pelo visitante.
        """
        # Determinar resultado real
        if home_goals > away_goals:
            actual_score = 1.0
        elif home_goals == away_goals:
            actual_score = 0.5
        else:
            actual_score = 0.0

        expected = self.expected_score(home_team, away_team)
        delta = self.k_factor * (actual_score - expected)

        self.ratings[home_team] += delta
        self.ratings[away_team] -= delta

    def get_elo_factor(self, home_team: str, away_team: str) -> float:
        """Calcula o fator multiplicativo para ajuste de lambda Poisson.

        Retorna um fator baseado na diferença de Elo entre os times,
        limitado (clamped) entre 0.7 e 1.3 para evitar distorções extremas.

        Fórmula: 1 + 0.001 * (Rh - Ra)

        Args:
            home_team: Nome do time mandante.
            away_team: Nome do time visitante.

        Returns:
            Fator multiplicativo entre 0.7 e 1.3.
        """
        home_rating = self.ratings[home_team]
        away_rating = self.ratings[away_team]
        raw_factor = 1.0 + 0.001 * (home_rating - away_rating)
        return max(0.7, min(1.3, raw_factor))


def estimate_dynamic_rho(
    home_goals_list: List[int],
    away_goals_list: List[int],
    lambda_h_list: List[float],
    lambda_a_list: List[float],
) -> float:
    """Estima o parâmetro rho de Dixon-Coles via Máxima Verossimilhança.

    Utiliza as últimas 200 partidas de uma liga para estimar o rho que
    maximiza a log-verossimilhança do modelo Dixon-Coles. O rho captura
    a correlação entre gols do mandante e visitante em placares baixos
    (0-0, 1-0, 0-1, 1-1).

    Args:
        home_goals_list: Lista de gols reais marcados pelo mandante.
        away_goals_list: Lista de gols reais marcados pelo visitante.
        lambda_h_list: Lista de lambdas Poisson previstos para o mandante.
        lambda_a_list: Lista de lambdas Poisson previstos para o visitante.

    Returns:
        Valor estimado de rho (tipicamente entre -0.20 e 0.05).
        Retorna -0.085 como fallback se não houver dados suficientes
        ou se a otimização falhar.
    """
    MIN_MATCHES = 50
    WINDOW = 200
    FALLBACK_RHO = -0.085

    n = len(home_goals_list)
    if n < MIN_MATCHES:
        return FALLBACK_RHO

    # Usar apenas as últimas WINDOW partidas
    start = max(0, n - WINDOW)
    hg = home_goals_list[start:]
    ag = away_goals_list[start:]
    lh = lambda_h_list[start:]
    la = lambda_a_list[start:]

    def _tau(x: int, y: int, lam_h: float, lam_a: float, rho: float) -> float:
        """Calcula o fator de correção tau de Dixon-Coles."""
        if x == 0 and y == 0:
            return 1.0 - lam_h * lam_a * rho
        elif x == 0 and y == 1:
            return 1.0 + lam_h * rho
        elif x == 1 and y == 0:
            return 1.0 + lam_a * rho
        elif x == 1 and y == 1:
            return 1.0 - rho
        return 1.0

    def _neg_log_likelihood(rho: float) -> float:
        """Calcula a log-verossimilhança negativa (para minimização)."""
        total = 0.0
        for i in range(len(hg)):
            tau = _tau(hg[i], ag[i], lh[i], la[i], rho)
            if tau <= 0:
                return 1e12  # Penalidade para rho inválido
            total += math.log(tau)
        return -total

    try:
        from scipy.optimize import minimize_scalar

        result = minimize_scalar(
            _neg_log_likelihood,
            bounds=(-0.20, 0.05),
            method="bounded",
        )

        if result.success:
            return float(result.x)
        return FALLBACK_RHO

    except (ImportError, Exception):
        # Fallback caso scipy não esteja disponível ou otimização falhe
        return FALLBACK_RHO

import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'elo_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

def get_df_cache_key(df: pd.DataFrame) -> str:
    if df.empty:
        return "empty"
    max_date = str(df['Date'].max())
    first_home = str(df['HomeTeam'].iloc[0]) if 'HomeTeam' in df.columns else ""
    raw_key = f"{len(df)}_{max_date}_{first_home}"
    return hashlib.md5(raw_key.encode('utf-8')).hexdigest()

def build_elo_tracker_from_history(df: pd.DataFrame) -> EloTracker:
    """Constrói e cálcula o estado final do Elo Tracker a partir de uma base histórica.

    Processa todos os jogos na base fornecida em ordem cronológica.
    Utiliza cache em disco para evitar reprocessamentos repetitivos de ligas estáticas.

    Args:
        df: DataFrame contendo o histórico de partidas ('Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG').

    Returns:
        Um objeto EloTracker com as pontuações atualizadas.
    """
    if df.empty or 'FTHG' not in df.columns or 'FTAG' not in df.columns:
        return EloTracker(k_factor=20, home_advantage=65)
        
    cache_key = get_df_cache_key(df)
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.pkl")
    
    # Try reading cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                tracker = pickle.load(f)
                return tracker
        except Exception:
            pass # fallback to rebuild if pickling fails
            
    tracker = EloTracker(k_factor=20, home_advantage=65)
    try:
        # Tenta ordenar. Assumindo que Date já pode ser datetime ou string.
        # Se 'Time' estiver disponível, deveríamos ordenar também por Time, mas Date basta para Elo diário.
        sort_cols = ['Date', 'Time'] if 'Time' in df.columns else ['Date']
        df_sorted = df.dropna(subset=['FTHG', 'FTAG']).sort_values(by=sort_cols)
    except Exception:
        df_sorted = df.dropna(subset=['FTHG', 'FTAG'])
        
    for _, row in df_sorted.iterrows():
        try:
            tracker.update(row['HomeTeam'], row['AwayTeam'], int(row['FTHG']), int(row['FTAG']))
        except ValueError:
            continue
            
    # Try saving to cache
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(tracker, f)
    except Exception:
        pass
            
    return tracker

