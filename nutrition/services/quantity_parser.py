# nutrition/services/quantity_parser.py
from __future__ import annotations
import re
from nutrition.services.portions import portion_match_from_labels, find_alt_portions_for_name
from nutrition.services.units import grams_from_local_registry

# Simple default grams-per-unit for previewing a "1 unit" portion
GRAMS_PER_UNIT_DEFAULT = {
    "g": 100.0,   # preview 100 g for the "g" option
    "cup": 240.0,
    "tbsp": 15.0,
    "tsp": 5.0,
    "clove": 3.0,
}

# Fallback typical weights: approximate grams per ONE unit for common foods/units
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
    """Return grams for a single 'unit' based on the food 'name' using the fallback table."""
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    u = (unit or "").strip().lower().rstrip("s")
    for pat, umap in FALLBACK_TYPICAL_WEIGHTS:
        if re.search(pat, n):
            g = umap.get(u)
            if isinstance(g, (int, float)):
                return float(g)
    return None

def guess_grams_from_unit(name: str, unit: str, qty: float, portions: list) -> float:
    """
    Try (1) current item portions; (2) typical weights table; (3) alternate portions; (4) generic volumes.
    """
    # 1) try current simplified portions
    if portions:
        p = portion_match_from_labels(portions, unit)
        if p and isinstance(p.get("gramWeight"), (int, float)):
            return float(p["gramWeight"]) * float(qty)

    # 2) typical weights
    tw = typical_grams_for_unit(name, unit)
    if isinstance(tw, (int, float)):
        return float(tw) * float(qty)

    # 3) alternates (same food name, different FDC that has portions)
    alt = find_alt_portions_for_name(name)
    if alt:
        p2 = portion_match_from_labels(alt, unit)
        if p2 and isinstance(p2.get("gramWeight"), (int, float)):
            return float(p2["gramWeight"]) * float(qty)

    # 4) generic volume approximations
    GENERIC_VOL = {"cup": 240.0, "tbsp": 15.0, "tsp": 5.0}
    u = (unit or "").strip().lower()
    if u in GENERIC_VOL:
        return GENERIC_VOL[u] * float(qty)

    return 0.0

def pick_default_unit(portions) -> str | None:
    """
    Choose the most human unit if available.
    Safe if portions is None, a string, or any non-list.
    """
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

def grams_from_qty_text(
    name: str,
    text: str,
    portions: list,
    grams_from_local_registry_fn=grams_from_local_registry,
):
    """
    Accepts: "100g", "200 g", "2 cup", "1.5 tbsp", "3 tsp", "1 clove",
             "1 cracker", "2 oz", "1 lb", "2", "//", "2//"
    Returns: (grams: float, used_unit: str, used_qty: float)
    """
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

    # 1) grams explicitly
    m = re.match(r"^(\d+(?:\.\d+)?)\s*g$", s)
    if m:
        g = float(m.group(1))
        return g, "g", g

    # 2) pure number => default unit
    m = re.match(r"^(\d+(?:\.\d+)?)$", s)
    if m:
        qty = float(m.group(1))
        unit = pick_default_unit(portions) or "whole"
        grams = guess_grams_from_unit(name, unit, qty, portions)
        if grams <= 0:
            grams = grams_from_local_registry_fn(name, unit, qty)
        return grams, unit, qty

    # 3) only slashes => count as default units
    if set(s) == {"/"}:
        qty = float(len(s))
        unit = pick_default_unit(portions) or "whole"
        grams = guess_grams_from_unit(name, unit, qty, portions)
        if grams <= 0:
            grams = grams_from_local_registry_fn(name, unit, qty)
        return grams, unit, qty

    # 4) "<num>//" => number of default units
    m = re.match(r"^(\d+(?:\.\d+)?)\s*/+$", s)
    if m:
        qty = float(m.group(1))
        unit = pick_default_unit(portions) or "whole"
        grams = guess_grams_from_unit(name, unit, qty, portions)
        if grams <= 0:
            grams = grams_from_local_registry_fn(name, unit, qty)
        return grams, unit, qty

    # 5) "<num> <unit>"
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

    # unrecognized
    return 0.0, "", 0.0
