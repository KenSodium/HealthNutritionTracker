# app_blueprints/search.py
from flask import Blueprint, render_template, request, session, redirect, url_for, current_app
import os
import json
import re

from nutrition.constants import ALLOWED_TYPES, TARGET_NUTRIENTS
from nutrition.services.usda_client import search_foods
from nutrition.services.portions import portion_match_from_labels  # (future)
from app_blueprints.luckysheet_api import append_rows_direct

search_bp = Blueprint("search", __name__, url_prefix="/search")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_calories_from_usda(n: dict) -> float:
    if not n:
        return 0.0
    kcal = ["Calories", "Energy (kcal)", "Energy", "calories", "Energy kcal"]
    kj = ["Energy (kJ)", "Energy (kj)", "kJ", "Kilojoules"]
    for k in kcal:
        v = n.get(k)
        if v not in (None, "", "NA"):
            try:
                return float(v)
            except Exception:
                pass
    for k in kj:
        v = n.get(k)
        if v not in (None, "", "NA"):
            try:
                return float(v) / 4.184
            except Exception:
                pass
    return 0.0


def normalize_per100(n: dict) -> dict:
    """
    Take a raw nutrient dict from USDA and normalize it into our
    canonical per-100g form with friendly keys.
    """
    n = dict(n or {})

    # Calories
    if not n.get("Calories"):
        n["Calories"] = _coerce_calories_from_usda(n)

    # Carbs
    if "Carbs" not in n:
        for k in ["Carbohydrate, by difference", "Carbohydrate", "Carbohydrates"]:
            if k in n:
                try:
                    n["Carbs"] = float(n[k] or 0)
                except Exception:
                    n["Carbs"] = 0.0
                break

    # Fat
    if "Fat" not in n:
        for k in ["Total lipid (fat)", "Total Fat"]:
            if k in n:
                try:
                    n["Fat"] = float(n[k] or 0)
                except Exception:
                    n["Fat"] = 0.0
                break

    # Sat fat
    if "Sat Fat" not in n:
        for k in ["Fatty acids, total saturated", "Saturated Fat"]:
            if k in n:
                try:
                    n["Sat Fat"] = float(n[k] or 0)
                except Exception:
                    n["Sat Fat"] = 0.0
                break

    # Mono fat
    if "Mono Fat" not in n:
        for k in ["Fatty acids, total monounsaturated"]:
            if k in n:
                try:
                    n["Mono Fat"] = float(n[k] or 0)
                except Exception:
                    n["Mono Fat"] = 0.0
                break

    # Poly fat
    if "Poly Fat" not in n:
        for k in ["Fatty acids, total polyunsaturated"]:
            if k in n:
                try:
                    n["Poly Fat"] = float(n[k] or 0)
                except Exception:
                    n["Poly Fat"] = 0.0
                break

    # Sugar
    if "Sugar" not in n:
        for k in ["Sugars, total including NLEA", "Sugars, total", "Sugar"]:
            if k in n:
                try:
                    n["Sugar"] = float(n[k] or 0)
                except Exception:
                    n["Sugar"] = 0.0
                break

    # Sodium / Potassium / Calcium / Magnesium / Iron / Phosphorus
    if "Sodium" not in n and "Sodium, Na" in n:
        try:
            n["Sodium"] = float(n["Sodium, Na"] or 0)
        except Exception:
            n["Sodium"] = 0.0
    if "Potassium" not in n and "Potassium, K" in n:
        try:
            n["Potassium"] = float(n["Potassium, K"] or 0)
        except Exception:
            n["Potassium"] = 0.0
    if "Calcium" not in n and "Calcium, Ca" in n:
        try:
            n["Calcium"] = float(n["Calcium, Ca"] or 0)
        except Exception:
            n["Calcium"] = 0.0
    if "Magnesium" not in n and "Magnesium, Mg" in n:
        try:
            n["Magnesium"] = float(n["Magnesium, Mg"] or 0)
        except Exception:
            n["Magnesium"] = 0.0
    if "Iron" not in n and "Iron, Fe" in n:
        try:
            n["Iron"] = float(n["Iron, Fe"] or 0)
        except Exception:
            n["Iron"] = 0.0
    if "Phosphorus" not in n and "Phosphorus, P" in n:
        try:
            n["Phosphorus"] = float(n["Phosphorus, P"] or 0)
        except Exception:
            n["Phosphorus"] = 0.0

    # Cholesterol (mg)
    if "Cholesterol" not in n:
        for k in ["Cholesterol", "Cholesterol, total"]:
            if k in n:
                try:
                    n["Cholesterol"] = float(n[k] or 0)
                except Exception:
                    n["Cholesterol"] = 0.0
                break

    # Canonical set we care about, coerced to float
    # (internal names, no units)
    wanted = [
        "Sodium",
        "Potassium",
        "Protein",
        "Calories",
        "Cholesterol",
        "Carbs",
        "Fat",
        "Sat Fat",
        "Mono Fat",
        "Poly Fat",
        "Sugar",
        "Calcium",
        "Magnesium",
        "Iron",
    ]
    for k in wanted:
        try:
            n[k] = float(n.get(k, 0.0) or 0.0)
        except Exception:
            n[k] = 0.0
    return n


def compute_portion_preview(item: dict) -> None:
    GRAMS_PER_UNIT_DEFAULT = {"g": 100.0, "cup": 240.0, "tbsp": 15.0, "tsp": 5.0, "clove": 3.0}
    if not isinstance(item, dict):
        return
    per100 = normalize_per100(item.get("nutrients", {}))
    item["nutrients"] = per100

    pref = item.setdefault("pref", {})
    unit_key = (pref.get("unit_key") or "").lower()
    unit_grams = pref.get("unit_grams")

    if unit_key == "g":
        grams = float(unit_grams) if unit_grams not in (None, "") else GRAMS_PER_UNIT_DEFAULT["g"]
    else:
        grams = float(unit_grams) if unit_grams not in (None, "") else GRAMS_PER_UNIT_DEFAULT.get(unit_key, 0.0)

    portion_nutrients = {}
    for k, v in per100.items():
        try:
            portion_nutrients[k] = round((float(v) * grams) / 100.0, 2)
        except Exception:
            portion_nutrients[k] = 0.0

    item.setdefault("computed", {})
    item["computed"]["portion_grams"] = round(grams, 2)
    item["computed"]["portion_nutrients"] = portion_nutrients


# --- Household label parsing helpers -----------------------------------------

_FRACTIONS = {
    "¼": 0.25,
    "½": 0.5,
    "¾": 0.75,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "⅛": 0.125,
    "⅜": 0.375,
    "⅝": 0.625,
    "⅞": 0.875,
}

import re as _re


def _parse_fraction_token(tok: str):
    tok = tok.strip()
    if tok in _FRACTIONS:
        return _FRACTIONS[tok]
    if "/" in tok:
        try:
            a, b = tok.split("/", 1)
            return float(a) / float(b)
        except Exception:
            return None
    try:
        return float(tok)
    except Exception:
        return None


def split_household(text: str):
    """
    Turn '3 slices' -> ('3','slices')
         '1 1/2 cups' -> ('1.5','cups')
         '½ cup (120 ml)' -> ('0.5','cup')
         'Slice' -> ('','Slice')
    Removes any (...) trailing details.
    """
    if not text:
        return ("", "")
    t = _re.sub(r"\(.*?\)", "", str(text)).strip()
    if not t:
        return ("", "")
    m = _re.match(
        r"^\s*(?P<num>(?:\d+(?:\.\d+)?)|(?:\d+\s+\d+/\d+)|(?:\d+/\d+)|(?:[¼½¾⅓⅔⅛⅜⅝⅞]))\s*(?P<label>[A-Za-z].*)?$",
        t,
    )
    if not m:
        return ("", t.strip())

    num_raw = m.group("num") or ""
    label = (m.group("label") or "").strip()

    if " " in num_raw and "/" in num_raw:
        a, b = num_raw.split(None, 1)
        a_val = _parse_fraction_token(a) or 0.0
        b_val = _parse_fraction_token(b) or 0.0
        val = (a_val or 0.0) + (b_val or 0.0)
    else:
        val = _parse_fraction_token(num_raw) or 0.0

    if isinstance(val, float) and abs(val - round(val)) < 1e-9:
        num_str = str(int(round(val)))
    else:
        num_str = str(val)

    return (num_str, label)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@search_bp.route("/search", methods=["GET"], endpoint="search")
def search():
    q = request.args.get("query", "").strip()
    types_multi = request.args.getlist("types")
    dtype_legacy = request.args.get("type")  # legacy support (not used by new UI)

    # Determine selected data types from checkboxes / legacy dropdown
    if types_multi:
        selected_types = types_multi
    elif dtype_legacy and dtype_legacy != "All":
        selected_types = [dtype_legacy]
    else:
        selected_types = []

    if not q:
        return redirect(url_for("search.index"))

    # Ask USDA for a *larger* page, 1 time (we'll rank & trim to 10 on our side)
    data_types = selected_types if selected_types else None
    foods = search_foods(q, page_size=100, page_number=1, data_types=data_types)

    results = []
    for food in foods:
        dt = food.get("dataType", "")
        if dt not in ALLOWED_TYPES:
            continue

        fdc = str(food.get("fdcId", ""))
        desc = food.get("description", "") or "Unknown"
        detail = food.get("brandOwner") if dt == "Branded" else food.get("foodCategory", "—")

        # Build base nutrient dict from TARGET_NUTRIENTS mapping (by nutrient id)
        zeroed = {name: 0.0 for name in TARGET_NUTRIENTS.values()}
        for nut in (food.get("foodNutrients") or []):
            nid = (nut.get("nutrient") or {}).get("id") or nut.get("nutrientId")
            amt = nut.get("amount") or nut.get("value")
            if nid in TARGET_NUTRIENTS and isinstance(amt, (int, float)):
                zeroed[TARGET_NUTRIENTS[nid]] = float(amt)

        # If no foodNutrients (e.g. some branded items), use labelNutrients as fallback
        if (not food.get("foodNutrients")) and food.get("labelNutrients"):
            for _, name in TARGET_NUTRIENTS.items():
                key = name.lower().replace(" ", "")
                val_container = food["labelNutrients"].get(key)
                if isinstance(val_container, dict):
                    val = val_container.get("value")
                else:
                    val = val_container
                if isinstance(val, (int, float)):
                    zeroed[name] = float(val)

        # Ensure Cholesterol exists in the dict
        if "Cholesterol" not in zeroed:
            zeroed["Cholesterol"] = 0.0

        # Try to detect cholesterol from foodNutrients by *name*.
        # Handle BOTH styles:
        #  - nested:  nut["nutrient"]["name"]
        #  - flat:    nut["nutrientName"]
        if zeroed.get("Cholesterol", 0.0) == 0.0:
            for nut in (food.get("foodNutrients") or []):
                nutrient_meta = nut.get("nutrient") or nut
                nname = (
                        nutrient_meta.get("name")
                        or nutrient_meta.get("nutrientName")
                        or ""
                ).lower()
                if "cholesterol" in nname:
                    amt = nut.get("amount") or nut.get("value")
                    if isinstance(amt, (int, float)):
                        zeroed["Cholesterol"] = float(amt)
                        break

        # If still zero, try labelNutrients['cholesterol'] (branded foods)
        if zeroed.get("Cholesterol", 0.0) == 0.0 and food.get("labelNutrients"):
            ln = food["labelNutrients"]
            chol_entry = ln.get("cholesterol")
            if isinstance(chol_entry, dict):
                val = chol_entry.get("value")
            else:
                val = chol_entry
            if isinstance(val, (int, float)):
                zeroed["Cholesterol"] = float(val)

        results.append(
            {
                "fdcId": fdc,
                "description": desc,
                "detail": detail or "—",
                "dataType": dt,
                "nutrients": zeroed,
                # branded/sizing metadata
                "servingSize": food.get("servingSize"),
                "servingSizeUnit": food.get("servingSizeUnit"),
                "householdServingFullText": food.get("householdServingFullText"),
                "brandOwner": food.get("brandOwner"),
                "brandedFoodCategory": food.get("brandedFoodCategory"),
            }
        )

    # --- Rank results so the best matches show up in the top 10 --------------

    q_low = q.lower()

    def _score_result(item: dict) -> float:
        desc = (item.get("description") or "").lower()
        detail_text = (item.get("detail") or "").lower()
        dt = item.get("dataType") or ""

        score = 0.0

        # Exact description match
        if desc == q_low:
            score += 100.0
        # Description starts with query
        if desc.startswith(q_low):
            score += 50.0
        # Query appears anywhere in description
        if q_low in desc:
            score += 25.0

        # Match in detail (brand / category)
        if detail_text == q_low:
            score += 15.0
        elif q_low in detail_text:
            score += 7.0

        # Prefer USDA "true" data over branded
        if dt in ("SR Legacy", "Foundation"):
            score += 5.0
        elif dt == "Survey (FNDDS)":
            score += 3.0
        elif dt == "Branded":
            score += 1.0

        return score

    results.sort(key=_score_result, reverse=True)

    # Keep only the best 10 for the Pick Foods table
    top_results = results[:10]

    session["search_results"] = top_results
    session["search_query"] = q
    session["search_types"] = selected_types
    # We no longer use USDA pagination, so no need for search_page here
    return redirect(url_for("search.index"))

@search_bp.route("/index", methods=["GET", "POST"], endpoint="index")
def index():
    search_results = session.get("search_results", [])
    query = session.get("search_query", "")
    page = session.get("search_page", 1)
    my_food_list = session.get("my_food_list", [])

    # NEW canonical nutrient order (internal names, no units)
    canonical_nutrient_order = [
        "Sodium",
        "Potassium",
        "Protein",
        "Calories",
        "Cholesterol",
        "Carbs",
        "Fat",
        "Sat Fat",
        "Mono Fat",
        "Poly Fat",
        "Sugar",
        "Calcium",
        "Magnesium",
        "Iron",
    ]
    # For the table headers we still use TARGET_NUTRIENTS values,
    # but in this new canonical order where they exist.
    nutrient_names = [
        name for name in canonical_nutrient_order if name in TARGET_NUTRIENTS.values()
    ]

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            selected_ids = request.form.getlist("selected_fdc")
            selected_items = [food for food in search_results if str(food.get("fdcId")) in selected_ids]

            for item in selected_items:
                fid = str(item.get("fdcId"))
                if any(str(f.get("fdcId")) == fid for f in my_food_list):
                    continue
                per100 = normalize_per100(item.get("nutrients", {}))
                new_entry = {
                    "fdcId": fid,
                    "description": item.get("description", "(item)"),
                    "dataType": item.get("dataType", ""),
                    "detail": item.get("detail", ""),
                    # branded/sizing metadata
                    "servingSize": item.get("servingSize"),
                    "servingSizeUnit": item.get("servingSizeUnit"),
                    "householdServingFullText": item.get("householdServingFullText"),
                    "brandOwner": item.get("brandOwner"),
                    "brandedFoodCategory": item.get("brandedFoodCategory"),
                    "nutrients": per100,
                    "pref": {"unit_key": "g", "unit_grams": 100.0},
                }
                compute_portion_preview(new_entry)
                my_food_list.append(new_entry)

            session["my_food_list"] = my_food_list

        elif action == "export_luckysheet":
            # Append ALL currently accumulated items to the Luckysheet DB
            rows_for_luckysheet = []

            # IMPORTANT: this order must match Univer HEAD2_COLUMNS (nutrient part)
            # HEAD2 nutrient columns in main.js (display with units):
            #   "Sodium (mg)",
            #   "Potassium (mg)",
            #   "Protein (g)",
            #   "Calories",
            #   "Cholesterol (mg)",
            #   "Carbs (g)",
            #   "Fat (g)",
            #   "Sat Fat (g)",
            #   "Mono Fat (g)",
            #   "Poly Fat (g)",
            #   "Sugar (g)",
            #   "Calcium (mg)",
            #   "Magnesium (mg)",
            #   "Iron (mg)",
            #
            # Here we use the *internal* names in the same order:
            wanted = [
                "Sodium",
                "Potassium",
                "Protein",
                "Calories",
                "Cholesterol",
                "Carbs",
                "Fat",
                "Sat Fat",
                "Mono Fat",
                "Poly Fat",
                "Sugar",
                "Calcium",
                "Magnesium",
                "Iron",
            ]

            for f in my_food_list:
                per100 = normalize_per100(f.get("nutrients", {}))
                num_label, label = split_household(f.get("householdServingFullText") or "")
                ss = f.get("servingSize") or ""
                ssu = f.get("servingSizeUnit") or ""

                # Data row: matches Univer "Food" + serving columns + nutrients
                row = [
                    (f.get("description") or "").strip() or "(item)",
                    ss,   # Serving Size
                    ssu,  # Serving Unit
                    num_label,  # Label Units
                    label,      # Unit Type (e.g., slices)
                ]
                for k in wanted:
                    row.append(per100.get(k, 0.0) or 0.0)

                rows_for_luckysheet.append(row)

            # Keep Luckysheet behavior as-is: append data rows only
            if rows_for_luckysheet:
                append_rows_direct(rows_for_luckysheet)

                # NEW: also write Univer foods_table.json with a proper header row
                try:
                    base = current_app.instance_path
                    univer_dir = os.path.join(base, "univer")
                    os.makedirs(univer_dir, exist_ok=True)
                    json_path = os.path.join(univer_dir, "foods_table.json")

                    # This header must match HEAD2_COLUMNS in Univer main.js
                    univer_header = [
                        "Food",
                        "Serving Size",
                        "Serving Unit",
                        "Label Units",
                        "Unit Type",
                        "Sodium (mg)",
                        "Potassium (mg)",
                        "Protein (g)",
                        "Calories",
                        "Cholesterol (mg)",
                        "Carbs (g)",
                        "Fat (g)",
                        "Sat Fat (g)",
                        "Mono Fat (g)",
                        "Poly Fat (g)",
                        "Sugar (g)",
                        "Calcium (mg)",
                        "Magnesium (mg)",
                        "Iron (mg)",
                    ]

                    # Univer rows: header + data
                    univer_rows = [univer_header] + rows_for_luckysheet

                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump({"rows": univer_rows}, f, ensure_ascii=False)

                    current_app.logger.info(
                        "Wrote Univer foods_table.json with %d data rows", len(rows_for_luckysheet)
                    )
                except Exception as e:
                    current_app.logger.exception("Failed to write Univer foods_table.json: %s", e)

        elif action == "remove_master":
            remove_ids = set(request.form.getlist("remove_id"))
            my_food_list = [f for f in my_food_list if str(f.get("fdcId")) not in remove_ids]
            session["my_food_list"] = my_food_list

        elif action == "clear_master":
            my_food_list = []
            session["my_food_list"] = my_food_list

        elif action == "choose_unit":
            fid = request.form.get("fid", "")
            unit_key = (request.form.get("unit_key") or "").lower()
            custom_g = request.form.get("unit_grams", "")
            unit_grams = None
            if custom_g not in (None, ""):
                try:
                    unit_grams = float(custom_g)
                except Exception:
                    unit_grams = None

            for f in my_food_list:
                if str(f.get("fdcId")) == str(fid):
                    pref = f.setdefault("pref", {})
                    if unit_key in ("g", "cup", "tbsp", "tsp", "clove"):
                        pref["unit_key"] = unit_key
                    if unit_grams is not None:
                        pref["unit_grams"] = unit_grams
                    else:
                        pref.pop("unit_grams", None)
                    compute_portion_preview(f)
                    break
            session["my_food_list"] = my_food_list

    # Normalize + recompute preview for display
    for f in my_food_list:
        f["nutrients"] = normalize_per100(f.get("nutrients", {}))
        compute_portion_preview(f)

    return render_template(
        "search/index.html",
        results=session.get("search_results", []),
        query=query,
        page=page,
        my_food_list=my_food_list,
        nutrient_names=nutrient_names,
        search_types=session.get("search_types", []),
    )
