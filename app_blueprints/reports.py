# app_blueprints/reports.py
from flask import Blueprint, render_template, session, make_response, request, current_app
import io
import csv
import os
import json
import datetime as _dt

from nutrition.services import history_store
from nutrition.utils import get_targets

reports_bp = Blueprint("reports", __name__)

FEATURED_NUTRIENTS = ["Sodium", "Potassium", "Protein", "Calories"]
ALL_HISTORY_NUTRIENTS = [
    "Sodium", "Protein", "Carbs", "Fat", "Sat Fat", "Mono Fat", "Poly Fat",
    "Sugar", "Potassium", "Calcium", "Magnesium", "Iron", "Calories",
]


def _load_history_from_files() -> dict:
    """
    Load per-user history from instance/history/<uid>.json.

    Returns either:
      - { "YYYY-MM-DD": day_record, ... }
      - OR { "days": { "YYYY-MM-DD": day_record, ... } }
      - OR { "days": [ { "date": "...", ... }, ... ] }
      - OR [ { "date": "...", ... }, ... ]
    """
    user = session.get("user") or {}
    uid = user.get("id") or user.get("uid") or "anon"

    hist_dir = os.path.join(current_app.instance_path, "history")
    path = os.path.join(hist_dir, f"{uid}.json")

    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    # Normalize to {date_str: record}
    if isinstance(data, dict):
        # { "days": {...} } or { "days": [ ... ] }
        if "days" in data:
            days = data["days"]
            if isinstance(days, dict):
                return days
            if isinstance(days, list):
                out = {}
                for rec in days:
                    if isinstance(rec, dict):
                        d = rec.get("date")
                        if d:
                            out[d] = rec
                return out
        # Already { "YYYY-MM-DD": {...}, ... }
        return data

    if isinstance(data, list):
        out = {}
        for rec in data:
            if isinstance(rec, dict):
                d = rec.get("date")
                if d:
                    out[d] = rec
        return out

    return {}


def sum_named_nutrients(daymap: dict, names=ALL_HISTORY_NUTRIENTS) -> dict:
    """Sum only the nutrients we care about across today's items (daymap values)."""
    totals = {n: 0.0 for n in names}
    for rec in (daymap or {}).values():
        n = rec.get("nutrients", {})
        for k in names:
            v = n.get(k)
            if isinstance(v, (int, float)):
                totals[k] += float(v)
    return totals


@reports_bp.route("/history", endpoint="history")
def history():
    history = session.get("history", {})
    dates = sorted(history.keys(), reverse=True)
    rows = []
    for d in dates:
        rec = history.get(d, {})
        entries = rec.get("entries", [])
        totals = rec.get("totals") or {}
        if not totals or any(k not in totals for k in ALL_HISTORY_NUTRIENTS):
            dm = {str(i): e for i, e in enumerate(entries)}
            totals = sum_named_nutrients(dm)
            rec["totals"] = totals
        rows.append({"date": d, "totals": totals, "entries": entries})
    return render_template(
        "app/history.html",
        days=rows,
        all_cols=ALL_HISTORY_NUTRIENTS,
        featured=FEATURED_NUTRIENTS,
    )


@reports_bp.route("/history_csv", endpoint="history_csv")
def history_csv():
    history = session.get("history", {})
    date_q = request.args.get("date")
    fieldnames = ["Date"] + ALL_HISTORY_NUTRIENTS

    output = io.StringIO()
    w = csv.DictWriter(output, fieldnames=fieldnames)
    w.writeheader()

    def _write_row(d, totals):
        row = {"Date": d}
        for n in ALL_HISTORY_NUTRIENTS:
            row[n] = round(totals.get(n, 0.0), 2)
        w.writerow(row)

    if date_q:
        rec = history.get(date_q)
        if rec:
            totals = rec.get("totals") or {}
            if not totals or any(k not in totals for k in ALL_HISTORY_NUTRIENTS):
                dm = {str(i): e for i, e in enumerate(rec.get("entries", []))}
                totals = sum_named_nutrients(dm)
            _write_row(date_q, totals)
        filename = f"history_{date_q}.csv"
    else:
        for d in sorted(history.keys()):
            rec = history[d]
            totals = rec.get("totals") or {}
            if not totals or any(k not in totals for k in ALL_HISTORY_NUTRIENTS):
                dm = {str(i): e for i, e in enumerate(rec.get("entries", []))}
                totals = sum_named_nutrients(dm)
            _write_row(d, totals)
        filename = "history_all_days.csv"

    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@reports_bp.route("/weekly_preview", endpoint="weekly_preview")
def weekly_preview():
    """
    Clinician-style preview reading from the history_store
    (instance/history/<user>.json) and handling missing days.

    Supports an optional ?days=N query param (default 7).
    """
    user = session.get("user") or {}
    patient_name = user.get("name") or user.get("email") or "Demo User"
    user_id = user.get("email") or user.get("id") or "demo@example.com"

    # --- 1. Load days from history_store ---
    all_days = history_store.list_days(current_app.instance_path, user_id)
    by_date = {d.get("date"): d for d in all_days if d.get("date")}

    # --- 2. Determine window size from query ---
    try:
        days_param = int(request.args.get("days", 7))
    except (TypeError, ValueError):
        days_param = 7

    # Clamp between 1 and 90 to avoid silly values
    days_param = max(1, min(days_param, 90))

    today = _dt.date.today()
    # Oldest -> newest, length = days_param
    date_keys = [
        (today - _dt.timedelta(days=i)).isoformat()
        for i in range(days_param - 1, -1, -1)
    ]
    window_days = len(date_keys)

    days_in_window = [by_date[d] for d in date_keys if d in by_date]
    days_with_data = len(days_in_window)
    missing_days = max(window_days - days_with_data, 0)

    period_from = date_keys[0] if date_keys else ""
    period_to = date_keys[-1] if date_keys else ""

    meta = {
        "from": period_from,
        "to": period_to,
        "window_days": window_days,
        "days_with_data": days_with_data,
        "missing_days": missing_days,
    }

    tgt = get_targets()  # e.g. {"na": 1500, "k": 3400}

    # If no days at all in this window, show empty state
    if not days_in_window:
        return render_template(
            "weekly_preview.html",
            meta=meta,
            patient_name=patient_name,
            featured_rows=[],
            supplemental_rows=[],
            notes=[],
            targets=tgt,
        )

    # --- 3. Nutrients config ---

    featured_order = [
        ("Sodium", "mg"),
        ("Potassium", "mg"),
        ("Protein", "g"),
        ("Calories", "kcal"),
    ]

    supplemental_order = [
        ("Phosphorus", "mg"),
        ("Calcium", "mg"),
        ("Magnesium", "mg"),
        ("Cholesterol", "mg"),
        ("Carbs", "g"),
        ("Fat", "g"),
        ("Sat Fat", "g"),
        ("Mono Fat", "g"),
        ("Poly Fat", "g"),
        ("Sugar", "g"),
        ("Iron", "mg"),
    ]

    demo_defaults = {
        "Protein": (60, 70),
        "Calories": (1800, 2200),
        "Phosphorus": (0, 800),
        "Calcium": (1000, 1000),
        "Magnesium": (400, 400),
    }

    # --- helpers ---

    def collect(nm: str):
        vals = []
        for d in days_in_window:
            totals = d.get("totals", {}) or {}
            v = totals.get(nm)
            if isinstance(v, (int, float)):
                vals.append(float(v))
        return vals

    def fmt0(v: float) -> str:
        """Format as x,xxx with no decimals."""
        try:
            return f"{v:,.0f}"
        except Exception:
            return "0"

    def range_fmt(vals):
        if not vals:
            return "0–0"
        return f"{fmt0(min(vals))}–{fmt0(max(vals))}"

    def featured_target_and_status(nm: str, avg: float):
        # Sodium & Potassium use Daily Diary targets
        if nm == "Sodium":
            maxv = float(tgt.get("na", 1500))
            target_label = f"<{int(maxv)}"
            if avg <= maxv:
                return target_label, ("OK", "badge bg-success")
            if avg <= maxv * 1.2:
                return target_label, ("Slightly High", "badge bg-warning text-dark")
            return target_label, ("High", "badge bg-danger")

        if nm == "Potassium":
            maxk = float(tgt.get("k", 3400))
            target_label = f"<{int(maxk)}"
            if avg <= maxk:
                return target_label, ("OK", "badge bg-success")
            if avg <= maxk * 1.2:
                return target_label, ("Slightly High", "badge bg-warning text-dark")
            return target_label, ("High", "badge bg-danger")

        # Others use demo ranges
        lo, hi = demo_defaults.get(nm, (0.0, 0.0))
        if lo == hi == 0.0:
            return "—", ("—", "badge bg-secondary")

        if lo > 0 and hi > 0 and lo < hi:
            target_label = f"{int(lo)}–{int(hi)}"
            if avg < lo * 0.95:
                return target_label, ("Low", "badge bg-warning text-dark")
            if avg > hi * 1.05:
                return target_label, ("High", "badge bg-danger")
            return target_label, ("OK", "badge bg-success")

        goal = hi if hi > 0 else lo
        target_label = f"≈{int(goal)}"
        if avg < goal * 0.85:
            return target_label, ("Low", "badge bg-warning text-dark")
        if avg > goal * 1.15:
            return target_label, ("High", "badge bg-danger")
        return target_label, ("OK", "badge bg-success")

    # --- 4. Build rows ---

    featured_rows = []
    for nm, unit in featured_order:
        vals = collect(nm)
        avg = (sum(vals) / len(vals)) if vals else 0.0
        avg_val = round(avg, 0)
        target_label, (status_text, status_cls) = featured_target_and_status(nm, avg)

        featured_rows.append(
            {
                "name": nm,
                "unit": unit,
                "target": target_label,
                "avg": avg_val,
                "avg_display": fmt0(avg_val),
                "range": range_fmt(vals),
                "status_text": status_text,
                "status_cls": status_cls,
            }
        )

    supplemental_rows = []
    for nm, unit in supplemental_order:
        vals = collect(nm)
        avg = (sum(vals) / len(vals)) if vals else 0.0
        avg_val = round(avg, 0)
        min_v = round(min(vals), 0) if vals else 0
        max_v = round(max(vals), 0) if vals else 0

        supplemental_rows.append(
            {
                "name": nm,
                "unit": unit,
                "avg": avg_val,
                "avg_display": fmt0(avg_val),
                "min": min_v,
                "min_display": fmt0(min_v),
                "max": max_v,
                "max_display": fmt0(max_v),
            }
        )

    # --- 5. Auto-generated notes ---

    notes = []
    f_na = next((r for r in featured_rows if r["name"] == "Sodium"), None)
    if f_na and f_na["status_text"] != "OK":
        notes.append(
            "Sodium is above your daily target on average. "
            "Consider reducing processed foods/sauces."
        )

    f_k = next((r for r in featured_rows if r["name"] == "Potassium"), None)
    if f_k and f_k["status_text"] != "OK":
        notes.append(
            "Potassium is outside your current limit; review high-K foods "
            "if advised by your care team."
        )

    # --- 6. Render ---

    return render_template(
        "weekly_preview.html",
        meta=meta,
        patient_name=patient_name,
        featured_rows=featured_rows,
        supplemental_rows=supplemental_rows,
        notes=notes,
        targets=tgt,
    )
