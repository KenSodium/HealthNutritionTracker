# app_blueprints/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, session

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"], endpoint="login")
def login():
    if request.method == "POST":
        mode = request.form.get("mode")  # "demo" or "form"
        if mode == "demo":
            session["user"] = {"name": "Demo User", "email": "demo@example.com", "plan": "premium"}
        else:
            name  = (request.form.get("name")  or "Demo User").strip()
            email = (request.form.get("email") or "demo@example.com").strip()
            plan  = (request.form.get("plan")  or "free").strip()
            session["user"] = {"name": name, "email": email, "plan": plan}

        # Be robust to either blueprint or legacy daily endpoint
        nxt = request.args.get("next")
        if not nxt:
            try:
                nxt = url_for("daily.daily")  # blueprint
            except Exception:
                nxt = url_for("daily")        # legacy
        return redirect(nxt)
    return render_template("marketing/login.html")

@auth_bp.route("/signup", methods=["GET", "POST"], endpoint="signup")
def signup():
    if request.method == "POST":
        name  = (request.form.get("name")  or "Demo User").strip()
        email = (request.form.get("email") or "demo@example.com").strip()
        plan  = (request.form.get("plan")  or "premium").strip()
        session["user"] = {"name": name, "email": email, "plan": plan}

        try:
            nxt = request.args.get("next") or url_for("daily.daily")
        except Exception:
            nxt = request.args.get("next") or url_for("daily")
        return redirect(nxt)
    return render_template("marketing/signup.html")

@auth_bp.route("/logout", endpoint="logout")
def logout():
    session.pop("user", None)
    # go home after logout
    try:
        return redirect(url_for("home"))
    except Exception:
        return redirect("/")  # last-resort fallback
