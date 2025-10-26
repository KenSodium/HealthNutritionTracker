# nutrition/services/food_portion_ref.py
import csv

def _load_measure_units(path="data/measure_unit.csv"):
    mu_name = {}
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            r = csv.DictReader(fh)
            for rec in r:
                try:
                    mu_name[int(rec.get("id", 0))] = rec.get("name", "")
                except:
                    pass
    except FileNotFoundError:
        pass
    return mu_name

def _load_food_meta(path="data/food.csv"):
    food_meta = {}
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            r = csv.DictReader(fh)
            for rec in r:
                try:
                    fid = int(rec.get("fdc_id", 0))
                except:
                    continue
                food_meta[fid] = {
                    "description": rec.get("description", ""),
                    "data_type": rec.get("data_type", ""),
                    "brand_owner": rec.get("brand_owner", ""),
                    "food_category": rec.get("food_category", ""),
                }
    except FileNotFoundError:
        pass
    return food_meta

def build_food_portion_rows(fdc_filter: set[int] | None = None,
                            path="data/food_portion.csv"):
    mu_name = _load_measure_units()
    food_meta = _load_food_meta()
    rows = []
    cols = [
        "fdc_id", "description", "data_type", "brand_owner", "food_category",
        "portion_description", "measure_unit", "amount", "gram_weight", "modifier"
    ]
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            r = csv.DictReader(fh)
            for rec in r:
                try:
                    fid = int(rec.get("fdc_id", 0))
                except:
                    continue
                if fdc_filter and fid not in fdc_filter:
                    continue
                mu = ""
                mu_id = rec.get("measure_unit_id")
                if mu_id:
                    try:
                        mu = mu_name.get(int(mu_id), "")
                    except:
                        mu = ""
                meta = food_meta.get(fid, {})
                rows.append({
                    "fdc_id": fid,
                    "description": meta.get("description", ""),
                    "data_type": meta.get("data_type", ""),
                    "brand_owner": meta.get("brand_owner", ""),
                    "food_category": meta.get("food_category", ""),
                    "portion_description": rec.get("portion_description", ""),
                    "measure_unit": mu,
                    "amount": rec.get("amount", ""),
                    "gram_weight": rec.get("gram_weight", ""),
                    "modifier": rec.get("modifier", ""),
                })
    except FileNotFoundError:
        pass
    return rows, cols
