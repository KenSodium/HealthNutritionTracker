// static/app/foods.js
// --- FOODS DIAGNOSTIC BANNER (safe to keep) ---
(function(){
  const scripts = document.querySelectorAll('script[src*="app/foods.js"]').length;
  console.log("%c[FOODS] script loaded", "color:#0b6;font-weight:700",
              { path: location.pathname, scriptsOnPage: scripts });
})();

(function () {
  // ----- Helpers ------------------------------------------------------------
  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const boot = (window.__FOODS_BOOT__ || {});
  const SAVE_URL = boot.saveUrl || "/app/api/foods/save";
console.log("[FOODS] boot", { saveUrl: SAVE_URL, hasBtnSave: !!document.getElementById("btn-save") });

  // Exact column order to match your THEAD and editor inputs
  // key  = canonical nutrient key in storage
  // inputId = the editor input id (note "Calorie" vs "Calories")
  const COLS = [
    { key: 'Calories',   inputId: 'n-Calorie'   },
    { key: 'Protein',    inputId: 'n-Protein'   },
    { key: 'Carbs',      inputId: 'n-Carbs'     },
    { key: 'Fat',        inputId: 'n-Fat'       },
    { key: 'Sat Fat',    inputId: 'n-Sat Fat'   },
    { key: 'Mono Fat',   inputId: 'n-Mono Fat'  },
    { key: 'Poly Fat',   inputId: 'n-Poly Fat'  },
    { key: 'Sugar',      inputId: 'n-Sugar'     },
    { key: 'Sodium',     inputId: 'n-Sodium'    },
    { key: 'Potassium',  inputId: 'n-Potassium' },
    { key: 'Calcium',    inputId: 'n-Calcium'   },
    { key: 'Magnesium',  inputId: 'n-Magnesium' },
    { key: 'Iron',       inputId: 'n-Iron'      }
  ];

  // Normalizer: make every item look like {id,name,brand,nutrients:{key->number}}
  function normalizeFood(f) {
    if (!f || typeof f !== 'object') return f;
    const name  = f.name || f.food || f.description || '';
    const brand = f.brand || f.brandName || '';
    const id    = f.id || f.fdcId || null;

    // accept either per100 or nutrients; build a clean bag matching COLS keys
    const bagRaw = f.nutrients || f.per100 || {};
    const bag = {};
    for (const {key} of COLS) {
      const low = key.toLowerCase();
      bag[key] = bagRaw[key] ?? bagRaw[low] ?? null;
    }
    return { id, name, brand, nutrients: bag };
  }

  // Initial list
  let MY = Array.isArray(boot.myFoods) ? boot.myFoods.map(normalizeFood) : [];

  const filterInput = $('#find-food') || $('#foods-filter');
  const tbody = $('#foods-body');

  function fmtNum(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    const n = Number(v);
    return Math.abs(n) >= 100 ? Math.round(n).toString() : n.toFixed(1);
  }

  function getNut(food, key) {
    const n = (food && food.nutrients) || {};
    return n[key] ?? n[key.toLowerCase()] ?? null;
  }

  // ----- Render -------------------------------------------------------------
  function renderTable(list) {
    if (!tbody) return;

    const rows = list.map((f, idx) => {
      const cells = [];

      // 1) Food name + (optional) brand
      const title = f.name || '—';
      cells.push(
        `<td>
           <div class="fw-600">${escapeHtml(title)}</div>
           ${f.brand ? `<div class="text-muted small">${escapeHtml(f.brand)}</div>` : ''}
         </td>`
      );

      // 2) Nutrients in exact column order
      for (const {key} of COLS) {
        cells.push(`<td class="text-end">${fmtNum(getNut(f, key))}</td>`);
      }

      // 3) Actions
      cells.push(
        `<td class="text-end">
           <button class="btn btn-sm btn-outline edit-row" data-idx="${idx}">Edit</button>
         </td>`
      );

      return `<tr data-idx="${idx}">${cells.join('')}</tr>`;
    });

    tbody.innerHTML = rows.join('');

    // Wire “Edit” buttons & row clicks
    $$('.edit-row', tbody).forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = Number(btn.getAttribute('data-idx'));
        loadIntoEditor(MY[idx]);
      });
    });
    $$('tr', tbody).forEach(tr => {
      tr.addEventListener('click', () => {
        const idx = Number(tr.getAttribute('data-idx'));
        loadIntoEditor(MY[idx]);
      });
    });
  }

  // ----- Editor fill --------------------------------------------------------
  function setVal(id, v) {
    const el = document.getElementById(id);
    if (el) el.value = (v ?? '');
  }
  function setNutrient(inputId, v) {
    const el = document.querySelector(`[id="${CSS.escape(inputId)}"]`);
    if (el) el.value = (v ?? '');
  }

  function loadIntoEditor(food) {
    if (!food) return;
    setVal('food-id',   food.id || '');
    setVal('food-name', food.name || '');

    // (brand / serving inputs are parked for later)
    setVal('brand',             food.brand || '');
    setVal('serving-amount',    food.servingAmount  || '');
    setVal('serving-grams',     food.servingGrams   || '');
    setVal('pref-unit-grams',   food.prefUnitGrams  || '');
    const unit = $('#pref-unit'); if (unit) unit.value = food.prefUnit || 'g';

    for (const {key, inputId} of COLS) {
      setNutrient(inputId, getNut(food, key));
    }

    const fn = $('#food-name'); if (fn) fn.focus();
  }

  // ----- Filter -------------------------------------------------------------
  function applyFilter() {
    const q = (filterInput && filterInput.value || '').trim().toLowerCase();
    if (!q) return renderTable(MY);
    const list = MY.filter(f => {
      const hay = (f.name || '').toLowerCase() + ' ' + (f.brand || '').toLowerCase();
      return hay.includes(q);
    });
    renderTable(list);
  }
  if (filterInput) filterInput.addEventListener('input', applyFilter);

  // ----- Create / Save ------------------------------------------------------
  // Support either id used in your HTML
  const btnNew  = $('#btn-new') || $('#btn-create');
  if (btnNew) {
    btnNew.addEventListener('click', () => {
      setVal('food-id', '');
      setVal('food-name', '');
      setVal('brand', '');
      setVal('serving-amount', '');
      setVal('serving-grams', '');
      setVal('pref-unit-grams', '');
      const unit = $('#pref-unit'); if (unit) unit.value = 'g';
      for (const {inputId} of COLS) setNutrient(inputId, '');
      const fn = $('#food-name'); if (fn) fn.focus();
    });
  }

  const btnSave = $('#btn-save');
  if (btnSave) {
    btnSave.addEventListener('click', async () => {
      try {
        btnSave.disabled = true;

        const payload = buildPayloadFromEditor();
        const res = await fetch(SAVE_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (!res.ok) {
          const text = await res.text();
          throw new Error(`Save failed ${res.status}: ${text}`);
        }

        // Expect: {"ok": true, "my_food_list": [...]}
        const data = await res.json();
        if (data && Array.isArray(data.my_food_list)) {
          MY = data.my_food_list.map(normalizeFood);
        } else if (data && data.saved) {
          upsertLocal(normalizeFood(data.saved));
        }
        applyFilter(); // re-render now (no need to navigate away)
      } catch (err) {
        console.error(err);
        alert('Save failed. See console for details.');
      } finally {
        btnSave.disabled = false;
      }
    });
  }

  function buildPayloadFromEditor() {
    const id    = $('#food-id')?.value || null;
    const name  = $('#food-name')?.value?.trim();
    const brand = $('#brand')?.value?.trim();

    // Nutrients from the editor, in the same order
    const nutrients = {};
    for (const {key, inputId} of COLS) {
      const el = document.querySelector(`[id="${CSS.escape(inputId)}"]`);
      const v = el ? parseFloat(el.value || '') : NaN;
      if (!isNaN(v)) nutrients[key] = v;
    }

    // Server keys it expects (serving/pref optional for now)
    const servingGrams  = $('#serving-grams')?.value?.trim();
    const prefUnit      = $('#pref-unit')?.value || '';
    const prefUnitGrams = $('#pref-unit-grams')?.value?.trim();

    const out = {
      id: id || undefined,     // include for edits/renames
      name,
      brand,
      nutrients,
      serving_grams:   servingGrams ? parseFloat(servingGrams) : null,
      pref_unit:       (prefUnit || 'g').toLowerCase(),
      pref_unit_grams: prefUnitGrams ? parseFloat(prefUnitGrams) : null
    };

    const servingAmount = $('#serving-amount')?.value?.trim();
    if (servingAmount) out.serving_amount = servingAmount;

    return out;
  }

  function upsertLocal(saved) {
    if (!saved) return;
    let idx = -1;
    if (saved.id != null) idx = MY.findIndex(f => f.id == saved.id);
    if (idx < 0 && saved.name) {
      idx = MY.findIndex(f => (f.name || '').toLowerCase() === saved.name.toLowerCase());
    }
    if (idx >= 0) MY[idx] = saved; else MY.push(saved);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c] || c));
  }

  // Initial paint
  renderTable(MY);
})();
