# app_blueprints/reports.py
from flask import Blueprint, render_template, session, make_response, request
import io, csv
import datetime as _dt

# If you need targets in weekly_preview status labels
from nutrition.utils import get_targets

reports_bp = Blueprint("reports", __name__)

FEATURED_NUTRIENTS = ["Sodium", "Potassium", "Protein", "Calories"]
ALL_HISTORY_NUTRIENTS = [
    "Sodium", "Protein", "Carbs", "Fat", "Sat Fat", "Mono Fat", "Poly Fat",
    "Sugar", "Potassium", "Calcium", "Magnesium", "Iron", "Calories"
]

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
    """Clinician-style 7-day preview (web + print)."""
    hist = session.get("history", {}) or {}

    # Last 7 calendar days, oldest -> newest
    today = _dt.date.today()
    date_keys = [(today - _dt.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    days = [hist[d] for d in date_keys if d in hist]

    meta = {
        "from": date_keys[0] if date_keys else "",
        "to": date_keys[-1] if date_keys else "",
        "days": len(days),
    }

    tgt = get_targets()  # {"na": 1500, "k": 3400}
    demo_defaults = {
        "Protein": (60, 70),
        "Calories": (1800, 2200),
        "Phosphorus": (0, 800),
        "Calcium": (1000, 1000),
        "Magnesium": (400, 400),
    }

    featured_order = [
        ("Sodium", "mg"),
        ("Potassium", "mg"),
        ("Protein", "g"),
        ("Calories", "kcal"),
        ("Phosphorus", "mg"),
        ("Calcium", "mg"),
        ("Magnesium", "mg"),
    ]
    supplemental_order = [
        ("Carbs", "g"),
        ("Fat", "g"),
        ("Sat Fat", "g"),
        ("Mono Fat", "g"),
        ("Poly Fat", "g"),
        ("Sugar", "g"),
        ("Iron", "mg"),
    ]

    def collect(nm: str):
        return [float(d.get("totals", {}).get(nm, 0.0)) for d in days]

    def rng(vals):
        if not vals:
            return "0–0"
        return f"{round(min(vals), 0)}–{round(max(vals), 0)}"

    def featured_target_and_status(nm: str, avg: float):
        if nm == "Sodium":
            maxv = float(tgt.get("na", 1500))
            target_label = f"<{int(maxv)}"
            if avg <= maxv: return target_label, ("OK", "badge bg-success")
            if avg <= maxv * 1.2: return target_label, ("Slightly High", "badge bg-warning text-dark")
            return target_label, ("High", "badge bg-danger")
        if nm == "Potassium":
            maxk = float(tgt.get("k", 3400))
            target_label = f"<{int(maxk)}"
            if avg <= maxk: return target_label, ("OK", "badge bg-success")
            if avg <= maxk * 1.2: return target_label, ("Slightly High", "badge bg-warning text-dark")
            return target_label, ("High", "badge bg-danger")
        lo, hi = demo_defaults.get(nm, (0.0, 0.0))
        if lo == hi == 0.0:
            return "—", ("—", "badge bg-secondary")
        if lo > 0 and hi > 0 and lo < hi:
            target_label = f"{int(lo)}–{int(hi)}"
            if avg < lo * 0.95: return target_label, ("Low", "badge bg-warning text-dark")
            if avg > hi * 1.05: return target_label, ("High", "badge bg-danger")
            return target_label, ("OK", "badge bg-success")
        goal = hi if hi > 0 else lo
        target_label = f"≈{int(goal)}"
        if avg < goal * 0.85: return target_label, ("Low", "badge bg-warning text-dark")
        if avg > goal * 1.15: return target_label, ("High", "badge bg-danger")
        return target_label, ("OK", "badge bg-success")

    featured_rows = []
    for nm, unit in featured_order:
        vals = collect(nm)
        avg = (sum(vals) / len(vals)) if vals else 0.0
        target_label, (status_text, status_cls) = featured_target_and_status(nm, avg)
        featured_rows.append({
            "name": nm, "unit": unit, "target": target_label,
            "avg": round(avg, 0), "range": rng(vals),
            "status_text": status_text, "status_cls": status_cls,
        })

    supplemental_rows = []
    for nm, unit in supplemental_order:
        vals = collect(nm)
        avg = (sum(vals) / len(vals)) if vals else 0.0
        supplemental_rows.append({
            "name": nm, "unit": unit,
            "avg": round(avg, 0),
            "min": round(min(vals), 0) if vals else 0,
            "max": round(max(vals), 0) if vals else 0,
        })

    user = session.get("user") or {"name": "Demo Patient"}
    patient_name = user.get("name") or "Demo Patient"

    notes = []
    f_na = next((r for r in featured_rows if r["name"] == "Sodium"), None)
    if f_na and f_na["status_text"] != "OK":
        notes.append("Sodium is above your daily target on average. Consider reducing processed foods/sauces.")
    f_ca = next((r for r in featured_rows if r["name"] == "Calcium"), None)
    if f_ca and f_ca["status_text"] == "Low":
        notes.append("Calcium is low; consider food sources (fortified options, leafy greens) per clinician guidance.")
    f_k = next((r for r in featured_rows if r["name"] == "Potassium"), None)
    if f_k and f_k["status_text"] != "OK":
        notes.append("Potassium is outside your current limit; review high-K foods if advised by your care team.")

    return render_template(
        "weekly_preview.html",
        meta=meta,
        patient_name=patient_name,
        featured_rows=featured_rows,
        supplemental_rows=supplemental_rows,
        notes=notes,
    )
