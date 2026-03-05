# CLI Reference

All scripts are run via `.venv/bin/python scripts/<script>.py`.

---

## run_battle.py

Run a single Spice Wars simulation.

```
.venv/bin/python scripts/run_battle.py <state_file> [model_file] [options]
```

| Argument | Description |
|---|---|
| `state_file` | Path to initial state JSON (required) |
| `model_file` | Path to model config JSON (optional — uses heuristic defaults if omitted) |
| `--seed N` | Override random seed |
| `--output PATH` | Write JSON replay log to file |
| `--alliance ID` | Show only this alliance in output (repeatable) |
| `--quiet` | Suppress stdout summary |

**Output:** Human-readable summary to stdout (initial state, per-event details, final rankings). Optional JSON replay log with `--output`.

---

## run_monte_carlo.py

Run Monte Carlo simulation across many seeds.

```
.venv/bin/python scripts/run_monte_carlo.py <state_file> [model_file] [options]
```

| Argument | Description |
|---|---|
| `state_file` | Path to initial state JSON (required) |
| `model_file` | Path to model config JSON (optional) |
| `-n`, `--num-iterations` | Number of simulation runs (default: 1000) |
| `--base-seed N` | Starting seed — each iteration uses `base_seed + i` (default: 0) |
| `--output PATH` | Write JSON results to file |
| `--alliance ID` | Show only this alliance in output (repeatable) |
| `--quiet` | Suppress summary tables |

**Output:** Tier distribution table, spice statistics table, and per-event targeting matrix to stdout. Optional JSON with full results via `--output`.

---

## compare_models.py

Compare multiple model configs via side-by-side Monte Carlo.

```
.venv/bin/python scripts/compare_models.py <state_file> <model_file> [model_file ...] [options]
```

| Argument | Description |
|---|---|
| `state_file` | Path to initial state JSON (required) |
| `model_files` | One or more model config JSON paths (required) |
| `-n`, `--num-iterations` | Iterations per model (default: 1000) |
| `--base-seed N` | Starting seed (default: 0) |
| `--alliance ID` | Filter output to this alliance (repeatable) |
| `--output PATH` | Write JSON results to file |
| `--quiet` | Suppress stdout |

**Output:** Side-by-side tier distribution and spice statistics, labeled [A], [B], [C]... All models use identical seed sequences for fair comparison.

---

## probability_grid.py

Display heuristic full-success probability grids for every attacker-defender pairing.

```
.venv/bin/python scripts/probability_grid.py <state_file>
```

| Argument | Description |
|---|---|
| `state_file` | Path to initial state JSON (required) |

**Output:** Four grids (one per day × attacker faction). Rows = attackers sorted by power, columns = defenders sorted by power, cells = integer percentage. Uses the same heuristic formulas as `ConfigurableModel._heuristic_probabilities`.

---

## generate_sheet_template.py

Generate a CSV template for model configuration from a state file.

```
.venv/bin/python scripts/generate_sheet_template.py <state_file> [options]
```

| Argument | Description |
|---|---|
| `state_file` | Path to initial state JSON (required) |
| `--top N` | Top N alliances per faction to include (default: 6) |
| `--output PATH` | Write CSV to file (default: stdout) |

**Output:** CSV pre-populated with alliance names, section structure, and heuristic probability values. Designed for import into Google Sheets for collaborative model configuration.

---

## import_sheet.py

Import a Google Sheet or local CSV file as model config JSON.

```
.venv/bin/python scripts/import_sheet.py <url_or_file> --output <path> [options]
```

| Argument | Description |
|---|---|
| `url_or_file` | Google Sheet URL or local CSV file path (required) |
| `--output PATH` | Write model config JSON to file (required) |
| `--state-file PATH` | State file for cross-validation of alliance IDs (optional) |

**Output:** Model config JSON file. Converts percentage values to decimals. Supports public Google Sheet URLs (auto-constructs CSV export URL) and local `.csv` files.

---

## build_web.sh

Package Python source code for the Pyodide web interface.

```
bash scripts/build_web.sh
```

No arguments. Bundles `src/spice_war/` into `web/python/spice_war.zip` (excluding `__pycache__` and `.pyc` files). Must be re-run after any Python source changes before deploying the web interface.
