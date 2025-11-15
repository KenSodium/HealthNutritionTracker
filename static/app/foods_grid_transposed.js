console.log("[TGRID] foods_grid_transposed.js v5");

// ---- Config -------------------------------------------------
const SHOW_UNITS = false;         // set true if you want the Units column visible
let foodCols = ["Food 1"];        // starting food column(s)

// ---- Rows = metrics -----------------------------------------
const METRICS = [
  ["Serving Size", "define_serving_size", "Define the Serving Size", ""],
  ["Serving Size", "num_units", "Number of Units", ""],
  ["Serving Size", "unit_name", "Name of Units", ""],
  ["Serving Size", "serving_weight_g", "Weight of Serving", "g"],
  ["Nutrients", "enter_nutrients", "Enter the Nutrients", ""],
  ["Nutrients", "Sodium", "Sodium", "mg"],
  ["Nutrients", "Potassium", "Potassium", "mg"],
  ["Nutrients", "Protein", "Protein", "g"],
  ["Nutrients", "Carbs", "Carbs", "g"],
  ["Nutrients", "Fat", "Fat", "g"],
  ["Nutrients", "Sat_Fat", "Sat Fat", "g"],
  ["Nutrients", "Mono_Fat", "Mono Fat", "g"],
  ["Nutrients", "Poly_Fat", "Poly Fat", "g"],
  ["Nutrients", "Sugar", "Sugar", "g"],
  ["Nutrients", "Calcium", "Calcium", "mg"],
  ["Nutrients", "Magnesium", "Magnesium", "mg"],
  ["Nutrients", "Iron", "Iron", "mg"],
  ["Nutrients", "Calories", "Calories", "kcal"],
];

const ROWS = METRICS.map(([section, key, label, units]) => ({ id: key, section, metric: label, units }));

// ---- Helpers ------------------------------------------------
const slug = s => String(s || "").trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");

function ensureFoodFields() {
  ROWS.forEach(r => {
    foodCols.forEach(name => {
      const f = `food__${slug(name)}`;
      if (!(f in r)) r[f] = null;
    });
  });
}

function buildColumns() {
  const cols = [
    { title: "Metric", field: "metric", frozen: true, width: 240, headerSort: true, hozAlign: "left" },
  ];
  if (SHOW_UNITS) cols.push({ title: "Units", field: "units", frozen: true, width: 70, headerSort: false, hozAlign: "center" });

  const w = parseInt(document.querySelector("#colw")?.value || "130", 10);
  foodCols.forEach(name => {
    cols.push({
      title: name,
      field: `food__${slug(name)}`,
      width: w, editor: "number", hozAlign: "right", headerSort: false,
    });
  });
  return cols;
}

// ---- Grid ---------------------------------------------------
let grid;

function buildGrid() {
  ensureFoodFields();
  grid = new Tabulator("#foods-grid-transposed", {
    data: ROWS,
    columns: buildColumns(),
    layout: "fitDataFill",
    height: "100%",
    selectable: false,
    index: "id",
    reactiveData: true,
    columnDefaults: { headerHozAlign: "left", vertAlign: "middle" },
    rowHeight: 30,
    rowFormatter: row => {
      const d = row.getData();

      // Apply custom formatting for the "Define the Serving Size" row
      if (d.section === "Serving Size" && d.id === "define_serving_size") {
        const element = row.getElement();
        const cell = element.querySelector('.tabulator-cell');

        cell.style.textIndent = "0px"; // No indentation
        cell.style.backgroundColor = "#ffffff"; // White background
        cell.style.fontWeight = "bold"; // Bold text
        cell.style.fontSize = "18px"; // Larger font size
        cell.style.borderBottom = "2px solid #000"; // Add a black bottom border
      }

      // Apply custom formatting for all other "Serving Size" rows
      if (d.section === "Serving Size" && d.id !== "define_serving_size") {
        const element = row.getElement();
        const cell = element.querySelector('.tabulator-cell');

        cell.style.textIndent = "30px"; // Indentation for the text (moves the text to the right)
        cell.style.backgroundColor = "#e3f2fd"; // Light blue background
        cell.style.fontWeight = "normal"; // Normal weight (not bold)
        cell.style.fontSize = "16px"; // Bigger font size
        cell.style.borderBottom = "2px solid #000"; // Add a black bottom border
      }

      // Apply custom formatting for the "Enter the Nutrients" row
      if (d.section === "Nutrients" && d.id === "enter_nutrients") {
        const element = row.getElement();
        const cell = element.querySelector('.tabulator-cell');

        cell.style.textIndent = "0px"; // No indentation
        cell.style.backgroundColor = "#ffccbc"; // Light orange background
        cell.style.fontWeight = "bold"; // Bold text
        cell.style.fontSize = "18px"; // Larger font size
      }

      // Apply custom formatting for all "Nutrients" rows except "Enter the Nutrients"
      if (d.section === "Nutrients" && d.id !== "enter_nutrients") {
        const element = row.getElement();
        const cell = element.querySelector('.tabulator-cell');

        cell.style.textIndent = "40px"; // Indentation for the text (moves the text to the right)
        cell.style.backgroundColor = "#e8f5e9"; // Light green background
        cell.style.fontWeight = "normal"; // Normal weight (not bold)
        cell.style.fontSize = "16px"; // Bigger font size
      }
    },
    tableBuilt: function () {
      wireToolbar();
      wireSearch();
      wireWidthSlider();
      refreshFoodPicker();
      drawSuperheaders();
      addCheckboxes(); // Call this function to add checkboxes after the table is built
    }
  });
}

// ---- Add Food Column --------------------------
function addFoodColumn() {
  const label = `Food ${foodCols.length + 1}`;
  foodCols.push(label); ensureFoodFields();
  grid.addColumn({
    title: label, field: `food__${slug(label)}`,
    width: parseInt(document.querySelector("#colw")?.value || "130", 10),
    editor: "number", hozAlign: "right", headerSort: false
  }, false, "end");
  refreshFoodPicker(); requestAnimationFrame(drawSuperheaders);
}

// ---- Add Checkboxes for Columns --------------------------
function addCheckboxes() {
  const checkboxesContainer = document.getElementById("food-column-checkboxes");
  checkboxesContainer.innerHTML = ""; // Clear the previous checkboxes

  foodCols.forEach((food, index) => {
    const checkboxHTML = `
      <div class="form-check">
        <input type="checkbox" class="form-check-input" id="food${index + 1}" name="food-column" value="Food ${index + 1}">
        <label class="form-check-label" for="food${index + 1}">${food}</label>
      </div>
    `;
    checkboxesContainer.innerHTML += checkboxHTML;
  });
}

// ---- Toolbar -----------------------------------------------
function wireToolbar() {
  document.getElementById("btn-add-food")?.addEventListener("click", addFoodColumn);
  document.getElementById("btn-del-food")?.addEventListener("click", deleteSelectedFood);
  document.getElementById("btn-export")?.addEventListener("click", () => grid.download("csv", "foods_grid_transposed.csv"));
}

document.addEventListener("DOMContentLoaded", buildGrid);
