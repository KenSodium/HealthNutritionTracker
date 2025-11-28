# app_blueprints/label_entry.py

import os
import json
from flask import Blueprint, render_template, request, session, redirect, url_for, current_app

# Reuse helpers from search
from app_blueprints.search import normalize_per100, split_household

label_bp = Blueprint("label_entry", __name__, url_prefix="/label")

# Canonical nutrient order for Univer / backend
CANONICAL_NUTRIENTS = [
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


def _field_name_for(n: str) -> str:
    # Turn "Sat Fat" -> "nut_Sat_Fat" for HTML input names
    return "nut_" + n.replace(" ", "_")


@label_bp.route("/", methods=["GET", "POST"])
def index():
    """
    Manual entry of a Nutrition Facts label.

    - User types values *per serving* (in the natural label order).
    - Internally we still compute per-100g for other parts of the app,
      but **Univer now always uses per-serving** values.
    - We append a new entry into session['my_food_list'] (for USDA page).
    - We rebuild instance/univer/foods_table.json from the master list
      using per-serving values (portion_nutrients).
    """
    my_food_list = session.get("my_food_list", [])

    if request.method == "POST":
        desc = (request.form.get("description") or "").strip() or "(manual label)"
        data_type = "Manual Label"

        household_text = request.form.get("householdServingFullText") or ""
        brand_owner = request.form.get("brandOwner") or ""

        # Serving size in grams (you’re entering grams directly on the page)
        serving_size_raw = request.form.get("serving_size") or ""
        try:
            grams_per_serving = float(serving_size_raw) if serving_size_raw not in ("", None) else 0.0
        except Exception:
            grams_per_serving = 0.0

        if grams_per_serving <= 0:
            grams_per_serving = 100.0  # last-resort fallback

        serving_unit = "g"

        # --- Internal per-100g nutrients (for consistency with existing code) ---
        per100 = {}
        for name in CANONICAL_NUTRIENTS:
            field_name = _field_name_for(name)
            raw = request.form.get(field_name, "")
            try:
                per_serving_val = float(raw) if raw not in ("", None) else 0.0
            except Exception:
                per_serving_val = 0.0

            # Keep internal semantics: per-100g
            per100[name] = round(per_serving_val * 100.0 / grams_per_serving, 4) if grams_per_serving > 0 else 0.0

        # Build the entry in the same shape as USDA entries
        new_entry = {
            "fdcId": f"manual-{len(my_food_list) + 1}",
            "description": desc,
            "dataType": data_type,
            "detail": "Manual Nutrition Label",
            "servingSize": grams_per_serving,
            "servingSizeUnit": serving_unit,
            "householdServingFullText": household_text,
            "brandOwner": brand_owner,
            "brandedFoodCategory": "Manual",
            "nutrients": per100,  # internal per-100g
            "pref": {"unit_key": "g", "unit_grams": grams_per_serving},
        }

        # Portion nutrients = exactly what you typed per serving
        portion_nutrients = {}
        # These are the label-entry nutrients in label order
        typed_names = [
            "Calories",
            "Fat",
            "Sat Fat",
            "Cholesterol",
            "Sodium",
            "Carbs",
            "Sugar",
            "Protein",
            "Calcium",
            "Iron",
            "Potassium",
        ]
        for name in typed_names:
            field_name = _field_name_for(name)
            raw = request.form.get(field_name, "")
            try:
                val = float(raw) if raw not in ("", None) else 0.0
            except Exception:
                val = 0.0
            portion_nutrients[name] = round(val, 2)

        new_entry["computed"] = {
            "portion_grams": round(grams_per_serving, 2),
            "portion_nutrients": portion_nutrients,
        }

        # Save to session for the USDA "Items Found" table
        my_food_list.append(new_entry)
        session["my_food_list"] = my_food_list
        session.modified = True

        # --------- REBUILD Univer foods_table.json USING PER-SERVING VALUES ---------
        # Header row must match HEAD2_COLUMNS from Univer main.js
        header = [
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

        nutrient_order = [
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

        rows = [header]

        for f in my_food_list:
            # Prefer per-serving nutrients if available
            comp = f.get("computed") or {}
            per_serving = comp.get("portion_nutrients")

            if not per_serving:
                # Fallback: derive something reasonable from nutrients
                per_serving = normalize_per100(f.get("nutrients", {}))

            # Serving info
            ss = f.get("servingSize") or 0
            ssu = f.get("servingSizeUnit") or "g"

            # Household label -> numeric amount + text (e.g. "2/3 cup")
            household_text = f.get("householdServingFullText") or ""
            label_units_str, unit_type = split_household(household_text)

            # For now keep the numeric value as float (we can pretty-print later)
            try:
                label_units = float(label_units_str) if label_units_str else ""
            except Exception:
                label_units = ""

            row = [
                (f.get("description") or "").strip() or "(manual label)",  # Food name
                ss,
                ssu,
                label_units,
                unit_type,
            ]

            # Append nutrients in canonical order (PER SERVING)
            for key in nutrient_order:
                row.append(per_serving.get(key, 0.0))

            # Skip totally empty rows (no description and all zeros)
            has_nutrients = any(v not in (0, 0.0, "", None) for v in row[5:])
            if has_nutrients:
                rows.append(row)

        base = current_app.instance_path
        univer_dir = os.path.join(base, "univer")
        os.makedirs(univer_dir, exist_ok=True)
        json_path = os.path.join(univer_dir, "foods_table.json")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"rows": rows}, f, ensure_ascii=False)

        # After saving, go straight to the Univer sheet
        return redirect(url_for("univer.univer_foods"))

    # GET: show the label entry form
    return render_template(
        "label/indexLabel.html",
        canonical_nutrients=CANONICAL_NUTRIENTS,
        field_name_for=_field_name_for,
    )
