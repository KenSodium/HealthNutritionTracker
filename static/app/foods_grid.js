console.log("[GRID] foods_grid.js loaded");

const $ = (s, r = document) => r.querySelector(s);

// Columns (NOTE: serving field names now match your Flask API rows)
const COLS = [
  {
    title: "",
    field: "_select",
    width: 46,
    minWidth: 46,
    headerSort: false,
    hozAlign: "center",
    formatter: "rowSelection",
    titleFormatter: "rowSelection",
    titleFormatterParams: { rowRange: "active" },
    frozen: true,
  },
  { title: "Food", field: "description", width: 220, minWidth: 160, headerSort: true, editor: "input", frozen: true },

  // Serving columns (match API row keys)
  { title: "Size",       field: "serving_size",     width: 90,  minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Units",      field: "serving_units",    width: 100, minWidth: 70, headerSort: true, hozAlign: "left",  editor: "input"  },
  { title: "Weight (g)", field: "serving_weight_g", width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },

  { title: "Sodium (mg)", field: "Sodium",    width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Potassium",   field: "Potassium", width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Protein (g)", field: "Protein",   width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Carbs (g)",   field: "Carbs",     width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Fat (g)",     field: "Fat",       width: 100, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Sat Fat (g)", field: "Sat Fat",   width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Mono Fat (g)",field: "Mono Fat",  width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Poly Fat (g)",field: "Poly Fat",  width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Sugar (g)",   field: "Sugar",     width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Calcium (mg)",field: "Calcium",   width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Magnesium (mg)", field: "Magnesium", width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Iron (mg)",   field: "Iron",      width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
  { title: "Calories",    field: "Calories",  width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
];

if (!window.Tabulator) {
  console.error("Tabulator library not found (static/vendor/tabulator/dist).");
}

let grid;
let lastRowClicked = null;
let scroller = null;

(function init() {
  const mount = $("#foods-grid");
  if (!mount || !window.Tabulator) return;

  grid = new Tabulator(mount, {
    columns: COLS,
    height: "100%",
    layout: "fitData",              // natural width; horizontal scroll appears when needed
    resizableColumnFit: false,
    movableColumns: true,
    selectable: true,
    rowHeight: 28,
    columnDefaults: { headerHozAlign: "left", vertAlign: "middle" },

    // ---- Load from your API
    ajaxURL: "/api/foods/list",
    ajaxConfig: "GET",
    ajaxContentType: "json",
    ajaxResponse: function (_url, params, response) {
      // Flask returns {total, rows}
      return (response && response.rows) || [];
    },

    // Save cell edits to your API
    cellEdited: async function (cell) {
      try {
        const row = cell.getRow().getData();
        const field = cell.getField();
        const value = cell.getValue();
        if (!row.fdcId) return;

        const body = {};
        body[field] = value;

        const res = await fetch(`/api/foods/${encodeURIComponent(row.fdcId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`PATCH failed: ${res.status}`);
      } catch (err) {
        console.error(err);
        alert("Save failed. See console.");
      }
    },
  });

  grid.on("rowClick", (_e, row) => (lastRowClicked = row));

  grid.on("tableBuilt", () => {
    const root = grid.getElement?.();
    scroller = root ? root.querySelector(".tabulator-tableholder") : null;
    if (scroller) scroller.style.overflowX = "auto";

    addDividerAfter("Protein");
    wireToolbar();
    wireSearch();                 // client-side filter is fine for now
    wireColumnWidthControl();
    wirePanButtons();
  });
})();

function addDividerAfter(fieldName) {
  const root = grid?.getElement?.();
  if (!root) return;
  const headerCol = root.querySelector(`.tabulator-col[data-field="${fieldName}"]`);
  if (headerCol) headerCol.style.borderRight = "2px solid var(--tblr-border-color,#666)";
  const cells = root.querySelectorAll(`.tabulator-cell[tabulator-field="${fieldName}"]`);
  cells.forEach((el) => (el.style.borderRight = "2px solid var(--tblr-border-color,#666)"));
}

// ---------- Column Width control ----------
function wireColumnWidthControl() {
  const slider = $("#colw");
  const label = $("#colw-val");
  if (!slider) return;

  const skipFields = new Set(["_select", "description"]); // keep frozen widths as-is
  let rafId = null, pendingVal = null;

  function doApply(valPx) {
    const target = Math.max(60, Math.min(220, parseInt(valPx || "110", 10)));
    if (label) label.textContent = `${target}px`;

    const canUpdateDef = typeof grid.updateColumnDefinition === "function";

    grid.getColumns().forEach((col) => {
      const field = col.getField && col.getField();
      if (!field || skipFields.has(field)) return;

      if (canUpdateDef) {
        try { grid.updateColumnDefinition(field, { width: target }); return; } catch {}
      }
      if (typeof col.setWidth === "function") {
        try { col.setWidth(target, true); } catch { col.setWidth(target); }
      }
    });

    requestAnimationFrame(() => grid.redraw(true));
  }

  function schedule(valPx) {
    pendingVal = valPx;
    if (rafId != null) return;
    rafId = requestAnimationFrame(() => { rafId = null; doApply(pendingVal); });
  }

  schedule(slider.value);
  slider.addEventListener("input", (e) => {
    const v = e.target.value;
    if (label) label.textContent = `${parseInt(v || "110", 10)}px`;
    schedule(v);
  });
  slider.addEventListener("change", (e) => schedule(e.target.value));
}

// ---------- Pan buttons ----------
function wirePanButtons() {
  const left = $("#btn-pan-left");
  const right = $("#btn-pan-right");
  const STEP = 300;

  function pan(dx) {
    if (!scroller) return;
    scroller.scrollBy({ left: dx, behavior: "smooth" });
  }

  left?.addEventListener("click", () => pan(-STEP));
  right?.addEventListener("click", () => pan(+STEP));
}

// ---------- Toolbar ----------
function wireToolbar() {
  const btnInsertTop = $("#btn-insert-top");
  const btnDeleteRow = $("#btn-delete-row");
  const btnDelete = $("#btn-delete");
  const btnExport = $("#btn-export");
  const fileImp = $("#file-import");

  btnInsertTop?.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/foods/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: "New Food" }),
      });
      if (!res.ok) throw new Error(`create failed: ${res.status}`);
      const data = await res.json();
      if (data && data.row) {
        await grid.addData([data.row], true); // add to top
      } else {
        // fallback: reload
        grid.replaceData();
      }
    } catch (err) {
      console.error(err);
      alert("Insert failed.");
    }
  });

  btnDeleteRow?.addEventListener("click", async () => {
    let rows = [];
    if (lastRowClicked) {
      rows = [lastRowClicked];
    } else {
      rows = grid.getSelectedRows().slice(0, 1);
    }
    if (!rows.length) return;

    await bulkDeleteRows(rows);
  });

  btnDelete?.addEventListener("click", async () => {
    const rows = grid.getSelectedRows();
    if (!rows.length) return;
    await bulkDeleteRows(rows);
  });

  btnExport?.addEventListener("click", () => {
    // Use your server export (preserves exact numbers/columns):
    window.location.href = "/api/foods/export.csv";
    // Or keep Tabulator client export:
    // grid.download("csv", "foods_grid.csv");
  });

  fileImp?.addEventListener("change", async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try {
      const text = await f.text();
      const rows = parseDelimited(text);
      if (!rows.length) return;

      // Map CSV headers to our grid fields (including serving_* names)
      const map = {
        food: "description",
        description: "description",
        name: "description",
        size: "serving_size",
        units: "serving_units",
        weight: "serving_weight_g",
        sodium: "Sodium",
        potassium: "Potassium",
        protein: "Protein",
        carbs: "Carbs",
        fat: "Fat",
        "sat fat": "Sat Fat",
        saturated: "Sat Fat",
        "mono fat": "Mono Fat",
        "poly fat": "Poly Fat",
        sugar: "Sugar",
        calcium: "Calcium",
        magnesium: "Magnesium",
        iron: "Iron",
        calories: "Calories",
      };

      const out = rows.map((r) => {
        const o = {};
        for (const [k, v] of Object.entries(r)) {
          const key = (k || "").trim().toLowerCase();
          const field = map[key];
          if (!field) continue;
          if (field === "description" || field === "serving_units") o[field] = String(v || "");
          else o[field] = v === "" ? null : Number(v);
        }
        // Ensure all fields exist
        COLS.forEach((c) => {
          if (!(c.field in o) && c.field !== "_select") {
            o[c.field] = (c.field === "description" || c.field === "serving_units") ? "" : null;
          }
        });
        return o;
      });

      // Client-side insert (fast). If you prefer server-side import, we can add an endpoint later.
      await grid.addData(out, true);
    } catch (err) {
      console.error("Import failed", err);
      alert("Import failed. See console.");
    } finally {
      e.target.value = "";
    }
  });
}

async function bulkDeleteRows(rows) {
  try {
    const ids = rows
      .map((r) => r.getData())
      .map((d) => d.fdcId)
      .filter(Boolean);

    if (!ids.length) return;

    const res = await fetch("/api/foods/bulk_delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    if (!res.ok) throw new Error(`bulk_delete failed: ${res.status}`);

    rows.forEach((r) => r.delete());
    lastRowClicked = null;
  } catch (err) {
    console.error(err);
    alert("Delete failed.");
  }
}

// ---------- Search (client-side filter is fine for now) ----------
function wireSearch() {
  const input = $("#food-search");
  const clear = $("#btn-clear-search");

  function apply() {
    const q = (input.value || "").trim();
    if (!q) {
      grid.clearFilter();
      return;
    }
    grid.setFilter([{ field: "description", type: "like", value: q }]);
  }

  let t = null;
  input?.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(apply, 150);
  });
  clear?.addEventListener("click", () => {
    if (!input) return;
    input.value = "";
    grid.clearFilter();
    input.focus();
  });
}

// ---------- Helpers ----------
function parseDelimited(text) {
  const first = text.split(/\r?\n/).find((l) => l.trim().length) || "";
  const delim = first.includes("\t") && !first.includes(",") ? "\t" : ",";

  const lines = text.split(/\r?\n/).filter((l) => l.trim().length);
  if (!lines.length) return [];

  const headers = splitRow(lines.shift(), delim).map((h) => h.trim());
  const rows = lines.map((line) => {
    const cells = splitRow(line, delim);
    const obj = {};
    headers.forEach((h, i) => (obj[h] = (cells[i] ?? "").trim()));
    return obj;
  });
  return rows;

  function splitRow(line, d) {
    const out = [];
    let cur = "", inQ = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (inQ && line[i + 1] === '"') { cur += '"'; i++; }
        else inQ = !inQ;
      } else if (ch === d && !inQ) {
        out.push(cur); cur = "";
      } else {
        cur += ch;
      }
    }
    out.push(cur);
    return out;
  }
}
