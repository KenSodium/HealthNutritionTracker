# app_blueprints/marketing.py
from flask import Blueprint, render_template, request, redirect, url_for

marketing_bp = Blueprint("marketing", __name__)

@marketing_bp.route("/", endpoint="home")
def home():
    return render_template("landing.html")

@marketing_bp.route("/sample-report", endpoint="sample_report")
def sample_report():
    return render_template("marketing/clinician_report_sample.html")

@marketing_bp.route("/assistant", methods=["GET", "POST"], endpoint="assistant")
def assistant():
    if request.method == "POST":
        choice = request.form.get("choice")
        if choice == "usda":
            # Prefer blueprint endpoint, fallback to legacy
            try:
                return redirect(url_for("search.index"))
            except Exception:
                return redirect(url_for("index"))
        elif choice == "sodium":
            try:
                return redirect(url_for("coach.chat"))
            except Exception:
                return redirect(url_for("chat"))
    return render_template("assistant.html")
