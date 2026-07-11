import math
from ..constants import PERFORMANCE_DECAY_BASE, TIME_DECAY_XI, PERFORMANCE_REFERENCE_GAMES

_WEIGHTS_CACHE = {}

# Games per regular season for each league code
# Used to scale exponential decay: fewer games → faster decay (each game is more informative)
_GAMES_PER_SEASON = {
    'E0': 38, 'E1': 46, 'E2': 46, 'E3': 46,
    'SP1': 38, 'SP2': 42,
    'I1': 38, 'I2': 38,
    'D1': 34, 'D2': 34,
    'F1': 38, 'F2': 38,
    'N1': 34, 'B1': 30, 'P1': 34, 'T1': 38, 'G1': 26,
    'SC0': 38, 'SC1': 36,
    'ARG': 27, 'BRA': 38, 'USA': 34, 'MEX': 34, 'JPN': 38,
    'SWEDEN_ALLSVENSKAN': 30, 'NORWAY_ELITESERIEN': 30,
}
_REFERENCE_GAMES = PERFORMANCE_REFERENCE_GAMES  # Premier League baseline


def get_league_weighted_decay(league_code, base_decay=None):
    """
    Returns league-adjusted decay for weighted_mean.
    Fewer games per season → higher decay (each game represents a larger fraction of the season).
    Scales relative to Premier League (38 games) as baseline.
    """
    if base_decay is None:
        base_decay = PERFORMANCE_DECAY_BASE
    games = _GAMES_PER_SEASON.get(league_code, _REFERENCE_GAMES)
    return base_decay * (_REFERENCE_GAMES / games)


def get_league_time_decay(league_code, base_xi=None):
    """
    Returns league-adjusted time decay for PoissonModel.predict_match.
    Same scaling logic: fewer games → faster time decay.
    """
    if base_xi is None:
        base_xi = TIME_DECAY_XI
    games = _GAMES_PER_SEASON.get(league_code, _REFERENCE_GAMES)
    return base_xi * (_REFERENCE_GAMES / games)

def weighted_mean(values, decay=0.06):
    if not values:
        return 0.0
    n = len(values)
    cache_key = (n, decay)
    global _WEIGHTS_CACHE
    if cache_key not in _WEIGHTS_CACHE:
        weights = [math.exp(-decay * (n - 1 - i)) for i in range(n)]
        sum_weights = sum(weights)
        _WEIGHTS_CACHE[cache_key] = (weights, sum_weights)
    else:
        weights, sum_weights = _WEIGHTS_CACHE[cache_key]
    return sum(v * w for v, w in zip(values, weights)) / sum_weights

# Market liquidity tiers for parametric slippage
_MARKET_LIQUIDITY = {
    # Tier 0: most liquid — tight spreads
    'home': 0.0, 'draw': 0.0, 'away': 0.0,
    'over_25': 0.0, 'under_25': 0.0,
    # Tier 1: liquid — minor spread
    'over_15': 0.2, 'under_15': 0.2,
    'over_35': 0.2, 'under_35': 0.2,
    'btts_yes': 0.2, 'btts_no': 0.2,
    # Tier 2: medium liquidity
    'over_45': 0.5, 'under_45': 0.5,
    'over_55': 0.5, 'under_55': 0.5,
    'ah_home': 0.5, 'ah_away': 0.5,
    'dnb_home': 0.5, 'dnb_away': 0.5,
    # Tier 3: lower liquidity
    'lay_home': 0.8, 'lay_draw': 0.8, 'lay_away': 0.8,
    'ht_home': 0.8, 'ht_draw': 0.8, 'ht_away': 0.8,
    'ht_over05': 0.8, 'ht_under05': 0.8,
    'ht_over15': 0.8, 'ht_under15': 0.8,
    'sh_home': 0.8, 'sh_draw': 0.8, 'sh_away': 0.8,
    'sh_over05': 0.8, 'sh_under05': 0.8,
    'sh_over15': 0.8, 'sh_under15': 0.8,
    # Tier 4: exotic — wide spreads
    'cs': 1.5, 'lay_cs': 1.5, 'corners': 2.0,
    'win_to_nil_home': 1.5, 'win_to_nil_away': 1.5,
}

# League liquidity tiers: additive penalty for lower-tier leagues
_LEAGUE_LIQUIDITY_TIER = {
    'E0': 0.0, 'SP1': 0.0, 'I1': 0.0, 'D1': 0.0, 'F1': 0.0,  # Top 5
    'E1': 0.1, 'E2': 0.1, 'SP2': 0.1, 'I2': 0.1, 'D2': 0.1, 'F2': 0.1,  # Second tier
    'E3': 0.2, 'N1': 0.2, 'B1': 0.2, 'P1': 0.2, 'T1': 0.2, 'G1': 0.2,
    'SC0': 0.2, 'SC1': 0.2,  # Smaller European
    'ARG': 0.3, 'BRA': 0.3, 'USA': 0.3, 'MEX': 0.3, 'JPN': 0.3,
    'SWEDEN_ALLSVENSKAN': 0.3, 'NORWAY_ELITESERIEN': 0.3,
}


def compute_slippage_factor(bookie_odds, market, base_pct=1.0, league_code=None):
    """
    Parametric slippage model that varies by odds, market liquidity, and league.

    slippage = base + odds_component + market_penalty + league_penalty

    - base: minimum slippage (default 1.0%)
    - odds_component: 0.25% per unit of odds above 2.0 (higher odds = wider spreads)
    - market_penalty: additive penalty based on market liquidity tier
    - league_penalty: additive penalty for lower-tier leagues

    Returns a factor in (0, 1] to multiply effective odds by.
    Capped to reasonable bounds [0.5%, 8.0%].
    """
    if bookie_odds is None or bookie_odds <= 1.0:
        return 1.0

    # Market penalty: look up by prefix match
    market_penalty = 0.0
    for prefix, penalty in sorted(_MARKET_LIQUIDITY.items(), key=lambda x: -len(x[0])):
        if market.startswith(prefix) or market == prefix:
            market_penalty = penalty
            break

    # League penalty: lower-tier leagues have wider spreads
    league_penalty = _LEAGUE_LIQUIDITY_TIER.get(league_code, 0.2) if league_code else 0.0

    # Odds component: kicks in above odds 2.0
    odds_component = max(0.0, (bookie_odds - 2.0) * 0.25)

    slippage_pct = base_pct + odds_component + market_penalty + league_penalty
    slippage_pct = max(0.5, min(8.0, slippage_pct))

    return 1.0 - (slippage_pct / 100.0)


def solve_kelly_multi(probs, outcomes, max_f=1.0):
    """
    Newton-Raphson solver for multi-outcome Kelly criterion.

    Maximizes E[log(1 + f * x)] where x are the outcome returns.
    Converges when derivative crosses zero within tolerance,
    or falls back to bounded binary search.
    """
    ev = sum(p * x for p, x in zip(probs, outcomes))
    if ev <= 0:
        return 0.0

    # Newton-Raphson: f_{n+1} = f_n - E[x/(1+f*x)] / E[-x^2/(1+f*x)^2]
    f = min(ev * 0.25, max_f * 0.5)  # conservative initial guess
    for _ in range(20):
        deriv = 0.0
        deriv2 = 0.0
        for p, x in zip(probs, outcomes):
            denom = 1.0 + f * x
            if denom <= 0:
                f = -0.99 / min(x for x in outcomes if x < 0)  # avoid singularity
                break
            deriv += p * x / denom
            deriv2 -= p * x * x / (denom * denom)
        else:
            if abs(deriv) < 1e-6:
                break
            if deriv2 == 0:
                break
            f_new = f - deriv / deriv2
            f_new = max(0.0, min(max_f, f_new))
            if abs(f_new - f) < 1e-8:
                f = f_new
                break
            f = f_new

    return max(0.0, min(max_f, f))


def compute_drawdown_multiplier(current_bankroll, peak_bankroll):
    """
    Circuit breaker: reduces exposure progressively as drawdown deepens.

    Rationale: syndicates don't just track drawdown — they act on it.
    Reducing stakes during drawdowns protects the bankroll from
    compounded losses and model miscalibration spirals.

    Tiers:
      - 0-10% DD : normal (1.0x)
      - 10-20% DD: caution (0.50x)
      - 20-30% DD: severe (0.25x)
      - >30% DD  : stop (0.00x) — requires model audit
    """
    if peak_bankroll <= 0:
        return 1.0
    dd = (peak_bankroll - current_bankroll) / peak_bankroll
    if dd < 0.10:
        return 1.0
    elif dd < 0.20:
        return 0.50
    elif dd < 0.30:
        return 0.25
    else:
        return 0.0


def compute_edge_scaled_cap(model_prob, effective_odds, mkt, max_cap_pct=5.0):
    """
    Compute per-bet stake cap as a percentage of bankroll, scaled by edge size
    and market volatility.

    Edge-scaled: cap = min(max_cap, 0.5 × edge_pct)
      - 2% edge → 1% cap, 10% edge → 5% cap, 15% edge → 5% cap (ceiling)
      - Prevents over-allocation to marginal edges while allowing bigger bets
        on high-conviction opportunities.

    Market-volatility multiplier (variance-based):
      - 1X2: 1.0 (baseline)
      - Over/Under: 0.85
      - BTTS: 0.7
      - AH/DNB: 0.9
      - Lay: 0.6
      - Correct Score: 0.4
      - HT/2H: 0.75
      - Corners: 0.5
    """
    if mkt.startswith('lay_'):
        # Lay EV: win prob keeps backer's stake (1 unit), lose prob pays (odds-1)
        edge_pct = (model_prob - (1.0 - model_prob) * (effective_odds - 1.0)) * 100.0
    else:
        edge_pct = (model_prob * effective_odds - 1.0) * 100.0
    if edge_pct <= 0:
        return 0.0

    # Edge-scaled cap: 0.5× edge, bounded by max_cap_pct
    edge_cap = min(max_cap_pct, 0.5 * edge_pct)

    # Market volatility multiplier
    if mkt in ('home', '1x2_home', 'away', '1x2_away', 'draw', '1x2_draw'):
        vol_mult = 1.0
    elif mkt.startswith('over') or mkt.startswith('under'):
        vol_mult = 0.85
    elif mkt.startswith('btts'):
        vol_mult = 0.7
    elif mkt.startswith('ah_') or mkt.startswith('dnb_'):
        vol_mult = 0.9
    elif mkt.startswith('lay_'):
        vol_mult = 0.6
    elif mkt.startswith('cs_') or mkt.startswith('lay_cs_'):
        vol_mult = 0.4
    elif mkt.startswith('ht_') or mkt.startswith('sh_'):
        vol_mult = 0.75
    elif mkt.startswith('corners'):
        vol_mult = 0.5
    elif mkt in ('win_to_nil_home', 'win_to_nil_away'):
        vol_mult = 0.5
    else:
        vol_mult = 0.8  # conservative default

    return edge_cap * vol_mult


def compute_corners_probs(expected_home_corners, expected_away_corners, max_corners=25):
    """
    Calculate corners market probabilities using Poisson-based models.

    - corners_1X2: approximated via P(H > A), P(H == A), P(H < A)
      using independent Poisson draws (simulated efficiently)
    - corners_over/under X: Poisson CDF on total expected corners

    Returns dict with keys: corners_1, corners_x, corners_2, and callable
    for over/under: corners_over(line), corners_under(line).
    """
    import math

    lambda_h = max(0.5, expected_home_corners)
    lambda_a = max(0.5, expected_away_corners)

    # Precompute factorial for Poisson PMF
    fact = [1.0]
    for i in range(1, max_corners + 1):
        fact.append(fact[-1] * i)

    def poisson_pmf(k, lam):
        return math.exp(-lam) * (lam ** k) / fact[k]

    # Build marginal PMFs
    h_pmf = [poisson_pmf(k, lambda_h) for k in range(max_corners + 1)]
    a_pmf = [poisson_pmf(k, lambda_a) for k in range(max_corners + 1)]

    # Normalize (accounts for truncation at max_corners)
    h_sum = sum(h_pmf)
    a_sum = sum(a_pmf)
    h_pmf = [p / h_sum for p in h_pmf]
    a_pmf = [p / a_sum for p in a_pmf]

    # Joint probabilities: P(H > A), P(H == A), P(H < A)
    prob_home = sum(
        h_pmf[i] * sum(a_pmf[:i]) for i in range(1, max_corners + 1)
    )
    prob_draw = sum(h_pmf[i] * a_pmf[i] for i in range(max_corners + 1))
    prob_away = 1.0 - prob_home - prob_draw

    # Over/Under using total corners Poisson
    lambda_total = lambda_h + lambda_a
    total_pmf = [poisson_pmf(k, lambda_total) for k in range(max_corners + 1)]
    total_sum = sum(total_pmf)
    total_pmf = [p / total_sum for p in total_pmf]
    total_cdf = []
    cum = 0.0
    for p in total_pmf:
        cum += p
        total_cdf.append(cum)

    def corners_over(line):
        if line >= max_corners:
            return 0.0
        return 1.0 - total_cdf[int(line)]

    def corners_under(line):
        if line <= 0:
            return 0.0
        if line >= max_corners:
            return 1.0
        return total_cdf[int(line)]

    return {
        'corners_1': prob_home,
        'corners_x': prob_draw,
        'corners_2': prob_away,
        'corners_over': corners_over,
        'corners_under': corners_under,
    }


def get_liquidity_max_stake(league_code, market, base_stake_pct=5.0):
    """
    Returns the maximum recommended stake as % of bankroll for a given
    league and market, accounting for liquidity constraints.

    League tiers (smaller leagues = lower liquidity = lower max stake):
      - Tier 0 (Top 5): 100% of base
      - Tier 1 (2nd div): 75% of base
      - Tier 2 (smaller EU): 50% of base
      - Tier 3 (SA/Asia): 35% of base
      - Default: 40% of base

    Market liquidity penalty (applied multiplicatively):
      - Correct Score, Corners: 0.5× (thin markets)
      - Win to Nil, Lay CS: 0.5×
      - BTTS, HT, 2H: 0.7×
      - Over/Under: 0.85×
      - 1X2, AH, DNB: 1.0×
    """
    # League tier
    _LEAGUE_TIER = {
        'E0': 0, 'SP1': 0, 'I1': 0, 'D1': 0, 'F1': 0,
        'E1': 1, 'E2': 1, 'SP2': 1, 'I2': 1, 'D2': 1, 'F2': 1,
        'E3': 2, 'N1': 2, 'B1': 2, 'P1': 2, 'T1': 2, 'G1': 2,
        'SC0': 2, 'SC1': 2, 'SC2': 2, 'SC3': 2,
        'ARG': 3, 'BRA': 3, 'USA': 3, 'MEX': 3, 'JPN': 3,
        'SWEDEN_ALLSVENSKAN': 3, 'NORWAY_ELITESERIEN': 3,
    }
    _TIER_MULTIPLIER = {0: 1.0, 1: 0.75, 2: 0.50, 3: 0.35}

    tier = _LEAGUE_TIER.get(league_code, 2)
    league_mult = _TIER_MULTIPLIER.get(tier, 0.40)

    # Market liquidity
    if market.startswith('cs_') or market.startswith('lay_cs_') or market.startswith('corners'):
        market_mult = 0.5
    elif market in ('win_to_nil_home', 'win_to_nil_away'):
        market_mult = 0.5
    elif market.startswith('btts') or market.startswith('ht_') or market.startswith('sh_'):
        market_mult = 0.7
    elif market.startswith('over') or market.startswith('under'):
        market_mult = 0.85
    else:
        market_mult = 1.0

    return base_stake_pct * league_mult * market_mult


def allocate_core_satellite(initial_bankroll, strategies):
    """
    Core/Satellite allocation: splits bankroll into core (80%) and
    satellite (20%) for controlled experimentation.

    strategies: list of dicts with keys:
      - name: strategy label
      - allocation: 'core' or 'satellite'
      - kelly_fraction: recommended Kelly multiplier
      - max_stake_pct: max per-bet % (relative to allocated bankroll)

    Returns dict with per-strategy bankroll and risk limits.
    """
    core_pct = 0.80
    satellite_pct = 0.20

    core_bankroll = initial_bankroll * core_pct
    satellite_bankroll = initial_bankroll * satellite_pct

    allocation = {}
    core_strategies = [s for s in strategies if s.get('allocation') == 'core']
    satellite_strategies = [s for s in strategies if s.get('allocation') != 'core']

    for s in core_strategies:
        alloc_bankroll = core_bankroll / max(len(core_strategies), 1)
        allocation[s['name']] = {
            'bankroll': round(alloc_bankroll, 2),
            'tier': 'core',
            'kelly_fraction': s.get('kelly_fraction', 0.25),
            'max_stake_pct': s.get('max_stake_pct', 5.0),
            'review_interval_days': 90,  # quarterly review
        }

    for s in satellite_strategies:
        alloc_bankroll = satellite_bankroll / max(len(satellite_strategies), 1)
        allocation[s['name']] = {
            'bankroll': round(alloc_bankroll, 2),
            'tier': 'satellite',
            'kelly_fraction': min(s.get('kelly_fraction', 0.25), 0.125),
            'max_stake_pct': min(s.get('max_stake_pct', 2.5), 2.5),
            'review_interval_days': 30,  # monthly review
        }

    return allocation


def compute_ewma_volatility(returns, halflife=20):
    """
    Exponentially Weighted Moving Average volatility estimate.

    More responsive than equal-weight std for detecting regime changes.
    halflife: number of periods for weight to decay by 50%.
    """
    if len(returns) < 2:
        return 0.0

    alpha = 2.0 / (halflife + 1.0)
    variance = returns[0] ** 2
    for r in returns[1:]:
        variance = alpha * (r ** 2) + (1.0 - alpha) * variance

    return variance ** 0.5


def compute_dynamic_kelly_fraction(base_kelly, returns, target_vol=0.15, halflife=20):
    """
    Dynamically adjusts the Kelly fraction based on recent return volatility.

    Vol below target → full Kelly (stable regime)
    Vol above target → reduce proportionally (turbulent regime)

    Capped between 0.1× and 1.0× of base_kelly.
    """
    current_vol = compute_ewma_volatility(returns, halflife)
    if current_vol <= 0 or target_vol <= 0:
        return base_kelly

    ratio = target_vol / current_vol
    adjusted = base_kelly * max(0.1, min(1.0, ratio))
    return adjusted


def detect_volatility_regime(returns, halflife=20, high_threshold=1.5):
    """
    Classifies current volatility regime based on EWMA vol vs long-run vol.

    Returns:
      'low': current vol < 0.67× long-run vol
      'normal': 0.67× to 1.5× long-run vol
      'high': > 1.5× long-run vol (reduce exposure)
    """
    if len(returns) < 10:
        return 'normal'

    current_vol = compute_ewma_volatility(returns, halflife)
    n = len(returns)
    long_run_vol = (sum(r ** 2 for r in returns) / n) ** 0.5

    if long_run_vol <= 0:
        return 'normal'

    ratio = current_vol / long_run_vol
    if ratio > high_threshold:
        return 'high'
    elif ratio < 1.0 / high_threshold:
        return 'low'
    return 'normal'
