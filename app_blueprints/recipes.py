# app_blueprints/recipes.py
from flask import Blueprint, render_template, request, session, redirect, url_for
from nutrition.constants import TARGET_NUTRIENTS
from nutrition.services.usda_client import (
    get_food_detail, search_top_for_recipes, search_best_fdc_for_recipes
)
from nutrition.services.portions import (
    recipe_portions, derive_common_volumes_simple, portion_match_from_labels,
    find_wiftee_portions_for_name, find_alt_portions_for_name
)
from nutrition.services.units import grams_from_local_registry, parse_line_to_qty_unit_name

recipes_bp = Blueprint("recipes", __name__)

# --- helper copied from app.py to avoid circular imports ---
def recipe_per100_from_detail(detail: dict) -> dict:
    per100 = {name: 0.0 for name in TARGET_NUTRIENTS.values()}

    # Preferred: foodNutrients
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

    # Fallback: labelNutrients scaled by servingSize (grams)
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
# -----------------------------------------------------------

@recipes_bp.route("/recipes", methods=["GET", "POST"], endpoint="recipes")
def recipes():
    session.setdefault("recipe_items", [])
    session.setdefault("recipe_picker", {})
    items = session["recipe_items"]
    picker = session["recipe_picker"]
    names = list(TARGET_NUTRIENTS.values())

    search_hits = []
    picked_detail = None
    picked_portions = []

    if request.method == "POST":
        action = request.form.get("action", "")

        # ---------- step 1: search ----------
        if action == "search":
            q = (request.form.get("ingredient_query") or "").strip()
            if q:
                picker.clear()
                search_hits = search_top_for_recipes(q, limit=10)
                picker["hits"] = search_hits
                picker["query"] = q
                session.modified = True

        # ---------- step 2: pick -> load detail + portions ----------
        elif action == "pick":
            fdc = request.form.get("fdc_pick")
            if fdc:
                det = get_food_detail(fdc)
                if det:
                    picker["fdcId"] = fdc
                    picker["detail"] = {
                        "description": det.get("description", "Unknown"),
                        "dataType": det.get("dataType", ""),
                    }
                    picker["per100"] = recipe_per100_from_detail(det)

                    base_parts = recipe_portions(det)  # may be empty
                    if not base_parts:
                        alt_parts = find_alt_portions_for_name(det.get("description", ""))
                        base_parts = alt_parts or []
                        if not base_parts:
                            base_parts = find_wiftee_portions_for_name(det.get("description", ""))

                    picker["portions"] = derive_common_volumes_simple(base_parts)
                    session.modified = True

        # ---------- step 3a: add by grams ----------
        elif action == "add_by_grams":
            graw = (request.form.get("grams_input") or "").strip()
            try:
                g = float(graw)
            except ValueError:
                g = 0.0
            per100 = picker.get("per100") or {}
            desc = (picker.get("detail") or {}).get("description") or "(item)"
            if g > 0 and per100:
                scaled = {n: round(per100.get(n, 0.0) * g / 100.0, 4) for n in names}
                items.append({"name": desc, "grams": g, "per100": per100, "scaled": scaled})
                session["recipe_picker"] = {}
                session.modified = True
                return redirect(url_for("recipes.recipes"))

        # ---------- step 3b: add by portion ----------
        elif action == "add_by_portion":
            sel = request.form.get("portion_id")
            qty_raw = (request.form.get("portion_qty") or "").strip()
            try:
                qty = float(qty_raw)
            except ValueError:
                qty = 0.0
            portions = picker.get("portions") or []
            per100 = picker.get("per100") or {}
            desc = (picker.get("detail") or {}).get("description") or "(item)"
            if sel is not None and per100 and portions and qty > 0:
                p = next((o for o in portions if o["id"] == sel), None)
                if p:
                    grams = p["gramWeight"] * qty
                    scaled = {n: round(per100.get(n, 0.0) * grams / 100.0, 4) for n in names}
                    items.append(
                        {"name": f"{desc} – {qty}× {p['label']}", "grams": grams, "per100": per100, "scaled": scaled}
                    )
                    session["recipe_picker"] = {}
                    session.modified = True
                    return redirect(url_for("recipes.recipes"))

        # ---------- step 3c: add by free unit ----------
        elif action == "add_by_unit":
            unit = (request.form.get("unit_name") or "").strip()
            qty_raw = (request.form.get("unit_qty") or "").strip()
            try:
                qty = float(qty_raw)
            except ValueError:
                qty = 0.0

            portions = picker.get("portions") or []
            per100 = picker.get("per100") or {}
            desc = (picker.get("detail") or {}).get("description") or "(item)"

            grams = 0.0
            if unit and qty > 0 and per100:
                if portions:
                    p = portion_match_from_labels(portions, unit)
                    if p and isinstance(p.get("gramWeight"), (int, float)):
                        grams = float(p["gramWeight"]) * qty
                if grams <= 0:
                    grams = grams_from_local_registry(desc, unit, qty)

            if grams > 0:
                scaled = {n: round(per100.get(n, 0.0) * grams / 100.0, 4) for n in names}
                items.append(
                    {"name": f"{desc} – {qty}× {unit}", "grams": grams, "per100": per100, "scaled": scaled}
                )
                session["recipe_picker"] = {}
                session.modified = True
                return redirect(url_for("recipes.recipes"))
            else:
                session["recipe_notice"] = (
                    f"No conversion for unit '{unit}' with item '{desc}'. "
                    f"Try 'cup', 'tbsp', 'tsp', 'whole', or add a mapping."
                )
                session.modified = True
                return redirect(url_for("recipes.recipes"))

        # ---------- bulk add ----------
        elif action == "bulk_add":
            raw = (request.form.get("bulk_text") or "").splitlines()
            for line in raw:
                qty, unit, name = parse_line_to_qty_unit_name(line)
                if not name or not qty:
                    continue

                fdc = search_best_fdc_for_recipes(name)
                if not fdc:
                    continue
                det = get_food_detail(fdc)
                if not det:
                    continue

                per100 = recipe_per100_from_detail(det)
                portions = derive_common_volumes_simple(recipe_portions(det))

                grams = 0.0
                if unit and portions:
                    pm = portion_match_from_labels(portions, unit)
                    if pm and isinstance(pm.get("gramWeight"), (int, float)):
                        grams = float(pm["gramWeight"]) * float(qty)

                if grams <= 0 and unit:
                    grams = grams_from_local_registry(det.get("description") or name, unit, qty)

                if grams == 0.0 and unit:
                    if unit in ("pound", "lb"):
                        grams = float(qty) * 453.592
                    elif unit in ("ounce", "oz"):
                        grams = float(qty) * 28.3495

                if grams <= 0:
                    session["recipe_notice"] = f"Could not convert '{line.strip()}'."
                    session.modified = True
                    continue

                desc = det.get("description") or name
                scaled = {n: round(per100.get(n, 0.0) * grams / 100.0, 4) for n in names}
                items.append({"name": f"{desc} – {line.strip()}", "grams": grams, "per100": per100, "scaled": scaled})

            session["recipe_picker"] = {}
            session.modified = True
            return redirect(url_for("recipes.recipes"))

        # ---------- remove / clear / picker clear ----------
        elif action == "remove":
            idxs = {int(x) for x in request.form.getlist("remove_index") if x.isdigit()}
            session["recipe_items"] = [it for i, it in enumerate(items) if i not in idxs]
            items = session["recipe_items"]
            session.modified = True

        elif action == "clear_items":
            session["recipe_items"] = []
            items = []
            session.modified = True

        elif action == "clear_picker":
            session["recipe_picker"] = {}
            picker = session["recipe_picker"]
            session.modified = True

        # save/send (deferred wiring)
        elif action == "save_to_my_list":
            pass
        elif action == "send_to_daily":
            pass

    # build picker data after POST
    search_hits = picker.get("hits") or []
    picked_detail = picker.get("detail")
    picked_portions = picker.get("portions") or []  # already simplified above
    notice = session.pop("recipe_notice", "")

    # totals and weighted per-100g
    totals = {n: 0.0 for n in names}
    total_weight = 0.0
    for it in items:
        g = float(it["grams"])
        total_weight += g
        per100_i = it["per100"]
        for n in names:
            totals[n] += float(per100_i.get(n, 0.0)) * g / 100.0

    recipe_per100 = {n: 0.0 for n in names}
    if total_weight > 0:
        for n in names:
            recipe_per100[n] = totals[n] / total_weight * 100.0

    return render_template(
        "recipes.html",
        nutrient_names=names,
        items=items,
        search_hits=search_hits,
        picked_detail=picked_detail,
        picked_portions=picked_portions,
        totals={n: round(totals[n], 2) for n in names},
        total_weight=round(total_weight, 2),
        recipe_per100={n: round(recipe_per100[n], 2) for n in names},
        notice=notice,
    )
