# nutrition/services/units.py
import json, os, re
from functools import lru_cache

CONV_PATH = os.path.join("data", "unit_conversions.json")

UNIT_SYNONYMS = {
    "clove": ["clove", "cloves"],
    "cup": ["cup", "cups"],
    "tbsp": ["tbsp", "tablespoon", "tablespoons"],
    "tsp": ["tsp", "teaspoon", "teaspoons"],
    "pound": ["lb", "lbs", "pound", "pounds"],
    "ounce": ["oz", "ounce", "ounces"],
    "whole": ["whole", "each", "piece"],
}

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def load_unit_conv():
    if os.path.exists(CONV_PATH):
        try:
            with open(CONV_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"defaults": {}, "items": []}

UNIT_CONV = load_unit_conv()

def grams_from_local_registry(name: str, unit: str, qty: float) -> float:
    n = _norm(name)
    u = _norm(unit).rstrip("s")

    # 1) ingredient-specific regex matches
    for item in UNIT_CONV.get("items", []):
        pat = item.get("pattern")
        if pat and re.search(pat, n):
            g = (item.get("units") or {}).get(u)
            if isinstance(g, (int, float)):
                return float(g) * float(qty)

    # 2) generic defaults, optionally water-like fallback
    dv = UNIT_CONV.get("defaults", {}).get(u)
    if isinstance(dv, (int, float)):
        return float(dv) * float(qty)
    if isinstance(dv, dict):
        base = dv.get("water_like") or next(iter(dv.values()), None)
        if base:
            return float(base) * float(qty)

    return 0.0

FALLBACK_TYPICAL_WEIGHTS = [
    (r"\bgarlic\b", {"clove": 3.0, "whole": 3.0, "tbsp": 8.5, "tsp": 2.8}),
    (r"\btomato,\s*roma\b", {"whole": 62.0, "cup": 180.0}),
    (r"\broma\s+tomato\b", {"whole": 62.0, "cup": 180.0}),
    (r"\btomato\b", {"whole": 123.0, "cup": 180.0}),
    (r"\bonion\b", {"whole": 110.0, "cup": 160.0}),
    (r"\bpepperoncini\b", {"whole": 10.0}),
    (r"\bchicken\s+thigh\b", {"whole": 80.0}),
]

def typical_grams_for_unit(name: str, unit: str):
    n = _norm(name)
    u = _norm(unit).rstrip('s')
    for pat, umap in FALLBACK_TYPICAL_WEIGHTS:
        if re.search(pat, n) and u in umap:
            return umap[u]
    return None

def parse_line_to_qty_unit_name(line: str):
    """
    '4 garlic cloves' -> (4.0, 'clove', 'garlic')
    '1 cup chicken stock' -> (1.0, 'cup', 'chicken stock')
    '1 onion' -> (1.0, 'whole', 'onion')
    """
    s = (line or "").strip().lower().replace("–", "-")
    if not s: return (None, None, None)
    s = re.sub(r"\s*,\s*", " ", s)
    m = re.match(r"^(\d+(?:\.\d+)?|\d+\s*/\s*\d+)\s+(.*)$", s)
    if not m: return (None, None, s)
    q_raw, rest = m.groups()
    if "/" in q_raw:
        a, b = q_raw.split("/")
        qty = float(a) / float(b)
    else:
        qty = float(q_raw)

    tokens = rest.split()
    if not tokens: return (qty, None, None)

    syn2canon = {syn: canon for canon, syns in UNIT_SYNONYMS.items() for syn in syns}
    first = tokens[0]
    unit = syn2canon.get(first)
    if unit:
        name = " ".join(tokens[1:]).strip()
    else:
        unit = "whole"
        name = " ".join(tokens).strip()
    return (qty, unit, name)
# nutrition/services/units.py
import re
from typing import Tuple, Optional
from nutrition.services.portions import portion_match_from_labels
# If grams_from_local_registry is in this same file already, you don't need to import it.

def _parse_fraction_or_float(s: str) -> Optional[float]:
    s = (s or "").strip()
    if not s:
        return None
    if "/" in s:
        try:
            a, b = s.split("/", 1)
            return float(a) / float(b)
        except Exception:
            return None
    try:
        return float(s)
    except Exception:
        return None

def parse_qty_text(text: str):
    """
    Returns a dict describing the intent:
      {"kind":"grams","value":120.0}
      {"kind":"default_units","qty":2.0}
      {"kind":"units","qty":2.0,"unit":"cracker"}
    """
    s = (text or "").strip().lower()
    if not s:
        return None

    # 120g / 120 gram(s)
    m = re.match(r'^(\d+(?:\.\d+)?|\d+\s*/\s*\d+)\s*(g|gram|grams)$', s)
    if m:
        val = _parse_fraction_or_float(m.group(1))
        return {"kind": "grams", "value": val}

    # only slashes/x (//, x3, ////, 3x)
    if re.fullmatch(r'[\/x\s]+', s):
        n = s.count('/') + s.count('x')
        return {"kind": "default_units", "qty": float(n)}

    m = re.match(r'^(?:x\s*)?(\d+(?:\.\d+)?)\s*(?:x)?$', s)  # 2x or x2 or 2
    if m:
        return {"kind": "default_units", "qty": float(m.group(1))}

    # 1/2 cup onion, 2 crackers, 3 tbsp, etc.
    m = re.match(r'^(\d+(?:\.\d+)?|\d+\s*/\s*\d+)\s+(.+)$', s)
    if m:
        qty = _parse_fraction_or_float(m.group(1)) or 0.0
        unit = m.group(2).strip()
        return {"kind": "units", "qty": qty, "unit": unit}

    # pure number → default units
    if re.match(r'^\d+(?:\.\d+)?$', s):
        return {"kind":"default_units","qty": float(s)}

    # unit word only → assume 1 of that unit
    return {"kind":"units","qty": 1.0, "unit": s}

def pick_default_unit(portions: list) -> str:
    """
    Decide a sensible default unit for the food, based on available portions.
    """
    priority = ["cracker", "slice", "cup", "tbsp", "tsp", "whole", "piece", "each"]
    units = [(p.get("unit") or "").lower() for p in (portions or []) if p.get("unit")]
    for u in priority:
        if u in units:
            return u
    return units[0] if units else "whole"

def grams_from_qty_text(desc: str, qty_text: str, portions: list, grams_from_local_registry_fn=None) -> Tuple[float, Optional[str], Optional[float]]:
    """
    Compute grams from a free-text quantity.
    Returns (grams, used_unit, used_qty).
    used_unit == 'g' for direct grams entry; for default, returns the chosen default unit.
    """
    parsed = parse_qty_text(qty_text)
    if not parsed:
        return 0.0, None, None

    # 1) Direct grams
    if parsed["kind"] == "grams":
        g = float(parsed.get("value") or 0.0)
        return g, "g", g

    # 2) Default-unit shorthand (//, 2x, 2, etc.)
    if parsed["kind"] == "default_units":
        default_u = pick_default_unit(portions)
        p = portion_match_from_labels(portions, default_u)
        if p and isinstance(p.get("gramWeight"), (int, float)):
            g = float(p["gramWeight"]) * float(parsed["qty"])
            return g, default_u, float(parsed["qty"])
        # fallback to your local registry if provided
        if grams_from_local_registry_fn:
            g = grams_from_local_registry_fn(desc, default_u, float(parsed["qty"]))
            return g, default_u, float(parsed["qty"])
        return 0.0, default_u, float(parsed["qty"])

    # 3) Explicit unit (e.g., "2 crackers", "1/2 cup")
    if parsed["kind"] == "units":
        unit = parsed.get("unit") or ""
        qty  = float(parsed.get("qty") or 0.0)
        if qty <= 0:
            return 0.0, unit, qty
        p = portion_match_from_labels(portions, unit)
        if p and isinstance(p.get("gramWeight"), (int, float)):
            g = float(p["gramWeight"]) * qty
            return g, unit, qty
        if grams_from_local_registry_fn:
            g = grams_from_local_registry_fn(desc, unit, qty)
            return g, unit, qty
        return 0.0, unit, qty

    return 0.0, None, None
