# nutrition/utils.py
import datetime
from flask import session

def today_str():
    return datetime.date.today().isoformat()

def get_targets():
    # Defaults – later make user-configurable
    session.setdefault("targets", {"na": 1500, "k": 3400})
    return session["targets"]

def get_diary(date=None):
    date = date or today_str()
    diary = session.setdefault("diary", {})  # {date: [entries]}
    diary.setdefault(date, [])
    return diary[date]

def calc_progress(value: float, target: float):
    """Return (percent, bootstrap_class) with traffic-light bands."""
    if target <= 0:
        pct = 0
    else:
        pct = min(100, round((value / target) * 100))
    if pct < 80:
        cls = "bg-success"
    elif pct <= 100:
        cls = "bg-warning text-dark"
    else:
        cls = "bg-danger"
    return pct, cls

def sum_nutrients(entries):
    totals = {}
    for e in entries:
        for k, v in (e.get("nutrients") or {}).items():
            totals[k] = totals.get(k, 0.0) + float(v or 0)
    return totals
