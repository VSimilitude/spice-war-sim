# Web Interface — Design Document

Implementation plan for [0009_web_interface_requirements.md](../improvements/0009_web_interface_requirements.md).

---

## Phase 1: Python Bridge Layer

**New file:** `src/spice_war/web/bridge.py` (+ `__init__.py`)

A thin adapter that exposes simulation functions as dict-in/dict-out calls with no filesystem dependencies. Every public function returns a `{"ok": True, ...}` or `{"ok": False, "error": "..."}` envelope.

### 1.1 Refactor: Extract dict validation from `validation.py`

The current `load_state()` and `load_model_config()` couple JSON parsing (file I/O) with validation logic. The bridge needs to validate dicts directly.

**Approach — extract, don't duplicate:**

Split each loader into two layers:

| Current function | New internal function | Existing function becomes |
|---|---|---|
| `load_state(path)` | `validate_state_dict(data: dict) -> tuple[list[Alliance], list[EventConfig]]` | Calls `_load_json(path)` then `validate_state_dict(data)` |
| `load_model_config(path, ...)` | `validate_model_config_dict(data: dict, alliance_ids, alliances) -> dict` | Calls `_load_json(path)` then `validate_model_config_dict(data, ...)` |

The new `validate_*_dict` functions contain all the existing validation logic unchanged. The old `load_*` functions become thin wrappers: load JSON from disk, then call the dict validator. No existing behavior changes; all 65 tests continue to pass.

The bridge calls `validate_state_dict` / `validate_model_config_dict` directly.

### 1.2 Bridge functions

Each function wraps existing logic in a try/except that catches `ValidationError` (and any unexpected exception) and returns the error envelope.

#### `get_default_state() -> dict`

Returns a hardcoded state dict (4 alliances, 2 factions, 4 events) matching the structure in `sample_state.json` but expanded to 4 events for a more realistic demo. Pure data, no computation.

#### `get_default_model_config() -> dict`

Returns `{}`. Trivial.

#### `validate_state(state_dict: dict) -> dict`

Calls `validate_state_dict(state_dict)`. On success, serializes the Alliance/EventConfig objects back to plain dicts for the `"alliances"` and `"event_schedule"` response fields.

#### `validate_model_config(model_dict: dict, state_dict: dict) -> dict`

First validates the state (to extract `alliance_ids` and `alliances`), then calls `validate_model_config_dict`. Two-step because model validation requires alliance context.

#### `run_single(state_dict, model_dict, seed=None) -> dict`

1. Validate state → `alliances`, `event_schedule`
2. Merge seed: if `seed` is not None, override `model_dict["random_seed"]`
3. Validate model config
4. Construct `ConfigurableModel(model_dict, alliances)`
5. Call `simulate_war(alliances, event_schedule, model)`
6. Return `{"ok": True, "seed": ..., "final_spice": ..., "rankings": ..., "event_history": ...}`

The `event_history` list comes directly from `simulate_war` — already JSON-serializable dicts.

#### `run_monte_carlo(state_dict, model_dict, num_iterations=1000, base_seed=0) -> dict`

1. Validate state + model
2. Call existing `run_monte_carlo(alliances, event_schedule, model_config, num_iterations, base_seed)`
3. Convert `MonteCarloResult` to response dict:
   - `tier_distribution`: call `result.tier_distribution(aid)` for each alliance, convert int keys to strings
   - `spice_stats`: call `result.spice_stats(aid)` for each alliance
   - `raw_results`: use `result.per_iteration` directly

#### `import_csv(csv_text: str) -> dict`

1. Parse CSV text into rows via `csv.reader(io.StringIO(csv_text))`
2. Call `import_from_csv(rows)` from `sheets/importer.py`
3. Return `{"ok": True, "config": result}`

Note: `fetch_csv_rows` uses `urllib.request` which won't work in Pyodide (no socket access). The bridge bypasses this by accepting raw CSV text and parsing it locally. The UI handles file upload / paste.

#### `generate_template_csv(state_dict, top_n=6) -> dict`

1. Validate state → `alliances`, `event_schedule`
2. Call `generate_template(alliances, schedule, top_n)` from `sheets/template.py`
3. Convert row list to CSV string via `csv.writer(io.StringIO())`
4. Return `{"ok": True, "csv": csv_string}`

### 1.3 Bridge test plan

14 tests as specified in requirements. All run under standard pytest (no Pyodide needed). Test file: `tests/test_web_bridge.py`.

Key implementation notes:
- Tests 1-2: Call `get_default_state()` / `get_default_model_config()`, feed output back through `validate_state()` / `validate_model_config()`
- Tests 7-8: `run_single` with sample state + seed 42, assert deterministic output
- Test 12: Sum each alliance's tier distribution values, assert `≈ 1.0` with tolerance
- Test 13: `generate_template_csv` → `import_csv` round-trip, validate result passes `validate_model_config`

---

## Phase 2: Pyodide Integration

**New file:** `web/js/pyodide-loader.js`

### 2.1 Architecture: Main thread (no Web Worker)

The requirements say worker is optional ("or inline in main JS"). The simulation runs in milliseconds even for 1000-iteration MC, so blocking the main thread briefly is acceptable and avoids the complexity of worker message passing. A spinner/disabled UI during execution prevents user confusion.

If latency becomes a problem (e.g., larger alliance sets), a worker can be added later without changing the bridge API.

### 2.2 Initialization sequence

```
1. Load Pyodide from CDN (https://cdn.jsdelivr.net/pyodide/v0.27.4/full/)
2. pyodide.FS.mkdir("/spice_war_pkg/spice_war")
3. Write all .py files from src/spice_war/ into the virtual filesystem
   - Files are inlined as JS string constants in a generated asset (see 2.3)
4. pyodide.runPython("import sys; sys.path.insert(0, '/spice_war_pkg')")
5. pyodide.runPython("from spice_war.web.bridge import *")
6. Store references to bridge functions via pyodide.globals
7. Signal UI ready
```

### 2.3 Python packaging for the browser

**Build script:** `scripts/build_web.py`

A simple Python script (run once before deployment or during dev) that:
1. Walks `src/spice_war/` and reads all `.py` files
2. Generates `web/js/python-sources.js` containing a JS object mapping file paths to source strings:
   ```js
   const PYTHON_SOURCES = {
     "spice_war/__init__.py": "",
     "spice_war/game/mechanics.py": "from __future__...",
     ...
   };
   ```
3. `pyodide-loader.js` iterates this object and writes files into Pyodide's virtual FS.

This avoids needing to fetch individual `.py` files (CORS issues with `file://`, extra HTTP requests) and keeps everything as static assets with no build toolchain.

### 2.4 JS ↔ Python calling convention

```js
// In pyodide-loader.js
async function callBridge(funcName, ...args) {
    const argsJson = JSON.stringify(args);
    const resultJson = pyodide.runPython(`
        import json
        _args = json.loads('${argsJson.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}')
        json.dumps(${funcName}(*_args))
    `);
    return JSON.parse(resultJson);
}
```

Alternative (cleaner): use `pyodide.globals.get(funcName)` to get a Python callable, call it with JS-to-Python proxy objects, and convert the result. The first approach is simpler since all bridge functions accept/return JSON-friendly types.

Chosen approach: **JSON string round-trip** for simplicity and to avoid proxy edge cases.

### 2.5 Error boundary

All `callBridge` calls are wrapped in try/catch. If Pyodide throws a `PythonError`, extract the message and return `{"ok": false, "error": message}` to the UI layer. This catches both bridge-level errors (returned as `ok: false`) and unexpected crashes.

---

## Phase 3: Web UI

**Location:** `web/` at project root

### 3.1 Technology choices

| Concern | Choice | Rationale |
|---|---|---|
| Framework | Vanilla JS + HTML templates | No build step, requirements say "buildless" |
| Styling | Single `style.css` + CSS custom properties | Theme variables for color consistency |
| JSON editor | `<textarea>` with monospace font | Simple, no dependency. Syntax highlighting not required. |
| Charts | Chart.js 4.x via CDN | Lightweight, well-documented, supports bar + box plots |
| Icons/spinners | CSS-only | No icon library dependency |

### 3.2 File structure

```
web/
  index.html              # Single page, all sections
  css/
    style.css             # All styles
  js/
    app.js                # UI logic: editors, run controls, results rendering
    pyodide-loader.js     # Pyodide init + callBridge()
    python-sources.js     # Generated: Python source files as JS strings
```

### 3.3 Page layout

Single page with vertically stacked sections. Each section can be collapsed.

```
┌──────────────────────────────────────────────────────────────┐
│  Spice War Simulator                          [Loading...]   │
├──────────────────────────────────────────────────────────────┤
│  ┌─── State Editor ──────────────────────────────────────┐   │
│  │ [Upload JSON]                          [✓ Valid]      │   │
│  │ ┌──────────────────────────────────────────────────┐  │   │
│  │ │ { "alliances": [...], ...}  (textarea)           │  │   │
│  │ └──────────────────────────────────────────────────┘  │   │
│  │ Alliance Summary Table (rendered after validation)    │   │
│  │ Event Schedule Table                                  │   │
│  └───────────────────────────────────────────────────────┘   │
│  ┌─── Model Editor ──────────────────────────────────────┐   │
│  │ [Upload JSON] [Import CSV] [Download Template]        │   │
│  │ ┌──────────────────────────────────────────────────┐  │   │
│  │ │ {} (textarea)                                    │  │   │
│  │ └──────────────────────────────────────────────────┘  │   │
│  │ [✓ Valid]                                             │   │
│  └───────────────────────────────────────────────────────┘   │
│  ┌─── Run Controls ──────────────────────────────────────┐   │
│  │ Single Run:  Seed [____]  [Run]                       │   │
│  │ Monte Carlo: Iterations [1000] Base Seed [0] [Run MC] │   │
│  └───────────────────────────────────────────────────────┘   │
│  ┌─── Results ───────────────────────────────────────────┐   │
│  │ (populated after a run completes)                     │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 State Editor behavior

1. On page load: populate textarea with `get_default_state()` output (pretty-printed)
2. On any textarea change (debounced 300ms): call `validate_state(parsed_json)`
   - Green indicator + render summary tables on success
   - Red indicator + error text on failure
   - If textarea is not valid JSON, show "Invalid JSON" without calling bridge
3. Upload button: `<input type="file" accept=".json">` → read file → populate textarea → triggers validation
4. Summary tables:
   - Alliances: ID, Faction, Power, Starting Spice, Daily Rate
   - Events: #, Attacker Faction, Day, Days Before

### 3.5 Model Editor behavior

1. On page load: populate textarea with `{}`
2. On textarea change (debounced 300ms): validate JSON locally, then call `validate_model_config(model_dict, state_dict)`
3. Upload JSON: same pattern as state
4. Import CSV: `<input type="file" accept=".csv">` or a paste textarea. Calls `import_csv(text)` → on success, populate model textarea with pretty-printed result → triggers validation
5. Download Template: calls `generate_template_csv(state_dict)` → triggers browser download of `.csv` file. Disabled if state is invalid.

### 3.6 Run Controls

- Both run buttons disabled while: Pyodide loading, state invalid, or run in progress
- Single Run: reads seed input (empty = `null`), calls `run_single(state, model, seed)`
- Monte Carlo: reads iterations + base_seed, calls `run_monte_carlo(state, model, iterations, base_seed)`
- Show spinner overlay during execution
- On completion: render results in the Results section, scroll into view

### 3.7 Single Run results

**Summary (default):**

Rankings table sorted by tier ascending, then spice descending:

| Alliance | Tier | Final Spice |
|---|---|---|
| RedWolves | 1 | 4,215,300 |
| BlueLions | 2 | 3,180,000 |
| ... | ... | ... |

**Detail (expandable):**

Each event as a collapsible `<details>` element:

```
▸ Event 1 — red attacks (Wednesday)
  Spice Before/After table
  Targeting: RedWolves → BlueLions, ...
  Battles:
    Battle 1: [RedWolves] vs [BlueLions, BlueShields]
      Outcome: full_success (p=0.65)
      Theft: 20% of 1,800,000 = 360,000
      Transfers: RedWolves +360,000, BlueLions -360,000
```

### 3.8 Monte Carlo results

**Summary (default):**

Tier distribution table — sorted by most-likely tier, then T1 probability:

| Alliance | T1 | T2 | T3 | T4 | T5 |
|---|---|---|---|---|---|
| RedWolves | 62% | 28% | 8% | 2% | 0% |
| ... | | | | | |

Spice statistics table:

| Alliance | Mean | Median | Min | Max | P25 | P75 |
|---|---|---|---|---|---|---|
| RedWolves | 4,215,300 | 4,180,000 | 2,950,000 | 5,620,000 | 3,800,000 | 4,600,000 |

**Charts:**

- Tier distribution: Chart.js grouped bar chart. X-axis = alliances, grouped bars = tiers 1-5. Color-coded by tier.
- Spice distribution: Chart.js box-and-whisker using the `chartjs-chart-boxplot` plugin (CDN). One box per alliance showing min/p25/median/p75/max.

### 3.9 Export

Two download buttons in the results section:
- **Download Results JSON**: `JSON.stringify(lastResult, null, 2)` → blob download
- **Download Model Config**: current model textarea contents → blob download

Both use the standard `URL.createObjectURL` + hidden `<a>` click pattern.

---

## Phase 4: Build & Deploy

### 4.1 Build script: `scripts/build_web.py`

```
Usage: python scripts/build_web.py

1. Walk src/spice_war/**/*.py
2. Generate web/js/python-sources.js
3. Print "Build complete. Serve web/ to run."
```

No npm, no bundler. This is the only build step.

### 4.2 Local development

```bash
python scripts/build_web.py          # regenerate python-sources.js
cd web && python -m http.server 8000 # serve at localhost:8000
```

Re-run `build_web.py` after any Python source change.

### 4.3 Production deployment

Deploy the `web/` directory to any static host. The directory is self-contained after the build step. Pyodide loads from its CDN, Chart.js loads from its CDN, everything else is local.

---

## Implementation Order

| Step | What | Depends on | Tests |
|---|---|---|---|
| 1 | Extract `validate_state_dict` / `validate_model_config_dict` from `validation.py` | — | Existing 65 tests still pass |
| 2 | Create `src/spice_war/web/bridge.py` with all 7 functions | Step 1 | 14 bridge tests |
| 3 | Create `scripts/build_web.py` | — | Manual: generates `python-sources.js` |
| 4 | Create `web/js/pyodide-loader.js` | Step 3 | Manual: Pyodide loads in browser |
| 5 | Create `web/index.html` + `web/css/style.css` | — | — |
| 6 | Create `web/js/app.js` — editors + validation | Steps 4-5 | Manual: checklist items 15-17 |
| 7 | Add run controls + single run results | Step 6 | Manual: checklist items 18-19 |
| 8 | Add Monte Carlo results + charts | Step 7 | Manual: checklist items 20 |
| 9 | Add file upload, CSV import, export | Steps 6-8 | Manual: checklist items 21-23 |

Steps 1-2 are pure Python, fully testable without a browser. Steps 3-9 are the web layer.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Pyodide version breaks API | Pin specific version (v0.27.4) in CDN URL |
| Large alliance sets slow MC in browser | Default 1000 iterations is fine for ~20 alliances. Add a warning if > 50 alliances or > 5000 iterations. |
| `urllib.request` import fails in Pyodide | The bridge's `import_csv` accepts text directly, never calls `fetch_csv_rows`. But if any transitive import pulls in `urllib`, it could fail at import time. Mitigation: the bridge module must not import `sheets/importer.fetch_csv_rows` at module level — use a local import inside `import_csv()`. |
| Browser caching stale `python-sources.js` | Append a content hash or version query param to the script tag |

---

## Scope

**In scope:** Everything listed in sections 1-6 of the requirements doc.

**Out of scope (per requirements):** Server-side execution, user accounts, Google Sheets direct fetch, real-time collaboration, mobile optimization, automated browser tests, build toolchain.

---

## Post-Launch Enhancements (0010–0016)

The following features were added after the initial web interface launch:

### Form-Based Model Editor (0010)

Replaced the raw JSON textarea with structured accordion sections:
- **General Settings**: seed, targeting strategy, targeting temperature, power noise, outcome noise
- **Faction Targeting Strategy**: per-faction strategy dropdowns
- **Default Targets**: dynamic add/remove rows with alliance dropdowns
- **Event Targets**: per-event sub-sections with attacker/defender selectors
- **Event Reinforcements**: per-event assignment rows
- **Battle Outcome Matrix**: grouped by day, percentage inputs, inline probability sum validation, heuristic placeholder hints
- **Damage Weights**: per-alliance weight inputs

A "Edit as JSON" / "Back to form" toggle provides bi-directional sync between form and JSON textarea. Alliance dropdowns auto-populate from validated state data.

The game state JSON editor is wrapped in a collapsible `<details>` element (collapsed by default), with summary tables always visible.

### Validation & UX Fixes (0011)

- Inline error messages on outcome matrix rows (type errors, range, probability sums)
- Heuristic probability placeholder hints computed from power ratios
- Duplicate alliance detection in targeting sections
- Guard flag prevents duplicate event listener stacking on form rebuilds

### Enhanced Results Tables (0011–0012)

- **Final Rankings**: Faction, Alliance, Rank, Tier, Final Spice columns
- **Spice Before/After**: Before/After Rank with colored rank-change arrows (green up, red down, grey dash)
- **Targeting**: Bracket, Attacker, Attacker Rank, Defender, Defender Rank columns
- Battle filter shows complete battles when any participant matches the filter

### Results Filter (0011, 0016)

Filter bar with "All", "Top 3", "Top 5", "Top 10 per faction" buttons. Filters all results tables and charts by top-N alliances per faction by power. Default changed to "Top 10" in 0016.

### Shareable URLs (0011)

Compressed configuration (state + model + run params) encoded into URL hash fragment using `CompressionStream("deflate")` + base64url. "Copy Share Link" button with toast notification. Auto-loads from URL hash on page open.

### MC Targeting Matrix (0013)

Per-event attacker/defender targeting frequency matrix displayed after Monte Carlo charts. Shows how often each attacker targeted each defender across all iterations, as a fraction. Respects the alliance filter.

### MC Randomness Controls (0015)

Three number inputs in General Settings: Targeting Temperature, Power Noise, Outcome Noise. Values of 0 or empty are omitted from the model config JSON.

### Collapsible Game State Sections (0016)

Alliances and Event Schedule summary tables wrapped in `<details>` elements. Alliances collapsed by default, Event Schedule expanded by default.

### Dynamic Default Model Config (0012)

`get_default_model_config()` accepts the state dict and generates a minimal model config with cross-faction matchup rows (top alliance per faction), so heuristic probability placeholder hints display immediately.
