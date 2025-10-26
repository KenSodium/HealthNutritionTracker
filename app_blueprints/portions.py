# app_blueprints/portions.py
from flask import Blueprint, render_template, session, request
from nutrition.services.food_portion_ref import build_food_portion_rows

portions_bp = Blueprint("portions", __name__)

@portions_bp.route("/foodportions", endpoint="food_portions")
def food_portions():
    """
    Shows the Food Portion Reference table. Keeps the SAME URL (/foodportions)
    so you don’t need to change links unless you want to update endpoints.
    """
    show_all = request.args.get("all") == "1"
    fdc_filter = set()
    if not show_all:
        for f in session.get("my_food_list", []):
            fid = str(f.get("fdcId", ""))
            if fid.isdigit():
                fdc_filter.add(int(fid))
    rows, cols = build_food_portion_rows(fdc_filter if fdc_filter else None)
    return render_template("food_portions.html", data=rows, columns=cols)
