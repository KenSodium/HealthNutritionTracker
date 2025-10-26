# nutrition/services/preview.py
from __future__ import annotations
from nutrition.services.nutrients import normalize_per100
from nutrition.services.quantity_parser import GRAMS_PER_UNIT_DEFAULT

def compute_portion_preview(item: dict) -> None:
    """
    For one my_food_list item: compute item['computed']['portion_grams'] and
    item['computed']['portion_nutrients'] based on chosen unit + grams.
    """
    if not isinstance(item, dict):
        return

    per100 = normalize_per100(item.get("nutrients", {}))
    item["nutrients"] = per100  # keep normalized

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
