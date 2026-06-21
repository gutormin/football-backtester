import json
import os
import uuid
import subprocess
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

def _git_commit_history():
    """
    Auto-commit history file to git so it persists across Render deployments.
    Requires GITHUB_TOKEN environment variable on the Render server.
    """
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return  # Git push not configured, skip silently

        # Set remote URL with token embedded
        repo_url = os.environ.get("GITHUB_REPO_URL", "https://github.com/gutormin/Backtest.git")
        # Build authenticated URL: https://<token>@github.com/...
        auth_url = repo_url.replace("https://", f"https://{token}@")

        # Configure git identity (needed on Render)
        subprocess.run(["git", "config", "user.email", "render@football-backtester.local"],
                       check=False, timeout=5, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Render Auto-Backup"],
                       check=False, timeout=5, capture_output=True)

        subprocess.run(["git", "add", HISTORY_FILE],
                       check=False, timeout=10, capture_output=True)

        result = subprocess.run(
            ["git", "commit", "-m", "auto: persist history strategies [skip ci]"],
            check=False, timeout=10, capture_output=True
        )

        # Only push if there was something to commit
        if result.returncode == 0:
            subprocess.run(
                ["git", "push", auth_url, "HEAD:main"],
                check=False, timeout=20, capture_output=True
            )
    except Exception:
        pass  # Git push failure is non-fatal; data is still saved locally on current deployment

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

    # Persist to git so Render deployments don't wipe the file
    _git_commit_history()
        
    return entry

def save_history(history: list):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4, ensure_ascii=False)
    # Also persist on manual saves (e.g., toggle_active, delete)
    _git_commit_history()

def delete_strategy(strategy_id: str):
    history = load_history()
    new_history = [s for s in history if s.get("id") != strategy_id]
    
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(new_history, f, indent=4, ensure_ascii=False)

    _git_commit_history()
        
    return True
