# app.py (cleaned & consolidated)

from flask import Flask, render_template, request, redirect, url_for, session, make_response
from flask_session import Session
import os
import re
import io
import csv
import datetime
from datetime import date, timedelta
from statistics import mean
from functools import wraps
import random

# ---- project modules ----
from nutrition.constants import TARGET_NUTRIENTS, LABEL_TO_NAME, ALLOWED_TYPES
from nutrition.utils import today_str, get_targets, get_diary, sum_nutrients, calc_progress
from nutrition.services.units import grams_from_local_registry, parse_line_to_qty_unit_name
# NEW imports
from nutrition.services.nutrients import normalize_per100, recipe_per100_from_detail
from nutrition.services.quantity_parser import grams_from_qty_text  # (and GRAMS_PER_UNIT_DEFAULT if needed)
from nutrition.services.preview import compute_portion_preview

from nutrition.services.portions import (
    recipe_portions,
    derive_common_volumes_simple,
    portion_match_from_labels,
    get_portions_for_fdc,
    build_hint_from_portions,
    find_wiftee_portions_for_name,
    find_alt_portions_for_name,
)
from nutrition.services.usda_client import (
    search_foods,
    get_food_detail,
    search_top_for_recipes,
    search_best_fdc_for_recipes,
)
from nutrition.services.food_portion_ref import build_food_portion_rows

# 3rd-party
from fuzzywuzzy import fuzz


# =============================================================================
# Flask setup
# =============================================================================
app = Flask(__name__, template_folder="templates", static_folder="static")
# Diagnose template resolution
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
app.config['EXPLAIN_TEMPLATE_LOADING'] = True


app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")  # set BEFORE Session()

app.config.update(
    SESSION_TYPE="filesystem",
    SESSION_FILE_DIR=os.path.join(app.root_path, ".flask_session"),
    SESSION_PERMANENT=False,
    SESSION_COOKIE_NAME="sc_session",
    SESSION_USE_SIGNER=True,
)

os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
Session(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")  # TODO: secure in prod


def approx_session_bytes():
    """Debug helper for session size warnings."""
    import json
    try:
        return len(json.dumps(dict(session)))
    except Exception:
        return -1


# =============================================================================
# Small, file-local helpers / constants
# =============================================================================

RESTAURANT_KEYWORDS = [
    "restaurant", "diner", "takeout", "fast food", "served", "grilled", "sauce", "entrée",
]
SAUCE_ESTIMATES = {"light": 300, "normal": 700, "heavy": 1200}

FEATURED_NUTRIENTS = ["Sodium", "Potassium", "Protein", "Calories"]
ALL_HISTORY_NUTRIENTS = [
    "Sodium", "Protein", "Carbs", "Fat", "Sat Fat", "Mono Fat", "Poly Fat",
    "Sugar", "Potassium", "Calcium", "Magnesium", "Iron", "Calories"
]

# =============================================================================
# Diary helpers
# =============================================================================

def get_daymap(date: str) -> dict:
    """Return today's entries keyed by fdcId, e.g. {'12345': {grams, nutrients,...}}"""
    di = session.setdefault("diary_by_food", {})
    di.setdefault(date, {})
    return di[date]


def sum_nutrients_from_map(daymap: dict) -> dict:
    """Sum standard nutrients across all items in the daymap."""
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


def sum_named_nutrients(daymap: dict, names=ALL_HISTORY_NUTRIENTS) -> dict:
    """Sum only selected nutrients across today's items (daymap values)."""
    totals = {n: 0.0 for n in names}
    for rec in daymap.values():
        n = rec.get("nutrients", {})
        for k in names:
            v = n.get(k)
            if isinstance(v, (int, float)):
                totals[k] += float(v)
    return totals


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
        "na": round(na, 0),
        "k":  round(k, 0),
        "protein": round(protein, 0),
        "cal": round(cal, 0),

        "na_pct": na_pct, "na_class": na_cls,
        "k_pct":  k_pct,  "k_class":  k_cls,
        "prot_pct": pr_pct, "prot_class": pr_cls,
        "cal_pct":  cal_pct, "cal_class":  cal_cls,

        "prot_target": prot_t,
        "cal_target":  cal_t,
    }


# =============================================================================
# Auth helpers
# =============================================================================

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# =============================================================================
# Recipe helpers (per-100g from detail)
# =============================================================================

def recipe_per100_from_detail(detail: dict) -> dict:
    """
    Robust per-100g extractor for TARGET_NUTRIENTS.
    Prefers foodNutrients; falls back to labelNutrients scaled by servingSize grams.
    """
    per100 = {name: 0.0 for name in TARGET_NUTRIENTS.values()}

    # 1) Preferred: foodNutrients (already per 100 g for SR/Found/FNDDS)
    fn = detail.get("foodNutrients")
    if fn:
        for nut in fn:
            nutrient = (nut.get("nutrient") or {})
            nid = nutrient.get("id") or nut.get("nutrientId")
            number = nutrient.get("number")
            name = (nutrient.get("name") or "").lower()
            amt = nut.get("amount") or nut.get("value")
            if not isinstance(amt, (int, float)):
                continue
            if nid in TARGET_NUTRIENTS:
                per100[TARGET_NUTRIENTS[nid]] = float(amt)
            elif number == "208" or "energy" in name:
                per100["Calories"] = float(amt)
        return per100

    # 2) Fallback: labelNutrients + servingSize (must be grams)
    ln = detail.get("labelNutrients")
    serving = detail.get("servingSize")
    unit = (detail.get("servingSizeUnit") or "").lower()
    if ln and isinstance(serving, (int, float)) and unit in ("g", "gram", "grams"):
        mapping = {
            "protein": "Protein",
            "carbohydrates": "Carbs",
            "fat": "Fat",
            "saturatedFat": "Sat Fat",
            "monounsaturatedFat": "Mono Fat",
            "polyunsaturatedFat": "Poly Fat",
            "sugars": "Sugar",
            "calcium": "Calcium",
            "iron": "Iron",
            "calories": "Calories",
            "sodium": "Sodium",
        }
        factor = 100.0 / float(serving)
        for k, col in mapping.items():
            v = (ln.get(k) or {}).get("value")
            if isinstance(v, (int, float)):
                per100[col] = float(v) * factor
    return per100


# =============================================================================
# Clinician weekly report helpers
# =============================================================================

CLINICIAN_NUTRIENTS = [
    ("Sodium", "mg"),
    ("Potassium", "mg"),
    ("Phosphorus", "mg"),
    ("Calcium", "mg"),
    ("Magnesium", "mg"),
    ("Protein", "g"),
    ("Calories", "kcal"),
]


def _get_day_totals(day_iso: str) -> dict:
    """Sum your diary entries for a given YYYY-MM-DD into a nutrient dict."""
    day_entries = (session.get("diary", {}).get(day_iso, []) or [])
    bucket = {}
    for e in day_entries:
        for k, v in (e.get("nutrients") or {}).items():
            bucket[k] = bucket.get(k, 0.0) + float(v or 0.0)
    return bucket


def _status_for(name: str, avg_val: float, rng_min: float | None, rng_max: float | None, upper_only: float | None):
    """Return (emoji, text) based on simple ranges—tunable later."""
    # Sodium: use session targets if available
    if name == "Sodium":
        upper = (session.get("targets", {}) or {}).get("na", 1500)
        if avg_val <= 0.95 * upper:   return "✅", "Within target"
        if avg_val <= 1.20 * upper:   return "⚠️", "Slightly high"
        return "❌", "High"

    # Potassium (demo bounds)
    if name == "Potassium":
        lo, hi = 2000, 2500
        if avg_val < lo * 0.9:        return "⚠️", "Slightly low"
        if lo <= avg_val <= hi:       return "✅", "Within range"
        if avg_val <= hi * 1.1:       return "⚠️", "Slightly high"
        return "❌", "High"

    # Phosphorus (upper-only demo)
    if name == "Phosphorus":
        upper = 800
        if avg_val <= 0.95 * upper:   return "✅", "Good"
        if avg_val <= 1.10 * upper:   return "⚠️", "Slightly high"
        return "❌", "High"

    # Calcium (illustrative)
    if name == "Calcium":
        target = 1000
        if avg_val < 0.8 * target:    return "⚠️", "Low"
        if avg_val <= 1.1 * target:   return "✅", "Good"
        return "⚠️", "High"

    # Magnesium (illustrative)
    if name == "Magnesium":
        target = 400
        if avg_val < 0.9 * target:    return "⚠️", "Slightly low"
        if avg_val <= 1.1 * target:   return "✅", "Good"
        return "⚠️", "High"

    # Protein (example goal 60–70 g/day; tune or user-specific later)
    if name == "Protein":
        lo, hi = 60, 70
        if avg_val < lo * 0.9:        return "⚠️", "Low"
        if lo <= avg_val <= hi:       return "✅", "Good"
        if avg_val <= hi * 1.1:       return "⚠️", "Slightly high"
        return "❌", "High"

    # Calories (no hard judgment here)
    return "ℹ️", "—"


def _format_range(values: list[float]) -> str:
    if not values:
        return "—"
    return f"{min(values):.0f}–{max(values):.0f}"


# --- Daily Diary (shell) ------------------------------------------------------

from flask import jsonify

def _iso_today():
    return datetime.date.today().isoformat()

def _my_foods():
    # Expect your session to hold a list like you already use:
    # [{fdcId, description, nutrients(per100), pref: {unit_key, unit_grams}}, ...]
    foods = session.get("my_food_list", [])
    # ensure per100 exists under .nutrients
    for f in foods:
        f.setdefault("nutrients", f.get("per100", {}))
    return foods

def _day_entries_map(date_iso):
    # day entries stored under session['diary_entries'][date] = {id: {fdcId, grams, nutrients, description}}
    di = session.setdefault("diary_entries", {})
    di.setdefault(date_iso, {})
    return di[date_iso]

def _entry_id():
    # simple counter id
    c = session.setdefault("_entry_seq", 0) + 1
    session["_entry_seq"] = c
    return f"e{c}"

def _nutrients_for_grams(per100: dict, grams: float) -> dict:
    out = {}
    for k, v in (per100 or {}).items():
        try:
            out[k] = float(v) * (grams or 0.0) / 100.0
        except Exception:
            out[k] = 0.0
    return out

def _sum_totals(entries: dict) -> dict:
    keys = ["Sodium","Potassium","Phosphorus","Calcium","Magnesium","Protein","Carbs","Fat","Sat Fat","Mono Fat","Poly Fat","Sugar","Iron","Calories"]
    totals = {k: 0.0 for k in keys}
    for e in entries.values():
        for k in keys:
            totals[k] += float((e.get("nutrients") or {}).get(k, 0.0))
    # include targets for the JS bars
    totals["targets"] = session.get("targets", {"na": 1500, "k": 3400, "cal": 0})
    return totals

# --- Signed-in app (Tabler) ---
@app.route("/app/daily")
def app_daily():
    # render the NEW app template (no redirect to the old blueprint)
    date_iso = request.args.get("date") or datetime.date.today().isoformat()
    return render_template(
        "app/daily.html",
        date_iso=date_iso,
        my_foods=session.get("my_food_list", []),
    )

# --- API: save a food (create or update) ---
@app.route("/app/api/foods/save", methods=["POST"])
def api_foods_save():
    """Create or update a manual food in session['my_food_list'].

    Input JSON:
      {
        "id": "custom:Old_Name" | null,
        "name": "Bread",
        "brand": "BrandCo",
        "nutrients": { "Calories": 80, "Sodium": 180, ... },
        "serving_grams": 28,                 # optional
        "pref_unit": "g",                    # optional
        "pref_unit_grams": 240               # optional
      }
    """
    import re, random, string
    from flask import jsonify, request, session

    data = request.get_json(force=True, silent=True) or {}

    # --- read incoming fields ---
    incoming_id   = (data.get("id") or "").strip() or None
    name          = (data.get("name") or "").strip() or "Manual Food"
    brand         = (data.get("brand") or "").strip()
    per100        = data.get("nutrients") or {}
    serving_grams = data.get("serving_grams")
    pref_unit     = (data.get("pref_unit") or "g").lower()
    pref_unit_g   = data.get("pref_unit_grams")

    # sanitize numeric map
    clean_per100 = {}
    for k, v in per100.items():
        try:
            clean_per100[k] = float(v)
        except Exception:
            pass

    # normalize optional numbers
    try:
        serving_grams = float(serving_grams) if serving_grams not in (None, "", "0") else None
    except Exception:
        serving_grams = None
    try:
        pref_unit_g = float(pref_unit_g) if pref_unit_g not in (None, "", "0") else None
    except Exception:
        pref_unit_g = None

    # --- generate or reuse id ---
    def slug(s):
        s = re.sub(r"\s+", "_", s.strip())
        s = re.sub(r"[^a-zA-Z0-9_:-]", "", s)
        return s

    lst = session.setdefault("my_food_list", [])

    if incoming_id:
        fdc_id = incoming_id  # keep the same id on edit (even if name changed)
    else:
        base = f"custom:{slug(name)}"
        fdc_id = base
        # ensure uniqueness if name collides
        if any(str(f.get("fdcId")) == fdc_id for f in lst):
            suffix = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(4))
            fdc_id = f"{base}-{suffix}"

    # --- build item we store ---
    item = {
        "fdcId": fdc_id,
        "description": name,      # display name
        "brandName": brand,
        "dataType": "Manual",
        "per100": clean_per100,   # canonical nutrient bag
        "servingSize": serving_grams,
        "servingSizeUnit": "g" if serving_grams else None,
        "pref": {
            "unit_key": pref_unit,
            **({"unit_grams": pref_unit_g} if pref_unit_g is not None else {})
        }
    }

    # --- upsert by id ---
    replaced = False
    for i, f in enumerate(lst):
        if str(f.get("fdcId")) == fdc_id:
            lst[i] = item
            replaced = True
            break
    if not replaced:
        lst.append(item)

    session.modified = True
    return jsonify({"ok": True, "my_food_list": lst})

# ---- JSON API for the page ----

@app.route("/api/day")
def api_day_get():
    date_iso = request.args.get("date") or _iso_today()
    entries = _day_entries_map(date_iso)
    # flatten to list for the UI
    data = {
        "date": date_iso,
        "entries": list(entries.values()),
        "totals": _sum_totals(entries),
    }
    return jsonify(data)

@app.route("/api/day/add", methods=["POST"])
def api_day_add():
    payload = request.get_json(force=True) or {}
    date_iso = payload.get("date") or _iso_today()
    fdcId = str(payload.get("fdcId") or "").strip()
    grams = float(payload.get("grams") or 100.0)  # default 100 g; user can edit
    # find food in my list
    food = next((f for f in _my_foods() if str(f.get("fdcId")) == fdcId), None)
    if not food:
        return jsonify({"ok": False, "error": "food-not-found"}), 400

    per100 = food.get("nutrients", {})
    n = _nutrients_for_grams(per100, grams)
    entry = {
        "id": _entry_id(),
        "fdcId": fdcId,
        "description": food.get("description", "(item)"),
        "grams": grams,
        "nutrients": n,
    }
    daymap = _day_entries_map(date_iso)
    daymap[entry["id"]] = entry
    session.modified = True
    return jsonify({"ok": True, "entry": entry})

@app.route("/api/day/update", methods=["POST"])
def api_day_update():
    payload = request.get_json(force=True) or {}
    date_iso = payload.get("date") or _iso_today()
    eid = payload.get("id")
    field = payload.get("field")
    value = payload.get("value")
    entries = _day_entries_map(date_iso)
    rec = entries.get(eid)
    if not rec:
        return jsonify({"ok": False, "error": "entry-not-found"}), 404
    if field == "grams":
        grams = float(value or 0.0)
        rec["grams"] = grams
        # recompute nutrients from per100 if we still have the food
        food = next((f for f in _my_foods() if str(f.get("fdcId")) == str(rec.get("fdcId"))), None)
        per100 = (food or {}).get("nutrients", {})
        rec["nutrients"] = _nutrients_for_grams(per100, grams)
        session.modified = True
    return jsonify({"ok": True})

@app.route("/api/day/remove", methods=["POST"])
def api_day_remove():
    payload = request.get_json(force=True) or {}
    date_iso = payload.get("date") or _iso_today()
    eid = payload.get("id")
    entries = _day_entries_map(date_iso)
    if eid in entries:
        del entries[eid]
        session.modified = True
    return jsonify({"ok": True})


# =============================================================================
# Portions reference
# =============================================================================

# =============================================================================
# main
# =============================================================================
# =============================================================================
# Marketing & Auth routes (stay in app.py)
# =============================================================================
#


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        mode = request.form.get("mode")  # "demo" or form login
        if mode == "demo":
            session["user"] = {"name": "Demo User", "email": "demo@example.com", "plan": "premium"}
        else:
            name  = (request.form.get("name") or "Demo User").strip()
            email = (request.form.get("email") or "demo@example.com").strip()
            plan  = (request.form.get("plan") or "free").strip()
            session["user"] = {"name": name, "email": email, "plan": plan}

        # in /login POST handler
        nxt = request.args.get("next") or url_for("app_dashboard")  # or url_for("app_daily")
        return redirect(nxt)

    return render_template("marketing/login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name  = (request.form.get("name") or "Demo User").strip()
        email = (request.form.get("email") or "demo@example.com").strip()
        plan  = (request.form.get("plan") or "premium").strip()
        session["user"] = {"name": name, "email": email, "plan": plan}

        nxt = request.args.get("next") or url_for("daily.daily")
        return redirect(nxt)
    return render_template("marketing/signup.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))


@app.route("/sample-report")
def sample_report():
    return render_template("marketing/clinician_report_sample.html")

@app.route("/foodportions")
def food_portions():
    show_all = request.args.get("all") == "1"
    fdc_filter = set()
    if not show_all:
        for f in session.get("my_food_list", []):
            fid = str(f.get("fdcId", ""))
            if fid.isdigit():
                fdc_filter.add(int(fid))
    rows, cols = build_food_portion_rows(fdc_filter if fdc_filter else None)
    return render_template("food_portions.html", data=rows, columns=cols)

from flask import render_template, session, redirect, url_for

@app.route("/")
def marketing_home():
    # pure marketing landing, no app data required
    return render_template("landing.html")

@app.route("/demo/softui")
def softui_about_demo():
    return render_template("softui_about_demo.html")


app.add_url_rule("/", endpoint="home", view_func=marketing_home)

# Keep your existing app “home” (the one with totals/quick add) at /app
@app.route("/app")
def app_home():
    # if you have auth, gate it:
    # if not session.get("user_id"): return redirect(url_for("login"))
    home_totals = {
        "sodium": 0, "sodium_pct": 0, "sodium_remaining": 1500,
        "potassium": 0, "potassium_pct": 0, "potassium_remaining": 4000,
    }
    home_usuals = []
    return render_template("home.html", home_totals=home_totals, home_usuals=home_usuals)

@app.route("/demo/tabler")
def tabler_demo():
    # demo numbers – replace later with real aggregates
    kpis = {"sodium_avg": 1580, "potassium_avg": 3200}
    days = 7
    top_foods = [
        {"food": "Bread (1 slice)", "na": 180, "k": 35},
        {"food": "Deli turkey (3 oz)", "na": 780, "k": 220},
        {"food": "Pickles (2 spears)", "na": 620, "k": 40},
    ]
    return render_template("tabler_demo.html", kpis=kpis, days=days, top_foods=top_foods)

# --- Public pages (Soft UI) ---
@app.route("/how-to")
def how_to():
    return render_template("how_it_works.html")  # stub with anchors

@app.route("/about")
def about():
    return render_template("about.html")         # simple public page

@app.route("/subscribe")
def subscribe():
    return render_template("subscribe.html")     # pricing/CTA stub

# --- Bridges to existing features ---
@app.route("/food/search")
def food_search():
    return redirect(url_for("search.index"))     # your USDA search blueprint


@app.route("/app/reports/day")
def reports_day():
    return redirect(url_for("reports.history"))

@app.route("/app/reports/share")
def reports_share():
    return render_template("reports_share.html") # stub for share-link flow
# --- Dashboard (signed-in app) ---
@app.route("/app/dashboard")
def app_dashboard():
    # TODO: replace these placeholders with your real query (e.g., DB) later
    recent_days = [
        {"date": "2025-10-18", "sodium": 1420, "potassium": 3050, "calories": 1820},
        {"date": "2025-10-17", "sodium": 1560, "potassium": 2890, "calories": 1750},
        {"date": "2025-10-16", "sodium": 1310, "potassium": 3210, "calories": 1900},
        {"date": "2025-10-15", "sodium": 1495, "potassium": 2980, "calories": 1760},
        {"date": "2025-10-14", "sodium": 1620, "potassium": 3105, "calories": 1880},
    ]

    # If you already compute "today totals" elsewhere, pass those instead
    today = {"date": "2025-10-19", "sodium": 640, "potassium": 1100, "calories": 820}

    return render_template(
        "app/dashboard.html",
        recent_days=recent_days,
        today=today,
    )

# --- Food List Editor (signed-in app) ---
@app.route("/app/foods")
def app_foods():
    # gate if you want auth:  if not session.get("user"): return redirect(url_for("login", next=request.path))
    my_foods = session.get("my_food_list", [])
    return render_template("app/foods.html", my_foods=my_foods)

from flask import jsonify

def _ensure_my_food_list():
    lst = session.get("my_food_list")
    if not isinstance(lst, list):
        lst = []
    session["my_food_list"] = lst
    return lst

def _coerce_float(x):
    try: return float(x)
    except: return 0.0

def _canonicalize_item(payload: dict) -> dict:
    # Build a consistent “Manual” food entry with per-100g nutrients and optional serving pref
    nutrients = payload.get("nutrients") or {}
    per100 = {
        "Sodium":     _coerce_float(nutrients.get("Sodium")),
        "Potassium":  _coerce_float(nutrients.get("Potassium")),
        "Phosphorus": _coerce_float(nutrients.get("Phosphorus")),
        "Calcium":    _coerce_float(nutrients.get("Calcium")),
        "Magnesium":  _coerce_float(nutrients.get("Magnesium")),
        "Protein":    _coerce_float(nutrients.get("Protein")),
        "Carbs":      _coerce_float(nutrients.get("Carbs")),
        "Fat":        _coerce_float(nutrients.get("Fat")),
        "Sat Fat":    _coerce_float(nutrients.get("Sat Fat")),
        "Mono Fat":   _coerce_float(nutrients.get("Mono Fat")),
        "Poly Fat":   _coerce_float(nutrients.get("Poly Fat")),
        "Sugar":      _coerce_float(nutrients.get("Sugar")),
        "Iron":       _coerce_float(nutrients.get("Iron")),
        "Calories":   _coerce_float(nutrients.get("Calories")),
    }
    from uuid import uuid4
    fdcId = str(payload.get("fdcId") or f"custom:{uuid4().hex[:10]}")
    item = {
        "fdcId": fdcId,
        "description": (payload.get("description") or "").strip() or "Manual Food",
        "brandName": (payload.get("brandName") or "").strip(),
        "dataType": "Manual",
        "nutrients": per100,
    }
    # optional serving prefs
    pref = payload.get("pref") or {}
    if pref:
        item["pref"] = {}
        if pref.get("unit_key"):   item["pref"]["unit_key"] = str(pref["unit_key"]).lower()
        if str(pref.get("unit_grams") or "").strip() != "":
            try:
                item["pref"]["unit_grams"] = float(pref["unit_grams"])
            except:
                pass
    return item

@app.post("/api/foods/upsert")
def api_foods_upsert():
    data = request.get_json(silent=True) or {}
    item = _canonicalize_item(data)
    lst = _ensure_my_food_list()
    # replace existing id or append
    for i, f in enumerate(lst):
        if str(f.get("fdcId")) == str(item["fdcId"]):
            lst[i] = item
            break
    else:
        lst.append(item)
    session.modified = True
    return jsonify({"ok": True, "item": item})

@app.post("/api/foods/delete")
def api_foods_delete():
    data = request.get_json(silent=True) or {}
    fid = str(data.get("fdcId") or "")
    lst = _ensure_my_food_list()
    lst[:] = [f for f in lst if str(f.get("fdcId")) != fid]
    session.modified = True
    return jsonify({"ok": True, "deleted": fid})

@app.post("/api/foods/import")
def api_foods_import():
    """
    Accepts plain text in JSON: {"text": "..."} with CSV/TSV paste.
    Columns recognized (case-insensitive): description, brand, sodium, potassium, protein, calories, etc.
    """
    import csv, io
    payload = request.get_json(silent=True) or {}
    text = payload.get("text") or ""
    if not text.strip():
        return jsonify({"ok": False, "error": "empty"}), 400

    # auto-detect delimiter
    delimiter = "\t" if "\t" in text and "," not in text.splitlines()[0] else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    added = 0
    for row in reader:
        item = _canonicalize_item({
            "description": row.get("description") or row.get("name") or row.get("food") or "",
            "brandName": row.get("brand") or "",
            "nutrients": {
                "Sodium":     row.get("sodium"),
                "Potassium":  row.get("potassium"),
                "Phosphorus": row.get("phosphorus"),
                "Calcium":    row.get("calcium"),
                "Magnesium":  row.get("magnesium"),
                "Protein":    row.get("protein"),
                "Carbs":      row.get("carbs") or row.get("carbohydrates"),
                "Fat":        row.get("fat"),
                "Sat Fat":    row.get("sat fat") or row.get("saturated"),
                "Mono Fat":   row.get("mono fat"),
                "Poly Fat":   row.get("poly fat"),
                "Sugar":      row.get("sugar"),
                "Iron":       row.get("iron"),
                "Calories":   row.get("calories"),
            }
        })
        lst = _ensure_my_food_list()
        lst.append(item)
        added += 1
    session.modified = True
    return jsonify({"ok": True, "added": added})

@app.get("/api/foods/export.csv")
def api_foods_export_csv():
    lst = session.get("my_food_list", [])
    cols = ["fdcId","description","brandName","Sodium","Potassium","Phosphorus","Calcium","Magnesium","Protein","Carbs","Fat","Sat Fat","Mono Fat","Poly Fat","Sugar","Iron","Calories","unit_key","unit_grams"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for f in lst:
        n = f.get("nutrients") or {}
        pref = f.get("pref") or {}
        w.writerow([
            f.get("fdcId",""), f.get("description",""), f.get("brandName",""),
            n.get("Sodium",0), n.get("Potassium",0), n.get("Phosphorus",0),
            n.get("Calcium",0), n.get("Magnesium",0), n.get("Protein",0),
            n.get("Carbs",0), n.get("Fat",0), n.get("Sat Fat",0),
            n.get("Mono Fat",0), n.get("Poly Fat",0), n.get("Sugar",0),
            n.get("Iron",0), n.get("Calories",0),
            pref.get("unit_key",""), pref.get("unit_grams",""),
        ])
    out = buf.getvalue().encode("utf-8-sig")
    return make_response((out, 200, {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": "attachment; filename=foods_export.csv",
    }))


from flask import jsonify

def _foods_by_id():
    """Index my_food_list by fdcId for quick lookups."""
    foods = session.get("my_food_list", [])
    return {str(f.get("fdcId")): f for f in foods}

def _per100(n):
    """Ensure a per-100g nutrient dict with expected keys (safe defaults)."""
    wanted = ["Sodium","Potassium","Phosphorus","Calcium","Magnesium",
              "Protein","Carbs","Fat","Sat Fat","Mono Fat","Poly Fat",
              "Sugar","Iron","Calories"]
    out = {k: 0.0 for k in wanted}
    n = dict(n or {})
    for k in wanted:
        v = n.get(k)
        if isinstance(v, (int, float)):
            out[k] = float(v)
    return out

def _scale(n100, grams):
    """Scale per-100g dict by grams."""
    out = {}
    for k, v in n100.items():
        try:
            out[k] = (float(v) * float(grams)) / 100.0
        except Exception:
            out[k] = 0.0
    return out

@app.get("/app/api/diary")
def api_diary_get():
    date_iso = request.args.get("date") or datetime.date.today().isoformat()
    daymap = get_daymap(date_iso)  # {'fdcId': {'grams', 'nutrients', 'desc'}}
    # flatten for UI
    rows = []
    for fid, rec in daymap.items():
        rows.append({
            "fdcId": fid,
            "description": rec.get("description", fid),
            "grams": float(rec.get("grams", 0)),
            "na": float(rec.get("nutrients", {}).get("Sodium", 0)),
            "k":  float(rec.get("nutrients", {}).get("Potassium", 0)),
        })
    totals = sum_named_nutrients(daymap, names=["Sodium","Potassium","Protein","Calories"])
    return jsonify({"date": date_iso, "entries": rows, "totals": totals})

@app.post("/app/api/diary/add")
def api_diary_add():
    data = request.get_json(silent=True) or {}
    date_iso = data.get("date") or datetime.date.today().isoformat()
    fid = str(data.get("fdcId") or "")
    grams = float(data.get("grams") or 100.0)
    foods = _foods_by_id()
    food = foods.get(fid)
    if not food:
        return jsonify({"ok": False, "error": "food_not_found"}), 404

    n100 = _per100(food.get("nutrients"))
    entry = {
        "grams": grams,
        "nutrients": _scale(n100, grams),
        "description": food.get("description") or fid,
    }
    daymap = get_daymap(date_iso)
    daymap[fid] = entry
    session.modified = True
    return jsonify({"ok": True})

@app.post("/app/api/diary/qty")
def api_diary_qty():
    data = request.get_json(silent=True) or {}
    date_iso = data.get("date") or datetime.date.today().isoformat()
    fid = str(data.get("fdcId") or "")
    grams = float(data.get("grams") or 0)
    daymap = get_daymap(date_iso)
    rec = daymap.get(fid)
    foods = _foods_by_id()
    food = foods.get(fid)
    if not rec or not food:
        return jsonify({"ok": False, "error": "not_found"}), 404

    n100 = _per100(food.get("nutrients"))
    rec["grams"] = grams
    rec["nutrients"] = _scale(n100, grams)
    session.modified = True
    return jsonify({"ok": True})

@app.post("/app/api/diary/remove")
def api_diary_remove():
    data = request.get_json(silent=True) or {}
    date_iso = data.get("date") or datetime.date.today().isoformat()
    fid = str(data.get("fdcId") or "")
    daymap = get_daymap(date_iso)
    if fid in daymap:
        del daymap[fid]
        session.modified = True
    return jsonify({"ok": True})


# -----------------------------------------------------------------------------
# App factory (safe starter)
# -----------------------------------------------------------------------------
def create_app():
    """
    Return the already-configured global `app`.
    We now register all blueprints unconditionally (no SC_BP_* flags).
    """

    # --- Import blueprints (fail fast if a file is missing) ---
    from app_blueprints.reports import reports_bp
    from app_blueprints.daily import daily_bp
    from app_blueprints.search import search_bp
    from app_blueprints.recipes import recipes_bp
    from app_blueprints.coach import coach_bp
    from app_blueprints.manual import manual_bp

    # --- Register blueprints ---
    app.register_blueprint(reports_bp)
    app.register_blueprint(daily_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(recipes_bp)
    app.register_blueprint(coach_bp)
    app.register_blueprint(manual_bp)

    # --- Route dump (handy to see final endpoints) ---
    with app.app_context():
        print("\n==== ROUTES ====")
        for r in sorted(app.url_map.iter_rules(), key=lambda x: x.rule):
            print(f"{r.rule:28}  →  endpoint={r.endpoint}")
        print("================\n")

    return app

# --- Food List JSON save (manual-first) ---
from flask import jsonify

# TOP imports (make sure these are present)
from flask import jsonify, request, session

# ...

@app.route("/app/foods/save", methods=["POST"])
def foods_save():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip() or "Manual Food"

    prev_id = (data.get("id") or "").strip() or None
    new_id  = f"custom:{name}".replace(" ", "_")

    per100 = data.get("nutrients") or {}
    serving_grams = data.get("serving_grams")
    try:
        serving_grams = float(serving_grams) if serving_grams not in (None, "", "0") else None
    except Exception:
        serving_grams = None

    item = {
        "fdcId": new_id,
        "description": name,
        "brandName": data.get("brand") or "",
        "dataType": "Manual",
        "servingSize": serving_grams,
        "servingSizeUnit": "g" if serving_grams else None,
        "per100": per100,
        "pref": {
            "unit_key": (data.get("pref_unit") or "g").lower()
        }
    }
    if data.get("pref_unit_grams"):
        try:
            item["pref"]["unit_grams"] = float(data["pref_unit_grams"])
        except Exception:
            pass

    lst = session.setdefault("my_food_list", [])

    # Prefer replacing by prev_id (edit/rename)
    if prev_id:
        for i, f in enumerate(lst):
            if str(f.get("fdcId")) == prev_id:
                lst[i] = item
                break
        else:
            lst.append(item)
    else:
        # Fallback: replace by new_id (same-name edit) or append
        for i, f in enumerate(lst):
            if str(f.get("fdcId")) == new_id:
                lst[i] = item
                break
        else:
            lst.append(item)

    session.modified = True
    return jsonify({"ok": True, "my_food_list": lst})

from flask import render_template  # you likely already have this

@app.get("/app/foods/grid")
def app_foods_grid():
    return render_template("app/foods_grid.html")
print(app.url_map)

@app.get("/app/foods/glide")
def app_foods_glide():
    return render_template("app/grid_glide.html")



app = create_app()  # safe: returns the same global `app`
if __name__ == "__main__":
    print(f"~ Session size (approx): {approx_session_bytes()} bytes")
    app.run(debug=True)

