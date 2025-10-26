# nutrition/services/usda_client.py
import os
import requests
from functools import lru_cache
from typing import Any, Dict, List, Optional

API_KEY = os.environ.get("USDA_API_KEY") or "nNHvl3jpsKmbZH7JeFzpPWPCJDivxatmbaEZ5B6n"
BASE = "https://api.nal.usda.gov/fdc/v1"

DEFAULT_TIMEOUT = (3.1, 10)  # (connect, read) seconds

def _get(url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        if r.ok:
            return r.json()
    except requests.RequestException:
        pass
    return None

def search_foods(query: str, page_size: int = 25, page_number: int = 1, data_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    params = {
        "api_key": API_KEY,
        "query": query,
        "pageSize": page_size,
        "pageNumber": page_number,
    }
    if data_types:
        params["dataType"] = data_types
    data = _get(f"{BASE}/foods/search", params) or {}
    return data.get("foods", [])

@lru_cache(maxsize=2048)
def get_food_detail(fdc_id: str) -> Dict[str, Any]:
    params = {"api_key": API_KEY}
    data = _get(f"{BASE}/food/{fdc_id}", params) or {}
    return data

def search_top_for_recipes(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """A thin wrapper used by the recipe picker (ordered by preferred types)."""
    foods = search_foods(query, page_size=limit)
    preferred = ["Foundation", "SR Legacy", "Survey (FNDDS)", "Branded"]
    ordered: List[Dict[str, Any]] = []
    for dt in preferred:
        ordered.extend([f for f in foods if f.get("dataType") == dt])
    leftovers = [f for f in foods if f not in ordered]
    return (ordered + leftovers)[:limit]

def search_best_fdc_for_recipes(query: str) -> Optional[str]:
    foods = search_foods(query, page_size=50)
    if not foods:
        return None
    preferred = ["Foundation", "SR Legacy", "Survey (FNDDS)", "Branded"]
    for dt in preferred:
        for f in foods:
            if f.get("dataType") == dt:
                return str(f.get("fdcId"))
    return str(foods[0].get("fdcId"))
