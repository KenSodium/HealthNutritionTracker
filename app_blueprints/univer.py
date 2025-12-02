# app_blueprints/univer.py

import os
import json
import shutil
from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    current_app,
    jsonify,
    request,
    redirect,
    url_for,
)

univer_bp = Blueprint(
    "univer",
    __name__,
    url_prefix="/univer",
)

# -------------------------------------------------------------------
# NEW: Curated foods helpers
# -------------------------------------------------------------------

def _curated_path() -> str:
    """
    Location of the curated foods JSON that ships with the app.

    By default this assumes:
        nutrition/data/curated_foods.json
    relative to your Flask app root.

    You can change this path if needed.
    """
    return os.path.join(
        current_app.root_path,
        "nutrition",
        "data",
        "curated_foods.json",
    )


def _load_curated_rows():
    """
    Load curated foods as a list of dicts from curated_foods.json.

    Expected JSON structure:
        [ { "Food": "...", "Calories": 100, ... }, ... ]

    If the file doesn't exist or is bad, returns [] and logs an error.
    """
    path = _curated_path()
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        current_app.logger.exception("Error loading curated foods JSON")
        return []

    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


# -------------------------------------------------------------------
# Path helpers + backup utilities
# -------------------------------------------------------------------

def _univer_dir() -> str:
    """Ensure instance/univer exists and return its path."""
    base = current_app.instance_path
    path = os.path.join(base, "univer")
    os.makedirs(path, exist_ok=True)
    return path


def _live_path() -> str:
    """Path to the live Univer foods table JSON."""
    return os.path.join(_univer_dir(), "foods_table.json")


def _backup_dir() -> str:
    """Ensure instance/univer/backups exists and return its path."""
    path = os.path.join(_univer_dir(), "backups")
    os.makedirs(path, exist_ok=True)
    return path


def _create_backup_if_exists() -> None:
    """
    If there is an existing foods_table.json, copy it to the backups folder
    with a timestamped name and keep only the newest 3 backups.
    """
    live = _live_path()
    if not os.path.exists(live):
        return

    # Timestamped filename: foods_table_YYYYmmdd-HHMMSS.json
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    bdir = _backup_dir()
    backup_name = f"foods_table_{ts}.json"
    backup_path = os.path.join(bdir, backup_name)

    shutil.copy2(live, backup_path)

    # Rotate: keep only 3 newest backups
    files = []
    for fname in os.listdir(bdir):
        if fname.startswith("foods_table_") and fname.endswith(".json"):
            full = os.path.join(bdir, fname)
            try:
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            files.append((full, mtime))

    # Newest first
    files.sort(key=lambda x: x[1], reverse=True)

    # Delete any beyond the newest 3
    for full, _ in files[3:]:
        try:
            os.remove(full)
        except OSError:
            pass


def _list_backups():
    """
    Return up to 3 newest backups as:
        [{ "name": filename, "label": "YYYY-mm-dd HH:MM" }, ...]
    """
    bdir = _backup_dir()
    items = []
    for fname in os.listdir(bdir):
        if fname.startswith("foods_table_") and fname.endswith(".json"):
            full = os.path.join(bdir, fname)
            try:
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            dt = datetime.fromtimestamp(mtime)
            items.append(
                {
                    "name": fname,
                    "label": dt.strftime("%Y-%m-%d %H:%M"),
                }
            )

    # Sort newest first by label (which encodes time)
    items.sort(key=lambda x: x["label"], reverse=True)
    return items[:3]


# -------------------------------------------------------------------
# Page: Univer foods sheet
# -------------------------------------------------------------------

@univer_bp.route("/foods")
def univer_foods():
    """
    Show the Univer-based 'My Food List' sheet.
    Also pass backup metadata so the template can show a restore dropdown.
    """
    backups = _list_backups()
    return render_template("app/univer_foods.html", backups=backups)


# -------------------------------------------------------------------
# API: load/save foods_table.json
# -------------------------------------------------------------------

@univer_bp.route("/api/foods-table", methods=["GET"])
def api_foods_table():
    """
    Read the Univer backing table written by USDA Search and/or Univer UI:
        instance/univer/foods_table.json

    Returns:
        { ok: true, rows: [...] }
    """
    path = _live_path()

    if not os.path.exists(path):
        # No file yet: treat as empty table
        return jsonify({"ok": True, "rows": []})

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Accept either {rows: [...]} or a raw list
        if isinstance(data, dict):
            rows = data.get("rows", [])
        else:
            rows = data

        if not isinstance(rows, list):
            rows = []

        return jsonify({"ok": True, "rows": rows})
    except Exception as e:
        current_app.logger.exception(
            "Error loading Univer foods_table.json: %s", e
        )
        return jsonify({"ok": False, "error": "Failed to load Univer food table"}), 500


@univer_bp.route("/api/foods-table", methods=["POST"])
def api_foods_table_save():
    """
    Overwrite the Univer backing table with rows sent from the Univer sheet.

    Expected JSON:
        { "rows": [ [header...], [row1...], [row2...], ... ] }

    On success:
        { "ok": true }

    Now also creates a timestamped backup of the previous file
    and keeps only the newest 3 backups.
    """
    path = _live_path()

    try:
        payload = request.get_json(silent=True) or {}
        rows = payload.get("rows", [])

        if not isinstance(rows, list):
            return jsonify({"ok": False, "error": "rows must be a list"}), 400

        # Normalize: ensure rows is list-of-lists of simple values
        norm_rows = []
        for r in rows:
            if isinstance(r, list):
                norm_rows.append(r)
            elif isinstance(r, (tuple,)):
                norm_rows.append(list(r))
            else:
                # Skip bad rows
                continue

        # Create backup *before* overwriting the live file
        _create_backup_if_exists()

        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rows": norm_rows}, f, ensure_ascii=False, indent=2)

        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.exception(
            "Error saving Univer foods_table.json: %s", e
        )
        return jsonify({"ok": False, "error": "Failed to save Univer food table"}), 500


# -------------------------------------------------------------------
# Restore from backup (called by dropdown on Univer page)
# -------------------------------------------------------------------

@univer_bp.route("/restore-backup", methods=["POST"])
def restore_backup():
    """
    Replace the current foods_table.json with a selected backup file.
    The backup name comes from a <select> on the Univer page.
    """
    backup_name = request.form.get("backup_name", "")

    # Basic safety: no path tricks, only our pattern
    if not (backup_name.startswith("foods_table_") and backup_name.endswith(".json")):
        return redirect(url_for("univer.univer_foods"))

    bpath = os.path.join(_backup_dir(), backup_name)
    if not os.path.exists(bpath):
        return redirect(url_for("univer.univer_foods"))

    try:
        shutil.copy2(bpath, _live_path())
    except Exception as e:
        current_app.logger.exception("Failed to restore backup %s: %s", backup_name, e)

    return redirect(url_for("univer.univer_foods"))


# -------------------------------------------------------------------
# NEW: Univer foods_table helpers (header + rows)
# -------------------------------------------------------------------

def _load_univer_rows():
    """
    Load rows from instance/univer/foods_table.json as a list-of-lists.
    """
    path = _live_path()
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        current_app.logger.exception("Error loading Univer foods_table.json")
        return []

    if isinstance(data, dict):
        rows = data.get("rows", []) or []
    else:
        rows = data or []

    if not isinstance(rows, list):
        return []
    return rows


def _get_univer_header(rows):
    """
    Treat the first row of the Univer sheet as the header.

    We DO NOT invent a new header here. If there is no first row,
    we return None and let the caller decide what to do.
    """
    if rows and isinstance(rows[0], list):
        return rows[0]
    return None


# -------------------------------------------------------------------
# NEW: API – curated foods (read-only)
# -------------------------------------------------------------------

@univer_bp.route("/api/curated-foods", methods=["GET"])
def api_curated_foods():
    """
    Return the curated foods list for display in a Tabulator table.

    Returns:
        { ok: true, rows: [ { ... }, ... ] }

    The rows are dicts keyed by your canonical column names
    (Food, Sodium, Potassium, etc.).
    """
    rows = _load_curated_rows()
    return jsonify({"ok": True, "rows": rows})


# -------------------------------------------------------------------
# NEW: API – add curated foods into Univer foods_table.json
# -------------------------------------------------------------------

@univer_bp.route("/api/add-curated", methods=["POST"])
def api_add_curated():
    """
    Append curated rows into the Univer foods_table.json.

    Expected JSON:
        { "rows": [ { ... }, { ... }, ... ] }

    Each dict is keyed by your existing header column names in the Univer sheet.
    We do NOT change the header; we simply map dicts -> list-of-values in
    that existing header order, and append unique rows.
    """
    try:
        payload = request.get_json(silent=True) or {}
        new_dict_rows = payload.get("rows", [])
        if not isinstance(new_dict_rows, list):
            return jsonify({"ok": False, "error": "rows must be a list"}), 400

        # Load current Univer rows and header
        rows = _load_univer_rows()
        header = _get_univer_header(rows)

        if header is None:
            # Safety: don't invent a header; require the existing sheet to have one
            return jsonify({
                "ok": False,
                "error": "Univer sheet has no header row. "
                         "Open 'My Food List (Univer)' and ensure the first row "
                         "contains your column names, then save."
            }), 400

        # Convert dict rows -> list rows in header order
        converted = []
        for rec in new_dict_rows:
            if not isinstance(rec, dict):
                continue
            row = [rec.get(col, "") for col in header]
            converted.append(row)

        # Simple de-duplication by full row content (excluding header)
        existing_set = {tuple(r) for r in rows[1:]}  # skip header row
        appended = 0

        for r in converted:
            t = tuple(r)
            if t in existing_set:
                continue
            rows.append(r)
            existing_set.add(t)
            appended += 1

        # Backup and save updated sheet
        _create_backup_if_exists()
        with open(_live_path(), "w", encoding="utf-8") as f:
            json.dump({"rows": rows}, f, ensure_ascii=False, indent=2)

        return jsonify({"ok": True, "added": appended})
    except Exception as e:
        current_app.logger.exception("Error adding curated rows: %s", e)
        return jsonify({"ok": False, "error": "Failed to add curated rows"}), 500
