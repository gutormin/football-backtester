import math

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
_REFERENCE_GAMES = 38  # Premier League baseline


def get_league_weighted_decay(league_code, base_decay=0.06):
    """
    Returns league-adjusted decay for weighted_mean.
    Fewer games per season → higher decay (each game represents a larger fraction of the season).
    Scales relative to Premier League (38 games) as baseline.
    """
    games = _GAMES_PER_SEASON.get(league_code, _REFERENCE_GAMES)
    return base_decay * (_REFERENCE_GAMES / games)


def get_league_time_decay(league_code, base_xi=0.0065):
    """
    Returns league-adjusted time decay for PoissonModel.predict_match.
    Same scaling logic: fewer games → faster time decay.
    """
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
    'sh_home': 0.8, 'sh_draw': 0.8, 'sh_away': 0.8,
    # Tier 4: exotic — wide spreads
    'cs': 1.5, 'corners': 2.0,
    'win_to_nil_home': 1.5, 'win_to_nil_away': 1.5,
}


def compute_slippage_factor(bookie_odds, market, base_pct=1.0):
    """
    Parametric slippage model that varies by odds and market liquidity.

    slippage = base + odds_component + market_penalty

    - base: minimum slippage (default 1.0%)
    - odds_component: 0.25% per unit of odds above 2.0 (higher odds = wider spreads)
    - market_penalty: additive penalty based on market liquidity tier

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

    # Odds component: kicks in above odds 2.0
    odds_component = max(0.0, (bookie_odds - 2.0) * 0.25)

    slippage_pct = base_pct + odds_component + market_penalty
    slippage_pct = max(0.5, min(8.0, slippage_pct))

    return 1.0 - (slippage_pct / 100.0)


def solve_kelly_multi(probs, outcomes, max_f=1.0):
    low = 0.0
    high = max_f
    ev = sum(p * x for p, x in zip(probs, outcomes))
    if ev <= 0:
        return 0.0
    for _ in range(15):
        mid = (low + high) / 2.0
        deriv = sum(p * x / (1.0 + mid * x) for p, x in zip(probs, outcomes))
        if deriv > 0:
            low = mid
        else:
            high = mid
    return low


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
        return total_cdf[int(line) - 1]

    return {
        'corners_1': prob_home,
        'corners_x': prob_draw,
        'corners_2': prob_away,
        'corners_over': corners_over,
        'corners_under': corners_under,
    }
