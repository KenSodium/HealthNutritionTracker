console.log("[GRID] foods_grid.js loaded");

const $ = (s, r = document) => r.querySelector(s);

/* ---------------- Columns: grouped with super-headings ---------------- */

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

  {
    title: "Serving Size",
    columns: [
      { title: "Number of Units", field: "Size", width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Name of Units",  field: "Units", width: 120, minWidth: 70, headerSort: true, hozAlign: "left",  editor: "input"  },
      { title: "Weight of Serving (g)", field: "Weight", width: 140, minWidth: 90, headerSort: true, hozAlign: "right", editor: "number" },
    ],
  },

  {
    title: "Nutrients",
    columns: [
      // Put a heavy divider on the first column of this group via cssClass
      { title: "Sodium (mg)",    field: "Sodium",    width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number", cssClass: "col-divider-left" },
      { title: "Potassium (mg)", field: "Potassium", width: 130, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Protein (g)",    field: "Protein",   width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Carbs (g)",      field: "Carbs",     width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Fat (g)",        field: "Fat",       width: 100, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Sat Fat (g)",    field: "Sat Fat",   width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Mono Fat (g)",   field: "Mono Fat",  width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Poly Fat (g)",   field: "Poly Fat",  width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Sugar (g)",      field: "Sugar",     width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Calcium (mg)",   field: "Calcium",   width: 120, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Magnesium (mg)", field: "Magnesium", width: 130, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Iron (mg)",      field: "Iron",      width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
      { title: "Calories",       field: "Calories",  width: 110, minWidth: 70, headerSort: true, hozAlign: "right", editor: "number" },
    ],
  },
];

/* ---------------- Demo rows (keep your existing mock data) ---------------- */

function makeRow(i) {
  const sizes = [
    { Size: 1, Units: "slice",    Weight: 28 },
    { Size: 3, Units: "crackers", Weight: 18 },
    { Size: 2, Units: "tbsp",     Weight: 30 },
    { Size: 1, Units: "cup",      Weight: 240 },
  ];
  const s = sizes[i % sizes.length];

  return {
    description: `Food ${i + 1}`,
    Size: s.Size,
    Units: s.Units,
    Weight: s.Weight,
    Sodium: Math.round(Math.random() * 800),
    Potassium: Math.round(Math.random() * 1200),
    Protein: +(Math.random() * 40).toFixed(1),
    Carbs: +(Math.random() * 60).toFixed(1),
    Fat: +(Math.random() * 30).toFixed(1),
    "Sat Fat": +(Math.random() * 10).toFixed(1),
    "Mono Fat": +(Math.random() * 12).toFixed(1),
    "Poly Fat": +(Math.random() * 12).toFixed(1),
    Sugar: +(Math.random() * 20).toFixed(1),
    Calcium: Math.round(Math.random() * 400),
    Magnesium: Math.round(Math.random() * 200),
    Iron: +(Math.random() * 10).toFixed(1),
    Calories: Math.round(Math.random() * 400),
  };
}
const ROWS = Array.from({ length: 25 }, (_, i) => makeRow(i));

if (!window.Tabulator) {
  console.error("Tabulator library not found (static/vendor/tabulator/dist).");
}

let grid;
let lastRowClicked = null;
let scroller = null;

/* ---------------- Init ---------------- */

(function init() {
  const mount = $("#foods-grid");
  if (!mount || !window.Tabulator) return;

  grid = new Tabulator(mount, {
    data: ROWS,
    columns: COLS,
    height: "540px",              // explicit height so body renders
    layout: "fitData",            // allow natural width (overflow ⇒ horizontal scroll)
    resizableColumnFit: false,
    movableColumns: true,
    selectable: true,
    rowHeight: 28,
    columnDefaults: { headerHozAlign: "left", vertAlign: "middle" },
  });

  grid.on("rowClick", (_e, row) => (lastRowClicked = row));

  grid.on("tableBuilt", () => {
    const root = grid.getElement?.();
    scroller = root ? root.querySelector(".tabulator-tableholder") : null;
    if (scroller) scroller.style.overflowX = "auto";
    console.log("[GRID] rows =", grid.getDataCount()); // sanity check

    wireToolbar();
    wireSearch();
    wireColumnWidthControl();
    wirePanButtons();
  });
})();

/* ---------------- Column Width control ---------------- */

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
      // skip group headers (no field)
      if (col.getType && col.getType() === "group") return;

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

/* ---------------- Pan buttons ---------------- */

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

/* ---------------- Toolbar (insert/delete/export/import) ---------------- */

function wireToolbar() {
  const btnInsertTop = $("#btn-insert-top");
  const btnDeleteRow = $("#btn-delete-row");
  const btnDelete = $("#btn-delete");
  const btnExport = $("#btn-export");
  const fileImp = $("#file-import");

  btnInsertTop?.addEventListener("click", () => {
    grid.addRow(blankRow(), true); // add at top
  });

  btnDeleteRow?.addEventListener("click", () => {
    if (lastRowClicked) {
      lastRowClicked.delete();
      lastRowClicked = null;
      return;
    }
    const rows = grid.getSelectedRows();
    if (rows.length) rows[0].delete();
  });

  btnDelete?.addEventListener("click", () => {
    const rows = grid.getSelectedRows();
    if (!rows.length) return;
    rows.forEach((r) => r.delete());
  });

  btnExport?.addEventListener("click", () => {
    grid.download("csv", "foods_grid.csv");
  });

  fileImp?.addEventListener("change", async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try {
      const text = await f.text();
      const rows = parseDelimited(text);
      if (!rows.length) return;

      const map = {
        food: "description",
        description: "description",
        name: "description",
        size: "Size",
        "number of units": "Size",
        units: "Units",
        "name of units": "Units",
        weight: "Weight",
        "weight of serving (g)": "Weight",
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
          if (field === "description" || field === "Units") o[field] = String(v || "");
          else o[field] = v === "" ? null : Number(v);
        }
        // fill any missing fields so row is complete
        walkLeafFields(COLS).forEach((fld) => {
          if (!(fld in o)) o[fld] = (fld === "description" || fld === "Units") ? "" : null;
        });
        return o;
      });

      grid.addData(out, true); // prepend at top
    } catch (err) {
      console.error("Import failed", err);
      alert("Import failed. See console.");
    } finally {
      e.target.value = "";
    }
  });
}

/* ---------------- Search ---------------- */

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

/* ---------------- Helpers ---------------- */

function blankRow() {
  return {
    description: "",
    Size: null,
    Units: "",
    Weight: null,
    Sodium: null,
    Potassium: null,
    Protein: null,
    Carbs: null,
    Fat: null,
    "Sat Fat": null,
    "Mono Fat": null,
    "Poly Fat": null,
    Sugar: null,
    Calcium: null,
    Magnesium: null,
    Iron: null,
    Calories: null,
  };
}

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

/* gather leaf fields from grouped columns */
function walkLeafFields(cols) {
  const out = [];
  for (const c of cols) {
    if (Array.isArray(c.columns)) out.push(...walkLeafFields(c.columns));
    else if (c.field) out.push(c.field);
  }
  return out;
}
