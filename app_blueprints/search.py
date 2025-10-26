# app_blueprints/search.py
from flask import Blueprint, render_template, request, session, redirect, url_for
import re

from nutrition.constants import ALLOWED_TYPES, TARGET_NUTRIENTS
from nutrition.services.usda_client import search_foods
from nutrition.services.portions import portion_match_from_labels  # (not used here, but handy later)

# Mount this blueprint under /search so the site root (/) can show your public landing page.
search_bp = Blueprint("search", __name__, url_prefix="/search")

# --- Minimal helpers (copied to avoid circular imports with app.py) -----------
def _coerce_calories_from_usda(n: dict) -> float:
    if not n:
        return 0.0
    kcal = ["Calories", "Energy (kcal)", "Energy", "calories", "Energy kcal"]
    kj   = ["Energy (kJ)", "Energy (kj)", "kJ", "Kilojoules"]
    for k in kcal:
        v = n.get(k)
        if v not in (None, "", "NA"):
            try:
                return float(v)
            except:
                pass
    for k in kj:
        v = n.get(k)
        if v not in (None, "", "NA"):
            try:
                return float(v) / 4.184
            except:
                pass
    return 0.0

def normalize_per100(n: dict) -> dict:
    n = dict(n or {})
    if not n.get("Calories"):
        n["Calories"] = _coerce_calories_from_usda(n)

    if "Carbs" not in n:
        for k in ["Carbohydrate, by difference", "Carbohydrate", "Carbohydrates"]:
            if k in n:
                try:
                    n["Carbs"] = float(n[k] or 0)
                except:
                    n["Carbs"] = 0.0
                break
    if "Fat" not in n:
        for k in ["Total lipid (fat)", "Total Fat"]:
            if k in n:
                try:
                    n["Fat"] = float(n[k] or 0)
                except:
                    n["Fat"] = 0.0
                break
    if "Sat Fat" not in n:
        for k in ["Fatty acids, total saturated", "Saturated Fat"]:
            if k in n:
                try:
                    n["Sat Fat"] = float(n[k] or 0)
                except:
                    n["Sat Fat"] = 0.0
                break
    if "Mono Fat" not in n:
        for k in ["Fatty acids, total monounsaturated"]:
            if k in n:
                try:
                    n["Mono Fat"] = float(n[k] or 0)
                except:
                    n["Mono Fat"] = 0.0
                break
    if "Poly Fat" not in n:
        for k in ["Fatty acids, total polyunsaturated"]:
            if k in n:
                try:
                    n["Poly Fat"] = float(n[k] or 0)
                except:
                    n["Poly Fat"] = 0.0
                break
    if "Sugar" not in n:
        for k in ["Sugars, total including NLEA", "Sugars, total", "Sugar"]:
            if k in n:
                try:
                    n["Sugar"] = float(n[k] or 0)
                except:
                    n["Sugar"] = 0.0
                break

    if "Sodium" not in n and "Sodium, Na" in n:
        try:
            n["Sodium"] = float(n["Sodium, Na"] or 0)
        except:
            n["Sodium"] = 0.0
    if "Potassium" not in n and "Potassium, K" in n:
        try:
            n["Potassium"] = float(n["Potassium, K"] or 0)
        except:
            n["Potassium"] = 0.0
    if "Calcium" not in n and "Calcium, Ca" in n:
        try:
            n["Calcium"] = float(n["Calcium, Ca"] or 0)
        except:
            n["Calcium"] = 0.0
    if "Magnesium" not in n and "Magnesium, Mg" in n:
        try:
            n["Magnesium"] = float(n["Magnesium, Mg"] or 0)
        except:
            n["Magnesium"] = 0.0
    if "Iron" not in n and "Iron, Fe" in n:
        try:
            n["Iron"] = float(n["Iron, Fe"] or 0)
        except:
            n["Iron"] = 0.0
    if "Phosphorus" not in n and "Phosphorus, P" in n:
        try:
            n["Phosphorus"] = float(n["Phosphorus, P"] or 0)
        except:
            n["Phosphorus"] = 0.0

    wanted = ["Sodium","Potassium","Phosphorus","Calcium","Magnesium",
              "Protein","Carbs","Fat","Sat Fat","Mono Fat","Poly Fat",
              "Sugar","Iron","Calories"]
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
# -----------------------------------------------------------------------------


@search_bp.route("/search", methods=["GET"], endpoint="search")
def search():
    """
    USDA search under /search/search — stores compact 100g summaries,
    then redirects back to the review page at /search/index.
    """
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
        detail = food.get("brandOwner") if dt == "Branded" else food.get("foodCategory", "—")

        zeroed = {name: 0.0 for name in TARGET_NUTRIENTS.values()}
        for nut in (food.get("foodNutrients") or []):
            nid = (nut.get("nutrient") or {}).get("id") or nut.get("nutrientId")
            amt = nut.get("amount") or nut.get("value")
            if nid in TARGET_NUTRIENTS and isinstance(amt, (int, float)):
                zeroed[TARGET_NUTRIENTS[nid]] = float(amt)

        if (not food.get("foodNutrients")) and food.get("labelNutrients"):
            for _, name in TARGET_NUTRIENTS.items():
                key = name.lower().replace(" ", "")
                val = (food["labelNutrients"].get(key) or {}).get("value")
                if isinstance(val, (int, float)):
                    zeroed[name] = float(val)

        results.append({
            "fdcId": fdc,
            "description": desc,
            "detail": detail or "—",
            "dataType": dt,
            "nutrients": zeroed,
        })

    session["search_results"] = results
    session["search_query"] = q
    session["search_types"] = selected_types
    session["search_page"] = page
    return redirect(url_for("search.index"))


@search_bp.route("/index", methods=["GET", "POST"], endpoint="index")
def index():
    """
    Review + manage 'My Food List' under /search/index.
    """
    search_results = session.get("search_results", [])
    query = session.get("search_query", "")
    dtype = session.get("search_dtype", "All")
    page = session.get("search_page", 1)
    my_food_list = session.get("my_food_list", [])
    nutrient_names = list(TARGET_NUTRIENTS.values())

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
                    "nutrients": per100,
                    "pref": {"unit_key": "g", "unit_grams": 100.0},
                }
                compute_portion_preview(new_entry)
                my_food_list.append(new_entry)
            session["my_food_list"] = my_food_list

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

    for f in my_food_list:
        f["nutrients"] = normalize_per100(f.get("nutrients", {}))
        compute_portion_preview(f)

    return render_template(
        "index.html",
        results=session.get("search_results", []),
        query=query,
        dtype=dtype,
        page=page,
        my_food_list=my_food_list,
        nutrient_names=nutrient_names,
        search_types=session.get("search_types", []),
    )
