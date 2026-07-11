"""
Corners model validation: Poisson-based predictions vs actual outcomes.

Tests the compute_corners_probs() model from helpers.py against historical data
with HC (Home Corners) and AC (Away Corners) columns across all leagues.

Metrics computed:
- Brier score (model vs naive baseline)
- Calibration by probability bucket
- Win rate by market
- Over/Under accuracy at standard lines (7.5, 8.5, 9.5, 10.5, 11.5)
"""
from __future__ import annotations

import os
import sys
import glob
import math
import json
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.backtest.helpers import compute_corners_probs
from backend.data_loader import read_csv_robust, DATA_DIR


def load_all_corners_data():
    """Load all CSV files with HC/AC columns. Returns combined DataFrame."""
    frames = []
    total_corners_matches = 0

    for csv_path in glob.glob(os.path.join(DATA_DIR, '*.csv')):
        fname = os.path.basename(csv_path)
        if fname == 'fixtures.csv':
            continue

        try:
            df = read_csv_robust(csv_path)
        except Exception:
            continue

        if df.empty or 'HC' not in df.columns or 'AC' not in df.columns:
            continue

        # Keep only rows with valid corners data
        valid = df.dropna(subset=['HC', 'AC'])
        if valid.empty:
            continue

        valid = valid.copy()
        valid['HC'] = pd.to_numeric(valid['HC'], errors='coerce')
        valid['AC'] = pd.to_numeric(valid['AC'], errors='coerce')
        valid = valid.dropna(subset=['HC', 'AC'])
        valid['HC'] = valid['HC'].astype(int)
        valid['AC'] = valid['AC'].astype(int)

        # Extract league code from filename
        valid['_league_code'] = fname.replace('.csv', '')

        if 'Date' in valid.columns:
            valid['Date'] = pd.to_datetime(valid['Date'], errors='coerce')

        frames.append(valid)
        total_corners_matches += len(valid)

    if not frames:
        return pd.DataFrame(), 0

    combined = pd.concat(frames, ignore_index=True)
    return combined, total_corners_matches


def evaluate_corners_1x2(df, predictions):
    """
    Evaluate corners 1X2 predictions.
    Returns dict with Brier score, accuracy, and calibration buckets.
    """
    outcomes = []
    probs_1 = []
    probs_x = []
    probs_2 = []

    for pred in predictions:
        hc = pred['hc']
        ac = pred['ac']
        p1 = pred['corners_1']
        px = pred['corners_x']
        p2 = pred['corners_2']

        if hc > ac:
            outcomes.append((1, 0, 0))
        elif hc == ac:
            outcomes.append((0, 1, 0))
        else:
            outcomes.append((0, 0, 1))

        probs_1.append(p1)
        probs_x.append(px)
        probs_2.append(p2)

    n = len(outcomes)
    if n == 0:
        return {'brier_score': None, 'n': 0}

    # Brier score (multiclass)
    brier = sum(
        (p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2
        for (o1, ox, o2), p1, px, p2 in zip(outcomes, probs_1, probs_x, probs_2)
    ) / n

    # Naive baseline: always predict league-average proportions
    home_frac = sum(1 for o in outcomes if o[0] == 1) / n
    draw_frac = sum(1 for o in outcomes if o[1] == 1) / n
    away_frac = sum(1 for o in outcomes if o[2] == 1) / n
    brier_baseline = sum(
        (home_frac - o1) ** 2 + (draw_frac - ox) ** 2 + (away_frac - o2) ** 2
        for o1, ox, o2 in outcomes
    ) / n

    # Accuracy
    winners = []
    for i in range(n):
        prob_max_idx = np.argmax([probs_1[i], probs_x[i], probs_2[i]])
        outcome_idx = outcomes[i].index(1)
        winners.append(1 if prob_max_idx == outcome_idx else 0)
    accuracy = sum(winners) / n

    # Calibration by probability bucket for corners_1 (home wins)
    buckets = defaultdict(list)
    for i in range(n):
        bucket = round(probs_1[i] * 20) / 20  # 0.05 buckets
        buckets[bucket].append(outcomes[i][0])

    calibration = []
    for bucket in sorted(buckets.keys()):
        obs = buckets[bucket]
        calibration.append({
            'bucket': round(bucket, 2),
            'predicted_pct': round(bucket * 100, 1),
            'actual_pct': round(np.mean(obs) * 100, 1),
            'n': len(obs),
        })

    return {
        'brier_score': round(brier, 4),
        'brier_baseline': round(brier_baseline, 4),
        'brier_improvement_pct': round((1 - brier / brier_baseline) * 100, 1) if brier_baseline > 0 else 0,
        'accuracy': round(accuracy * 100, 1),
        'n': n,
        'calibration_corners_1': calibration,
        'home_frac': round(home_frac * 100, 1),
        'draw_frac': round(draw_frac * 100, 1),
        'away_frac': round(away_frac * 100, 1),
    }


def evaluate_corners_over_under(predictions, lines=(7.5, 8.5, 9.5, 10.5, 11.5)):
    """Evaluate corners over/under at multiple lines."""
    results = {}

    for line in lines:
        outcomes_over = []
        probs_over = []

        for pred in predictions:
            total_corners = pred['hc'] + pred['ac']
            prob_over = pred['corners_over'](line)

            outcomes_over.append(1 if total_corners > line else 0)
            probs_over.append(prob_over)

        n = len(outcomes_over)
        if n == 0:
            results[f'over_{str(line).replace(".", "_")}'] = {'n': 0}
            continue

        # Brier score (binary)
        brier = sum((p - o) ** 2 for p, o in zip(probs_over, outcomes_over)) / n

        # Baseline: historical proportion
        baseline = sum(outcomes_over) / n
        brier_baseline = sum((baseline - o) ** 2 for o in outcomes_over) / n

        # Accuracy
        correct = sum(1 for p, o in zip(probs_over, outcomes_over) if (p >= 0.5 and o == 1) or (p < 0.5 and o == 0))
        accuracy = correct / n

        results[f'over_{str(line).replace(".", "_")}'] = {
            'line': line,
            'brier_score': round(brier, 4),
            'brier_baseline': round(brier_baseline, 4),
            'brier_improvement_pct': round((1 - brier / brier_baseline) * 100, 1) if brier_baseline > 0 else 0,
            'accuracy': round(accuracy * 100, 1),
            'actual_over_pct': round(baseline * 100, 1),
            'n': n,
        }

    return results


def run_validation(league_filter=None, max_matches=0):
    """Main validation entry point.

    Args:
        league_filter: optional league code prefix (e.g. "E0") to filter.
        max_matches: if > 0, limit matches processed (for quick checks).
    """
    print("Carregando dados de cantos...")
    df, total = load_all_corners_data()
    if df.empty:
        print("ERRO: Nenhum dado de cantos encontrado.")
        return {'status': 'error', 'message': 'No corners data found'}

    print(f"  {total} partidas com dados de cantos carregadas.")
    df = df.sort_values('Date').reset_index(drop=True)

    if league_filter:
        df = df[df['_league_code'].str.startswith(league_filter)]
        print(f"  Filtrado para ligas '{league_filter}*': {len(df)} partidas.")

    if max_matches > 0 and len(df) > max_matches:
        df = df.iloc[-max_matches:]
        print(f"  Limitado às últimas {max_matches} partidas.")

    # Walk-forward: compute predictions using rolling league averages
    league_stats = defaultdict(lambda: {'hc_sum': 0, 'ac_sum': 0, 'count': 0, 'hc_vals': [], 'ac_vals': []})
    predictions = []

    for _, row in df.iterrows():
        league = row['_league_code']
        hc = int(row['HC'])
        ac = int(row['AC'])

        stats = league_stats[league]
        # Use last 200 matches rolling window
        recent_hc = stats['hc_vals'][-200:]
        recent_ac = stats['ac_vals'][-200:]
        exp_h = np.mean(recent_hc) if recent_hc else 5.5
        exp_a = np.mean(recent_ac) if recent_ac else 4.5

        corners_probs = compute_corners_probs(exp_h, exp_a)

        predictions.append({
            'league': league,
            'hc': hc,
            'ac': ac,
            'total': hc + ac,
            'expected_h': exp_h,
            'expected_a': exp_a,
            'corners_1': corners_probs['corners_1'],
            'corners_x': corners_probs['corners_x'],
            'corners_2': corners_probs['corners_2'],
            'corners_over': corners_probs['corners_over'],
            'corners_under': corners_probs['corners_under'],
        })

        # Update rolling stats
        stats['hc_vals'].append(hc)
        stats['ac_vals'].append(ac)
        stats['hc_sum'] += hc
        stats['ac_sum'] += ac
        stats['count'] += 1

    n_preds = len(predictions)
    if n_preds == 0:
        print("Nenhuma predicao gerada.")
        return {'status': 'skipped', 'message': 'No predictions'}

    print(f"\n{n_preds} predicoes geradas (walk-forward).")
    print(f"Media de cantos: home={np.mean([p['expected_h'] for p in predictions]):.2f}, "
          f"away={np.mean([p['expected_a'] for p in predictions]):.2f}")

    # === 1X2 Evaluation ===
    print("\n" + "=" * 60)
    print(" CORNERS 1X2 (Poisson independente)")
    print("=" * 60)
    results_1x2 = evaluate_corners_1x2(df, predictions)
    print(f"  Partidas: {results_1x2['n']}")
    print(f"  Accuracy: {results_1x2['accuracy']}%")
    print(f"  Brier Score: {results_1x2['brier_score']} (baseline naive: {results_1x2['brier_baseline']})")
    print(f"  Melhora vs baseline: {results_1x2['brier_improvement_pct']}%")
    print(f"  Distribuicao real: H={results_1x2['home_frac']}% D={results_1x2['draw_frac']}% A={results_1x2['away_frac']}%")

    # === Over/Under Evaluation ===
    print("\n" + "=" * 60)
    print(" CORNERS OVER/UNDER (Poisson total)")
    print("=" * 60)
    results_ou = evaluate_corners_over_under(predictions)
    for key, res in sorted(results_ou.items()):
        if res.get('n', 0) == 0:
            continue
        print(f"\n  Over {res['line']}:")
        print(f"    Brier: {res['brier_score']} (baseline: {res['brier_baseline']}, "
              f"melhora: {res['brier_improvement_pct']}%)")
        print(f"    Accuracy: {res['accuracy']}% | Real over: {res['actual_over_pct']}% | n={res['n']}")

    # === Verdict ===
    brier_improvement_1x2 = results_1x2.get('brier_improvement_pct', 0)
    ou_improvements = [v.get('brier_improvement_pct', 0) for v in results_ou.values() if v.get('n', 0) > 0]
    avg_ou_improvement = np.mean(ou_improvements) if ou_improvements else 0

    print("\n" + "=" * 60)
    print(" VEREDICTO")
    print("=" * 60)

    if brier_improvement_1x2 > 5 and avg_ou_improvement > 3:
        verdict = "VALIDO"
        detail = "Modelo supera baseline naive consistentemente. Pode ser usado em producao."
    elif brier_improvement_1x2 > 0 or avg_ou_improvement > 0:
        verdict = "MARGINAL"
        detail = "Modelo melhor que baseline mas por margem pequena. Usar com caution."
    else:
        verdict = "PLACEBO"
        detail = "Modelo nao supera baseline naive. Nao deve ser usado para apostas reais."

    print(f"  Status: {verdict}")
    print(f"  Melhora 1X2: {brier_improvement_1x2}%")
    print(f"  Melhora media O/U: {avg_ou_improvement:.1f}%")
    print(f"  {detail}")

    return {
        'status': 'ok',
        'verdict': verdict,
        'detail': detail,
        'n_predictions': n_preds,
        'n_leagues': len(league_stats),
        'corners_1x2': results_1x2,
        'corners_over_under': results_ou,
        'brier_improvement_1x2': brier_improvement_1x2,
        'avg_ou_improvement': round(avg_ou_improvement, 1),
    }


def quick_validation():
    """Lightweight version for startup check — uses max 5000 matches."""
    return run_validation(max_matches=5000)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Validate corners Poisson model')
    parser.add_argument('--league', type=str, default=None, help='Filter by league code prefix (e.g. E0)')
    parser.add_argument('--max-matches', type=int, default=0, help='Limit matches (0 = all)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    result = run_validation(league_filter=args.league, max_matches=args.max_matches)

    if args.json:
        # Remove callables for JSON serialization
        if 'corners_over_under' in result:
            for k in list(result['corners_over_under'].keys()):
                if isinstance(result['corners_over_under'][k], dict):
                    result['corners_over_under'][k].pop('predictions', None)
        print(json.dumps(result, indent=2, default=str))
