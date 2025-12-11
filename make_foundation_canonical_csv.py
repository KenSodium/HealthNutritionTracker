import os
import pandas as pd
import traceback
import numpy as np

# ---------------------------------------------------------
# CONFIG: USDA CSV directory and output files
# ---------------------------------------------------------
BASE_DIR = r"C:\Users\krieg\Documents\USDA Full Download All Data\FoodData_Central_csv_2025-04-24"
OUTPUT_CSV = os.path.join(BASE_DIR, "foundation_canonical.csv")
ERROR_LOG_FILE = "error_log.txt"

def csv_path(name: str) -> str:
    return os.path.join(BASE_DIR, name)

def main():
    print("Loading USDA CSV files...")

    food = pd.read_csv(csv_path("food.csv"))
    food_nutrient = pd.read_csv(csv_path("food_nutrient.csv"))
    nutrient = pd.read_csv(csv_path("nutrient.csv"))
    food_category = pd.read_csv(csv_path("food_category.csv"))
    foundation_food = pd.read_csv(csv_path("foundation_food.csv"))

    print(f"  food rows:            {len(food):,}")
    print(f"  food_nutrient rows:   {len(food_nutrient):,}")
    print(f"  nutrient rows:        {len(nutrient):,}")
    print(f"  food_category rows:   {len(food_category):,}")
    print(f"  foundation_food rows: {len(foundation_food):,}")

    # Optional tables
    try:
        food_portion = pd.read_csv(csv_path("food_portion.csv"))
        print(f"  food_portion rows:    {len(food_portion):,}")
    except FileNotFoundError:
        print("  WARNING: food_portion.csv not found. Portion data will be missing.")
        food_portion = None

    try:
        measure_unit = pd.read_csv(csv_path("measure_unit.csv"))
        print(f"  measure_unit rows:    {len(measure_unit):,}")
    except FileNotFoundError:
        print("  WARNING: measure_unit.csv not found. Portion units will be missing.")
        measure_unit = None

    # ---------------------------------------------------------
    # 1. Foundation set = all fdc_id present in foundation_food.csv
    # ---------------------------------------------------------
    foundation_ids = foundation_food["fdc_id"].unique()
    print(f"\nUnique Foundation fdc_id: {len(foundation_ids):,}")

    foundation_small = (
        food[food["fdc_id"].isin(foundation_ids)]
        [["fdc_id", "description", "food_category_id"]]
        .copy()
    )
    foundation_small["food_category_id"] = foundation_small["food_category_id"].astype("Int64")

    # ---------------------------------------------------------
    # 2. Nutrients we care about, mapped to your canonical names
    # ---------------------------------------------------------
    nutrient_map = {
        "Sodium, Na": "Sodium (mg)",
        "Potassium, K": "Potassium (mg)",
        "Protein": "Protein (g)",
        "Energy": "Calories",
        "Cholesterol": "Cholesterol (mg)",
        "Carbohydrate, by difference": "Carbs (g)",
        "Total lipid (fat)": "Fat (g)",
        "Fatty acids, total saturated": "Sat Fat (g)",
        "Fatty acids, total monounsaturated": "Mono Fat (g)",
        "Fatty acids, total polyunsaturated": "Poly Fat (g)",
        "Sugars, total including NLEA": "Sugar (g)",
        "Sugars, total": "Sugar (g)",
        "Calcium, Ca": "Calcium (mg)",
        "Magnesium, Mg": "Magnesium (mg)",
        "Iron, Fe": "Iron (mg)",
    }
    wanted_names = list(nutrient_map.keys())
    nut_sel = nutrient[nutrient["name"].isin(wanted_names)][["id", "name"]].rename(columns={"id": "nutrient_id"})

    # ---------------------------------------------------------
    # 3. Create wide table for nutrients
    # ---------------------------------------------------------
    fn = food_nutrient.merge(nut_sel, on="nutrient_id", how="inner")
    fn = fn[fn["fdc_id"].isin(foundation_ids)]
    fn = fn.merge(foundation_small, on="fdc_id", how="left")

    index_cols = ["fdc_id", "description"]
    wide = fn.pivot_table(index=index_cols, columns="name", values="amount", aggfunc="first").reset_index()
    wide.columns.name = None

    rename_dict = {orig: new for orig, new in nutrient_map.items() if orig in wide.columns}
    wide = wide.rename(columns=rename_dict)

    print(f"\nWide nutrient table shape: {wide.shape}")

    # ---------------------------------------------------------
    # 4. Get a single default portion for each food
    # ---------------------------------------------------------
    default_portions = None
    if food_portion is not None:
        print("\nProcessing default portions...")
        fp = food_portion[food_portion["fdc_id"].isin(foundation_ids)].copy()

        sort_by = ["fdc_id"]
        sort_ascending = [True]
        if "is_default" in fp.columns:
            sort_by.append("is_default")
            sort_ascending.append(False)
        if "seq_num" in fp.columns:
            sort_by.append("seq_num")
            sort_ascending.append(True)
        
        if len(sort_by) > 1:
            fp = fp.sort_values(by=sort_by, ascending=sort_ascending)

        default_portions = fp.drop_duplicates("fdc_id", keep="first").copy()

        if measure_unit is not None and "measure_unit_id" in default_portions.columns:
            mu = measure_unit.rename(columns={"id": "measure_unit_id", "name": "Unit Type"})
            default_portions = default_portions.merge(mu, on="measure_unit_id", how="left")

        default_portions = default_portions.rename(columns={
            "gram_weight": "Serving Size",
            "portion_description": "Serving Unit",
            "amount": "Label Units"
        })
        
        keep_cols = ["fdc_id", "Serving Size", "Serving Unit", "Label Units", "Unit Type"]
        final_portion_cols = [col for col in keep_cols if col in default_portions.columns]
        default_portions = default_portions[final_portion_cols]
        
        print(f"  Found {len(default_portions)} default portions.")
    else:
        print("\nSkipping portion processing.")

    # ---------------------------------------------------------
    # 5. Merge nutrients and portions, finalize columns
    # ---------------------------------------------------------
    print("\nMerging nutrients and portions...")
    if default_portions is not None:
        merged = wide.merge(default_portions, on="fdc_id", how="left")
    else:
        merged = wide.copy()

    merged = merged.rename(columns={"description": "Food"})

    print("Applying default values and redefining 'Serving Unit'...")
    merged["Serving Size"].fillna(100, inplace=True)
    
    # Redefine 'Serving Unit' based on 'Serving Size'
    merged["Serving Unit"] = np.where(merged["Serving Size"] == 100, "Standard Weight", "Defined Portion")

    merged["Label Units"].fillna(100, inplace=True)
    merged["Unit Type"].fillna("gram", inplace=True)

    # Define final column order
    final_cols_ordered = [
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

    for col in final_cols_ordered:
        if col not in merged.columns:
            merged[col] = pd.NA

    final_df = merged[final_cols_ordered].copy()
    final_df = final_df.sort_values("Food", ignore_index=True)

    # ---------------------------------------------------------
    # 6. Write the single, combined CSV
    # ---------------------------------------------------------
    print(f"\nWriting combined CSV to: {OUTPUT_CSV}")
    final_df.to_csv(OUTPUT_CSV, index=False)
    print(f"  Rows in final file: {len(final_df):,}")
    print("Done.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"An error occurred: {e}")
        print(f"Writing error details to {ERROR_LOG_FILE}")
        with open(ERROR_LOG_FILE, "w") as f:
            f.write(f"Error: {e}\n\n")
            f.write("Traceback:\n")
            traceback.print_exc(file=f)
        raise
