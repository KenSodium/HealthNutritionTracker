# app_blueprints/history_api.py
from __future__ import annotations
from flask import Blueprint, current_app, request, jsonify, render_template, Response
from typing import Any, Dict, List
from pathlib import Path
import csv
import io

from nutrition.services import history_store

# Keep blueprint name "history" so url_for('history.history_page') works
history_bp = Blueprint("history", __name__, url_prefix="/history")

# ------------------------ User-id resolution ------------------------

def _history_dir() -> Path:
    return Path(current_app.instance_path) / "history"

def _file_for(user_id: str) -> Path:
    safe = user_id.replace("/", "_").replace("\\", "_")
    p = _history_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{safe}.json"

def _candidate_ids() -> List[str]:
    ids: List[str] = []
    cfg = current_app.config.get("HISTORY_USER_ID")
    if cfg:
        ids.append(str(cfg))
    ids.extend([
        "demo",
        "demo@example.com",
        "user",
        "local",
        "default",
    ])
    return ids

def _resolve_user_id() -> str:
    """
    Picks a user id that actually has data.
    Priority:
      1) ?uid=<id> query param (useful for quick manual override)
      2) app.config["HISTORY_USER_ID"]
      3) known legacy ids if non-empty file exists
      4) newest non-empty *.json under instance/history
      5) fallback to configured/default "demo"
    """
    # 1) URL override for quick recovery/debug: /history/?uid=foo
    override = request.args.get("uid")
    if override:
        f = _file_for(override)
        if f.exists() and f.stat().st_size > 2:
            return override

    # 2) Preferred from config
    preferred = current_app.config.get("HISTORY_USER_ID", "demo")
    pf = _file_for(preferred)
    if pf.exists() and pf.stat().st_size > 2:
        return preferred

    # 3) Legacy candidates
    for cid in _candidate_ids():
        f = _file_for(cid)
        if f.exists() and f.stat().st_size > 2:
            return cid

    # 4) Any non-empty *.json (pick newest)
    hdir = _history_dir()
    if hdir.exists():
        jsons = sorted(
            (p for p in hdir.glob("*.json") if p.is_file() and p.stat().st_size > 2),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if jsons:
            return jsons[0].stem

    # 5) Fallback
    return preferred

# ----------------------------- Pages -------------------------------

@history_bp.get("/", endpoint="history_page")
def history_page():
    user_id = _resolve_user_id()
    days = history_store.list_days(current_app.instance_path, user_id)
    try:
        file_path = history_store.history_file_path(current_app.instance_path, user_id)
    except AttributeError:
        file_path = str(_file_for(user_id))
    return render_template(
        "app/history.html",
        days=days,
        uid=user_id,
        file_path=file_path,
        # REMOVE this line if present:
        # debug=request.args.get("debug") in ("1", "true"),
    )


# ---------------------- API: save / get / csv ----------------------

@history_bp.post("/api/day/save")
def api_day_save():
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    date = payload.get("date")
    totals = payload.get("totals", {})
    entries = payload.get("entries", [])

    if not date:
        return jsonify({"ok": False, "error": "Missing 'date'"}), 400
    if not isinstance(totals, dict):
        return jsonify({"ok": False, "error": "'totals' must be an object"}), 400
    if not isinstance(entries, list):
        return jsonify({"ok": False, "error": "'entries' must be a list"}), 400

    user_id = _resolve_user_id()

    # 1) Save/overwrite totals history (what /history shows)
    day_totals = {"date": date, "totals": totals, "entries": entries}
    history_store.upsert_day(current_app.instance_path, user_id, day_totals)

    # 2) Save/overwrite full-day entries (separate DB shown at /history/full)
    from nutrition.services import full_day_store
    day_full = {"date": date, "entries": entries}
    full_day_store.upsert_day(current_app.instance_path, user_id, day_full)

    return jsonify({"ok": True})


@history_bp.get("/api/day/get")
def api_day_get():
    date = request.args.get("date", "")
    if not date:
        return jsonify({"ok": False, "error": "Missing ?date=YYYY-MM-DD"}), 400
    user_id = _resolve_user_id()
    day = history_store.get_day(current_app.instance_path, user_id, date)
    if not day:
        return jsonify({"ok": False, "error": "Not found"}), 404
    return jsonify({"ok": True, "day": day})

@history_bp.get("/api/day/csv")
def api_day_csv():
    date = request.args.get("date", "")
    if not date:
        return jsonify({"ok": False, "error": "Missing ?date=YYYY-MM-DD"}), 400
    user_id = _resolve_user_id()
    day = history_store.get_day(current_app.instance_path, user_id, date)
    if not day:
        return jsonify({"ok": False, "error": "Not found"}), 404

    out = io.StringIO()
    w = csv.writer(out)
    # Totals first (matches your history table expectations)
    w.writerow(["Date", "Sodium (mg)", "Potassium (mg)", "Cholesterol (mg)", "Protein (g)", "Calories"])
    t = day.get("totals", {})
    w.writerow([
        day.get("date", ""),
        t.get("Sodium", ""), t.get("Potassium", ""), t.get("Cholesterol", ""),
        t.get("Protein", ""), t.get("Calories", "")
    ])
    # Spacer + optional entries
    w.writerow([])
    entries: List[Dict[str, Any]] = day.get("entries", [])
    if entries:
        preferred = ["food", "amount", "sodium_mg", "potassium_mg", "protein_g", "calories_kcal"]
        keys = set().union(*(e.keys() for e in entries))
        cols = preferred + [k for k in sorted(keys) if k not in preferred]
        w.writerow(cols)
        for e in entries:
            w.writerow([e.get(k, "") for k in cols])
    else:
        w.writerow(["No entries"])

    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="day_{date}.csv"'}
    )

# -------------------- Back-compat endpoints ------------------------

@history_bp.get("/api/history/csv")
def api_history_csv():
    user_id = _resolve_user_id()
    days = history_store.list_days(current_app.instance_path, user_id)

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date", "Sodium (mg)", "Potassium (mg)", "Cholesterol (mg)", "Protein (g)", "Calories",
                "Carbs (g)", "Fat (g)", "Sat Fat (g)", "Mono Fat (g)", "Poly Fat (g)", "Sugar (g)",
                "Calcium (mg)", "Magnesium (mg)", "Iron (mg)"])
    for d in days:
        t = d.get("totals", {})
        w.writerow([
            d.get("date", ""),
            t.get("Sodium", ""), t.get("Potassium", ""), t.get("Cholesterol", ""),
            t.get("Protein", ""), t.get("Calories", ""),
            t.get("Carbs", ""), t.get("Fat", ""), t.get("Sat Fat", ""),
            t.get("Mono Fat", ""), t.get("Poly Fat", ""), t.get("Sugar", ""),
            t.get("Calcium", ""), t.get("Magnesium", ""), t.get("Iron", ""),
        ])

    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="history_all_days.csv"'}
    )

@history_bp.get("/api/history/debug")
def api_history_debug():
    user_id = _resolve_user_id()
    days = history_store.list_days(current_app.instance_path, user_id)
    try:
        file_path = history_store.history_file_path(current_app.instance_path, user_id)
    except AttributeError:
        file_path = str(_file_for(user_id))
    return jsonify({"ok": True, "uid": user_id, "file": file_path, "count": len(days), "days": days})
# ---------- View: Full Daily Records ----------
@history_bp.get("/full")
def full_records_page():
    """
    Show the complete daily records (all food entries, not just totals).
    """
    from nutrition.services import full_day_store
    user_id = _resolve_user_id()
    days = full_day_store.list_days(current_app.instance_path, user_id)
    return render_template("app/full_days.html", days=days, uid=user_id)
@history_bp.get("/api/full/csv")
def api_full_csv():
    """Export one row per entry with the date on each row."""
    user_id = _resolve_user_id()
    days = history_store.list_days(current_app.instance_path, user_id)

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([
        "Date","Food","Amount",
        "Sodium (mg)","Potassium (mg)","Cholesterol (mg)",
        "Protein (g)","Calories",
        "Carbs (g)","Fat (g)","Sat Fat (g)","Mono Fat (g)","Poly Fat (g)","Sugar (g)",
        "Calcium (mg)","Magnesium (mg)","Iron (mg)"
    ])

    for d in days:
        date = d.get("date","")
        for e in (d.get("entries") or []):
            w.writerow([
                date,
                e.get("food",""),
                e.get("amount",0),
                e.get("sodium_mg",0),
                e.get("potassium_mg",0),
                e.get("cholesterol_mg",0),
                e.get("protein_g",0),
                e.get("calories_kcal",0),
                e.get("carbs_g",0),
                e.get("fat_g",0),
                # try multiple keys for sat fat if your save code evolves
                e.get("sat_g", e.get("sat_fat_g", e.get("satfat_g",0))),
                e.get("mono_g",0),
                e.get("poly_g",0),
                e.get("sugar_g",0),
                e.get("calcium_mg",0),
                e.get("magnesium_mg",0),
                e.get("iron_mg",0),
            ])

    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="full_daily_records.csv"'}
    )
