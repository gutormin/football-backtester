"""
Backtest de Sugestões Reais do Dutching.

Diferente do dutching_backtester.py (que roda o modelo em dados históricos),
este módulo pega as sugestões que o sistema REALMENTE enviou (salvas em
telegram_dutching_tips_sent.json) e calcula o lucro/prejuízo que teria sido
obtido se o usuário tivesse apostado nelas.

Fluxo:
1. Lê o histórico de tips enviadas
2. Filtra por período
3. Para cada tip, busca o resultado real do jogo
4. Calcula lucro/prejuízo do dutching (stake fixa e Kelly)
"""

import os
import json
import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')
DUTCHING_TIPS_LOG_PATH = os.path.join(DATA_DIR, 'telegram_dutching_tips_sent.json')


def _load_tips():
    """Carrega o histórico de sugestões enviadas."""
    if os.path.exists(DUTCHING_TIPS_LOG_PATH):
        try:
            with open(DUTCHING_TIPS_LOG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao carregar tips: {e}")
    return []


def _parse_tip_date(date_str):
    """Converte a data da tip (formatos variados) para datetime."""
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _find_actual_score(tip, results_cache):
    """
    Busca o placar real do jogo sugerido.
    Primeiro tenta o campo salvo na tip; senão procura nos CSVs históricos.
    """
    # Se já foi checado e salvo
    if tip.get('actual_score'):
        return tip['actual_score']

    home = tip.get('home_team') or ''
    match = tip.get('match') or ''

    # Extrair times do nome do match "Team A vs Team B"
    teams = []
    for sep in (' vs ', ' x ', ' - ', ' v '):
        if sep in match:
            teams = [t.strip() for t in match.split(sep)]
            break

    if len(teams) < 2:
        return None

    home_team, away_team = teams[0], teams[1]
    tip_dt = _parse_tip_date(tip.get('date'))
    if not tip_dt:
        return None

    # Procurar nos CSVs de resultados (cache por liga)
    # Busca simples por nome de time e data aproximada
    for df in results_cache.values():
        if df is None or df.empty:
            continue
        try:
            mask = (
                df['HomeTeam'].str.contains(home_team[:8], case=False, na=False, regex=False) &
                df['AwayTeam'].str.contains(away_team[:8], case=False, na=False, regex=False)
            )
            matches = df[mask]
            if not matches.empty:
                row = matches.iloc[0]
                if pd.notna(row.get('FTHG')) and pd.notna(row.get('FTAG')):
                    return f"{int(row['FTHG'])}-{int(row['FTAG'])}"
        except Exception:
            continue

    return None


def _load_results_cache(leagues=None):
    """Carrega CSVs de resultados para lookup de placares."""
    from ..data_loader import load_league_data, get_all_available_leagues

    cache = {}
    try:
        available = get_all_available_leagues('footballdata')
        codes = [l['code'] for l in available]
    except Exception:
        codes = ['E0', 'SP1', 'I1', 'D1', 'F1']

    for code in codes[:30]:  # limitar para não estourar memória
        try:
            df = load_league_data(code, start_date='2024-08-01', data_source='footballdata')
            if not df.empty:
                cache[code] = df
        except Exception:
            continue

    return cache


def _calc_dutching_profit(selections, odds, actual_score, stake):
    """
    Calcula o lucro/prejuízo de um dutching.
    Retorna (profit, covered).
    """
    if not selections or not odds or len(selections) != len(odds):
        return 0.0, False

    covered = actual_score in selections
    overround = sum(1.0 / o for o in odds if o > 1.0)
    if overround <= 0:
        return 0.0, False

    if covered:
        idx = selections.index(actual_score)
        winning_odd = odds[idx]
        stake_on_winner = stake * (1.0 / winning_odd) / overround
        profit = stake_on_winner * winning_odd - stake
    else:
        profit = -stake

    return round(profit, 2), covered


def parse_telegram_tip(text):
    """
    Extrai os dados de uma mensagem de sugestão de Dutching colada do Telegram.

    Formato esperado:
        🤖 ALERTA DE DUTCHING PRO DETECTADO
        ⚽ Jogo: Arsenal vs Chelsea
        📅 Data/Hora: 20/07/2026 16:00
        🏦 Casa Recomendada: Bet365
        🧠 Estratégia Recomendada: Under / Jogo Truncado
        📋 Seleções e Odds:
        🔹 1-0: Odd @9.00
        🔹 0-0: Odd @11.00
        📉 Odd Combinada Dutching: @3.50
    """
    import re

    if not text or not text.strip():
        return None

    result = {
        'match': None, 'date': None, 'bookmaker': None, 'market': None,
        'selections': [], 'odds': [], 'dutching_odd': None, 'model_prob': None,
        'edge': 0.0, 'home_team': None, 'league': None,
    }

    # Jogo
    m = re.search(r'Jogo:\s*(.+?)(?:\n|$)', text)
    if m:
        result['match'] = m.group(1).strip()
        for sep in (' vs ', ' x ', ' - ', ' v '):
            if sep in result['match']:
                result['home_team'] = result['match'].split(sep)[0].strip()
                break

    # Data/Hora
    m = re.search(r'Data/Hora:\s*(.+?)(?:\n|$)', text)
    if m:
        result['date'] = m.group(1).strip()

    # Casa
    m = re.search(r'Casa Recomendada:\s*(.+?)(?:\n|$)', text)
    if m:
        result['bookmaker'] = m.group(1).strip()

    # Estratégia/Mercado
    m = re.search(r'Estratégia Recomendada:\s*(.+?)(?:\n|$)', text)
    if m:
        result['market'] = m.group(1).strip()

    # Seleções e odds: "🔹 1-0: Odd @9.00" ou "1-0: @9.00"
    sel_pattern = re.findall(r'(\d+[-x]\d+)\s*:?\s*(?:Odd\s*)?@?\s*(\d+\.?\d*)', text)
    for score, odd in sel_pattern:
        score_norm = score.replace('x', '-')
        # Não confundir com "Odd Combinada"
        result['selections'].append(score_norm)
        result['odds'].append(float(odd))

    # Odd combinada
    m = re.search(r'Odd Combinada\s*(?:Dutching)?:\s*@?\s*(\d+\.?\d*)', text)
    if m:
        result['dutching_odd'] = float(m.group(1))

    # Probabilidade IA
    m = re.search(r'Probabilidade\s*(?:Real)?\s*\(?IA\)?:\s*(.+?)(?:\n|$)', text)
    if m:
        result['model_prob'] = m.group(1).strip()

    # Edge
    m = re.search(r'Edge\s*\(?\+?EV\)?:\s*\+?(\d+\.?\d*)\s*%?', text)
    if m:
        result['edge'] = float(m.group(1)) / 100.0

    # Precisa ter pelo menos jogo, data e seleções
    if not result['match'] or not result['date'] or not result['selections']:
        return None

    return result


def run_tips_backtest(start_date=None, end_date=None, initial_bankroll=1000.0,
                      stake_value=50.0, staking_rule='fixed'):
    """
    Roda o backtest sobre as sugestões reais enviadas.

    Args:
        start_date, end_date: filtro de período (YYYY-MM-DD ou None)
        initial_bankroll: banca inicial
        stake_value: stake fixa por aposta
        staking_rule: 'fixed' ou 'kelly_quarter'

    Returns:
        dict com summary, bets, equity_curve
    """
    tips = _load_tips()
    if not tips:
        return {"error": "Nenhuma sugestão encontrada no histórico. O sistema precisa ter enviado tips primeiro."}

    # Filtrar por período
    start_dt = pd.to_datetime(start_date) if start_date else None
    end_dt = pd.to_datetime(end_date) if end_date else None

    filtered = []
    for tip in tips:
        tip_dt = _parse_tip_date(tip.get('date'))
        if not tip_dt:
            continue
        if start_dt and tip_dt < start_dt:
            continue
        if end_dt and tip_dt > end_dt:
            continue
        filtered.append(tip)

    if not filtered:
        return {"error": f"Nenhuma sugestão no período selecionado ({start_date} a {end_date})."}

    # Ordenar cronologicamente
    filtered.sort(key=lambda t: _parse_tip_date(t.get('date')) or datetime.min)

    # Carregar resultados
    results_cache = _load_results_cache()

    # Processar cada tip
    bankroll = initial_bankroll
    bets = []
    equity_curve = [initial_bankroll]
    total_staked = 0.0
    wins = 0
    resolved = 0
    unresolved = 0

    for tip in filtered:
        selections = tip.get('selections') or []
        odds = tip.get('odds') or []

        # Sem seleções salvas — não dá para calcular (tips antigas)
        if not selections or not odds:
            unresolved += 1
            bets.append({
                'date': tip.get('date'),
                'match': tip.get('match'),
                'home_team': tip.get('home_team') or tip.get('match', '').split(' vs ')[0],
                'away_team': tip.get('match', '').split(' vs ')[-1] if ' vs ' in tip.get('match', '') else '',
                'league': tip.get('league') or '—',
                'selections': selections,
                'edge': tip.get('edge'),
                'actual_score': '—',
                'total_stake': 0,
                'profit': 0,
                'bankroll': round(bankroll, 2),
                'status': 'sem_dados',
                'won': None,
            })
            continue

        # Buscar placar real
        actual_score = _find_actual_score(tip, results_cache)
        if not actual_score:
            unresolved += 1
            bets.append({
                'date': tip.get('date'),
                'match': tip.get('match'),
                'home_team': tip.get('home_team') or tip.get('match', '').split(' vs ')[0],
                'away_team': tip.get('match', '').split(' vs ')[-1] if ' vs ' in tip.get('match', '') else '',
                'league': tip.get('league') or '—',
                'selections': selections,
                'edge': tip.get('edge'),
                'actual_score': 'pendente',
                'total_stake': 0,
                'profit': 0,
                'bankroll': round(bankroll, 2),
                'status': 'pendente',
                'won': None,
            })
            continue

        # Calcular stake
        if staking_rule == 'kelly_quarter':
            dutching_odd = tip.get('dutching_odd') or 0
            edge_val = (tip.get('edge') or 0)
            if isinstance(edge_val, str):
                edge_val = float(edge_val.replace('%', '').replace('+', '').strip() or 0) / 100.0
            if dutching_odd and dutching_odd > 1.01:
                kelly = edge_val / (dutching_odd - 1.0)
                stake = bankroll * kelly * 0.25
                stake = max(5.0, min(stake, bankroll * 0.05))
            else:
                stake = stake_value
        else:
            stake = stake_value

        stake = min(stake, bankroll)
        if stake <= 0:
            continue

        profit, covered = _calc_dutching_profit(selections, odds, actual_score, stake)
        bankroll += profit
        total_staked += stake
        resolved += 1
        if covered:
            wins += 1

        home = tip.get('home_team') or (tip.get('match', '').split(' vs ')[0] if ' vs ' in tip.get('match', '') else tip.get('match', ''))
        away = tip.get('match', '').split(' vs ')[-1] if ' vs ' in tip.get('match', '') else ''

        bets.append({
            'date': tip.get('date'),
            'match': tip.get('match'),
            'home_team': home,
            'away_team': away,
            'league': tip.get('league') or '—',
            'selections': selections,
            'odds': odds,
            'edge': tip.get('edge'),
            'market': tip.get('market'),
            'bookmaker': tip.get('bookmaker'),
            'actual_score': actual_score,
            'total_stake': round(stake, 2),
            'profit': profit,
            'bankroll': round(bankroll, 2),
            'status': 'resolvido',
            'won': covered,
            'covered': covered,
        })
        equity_curve.append(round(bankroll, 2))

    net_profit = bankroll - initial_bankroll
    roi = (net_profit / total_staked * 100) if total_staked > 0 else 0
    win_rate = (wins / resolved * 100) if resolved > 0 else 0

    return {
        'status': 'success',
        'summary': {
            'total_tips': len(filtered),
            'resolved': resolved,
            'unresolved': unresolved,
            'total_bets': resolved,
            'total_wins': wins,
            'win_rate': round(win_rate, 1),
            'net_profit': round(net_profit, 2),
            'roi': round(roi, 1),
            'total_staked': round(total_staked, 2),
            'initial_bankroll': initial_bankroll,
            'final_bankroll': round(bankroll, 2),
        },
        'bets': bets,
        'equity_curve': equity_curve,
    }
