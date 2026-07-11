import os
import logging
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from .api_utils import retry_with_backoff

logger = logging.getLogger(__name__)

load_dotenv()

# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

# Betfair Exchange commission — charged on NET PROFIT (not stake)
BETFAIR_COMMISSION = 0.02         # 2% for liquid football markets (Premier League, etc.)
BETFAIR_COMMISSION_LOW_TIER = 0.05  # 5% for lower volume leagues
BETFAIR_EXCHANGE_NAMES = {'betfair exchange', 'betfair'}

# Slippage model by odds tier (empirical + academic: Franck et al. 2010)
def _slippage(odds: float) -> float:
    """Estimated percentage slippage when executing at detected odds."""
    if odds <= 1.20:
        return 0.030   # very short odds — bookies reprice instantly
    elif odds <= 2.00:
        return 0.015
    elif odds <= 5.00:
        return 0.010
    else:
        return 0.025   # longshots — thinner liquidity

# Leagues considered "low tier" for Betfair commission purposes
LOW_TIER_LEAGUE_PREFIXES = (
    'soccer_brazil_serie_b', 'soccer_england_league2', 'soccer_germany_bundesliga2',
    'soccer_italy_serie_b', 'soccer_france_ligue_two', 'soccer_spain_segunda_division',
    'soccer_turkey_super_league', 'soccer_greece_super_league',
    'soccer_sweden_', 'soccer_norway_',
)
HIGH_TIER_LEAGUE_PREFIXES = (
    'soccer_epl', 'soccer_spain_la_liga', 'soccer_italy_serie_a',
    'soccer_germany_bundesliga', 'soccer_france_ligue_one',
    'soccer_uefa_champs', 'soccer_uefa_europa',
    'soccer_brazil_campeonato', 'soccer_argentina_primera_division',
)

MIN_PROFIT_THRESHOLD = 1.0        # minimum profit % after slippage (was 0.0)
MAX_PROFIT_THRESHOLD = 15.0       # cap — above this is likely a stale/error odd
MIN_QUALITY_SCORE = 30            # quality score floor to include in results

# Markets to fetch — totals + h2h + spreads for cross-market arb
MARKETS = 'h2h,totals,spreads'
REGIONS = 'eu,uk,us'

# Soccer leagues to scan individually (per-league query = 1 credit each)
# Imported from shared mappings to stay in sync with dutching + live_odds modules
from .odds_api_mappings import ALL_SOCCER_SPORT_KEYS as SOCCER_SPORT_KEYS  # noqa: F401


# ══════════════════════════════════════════════════════════════════════════════
# Quality Scoring
# ══════════════════════════════════════════════════════════════════════════════

def _compute_quality_score(profit_pct_net: float, num_bookmakers: int,
                           hours_to_kickoff: float, market_type: str,
                           odds_range: float) -> float:
    """
    Composite quality score 0–100 for an arbitrage opportunity.

    Components:
      - Net profit margin:         30 pts  (0% → 0, 5%+ → 30)
      - Bookmaker liquidity:       20 pts  (1 bookie → 0, 4+ → 20)
      - Time to kickoff:           20 pts  (>24h → 20, <1h → 0)
      - Market type stability:     15 pts  (h2h=15, totals=12, spreads=5)
      - Odd range (stability):     15 pts  (<0.5 → 15, >3.0 → 0)
    """
    score = 0.0

    # 1. Net profit (30 pts)
    score += min(profit_pct_net * 6.0, 30.0)

    # 2. Liquidity (20 pts) — proxy: number of unique bookmakers with competitive odds
    score += min(num_bookmakers * 5.0, 20.0)

    # 3. Time to kickoff (20 pts)
    if hours_to_kickoff > 24:
        score += 20.0
    elif hours_to_kickoff > 12:
        score += 18.0
    elif hours_to_kickoff > 6:
        score += 15.0
    elif hours_to_kickoff > 3:
        score += 10.0
    elif hours_to_kickoff > 1:
        score += 5.0

    # 4. Market type (15 pts)
    market_scores = {'h2h': 15, 'totals': 12, 'spreads': 5}
    score += market_scores.get(market_type, 5)

    # 5. Odd range stability (15 pts) — tightly clustered best odds = healthier market
    if odds_range < 0.5:
        score += 15.0
    elif odds_range < 1.5:
        score += 10.0
    elif odds_range < 3.0:
        score += 5.0

    return round(min(score, 100.0), 1)


# ══════════════════════════════════════════════════════════════════════════════
# Betfair Commission
# ══════════════════════════════════════════════════════════════════════════════

def _is_betfair(name: str) -> bool:
    return name.lower() in BETFAIR_EXCHANGE_NAMES

def _betfair_effective_odds(odds: float, sport_key: str = '') -> float:
    """Convert Betfair Exchange odds to effective odds after commission.

    Betfair charges commission on NET PROFIT, not stake.
    effective_odds = 1 + (odds - 1) * (1 - commission)
    """
    is_low = not any(sport_key.startswith(p) for p in HIGH_TIER_LEAGUE_PREFIXES)
    rate = BETFAIR_COMMISSION_LOW_TIER if is_low else BETFAIR_COMMISSION
    return 1.0 + (odds - 1.0) * (1.0 - rate)


# ══════════════════════════════════════════════════════════════════════════════
# Net Profit Calculation (after slippage + commission)
# ══════════════════════════════════════════════════════════════════════════════

def _compute_net_profit(odds_list, bookie_names, sport_key=''):
    """Compute arbitrage profit AFTER slippage and Betfair commission.

    Returns (gross_profit_pct, net_profit_pct, total_slippage_pts).
    """
    # Apply Betfair commission
    effective_odds = []
    for odd, name in zip(odds_list, bookie_names):
        if _is_betfair(name):
            effective_odds.append(_betfair_effective_odds(odd, sport_key))
        else:
            effective_odds.append(odd)

    # Apply slippage
    slipped_odds = []
    total_slip = 0.0
    for odd in effective_odds:
        slip = _slippage(odd)
        total_slip += slip
        slipped_odds.append(odd * (1.0 - slip))

    # Gross implied
    raw_implied = sum(1.0 / o for o in odds_list)
    # Net implied (after costs)
    net_implied = sum(1.0 / o for o in slipped_odds)

    gross_pct = (1.0 - raw_implied) / raw_implied * 100.0
    net_pct = (1.0 - net_implied) / net_implied * 100.0

    return gross_pct, net_pct, total_slip / len(odds_list)


# ══════════════════════════════════════════════════════════════════════════════
# API Fetch
# ══════════════════════════════════════════════════════════════════════════════

@retry_with_backoff(max_retries=3, base_delay=1.0)
def _fetch_odds_api(url, headers):
    return requests.get(url, headers=headers, timeout=15)


def fetch_arbitrage_opportunities(allowed_bookies=None):
    """
    Scan The Odds API for football arbitrage opportunities.

    v3: Queries each soccer league individually (per-league = 1 credit each)
        instead of the generic 'upcoming' endpoint which returns mostly non-soccer
        sports during off-season months (June–August).

    Filters:
      - Football only (soccer_* sport keys)
      - Betfair Exchange commission (2–5% on net profit)
      - Slippage model by odds range
      - Min 1.0% net profit, max 15% (cap for stale odds)
      - Quality score 0–100, minimum 30
      - Capture timestamp for staleness detection
    """
    API_KEY = os.getenv('THE_ODDS_API_KEY')
    if not API_KEY:
        logger.error("THE_ODDS_API_KEY not set in environment")
        return [{'error': 'no_api_key', 'message': 'API key da The Odds API não configurada. Obtenha uma em https://the-odds-api.com e defina THE_ODDS_API_KEY no ambiente do Render.'}]

    headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/91.0.4472.124 Safari/537.36')
    }

    captured_at = datetime.now(timezone.utc)

    # Query each soccer league individually — the generic 'upcoming' endpoint
    # returns mostly non-soccer sports during off-season months
    all_matches = []
    total_credits_used = 0
    total_credits_remaining = 0

    for sport_key in SOCCER_SPORT_KEYS:
        url = (f'https://api.the-odds-api.com/v4/sports/{sport_key}/odds/'
               f'?apiKey={API_KEY}&regions={REGIONS}&markets={MARKETS}')
        try:
            response = _fetch_odds_api(url, headers)
        except Exception as e:
            logger.warning(f"API error for {sport_key}: {e}")
            continue

        total_credits_used = response.headers.get('x-requests-used', '?')
        total_credits_remaining = response.headers.get('x-requests-remaining', '?')

        if response.status_code == 422:
            continue  # no upcoming matches for this league
        if response.status_code != 200:
            if response.status_code == 429:
                logger.warning(f"Rate limit atingido em {sport_key}, parando scan")
                break
            continue

        league_matches = response.json()
        if isinstance(league_matches, list) and league_matches:
            all_matches.extend(league_matches)

    logger.info(f"Odds API credits: used={total_credits_used}, remaining={total_credits_remaining}")
    logger.info(f"Fetched {len(all_matches)} soccer matches across {len(SOCCER_SPORT_KEYS)} leagues")

    data = all_matches

    # Debug counters
    _dbg_total_matches = len(data)
    _dbg_soccer = 0
    _dbg_not_live = 0
    _dbg_within_7d = 0
    _dbg_raw_opps = 0
    _dbg_net_filtered = 0
    _dbg_quality_filtered = 0

    opportunities = []
    near_misses = []  # raw opps that didn't pass filters — displayed for transparency
    all_edge_candidates = []  # all markets implied probs for "closest to arb" display
    now_utc = datetime.now(timezone.utc)

    if not allowed_bookies:
        allowed_bookies = [
            'Bet365', 'Pinnacle', 'Betfair Exchange', 'Betfair', 'Betano',
            '1xBet', 'Sportingbet', 'Betsson', 'Marathon Bet', '888sport',
            'William Hill', 'Bovada', 'BetMGM', 'BetRivers', 'PointsBet (US)',
            'LeoVegas', 'GTbets', 'LowVig.ag', 'EveryGame',
        ]

    allowed_bookies_lower = {b.lower() for b in allowed_bookies}

    for match in data:
        sport_key = match.get('sport_key', '')

        # ── Football only ──
        if not sport_key.startswith('soccer_'):
            continue
        _dbg_soccer += 1

        home_team = match.get('home_team', '')
        away_team = match.get('away_team', '')
        match_name = f"{home_team} vs {away_team}"

        # ── Parse + filter live matches ──
        dt = match.get('commence_time')
        hours_to_kickoff = None
        if dt:
            try:
                match_time = datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if match_time < now_utc:
                    continue  # skip live matches → ghost arb
                _dbg_not_live += 1
                match_date = match_time.strftime("%d/%m/%Y %H:%M")
                hours_to_kickoff = (match_time - now_utc).total_seconds() / 3600.0
                if hours_to_kickoff > 168:  # skip matches > 7 days out — odds unreliable
                    continue
                _dbg_within_7d += 1
            except Exception:
                match_date = dt
        else:
            match_date = "Unknown"

        # ── Best odds per outcome ──
        best_home = {'price': 0.0, 'bookmaker': ''}
        best_draw = {'price': 0.0, 'bookmaker': ''}
        best_away = {'price': 0.0, 'bookmaker': ''}

        # Totals: {point_str: {Over: {price, bookmaker}, Under: {price, bookmaker}}}
        best_totals = {}

        # Spreads: {key: {Home: {price, bookmaker, point}, Away: {price, bookmaker, point}}}
        best_spreads = {}

        unique_bookies_with_odds = set()

        for bookie in match.get('bookmakers', []):
            bookie_name = bookie.get('title', 'Unknown')

            if bookie_name.lower() not in allowed_bookies_lower:
                continue

            for market in bookie.get('markets', []):
                market_key = market.get('key')

                # ── H2H ──
                if market_key == 'h2h':
                    for outcome in market.get('outcomes', []):
                        price = outcome.get('price', 0.0)
                        name = outcome.get('name')
                        if name == home_team and price > best_home['price']:
                            best_home = {'price': price, 'bookmaker': bookie_name}
                        elif name == away_team and price > best_away['price']:
                            best_away = {'price': price, 'bookmaker': bookie_name}
                        elif name == 'Draw' and price > best_draw['price']:
                            best_draw = {'price': price, 'bookmaker': bookie_name}
                        if price > 1.0:
                            unique_bookies_with_odds.add(bookie_name)

                # ── Totals ──
                elif market_key == 'totals':
                    for outcome in market.get('outcomes', []):
                        price = outcome.get('price', 0.0)
                        name = outcome.get('name')
                        point = str(outcome.get('point', '0'))
                        if point not in best_totals:
                            best_totals[point] = {
                                'Over': {'price': 0.0, 'bookmaker': ''},
                                'Under': {'price': 0.0, 'bookmaker': ''}
                            }
                        if name == 'Over' and price > best_totals[point]['Over']['price']:
                            best_totals[point]['Over'] = {'price': price, 'bookmaker': bookie_name}
                        elif name == 'Under' and price > best_totals[point]['Under']['price']:
                            best_totals[point]['Under'] = {'price': price, 'bookmaker': bookie_name}
                        if price > 1.0:
                            unique_bookies_with_odds.add(bookie_name)

                # ── Spreads ──
                elif market_key == 'spreads':
                    for outcome in market.get('outcomes', []):
                        price = outcome.get('price', 0.0)
                        name = outcome.get('name')
                        point = outcome.get('point', 0.0)
                        if name == home_team:
                            key = f"H{point}_A{-point}"
                            side = 'Home'
                        elif name == away_team:
                            key = f"H{-point}_A{point}"
                            side = 'Away'
                        else:
                            continue
                        if key not in best_spreads:
                            best_spreads[key] = {
                                'Home': {'price': 0.0, 'bookmaker': '', 'point': 0},
                                'Away': {'price': 0.0, 'bookmaker': '', 'point': 0}
                            }
                        if side == 'Home' and price > best_spreads[key]['Home']['price']:
                            best_spreads[key]['Home'] = {'price': price, 'bookmaker': bookie_name, 'point': point}
                        elif side == 'Away' and price > best_spreads[key]['Away']['price']:
                            best_spreads[key]['Away'] = {'price': price, 'bookmaker': bookie_name, 'point': point}
                        if price > 1.0:
                            unique_bookies_with_odds.add(bookie_name)

        num_bookmakers = len(unique_bookies_with_odds)

        # ── Check 1X2 ──
        mh, md, ma = best_home['price'], best_draw['price'], best_away['price']
        if mh > 1.0 and md > 1.0 and ma > 1.0:
            raw_implied = (1/mh) + (1/md) + (1/ma)
            gross, net, avg_slip = _compute_net_profit(
                [mh, md, ma],
                [best_home['bookmaker'], best_draw['bookmaker'], best_away['bookmaker']],
                sport_key
            )
            # Track all matches for "closest to arb" display
            all_edge_candidates.append({
                'match': match_name, 'sport_key': sport_key,
                'date': match_date,
                'hours_to_kickoff': round(hours_to_kickoff, 1) if hours_to_kickoff else None,
                'market': 'Match Odds (1X2)',
                'odds': {'1': mh, 'X': md, '2': ma},
                'bookmakers': {'1': best_home['bookmaker'], 'X': best_draw['bookmaker'], '2': best_away['bookmaker']},
                'implied_prob': round(raw_implied * 100, 2),
                'profit_margin': round(gross, 2),
                'profit_margin_net': round(net, 2),
                'slippage_pct': round(avg_slip * 100, 1),
                'quality_score': None,
                'num_bookmakers': num_bookmakers,
            })
            if raw_implied < 1.0:
                _dbg_raw_opps += 1
                logger.debug(
                    f"  1X2 raw opp: {match_name} | odds={mh:.2f}/{md:.2f}/{ma:.2f} | "
                    f"implied={raw_implied*100:.1f}% | gross={gross:.2f}% | net={net:.2f}% | "
                    f"slip={avg_slip*100:.1f}% | books={best_home['bookmaker']}/{best_draw['bookmaker']}/{best_away['bookmaker']}"
                )
            if net < MIN_PROFIT_THRESHOLD or net > MAX_PROFIT_THRESHOLD:
                if raw_implied < 1.0:
                    _dbg_net_filtered += 1
                    near_misses.append({
                        'match': match_name, 'sport_key': sport_key,
                        'date': match_date,
                        'hours_to_kickoff': round(hours_to_kickoff, 1) if hours_to_kickoff else None,
                        'market': 'Match Odds (1X2)',
                        'odds': {'1': mh, 'X': md, '2': ma},
                        'bookmakers': {'1': best_home['bookmaker'], 'X': best_draw['bookmaker'], '2': best_away['bookmaker']},
                        'implied_prob': round(raw_implied * 100, 2),
                        'profit_margin': round(gross, 2),
                        'profit_margin_net': round(net, 2),
                        'slippage_pct': round(avg_slip * 100, 1),
                        'quality_score': None,
                        'num_bookmakers': num_bookmakers,
                        'fail_reason': 'net_too_low' if net < MIN_PROFIT_THRESHOLD else 'net_too_high',
                    })
            elif MIN_PROFIT_THRESHOLD <= net <= MAX_PROFIT_THRESHOLD:
                odds_range = max(mh, md, ma) - min(mh, md, ma)
                quality = _compute_quality_score(
                    net, num_bookmakers, hours_to_kickoff or 999,
                    'h2h', odds_range
                )
                if quality < MIN_QUALITY_SCORE:
                    _dbg_quality_filtered += 1
                elif quality >= MIN_QUALITY_SCORE:
                    opportunities.append({
                        'match': match_name,
                        'sport_key': sport_key,
                        'date': match_date,
                        'hours_to_kickoff': round(hours_to_kickoff, 1) if hours_to_kickoff else None,
                        'market': 'Match Odds (1X2)',
                        'odds': {'1': mh, 'X': md, '2': ma},
                        'bookmakers': {'1': best_home['bookmaker'], 'X': best_draw['bookmaker'], '2': best_away['bookmaker']},
                        'implied_prob': round((1/mh + 1/md + 1/ma) * 100, 2),
                        'profit_margin': round(gross, 2),
                        'profit_margin_net': round(net, 2),
                        'slippage_pct': round(avg_slip * 100, 1),
                        'quality_score': quality,
                        'captured_at': captured_at.isoformat(),
                        'num_bookmakers': num_bookmakers,
                    })

        # ── Check Totals ──
        for point, out in best_totals.items():
            po, pu = out['Over']['price'], out['Under']['price']
            if po > 1.0 and pu > 1.0:
                raw_implied_t = (1/po) + (1/pu)
                gross, net, avg_slip = _compute_net_profit(
                    [po, pu],
                    [out['Over']['bookmaker'], out['Under']['bookmaker']],
                    sport_key
                )
                all_edge_candidates.append({
                    'match': match_name, 'sport_key': sport_key,
                    'date': match_date,
                    'hours_to_kickoff': round(hours_to_kickoff, 1) if hours_to_kickoff else None,
                    'market': f'Over/Under ({point})',
                    'odds': {'1': po, '2': pu},
                    'bookmakers': {'1': out['Over']['bookmaker'], '2': out['Under']['bookmaker']},
                    'implied_prob': round(raw_implied_t * 100, 2),
                    'profit_margin': round(gross, 2),
                    'profit_margin_net': round(net, 2),
                    'slippage_pct': round(avg_slip * 100, 1),
                    'quality_score': None,
                    'num_bookmakers': num_bookmakers,
                })
                if raw_implied_t < 1.0:
                    _dbg_raw_opps += 1
                    logger.debug(f"  Totals({point}) raw: {match_name} | implied={raw_implied_t*100:.1f}% | gross={gross:.2f}% | net={net:.2f}% | books={out['Over']['bookmaker']}/{out['Under']['bookmaker']}")
                if net < MIN_PROFIT_THRESHOLD or net > MAX_PROFIT_THRESHOLD:
                    if raw_implied_t < 1.0:
                        _dbg_net_filtered += 1
                        near_misses.append({
                            'match': match_name, 'sport_key': sport_key,
                            'date': match_date,
                            'hours_to_kickoff': round(hours_to_kickoff, 1) if hours_to_kickoff else None,
                            'market': f'Over/Under ({point})',
                            'odds': {'1': po, '2': pu},
                            'bookmakers': {'1': out['Over']['bookmaker'], '2': out['Under']['bookmaker']},
                            'implied_prob': round(raw_implied_t * 100, 2),
                            'profit_margin': round(gross, 2),
                            'profit_margin_net': round(net, 2),
                            'slippage_pct': round(avg_slip * 100, 1),
                            'quality_score': None,
                            'num_bookmakers': num_bookmakers,
                            'fail_reason': 'net_too_low' if net < MIN_PROFIT_THRESHOLD else 'net_too_high',
                        })
                elif MIN_PROFIT_THRESHOLD <= net <= MAX_PROFIT_THRESHOLD:
                    odds_range = abs(po - pu)
                    quality = _compute_quality_score(
                        net, num_bookmakers, hours_to_kickoff or 999,
                        'totals', odds_range
                    )
                    if quality < MIN_QUALITY_SCORE:
                        _dbg_quality_filtered += 1
                    elif quality >= MIN_QUALITY_SCORE:
                        opportunities.append({
                            'match': match_name,
                            'sport_key': sport_key,
                            'date': match_date,
                            'hours_to_kickoff': round(hours_to_kickoff, 1) if hours_to_kickoff else None,
                            'market': f'Over/Under ({point})',
                            'odds': {'1': po, '2': pu},
                            'bookmakers': {'1': out['Over']['bookmaker'], '2': out['Under']['bookmaker']},
                            'implied_prob': round((1/po + 1/pu) * 100, 2),
                            'profit_margin': round(gross, 2),
                            'profit_margin_net': round(net, 2),
                            'slippage_pct': round(avg_slip * 100, 1),
                            'quality_score': quality,
                            'captured_at': captured_at.isoformat(),
                            'num_bookmakers': num_bookmakers,
                            'is_2_way': True,
                            'labels': {'1': f'Over {point}', '2': f'Under {point}'},
                        })

        # ── Check Spreads ──
        for key, out in best_spreads.items():
            ph, pa = out['Home']['price'], out['Away']['price']
            if ph > 1.0 and pa > 1.0:
                raw_implied_s = (1/ph) + (1/pa)
                gross, net, avg_slip = _compute_net_profit(
                    [ph, pa],
                    [out['Home']['bookmaker'], out['Away']['bookmaker']],
                    sport_key
                )
                h_point = out['Home']['point']
                a_point = out['Away']['point']
                all_edge_candidates.append({
                    'match': match_name, 'sport_key': sport_key,
                    'date': match_date,
                    'hours_to_kickoff': round(hours_to_kickoff, 1) if hours_to_kickoff else None,
                    'market': f'Handicap ({h_point:+g}/{a_point:+g})',
                    'odds': {'1': ph, '2': pa},
                    'bookmakers': {'1': out['Home']['bookmaker'], '2': out['Away']['bookmaker']},
                    'implied_prob': round(raw_implied_s * 100, 2),
                    'profit_margin': round(gross, 2),
                    'profit_margin_net': round(net, 2),
                    'slippage_pct': round(avg_slip * 100, 1),
                    'quality_score': None,
                    'num_bookmakers': num_bookmakers,
                })
                if raw_implied_s < 1.0:
                    _dbg_raw_opps += 1
                    logger.debug(f"  Spreads raw: {match_name} | implied={raw_implied_s*100:.1f}% | gross={gross:.2f}% | net={net:.2f}% | books={out['Home']['bookmaker']}/{out['Away']['bookmaker']}")
                if net < MIN_PROFIT_THRESHOLD or net > MAX_PROFIT_THRESHOLD:
                    if raw_implied_s < 1.0:
                        _dbg_net_filtered += 1
                elif MIN_PROFIT_THRESHOLD <= net <= MAX_PROFIT_THRESHOLD:
                    odds_range = abs(ph - pa)
                    quality = _compute_quality_score(
                        net, num_bookmakers, hours_to_kickoff or 999,
                        'spreads', odds_range
                    )
                    if quality < MIN_QUALITY_SCORE:
                        _dbg_quality_filtered += 1
                    elif quality >= MIN_QUALITY_SCORE:
                        h_point = out['Home']['point']
                        a_point = out['Away']['point']
                        opportunities.append({
                            'match': match_name,
                            'sport_key': sport_key,
                            'date': match_date,
                            'hours_to_kickoff': round(hours_to_kickoff, 1) if hours_to_kickoff else None,
                            'market': 'Handicap (Spreads)',
                            'odds': {'1': ph, '2': pa},
                            'bookmakers': {'1': out['Home']['bookmaker'], '2': out['Away']['bookmaker']},
                            'implied_prob': round((1/ph + 1/pa) * 100, 2),
                            'profit_margin': round(gross, 2),
                            'profit_margin_net': round(net, 2),
                            'slippage_pct': round(avg_slip * 100, 1),
                            'quality_score': quality,
                            'captured_at': captured_at.isoformat(),
                            'num_bookmakers': num_bookmakers,
                            'is_2_way': True,
                            'labels': {'1': f'Home {h_point:+g}', '2': f'Away {a_point:+g}'},
                        })

    # Sort by net profit (after costs) descending
    opportunities = sorted(opportunities, key=lambda x: x['profit_margin_net'], reverse=True)

    pipeline = {
        'total_matches': _dbg_total_matches,
        'soccer': _dbg_soccer,
        'future': _dbg_not_live,
        'within_7d': _dbg_within_7d,
        'raw_opps': _dbg_raw_opps,
        'failed_net': _dbg_net_filtered,
        'failed_quality': _dbg_quality_filtered,
        'published': len(opportunities),
        'min_profit_pct': MIN_PROFIT_THRESHOLD,
        'min_quality': MIN_QUALITY_SCORE,
        'credits_remaining': int(total_credits_remaining) if isinstance(total_credits_remaining, str) and total_credits_remaining.isdigit() else None,
    }

    # Top 5 closest-to-arb matches (lowest implied prob = closest to surebet), deduped
    opportunity_keys = {(o['match'], o['market']) for o in opportunities}
    near_miss_keys = {(n['match'], n['market']) for n in near_misses}
    edge_opportunities = sorted(
        [e for e in all_edge_candidates
         if (e['match'], e['market']) not in near_miss_keys
         and (e['match'], e['market']) not in opportunity_keys],
        key=lambda x: x['implied_prob']
    )[:5]

    logger.info(
        f"Arbitrage pipeline: {_dbg_total_matches} total | "
        f"{_dbg_soccer} soccer | {_dbg_not_live} future | "
        f"{_dbg_within_7d} within-7d | "
        f"{_dbg_raw_opps} raw | "
        f"{_dbg_net_filtered} failed-net | "
        f"{_dbg_quality_filtered} failed-quality | "
        f"{len(opportunities)} published "
        f"(Q>={MIN_QUALITY_SCORE}, Net>={MIN_PROFIT_THRESHOLD}%)"
    )
    return {'opportunities': opportunities, 'near_misses': near_misses, 'edge_opportunities': edge_opportunities, 'pipeline': pipeline}


# ══════════════════════════════════════════════════════════════════════════════
# Executability Verification (optional 2nd scan)
# ══════════════════════════════════════════════════════════════════════════════

def verify_opportunity_survival(opportunity, delay_seconds=45):
    """
    Check if an arbitrage opportunity still exists after a delay.
    Makes a 2nd API call to verify the odds haven't moved.

    Returns dict with survival data, or None if expired.
    This costs an extra API credit — use sparingly (only for top-N opps).
    """
    import asyncio

    API_KEY = os.getenv('THE_ODDS_API_KEY')
    if not API_KEY:
        return None

    match_name = opportunity.get('match', '')
    market = opportunity.get('market', '')
    odds = opportunity.get('odds', {})

    time.sleep(delay_seconds)

    # Build a fresh query for the specific match's league
    sport_key = opportunity.get('sport_key', 'upcoming')
    url = (f'https://api.the-odds-api.com/v4/sports/{sport_key}/odds/'
           f'?apiKey={API_KEY}&regions={REGIONS}&markets={MARKETS}')

    headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/91.0.4472.124 Safari/537.36')
    }

    try:
        response = _fetch_odds_api(url, headers)
    except Exception as e:
        logger.warning(f"Survival check failed (connection): {e}")
        return {'survived': False, 'reason': 'connection_error'}

    if response.status_code != 200:
        logger.warning(f"Survival check failed (HTTP {response.status_code})")
        return {'survived': False, 'reason': f'http_{response.status_code}'}

    data = response.json()
    verified_at = datetime.now(timezone.utc)

    # Find the same match in fresh data
    for match in data:
        home = match.get('home_team', '')
        away = match.get('away_team', '')
        if f"{home} vs {away}" != match_name:
            continue

        # Check if similar odds still exist
        current_best = {}
        for bookie in match.get('bookmakers', []):
            for mkt in bookie.get('markets', []):
                key = mkt.get('key')
                if key == 'h2h':
                    for outcome in mkt.get('outcomes', []):
                        name = outcome.get('name')
                        price = outcome.get('price', 0.0)
                        if name not in current_best or price > current_best[name]:
                            current_best[name] = price

        # Compare with original odds
        odds_still_alive = True
        for leg, orig_odd in odds.items():
            leg_name = leg
            if leg == '1':
                leg_name = home
            elif leg == '2':
                leg_name = away
            elif leg == 'X':
                leg_name = 'Draw'

            current_odd = current_best.get(leg_name, 0)
            if current_odd <= 0 or (current_odd / orig_odd) < 0.90:
                odds_still_alive = False
                break

        return {
            'survived': odds_still_alive,
            'verified_at': verified_at.isoformat(),
            'delay_seconds': delay_seconds,
        }

    return {'survived': False, 'reason': 'match_not_found'}
