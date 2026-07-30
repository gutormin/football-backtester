"""
Triagem Ancorada de Dutching.

Diferente do scanner tradicional (que INVENTA odds de Correct Score a partir
do Over/Under), este módulo NÃO estima odds de CS para calcular edge. Em vez
disso, ranqueia os jogos futuros por sinais REAIS e confiáveis:

  1. Divergência modelo × mercado real (1X2 e Over/Under que a casa realmente
     oferece): o modelo Poisson discorda da casa sobre número de gols / favorito?
  2. Concentração de probabilidade: os placares prováveis estão concentrados em
     poucos (viável para dutching) ou espalhados (inviável)?
  3. Confiança do modelo: o jogo é previsível o suficiente?

O resultado é um RANKING de jogos "que valem a pena investigar". O usuário
então digita as odds REAIS de CS apenas nos finalistas, e o sistema recalcula
todas as métricas de verdade (edge, quality, lucro, alocação).

Fornece também uma PRÉVIA com odds estimadas (claramente marcadas como
estimativa) para o usuário ter uma referência inicial.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)


def _concentration_score(score_probs, top_n=4):
    """
    Mede quão concentrada está a probabilidade nos placares mais prováveis.
    Retorna a soma de probabilidade dos top_n placares (0 a 1).
    Alta concentração = bom para dutching (poucos placares cobrem muito).
    """
    if not score_probs:
        return 0.0
    sorted_probs = sorted(score_probs.values(), reverse=True)
    return float(sum(sorted_probs[:top_n]))


def _model_confidence(pred):
    """
    Confiança do modelo no jogo (0 a 1).
    Jogos com favorito claro OU perfil de gols bem definido são mais previsíveis.
    """
    lambda_home = pred.get('lambda_home', 1.2)
    lambda_away = pred.get('lambda_away', 1.0)
    lambda_total = lambda_home + lambda_away

    # Dominância: quão claro é o favorito
    dominance = abs(lambda_home - lambda_away) / max(lambda_total, 1.0)

    # Definição de gols: quão longe da média (jogos claramente over ou under)
    goal_clarity = min(1.0, abs(lambda_total - 2.6) / 1.5)

    # Combina os dois sinais
    return float(min(1.0, dominance * 0.6 + goal_clarity * 0.4))


def compute_anchored_score(pred, market_ou_odds=None, market_1x2_odds=None,
                           score_probs=None, league_code=None):
    """
    Calcula o score de oportunidade ANCORADO em mercados reais.

    Args:
        pred: dict do modelo (lambda_home, lambda_away, prob_h, prob_d, prob_a, etc.)
        market_ou_odds: (over_odd, under_odd) REAIS da casa, ou None
        market_1x2_odds: (home_odd, draw_odd, away_odd) REAIS da casa, ou None
        score_probs: dict {"1-0": prob, ...} do modelo
        league_code: código da liga

    Returns:
        dict com score (0-100), componentes e explicação.
    """
    from .dutching_scanner import _solve_lambda_from_under25_fast, _get_league_avg_goals

    lambda_home = pred.get('lambda_home', 1.2)
    lambda_away = pred.get('lambda_away', 1.0)
    lambda_total = lambda_home + lambda_away

    # ── 1. Divergência modelo × mercado Over/Under (real) ──
    ou_divergence = 0.0
    ou_divergence_pct = 0.0
    if market_ou_odds:
        over_odd, under_odd = market_ou_odds
        if over_odd and under_odd and over_odd > 1.01 and under_odd > 1.01:
            imp_over = 1.0 / over_odd
            imp_under = 1.0 / under_odd
            fair_under = imp_under / (imp_over + imp_under)
            if 0.01 < fair_under < 0.99:
                mkt_lambda = _solve_lambda_from_under25_fast(fair_under)
                if mkt_lambda > 0:
                    ou_divergence = lambda_total - mkt_lambda
                    ou_divergence_pct = (ou_divergence / mkt_lambda) * 100 if mkt_lambda > 0 else 0

    # ── 2. Divergência modelo × mercado 1X2 (real) ──
    x2_divergence = 0.0
    if market_1x2_odds:
        h_odd, d_odd, a_odd = market_1x2_odds
        if all(o and o > 1.01 for o in [h_odd, d_odd, a_odd]):
            imp_h, imp_d, imp_a = 1.0/h_odd, 1.0/d_odd, 1.0/a_odd
            total_imp = imp_h + imp_d + imp_a
            fair_h = imp_h / total_imp
            fair_d = imp_d / total_imp
            fair_a = imp_a / total_imp
            model_h = pred.get('prob_h', 0.37)
            model_d = pred.get('prob_d', 0.26)
            model_a = pred.get('prob_a', 0.37)
            # Maior divergência absoluta entre modelo e mercado nos 3 resultados
            x2_divergence = max(abs(model_h - fair_h), abs(model_d - fair_d), abs(model_a - fair_a))

    # ── 3. Concentração de probabilidade ──
    concentration = _concentration_score(score_probs, top_n=4) if score_probs else 0.0

    # ── 4. Confiança do modelo ──
    confidence = _model_confidence(pred)

    # ── Score final (0-100) ──
    # Divergência O/U: normalizada (0.5 gol de divergência = forte sinal)
    ou_signal = min(1.0, abs(ou_divergence) / 0.5)
    # Divergência 1X2: 10% de divergência = forte sinal
    x2_signal = min(1.0, x2_divergence / 0.10)
    # Divergência combinada (o maior dos dois sinais de mercado)
    market_signal = max(ou_signal, x2_signal)

    # Concentração: 45% nos top 4 já é bom
    conc_signal = min(1.0, concentration / 0.45)

    # Pesos: mercado é o sinal mais importante (é real), depois concentração, depois confiança
    score = (
        market_signal * 45 +      # divergência contra a casa (real) = 45 pts
        conc_signal * 30 +        # viabilidade do dutching = 30 pts
        confidence * 25           # previsibilidade do jogo = 25 pts
    )
    score = round(min(100, max(0, score)), 1)

    # ── Explicação legível ──
    reasons = []
    if abs(ou_divergence) > 0.25:
        direction = "mais gols" if ou_divergence > 0 else "menos gols"
        reasons.append(f"Modelo espera {direction} que o mercado ({ou_divergence:+.2f} gols)")
    if x2_divergence > 0.06:
        reasons.append(f"Modelo diverge do 1X2 da casa ({x2_divergence*100:.0f}%)")
    if concentration > 0.40:
        reasons.append(f"Placares concentrados ({concentration*100:.0f}% nos top 4)")
    if confidence > 0.5:
        reasons.append("Jogo previsível")
    if not reasons:
        reasons.append("Sinais fracos — baixa prioridade")

    return {
        'anchored_score': score,
        'components': {
            'market_divergence': round(market_signal * 45, 1),
            'concentration': round(conc_signal * 30, 1),
            'confidence': round(confidence * 25, 1),
        },
        'ou_divergence': round(ou_divergence, 3),
        'x2_divergence': round(x2_divergence, 3),
        'concentration': round(concentration, 3),
        'model_confidence': round(confidence, 3),
        'reasons': reasons,
        'has_real_ou': market_ou_odds is not None,
        'has_real_1x2': market_1x2_odds is not None,
    }
