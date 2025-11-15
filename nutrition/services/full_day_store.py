from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List

def _file_path(instance_path: str, user_id: str) -> Path:
    p = Path(instance_path) / "full_days"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{user_id}.json"

def list_days(instance_path: str, user_id: str) -> List[Dict[str, Any]]:
    f = _file_path(instance_path, user_id)
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []

def upsert_day(instance_path: str, user_id: str, day: Dict[str, Any]) -> None:
    days = list_days(instance_path, user_id)
    # Replace if same date exists
    days = [d for d in days if d.get("date") != day.get("date")]
    days.append(day)
    days.sort(key=lambda d: d.get("date"))
    f = _file_path(instance_path, user_id)
    f.write_text(json.dumps(days, indent=2), encoding="utf-8")
