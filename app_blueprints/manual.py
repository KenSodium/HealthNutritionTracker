# app_blueprints/manual.py
from flask import Blueprint, render_template, request, redirect, url_for, session
from nutrition.constants import LABEL_TO_NAME  # maps label text → canonical names
from nutrition.services.nutrients import normalize_per100  # already in your services

# --- Portion parsing: function + portions map (robust imports with fallback) ---
PORTION_DB = {}  # default, will be replaced by real mapping if available

try:
    # Your project originally imported the function from quantity_parser.
    # Many implementations expect: grams_from_qty_text(text, portions)
    from nutrition.services.quantity_parser import grams_from_qty_text, PORTIONS as PORTION_DB  # type: ignore
except Exception:
    try:
        from nutrition.services.quantity_parser import grams_from_qty_text, DEFAULT_PORTIONS as PORTION_DB  # type: ignore
    except Exception:
        # Final fallback: import just the function, supply our own minimal mapping below.
        try:
            from nutrition.services.quantity_parser import grams_from_qty_text  # type: ignore
        except Exception:
            # If even this fails, define a no-op parser that returns 0.0
            def grams_from_qty_text(*args, **kwargs):
                return 0.0  # type: ignore

# If nothing provided a map, use a conservative, generic one (units → grams)
if not PORTION_DB:
    PORTION_DB = {
        "g": 1.0, "gram": 1.0, "grams": 1.0,
        "slice": 28.0, "slices": 28.0,           # ≈ 1 oz per slice (generic)
        "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
        "lb": 453.592,
        "cup": 240.0, "cups": 240.0,            # generic volume; food-specific will vary
        "tbsp": 15.0, "tablespoon": 15.0,
        "tsp": 5.0, "teaspoon": 5.0,
        "serving": 0.0, "servings": 0.0,        # treat as unknown unless specified
    }

manual_bp = Blueprint("manual", __name__)

def _empty_label():
    # keys you care about; extend as needed
    return {
        "name": "",
        "brand": "",
        "serving_amount": "",     # e.g. "2/3 cup" or "1 slice" or "40 g"
        "serving_grams": "",      # explicit grams, if known (overrides parsing)
        "servings_per_container": "",
        "Calories": "",
        "Protein": "",
        "Carbs": "",
        "Fat": "",
        "Sat Fat": "",
        "Mono Fat": "",
        "Poly Fat": "",
        "Sugar": "",
        "Sodium": "",
        "Potassium": "",
        "Calcium": "",
        "Magnesium": "",
        "Iron": "",
        # add Phosphorus etc. if you track them
    }

@manual_bp.route("/manual", methods=["GET"], endpoint="form")
def form():
    data = session.get("manual_form_last", _empty_label())
    return render_template("manual_entry.html", data=data)

@manual_bp.route("/manual", methods=["POST"], endpoint="submit")
def submit():
    # 1) collect posted fields
    fields = _empty_label()
    for k in fields.keys():
        fields[k] = (request.form.get(k) or "").strip()

    session["manual_form_last"] = fields  # convenience

    # 2) derive serving grams
    serving_grams = 0.0

    # (a) explicit grams wins, if provided
    if fields["serving_grams"]:
        try:
            serving_grams = float(fields["serving_grams"])
        except ValueError:
            serving_grams = 0.0

    # (b) else parse free text like “2/3 cup”, “1 slice”, “40 g”, etc.
    if serving_grams <= 0.0 and fields["serving_amount"]:
        serving_text = fields["serving_amount"].strip()
        try:
            # Most implementations use: grams_from_qty_text(text, portions)
            serving_grams = float(grams_from_qty_text(serving_text, PORTION_DB) or 0.0)
        except TypeError:
            # If your function only accepts one arg (legacy), fall back
            try:
                serving_grams = float(grams_from_qty_text(serving_text) or 0.0)  # type: ignore
            except Exception:
                serving_grams = 0.0
        except Exception:
            serving_grams = 0.0

    # If still unknown, we can’t scale label values to per 100 g reliably.
    # We'll treat entered label values as already “per 100 g”.
    factor = (100.0 / serving_grams) if serving_grams > 0 else 1.0

    # 3) build a USDA-like detail (enough for your downstream code)
    per100 = {}
    for label_key, canonical_name in LABEL_TO_NAME.items():
        if canonical_name in (
            "Protein","Carbs","Fat","Sat Fat","Mono Fat","Poly Fat","Sugar",
            "Sodium","Potassium","Calcium","Magnesium","Iron","Calories"
        ):
            raw = fields.get(canonical_name, "")
            try:
                val = float(raw) if raw else 0.0
            except Exception:
                val = 0.0
            per100[canonical_name] = round(val * factor, 6)

    # 4) construct a “custom food” entry similar to USDA search result
    custom_id = f"custom:{(fields['name'] or 'Manual Food').strip()}".replace(" ", "_")
    custom_food = {
        "fdcId": custom_id,                 # non-numeric on purpose
        "description": fields["name"] or "Manual Food",
        "brandName": fields.get("brand", ""),
        "dataType": "Manual",
        "servingSize": serving_grams if serving_grams > 0 else None,
        "servingSizeUnit": "g" if serving_grams > 0 else None,
        "per100": per100,                   # normalized, per-100g nutrient dict
    }

    # 5) stash in a “custom foods” list so it appears alongside USDA foods
    my_foods = session.setdefault("my_food_list", [])
    # replace existing with same custom id, else append
    for i, f in enumerate(my_foods):
        if str(f.get("fdcId")) == custom_id:
            my_foods[i] = custom_food
            break
    else:
        my_foods.append(custom_food)
    session.modified = True

    # 6) redirect to daily page (or search page), as you already do after USDA adds
    return redirect(url_for("daily.daily"))
