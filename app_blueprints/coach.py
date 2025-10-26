# app_blueprints/coach.py
from flask import Blueprint, render_template, request, session, redirect, url_for
import re, random
from fuzzywuzzy import fuzz

coach_bp = Blueprint("coach", __name__)

# Keep these local so the bp is self-contained
RESTAURANT_KEYWORDS = [
    "restaurant", "diner", "takeout", "fast food", "served", "grilled", "sauce", "entrée",
]

@coach_bp.route("/assistant", methods=["GET", "POST"], endpoint="assistant")
def assistant():
    if request.method == "POST":
        choice = request.form.get("choice")
        if choice == "usda":
            # index now lives in the search blueprint
            return redirect(url_for("search.index"))
        elif choice == "sodium":
            return redirect(url_for("coach.chat"))
    return render_template("assistant.html")


@coach_bp.route("/chat", methods=["GET", "POST"], endpoint="chat")
def chat():
    if "coach_stage" not in session:
        session["coach_stage"] = "ask_food"
        session["pending_food"] = None

    message = ""
    reply = ""
    grams = 0.0

    if request.method == "POST":
        message = (request.form.get("user_message") or "").strip()
        weight_input = (request.form.get("weight_in_grams") or "").strip()

        used_sodium = sum(log["totals"].get("Sodium", 0) for log in session.get("daily_logs", []))
        remaining_sodium = 1500 - used_sodium

        if message.lower() == "reset":
            session["coach_stage"] = "ask_food"
            session["pending_food"] = None
            return render_template("chat.html", reply="🔄 Reset. What did you eat?", user_message="")

        if session["coach_stage"] == "ask_food":
            best_match = None
            best_score = 0
            for food in session.get("my_food_list", []):
                food_name = food.get("description", "")
                score = fuzz.token_set_ratio(message.lower(), food_name.lower())
                if score > best_score:
                    best_score = score
                    best_match = food

            if best_match and best_score >= 80:
                session["pending_food"] = best_match
                session["coach_stage"] = "ask_quantity"
                reply = (
                    f"🧂 Got it: {best_match['description']}. "
                    "How much did you eat? (e.g., 2 crackers, 1 tomato, or enter weight below)"
                )
            else:
                reply = "🤔 I couldn’t find that food in your saved list. Try searching and adding it to your list first."

        elif session["coach_stage"] == "ask_quantity":
            best_match = session.get("pending_food")
            sodium_per_100g = (best_match or {}).get("nutrients", {}).get("Sodium", 0)

            if weight_input and weight_input.isdigit():
                grams = float(weight_input)
            elif message:
                PORTION_WEIGHTS = {
                    "cracker": 4.5,
                    "crackers": 4.5,
                    "slice of bread": 28,
                    "salmon steak": 180,
                    "tomato": 100,
                    "small tomato": 75,
                    "large tomato": 150,
                    "bowl of soup": 250,
                }
                for key, gw in PORTION_WEIGHTS.items():
                    m = re.search(rf"(\d+)?\s*{re.escape(key)}", message.lower())
                    if m:
                        qty = int(m.group(1)) if m.group(1) else 1
                        grams = qty * gw
                        break

            if grams > 0 and best_match:
                base_sodium = (sodium_per_100g * grams) / 100.0

                # Adjust for restaurant context
                user_input = message
                if any(word in (user_input or "").lower() for word in RESTAURANT_KEYWORDS):
                    sauce_sodium = random.randint(600, 1200)
                    total_sodium = base_sodium + sauce_sodium
                    note = f" (including ~{sauce_sodium} mg from sauce)"
                else:
                    sauce_sodium = 0
                    total_sodium = base_sodium
                    note = ""

                remaining = remaining_sodium - total_sodium
                reply = (
                    f"🍽️ {grams:.0f}g of {best_match['description']}\n"
                    f"Estimated sodium: {total_sodium:.0f} mg{note}\n"
                    f"Remaining today: {remaining:.0f} mg"
                )

                session["coach_stage"] = "ask_food"
                session["pending_food"] = None
                session.setdefault("daily_logs", [])
                session["daily_logs"].append(
                    {
                        "description": best_match["description"],
                        "grams": grams,
                        "sauce_estimate": sauce_sodium,
                        "totals": {
                            nutrient: (value * grams / 100.0)
                            for nutrient, value in best_match.get("nutrients", {}).items()
                        },
                    }
                )
                session.modified = True
            else:
                reply = "🤔 I couldn't understand that amount. Try entering a number of crackers or an estimated gram weight."

    return render_template("chat.html", reply=reply, user_message=message)
