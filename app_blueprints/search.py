# app_blueprints/search.py
from flask import Blueprint, render_template, request, session, redirect, url_for
import re

from nutrition.constants import ALLOWED_TYPES, TARGET_NUTRIENTS
from nutrition.services.usda_client import search_foods
from nutrition.services.portions import portion_match_from_labels  # (future)
# from app_blueprints.luckysheet_api import append_rows  # <-- use our helper
from app_blueprints.luckysheet_api import append_rows_direct

search_bp = Blueprint("search", __name__, url_prefix="/search")

# --- Helpers (unchanged-ish) --------------------------------------------------


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
            except:  # noqa: E722
                pass
    for k in kj:
        v = n.get(k)
        if v not in (None, "", "NA"):
            try:
                return float(v) / 4.184
            except:  # noqa: E722
                pass
    return 0.0


def normalize_per100(n: dict) -> dict:
    """
    Normalize nutrient keys into our TARGET_NUTRIENTS naming.
    IMPORTANT: this function does *not* change the basis; it just maps keys and
    fills missing ones. If the incoming values are "per serving" (Branded) they
    remain per serving; if they are "per 100 g" (Legacy) they remain per 100 g.
    """
    n = dict(n or {})
    if not n.get("Calories"):
        n["Calories"] = _coerce_calories_from_usda(n)

    if "Carbs" not in n:
        for k in ["Carbohydrate, by difference", "Carbohydrate", "Carbohydrates"]:
            if k in n:
                try:
                    n["Carbs"] = float(n[k] or 0)
                except Exception:  # noqa: E722
                    n["Carbs"] = 0.0
                break
    if "Fat" not in n:
        for k in ["Total lipid (fat)", "Total Fat"]:
            if k in n:
                try:
                    n["Fat"] = float(n[k] or 0)
                except Exception:  # noqa: E722
                    n["Fat"] = 0.0
                break
    if "Sat Fat" not in n:
        for k in ["Fatty acids, total saturated", "Saturated Fat"]:
            if k in n:
                try:
                    n["Sat Fat"] = float(n[k] or 0)
                except Exception:  # noqa: E722
                    n["Sat Fat"] = 0.0
                break
    if "Mono Fat" not in n:
        for k in ["Fatty acids, total monounsaturated"]:
            if k in n:
                try:
                    n["Mono Fat"] = float(n[k] or 0)
                except Exception:  # noqa: E722
                    n["Mono Fat"] = 0.0
                break
    if "Poly Fat" not in n:
        for k in ["Fatty acids, total polyunsaturated"]:
            if k in n:
                try:
                    n["Poly Fat"] = float(n[k] or 0)
                except Exception:  # noqa: E722
                    n["Poly Fat"] = 0.0
                break
    if "Sugar" not in n:
        for k in ["Sugars, total including NLEA", "Sugars, total", "Sugar"]:
            if k in n:
                try:
                    n["Sugar"] = float(n[k] or 0)
                except Exception:  # noqa: E722
                    n["Sugar"] = 0.0
                break

    if "Sodium" not in n and "Sodium, Na" in n:
        try:
            n["Sodium"] = float(n["Sodium, Na"] or 0)
        except Exception:  # noqa: E722
            n["Sodium"] = 0.0
    if "Potassium" not in n and "Potassium, K" in n:
        try:
            n["Potassium"] = float(n["Potassium, K"] or 0)
        except Exception:  # noqa: E722
            n["Potassium"] = 0.0
    if "Calcium" not in n and "Calcium, Ca" in n:
        try:
            n["Calcium"] = float(n["Calcium, Ca"] or 0)
        except Exception:  # noqa: E722
            n["Calcium"] = 0.0
    if "Magnesium" not in n and "Magnesium, Mg" in n:
        try:
            n["Magnesium"] = float(n["Magnesium, Mg"] or 0)
        except Exception:  # noqa: E722
            n["Magnesium"] = 0.0
    if "Iron" not in n and "Iron, Fe" in n:
        try:
            n["Iron"] = float(n["Iron, Fe"] or 0)
        except Exception:  # noqa: E722
            n["Iron"] = 0.0
    if "Phosphorus" not in n and "Phosphorus, P" in n:
        try:
            n["Phosphorus"] = float(n["Phosphorus, P"] or 0)
        except Exception:  # noqa: E722
            n["Phosphorus"] = 0.0

    wanted = [
        "Sodium",
        "Potassium",
        "Phosphorus",
        "Calcium",
        "Magnesium",
        "Protein",
        "Carbs",
        "Fat",
        "Sat Fat",
        "Mono Fat",
        "Poly Fat",
        "Sugar",
        "Iron",
        "Calories",
    ]
    for k in wanted:
        try:
            n[k] = float(n.get(k, 0.0) or 0.0)
        except Exception:  # noqa: E722
            n[k] = 0.0
    return n


def compute_portion_preview(item: dict) -> None:
    """
    Compute a "portion preview" for display in the Items Found table.

    - For Branded items: use Nutrition Facts serving as-is from item["nutrients"]
      (which we populate from label-like values derived from per-100g) and set
      portion_grams from servingSize when numeric.

    - For Legacy/Foundation/etc: treat item["nutrients"] as per 100 g and scale
      to the preferred grams (pref.unit_key + pref.unit_grams).
    """
    GRAMS_PER_UNIT_DEFAULT = {
        "g": 100.0,
        "cup": 240.0,
        "tbsp": 15.0,
        "tsp": 5.0,
        "clove": 3.0,
    }
    if not isinstance(item, dict):
        return

    # Normalize keys but keep the basis (per serving vs per 100 g)
    per = normalize_per100(item.get("nutrients", {}))
    item["nutrients"] = per

    item.setdefault("computed", {})
    dtype = (item.get("dataType") or "").strip()

    # Branded → label serving
    if dtype == "Branded":
        serving_size = item.get("servingSize")
        grams = None
        try:
            if serving_size not in (None, ""):
                grams = float(serving_size)
        except Exception:  # noqa: E722
            grams = None

        item["computed"]["portion_grams"] = grams
        # For branded, the preview nutrients *are* the label nutrients
        item["computed"]["portion_nutrients"] = per
        return

    # Non-branded → assume per 100 g and scale based on pref/unit
    pref = item.setdefault("pref", {})
    unit_key = (pref.get("unit_key") or "").lower()
    unit_grams = pref.get("unit_grams")

    if unit_key == "g":
        if unit_grams not in (None, ""):
            grams = float(unit_grams)
        else:
            grams = GRAMS_PER_UNIT_DEFAULT["g"]
    else:
        if unit_grams not in (None, ""):
            grams = float(unit_grams)
        else:
            grams = GRAMS_PER_UNIT_DEFAULT.get(unit_key, 0.0)

    portion_nutrients = {}
    for k, v in per.items():
        try:
            portion_nutrients[k] = round((float(v) * grams) / 100.0, 2)
        except Exception:  # noqa: E722
            portion_nutrients[k] = 0.0

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
        except Exception:  # noqa: E722
            return None
    try:
        return float(tok)
    except Exception:  # noqa: E722
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

    # Pretty string (avoid trailing .0)
    if isinstance(val, float) and abs(val - round(val)) < 1e-9:
        num_str = str(int(round(val)))
    else:
        num_str = str(val)

    return (num_str, label)


# --- Routes -------------------------------------------------------------------


@search_bp.route("/search", methods=["GET"], endpoint="search")
def search():
    q = request.args.get("query", "").strip()
    page = int(request.args.get("page", 1))
    types_multi = request.args.getlist("types")
    dtype_legacy = request.args.get("type")

    if types_multi:
        selected_types = types_multi
    elif dtype_legacy and dtype_legacy != "All":
        selected_types = [dtype_legacy]
    else:
        selected_types = []

    if not q:
        return redirect(url_for("search.index"))

    data_types = selected_types if selected_types else None
    foods = search_foods(q, page_size=25, page_number=page, data_types=data_types)

    results = []
    for food in foods:
        dt = food.get("dataType", "")
        if dt not in ALLOWED_TYPES:
            continue

        fdc = str(food.get("fdcId", ""))
        desc = food.get("description", "") or "Unknown"
        detail = food.get("brandOwner") if dt == "Branded" else food.get(
            "foodCategory", "—"
        )

        # --- Step 1: build per-100g nutrients from foodNutrients ---------------
        per100_raw = {name: 0.0 for name in TARGET_NUTRIENTS.values()}
        for nut in (food.get("foodNutrients") or []):
            nid = (nut.get("nutrient") or {}).get("id") or nut.get("nutrientId")
            amt = nut.get("amount") or nut.get("value")
            if nid in TARGET_NUTRIENTS and isinstance(amt, (int, float)):
                key = TARGET_NUTRIENTS[nid]
                per100_raw[key] = float(amt)

        per100_norm = normalize_per100(per100_raw)

        # --- Step 2: derive label-serving nutrients for Branded items ---------
        nutrients_for_display = dict(per100_norm)  # default: per 100 g

        if dt == "Branded":
            serving_size = food.get("servingSize")
            try:
                serving_g = float(serving_size) if serving_size not in (None, "") else None
            except Exception:  # noqa: E722
                serving_g = None

            if serving_g and serving_g > 0:
                # Convert per-100g → per-serving (label table)
                label_nutrients = {}
                for k, v in per100_norm.items():
                    try:
                        label_nutrients[k] = (float(v) * serving_g) / 100.0
                    except Exception:  # noqa: E722
                        label_nutrients[k] = 0.0
                nutrients_for_display = label_nutrients

        results.append(
            {
                "fdcId": fdc,
                "description": desc,
                "detail": detail or "—",
                "dataType": dt,
                # What the user sees in "Items Found in USDA":
                # - Branded: per-serving (label-like) values
                # - Others: per-100g values
                "nutrients": nutrients_for_display,
                # Keep the per-100g map around for future math
                "nutrients_per100": per100_norm,
                # branded/sizing metadata
                "servingSize": food.get("servingSize"),
                "servingSizeUnit": food.get("servingSizeUnit"),
                "householdServingFullText": food.get("householdServingFullText"),
                "brandOwner": food.get("brandOwner"),
                "brandedFoodCategory": food.get("brandedFoodCategory"),
            }
        )

    session["search_results"] = results
    session["search_query"] = q
    session["search_types"] = selected_types
    session["search_page"] = page
    return redirect(url_for("search.index"))


@search_bp.route("/index", methods=["GET", "POST"], endpoint="index")
def index():
    search_results = session.get("search_results", [])
    query = session.get("search_query", "")
    page = session.get("search_page", 1)
    my_food_list = session.get("my_food_list", [])
    nutrient_names = list(TARGET_NUTRIENTS.values())

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            # Accumulate selected results in session; no Luckysheet append here
            selected_ids = request.form.getlist("selected_fdc")
            selected_items = [
                food for food in search_results if str(food.get("fdcId")) in selected_ids
            ]

            for item in selected_items:
                fid = str(item.get("fdcId"))
                if any(str(f.get("fdcId")) == fid for f in my_food_list):
                    continue

                # item["nutrients"] is already:
                #  - label-serving for Branded, or
                #  - per 100 g for others
                per_norm = normalize_per100(item.get("nutrients", {}))

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
                    # nutrient basis preserved (per serving for Branded; per 100 g for others)
                    "nutrients": per_norm,
                    # keep per-100g copy if we ever need grams/ounces math
                    "nutrients_per100": item.get("nutrients_per100"),
                    # default pref: 100 g for non-branded; unused for branded previews
                    "pref": {"unit_key": "g", "unit_grams": 100.0},
                }
                compute_portion_preview(new_entry)
                my_food_list.append(new_entry)

            session["my_food_list"] = my_food_list

        elif action == "export_luckysheet":
            # Append ALL currently accumulated items to the Luckysheet DB
            rows_for_luckysheet = []
            wanted = [
                "Sodium",
                "Potassium",
                "Protein",
                "Carbs",
                "Fat",
                "Sat Fat",
                "Mono Fat",
                "Poly Fat",
                "Sugar",
                "Calcium",
                "Magnesium",
                "Iron",
                "Calories",
            ]

            for f in my_food_list:
                per_norm = normalize_per100(f.get("nutrients", {}))
                num_label, label = split_household(
                    f.get("householdServingFullText") or ""
                )
                ss = f.get("servingSize") or ""
                ssu = f.get("servingSizeUnit") or ""
                row = [
                    (f.get("description") or "").strip() or "(item)",
                    ss,  # Serving Size
                    ssu,  # Serving Unit
                    num_label,  # Number Label
                    label,  # Label
                ]
                for k in wanted:
                    row.append(per_norm.get(k, 0.0) or 0.0)

                rows_for_luckysheet.append(row)

            if rows_for_luckysheet:
                append_rows_direct(rows_for_luckysheet)

        elif action == "remove_master":
            remove_ids = set(request.form.getlist("remove_id"))
            my_food_list = [
                f for f in my_food_list if str(f.get("fdcId")) not in remove_ids
            ]
            session["my_food_list"] = my_food_list

        elif action == "clear_master":
            my_food_list = []
            session["my_food_list"] = my_food_list

        elif action == "choose_unit":
            # Still supported for non-branded items (even though the UI column
            # was removed in the new template).
            fid = request.form.get("fid", "")
            unit_key = (request.form.get("unit_key") or "").lower()
            custom_g = request.form.get("unit_grams", "")
            unit_grams = None
            if custom_g not in (None, ""):
                try:
                    unit_grams = float(custom_g)
                except Exception:  # noqa: E722
                    unit_grams = None

            for f in my_food_list:
                if str(f.get("fdcId")) == str(fid):
                    # Don't rescale branded items based on arbitrary units
                    if (f.get("dataType") or "").strip() == "Branded":
                        break

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

    # Refresh previews every time we render
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
