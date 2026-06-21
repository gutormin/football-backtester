import json
import os
import uuid
from datetime import datetime

HISTORY_FILE = "data/history_strategies.json"

def ensure_history_dir():
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)

def load_history():
    ensure_history_dir()
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def add_strategy(data: dict):
    history = load_history()
    
    entry = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now().isoformat(),
        "name": data.get("name", "Nova Estratégia"),
        "type": data.get("type", "strategy"),
        "params": data.get("params", {}),
        "summary": data.get("summary", {})
    }
    
    # Insert at the beginning
    history.insert(0, entry)
    
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4, ensure_ascii=False)
        
    return entry

def save_history(history: list):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4, ensure_ascii=False)

def delete_strategy(strategy_id: str):
    history = load_history()
    new_history = [s for s in history if s.get("id") != strategy_id]
    
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(new_history, f, indent=4, ensure_ascii=False)
        
    return True
