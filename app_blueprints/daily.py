# app_blueprints/daily.py
from flask import Blueprint, render_template, request, session, redirect, url_for
import re
import datetime
from nutrition.utils import today_str, get_targets
from nutrition.constants import TARGET_NUTRIENTS
from nutrition.services.portions import (
    get_portions_for_fdc,
    build_hint_from_portions,
    portion_match_from_labels,
    find_alt_portions_for_name,
)
from nutrition.services.units import grams_from_local_registry

daily_bp = Blueprint("daily", __name__)

# --- Minimal helpers (kept local and self-contained) ----

def normalize_per100(n: dict) -> dict:
    ENERGY_KEYS_KCAL = ["Calories", "Energy (kcal)", "Energy", "calories", "Energy kcal"]
    ENERGY_KEYS_KJ   = ["Energy (kJ)", "Energy (kj)", "kJ", "Kilojoules"]

    def _coerce_calories_from_usda(n0: dict) -> float:
        if not n0: return 0.0
        for k in ENERGY_KEYS_KCAL:
            v = n0.get(k)
            if v not in (None, "", "NA"):
                try: return float(v)
                except: pass
        for k in ENERGY_KEYS_KJ:
            v = n0.get(k)
            if v not in (None, "", "NA"):
                try: return float(v) / 4.184
                except: pass
        return 0.0

    n = dict(n or {})
    if not n.get("Calories"):
        n["Calories"] = _coerce_calories_from_usda(n)

    if "Carbs" not in n:
        for k in ["Carbohydrate, by difference", "Carbohydrate", "Carbohydrates"]:
            if k in n:
                try: n["Carbs"] = float(n[k] or 0)
                except: n["Carbs"] = 0.0
                break
    if "Fat" not in n:
        for k in ["Total lipid (fat)", "Total Fat"]:
            if k in n:
                try: n["Fat"] = float(n[k] or 0)
                except: n["Fat"] = 0.0
                break
    if "Sat Fat" not in n:
        for k in ["Fatty acids, total saturated", "Saturated Fat"]:
            if k in n:
                try: n["Sat Fat"] = float(n[k] or 0)
                except: n["Sat Fat"] = 0.0
                break
    if "Mono Fat" not in n:
        for k in ["Fatty acids, total monounsaturated"]:
            if k in n:
                try: n["Mono Fat"] = float(n[k] or 0)
                except: n["Mono Fat"] = 0.0
                break
    if "Poly Fat" not in n:
        for k in ["Fatty acids, total polyunsaturated"]:
            if k in n:
                try: n["Poly Fat"] = float(n[k] or 0)
                except: n["Poly Fat"] = 0.0
                break
    if "Sugar" not in n:
        for k in ["Sugars, total including NLEA", "Sugars, total", "Sugar"]:
            if k in n:
                try: n["Sugar"] = float(n[k] or 0)
                except: n["Sugar"] = 0.0
                break

    maps = [
        ("Sodium", "Sodium, Na"),
        ("Potassium", "Potassium, K"),
        ("Calcium", "Calcium, Ca"),
        ("Magnesium", "Magnesium, Mg"),
        ("Iron", "Iron, Fe"),
        ("Phosphorus", "Phosphorus, P"),
    ]
    for std, alt in maps:
        if std not in n and alt in n:
            try: n[std] = float(n[alt] or 0)
            except: n[std] = 0.0

    wanted = ["Sodium","Potassium","Phosphorus","Calcium","Magnesium",
              "Protein","Carbs","Fat","Sat Fat","Mono Fat","Poly Fat",
              "Sugar","Iron","Calories"]
    for k in wanted:
        try: n[k] = float(n.get(k, 0.0) or 0.0)
        except: n[k] = 0.0
    return n


def get_daymap(date_iso: str) -> dict:
    di = session.setdefault("diary_by_food", {})
    di.setdefault(date_iso, {})
    return di[date_iso]


def sum_nutrients_from_map(daymap: dict) -> dict:
    keys = [
        "Sodium","Potassium","Phosphorus","Calcium","Magnesium",
        "Protein","Carbs","Fat","Sat Fat","Mono Fat","Poly Fat",
        "Sugar","Iron","Calories"
    ]
    totals = {k: 0.0 for k in keys}
    for rec in daymap.values():
        n = rec.get("nutrients", {})
        for k in totals:
            totals[k] += float(n.get(k, 0.0))
    return totals


def calc_progress(val, target):
    if target <= 0: return 0, "bg-secondary"
    pct = max(0, min(100, int(round(100 * float(val) / float(target)))))
    cls = "bg-success" if pct <= 100 else "bg-danger"
    return pct, cls


def _build_totals_view(totals_raw: dict, targets: dict, prot_target: float, cal_target: float) -> dict:
    """Return a uniform totals dict for the template (bars, classes, targets)."""
    na = float(totals_raw.get("Sodium", 0.0))
    k  = float(totals_raw.get("Potassium", 0.0))
    protein = float(totals_raw.get("Protein", 0.0))
    cal = float(totals_raw.get("Calories", 0.0))

    na_target = int(targets.get("na", 1500))
    k_target  = int(targets.get("k", 3400))
    prot_t = int(prot_target or 0)
    cal_t  = int(cal_target or 0)

    na_pct, na_cls   = calc_progress(na, na_target)
    k_pct,  k_cls    = calc_progress(k,  k_target)
    pr_pct, pr_cls   = calc_progress(protein, prot_t)
    cal_pct, cal_cls = calc_progress(cal, cal_t)

    return {
        "na": round(na, 0), "k": round(k, 0),
        "protein": round(protein, 0), "cal": round(cal, 0),
        "na_pct": na_pct, "na_class": na_cls,
        "k_pct":  k_pct,  "k_class":  k_cls,
        "prot_pct": pr_pct, "prot_class": pr_cls,
        "cal_pct":  cal_pct, "cal_class":  cal_cls,
        "prot_target": prot_t, "cal_target":  cal_t,
    }


# --- Portion parsing helpers used by the POST action ----

FALLBACK_TYPICAL_WEIGHTS = [
    (r"\bcracker(s)?\b|\bcrisp'?n?\s*light\b|\bsaltine(s)?\b|\britz\b", {
        "cracker": 4.0, "crackers": 4.0, "piece": 4.0
    }),
    (r"\bgarlic\b", {
        "clove": 3.0, "whole": 3.0, "tbsp": 8.5, "tsp": 2.8
    }),
    (r"\btomato,\s*roma\b|\broma\s+tomato\b", {
        "whole": 62.0, "cup": 180.0
    }),
    (r"\btomato\b", {
        "whole": 123.0, "cup": 180.0
    }),
    (r"\bonion\b", {
        "whole": 110.0, "cup": 160.0
    }),
    (r"\bpepperoncini\b", {
        "whole": 10.0
    }),
    (r"\bchicken\s+thigh\b", {
        "whole": 80.0
    }),
]

def typical_grams_for_unit(name: str, unit: str) -> float | None:
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    u = (unit or "").strip().lower().rstrip("s")
    for pat, umap in FALLBACK_TYPICAL_WEIGHTS:
        if re.search(pat, n):
            g = umap.get(u)
            if isinstance(g, (int, float)):
                return float(g)
    return None

def guess_grams_from_unit(name: str, unit: str, qty: float, portions: list) -> float:
    if portions:
        p = portion_match_from_labels(portions, unit)
        if p and isinstance(p.get("gramWeight"), (int, float)):
            return float(p["gramWeight"]) * float(qty)
    tw = typical_grams_for_unit(name, unit)
    if isinstance(tw, (int, float)):
        return float(tw) * float(qty)
    alt = find_alt_portions_for_name(name)
    if alt:
        p2 = portion_match_from_labels(alt, unit)
        if p2 and isinstance(p2.get("gramWeight"), (int, float)):
            return float(p2["gramWeight"]) * float(qty)
    GENERIC_VOL = {"cup": 240.0, "tbsp": 15.0, "tsp": 5.0}
    u = (unit or "").strip().lower()
    if u in GENERIC_VOL:
        return GENERIC_VOL[u] * float(qty)
    return 0.0

def pick_default_unit(portions) -> str | None:
    priority = ["cracker", "slice", "cup", "tbsp", "tsp", "whole", "piece"]
    if not isinstance(portions, (list, tuple)):
        portions = []
    clean = [p for p in portions if isinstance(p, dict)]
    units = {(p.get("unit") or "").lower() for p in clean if p.get("unit")}
    for u in priority:
        if u in units:
            return u
    for p in clean:
        u = (p.get("unit") or "").lower()
        if u:
            return u
    return None

def grams_from_qty_text(name: str, text: str, portions: list,
                        grams_from_local_registry_fn=grams_from_local_registry):
    s = (text or "").strip().lower()
    if not s:
        return 0.0, "", 0.0
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s)

    UNIT_MAP = {
        "tablespoon": "tbsp", "tbsp": "tbsp", "tbs": "tbsp",
        "teaspoon": "tsp", "tsp": "tsp",
        "cups": "cup", "cup": "cup",
        "cloves": "clove", "clove": "clove",
        "pieces": "piece", "piece": "piece",
        "ounces": "oz", "ounce": "oz", "oz": "oz",
        "pounds": "lb", "pound": "lb", "lb": "lb", "lbs": "lb",
        "g": "g", "gram": "g", "grams": "g",
        "slice": "slice", "slices": "slice",
        "cracker": "cracker", "crackers": "cracker",
        "whole": "whole"
    }

    m = re.match(r"^(\d+(?:\.\d+)?)\s*g$", s)
    if m:
        g = float(m.group(1))
        return g, "g", g

    m = re.match(r"^(\d+(?:\.\d+)?)$", s)
    if m:
        qty = float(m.group(1))
        unit = pick_default_unit(portions) or "whole"
        grams = guess_grams_from_unit(name, unit, qty, portions)
        if grams <= 0:
            grams = grams_from_local_registry_fn(name, unit, qty)
        return grams, unit, qty

    if set(s) == {"/"}:
        qty = float(len(s))
        unit = pick_default_unit(portions) or "whole"
        grams = guess_grams_from_unit(name, unit, qty, portions)
        if grams <= 0:
            grams = grams_from_local_registry_fn(name, unit, qty)
        return grams, unit, qty

    m = re.match(r"^(\d+(?:\.\d+)?)\s*/+$", s)
    if m:
        qty = float(m.group(1))
        unit = pick_default_unit(portions) or "whole"
        grams = guess_grams_from_unit(name, unit, qty, portions)
        if grams <= 0:
            grams = grams_from_local_registry_fn(name, unit, qty)
        return grams, unit, qty

    m = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)$", s)
    if m:
        qty = float(m.group(1))
        unit = UNIT_MAP.get(m.group(2), m.group(2))
        grams = guess_grams_from_unit(name, unit, qty, portions)
        if grams <= 0:
            grams = grams_from_local_registry_fn(name, unit, qty)
        if grams <= 0 and unit == "lb":
            grams = qty * 453.592
        elif grams <= 0 and unit == "oz":
            grams = qty * 28.3495
        return grams, unit, qty

    return 0.0, "", 0.0


# ---------------------- Route: /daily ----------------------

@daily_bp.route("/daily", methods=["GET", "POST"], endpoint="daily")
def daily():
    date_iso = request.args.get("date") or today_str()
    my_food_list = session.get("my_food_list", [])
    daymap = get_daymap(date_iso)
    targets = get_targets()

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "update_portions":
            qty_errors = {}
            qty_inputs = {}
            had_errors = False

            for f in my_food_list:
                fid = str(f.get("fdcId"))
                desc = f.get("description", "(item)")
                per100 = f.get("nutrients", {}) or {}

                raw = (request.form.get(f"qty_{fid}") or "").strip()
                if raw != "":
                    qty_inputs[fid] = raw

                if raw == "":
                    continue

                if raw.lower() in ("0", "clear", "none", "x"):
                    daymap.pop(fid, None)
                    continue

                parts = get_portions_for_fdc(fid, desc) or []
                if not isinstance(parts, (list, tuple)):
                    parts = []

                try:
                    grams, used_unit, used_qty = grams_from_qty_text(
                        desc, raw, parts, grams_from_local_registry_fn=grams_from_local_registry
                    )
                except Exception:
                    grams, used_unit, used_qty = 0.0, "", 0.0

                if grams <= 0:
                    had_errors = True
                    qty_errors[fid] = (
                        "Please enter e.g. 100g · // (=1) · 2// · 1 cup · 2 tbsp · 1 cracker · or 0 to clear."
                    )
                    qty_inputs[fid] = raw
                    continue

                per100 = normalize_per100(per100)
                scaled = {
                    name: round((per100.get(name, 0.0) * grams) / 100.0, 2)
                    for name in TARGET_NUTRIENTS.values()
                }
                if used_unit in ("g", "gram", "grams") or not used_unit:
                    portion_human = f"{grams:.0f} g"
                else:
                    portion_human = f"{used_qty:g} × {used_unit} (~{grams:.0f} g)"

                daymap[fid] = {
                    "fdcId": fid,
                    "name": desc,
                    "grams": grams,
                    "portion_human": portion_human,
                    "nutrients": scaled,
                }

            session.modified = True

            if had_errors:
                totals_raw   = sum_nutrients_from_map(daymap)
                prot_target  = session.get("protein_target", 60.0)
                cal_target   = session.get("cal_target", 2000.0)
                totals_view  = _build_totals_view(totals_raw, targets, prot_target, cal_target)

                portion_options = {}
                hints = {}
                for f in my_food_list:
                    _fid = str(f.get("fdcId"))
                    _desc = f.get("description", "")
                    _parts = get_portions_for_fdc(_fid, _desc)
                    portion_options[_fid] = _parts
                    hints[_fid] = build_hint_from_portions(_parts)

                top_sodium = None
                if daymap:
                    ranked = sorted(
                        daymap.values(),
                        key=lambda e: e["nutrients"].get("Sodium", 0.0),
                        reverse=True
                    )
                    total_na = totals_raw.get("Sodium", 0.0) or 1.0
                    share = round(100 * ranked[0]["nutrients"].get("Sodium", 0.0) / total_na, 1)
                    top_sodium = {"name": ranked[0]["name"], "share": share}

                return render_template(
                    "daily.html",
                    diary_date=date_iso,
                    my_food_list=my_food_list,
                    daymap=daymap,
                    targets=targets,
                    totals=totals_view,
                    portion_options=portion_options,
                    hints=hints,
                    insights={"top_sodium": top_sodium},
                    qty_errors=qty_errors,
                    qty_inputs=qty_inputs,
                )

            return redirect(url_for("daily.daily", date=date_iso))

        if action == "copy_yesterday":
            ydate = (datetime.date.fromisoformat(date_iso) - datetime.timedelta(days=1)).isoformat()
            ymap = session.get("diary_by_food", {}).get(ydate, {})
            session["diary_by_food"][date_iso] = {k: dict(v) for k, v in ymap.items()}
            session.modified = True
            return redirect(url_for("daily.daily", date=date_iso))

        if action == "clear_day":
            session["diary_by_food"][date_iso] = {}
            session.modified = True
            return redirect(url_for("daily.daily", date=date_iso))

        if action == "finalize_day":
            totals = sum_nutrients_from_map(daymap)
            history = session.setdefault("history", {})
            history[date_iso] = {"entries": list(daymap.values()), "totals": totals}
            session.modified = True
            return redirect(url_for("reports.history"))

    totals_raw   = sum_nutrients_from_map(daymap)
    prot_target  = session.get("protein_target", 60.0)
    cal_target   = session.get("cal_target", 2000.0)
    totals_view  = _build_totals_view(totals_raw, targets, prot_target, cal_target)

    top_sodium = None
    if daymap:
        ranked = sorted(daymap.values(), key=lambda e: e["nutrients"].get("Sodium", 0.0), reverse=True)
        total_na = totals_raw.get("Sodium", 0.0) or 1.0
        share = round(100 * ranked[0]["nutrients"].get("Sodium", 0.0) / total_na, 1)
        top_sodium = {"name": ranked[0]["name"], "share": share}

    return render_template(
        "daily.html",
        diary_date=date_iso,
        my_food_list=my_food_list,
        daymap=daymap,
        totals=totals_view,
        targets=targets,
        insights={"top_sodium": top_sodium},
        qty_errors={},
        qty_inputs={},
    )
