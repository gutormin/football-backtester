import json
import logging
import math
import os
import sqlite3
import uuid
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)


def _sanitize_for_json(obj):
    """Recursively walk obj, converting numpy types to native Python and NaN/Inf to None."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, np.ndarray):
        return _sanitize_for_json(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj

DB_FILE = "data/backtester.db"
HISTORY_FILE = "data/history_strategies.json"
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_pg_connection():
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    import psycopg2
    return psycopg2.connect(url)

def init_db():
    if DATABASE_URL:
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS strategies (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        type TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        is_tg_active INTEGER DEFAULT 0,
                        parameters TEXT NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao inicializar banco PostgreSQL: {e}", exc_info=True)
        finally:
            conn.close()
        return

    conn = get_db_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_tg_active INTEGER DEFAULT 0,
                parameters TEXT NOT NULL
            )
        """)
        conn.commit()
        
        # Check for legacy migration
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                
                if isinstance(history, list) and len(history) > 0:
                    logger.info(f"Migrando {len(history)} estratégias legadas de {HISTORY_FILE} para o SQLite...")
                    with conn:
                        for s in history:
                            provided_id = s.get("id") or str(uuid.uuid4())
                            name = s.get("name", "Nova Estratégia")
                            stype = s.get("type", "strategy")
                            # Retrospective migration
                            if stype != 'portfolio' and 'strategy_ids' in s.get('params', {}):
                                stype = 'portfolio'
                            created_at = s.get("created_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                            is_tg_active = 1 if s.get("is_tg_active", False) else 0
                            
                            parameters_blob = json.dumps({
                                "params": s.get("params", {}),
                                "summary": s.get("summary", {})
                            }, ensure_ascii=False)
                            
                            conn.execute("""
                                INSERT OR IGNORE INTO strategies (id, name, type, created_at, is_tg_active, parameters)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (provided_id, name, stype, created_at, is_tg_active, parameters_blob))
                    logger.info("Migração concluída com sucesso no SQLite.")
                
                # Rename legacy file to avoid migrating again
                bak_file = HISTORY_FILE + ".bak"
                if os.path.exists(bak_file):
                    try:
                        os.remove(bak_file)
                    except Exception:
                        pass
                os.rename(HISTORY_FILE, bak_file)
                logger.info(f"Arquivo legado renomeado para {bak_file}")
                
            except Exception as e:
                logger.error(f"Erro durante a migração do histórico legado: {e}", exc_info=True)
    finally:
        conn.close()

# Initialize DB on import
init_db()

def load_history():
    init_db()
    if DATABASE_URL:
        conn = get_pg_connection()
        from psycopg2.extras import RealDictCursor
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, name, type, created_at, is_tg_active, parameters FROM strategies ORDER BY created_at DESC")
                rows = cur.fetchall()
                history = []
                for row in rows:
                    try:
                        params_dict = json.loads(row['parameters'])
                    except Exception:
                        params_dict = {}
                    history.append({
                        "id": row['id'],
                        "name": row['name'],
                        "type": row['type'],
                        "created_at": row['created_at'],
                        "is_tg_active": bool(row['is_tg_active']),
                        "params": params_dict.get("params", {}),
                        "summary": params_dict.get("summary", {})
                    })
                return history
        except Exception as e:
            logger.error(f"Erro ao carregar histórico do PostgreSQL: {e}", exc_info=True)
            return []
        finally:
            conn.close()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, type, created_at, is_tg_active, parameters FROM strategies ORDER BY created_at DESC")
        rows = cursor.fetchall()
        
        history = []
        modified = False
        
        for row in rows:
            try:
                params_dict = json.loads(row['parameters'])
            except Exception:
                params_dict = {}
            
            entry = {
                "id": row['id'],
                "name": row['name'],
                "type": row['type'],
                "created_at": row['created_at'],
                "is_tg_active": bool(row['is_tg_active']),
                "params": params_dict.get("params", {}),
                "summary": params_dict.get("summary", {})
            }
            
            if entry['type'] != 'portfolio' and 'strategy_ids' in entry.get('params', {}):
                entry['type'] = 'portfolio'
                modified = True
                conn.execute("UPDATE strategies SET type = ? WHERE id = ?", ("portfolio", entry['id']))
                
            history.append(entry)
            
        if modified:
            conn.commit()
            
        return history
    except Exception as e:
        logger.error(f"Erro ao carregar histórico: {e}", exc_info=True)
        return []
    finally:
        conn.close()

def add_strategy(data: dict):
    init_db()
    provided_id = data.get("id")
    inferred_type = data.get("type", "strategy")
    if 'strategy_ids' in data.get("params", {}):
        inferred_type = "portfolio"
        
    params = data.get("params", {})
    if params.get("data_source") == "futpython":
        if not params.get("futpython_api_key"):
            try:
                from .data_loader import get_futpython_api_key
                params["futpython_api_key"] = get_futpython_api_key()
            except Exception:
                import os
                from dotenv import load_dotenv
                load_dotenv()
                params["futpython_api_key"] = os.getenv("FUTPYTHON_API_KEY")

    entry = {
        "id": provided_id if provided_id else str(uuid.uuid4()),
        "created_at": data.get("created_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "name": data.get("name", "Nova Estratégia"),
        "type": inferred_type,
        "is_tg_active": data.get("is_tg_active", False),
        "params": params,
        "summary": data.get("summary", {})
    }
    
    parameters_blob = json.dumps(_sanitize_for_json({
        "params": entry["params"],
        "summary": entry["summary"]
    }), ensure_ascii=False)

    if DATABASE_URL:
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO strategies (id, name, type, created_at, is_tg_active, parameters)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        type = EXCLUDED.type,
                        created_at = EXCLUDED.created_at,
                        is_tg_active = EXCLUDED.is_tg_active,
                        parameters = EXCLUDED.parameters
                """, (
                    entry["id"],
                    entry["name"],
                    entry["type"],
                    entry["created_at"],
                    1 if entry["is_tg_active"] else 0,
                    parameters_blob
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao salvar estratégia no PostgreSQL: {e}", exc_info=True)
        finally:
            conn.close()
        return entry
    
    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO strategies (id, name, type, created_at, is_tg_active, parameters)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            entry["id"],
            entry["name"],
            entry["type"],
            entry["created_at"],
            1 if entry["is_tg_active"] else 0,
            parameters_blob
        ))
        conn.commit()
    finally:
        conn.close()
        
    return entry

def save_history(history: list):
    init_db()
    if DATABASE_URL:
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM strategies")
                for s in history:
                    provided_id = s.get("id") or str(uuid.uuid4())
                    name = s.get("name", "Nova Estratégia")
                    stype = s.get("type", "strategy")
                    created_at = s.get("created_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    is_tg_active = 1 if s.get("is_tg_active", False) else 0
                    
                    parameters_blob = json.dumps(_sanitize_for_json({
                        "params": s.get("params", {}),
                        "summary": s.get("summary", {})
                    }), ensure_ascii=False)
                    
                    cur.execute("""
                        INSERT INTO strategies (id, name, type, created_at, is_tg_active, parameters)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (provided_id, name, stype, created_at, is_tg_active, parameters_blob))
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao re-salvar histórico no PostgreSQL: {e}", exc_info=True)
        finally:
            conn.close()
        return

    conn = get_db_connection()
    try:
        with conn:
            conn.execute("DELETE FROM strategies")
            for s in history:
                provided_id = s.get("id") or str(uuid.uuid4())
                name = s.get("name", "Nova Estratégia")
                stype = s.get("type", "strategy")
                created_at = s.get("created_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                is_tg_active = 1 if s.get("is_tg_active", False) else 0
                
                parameters_blob = json.dumps(_sanitize_for_json({
                    "params": s.get("params", {}),
                    "summary": s.get("summary", {})
                }), ensure_ascii=False)
                
                conn.execute("""
                    INSERT INTO strategies (id, name, type, created_at, is_tg_active, parameters)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (provided_id, name, stype, created_at, is_tg_active, parameters_blob))
    finally:
        conn.close()

def delete_strategy(strategy_id: str):
    init_db()
    if DATABASE_URL:
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao deletar estratégia no PostgreSQL: {e}", exc_info=True)
        finally:
            conn.close()
        return True

    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
        conn.commit()
    finally:
        conn.close()
    return True
