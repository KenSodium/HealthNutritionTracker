// static/app/daily.js
console.log("[DAILY] clean v22 loaded");

const $ = (s, r = document) => r.querySelector(s);
const fmt0 = v => (isFinite(v) ? Math.round(v) : 0);
const fmt1 = v => (isFinite(v) ? Number(v).toFixed(1) : "0.0");

// -------------------- HISTORY API CONFIG --------------------
const __H = window.__HISTORY_API__ || {
  save: "/api/day/save",
  csv:  "/api/history.csv"
};

// -------------------- BASIC TOTALS CALCULATION --------------------
const NA_BUDGET = 1500;
let grid; // optional if using Tabulator elsewhere

function calcTotals() {
  const rows = document.querySelectorAll("#foods-body tr");
  let t = {
    Sodium: 0, Potassium: 0, Protein: 0, Carbs: 0, Fat: 0,
    "Sat Fat": 0, "Mono Fat": 0, "Poly Fat": 0, Sugar: 0,
    Calcium: 0, Magnesium: 0, Iron: 0, Calories: 0
  };
  rows.forEach(tr => {
    const amt = Number(tr.querySelector("input.amount")?.value) || 0;
    if (amt <= 0) return;
    const g = f => Number(tr.dataset[f] || 0) * amt;
    t.Sodium += g("na");
    t.Potassium += g("k");
    t.Protein += g("pro");
    t.Carbs += g("carbs");
    t.Fat += g("fat");
    t["Sat Fat"] += g("sat");
    t["Mono Fat"] += g("mono");
    t["Poly Fat"] += g("poly");
    t.Sugar += g("sugar");
    t.Calcium += g("ca");
    t.Magnesium += g("mg");
    t.Iron += g("iron");
    t.Calories += g("cal");
  });
  return t;
}

// -------------------- RENDER LIVE TOTALS --------------------
function renderAllTotals() {
  const t = calcTotals();
  const tbody = $("#all-totals-body");
  if (!tbody) return;
  const rows = Object.entries(t)
    .map(([k, v]) => `<tr><td>${k}</td><td class="text-end">${fmt0(v)}</td></tr>`)
    .join("");
  tbody.innerHTML = rows;
}

// -------------------- SAVE TO HISTORY --------------------
async function saveToHistory() {
  const btn = $("#btn-save-history");
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = "Saving…";

  const payload = {
    date: new Date().toISOString().slice(0, 10),
    totals: calcTotals()
  };

  try {
    const r = await fetch(__H.save, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error("Save failed: " + r.status);
    btn.classList.remove("btn-success");
    btn.classList.add("btn-secondary");
    btn.textContent = "Saved";

    // ✅ Immediately open a simple HTML view of the history CSV
    window.open(__H.csv, "_blank");

  } catch (err) {
    console.error(err);
    alert("Save failed: " + err.message);
    btn.disabled = false;
    btn.textContent = "Save to History";
  }
}

// -------------------- INITIALIZE --------------------
document.addEventListener("DOMContentLoaded", () => {
  $("#btn-save-history")?.addEventListener("click", saveToHistory);
  // refresh live totals on any input change
  document.querySelectorAll("#foods-body input.amount")
    .forEach(inp => inp.addEventListener("input", renderAllTotals));
  renderAllTotals();
});
