# nutrition/services/nutrients.py
from __future__ import annotations
from nutrition.constants import TARGET_NUTRIENTS

# Energy/Calories normalization keys
ENERGY_KEYS_KCAL = ["Calories", "Energy (kcal)", "Energy", "calories", "Energy kcal"]
ENERGY_KEYS_KJ   = ["Energy (kJ)", "Energy (kj)", "kJ", "Kilojoules"]

def _coerce_calories_from_usda(n: dict) -> float:
    """Return Calories (kcal) no matter how USDA labeled it; convert kJ → kcal if needed."""
    if not n:
        return 0.0
    for k in ENERGY_KEYS_KCAL:
        v = n.get(k)
        if v not in (None, "", "NA"):
            try:
                return float(v)
            except Exception:
                pass
    for k in ENERGY_KEYS_KJ:
        v = n.get(k)
        if v not in (None, "", "NA"):
            try:
                return float(v) / 4.184  # kJ → kcal
            except Exception:
                pass
    return 0.0

def normalize_per100(n: dict) -> dict:
    """
    Ensure per-100g 'nutrients' dict always has the 13 keys we care about,
    especially 'Calories'. Also map common USDA synonyms.
    """
    n = dict(n or {})
    # Calories first
    if not n.get("Calories"):
        n["Calories"] = _coerce_calories_from_usda(n)

    # carbs / fats (common USDA names)
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

    # minerals synonyms
    if "Sodium" not in n and "Sodium, Na" in n:
        try: n["Sodium"] = float(n["Sodium, Na"] or 0)
        except: n["Sodium"] = 0.0
    if "Potassium" not in n and "Potassium, K" in n:
        try: n["Potassium"] = float(n["Potassium, K"] or 0)
        except: n["Potassium"] = 0.0
    if "Calcium" not in n and "Calcium, Ca" in n:
        try: n["Calcium"] = float(n["Calcium, Ca"] or 0)
        except: n["Calcium"] = 0.0
    if "Magnesium" not in n and "Magnesium, Mg" in n:
        try: n["Magnesium"] = float(n["Magnesium, Mg"] or 0)
        except: n["Magnesium"] = 0.0
    if "Iron" not in n and "Iron, Fe" in n:
        try: n["Iron"] = float(n["Iron, Fe"] or 0)
        except: n["Iron"] = 0.0
    if "Phosphorus" not in n and "Phosphorus, P" in n:
        try: n["Phosphorus"] = float(n["Phosphorus, P"] or 0)
        except: n["Phosphorus"] = 0.0

    # make sure numeric for all keys we show
    wanted = ["Sodium","Potassium","Phosphorus","Calcium","Magnesium",
              "Protein","Carbs","Fat","Sat Fat","Mono Fat","Poly Fat",
              "Sugar","Iron","Calories"]
    for k in wanted:
        try:
            n[k] = float(n.get(k, 0.0) or 0.0)
        except Exception:
            n[k] = 0.0
    return n

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
