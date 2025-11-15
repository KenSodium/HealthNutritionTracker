# nutrition/services/history_store.py
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict, Any

HISTORY_DIRNAME = "history"

def _history_path(instance_path: str, user_id: str) -> Path:
    """
    Returns instance/history/<user_id>.json
    """
    safe_user = user_id.replace("/", "_").replace("\\", "_")
    p = Path(instance_path) / HISTORY_DIRNAME
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{safe_user}.json"

def _load_all(instance_path: str, user_id: str) -> List[Dict[str, Any]]:
    path = _history_path(instance_path, user_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # Corrupt or empty file fallback
        return []

def _save_all(instance_path: str, user_id: str, days: List[Dict[str, Any]]) -> None:
    path = _history_path(instance_path, user_id)
    path.write_text(json.dumps(days, ensure_ascii=False, indent=2), encoding="utf-8")

def list_days(instance_path: str, user_id: str) -> List[Dict[str, Any]]:
    """
    Returns list of day dicts (each includes 'date', 'totals', and optionally 'entries').
    Sorted descending by date string (YYYY-MM-DD).
    """
    days = _load_all(instance_path, user_id)
    return sorted(days, key=lambda d: d.get("date", ""), reverse=True)

def get_day(instance_path: str, user_id: str, date_str: str) -> Dict[str, Any] | None:
    """
    Returns a single day dict (with entries) for the given date.
    """
    for d in _load_all(instance_path, user_id):
        if d.get("date") == date_str:
            return d
    return None

def upsert_day(instance_path: str, user_id: str, day: Dict[str, Any]) -> None:
    """
    Inserts or replaces a day by 'date'. Expects keys: date, totals, entries.
    """
    if "date" not in day or "totals" not in day:
        raise ValueError("Day must include 'date' and 'totals'.")
    days = _load_all(instance_path, user_id)
    by_date = {d.get("date"): i for i, d in enumerate(days) if "date" in d}
    if day["date"] in by_date:
        days[by_date[day["date"]]] = day
    else:
        days.append(day)
    _save_all(instance_path, user_id, days)
# add near the other helpers
def history_file_path(instance_path: str, user_id: str) -> str:
    """Public helper: absolute path to the user's history JSON file."""
    return str(_history_path(instance_path, user_id))
