import math
import os
import numpy as np
from fastapi import APIRouter, HTTPException
from ..history_manager import load_history, add_strategy, delete_strategy, save_history

router = APIRouter()


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

@router.get("/history")
def api_get_history():
    return load_history()

@router.get("/debug_db")
def api_debug_db():
    try:
        h = load_history()
        return {
            "file_exists": os.path.exists("data/history_strategies.json"),
            "file_size": os.path.getsize("data/history_strategies.json") if os.path.exists("data/history_strategies.json") else 0,
            "items_count": len(h),
            "items": [{"id": x.get("id"), "name": x.get("name"), "type": x.get("type"), "created_at": x.get("created_at")} for x in h]
        }
    except Exception as e:
        return {"error": str(e)}

@router.post("/history")
def api_save_history(payload: dict):
    try:
        sanitized = _sanitize_for_json(payload)
        new_entry = add_strategy(sanitized)
        return {"status": "ok", "entry": new_entry}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/history/{strategy_id}")
def api_delete_history(strategy_id: str):
    try:
        delete_strategy(strategy_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/history/{strategy_id}/toggle_active")
def api_toggle_active_portfolio(strategy_id: str):
    try:
        history = load_history()
        
        # Find the strategy or portfolio
        target = next((s for s in history if s.get('id') == strategy_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Estratégia ou portfólio não encontrado.")
            
        new_status = not target.get('is_tg_active', False)
        
        # Toggle target status only.
        for s in history:
            if s.get('id') == strategy_id:
                s['is_tg_active'] = new_status
                        
        save_history(history)
        return {"status": "ok", "is_tg_active": new_status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
