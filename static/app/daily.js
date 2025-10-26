// static/app/daily.js
(function () {
  // -------- boot & dom ----------
  const boot   = window.__DAILY_BOOT__ || { date: null, myFoods: [] };
  const foods  = Array.isArray(boot.myFoods) ? boot.myFoods.slice() : [];
  const dayIso = boot.date;

  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const tbodyFoods   = $("#foods-body");
  const tbodyEntries = $("#entries-body");
  const totalsPanel  = $("#totals-panel");
  const filter       = $("#foods-filter");
  const dayLabel     = $("#day-label");
  const dayLabel2    = $("#day-label-2");
  const picker       = $("#day-picker");
  const btnPrev      = $("#btn-prev");
  const btnNext      = $("#btn-next");

  // -------- helpers ----------
  function getPer100(food, key) {
    const p   = (food && food.per100)    || {};
    const n   = (food && food.nutrients) || {};
    const low = key.toLowerCase();
    return p[key] ?? p[low] ?? n[key] ?? n[low] ?? null;
  }
  function fmtNum(v) {
    if (v == null || Number.isNaN(v)) return "—";
    const n = Number(v);
    return Math.abs(n) >= 100 ? String(Math.round(n)) : n.toFixed(1);
  }
  function fmt(v, digits = 0) {
    if (v == null || isNaN(v)) return "0";
    return Number(v).toFixed(digits);
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c] || c));
  }

  // -------- totals panel ----------
  function renderTotals(totals) {
    const na   = totals.Sodium    || 0;
    const k    = totals.Potassium || 0;
    const prot = totals.Protein   || 0;
    const cal  = totals.Calories  || 0;

    const naGoal = 1500, kGoal = 3400, protGoal = 65, calGoal = 2000;
    const pct = (v, g) => Math.max(0, Math.min(100, Math.round((v / g) * 100)));

    totalsPanel.innerHTML = `
      <div class="mb-2">
        <div class="d-flex justify-content-between"><div>Sodium</div><div>${fmt(na)} / ${naGoal} mg</div></div>
        <div class="progress"><div class="progress-bar" style="width:${pct(na, naGoal)}%"></div></div>
      </div>
      <div class="mb-2">
        <div class="d-flex justify-content-between"><div>Potassium</div><div>${fmt(k)} / ${kGoal} mg</div></div>
        <div class="progress"><div class="progress-bar bg-warning" style="width:${pct(k, kGoal)}%"></div></div>
      </div>
      <div class="mb-2">
        <div class="d-flex justify-content-between"><div>Protein</div><div>${fmt(prot)} / ${protGoal} g</div></div>
        <div class="progress"><div class="progress-bar bg-success" style="width:${pct(prot, protGoal)}%"></div></div>
      </div>
      <div>
        <div class="d-flex justify-content-between"><div>Calories</div><div>${fmt(cal)} / ${calGoal}</div></div>
        <div class="progress"><div class="progress-bar bg-secondary" style="width:${pct(cal, calGoal)}%"></div></div>
      </div>
    `;
  }

  // -------- API ----------
  async function api(method, url, payload) {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: payload ? JSON.stringify(payload) : undefined
    });
    if (!res.ok) throw new Error(`${method} ${url} → ${res.status}`);
    return await res.json();
  }

  // -------- entries (center table) ----------
  async function reloadEntries() {
    const data = await api("GET", `/app/api/diary?date=${encodeURIComponent(picker.value)}`);

    tbodyEntries.innerHTML = "";
    data.entries.forEach(e => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(e.description)}</td>
        <td class="text-end">
          <input type="number" min="0" step="1" class="form-control form-control-sm grams" value="${fmt(e.grams,0)}" style="width:100px">
        </td>
        <td class="text-end">${fmt(e.na)}</td>
        <td class="text-end">${fmt(e.k)}</td>
        <td class="text-end">
          <button class="btn btn-link text-danger p-0 del" title="Remove">🗑️</button>
        </td>
      `;

      tr.querySelector(".grams").addEventListener("change", async (ev) => {
        const grams = parseFloat(ev.target.value || "0");
        await api("POST", "/app/api/diary/qty", { date: picker.value, fdcId: e.fdcId, grams });
        await reloadEntries();
      });

      tr.querySelector(".del").addEventListener("click", async () => {
        await api("POST", "/app/api/diary/remove", { date: picker.value, fdcId: e.fdcId });
        await reloadEntries();
      });

      tbodyEntries.appendChild(tr);
    });

    renderTotals(data.totals || {});
  }

  // -------- My Foods (left table) ----------
  function renderFoods(list) {
    tbodyFoods.innerHTML = "";
    list.forEach(f => {
      const desc = f.description || f.name || f.food || String(f.fdcId || "");
      const na   = getPer100(f, "Sodium");
      const k    = getPer100(f, "Potassium");
      const fdc  = String(f.fdcId || f.id || desc); // tolerate custom items

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(desc)}</td>
        <td class="text-end">${fmtNum(na)}</td>
        <td class="text-end">${fmtNum(k)}</td>
        <td class="text-end">
          <button class="btn btn-sm btn-primary add">+</button>
        </td>
      `;

      tr.querySelector(".add").addEventListener("click", async () => {
        await api("POST", "/app/api/diary/add", {
          date: picker.value,
          fdcId: fdc,
          grams: 100
        });
        await reloadEntries();
      });

      tbodyFoods.appendChild(tr);
    });
  }

  function applyFilter() {
    const q = (filter && filter.value || "").trim().toLowerCase();
    if (!q) { renderFoods(foods); return; }
    const out = foods.filter(f => {
      const name = (f.description || f.name || f.food || "").toLowerCase();
      return name.includes(q);
    });
    renderFoods(out);
  }

  // -------- sorting for My Foods ----------
  let sortState = { key: 'description', dir: 1 }; // 1 asc, -1 desc

  function sortFoodsBy(key, numeric=false) {
    foods.sort((a, b) => {
      const av = (key === 'description')
        ? (a.description || a.name || a.food || '')
        : (getPer100(a, key) || 0);
      const bv = (key === 'description')
        ? (b.description || b.name || b.food || '')
        : (getPer100(b, key) || 0);

      if (numeric) return sortState.dir * (Number(av) - Number(bv));
      return sortState.dir * String(av).localeCompare(String(bv));
    });
  }

  function wireHeaderSort() {
    const ths = $$('#tbl-foods thead th');
    ths.forEach(th => {
      const mode = th.getAttribute('data-sort'); // "text" or "num"
      if (!mode) return;
      th.style.cursor = 'pointer';
      th.addEventListener('click', () => {
        const label = th.textContent.trim().toLowerCase();
        let key = 'description', numeric = false;
        if (label.startsWith('na')) { key = 'Sodium'; numeric = true; }
        else if (label.startsWith('k')) { key = 'Potassium'; numeric = true; }

        if (sortState.key === key) sortState.dir *= -1;
        else { sortState.key = key; sortState.dir = 1; }

        sortFoodsBy(key, numeric);
        applyFilter();
      });
    });

    // initial sort by description
    sortFoodsBy('description', false);
  }

  // -------- keep foods fresh (pull from session) ----------
  async function loadFoodsFromApi() {
    try {
      const res = await fetch("/app/api/foods");
      if (!res.ok) throw new Error("foods api " + res.status);
      const list = await res.json(); // session["my_food_list"]
      foods.length = 0;
      list.forEach(f => foods.push(f));
      applyFilter(); // re-render left table with the freshest data
    } catch (e) {
      console.warn("Failed to refresh foods list:", e);
    }
  }

  // -------- date controls ----------
  function setDate(dIso) {
    if (picker)    picker.value = dIso;
    if (dayLabel)  dayLabel.textContent = dIso;
    if (dayLabel2) dayLabel2.textContent = dIso;
  }
  function stepDate(days) {
    const d = new Date(picker.value);
    d.setDate(d.getDate() + days);
    setDate(d.toISOString().slice(0,10));
    reloadEntries();
  }

  // -------- init ----------
  setDate(dayIso);
  wireHeaderSort();
  renderFoods(foods);
  applyFilter();
  reloadEntries();
  loadFoodsFromApi(); // <- pulls the latest My Foods from session

  if (filter)  filter.addEventListener("input", applyFilter);
  if (btnPrev) btnPrev.addEventListener("click", () => stepDate(-1));
  if (btnNext) btnNext.addEventListener("click", () => stepDate(+1));
})();
