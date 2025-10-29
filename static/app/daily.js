/* static/app/daily.js */
console.log("[DAILY] v20 loaded");

const $ = (s, r = document) => r.querySelector(s);
const fmt0 = (v) => (isFinite(v) ? Math.round(v) : 0);
const fmt1 = (v) => (isFinite(v) ? Number(v).toFixed(1) : "0.0");
const fmt2 = (v) => (isFinite(v) ? Number(v).toFixed(2) : "0.00");

const ISO = (window.__DAILY_BOOT__?.date || new Date().toISOString().slice(0, 10));
const NA_BUDGET = 1500; // mg

let grid;
let foods = bootFoodsFromMyFoodList();

/** Build rows from the app’s source of truth: My Food List. */
function bootFoodsFromMyFoodList() {
  const src = (window.__DAILY_BOOT__?.myFoods || []);
  return src.map(f => {
    const pref = f.pref || {};
    const comp = f.computed || {};
    const perServ = Object.assign({
      Sodium:0, Potassium:0, Protein:0, Carbs:0, Fat:0,
      "Sat Fat":0, "Mono Fat":0, "Poly Fat":0, Sugar:0,
      Calcium:0, Magnesium:0, Iron:0, Calories:0
    }, comp.portion_nutrients || {}, f.perServ || {});

    // grams for ONE “serving” in this grid (your preview grams from My Food List)
    const servG = (typeof comp.portion_grams === "number" && comp.portion_grams > 0) ? comp.portion_grams : 100;

    return {
      // identity
      fdcId: String(f.fdcId || f.id || ""),
      description: f.description || f.name || "(item)",

      // serving definition (for display/reference)
      Size: (typeof f.servingSize === "number") ? f.servingSize : null, // not used for math
      Units: (pref.unit_key || f.servingSizeUnit || "").toString(),
      Weight: servG, // grams per *one* serving in this grid

      // per-serving nutrients (for the serving defined above)
      perServ,

      // day entry fields (user edits)
      Ate: 0,       // number of servings eaten today
      Grams: null,  // if set, use grams override instead of Ate

      // cached computed — kept for convenience
      _calc: { gramsToday: 0, scale: 0 },
    };
  });
}

/** How many grams should be saved for today’s diary row? */
function gramsForRow(row) {
  const g = Number(row.Grams || 0);
  if (isFinite(g) && g > 0) return g;
  const servG = Number(row.Weight || 0);
  const ate = Number(row.Ate || 0);
  return (isFinite(servG) && isFinite(ate)) ? servG * ate : 0;
}

/** Scale factor for today’s nutrient totals (servings or grams override). */
function scaleForRow(row) {
  const g = Number(row.Grams || 0);
  const servG = Number(row.Weight || 0);
  if (isFinite(g) && g > 0 && isFinite(servG) && servG > 0) {
    return g / servG; // grams override
  }
  const ate = Number(row.Ate || 0);
  return isFinite(ate) ? ate : 0; // servings
}

/** Compute “today” value for a nutrient key on a row. */
function todayVal(row, key) {
  const base = Number(row.perServ?.[key] || 0);
  const s = scaleForRow(row);
  return (isFinite(base) && isFinite(s)) ? base * s : 0;
}

/** Render a simple sodium % bar (of 1500 mg). */
function renderNaPct(cell, formatterParams, onRendered) {
  const row = cell.getRow().getData();
  const mg = todayVal(row, "Sodium");
  const pct = Math.min(100, Math.max(0, (mg / NA_BUDGET) * 100));
  const label = `${fmt1(pct)}%`;

  const wrap = document.createElement("div");
  wrap.style.display = "flex";
  wrap.style.alignItems = "center";
  wrap.style.gap = "8px";

  const barBox = document.createElement("div");
  barBox.style.flex = "1 1 auto";
  barBox.style.height = "10px";
  barBox.style.background = "rgba(0,0,0,0.08)";
  barBox.style.borderRadius = "6px";
  barBox.style.overflow = "hidden";

  const fill = document.createElement("div");
  fill.style.height = "100%";
  fill.style.width = `${pct}%`;
  // color scale (green -> amber -> red-ish)
  let bg = "#66bb6a";
  if (pct >= 66) bg = "#ef5350";
  else if (pct >= 33) bg = "#ffa726";
  fill.style.background = bg;

  barBox.appendChild(fill);

  const txt = document.createElement("div");
  txt.textContent = label;
  txt.style.minWidth = "52px";
  txt.style.textAlign = "right";
  txt.style.fontVariantNumeric = "tabular-nums";

  wrap.appendChild(barBox);
  wrap.appendChild(txt);
  return wrap;
}

/** API helpers (defensive: don’t crash if server absent) */
async function apiDiaryAdd(fid, grams, dateIso) {
  const r = await fetch(`/app/api/diary/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: dateIso, fdcId: fid, grams })
  });
  if (!r.ok) throw new Error("diary/add failed");
  return r.json();
}
async function apiDiaryQty(fid, grams, dateIso) {
  const r = await fetch(`/app/api/diary/qty`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: dateIso, fdcId: fid, grams })
  });
  if (!r.ok) throw new Error("diary/qty failed");
  return r.json();
}
async function apiDiaryRemove(fid, dateIso) {
  const r = await fetch(`/app/api/diary/remove`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: dateIso, fdcId: fid })
  });
  if (!r.ok) throw new Error("diary/remove failed");
  return r.json();
}

/** Persist one row after edit. */
let saveInFlight = 0;
async function persistRow(rowData) {
  const fid = rowData.fdcId;
  const grams = gramsForRow(rowData);

  try {
    saveInFlight++;
    if (grams > 0) {
      await apiDiaryQty(fid, grams, ISO).catch(async () => {
        // if qty fails (no entry yet), try add
        await apiDiaryAdd(fid, grams, ISO);
      });
    } else {
      await apiDiaryRemove(fid, ISO);
    }
  } catch (e) {
    console.error(e);
    // don’t block UI; show a soft alert
    if (window?.alert) alert("Save failed (diary). See console.");
  } finally {
    saveInFlight--;
  }
}

/** After any edit, recompute cached & refresh totals panel. */
function postEditRefresh() {
  // refresh cached computed values for all rows (for performance if needed)
  grid?.getData()?.forEach(r => {
    const grams = gramsForRow(r);
    r._calc.gramsToday = grams;
    r._calc.scale = scaleForRow(r);
  });
  renderTotalsPanel();
}

/** Totals panel on the right (Today’s Totals). */
function renderTotalsPanel() {
  const host = $("#totals-panel");
  if (!host) return;

  let totals = {
    Sodium: 0, Potassium: 0, Protein: 0, Carbs: 0, Fat: 0,
    "Sat Fat": 0, "Mono Fat": 0, "Poly Fat": 0, Sugar: 0,
    Calcium: 0, Magnesium: 0, Iron: 0, Calories: 0,
    grams: 0,
  };

  grid.getData().forEach(r => {
    const s = scaleForRow(r);
    totals.Sodium    += (r.perServ.Sodium || 0)    * s;
    totals.Potassium += (r.perServ.Potassium || 0) * s;
    totals.Protein   += (r.perServ.Protein || 0)   * s;
    totals.Carbs     += (r.perServ.Carbs || 0)     * s;
    totals.Fat       += (r.perServ.Fat || 0)       * s;
    totals["Sat Fat"]+= (r.perServ["Sat Fat"]||0)  * s;
    totals["Mono Fat"]+= (r.perServ["Mono Fat"]||0)* s;
    totals["Poly Fat"]+= (r.perServ["Poly Fat"]||0)* s;
    totals.Sugar     += (r.perServ.Sugar || 0)     * s;
    totals.Calcium   += (r.perServ.Calcium || 0)   * s;
    totals.Magnesium += (r.perServ.Magnesium || 0) * s;
    totals.Iron      += (r.perServ.Iron || 0)      * s;
    totals.Calories  += (r.perServ.Calories || 0)  * s;
    totals.grams     += gramsForRow(r);
  });

  const naPct = Math.min(100, Math.max(0, (totals.Sodium / NA_BUDGET) * 100));
  const bar = `
    <div style="height:10px;background:rgba(0,0,0,.08);border-radius:6px;overflow:hidden">
      <div style="height:100%;width:${naPct}%;background:${naPct>=66?'#ef5350':naPct>=33?'#ffa726':'#66bb6a'}"></div>
    </div>`;

  host.innerHTML = `
    <div class="mb-2"><strong>Sodium</strong> ${fmt0(totals.Sodium)} mg of ${NA_BUDGET} mg</div>
    ${bar}
    <hr class="my-2">
    <div class="small text-muted">Potassium</div>
    <div class="mb-2">${fmt0(totals.Potassium)} mg</div>
    <div class="small text-muted">Protein</div>
    <div class="mb-2">${fmt1(totals.Protein)} g</div>
    <div class="small text-muted">Calories</div>
    <div class="mb-2">${fmt0(totals.Calories)}</div>
    <div class="small text-muted">Total grams eaten</div>
    <div class="mb-1">${fmt0(totals.grams)} g</div>
  `;
}

/* -------------------- Tabulator Grid -------------------- */

const COLS = [
  // selection
  {
    title: "", field: "_sel", width: 46, minWidth: 46, headerSort: false, hozAlign: "center",
    formatter: "rowSelection", titleFormatter: "rowSelection",
    titleFormatterParams: { rowRange: "active" }, frozen: true,
  },

  // Food
  { title: "Food", field: "description", width: 260, minWidth: 180, headerSort: true, editor: "input", frozen: true },

  // >>> Per request: move these right next to Food
  { title: "Ate Today", field: "Ate", width: 110, hozAlign: "right",
    editor: "number", editorParams: { min: 0, step: 0.5 },
    cellEdited: onEditServingsOrGrams
  },
  { title: "Grams (override)", field: "Grams", width: 130, hozAlign: "right",
    editor: "number", editorParams: { min: 0, step: 1 },
    cellEdited: onEditServingsOrGrams
  },

  // Show the “serving definition” (not editable here) — comment these out if you want them hidden
  // { title: "Size", field: "Size", width: 80, hozAlign: "right" },
  // { title: "Units", field: "Units", width: 90 },
  // { title: "Weight (g)", field: "Weight", width: 110, hozAlign: "right" },

  // Nutrients — these show TODAY’S amounts (perServ * scale)
  { title: "Sodium (mg)", field: "perServ.Sodium", width: 120, hozAlign: "right",
    mutator: (_v, _d, row) => fmt0(todayVal(row, "Sodium")) },
  { title: "Potassium", field: "perServ.Potassium", width: 120, hozAlign: "right",
    mutator: (_v, _d, row) => fmt0(todayVal(row, "Potassium")) },
  { title: "Protein (g)", field: "perServ.Protein", width: 110, hozAlign: "right",
    mutator: (_v, _d, row) => fmt1(todayVal(row, "Protein")) },
  { title: "Carbs (g)", field: "perServ.Carbs", width: 110, hozAlign: "right",
    mutator: (_v, _d, row) => fmt1(todayVal(row, "Carbs")) },
  { title: "Fat (g)", field: "perServ.Fat", width: 100, hozAlign: "right",
    mutator: (_v, _d, row) => fmt1(todayVal(row, "Fat")) },
  { title: "Sat Fat (g)", field: "perServ.Sat Fat", width: 120, hozAlign: "right",
    mutator: (_v, _d, row) => fmt1(todayVal(row, "Sat Fat")) },
  { title: "Mono Fat (g)", field: "perServ.Mono Fat", width: 120, hozAlign: "right",
    mutator: (_v, _d, row) => fmt1(todayVal(row, "Mono Fat")) },
  { title: "Poly Fat (g)", field: "perServ.Poly Fat", width: 120, hozAlign: "right",
    mutator: (_v, _d, row) => fmt1(todayVal(row, "Poly Fat")) },
  { title: "Sugar (g)", field: "perServ.Sugar", width: 110, hozAlign: "right",
    mutator: (_v, _d, row) => fmt1(todayVal(row, "Sugar")) },
  { title: "Calcium (mg)", field: "perServ.Calcium", width: 120, hozAlign: "right",
    mutator: (_v, _d, row) => fmt0(todayVal(row, "Calcium")) },
  { title: "Magnesium (mg)", field: "perServ.Magnesium", width: 120, hozAlign: "right",
    mutator: (_v, _d, row) => fmt0(todayVal(row, "Magnesium")) },
  { title: "Iron (mg)", field: "perServ.Iron", width: 110, hozAlign: "right",
    mutator: (_v, _d, row) => fmt1(todayVal(row, "Iron")) },
  { title: "Calories", field: "perServ.Calories", width: 110, hozAlign: "right",
    mutator: (_v, _d, row) => fmt0(todayVal(row, "Calories")) },

  // Sodium % of 1500, with a bar
  { title: "Na % of 1500", field: "_naPct", width: 170, hozAlign: "left",
    headerSort: false, formatter: renderNaPct },
];

/** When user edits Ate Today or Grams override. */
async function onEditServingsOrGrams(cell) {
  const rowData = cell.getRow().getData();

  // Clamp negatives to 0
  if (Number(rowData.Ate) < 0) { rowData.Ate = 0; cell.getRow().update({ Ate: 0 }); }
  if (Number(rowData.Grams) < 0) { rowData.Grams = 0; cell.getRow().update({ Grams: 0 }); }

  // Persist to diary (grams value derived from row state)
  await persistRow(rowData);

  // Force recompute and redraw
  postEditRefresh();
  grid?.redraw(true);
}

/** Initialize the grid on #daily-grid. */
(function init() {
  const mount = $("#daily-grid");
  if (!mount || !window.Tabulator) {
    if (!mount) console.error("daily.js: #daily-grid mount not found");
    if (!window.Tabulator) console.error("daily.js: Tabulator library missing");
    return;
  }

  grid = new Tabulator(mount, {
    data: foods,
    columns: COLS,
    height: "100%",
    layout: "fitData",
    resizableColumnFit: false,
    movableColumns: true,
    selectable: true,
    rowHeight: 28,
    columnDefaults: { headerHozAlign: "left", vertAlign: "middle" },
    index: "fdcId",
  });

  grid.on("tableBuilt", () => {
    // Precompute cache & render initial totals
    postEditRefresh();
  });

  // Also compute totals on data changes (e.g., external)
  grid.on("dataProcessed", postEditRefresh);
})();
