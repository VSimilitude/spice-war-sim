# Web Interface — Design

## Overview

A client-side web application that runs the Spice War simulation entirely in the browser via Pyodide. Two new components: a Python bridge module (`src/spice_war/web/bridge.py`) that wraps the existing simulation API with dict-in/dict-out functions, and a static web app (`web/`) with vanilla JS that calls the bridge through Pyodide. No build step, no backend server. The bridge bypasses the file-path-based `load_state()` and `load_model_config()` by constructing `Alliance`/`EventConfig` objects directly from dicts and calling `_check_model_references()` for validation.

---

## 1. Python Bridge Layer

### New file: `src/spice_war/web/bridge.py`

All functions accept and return plain dicts (JSON-serializable). Every public function wraps its body in a try/except that catches any exception and returns `{"ok": false, "error": str(e)}`.

#### Imports

```python
from __future__ import annotations

import csv
import io
import json

from spice_war.game.monte_carlo import MonteCarloResult, run_monte_carlo
from spice_war.game.simulator import simulate_war
from spice_war.models.configurable import ConfigurableModel
from spice_war.utils.data_structures import Alliance, EventConfig
from spice_war.utils.validation import ValidationError, _check_model_references
```

#### `_build_alliances(state_dict: dict) -> list[Alliance]`

Private helper that constructs Alliance objects from a state dict, replicating the field mapping from `load_state()` without file I/O.

```python
def _build_alliances(state_dict: dict) -> list[Alliance]:
    alliances = []
    for i, raw in enumerate(state_dict.get("alliances", [])):
        required = ["alliance_id", "faction", "power", "starting_spice", "daily_rate"]
        missing = [k for k in required if k not in raw]
        if missing:
            raise ValidationError(
                f"Alliance #{i + 1}: missing required fields: {missing}"
            )
        if raw["alliance_id"] == "*":
            raise ValidationError(
                f"Alliance #{i + 1}: '*' is reserved and cannot be used "
                f"as an alliance_id"
            )
        alliances.append(
            Alliance(
                alliance_id=raw["alliance_id"],
                faction=raw["faction"],
                power=raw["power"],
                starting_spice=raw["starting_spice"],
                daily_spice_rate=raw["daily_rate"],
                name=raw.get("name"),
                server=raw.get("server"),
            )
        )
    return alliances
```

This mirrors the construction logic in `validation.load_state()` (lines ~45–75), including the `daily_rate` → `daily_spice_rate` rename and the `"*"` reservation check. The bridge does not duplicate the full validation — it relies on `_check_model_references()` for cross-reference checks and validates the minimal structural requirements inline.

#### `_build_schedule(state_dict: dict) -> list[EventConfig]`

```python
def _build_schedule(state_dict: dict) -> list[EventConfig]:
    schedule = []
    for i, raw in enumerate(state_dict.get("event_schedule", [])):
        required = ["attacker_faction", "day", "days_before"]
        missing = [k for k in required if k not in raw]
        if missing:
            raise ValidationError(
                f"Event #{i + 1}: missing required fields: {missing}"
            )
        day = raw["day"].lower()
        if day not in ("wednesday", "saturday"):
            raise ValidationError(
                f"Event #{i + 1}: day must be 'wednesday' or 'saturday', "
                f"got '{raw['day']}'"
            )
        schedule.append(
            EventConfig(
                attacker_faction=raw["attacker_faction"],
                day=day,
                days_before=raw["days_before"],
            )
        )
    return schedule
```

#### `_validate_state_structure(state_dict: dict) -> None`

Validates structural requirements that `load_state()` checks but `_check_model_references()` does not.

```python
def _validate_state_structure(state_dict: dict) -> None:
    if not isinstance(state_dict, dict):
        raise ValidationError("State must be a JSON object")
    if "alliances" not in state_dict:
        raise ValidationError("State must contain 'alliances'")
    if "event_schedule" not in state_dict:
        raise ValidationError("State must contain 'event_schedule'")
    if not state_dict["alliances"]:
        raise ValidationError("State must contain at least one alliance")
    if not state_dict["event_schedule"]:
        raise ValidationError("State must contain at least one event")

    # Check exactly two factions
    factions = {a["faction"] for a in state_dict["alliances"] if "faction" in a}
    if len(factions) != 2:
        raise ValidationError(
            f"State must contain exactly 2 factions, found {len(factions)}: "
            f"{sorted(factions)}"
        )

    # Check event attacker_factions reference valid factions
    for i, event in enumerate(state_dict["event_schedule"]):
        if "attacker_faction" in event and event["attacker_faction"] not in factions:
            raise ValidationError(
                f"Event #{i + 1}: attacker_faction '{event['attacker_faction']}' "
                f"is not one of the state's factions: {sorted(factions)}"
            )

    # Check unique alliance IDs
    ids = [a.get("alliance_id") for a in state_dict["alliances"]]
    dupes = [aid for aid in ids if ids.count(aid) > 1]
    if dupes:
        raise ValidationError(
            f"Duplicate alliance_id(s): {sorted(set(dupes))}"
        )
```

#### `_validate_model_dict(model_dict: dict, alliances: list[Alliance]) -> None`

Wraps `_check_model_references()` with the inputs it needs.

```python
_ALLOWED_MODEL_KEYS = {
    "random_seed",
    "battle_outcome_matrix",
    "event_targets",
    "event_reinforcements",
    "damage_weights",
    "targeting_strategy",
    "default_targets",
    "faction_targeting_strategy",
}

def _validate_model_dict(model_dict: dict, alliances: list[Alliance]) -> None:
    if not isinstance(model_dict, dict):
        raise ValidationError("Model config must be a JSON object")

    unknown = set(model_dict.keys()) - _ALLOWED_MODEL_KEYS
    if unknown:
        raise ValidationError(f"Unknown model config keys: {sorted(unknown)}")

    alliance_ids = {a.alliance_id for a in alliances}
    faction_ids = {a.faction for a in alliances}
    _check_model_references(model_dict, alliance_ids, faction_ids)
```

This replicates the key-checking and delegation logic from `load_model_config()` (lines ~95–115 of `validation.py`) without file I/O.

#### `get_default_state() -> dict`

```python
def get_default_state() -> dict:
    return {
        "alliances": [
            {
                "alliance_id": "Alpha",
                "faction": "Sun",
                "power": 15.0,
                "starting_spice": 2_000_000,
                "daily_rate": 50_000,
            },
            {
                "alliance_id": "Bravo",
                "faction": "Sun",
                "power": 10.0,
                "starting_spice": 1_500_000,
                "daily_rate": 40_000,
            },
            {
                "alliance_id": "Charlie",
                "faction": "Moon",
                "power": 12.0,
                "starting_spice": 1_800_000,
                "daily_rate": 45_000,
            },
            {
                "alliance_id": "Delta",
                "faction": "Moon",
                "power": 8.0,
                "starting_spice": 1_200_000,
                "daily_rate": 35_000,
            },
        ],
        "event_schedule": [
            {"attacker_faction": "Sun", "day": "wednesday", "days_before": 21},
            {"attacker_faction": "Moon", "day": "saturday", "days_before": 18},
            {"attacker_faction": "Sun", "day": "wednesday", "days_before": 14},
            {"attacker_faction": "Moon", "day": "saturday", "days_before": 11},
        ],
    }
```

Four alliances, two factions, four events — enough to demonstrate the system without being overwhelming.

#### `get_default_model_config() -> dict`

```python
def get_default_model_config() -> dict:
    return {}
```

Empty dict = all heuristic defaults.

#### `validate_state(state_dict: dict) -> dict`

```python
def validate_state(state_dict: dict) -> dict:
    try:
        _validate_state_structure(state_dict)
        alliances = _build_alliances(state_dict)
        schedule = _build_schedule(state_dict)
        return {
            "ok": True,
            "alliances": [
                {
                    "alliance_id": a.alliance_id,
                    "faction": a.faction,
                    "power": a.power,
                    "starting_spice": a.starting_spice,
                    "daily_rate": a.daily_spice_rate,
                }
                for a in alliances
            ],
            "event_schedule": [
                {
                    "event_number": i + 1,
                    "attacker_faction": e.attacker_faction,
                    "day": e.day,
                    "days_before": e.days_before,
                }
                for i, e in enumerate(schedule)
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

#### `validate_model_config(model_dict: dict, state_dict: dict) -> dict`

```python
def validate_model_config(model_dict: dict, state_dict: dict) -> dict:
    try:
        alliances = _build_alliances(state_dict)
        _validate_model_dict(model_dict, alliances)
        return {"ok": True, "config": model_dict}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

Validates state first (to get alliance objects), then validates model against it. If state is invalid, the error bubbles up — the UI should validate state before calling this.

#### `run_single(state_dict: dict, model_dict: dict, seed: int | None = None) -> dict`

```python
def run_single(state_dict: dict, model_dict: dict, seed: int | None = None) -> dict:
    try:
        _validate_state_structure(state_dict)
        alliances = _build_alliances(state_dict)
        schedule = _build_schedule(state_dict)
        _validate_model_dict(model_dict, alliances)

        config = dict(model_dict)
        if seed is not None:
            config["random_seed"] = seed
        elif "random_seed" not in config:
            config["random_seed"] = 0

        model = ConfigurableModel(config, alliances)
        result = simulate_war(alliances, schedule, model)

        return {
            "ok": True,
            "seed": config["random_seed"],
            "final_spice": result["final_spice"],
            "rankings": result["rankings"],
            "event_history": result["event_history"],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

`simulate_war()` already returns a JSON-serializable dict with `final_spice`, `rankings`, and `event_history` — no conversion needed.

#### `run_monte_carlo(state_dict: dict, model_dict: dict, num_iterations: int = 1000, base_seed: int = 0) -> dict`

```python
def run_monte_carlo(
    state_dict: dict,
    model_dict: dict,
    num_iterations: int = 1000,
    base_seed: int = 0,
) -> dict:
    try:
        _validate_state_structure(state_dict)
        alliances = _build_alliances(state_dict)
        schedule = _build_schedule(state_dict)
        _validate_model_dict(model_dict, alliances)

        result = run_monte_carlo_impl(
            alliances, schedule, model_dict,
            num_iterations=num_iterations,
            base_seed=base_seed,
        )

        return {
            "ok": True,
            "num_iterations": result.num_iterations,
            "base_seed": result.base_seed,
            "tier_distribution": {
                aid: {
                    str(tier): frac
                    for tier, frac in result.tier_distribution(aid).items()
                }
                for aid in result.tier_counts
            },
            "spice_stats": {
                aid: result.spice_stats(aid)
                for aid in result.tier_counts
            },
            "raw_results": result.per_iteration,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

Note the import alias to avoid name collision with the bridge function itself:

```python
from spice_war.game.monte_carlo import run_monte_carlo as run_monte_carlo_impl
```

The `MonteCarloResult` is serialized manually using its `.tier_distribution()`, `.spice_stats()`, and `.per_iteration` accessors — the same pattern used in `scripts/run_monte_carlo.py`'s `_write_json()`.

#### `import_csv(csv_text: str) -> dict`

```python
def import_csv(csv_text: str) -> dict:
    try:
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        config = import_from_csv(rows)
        return {"ok": True, "config": config}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

`import_from_csv()` from `sheets/importer.py` already accepts `list[list[str]]` — the bridge just converts the raw CSV text to rows via `csv.reader`.

#### `generate_template_csv(state_dict: dict, top_n: int = 6) -> dict`

```python
def generate_template_csv(state_dict: dict, top_n: int = 6) -> dict:
    try:
        alliances = _build_alliances(state_dict)
        schedule = _build_schedule(state_dict)
        rows = generate_template(alliances, schedule, top_n=top_n)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(rows)
        return {"ok": True, "csv": output.getvalue()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

`generate_template()` from `sheets/template.py` returns `list[list[str]]`. The bridge serializes to a CSV string for download in the browser.

### New file: `src/spice_war/web/__init__.py`

Empty file to make `web` a package.

---

## 2. Pyodide Integration

### New file: `web/js/pyodide-loader.js`

Handles Pyodide initialization, Python package loading, and JS↔Python bridge calls.

#### Initialization

```javascript
let pyodide = null;
let bridgeReady = false;

async function initPyodide(onProgress) {
    onProgress("Downloading Python runtime...");
    pyodide = await loadPyodide({
        indexURL: "https://cdn.jsdelivr.net/pyodide/v0.27.4/full/",
    });

    onProgress("Loading simulation engine...");
    // Load the spice_war package from bundled zip
    await pyodide.loadPackage("micropip");
    const micropip = pyodide.pyimport("micropip");
    await micropip.install("file:///python/spice_war.zip");

    onProgress("Initializing bridge...");
    pyodide.runPython(`
        from spice_war.web import bridge
    `);

    bridgeReady = true;
    onProgress("Ready");
}
```

The `loadPyodide` global is loaded via a `<script>` tag in `index.html` pointing at the Pyodide CDN. The `spice_war` package is bundled as a zip (see Section 4 — Packaging).

**Alternative loading approach (no micropip):** If the zip-install route proves problematic, Pyodide's `pyodide.FS` API can unpack the package directly:

```javascript
// Alternative: unpack source files directly into Pyodide's filesystem
const response = await fetch("python/spice_war.zip");
const zipData = await response.arrayBuffer();
pyodide.unpackArchive(zipData, "zip", { extractDir: "/lib/python3.12/site-packages/" });
```

This avoids the micropip dependency entirely. Both approaches are valid — the design uses `unpackArchive` as the primary approach since it's simpler and doesn't require micropip.

```javascript
async function initPyodide(onProgress) {
    onProgress("Downloading Python runtime...");
    pyodide = await loadPyodide({
        indexURL: "https://cdn.jsdelivr.net/pyodide/v0.27.4/full/",
    });

    onProgress("Loading simulation engine...");
    const response = await fetch("python/spice_war.zip");
    const zipData = await response.arrayBuffer();
    pyodide.unpackArchive(zipData, "zip", {
        extractDir: "/lib/python3.12/site-packages/",
    });

    onProgress("Initializing bridge...");
    pyodide.runPython("from spice_war.web import bridge");

    bridgeReady = true;
    onProgress("Ready");
}
```

#### Bridge call wrapper

```javascript
function callBridge(funcName, ...args) {
    if (!bridgeReady) {
        return { ok: false, error: "Python runtime not ready" };
    }

    const jsonArgs = args.map(a => JSON.stringify(a));
    const argStr = jsonArgs.map(a => `json.loads('${a.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}')`).join(", ");

    const resultJson = pyodide.runPython(`
        import json
        json.dumps(bridge.${funcName}(${argStr}))
    `);

    return JSON.parse(resultJson);
}
```

All inputs are serialized as JSON strings in JS, deserialized in Python via `json.loads()`, and results are returned via `json.dumps()` → `JSON.parse()`. This avoids Pyodide's proxy object overhead and keeps the boundary clean.

However, this string-escaping approach is fragile with nested quotes. A more robust alternative uses Pyodide's `toPy()` conversion:

```javascript
function callBridge(funcName, ...args) {
    if (!bridgeReady) {
        return { ok: false, error: "Python runtime not ready" };
    }

    // Set args as a JSON string in Python, then parse there
    const argsJson = JSON.stringify(args);
    pyodide.globals.set("_bridge_args_json", argsJson);

    const resultJson = pyodide.runPython(`
import json
_bridge_args = json.loads(_bridge_args_json)
json.dumps(bridge.${funcName}(*_bridge_args))
`);

    return JSON.parse(resultJson);
}
```

This passes the entire args array as a single JSON string, avoiding any escaping issues. The Python side deserializes once and unpacks with `*_bridge_args`.

#### Async wrapper

Bridge calls are synchronous (Pyodide runs Python synchronously on the main thread), but Monte Carlo with 1000 iterations may take a few hundred milliseconds. To keep the UI responsive, wrap calls in a microtask:

```javascript
async function callBridgeAsync(funcName, ...args) {
    // Yield to the event loop so the UI can update (show spinner)
    await new Promise(r => setTimeout(r, 0));
    return callBridge(funcName, ...args);
}
```

For truly long runs, a Web Worker would be better, but the requirements note that even 1000-iteration MC "runs complete in milliseconds" — so main-thread execution is acceptable.

#### Exported API

```javascript
// Public API used by app.js
const PyBridge = {
    init: initPyodide,
    isReady: () => bridgeReady,
    getDefaultState: () => callBridge("get_default_state"),
    getDefaultModelConfig: () => callBridge("get_default_model_config"),
    validateState: (state) => callBridge("validate_state", state),
    validateModelConfig: (model, state) => callBridge("validate_model_config", model, state),
    runSingle: (state, model, seed) => callBridgeAsync("run_single", state, model, seed),
    runMonteCarlo: (state, model, n, seed) => callBridgeAsync("run_monte_carlo", state, model, n, seed),
    importCsv: (csvText) => callBridge("import_csv", csvText),
    generateTemplateCsv: (state, topN) => callBridge("generate_template_csv", state, topN),
};
```

---

## 3. Web UI

### New file: `web/index.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spice War Simulator</title>
    <link rel="stylesheet" href="css/style.css">
    <script src="https://cdn.jsdelivr.net/pyodide/v0.27.4/full/pyodide.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>
    <div id="loading-screen">
        <h1>Spice War Simulator</h1>
        <div class="spinner"></div>
        <p id="loading-status">Loading Python runtime...</p>
    </div>

    <div id="app" class="hidden">
        <header>
            <h1>Spice War Simulator</h1>
        </header>

        <main>
            <!-- State Editor -->
            <section id="state-editor">
                <h2>Game State <span id="state-status" class="status"></span></h2>
                <div class="editor-controls">
                    <button id="state-upload-btn">Upload JSON</button>
                    <input type="file" id="state-file-input" accept=".json" class="hidden">
                </div>
                <textarea id="state-textarea" rows="20" spellcheck="false"></textarea>
                <div id="state-error" class="error-msg hidden"></div>
                <div id="state-summary" class="hidden"></div>
            </section>

            <!-- Model Editor -->
            <section id="model-editor">
                <h2>Model Config <span id="model-status" class="status"></span></h2>
                <div class="editor-controls">
                    <button id="model-upload-btn">Upload JSON</button>
                    <input type="file" id="model-file-input" accept=".json" class="hidden">
                    <button id="csv-import-btn">Import CSV</button>
                    <input type="file" id="csv-file-input" accept=".csv" class="hidden">
                    <button id="csv-template-btn">Download CSV Template</button>
                </div>
                <textarea id="model-textarea" rows="10" spellcheck="false"></textarea>
                <div id="model-error" class="error-msg hidden"></div>
            </section>

            <!-- Run Controls -->
            <section id="run-controls">
                <h2>Run Simulation</h2>
                <div class="run-group">
                    <h3>Single Run</h3>
                    <label>Seed: <input type="number" id="single-seed" placeholder="auto"></label>
                    <button id="run-single-btn" disabled>Run</button>
                </div>
                <div class="run-group">
                    <h3>Monte Carlo</h3>
                    <label>Iterations: <input type="number" id="mc-iterations" value="1000" min="1"></label>
                    <label>Base seed: <input type="number" id="mc-base-seed" value="0" min="0"></label>
                    <button id="run-mc-btn" disabled>Run Monte Carlo</button>
                </div>
                <div id="run-spinner" class="spinner hidden"></div>
            </section>

            <!-- Results -->
            <section id="results" class="hidden">
                <h2>Results</h2>
                <div class="result-controls">
                    <button id="download-results-btn">Download Results JSON</button>
                    <button id="download-model-btn">Download Model JSON</button>
                </div>
                <div id="results-content"></div>
            </section>
        </main>
    </div>

    <script src="js/pyodide-loader.js"></script>
    <script src="js/app.js"></script>
</body>
</html>
```

### New file: `web/css/style.css`

Minimal styling. Key classes:

```css
.hidden { display: none; }
.status { font-size: 0.8em; padding: 2px 8px; border-radius: 4px; }
.status.valid { background: #d4edda; color: #155724; }
.status.invalid { background: #f8d7da; color: #721c24; }
.error-msg { color: #dc3545; margin-top: 4px; white-space: pre-wrap; }
.spinner { /* CSS-only spinner animation */ }

textarea {
    width: 100%;
    font-family: monospace;
    font-size: 13px;
    tab-size: 2;
}

table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: right; }
th { background: #f5f5f5; }
td:first-child, th:first-child { text-align: left; }
```

Not fully specified here — styling is cosmetic and can be iterated freely.

### New file: `web/js/app.js`

The UI logic. Organized by section.

#### Initialization

```javascript
document.addEventListener("DOMContentLoaded", async () => {
    const loadingStatus = document.getElementById("loading-status");

    await PyBridge.init((msg) => {
        loadingStatus.textContent = msg;
    });

    // Hide loading screen, show app
    document.getElementById("loading-screen").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");

    // Populate editors with defaults
    const defaultState = PyBridge.getDefaultState();
    document.getElementById("state-textarea").value = JSON.stringify(defaultState, null, 2);
    document.getElementById("model-textarea").value = "{}";

    // Initial validation
    validateState();
    validateModel();

    // Enable run buttons
    updateRunButtons();

    // Wire up event handlers
    setupEventHandlers();
});
```

#### State validation (debounced)

```javascript
let stateValidationTimer = null;
let currentStateDict = null;
let stateIsValid = false;

function validateState() {
    const textarea = document.getElementById("state-textarea");
    const statusEl = document.getElementById("state-status");
    const errorEl = document.getElementById("state-error");
    const summaryEl = document.getElementById("state-summary");

    let parsed;
    try {
        parsed = JSON.parse(textarea.value);
    } catch (e) {
        statusEl.className = "status invalid";
        statusEl.textContent = "Invalid JSON";
        errorEl.textContent = e.message;
        errorEl.classList.remove("hidden");
        summaryEl.classList.add("hidden");
        stateIsValid = false;
        currentStateDict = null;
        updateRunButtons();
        return;
    }

    const result = PyBridge.validateState(parsed);

    if (result.ok) {
        statusEl.className = "status valid";
        statusEl.textContent = "Valid";
        errorEl.classList.add("hidden");
        currentStateDict = parsed;
        stateIsValid = true;
        renderStateSummary(summaryEl, result);
    } else {
        statusEl.className = "status invalid";
        statusEl.textContent = "Invalid";
        errorEl.textContent = result.error;
        errorEl.classList.remove("hidden");
        summaryEl.classList.add("hidden");
        stateIsValid = false;
        currentStateDict = null;
    }

    updateRunButtons();
}

function onStateInput() {
    clearTimeout(stateValidationTimer);
    stateValidationTimer = setTimeout(validateState, 300);
}
```

The 300ms debounce prevents validation from firing on every keystroke. `renderStateSummary()` builds an HTML table from the `result.alliances` and `result.event_schedule` arrays.

#### State summary table

```javascript
function renderStateSummary(container, result) {
    let html = "<h3>Alliances</h3><table><tr>";
    html += "<th>ID</th><th>Faction</th><th>Power</th><th>Starting Spice</th><th>Daily Rate</th>";
    html += "</tr>";
    for (const a of result.alliances) {
        html += `<tr>
            <td>${esc(a.alliance_id)}</td>
            <td>${esc(a.faction)}</td>
            <td>${a.power}</td>
            <td>${a.starting_spice.toLocaleString()}</td>
            <td>${a.daily_rate.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    html += "<h3>Event Schedule</h3><table><tr>";
    html += "<th>#</th><th>Attacker</th><th>Day</th><th>Days Before</th>";
    html += "</tr>";
    for (const e of result.event_schedule) {
        html += `<tr>
            <td>${e.event_number}</td>
            <td>${esc(e.attacker_faction)}</td>
            <td>${esc(e.day)}</td>
            <td>${e.days_before}</td>
        </tr>`;
    }
    html += "</table>";

    container.innerHTML = html;
    container.classList.remove("hidden");
}

function esc(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
```

The `esc()` helper prevents XSS from user-supplied alliance IDs or faction names that might contain HTML characters.

#### Model validation (debounced)

Same pattern as state validation. Validates against `currentStateDict` if state is valid:

```javascript
let modelValidationTimer = null;
let modelIsValid = false;

function validateModel() {
    const textarea = document.getElementById("model-textarea");
    const statusEl = document.getElementById("model-status");
    const errorEl = document.getElementById("model-error");

    let parsed;
    try {
        parsed = JSON.parse(textarea.value);
    } catch (e) {
        statusEl.className = "status invalid";
        statusEl.textContent = "Invalid JSON";
        errorEl.textContent = e.message;
        errorEl.classList.remove("hidden");
        modelIsValid = false;
        updateRunButtons();
        return;
    }

    if (!stateIsValid) {
        statusEl.className = "status";
        statusEl.textContent = "Needs valid state";
        errorEl.classList.add("hidden");
        modelIsValid = false;
        updateRunButtons();
        return;
    }

    const result = PyBridge.validateModelConfig(parsed, currentStateDict);

    if (result.ok) {
        statusEl.className = "status valid";
        statusEl.textContent = "Valid";
        errorEl.classList.add("hidden");
        modelIsValid = true;
    } else {
        statusEl.className = "status invalid";
        statusEl.textContent = "Invalid";
        errorEl.textContent = result.error;
        errorEl.classList.remove("hidden");
        modelIsValid = false;
    }

    updateRunButtons();
}

function onModelInput() {
    clearTimeout(modelValidationTimer);
    modelValidationTimer = setTimeout(validateModel, 300);
}
```

#### Run buttons

```javascript
function updateRunButtons() {
    const canRun = stateIsValid && modelIsValid;
    document.getElementById("run-single-btn").disabled = !canRun;
    document.getElementById("run-mc-btn").disabled = !canRun;
}
```

#### Single run

```javascript
let lastResult = null;

async function runSingle() {
    const stateDict = JSON.parse(document.getElementById("state-textarea").value);
    const modelDict = JSON.parse(document.getElementById("model-textarea").value);
    const seedInput = document.getElementById("single-seed").value;
    const seed = seedInput ? parseInt(seedInput, 10) : null;

    setRunning(true);
    const result = await PyBridge.runSingle(stateDict, modelDict, seed);
    setRunning(false);

    if (!result.ok) {
        showError(result.error);
        return;
    }

    lastResult = result;
    renderSingleResults(result);
}
```

#### Single run results rendering

```javascript
function renderSingleResults(result) {
    const container = document.getElementById("results-content");
    const section = document.getElementById("results");
    section.classList.remove("hidden");

    // Sort alliances by tier then spice descending
    const entries = Object.entries(result.final_spice).map(([id, spice]) => ({
        id,
        spice,
        tier: result.rankings[id],
    }));
    entries.sort((a, b) => a.tier - b.tier || b.spice - a.spice);

    // Summary table
    let html = `<h3>Final Rankings (seed: ${result.seed})</h3>`;
    html += "<table><tr><th>Alliance</th><th>Tier</th><th>Final Spice</th></tr>";
    for (const e of entries) {
        html += `<tr>
            <td>${esc(e.id)}</td>
            <td>${e.tier}</td>
            <td>${e.spice.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    // Event accordion
    html += "<h3>Event Details</h3>";
    for (const event of result.event_history) {
        html += `<details>
            <summary>Event ${event.event_number}: ${esc(event.attacker_faction)} (${esc(event.day)})</summary>
            ${renderEventDetail(event)}
        </details>`;
    }

    container.innerHTML = html;
}
```

The `<details>/<summary>` HTML elements provide the accordion behavior without any JavaScript — native browser expand/collapse.

#### Event detail rendering

```javascript
function renderEventDetail(event) {
    let html = "";

    // Spice before/after
    html += "<h4>Spice</h4><table>";
    html += "<tr><th>Alliance</th><th>Before</th><th>After</th><th>Change</th></tr>";
    for (const [id, before] of Object.entries(event.spice_before)) {
        const after = event.spice_after[id];
        const change = after - before;
        const sign = change >= 0 ? "+" : "";
        html += `<tr>
            <td>${esc(id)}</td>
            <td>${before.toLocaleString()}</td>
            <td>${after.toLocaleString()}</td>
            <td>${sign}${change.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    // Targeting
    html += "<h4>Targeting</h4><table>";
    html += "<tr><th>Attacker</th><th>Defender</th></tr>";
    for (const [att, def_] of Object.entries(event.targeting)) {
        html += `<tr><td>${esc(att)}</td><td>${esc(def_)}</td></tr>`;
    }
    html += "</table>";

    // Battles
    html += "<h4>Battles</h4>";
    for (const battle of event.battles) {
        html += `<div class="battle-detail">`;
        html += `<p><strong>${esc(battle.attackers.join(", "))} → ${esc(battle.defenders[0])}</strong>`;
        html += ` | Outcome: ${esc(battle.outcome)}`;
        html += ` | Theft: ${battle.theft_percentage}%</p>`;

        // Probabilities
        const probs = battle.outcome_probabilities;
        html += `<p class="probs">P(full)=${(probs.full_success * 100).toFixed(1)}%`;
        html += ` P(partial)=${(probs.partial_success * 100).toFixed(1)}%`;
        if (probs.custom !== undefined) {
            html += ` P(custom)=${(probs.custom * 100).toFixed(1)}%`;
        }
        html += ` P(fail)=${(probs.fail * 100).toFixed(1)}%</p>`;

        // Transfers
        if (Object.keys(battle.transfers).length > 0) {
            html += "<table><tr><th>Alliance</th><th>Transfer</th></tr>";
            for (const [id, amount] of Object.entries(battle.transfers)) {
                const sign = amount >= 0 ? "+" : "";
                html += `<tr><td>${esc(id)}</td><td>${sign}${amount.toLocaleString()}</td></tr>`;
            }
            html += "</table>";
        }
        html += "</div>";
    }

    return html;
}
```

#### Monte Carlo results rendering

```javascript
async function runMonteCarlo() {
    const stateDict = JSON.parse(document.getElementById("state-textarea").value);
    const modelDict = JSON.parse(document.getElementById("model-textarea").value);
    const iterations = parseInt(document.getElementById("mc-iterations").value, 10) || 1000;
    const baseSeed = parseInt(document.getElementById("mc-base-seed").value, 10) || 0;

    setRunning(true);
    const result = await PyBridge.runMonteCarlo(stateDict, modelDict, iterations, baseSeed);
    setRunning(false);

    if (!result.ok) {
        showError(result.error);
        return;
    }

    lastResult = result;
    renderMonteCarloResults(result);
}
```

```javascript
function renderMonteCarloResults(result) {
    const container = document.getElementById("results-content");
    const section = document.getElementById("results");
    section.classList.remove("hidden");

    // Sort alliances by most-likely tier, then T1 probability descending
    const aids = Object.keys(result.tier_distribution);
    aids.sort((a, b) => {
        const aT1 = parseFloat(result.tier_distribution[a]["1"] || 0);
        const bT1 = parseFloat(result.tier_distribution[b]["1"] || 0);
        return bT1 - aT1;
    });

    // Tier distribution table
    let html = `<h3>Tier Distribution (${result.num_iterations} iterations)</h3>`;
    html += "<table><tr><th>Alliance</th>";
    for (let t = 1; t <= 5; t++) html += `<th>T${t}</th>`;
    html += "</tr>";
    for (const aid of aids) {
        html += `<tr><td>${esc(aid)}</td>`;
        const dist = result.tier_distribution[aid];
        for (let t = 1; t <= 5; t++) {
            const pct = (parseFloat(dist[String(t)] || 0) * 100).toFixed(1);
            html += `<td>${pct}%</td>`;
        }
        html += "</tr>";
    }
    html += "</table>";

    // Spice statistics table
    html += "<h3>Spice Statistics</h3>";
    html += "<table><tr><th>Alliance</th><th>Mean</th><th>Median</th>";
    html += "<th>Min</th><th>Max</th><th>P25</th><th>P75</th></tr>";
    for (const aid of aids) {
        const s = result.spice_stats[aid];
        html += `<tr>
            <td>${esc(aid)}</td>
            <td>${s.mean.toLocaleString()}</td>
            <td>${s.median.toLocaleString()}</td>
            <td>${s.min.toLocaleString()}</td>
            <td>${s.max.toLocaleString()}</td>
            <td>${s.p25.toLocaleString()}</td>
            <td>${s.p75.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table>";

    // Chart containers
    html += '<div id="chart-section">';
    html += '<h3>Tier Distribution</h3><canvas id="tier-chart"></canvas>';
    html += '<h3>Spice Distribution</h3><canvas id="spice-chart"></canvas>';
    html += "</div>";

    container.innerHTML = html;

    // Render charts after DOM update
    renderTierChart(aids, result.tier_distribution);
    renderSpiceChart(aids, result.spice_stats);
}
```

#### Charts (Chart.js)

```javascript
let tierChartInstance = null;
let spiceChartInstance = null;

function renderTierChart(aids, tierDist) {
    if (tierChartInstance) tierChartInstance.destroy();

    const ctx = document.getElementById("tier-chart").getContext("2d");
    const datasets = [];
    const tierColors = ["#28a745", "#17a2b8", "#ffc107", "#fd7e14", "#dc3545"];

    for (let t = 1; t <= 5; t++) {
        datasets.push({
            label: `Tier ${t}`,
            data: aids.map(aid => parseFloat(tierDist[aid][String(t)] || 0) * 100),
            backgroundColor: tierColors[t - 1],
        });
    }

    tierChartInstance = new Chart(ctx, {
        type: "bar",
        data: { labels: aids, datasets },
        options: {
            responsive: true,
            scales: {
                x: { stacked: true },
                y: { stacked: true, max: 100, title: { display: true, text: "%" } },
            },
        },
    });
}

function renderSpiceChart(aids, spiceStats) {
    if (spiceChartInstance) spiceChartInstance.destroy();

    const ctx = document.getElementById("spice-chart").getContext("2d");

    // Use a horizontal bar chart showing min/p25/median/p75/max ranges
    const datasets = [
        {
            label: "Min–Max Range",
            data: aids.map(aid => [spiceStats[aid].min, spiceStats[aid].max]),
            backgroundColor: "rgba(54, 162, 235, 0.2)",
            borderColor: "rgba(54, 162, 235, 1)",
            borderWidth: 1,
        },
        {
            label: "P25–P75 Range",
            data: aids.map(aid => [spiceStats[aid].p25, spiceStats[aid].p75]),
            backgroundColor: "rgba(54, 162, 235, 0.5)",
            borderColor: "rgba(54, 162, 235, 1)",
            borderWidth: 1,
        },
        {
            label: "Median",
            data: aids.map(aid => spiceStats[aid].median),
            type: "line",
            borderColor: "#dc3545",
            pointRadius: 6,
            pointStyle: "rectRot",
            showLine: false,
        },
    ];

    spiceChartInstance = new Chart(ctx, {
        type: "bar",
        data: { labels: aids, datasets },
        options: {
            indexAxis: "y",
            responsive: true,
            scales: {
                x: { title: { display: true, text: "Spice" } },
            },
        },
    });
}
```

The tier chart uses stacked bars (100% stacked per alliance). The spice chart uses floating bars for range visualization — Chart.js supports `[min, max]` data points for bar charts, creating a box-plot-like display.

#### File upload & download handlers

```javascript
function setupEventHandlers() {
    // State editor
    document.getElementById("state-textarea").addEventListener("input", onStateInput);
    document.getElementById("state-upload-btn").addEventListener("click", () => {
        document.getElementById("state-file-input").click();
    });
    document.getElementById("state-file-input").addEventListener("change", (e) => {
        readFileToTextarea(e.target.files[0], "state-textarea", validateState);
    });

    // Model editor
    document.getElementById("model-textarea").addEventListener("input", onModelInput);
    document.getElementById("model-upload-btn").addEventListener("click", () => {
        document.getElementById("model-file-input").click();
    });
    document.getElementById("model-file-input").addEventListener("change", (e) => {
        readFileToTextarea(e.target.files[0], "model-textarea", validateModel);
    });

    // CSV import
    document.getElementById("csv-import-btn").addEventListener("click", () => {
        document.getElementById("csv-file-input").click();
    });
    document.getElementById("csv-file-input").addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = () => {
            const result = PyBridge.importCsv(reader.result);
            if (result.ok) {
                document.getElementById("model-textarea").value =
                    JSON.stringify(result.config, null, 2);
                validateModel();
            } else {
                alert("CSV import error: " + result.error);
            }
        };
        reader.readAsText(file);
    });

    // CSV template download
    document.getElementById("csv-template-btn").addEventListener("click", () => {
        if (!currentStateDict) return;
        const result = PyBridge.generateTemplateCsv(currentStateDict, 6);
        if (result.ok) {
            downloadFile("spice_war_template.csv", result.csv, "text/csv");
        } else {
            alert("Template error: " + result.error);
        }
    });

    // Run buttons
    document.getElementById("run-single-btn").addEventListener("click", runSingle);
    document.getElementById("run-mc-btn").addEventListener("click", runMonteCarlo);

    // Export buttons
    document.getElementById("download-results-btn").addEventListener("click", () => {
        if (lastResult) {
            downloadFile("spice_war_results.json",
                JSON.stringify(lastResult, null, 2), "application/json");
        }
    });
    document.getElementById("download-model-btn").addEventListener("click", () => {
        const model = document.getElementById("model-textarea").value;
        downloadFile("model_config.json", model, "application/json");
    });
}
```

#### Utility functions

```javascript
function readFileToTextarea(file, textareaId, validateFn) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
        document.getElementById(textareaId).value = reader.result;
        validateFn();
    };
    reader.readAsText(file);
}

function downloadFile(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

function setRunning(isRunning) {
    document.getElementById("run-single-btn").disabled = isRunning;
    document.getElementById("run-mc-btn").disabled = isRunning;
    document.getElementById("run-spinner").classList.toggle("hidden", !isRunning);
}

function showError(msg) {
    const container = document.getElementById("results-content");
    const section = document.getElementById("results");
    section.classList.remove("hidden");
    container.innerHTML = `<div class="error-msg">${esc(msg)}</div>`;
}
```

---

## 4. Packaging

### Build script: `scripts/build_web.sh`

A shell script that packages the Python source into a zip and copies it into the web directory for serving.

```bash
#!/bin/bash
set -e

# Create python package zip for Pyodide
cd src
zip -r ../web/python/spice_war.zip spice_war/ -x "spice_war/__pycache__/*" "spice_war/**/__pycache__/*"
cd ..

echo "Built web/python/spice_war.zip"
```

Run before serving or deploying:

```
bash scripts/build_web.sh
cd web && python -m http.server 8000
```

### Static file structure

```
web/
  index.html
  css/
    style.css
  js/
    app.js
    pyodide-loader.js
  python/
    spice_war.zip          # Generated by build_web.sh
```

---

## 5. Tests — `tests/test_web_bridge.py`

All tests are standard pytest tests that test the bridge module's Python functions directly — no Pyodide or browser involved.

### Imports

```python
import pytest

from spice_war.web.bridge import (
    generate_template_csv,
    get_default_model_config,
    get_default_state,
    import_csv,
    run_monte_carlo,
    run_single,
    validate_model_config,
    validate_state,
)
```

### Test implementations

| # | Test | Implementation |
|---|------|----------------|
| 1 | **`get_default_state` returns valid state** | Call `get_default_state()`, pass result to `validate_state()`. Assert `result["ok"] is True`. Assert `result["alliances"]` has 4 entries. Assert `result["event_schedule"]` has 4 entries. |
| 2 | **`get_default_model_config` returns valid config** | Call `get_default_model_config()`, pass to `validate_model_config()` with default state. Assert `result["ok"] is True`. |
| 3 | **`validate_state` accepts good input** | Construct a minimal valid state dict (2 alliances, 2 factions, 1 event). Call `validate_state()`. Assert `result["ok"] is True`. Assert `result["alliances"]` matches input. |
| 4 | **`validate_state` rejects missing alliances** | State dict without `"alliances"` key. Assert `result["ok"] is False`. Assert `"alliances"` in `result["error"]`. |
| 5 | **`validate_state` rejects missing alliance fields** | Alliance missing `"power"`. Assert `result["ok"] is False`. Assert `"missing"` in `result["error"]`. |
| 6 | **`validate_state` rejects single faction** | All alliances in one faction. Assert `result["ok"] is False`. Assert `"2 factions"` in `result["error"]`. |
| 7 | **`validate_state` rejects duplicate IDs** | Two alliances with same `alliance_id`. Assert `result["ok"] is False`. Assert `"Duplicate"` in `result["error"]`. |
| 8 | **`validate_model_config` accepts good input** | Valid state + `{}` model. Assert `result["ok"] is True`. |
| 9 | **`validate_model_config` rejects unknown keys** | Model with `{"unknown_key": 1}`. Assert `result["ok"] is False`. Assert `"unknown"` in `result["error"].lower()`. |
| 10 | **`validate_model_config` rejects bad alliance ref** | Model with `event_targets` referencing nonexistent alliance. Assert `result["ok"] is False`. |
| 11 | **`run_single` produces correct structure** | Run with default state and `{}` model. Assert `result["ok"] is True`. Assert keys: `seed`, `final_spice`, `rankings`, `event_history`. Assert `len(result["event_history"]) == 4` (4 events in default state). Assert all 4 alliance IDs present in `final_spice` and `rankings`. |
| 12 | **`run_single` is deterministic** | Run twice with same state, model, and `seed=42`. Assert `result1["final_spice"] == result2["final_spice"]`. Assert `result1["rankings"] == result2["rankings"]`. |
| 13 | **`run_single` reports validation errors** | Run with invalid state (missing alliances). Assert `result["ok"] is False`. |
| 14 | **`run_monte_carlo` produces correct structure** | Run with default state, `{}` model, `num_iterations=10`. Assert `result["ok"] is True`. Assert keys: `num_iterations`, `base_seed`, `tier_distribution`, `spice_stats`, `raw_results`. Assert `result["num_iterations"] == 10`. |
| 15 | **`run_monte_carlo` iteration count** | Run with `num_iterations=25`. Assert `len(result["raw_results"]) == 25`. |
| 16 | **`run_monte_carlo` tier distributions sum to 1** | Run with `num_iterations=100`. For each alliance, sum tier probabilities 1–5. Assert `pytest.approx(1.0)`. |
| 17 | **`run_monte_carlo` spice stats structure** | Check each alliance's `spice_stats` has keys `mean`, `median`, `min`, `max`, `p25`, `p75`. Assert `min <= p25 <= median <= p75 <= max`. |
| 18 | **`import_csv` round-trip** | Call `generate_template_csv()` with default state. Pass the CSV string to `import_csv()`. Assert `result["ok"] is True`. Assert result contains a valid config dict (has `random_seed` key). |
| 19 | **`import_csv` error on bad CSV** | Pass `"not,valid,csv,data\nwith,random,stuff,here"`. Assert `result["ok"] is True` with an empty or minimal config (the importer skips unrecognized rows). Alternatively, pass something that triggers an actual parse error and assert `result["ok"] is False`. |

### Shared fixture

```python
@pytest.fixture
def default_state():
    return get_default_state()

@pytest.fixture
def valid_state():
    """Minimal 2-alliance, 1-event state for fast tests."""
    return {
        "alliances": [
            {
                "alliance_id": "A1",
                "faction": "red",
                "power": 10.0,
                "starting_spice": 1_000_000,
                "daily_rate": 30_000,
            },
            {
                "alliance_id": "D1",
                "faction": "blue",
                "power": 10.0,
                "starting_spice": 1_000_000,
                "daily_rate": 30_000,
            },
        ],
        "event_schedule": [
            {"attacker_faction": "red", "day": "wednesday", "days_before": 7},
        ],
    }
```

### Notes

- Tests 11–17 use small iteration counts (10–100) for speed, not the default 1000.
- Test 12 validates determinism by comparing the full `final_spice` dict, not just a single value.
- Test 18 relies on the existing `generate_template` → `import_from_csv` round-trip logic; the bridge just wraps it with CSV string serialization.
- All tests call the bridge functions directly as Python functions — no JSON string serialization. The JS→Python serialization boundary is tested by the manual browser checklist (requirement tests 15–23).

---

## File Changes Summary

| File | Change |
|------|--------|
| `src/spice_war/web/__init__.py` | New file — empty package init |
| `src/spice_war/web/bridge.py` | New file — 9 public functions + 4 private helpers |
| `web/index.html` | New file — single-page HTML shell |
| `web/css/style.css` | New file — minimal styling |
| `web/js/pyodide-loader.js` | New file — Pyodide init + JS↔Python bridge calls |
| `web/js/app.js` | New file — UI logic, event handlers, result rendering, charts |
| `scripts/build_web.sh` | New file — packages Python source into zip for Pyodide |
| `tests/test_web_bridge.py` | New file — 19 tests |

No changes to any existing files. The bridge imports from existing modules (`validation`, `simulator`, `monte_carlo`, `configurable`, `data_structures`, `sheets/importer`, `sheets/template`) but does not modify them.

## Backward Compatibility

All new files — no changes to existing code or behavior.
