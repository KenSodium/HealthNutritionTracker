# nutrition/services/portions.py
import csv
from functools import lru_cache
from typing import List, Dict
from nutrition.services.usda_client import get_food_detail, search_top_for_recipes
from nutrition.services.units import grams_from_local_registry  # optional if you want last-resort
# If you need typical weights etc., import from units as well.

def recipe_portions(detail: dict) -> List[Dict]:
    """
    Simplify USDA foodPortions to: {id,label,gramWeight,unit,amount}
    """
    out = []
    for i, p in enumerate(detail.get("foodPortions") or []):
        gw = p.get("gramWeight")
        if not isinstance(gw, (int, float)):
            continue
        mu = (p.get("measureUnit") or {}).get("name") or ""  # 'cup', 'tablespoon', ...
        mod = (p.get("modifier") or "")
        amt = p.get("amount")
        label = (f"{amt} {mu}".strip() if amt and mu else (mu or "portion"))
        if mod: label += f" ({mod})"
        out.append({
            "id": str(i),
            "label": label,
            "gramWeight": float(gw),
            "unit": mu.lower(),
            "amount": float(amt) if isinstance(amt, (int, float)) else None,
        })
    return out

def derive_common_volumes_simple(portions: List[Dict]) -> List[Dict]:
    out = list(portions)
    tbsp = next((p for p in portions if p.get("unit") in ("tablespoon", "tbsp")), None)
    tsp  = next((p for p in portions if p.get("unit") in ("teaspoon", "tsp")), None)
    def clone(new_unit: str, grams: float, note: str):
        return {
            "id": f"der-{new_unit}-{len(out)}",
            "label": f"1 {new_unit} ({note})",
            "gramWeight": grams,
            "unit": new_unit,
            "amount": 1.0,
        }
    if tbsp:
        gw = float(tbsp["gramWeight"])
        out.append(clone("tsp", gw / 3.0, "derived"))
        out.append(clone("cup", gw * 16.0, "derived"))
    if tsp and not tbsp:
        gw = float(tsp["gramWeight"])
        out.append(clone("tbsp", gw * 3.0, "derived"))
    return out

def portion_match_from_labels(portions: List[Dict], user_unit: str):
    if not user_unit or not portions: return None
    u = user_unit.strip().lower()
    UNIT_SYNONYMS = {
        "clove": ["clove", "cloves"],
        "cup": ["cup", "cups"],
        "tbsp": ["tbsp", "tablespoon", "tablespoons"],
        "tsp": ["tsp", "teaspoon", "teaspoons"],
        "pound": ["lb", "lbs", "pound", "pounds"],
        "ounce": ["oz", "ounce", "ounces"],
        "whole": ["whole", "each", "piece"],
        "undetermined": ["undetermined"]
    }
    cands = set([u])
    for canon, syns in UNIT_SYNONYMS.items():
        if u == canon or u in syns:
            cands.add(canon); cands.update(syns)
    for p in portions:
        if p.get("unit") in cands:
            return p
    for p in portions:
        lab = (p.get("label") or "").lower()
        if any(c in lab for c in cands):
            return p
    return None

def find_alt_portions_for_name(name: str):
    """
    Try searching alternates to find another FDC record that has portions.
    Only returns derived common volumes (so you can match cups/tsp quickly).
    """
    def _search_and_take(query: str):
        hits = search_top_for_recipes(query, limit=20)
        for h in hits:
            det = get_food_detail(str(h.get("fdcId")))
            if not det: continue
            parts = recipe_portions(det)
            if parts:
                return derive_common_volumes_simple(parts)
        return []
    parts = _search_and_take(name)
    if parts: return parts

    nm = (name or "").lower()
    variants = []
    if "tomato, roma" in nm: variants.append("roma tomato")
    if "roma tomato" in nm: variants.append("tomato, roma")

    for v in variants:
        parts = _search_and_take(v)
        if parts: return parts
    return []

# ------- WIFtEE fallback portions (local CSV) -------
@lru_cache(maxsize=1)
def _load_wiftee_portions():
    rows = []
    try:
        with open("data/wiftee_portions.csv", newline="", encoding="utf-8") as fh:
            r = csv.DictReader(fh)
            for rec in r:
                try:
                    gw = float(rec.get("gram_weight", 0) or 0)
                except:
                    gw = 0.0
                if gw <= 0: continue
                rows.append({
                    "food_description": (rec.get("food_description") or "").strip(),
                    "measure_description": (rec.get("measure_description") or "").strip(),
                    "number_of_servings": str(rec.get("number_of_servings", "") or "").strip(),
                    "gram_weight": gw,
                })
    except FileNotFoundError:
        pass
    return rows

def _norm_txt(s: str) -> str:
    return (s or "").lower().replace(",", " ").replace("  ", " ").strip()

def find_wiftee_portions_for_name(name: str, max_hits: int = 6):
    if not name: return []
    target = _norm_txt(name)
    rows = _load_wiftee_portions()
    if not rows: return []
    starts = [r for r in rows if _norm_txt(r["food_description"]).startswith(target)]
    contains = [r for r in rows if target in _norm_txt(r["food_description"])]
    hits = (starts or contains)[:max_hits]
    out = []
    for i, r in enumerate(hits):
        label = r["measure_description"]
        nserv = r["number_of_servings"]
        if nserv and nserv != "1":
            label = f"{nserv} × {label}"
        out.append({
            "id": f"w{i}",
            "label": label,
            "gramWeight": float(r["gram_weight"]),
            "unit": label.lower(),
        })
    return out

# ------- User-facing helpers used by /daily -------
from functools import lru_cache as _lru

@_lru(maxsize=4096)
def get_portions_for_fdc(fdc_id: str, description: str = "") -> list[dict]:
    parts = []
    if fdc_id and str(fdc_id).isdigit():
        det = get_food_detail(str(fdc_id))
        if det:
            parts = recipe_portions(det)
    if not parts and description:
        parts = find_alt_portions_for_name(description) or []
    if not parts and description:
        parts = find_wiftee_portions_for_name(description) or []
    if parts:
        parts = derive_common_volumes_simple(parts)
    # normalize
    out = []
    for i, p in enumerate(parts or []):
        gw = p.get("gramWeight")
        if isinstance(gw, (int, float)) and gw > 0:
            out.append({
                "id": p.get("id", f"p{i}"),
                "label": p.get("label") or (p.get("unit") or "portion"),
                "unit": (p.get("unit") or "").lower(),
                "gramWeight": float(gw),
            })
    return out

def build_hint_from_portions(portions: list[dict]) -> str:
    units = { (p.get("unit") or "").lower() for p in portions }
    for u, msg in [
        ("cracker", "enter grams or number of crackers"),
        ("slice",   "enter grams or number of slices"),
        ("cup",     "enter grams or number of cups"),
        ("tbsp",    "enter grams or number of tablespoons"),
        ("tsp",     "enter grams or number of teaspoons"),
        ("whole",   "enter grams or number of whole pieces"),
    ]:
        if u in units: return msg
    return "enter grams or units"
