# Web Interface — Requirements

## Goal

Provide a browser-based interface for the Spice War simulation, allowing users to
configure game state and model parameters, run single simulations and Monte Carlo
analyses, and explore results interactively — without installing Python or using
the command line.

## Architecture

**Client-side only.** The entire simulation runs in the browser via
[Pyodide](https://pyodide.org/) (CPython compiled to WebAssembly). The app is
hosted as static files — no backend server required.

### Why Pyodide?

- The simulation is pure Python stdlib (no C extensions, no third-party deps).
- Runs complete in milliseconds, even for 1000-iteration Monte Carlo.
- Static hosting is free (Cloudflare Pages, Netlify, GitHub Pages) and
  maintenance-free.
- The existing Python codebase is used directly — no port or rewrite needed.

### Tradeoffs

- ~10 MB initial download for the Pyodide runtime (cached after first visit).
- A few seconds of load time on first page load.

---

## 1. Python Bridge Layer

**Location:** `src/spice_war/web/bridge.py`

A thin adapter module that exposes the simulation API without filesystem
dependencies. All functions accept and return JSON-serializable dicts/lists.

### Functions

#### `get_default_state() -> dict`

Returns a minimal example state dict that can be used as a starting point for
the state editor. Includes 4 alliances across 2 factions and a 4-event schedule.

#### `get_default_model_config() -> dict`

Returns an empty model config `{}` (all heuristics). This is the baseline —
users can add overrides from here.

#### `validate_state(state_dict: dict) -> dict`

Validates a state dict and returns either:
- `{"ok": True, "alliances": [...], "event_schedule": [...]}`
- `{"ok": False, "error": "description of validation failure"}`

Wraps the existing `validation.py` logic, adapted to accept a dict instead of
a file path.

#### `validate_model_config(model_dict: dict, state_dict: dict) -> dict`

Validates a model config against a state. Returns either:
- `{"ok": True, "config": {...}}`
- `{"ok": False, "error": "description of validation failure"}`

#### `run_single(state_dict: dict, model_dict: dict, seed: int | None = None) -> dict`

Runs one simulation. Returns:
```json
{
  "ok": true,
  "seed": 42,
  "final_spice": {"alliance_id": 12345, ...},
  "rankings": {"alliance_id": 1, ...},
  "event_history": [...]
}
```

Or `{"ok": false, "error": "..."}` on validation failure.

The `event_history` entries match the existing replay format (spice before/after,
targeting, battles with outcomes, transfers, etc.).

#### `run_monte_carlo(state_dict: dict, model_dict: dict, num_iterations: int = 1000, base_seed: int = 0) -> dict`

Runs a Monte Carlo analysis. Returns:
```json
{
  "ok": true,
  "num_iterations": 1000,
  "base_seed": 0,
  "tier_distribution": {
    "alliance_id": {"1": 0.62, "2": 0.28, "3": 0.08, "4": 0.02, "5": 0.0}
  },
  "spice_stats": {
    "alliance_id": {"mean": 4215300, "median": 4180000, "min": 2950000, "max": 5620000, "p25": 3800000, "p75": 4600000}
  },
  "raw_results": [
    {"seed": 0, "final_spice": {...}, "rankings": {...}},
    ...
  ]
}
```

Or `{"ok": false, "error": "..."}` on validation failure.

#### `import_csv(csv_text: str) -> dict`

Parses CSV text (from file upload or paste) into a model config dict. Wraps
the existing `sheets/importer.py` logic with string input instead of
file/URL. Returns:
- `{"ok": true, "config": {...}}`
- `{"ok": false, "error": "..."}`

#### `generate_template_csv(state_dict: dict, top_n: int = 6) -> dict`

Generates a CSV template string for model configuration. Wraps the existing
`sheets/template.py` logic. Returns:
- `{"ok": true, "csv": "..."}`
- `{"ok": false, "error": "..."}`

---

## 2. Web UI

**Location:** `web/` directory at project root

A single-page application with static HTML, CSS, and JavaScript. No build step
required (no bundler, no framework compilation). Framework choice is open (vanilla
JS, Preact via CDN, etc.) but must remain buildless — all assets servable as
static files.

### 2.1 Loading Screen

Shown while Pyodide downloads and initializes. Displays:
- App title
- A progress indicator (spinner or progress bar)
- Brief explanation of what's loading ("Loading Python runtime...")

### 2.2 State Editor

Allows users to configure the game state (alliances and event schedule).

**Inputs:**
- **JSON editor** — a text area pre-populated with the default state JSON.
  Users can edit directly or paste their own state file.
- **Upload button** — load a state JSON file from disk.
- **Validation feedback** — on any change, validate the state and display
  errors inline. Show a green/red status indicator.

**Display:**
- After successful validation, show a summary table of alliances (ID, faction,
  power, starting spice, daily rate) and event schedule (event #, attacker
  faction, day, days before).

### 2.3 Model Editor

Allows users to configure the battle model.

**Inputs:**
- **JSON editor** — a text area pre-populated with `{}` (empty = all
  heuristics). Users can edit directly or paste their own model config.
- **Upload button** — load a model config JSON file from disk.
- **CSV import** — upload a CSV file or paste CSV text, converting to model
  config via `import_csv()`.
- **Template download** — button to generate and download a CSV template
  (requires valid state).
- **Validation feedback** — validate against the current state and display
  errors inline.

### 2.4 Run Controls

**Single Run:**
- **Seed input** — optional integer field. If blank, uses the model config's
  `random_seed` (or 0 if unset).
- **Run button** — calls `run_single()` and displays results.

**Monte Carlo:**
- **Iterations input** — integer field, default 1000.
- **Base seed input** — integer field, default 0.
- **Run button** — calls `run_monte_carlo()` and displays results.

Both buttons are disabled while Pyodide is loading or while a run is in
progress. Display a spinner during execution.

### 2.5 Single Run Results

Shown after a single run completes. Two levels of detail:

**Summary view (default):**
- Final rankings table: alliance, tier, final spice — sorted by tier then
  spice descending.

**Detail view (click to expand):**
- Event-by-event accordion or tabs. Each event shows:
  - Event header: event #, attacker faction, day
  - Spice before/after table for all alliances
  - Targeting assignments (attacker → defender)
  - Per-battle details: attackers, defenders, outcome, probabilities,
    theft %, spice transfers

### 2.6 Monte Carlo Results

Shown after a Monte Carlo run completes.

**Summary view (default):**
- **Tier distribution table** — alliances as rows, tiers 1–5 as columns,
  cells show percentage. Sorted by most-likely tier then by tier-1
  probability descending.
- **Spice statistics table** — alliance, mean, median, min, max, p25, p75.

**Chart view:**
- **Tier distribution bar chart** — grouped or stacked bars showing tier
  probabilities per alliance.
- **Spice distribution box plot or histogram** — one per alliance, showing
  the spread of final spice outcomes.

Charts should use a lightweight library (e.g., Chart.js via CDN).

### 2.7 Export

- **Download results JSON** — export the full result dict (single run or MC)
  as a JSON file.
- **Download model config** — export the current model editor contents as a
  JSON file.

---

## 3. Pyodide Integration

**Location:** `web/js/pyodide-worker.js` (or inline in main JS)

### Initialization

1. Load Pyodide from CDN (`https://cdn.jsdelivr.net/pyodide/`).
2. After Pyodide initializes, load the `spice_war` package from local files
   (the `src/spice_war/` directory, bundled into the static site as a Python
   package or zip).
3. Import `spice_war.web.bridge` in the Pyodide context.
4. Signal the UI that the runtime is ready.

### Execution

JavaScript calls bridge functions via `pyodide.runPython()` or by accessing
the bridge module's functions directly through `pyodide.globals`. Inputs are
passed as JSON strings (serialized in JS, deserialized in Python). Outputs are
returned as JSON strings (serialized in Python, parsed in JS).

### Error Handling

Any uncaught Python exception during a bridge call should be caught at the
JS/Python boundary and returned as `{"ok": false, "error": "..."}` to the UI
layer.

---

## 4. Hosting & Deployment

### Static File Structure

```
web/
  index.html
  css/
    style.css
  js/
    app.js              # UI logic
    pyodide-loader.js   # Pyodide initialization and bridge calls
  python/
    spice_war/          # Copy of src/spice_war/ (or zip archive)
```

### Local Development

Run with any static file server:
```
cd web && python -m http.server 8000
```

### Production Hosting

Deploy the `web/` directory to any static hosting provider (Cloudflare Pages,
Netlify, GitHub Pages, etc.). Point the user's domain at the provider.

No server-side runtime, database, or environment variables required.

---

## 5. Tests

### Bridge Layer Tests

Run with pytest (standard Python test suite).

| # | Test | Validates |
|---|------|-----------|
| 1 | **`get_default_state` returns valid state** | Output passes `validate_state()` |
| 2 | **`get_default_model_config` returns valid config** | Output passes `validate_model_config()` with default state |
| 3 | **`validate_state` accepts good input** | Returns `ok: true` for sample state |
| 4 | **`validate_state` rejects bad input** | Returns `ok: false` with error for missing fields |
| 5 | **`validate_model_config` accepts good input** | Returns `ok: true` for sample model |
| 6 | **`validate_model_config` rejects bad input** | Returns `ok: false` for invalid references |
| 7 | **`run_single` produces correct structure** | Output contains `final_spice`, `rankings`, `event_history` |
| 8 | **`run_single` is deterministic** | Same inputs + seed → identical output |
| 9 | **`run_single` reports validation errors** | Bad state → `ok: false` |
| 10 | **`run_monte_carlo` produces correct structure** | Output contains `tier_distribution`, `spice_stats`, `raw_results` |
| 11 | **`run_monte_carlo` iteration count** | `len(raw_results) == num_iterations` |
| 12 | **`run_monte_carlo` tier distributions sum to 1** | All alliances' tier probabilities ≈ 1.0 |
| 13 | **`import_csv` round-trip** | `generate_template_csv` → `import_csv` → valid config |
| 14 | **`import_csv` error on bad CSV** | Malformed input → `ok: false` |

### Browser Tests

Manual testing checklist (not automated):

| # | Test | Validates |
|---|------|-----------|
| 15 | **Page loads and Pyodide initializes** | Loading screen appears, then editor becomes interactive |
| 16 | **Default state populates editors** | State and model editors show defaults on load |
| 17 | **State validation feedback** | Editing state JSON shows green/red indicator |
| 18 | **Single run produces results** | Click Run → results table appears |
| 19 | **Event detail drill-down** | Click event → battle details expand |
| 20 | **Monte Carlo produces results** | Click Run MC → tier table and charts appear |
| 21 | **File upload works** | Upload state/model JSON files → editors populate |
| 22 | **CSV import works** | Upload CSV → model editor populates with config |
| 23 | **Export downloads files** | Download buttons produce valid JSON files |

---

## 6. Scope Exclusions

- **Server-side execution** — all computation happens in the browser. No API
  server.
- **User accounts / persistence** — no login, no saved sessions. Users can
  export/import JSON files to preserve their work.
- **Google Sheets direct fetch** — CORS prevents `urllib` in the browser.
  Users download their sheet as CSV and upload it instead.
- **Real-time collaboration** — single-user tool.
- **Mobile optimization** — desktop-first. Should be usable on tablet but
  phone layout is not a priority.
- **Automated browser tests** — manual testing checklist only for the UI.
  The bridge layer is tested with pytest.
- **Build toolchain** — no bundler, transpiler, or framework build step.
  All JS/CSS served as authored.
