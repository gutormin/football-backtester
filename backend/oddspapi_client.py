"""
Cliente para a OddsPapi (https://oddspapi.io).

Busca fixtures e odds e converte para o mesmo formato que o scanner de
arbitragem já espera (formato compatível com The Odds API):

    {
      'home_team': str,
      'away_team': str,
      'commence_time': 'YYYY-MM-DDTHH:MM:SSZ',
      'bookmakers': [
          {
            'title': str,
            'markets': [
                {'key': 'h2h', 'outcomes': [{'name': 'Home'|'Draw'|'Away'|team, 'price': float}]},
                {'key': 'totals', 'outcomes': [{'name': 'Over'|'Under', 'price': float, 'point': float}]},
            ]
          },
          ...
      ]
    }

Docs OddsPapi:
  - Auth: query param ?apiKey=...
  - GET /v4/fixtures?sportId=10&from=YYYY-MM-DD&to=YYYY-MM-DD
  - GET /v4/odds?fixtureId=ID
  - Mercado 101 = Full Time Result (1X2): 101=Home, 102=Draw, 103=Away
  - Preço aninhado: outcomes[outcomeId].players["0"].price
"""

import os
import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.oddspapi.io/v4"
SOCCER_SPORT_ID = 10

# IDs de mercado da OddsPapi
MARKET_1X2 = "101"          # Full Time Result
MARKET_OVER_UNDER = "102"   # (pode variar — confirmar via /markets)

# Outcomes do mercado 1X2
OUTCOME_HOME = "101"
OUTCOME_DRAW = "102"
OUTCOME_AWAY = "103"


def get_oddspapi_key():
    """Carrega a chave da OddsPapi do ambiente ou config."""
    key = os.getenv('ODDSPAPI_API_KEY')
    if key:
        return key
    # Fallback: config file
    try:
        import json
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'data', 'oddspapi_config.json'
        )
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return json.load(f).get('apiKey', '')
    except Exception:
        pass
    return ''


def _price(outcome_obj):
    """Extrai o preço do formato aninhado da OddsPapi."""
    try:
        return float(outcome_obj.get('players', {}).get('0', {}).get('price', 0))
    except (ValueError, TypeError, AttributeError):
        return 0.0


def fetch_fixtures(api_key, days_ahead=7):
    """Busca fixtures de futebol dos próximos N dias."""
    today = datetime.now().strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=min(days_ahead, 10))).strftime('%Y-%m-%d')

    resp = requests.get(f"{BASE_URL}/fixtures", params={
        "apiKey": api_key,
        "sportId": SOCCER_SPORT_ID,
        "from": today,
        "to": end,
    }, timeout=20)

    if resp.status_code == 401:
        raise PermissionError("Chave da OddsPapi inválida.")
    if resp.status_code == 429:
        raise RuntimeError("Limite de requisições da OddsPapi atingido (free tier: 100/hora).")
    resp.raise_for_status()

    return resp.json()


def fetch_odds_for_fixture(api_key, fixture_id):
    """Busca odds de um fixture específico."""
    resp = requests.get(f"{BASE_URL}/odds", params={
        "apiKey": api_key,
        "fixtureId": fixture_id,
    }, timeout=20)
    if resp.status_code != 200:
        return None
    return resp.json()


def _convert_fixture_to_odds_api_format(fixture, odds_data):
    """
    Converte um fixture + odds da OddsPapi para o formato The Odds API
    que o scanner de arbitragem já entende.
    """
    home = fixture.get('participant1Name', '')
    away = fixture.get('participant2Name', '')
    start = fixture.get('startTime') or fixture.get('date')

    # Normalizar data para formato ISO com Z
    commence_time = None
    if start:
        try:
            # startTime já vem como ISO; garantir sufixo Z
            if start.endswith('Z'):
                commence_time = start[:19] + 'Z'
            else:
                dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                commence_time = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            commence_time = start

    bookmaker_odds = (odds_data or {}).get('bookmakerOdds', {})
    bookmakers = []

    for slug, book_data in bookmaker_odds.items():
        markets_raw = book_data.get('markets', {})
        markets_converted = []

        # ── Mercado 1X2 (h2h) ──
        if MARKET_1X2 in markets_raw:
            outcomes_raw = markets_raw[MARKET_1X2].get('outcomes', {})
            h = _price(outcomes_raw.get(OUTCOME_HOME, {}))
            d = _price(outcomes_raw.get(OUTCOME_DRAW, {}))
            a = _price(outcomes_raw.get(OUTCOME_AWAY, {}))
            if h > 1.0 and a > 1.0:
                h2h_outcomes = [
                    {'name': home, 'price': h},
                    {'name': away, 'price': a},
                ]
                if d > 1.0:
                    h2h_outcomes.insert(1, {'name': 'Draw', 'price': d})
                markets_converted.append({'key': 'h2h', 'outcomes': h2h_outcomes})

        if markets_converted:
            bookmakers.append({
                'title': slug,
                'markets': markets_converted,
            })

    return {
        'home_team': home,
        'away_team': away,
        'commence_time': commence_time,
        'bookmakers': bookmakers,
    }


def fetch_oddspapi_matches(api_key=None, days_ahead=7, category_filter=None, max_fixtures=60):
    """
    Busca partidas com odds da OddsPapi e retorna no formato The Odds API.

    Args:
        api_key: chave da OddsPapi (usa env/config se None)
        days_ahead: janela de dias
        category_filter: filtro por categoria (ex: 'brazil') ou None para todas
        max_fixtures: limite de fixtures a buscar odds (para não estourar rate limit)

    Returns:
        (matches, error). matches é lista no formato The Odds API.
    """
    if not api_key:
        api_key = get_oddspapi_key()
    if not api_key:
        return [], {'error': 'no_api_key', 'message': 'Chave da OddsPapi não configurada. Defina ODDSPAPI_API_KEY.'}

    try:
        fixtures = fetch_fixtures(api_key, days_ahead=days_ahead)
    except PermissionError as e:
        return [], {'error': 'invalid_api_key', 'message': str(e)}
    except RuntimeError as e:
        return [], {'error': 'rate_limit', 'message': str(e)}
    except Exception as e:
        logger.error(f"OddsPapi fixtures error: {e}")
        return [], {'error': 'fetch_error', 'message': str(e)}

    # Filtrar por fixtures com odds
    with_odds = [f for f in fixtures if f.get('hasOdds', False)]

    # Filtro de categoria opcional
    if category_filter:
        cf = category_filter.lower()
        with_odds = [f for f in with_odds if cf in (f.get('categorySlug', '') or '').lower()]

    with_odds = with_odds[:max_fixtures]

    matches = []
    for fixture in with_odds:
        fid = fixture.get('fixtureId') or fixture.get('id')
        if not fid:
            continue
        try:
            odds_data = fetch_odds_for_fixture(api_key, fid)
            if odds_data:
                converted = _convert_fixture_to_odds_api_format(fixture, odds_data)
                if converted['bookmakers']:  # só incluir se tem odds
                    matches.append(converted)
        except Exception as e:
            logger.warning(f"OddsPapi odds error for fixture {fid}: {e}")
            continue

    return matches, None
