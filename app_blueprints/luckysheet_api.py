# app_blueprints/luckysheet_api.py
from flask import Blueprint, current_app, jsonify, request, session, make_response
import os, json

bp = Blueprint("luckysheet_api", __name__, url_prefix="/api")

# --- Constants ---------------------------------------------------------------

# Enforce: freeze top 3 rows (0,1,2) and 1 left column (A)
# How many rows/columns you want frozen:
FROZEN = {"type": "both", "range": [3, 1]}  # top 3 rows, 1 left column

def _enforce_frozen_on_sheet(sheet: dict) -> None:
    """
    Make sure a Luckysheet `sheet` has the freeze state set in BOTH
    the `frozen` key and in `config.freezen`, which is what the UI uses.
    """
    if not isinstance(sheet, dict):
        return

    # Top-level `frozen` (some Luckysheet code paths still look here)
    sheet["frozen"] = dict(FROZEN)

    # config.freezen is what the drag-bar and UI logic use
    cfg = sheet.setdefault("config", {})
    cfg["freezen"] = dict(FROZEN)


# Row 2 labels (HEAD2) that the rest of the app expects
HEAD2 = [
    "Food",
    # Serving block (4 cols)
    "Serving Size",      # numeric value from USDA branded 'servingSize'
    "Serving Unit",      # USDA 'servingSizeUnit' (e.g., g, ml, piece)
    "Label Units",       # numeric part from householdLabel (e.g., 0.25 from '1/4 cup')
    "Unit Type",         # text part from householdLabel (e.g., 'cup')
    # Nutrients (13 cols)
    "Sodium (mg)", "Potassium (mg)", "Protein (g)", "Carbs (g)", "Fat (g)",
    "Sat Fat (g)", "Mono Fat (g)", "Poly Fat (g)", "Sugar (g)",
    "Calcium (mg)", "Magnesium (mg)", "Iron (mg)", "Calories",
]

# Merged header regions for row 0
MERGES = {
    "0_0": {"r": 0, "c": 0, "rs": 2, "cs": 1},   # "Food" spans rows 0..1, col 0
    "0_1": {"r": 0, "c": 1, "rs": 1, "cs": 3},   # "Serving Size" block spans row 0, cols 1..3
    "0_4": {"r": 0, "c": 4, "rs": 1, "cs": 13},  # "Nutrients" spans row 0, cols 4..16
}

# Column widths (18 columns total)
COL_WIDTHS = [
    240,  # Food
    110,  # Serving Size
    120,  # Serving Unit
    120,  # Label Units
    200,  # Unit Type (household label text)
    120, 130, 110, 110, 100, 120, 120, 120, 110, 120, 130, 110, 110  # nutrients
]
COLUMNLEN = {i: w for i, w in enumerate(COL_WIDTHS)}

# --- Utilities ---------------------------------------------------------------

def _user_wb_dir():
    d = os.path.join(current_app.instance_path, "luckysheet")
    os.makedirs(d, exist_ok=True)
    return d

def _user_wb_path():
    """
    Return the per-user Luckysheet JSON path under the app's instance folder.
    Falls back to 'anon.json' if no user id is present.
    """
    uid = session.get("user_id") or session.get("_id") or "anon"
    return os.path.join(_user_wb_dir(), f"{uid}.json")

def _to_lucky_rows(rows_2d):
    """Wrap plain values into Luckysheet cell dicts: {'v': value} or None."""
    return [[(None if v is None else {"v": v}) for v in row] for row in rows_2d]

def _from_lucky_rows(ls_rows):
    """Extract plain values from Luckysheet sheet['data'] array-of-arrays."""
    return [[(c.get("v") if isinstance(c, dict) else (None if c is None else c))
             for c in (row or [])] for row in (ls_rows or [])]

def _sheet_to_grid(sheet: dict):
    """
    Convert a Luckysheet sheet (either 'data' or 'celldata' style) to plain 2-D list.
    """
    if isinstance(sheet.get("data"), list) and sheet["data"]:
        return _from_lucky_rows(sheet["data"])

    grid = []
    for cell in sheet.get("celldata", []):
        r, c = cell["r"], cell["c"]
        v = cell["v"]
        v = v.get("v") if isinstance(v, dict) and "v" in v else v
        while len(grid) <= r:
            grid.append([])
        while len(grid[r]) <= c:
            grid[r].append(None)
        grid[r][c] = v
    return grid

def _grid_to_celldata(grid):
    """Convert plain 2-D list into Luckysheet 'celldata' array."""
    cells = []
    for r, row in enumerate(grid):
        for c, v in enumerate(row or []):
            if v is None:
                continue
            cells.append({"r": r, "c": c, "v": {"v": v}})
    return cells

# --- Seeding & Normalization -------------------------------------------------

def _seed_sheet():
    """
    Build a fresh first sheet with two header rows + one spacer row,
    merges, widths, and the required frozen spec.
    """
    head1 = ["Food", "Serving Size", None, None, "Nutrients"] + [None] * 12
    head2 = HEAD2
    spacer = [" "] + [None] * (len(HEAD2) - 1)  # a real 3rd row so freezing [3,1] is valid

    seed_rows = [head1, head2, spacer]
    sheet = {
        "name": "Foods", "index": 0, "order": 0, "status": 1,
        "data": _to_lucky_rows(seed_rows),
        "config": {
            "merge": MERGES.copy(),
            "rowlen": {"0": 28, "1": 28, "2": 8},
            "columnlen": COLUMNLEN.copy(),
        },
        "frozen": FROZEN.copy(),
    }
    return sheet

def _empty_workbook():
    return {"data": [_seed_sheet()]}

def _ensure_three_seed_rows(sheet: dict):
    """
    Guarantee the first sheet has at least 3 rows (two headers + spacer) and correct frozen.
    """
    if not isinstance(sheet, dict):
        return
    # Ensure data is present and at least 3 rows
    data = sheet.get("data")
    if not isinstance(data, list) or not data:
        sheet["data"] = _seed_sheet()["data"]
        data = sheet["data"]

    # Count rows
    rows = len(data)
    width = len(HEAD2)
    while rows < 3:
        spacer = [" "] + [None] * (width - 1)
        data.append(_to_lucky_rows([spacer])[0])
        rows += 1

    # Ensure frozen present & correct
    sheet["frozen"] = FROZEN.copy()

    # Ensure config with rowlen & columnlen is present
    cfg = sheet.setdefault("config", {})
    rowlen = cfg.setdefault("rowlen", {})
    rowlen["0"] = rowlen.get("0", 28)
    rowlen["1"] = rowlen.get("1", 28)
    rowlen["2"] = rowlen.get("2", 8)
    cfg.setdefault("merge", MERGES.copy())
    cfg.setdefault("columnlen", COLUMNLEN.copy())

def _normalize_wb(wb: dict):
    """
    Normalize a workbook loaded from disk or client:
    - ensure data array exists
    - ensure first sheet has at least 3 rows
    - enforce sheet-level frozen to FROZEN
    - strip any top-level 'frozen' (we keep it sheet-level for clarity)
    """
    if not isinstance(wb, dict):
        wb = {}
    data = wb.get("data")
    if not isinstance(data, list) or not data:
        wb = _empty_workbook()
        data = wb["data"]

    # Normalize first sheet
    sheet0 = data[0]
    if not isinstance(sheet0, dict):
        data[0] = _seed_sheet()
    else:
        _ensure_three_seed_rows(sheet0)

    # Remove any ambiguous top-level frozen
    if "frozen" in wb:
        wb.pop("frozen", None)

    return wb

# --- Load / Save -------------------------------------------------------------

def _safe_load():
    """
    Load the workbook; if file is missing/corrupt, return a normalized fresh one.
    Also normalize legacy shapes (e.g., wrong frozen spec).
    """
    p = _user_wb_path()
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                wb = json.load(f)
            return _normalize_wb(wb)
    except Exception:
        pass
    return _empty_workbook()

def _save_wb(wb: dict):
    """Persist workbook after normalizing structure and frozen."""
    wb = _normalize_wb(wb)
    p = _user_wb_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(wb, f, ensure_ascii=False)

# --- Public helpers used by other modules -----------------------------------

def append_rows(rows):
    """
    Append Luckysheet data rows to the first sheet.
    `rows` is a list[list] aligned to HEAD2 order.
    """
    wb = _safe_load()
    sheet = wb["data"][0]
    data_grid = _sheet_to_grid(sheet)

    # Ensure we have headers + spacer exactly once
    if len(data_grid) < 2:
        seeded = _sheet_to_grid(_seed_sheet())
        data_grid = seeded

    # Append rows, normalized to HEAD2 width
    for r in rows or []:
        arr = list(r[:len(HEAD2)]) + [None] * max(0, len(HEAD2) - len(r))
        data_grid.append(arr)

    # Write back and save
    sheet["data"] = _to_lucky_rows(data_grid)
    sheet["frozen"] = FROZEN.copy()
    _save_wb(wb)
    return {"ok": True, "added": len(rows or [])}

def append_rows_direct(rows):
    """Alias retained for compatibility with existing imports."""
    return append_rows(rows)

# --- API Routes --------------------------------------------------------------

@bp.get("/luckysheet")
def api_luckysheet_get():
    """
    Return the Luckysheet workbook JSON, always enforcing our freeze config
    on every sheet before sending it to the browser.
    """
    from pathlib import Path
    import json
    from flask import current_app, jsonify

    # Adjust this to however you currently locate your luckysheet JSON file
    inst = Path(current_app.instance_path)
    f = inst / "luckysheet" / "anon.json"  # or your actual filename

    if not f.exists():
        # If you have a function to build a seed workbook, call it here instead
        data = []  # or seed data
        # Enforce freeze on any sheets
        for sh in data:
            _enforce_frozen_on_sheet(sh)
        return jsonify({"data": data})

    raw_text = f.read_text(encoding="utf-8")
    wb = json.loads(raw_text) if raw_text.strip() else {}

    # Workbooks can be either:
    #  - {"data": [sheet, sheet, ...]} (typical Luckysheet)
    #  - [sheet, sheet, ...] as top-level list
    if isinstance(wb, dict) and isinstance(wb.get("data"), list):
        for sh in wb["data"]:
            _enforce_frozen_on_sheet(sh)
    elif isinstance(wb, list):
        for sh in wb:
            _enforce_frozen_on_sheet(sh)

    return jsonify(wb)

@bp.post("/luckysheet")
def api_luckysheet_post():
    """
    Save workbook JSON from Luckysheet, but normalize its freeze config
    first so future loads are consistent.
    """
    from pathlib import Path
    import json
    from flask import current_app, request, jsonify

    payload = request.get_json(silent=True) or {}

    # payload can be {"data":[...]} or just [...]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        for sh in payload["data"]:
            _enforce_frozen_on_sheet(sh)
    elif isinstance(payload, list):
        for sh in payload:
            _enforce_frozen_on_sheet(sh)

    inst = Path(current_app.instance_path)
    f = inst / "luckysheet" / "anon.json"  # adjust to match GET

    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return jsonify({"ok": True})

@bp.post("/luckysheet/append")
def api_luckysheet_append():
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or []
    result = append_rows(rows)
    return jsonify(result)
@bp.post("/luckysheet/reset")
def api_luckysheet_reset():
    """
    Server-owned reset: throw away the current workbook and seed a fresh one.
    This guarantees headers + frozen are in the shape Daily & USDA expect.
    """
    _save_wb(_empty_workbook())
    return jsonify({"ok": True})
