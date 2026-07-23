import os
import json
import logging
import requests
from datetime import datetime, timedelta, timezone
from .api_utils import retry_with_backoff

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
TRACKER_FILE  = os.path.join(DATA_DIR, 'live_odds_tracker.json')
BASELINE_FILE = os.path.join(DATA_DIR, 'odds_baseline.json')   # ← NOVO: imutável

from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv('THE_ODDS_API_KEY')
SPORT   = 'upcoming'
REGIONS = 'eu,uk,us'
MARKETS = 'h2h,spreads,totals'

# ─────────────────────────────────────────────────────────────────────────────
#  BASELINE IMUTÁVEL
#  Cada entrada é gravada UMA única vez quando a odd é vista pela primeira vez.
#  Nunca é sobrescrita — sobrevive a qualquer restart do servidor.
# ─────────────────────────────────────────────────────────────────────────────

def _load_baseline() -> dict:
    """Carrega o arquivo de baseline. Retorna {} se não existir ou inválido."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(BASELINE_FILE):
        return {}
    try:
        with open(BASELINE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_baseline(baseline: dict) -> None:
    """Persiste a baseline em disco."""
    try:
        with open(BASELINE_FILE, 'w', encoding='utf-8') as f:
            json.dump(baseline, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar baseline: {e}", exc_info=True)


def get_or_set_opening(baseline: dict, match_id: str, comp_key: str,
                       price: float, commence_time: str,
                       title: str, sport_key: str) -> float:
    """
    Retorna a odd de abertura (primeira vez que foi vista) para este par match+mercado.
    Se ainda não existe, registra 'price' como opening AGORA e persiste.

    Args:
        baseline:       dict carregado de BASELINE_FILE (mutado in-place).
        match_id:       ID único do jogo vindo da API.
        comp_key:       Chave composta do mercado (ex: "h2h_home").
        price:          Preço atual retornado pela API.
        commence_time:  ISO 8601 do início do jogo.
        title:          "HomeTeam vs AwayTeam".
        sport_key:      Liga da API.

    Returns:
        float — opening original (imutável).
    """
    entry_key = f"{match_id}::{comp_key}"

    if entry_key not in baseline:
        baseline[entry_key] = {
            'opening': price,
            'first_seen': datetime.now(timezone.utc).isoformat(),
            'match_id': match_id,
            'comp_key': comp_key,
            'commence_time': commence_time,
            'title': title,
            'sport_key': sport_key,
        }
        # Persiste imediatamente para não perder caso o processo morra
        _save_baseline(baseline)

    return baseline[entry_key]['opening']


# ─────────────────────────────────────────────────────────────────────────────
#  TRACKER PRINCIPAL (estado corrente das odds)
# ─────────────────────────────────────────────────────────────────────────────

def load_tracker_data() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(TRACKER_FILE):
        return {}
    try:
        with open(TRACKER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_tracker_data(data: dict) -> None:
    try:
        with open(TRACKER_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar tracker: {e}", exc_info=True)


from .odds_api_mappings import SPORT_TO_LEAGUE as SPORT_LEAGUE_MAP, UNMAPPED_LEAGUE_CODE


def map_sport_to_league_code(sport_key: str) -> str:
    """Converte um sport_key da The Odds API no league_code interno do sistema.

    Função canônica: é o único lugar que decide como um sport_key vira um
    league_code. Ligas não mapeadas caem em UNMAPPED_LEAGUE_CODE (mesmo valor
    nas duas pontas), evitando que a chave 'league_code|market' do cache do
    Radar Ao Vivo divirja da chave gravada pelo Laboratório.

    Args:
        sport_key: chave da liga vinda da The Odds API (ex: 'soccer_epl').

    Returns:
        Código interno da liga (ex: 'E0') ou 'OUTROS' se não mapeada.
    """
    if not sport_key:
        return UNMAPPED_LEAGUE_CODE
    return SPORT_LEAGUE_MAP.get(sport_key, UNMAPPED_LEAGUE_CODE)


MAX_STEAM_HISTORY_COUNT = 500
MAX_STEAM_HISTORY_AGE_DAYS = 30


def add_alert_to_history(alert_data: dict) -> None:
    history_file = os.path.join(DATA_DIR, 'live_steam_moves_history.json')
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            history = []

    unique_id = f"{alert_data['match']}_{alert_data['bookmaker']}_{alert_data['market']}"
    for item in history:
        if item.get('unique_id') == unique_id:
            return   # alerta já registrado — não duplicar

    alert_data['unique_id'] = unique_id
    alert_data['created_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    history.append(alert_data)

    # Prune: remove resolved alerts older than MAX_STEAM_HISTORY_AGE_DAYS, cap at MAX_STEAM_HISTORY_COUNT
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_STEAM_HISTORY_AGE_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    history = [h for h in history if not (h.get('resolved') and h.get('created_at', '') < cutoff)]
    if len(history) > MAX_STEAM_HISTORY_COUNT:
        history = history[-MAX_STEAM_HISTORY_COUNT:]

    try:
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar histórico: {e}", exc_info=True)


def cleanup_old_matches(data: dict) -> None:
    """Remove partidas que já começaram há mais de 12 horas."""
    now = datetime.now(timezone.utc)
    to_delete = []
    for match_id, match_data in data.items():
        try:
            commence_time = datetime.fromisoformat(
                match_data['commence_time'].replace('Z', '+00:00')
            )
            if now > commence_time + timedelta(hours=12):
                to_delete.append(match_id)
        except Exception:
            to_delete.append(match_id)

    for md in to_delete:
        del data[md]


def normalize_market_key(market_key: str, outcome_name: str,
                          home_team: str, away_team: str) -> str:
    if market_key == 'h2h':
        if outcome_name == home_team:   return 'home'
        elif outcome_name == away_team: return 'away'
        else:                           return 'draw'
    elif market_key == 'totals':
        if outcome_name.lower() == 'over':  return 'over25'
        elif outcome_name.lower() == 'under': return 'under25'
    elif market_key == 'spreads':
        if outcome_name == home_team:   return 'home_spread'
        elif outcome_name == away_team: return 'away_spread'
    elif market_key == 'btts':
        if outcome_name.lower() == 'yes': return 'btts_yes'
        elif outcome_name.lower() == 'no': return 'btts_no'
    elif market_key == 'draw_no_bet':
        if outcome_name == home_team: return 'home_dnb'
        elif outcome_name == away_team: return 'away_dnb'
    return outcome_name


# ─────────────────────────────────────────────────────────────────────────────
#  CICLO DE COLETA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

@retry_with_backoff(max_retries=3, base_delay=1.0)
def _fetch_odds(url):
    return requests.get(url, timeout=15)


def fetch_and_update_live_odds() -> None:
    logger.info("Iniciando varredura The Odds API...")

    url = (
        f'https://api.the-odds-api.com/v4/sports/{SPORT}/odds/'
        f'?apiKey={API_KEY}&regions={REGIONS}&markets={MARKETS}'
    )

    try:
        response = _fetch_odds(url)
        if response.status_code == 401:
            try:
                body = response.json()
                error_code = body.get('error_code', '')
            except Exception:
                error_code = ''
            if error_code == 'OUT_OF_USAGE_CREDITS':
                logger.error("Smart Money: Créditos da The Odds API esgotados. O plano gratuito renova mensalmente.")
            else:
                logger.error(f"Smart Money: Chave de API inválida (HTTP 401). Verifique THE_ODDS_API_KEY.")
            return
        if response.status_code != 200:
            logger.error(f"Smart Money API Error {response.status_code}: {response.text}")
            return

        matches = response.json()

        # Carrega estado corrente e baseline imutável
        data     = load_tracker_data()
        baseline = _load_baseline()

        cleanup_old_matches(data)

        updated_count = 0
        new_count     = 0
        alert_count   = 0
        now_str = datetime.now(timezone.utc).isoformat()

        # Flag para saber se a baseline foi modificada (evita writes desnecessários)
        baseline_dirty = False

        for match in matches:
            match_id      = match['id']
            home_team     = match['home_team']
            away_team     = match['away_team']
            sport_key     = match['sport_key']
            commence_time = match['commence_time']

            if 'soccer' not in sport_key.lower():
                continue

            # ── Estado corrente do jogo ──────────────────────────────────────
            if match_id not in data:
                data[match_id] = {
                    'title':         f"{home_team} vs {away_team}",
                    'sport':         sport_key,
                    'commence_time': commence_time,
                    'bookmakers':    {},
                }
                new_count += 1

            match_entry = data[match_id]

            for bookie in match.get('bookmakers', []):
                bookie_name = bookie['title']
                if bookie_name not in match_entry['bookmakers']:
                    match_entry['bookmakers'][bookie_name] = {}

                bookie_entry = match_entry['bookmakers'][bookie_name]

                for market in bookie.get('markets', []):
                    market_key = market['key']

                    for outcome in market.get('outcomes', []):
                        outcome_name = outcome['name']
                        price        = outcome['price']

                        norm_market = normalize_market_key(
                            market_key, outcome_name, home_team, away_team
                        )
                        comp_key = f"{market_key}_{norm_market}"

                        # ── BASELINE IMUTÁVEL: obtém (ou registra) opening ──
                        prev_baseline_len = len(baseline)
                        opening = get_or_set_opening(
                            baseline, match_id, comp_key, price,
                            commence_time,
                            f"{home_team} vs {away_team}",
                            sport_key
                        )
                        if len(baseline) != prev_baseline_len:
                            baseline_dirty = True

                        # ── Estado corrente por bookmaker ───────────────────
                        if comp_key not in bookie_entry:
                            bookie_entry[comp_key] = {
                                'market_type':  market_key,
                                'outcome_name': outcome_name,
                                'norm_market':  norm_market,
                                'opening':      opening,   # usa baseline!
                                'current':      price,
                                'last_updated': now_str,
                                'first_seen':   now_str,
                                'telegram_sent': False,
                                'updates': [
                                    {'timestamp': now_str, 'price': price}
                                ]
                            }
                        else:
                            # Sempre sincroniza o opening com a baseline
                            bookie_entry[comp_key]['opening'] = opening

                            # Atualiza current se mudou
                            if bookie_entry[comp_key]['current'] != price:
                                bookie_entry[comp_key]['current']      = price
                                bookie_entry[comp_key]['last_updated'] = now_str
                                
                                if 'updates' not in bookie_entry[comp_key]:
                                    # Fallback: se não existia, inicia com o opening antigo e o novo current
                                    bookie_entry[comp_key]['updates'] = [
                                        {'timestamp': bookie_entry[comp_key].get('first_seen', now_str), 'price': opening},
                                        {'timestamp': now_str, 'price': price}
                                    ]
                                else:
                                    bookie_entry[comp_key]['updates'].append(
                                        {'timestamp': now_str, 'price': price}
                                    )
                                    # Limitar histórico para evitar crescimento desordenado
                                    if len(bookie_entry[comp_key]['updates']) > 30:
                                        bookie_entry[comp_key]['updates'] = bookie_entry[comp_key]['updates'][-30:]
                                
                                updated_count += 1

                        # ── DETECÇÃO DE STEAM MOVE ──────────────────────────
                        current_in_entry = bookie_entry[comp_key]['current']
                        if (opening > 1.0
                                and current_in_entry > 0.0
                                and current_in_entry < opening):

                            drop_pct = ((opening / current_in_entry) - 1.0) * 100

                            # Determinar se a partida está In-Play e calcular minutos decorridos
                            is_in_play = False
                            elapsed_minutes = 0.0
                            try:
                                commence_dt = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                                now_utc = datetime.now(timezone.utc)
                                if now_utc > commence_dt:
                                    is_in_play = True
                                    elapsed_minutes = (now_utc - commence_dt).total_seconds() / 60.0
                                    if elapsed_minutes > 95.0:
                                        elapsed_minutes = 95.0
                            except Exception:
                                pass

                            # Calcular cotação teórica com decaimento natural e drop ajustado
                            from .smart_money import calculate_time_decay_adjusted_drop
                            odd_decay, adjusted_drop_pct = calculate_time_decay_adjusted_drop(
                                norm_market=norm_market,
                                opening=opening,
                                current=current_in_entry,
                                elapsed_minutes=elapsed_minutes
                            )

                            # Se estiver In-Play, o gatilho usa o drop ajustado, caso contrário o drop nominal
                            trigger_drop = adjusted_drop_pct if is_in_play else drop_pct

                            if trigger_drop >= 5.0:
                                try:
                                    from .smart_money import calculate_confidence_score, classify_drop_profile, calculate_odds_metrics
                                    mapped_league = map_sport_to_league_code(sport_key)
                                    score, confidence_level, tier_name = calculate_confidence_score(
                                        trigger_drop, mapped_league
                                    )
                                    sharpness_score, profile_type = classify_drop_profile(
                                        drop_pct=trigger_drop,
                                        league_identifier=mapped_league,
                                        commence_time_str=commence_time,
                                        bookmaker_name=bookie_name,
                                        match_entry=match_entry,
                                        comp_key=comp_key
                                    )
                                    
                                    # Calcular velocidade e aceleração
                                    metrics = calculate_odds_metrics(bookie_entry[comp_key].get('updates', []))

                                    # Formata data local do jogo
                                    try:
                                        dt = datetime.fromisoformat(
                                            commence_time.replace('Z', '+00:00')
                                        )
                                        date_str = dt.astimezone().strftime('%d/%m %H:%M')
                                    except Exception:
                                        date_str = commence_time

                                    alert_entry = {
                                        'date':             date_str,
                                        'match':            match_entry.get('title', 'Desconhecido'),
                                        'league_code':      mapped_league,
                                        'bookmaker':        bookie_name,
                                        'market':           norm_market,
                                        'opening_odd':      opening,
                                        'current_odd':      current_in_entry,
                                        'drop_pct':         round(drop_pct, 1),
                                        'is_in_play':       is_in_play,
                                        'elapsed_minutes':  round(elapsed_minutes),
                                        'adjusted_drop_pct': round(adjusted_drop_pct, 1),
                                        'confidence_score': score,
                                        'confidence_level': confidence_level,
                                        'liquidity_tier':   tier_name,
                                        'sharpness_score':  sharpness_score,
                                        'profile_type':     profile_type,
                                        'velocity':         metrics['velocity_recent'],
                                        'acceleration_ratio': metrics['acceleration_ratio'],
                                        'acceleration_text': metrics['acceleration_text'],
                                        'won':              None,
                                        'profit':           0.0,
                                        'stake_value':      10.0,
                                        'resolved':         False,
                                        'source':           'live',
                                    }
                                    add_alert_to_history(alert_entry)

                                    # CLV tracking — registra odd de detecção para calcular
                                    # se batemos o fechamento quando o jogo começar
                                    try:
                                        from .smart_money import register_detection_for_clv
                                        register_detection_for_clv(
                                            harness_match_id=match_entry.get('title', match_id),
                                            bookmaker=bookie_name,
                                            market=norm_market,
                                            detection_odd=current_in_entry,
                                            detection_time=now_str,
                                            league_code=mapped_league,
                                        )
                                    except Exception:
                                        pass  # CLV tracking is non-critical

                                    # Telegram — envia apenas uma vez por par match+mercado
                                    if not bookie_entry[comp_key].get('telegram_sent', False):
                                        try:
                                            from .telegram_bot import (
                                                send_telegram_message,
                                                format_telegram_smart_money_tip,
                                            )
                                            msg = format_telegram_smart_money_tip(
                                                match_entry.get('title', 'Desconhecido'),
                                                date_str,
                                                bookie_name,
                                                norm_market.upper(),
                                                opening,
                                                current_in_entry,
                                                drop_pct,
                                                confidence_score=score,
                                                confidence_level=confidence_level,
                                                liquidity_tier=tier_name,
                                                sharpness_score=sharpness_score,
                                                profile_type=profile_type,
                                                velocity=metrics['velocity_recent'],
                                                acceleration_ratio=metrics['acceleration_ratio'],
                                                acceleration_text=metrics['acceleration_text'],
                                                is_in_play=is_in_play,
                                                elapsed_minutes=round(elapsed_minutes),
                                                adjusted_drop_pct=round(adjusted_drop_pct, 1)
                                            )
                                            send_telegram_message(msg)
                                            bookie_entry[comp_key]['telegram_sent'] = True
                                            alert_count += 1
                                            logger.info(
                                                f"Telegram enviado: "
                                                f"{match_entry.get('title')} | {norm_market.upper()} | "
                                                f"Drop {drop_pct:.1f}% "
                                                f"(Opening: {opening} -> Atual: {current_in_entry})"
                                            )
                                        except Exception as tg_err:
                                            logger.error(f"Telegram erro: {tg_err}")

                                except Exception as e:
                                    logger.error(f"Erro ao processar alerta: {e}", exc_info=True)

        save_tracker_data(data)

        # Só salva baseline se houve novidades (evita I/O desnecessário)
        if baseline_dirty:
            _save_baseline(baseline)

        logger.info(
            f"Concluído. "
            f"{new_count} novos jogos | {updated_count} odds atualizadas | "
            f"{alert_count} alertas Telegram enviados."
        )

        # Resolve resultados de steam moves históricos
        resolve_historical_steam_results()

        # Atualiza CLV para jogos que já começaram
        try:
            from .smart_money import update_closing_odds_for_kickoffs
            clv_resolved = update_closing_odds_for_kickoffs(data)
            if clv_resolved > 0:
                logger.info(f"CLV: {clv_resolved} entradas tiveram odd de fechamento registrada.")
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Exceção durante varredura: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
#  DIAGNÓSTICO: mostra quantas baselines existem e stats rápidas
# ─────────────────────────────────────────────────────────────────────────────

def get_baseline_stats() -> dict:
    """
    Retorna estatísticas da baseline para diagnóstico via API.
    """
    baseline = _load_baseline()
    total = len(baseline)
    matches = set()
    oldest_dt = None
    newest_dt = None

    for entry in baseline.values():
        matches.add(entry.get('match_id', ''))
        first_seen_str = entry.get('first_seen', '')
        try:
            dt = datetime.fromisoformat(first_seen_str)
            if oldest_dt is None or dt < oldest_dt:
                oldest_dt = dt
            if newest_dt is None or dt > newest_dt:
                newest_dt = dt
        except Exception:
            pass

    return {
        'total_entries':   total,
        'unique_matches':  len(matches),
        'oldest_entry':    oldest_dt.isoformat() if oldest_dt else None,
        'newest_entry':    newest_dt.isoformat() if newest_dt else None,
        'baseline_file':   BASELINE_FILE,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  RESOLUÇÃO DE RESULTADOS (mantida igual, sem alterações)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_historical_steam_results() -> None:
    logger.info("Iniciando resolução de resultados de Smart Money...")
    history_file = os.path.join(DATA_DIR, 'live_steam_moves_history.json')
    if not os.path.exists(history_file):
        return

    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except Exception:
        return

    updated = False
    loaded_dfs = {}

    try:
        from .data_loader import load_league_data, auto_detect_data_source
    except ImportError:
        from backend.data_loader import load_league_data, auto_detect_data_source

    import pandas as pd

    for item in history:
        if item.get('resolved', False) or item.get('won') is not None:
            continue

        date_str = item.get('date', '')
        try:
            now = datetime.now()
            dt_parts   = date_str.split(' ')
            day_month  = dt_parts[0].split('/')
            hour_min   = dt_parts[1].split(':')
            match_dt = datetime(
                year=now.year,
                month=int(day_month[1]),
                day=int(day_month[0]),
                hour=int(hour_min[0]),
                minute=int(hour_min[1])
            )
            # Aguarda 3h após o início antes de tentar resolver
            if datetime.now() < match_dt + timedelta(hours=3):
                continue
        except Exception:
            continue

        lcode = item.get('league_code')
        if not lcode or lcode == 'OUTROS':
            item['won']      = False
            item['profit']   = -item.get('stake_value', 10.0)
            item['resolved'] = True
            updated = True
            continue

        if lcode not in loaded_dfs:
            try:
                loaded_dfs[lcode] = load_league_data(lcode, start_date='2020-08-01', data_source=auto_detect_data_source(lcode))
            except Exception:
                loaded_dfs[lcode] = None

        df = loaded_dfs[lcode]
        if df is None or df.empty:
            continue

        teams = item.get('match', '').split(' vs ')
        if len(teams) != 2:
            continue
        home_target = teams[0].strip().lower()
        away_target = teams[1].strip().lower()

        match_row = None
        best_score = 0
        for _, row in df.iterrows():
            h_local = str(row.get('HomeTeam', '')).strip().lower()
            a_local = str(row.get('AwayTeam', '')).strip().lower()

            # Exact match (best)
            if h_local == home_target and a_local == away_target:
                match_row = row
                break

            # Score-based fuzzy matching
            score = 0
            # Check containment in both directions
            if h_local in home_target or home_target in h_local:
                score += 3
            if a_local in away_target or away_target in a_local:
                score += 3
            # Partial word overlap
            h_words = set(h_local.split())
            ht_words = set(home_target.split())
            a_words = set(a_local.split())
            at_words = set(away_target.split())
            h_overlap = len(h_words & ht_words)
            a_overlap = len(a_words & at_words)
            score += h_overlap + a_overlap

            if score >= 4 and score > best_score:
                best_score = score
                match_row = row

        # Second pass: exact match preferred over fuzzy
        if match_row is not None and best_score < 6:
            # Medium-confidence match — log it for audit
            logger.info(
                f"SmartMoney resolution fuzzy match (score={best_score}): "
                f"'{home_target}' vs '{away_target}' -> "
                f"'{str(match_row.get('HomeTeam', '')).strip().lower()}' vs "
                f"'{str(match_row.get('AwayTeam', '')).strip().lower()}'"
            )

        if match_row is not None:
            ftr        = match_row.get('FTR')
            fthg       = match_row.get('FTHG')
            ftag       = match_row.get('FTAG')
            hthg       = match_row.get('HTHG')
            htag       = match_row.get('HTAG')
            market     = item.get('market', '').lower()
            stake      = item.get('stake_value', 10.0)
            current_odd = item.get('current_odd', 1.0)

            won = False
            # ── 1X2 ──────────────────────────────────────────────────
            if market in ('home', '1', 'home_dnb'):
                won = (ftr == 'H')
            elif market in ('draw', 'x'):
                won = (ftr == 'D')
            elif market in ('away', '2', 'away_dnb'):
                won = (ftr == 'A')
            elif market == 'lay_home':
                won = (ftr in ('D', 'A'))  # X2
            elif market == 'lay_away':
                won = (ftr in ('H', 'D'))  # 1X
            elif market == 'lay_draw':
                won = (ftr in ('H', 'A'))  # 12

            # ── Over/Under ───────────────────────────────────────────
            elif 'over' in market or 'under' in market:
                if pd.notna(fthg) and pd.notna(ftag):
                    total_goals = fthg + ftag
                    # Extract threshold from market name
                    import re
                    threshold_match = re.search(r'(\d+\.?\d*)', market)
                    if threshold_match:
                        threshold = float(threshold_match.group(1))
                        if 'over' in market:
                            won = total_goals > threshold
                        else:
                            won = total_goals < threshold
                    else:
                        # Fallback: assume Over/Under 2.5
                        if 'over' in market:
                            won = total_goals > 2.5
                        else:
                            won = total_goals < 2.5

            # ── BTTS ─────────────────────────────────────────────────
            elif 'btts' in market:
                if pd.notna(fthg) and pd.notna(ftag):
                    both_scored = (fthg > 0 and ftag > 0)
                    if 'yes' in market or 'sim' in market:
                        won = both_scored
                    elif 'no' in market or 'nao' in market or 'não' in market:
                        won = not both_scored

            # ── HT (Half-Time) markets ────────────────────────────────
            elif 'ht' in market or '_1h' in market:
                ht_market = market.replace('ht_', '').replace('_1h', '')
                if pd.notna(hthg) and pd.notna(htag):
                    if ht_market in ('home', '1'):
                        won = (hthg > htag)
                    elif ht_market in ('draw', 'x'):
                        won = (hthg == htag)
                    elif ht_market in ('away', '2'):
                        won = (hthg < htag)
                    elif 'over' in ht_market:
                        total_ht = hthg + htag
                        won = total_ht > 0.5  # default Over 0.5 HT
                    elif 'under' in ht_market:
                        total_ht = hthg + htag
                        won = total_ht < 1.5  # default Under 1.5 HT

            # ── Correct Score ─────────────────────────────────────────
            elif market.startswith('cs_'):
                if pd.notna(fthg) and pd.notna(ftag):
                    # cs_10 = home 1, away 0
                    try:
                        parts = market.replace('cs_', '')
                        h_goals = int(parts[0])
                        a_goals = int(parts[1])
                        won = (fthg == h_goals and ftag == a_goals)
                    except (ValueError, IndexError):
                        pass

            # ── AH (Asian Handicap) — simplified ─────────────────────
            elif market.startswith('ah_'):
                if pd.notna(fthg) and pd.notna(ftag):
                    try:
                        ah_val = float(market.replace('ah_home_', '').replace('ah_away_', '').replace('ah_', ''))
                        if 'home' in market:
                            won = (fthg - ftag + ah_val > 0)
                        else:
                            won = (ftag - fthg + ah_val > 0)
                    except ValueError:
                        pass

            item['won']      = won
            item['profit']   = round((current_odd - 1.0) * stake if won else -stake, 2)
            item['resolved'] = True
            updated = True
            logger.info(
                f"Resolvido: {item.get('match')} | "
                f"Mercado: {market} | FTR: {ftr} | FTHG: {fthg}-{ftag} | Ganhou: {won}"
            )

    if updated:
        # Prune resolved old entries
        cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_STEAM_HISTORY_AGE_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
        history = [h for h in history if not (h.get('resolved') and h.get('created_at', '') < cutoff)]
        if len(history) > MAX_STEAM_HISTORY_COUNT:
            history = history[-MAX_STEAM_HISTORY_COUNT:]
        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erro ao salvar histórico resolvido: {e}", exc_info=True)


if __name__ == '__main__':
    fetch_and_update_live_odds()
