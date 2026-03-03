# MC Targeting Matrix — Design

## Overview

Four changes across `monte_carlo.py`, `run_monte_carlo.py`, `bridge.py`, and
`app.js`. During Monte Carlo aggregation, count which defender each attacker
targeted in each iteration, convert to fractions, and display per-event
matrices in the CLI, JSON output, and web UI.

---

## 1. Data Collection

**File:** `src/spice_war/game/monte_carlo.py`

Add a `targeting_counts` field to `MonteCarloResult` — a nested dict of
event number (str) → attacker_id → Counter of defender_ids.

Add a `targeting_matrix()` method that converts raw counts to fractions
(count / num_iterations).

In the MC loop, after each `simulate_war()` call, iterate over
`war_result["event_history"]` and increment the targeting counters from
each event's `targeting` dict.

---

## 2. CLI Output

**File:** `scripts/run_monte_carlo.py`

Pass `schedule` into `_print_summary()` so the targeting matrix headings
can include attacker faction and day.

Add a `_print_targeting_matrices()` function called at the end of
`_print_summary()`. For each event, print a heading
("Event N — [faction] attacks ([day])") followed by a matrix with defenders
as columns and attackers as rows, cells showing percentages.

Filter rows/columns by `display_aids` when `--alliance` is active. Skip
events with no matching attackers or defenders after filtering.

No change needed for `--quiet` — `_print_summary()` is already gated behind
the quiet check.

---

## 3. JSON Output

### 3a. CLI JSON

**File:** `scripts/run_monte_carlo.py`

Add a `targeting_matrix` key to the JSON output dict. Add a
`_filter_targeting_matrix()` helper that filters both attacker and defender
keys by the active alliance set. Pass `schedule` through to `_write_json()`.

### 3b. Web bridge

**File:** `src/spice_war/web/bridge.py`

Add `targeting_matrix` to the MC response dict using the raw
(unfiltered) matrix from `result.targeting_matrix()`.

---

## 4. Web UI Display

**File:** `web/js/app.js`

In `renderMonteCarloResults()`, after the chart section, iterate over
`result.targeting_matrix` and render one table per event. Each table has a
heading ("Event N — [faction] attacks ([day])"), defenders as column headers,
attackers as row labels, and percentage cells.

Use `currentStateDict.event_schedule` for event metadata. Filter attackers
and defenders using the existing `allowed` set from `getFilteredAlliances()`.

---

## Files Changed

| File | Changes |
|------|---------|
| `src/spice_war/game/monte_carlo.py` | Add `targeting_counts` field, `targeting_matrix()` method, collect data in MC loop |
| `scripts/run_monte_carlo.py` | Add `_print_targeting_matrices()`, `_filter_targeting_matrix()`, pass `schedule` to summary/JSON functions, include matrix in JSON output |
| `src/spice_war/web/bridge.py` | Add `targeting_matrix` key to MC response |
| `web/js/app.js` | Render per-event targeting matrix tables after charts |

---

## Testing

- Run MC with default state and model — verify targeting matrices print after
  Spice Summary, one per event, with correct faction/day headings
- Run MC with `--alliance VON --alliance Ghst` — verify only those alliances
  appear as rows/columns in the matrices; events with no matching
  attackers/defenders are skipped
- Run MC with `--quiet` — verify targeting matrices are suppressed
- Run MC with `--output` — verify JSON contains `targeting_matrix` key with
  correct structure (event_num → attacker → defender → fraction)
- Run MC with `--output --alliance VON` — verify JSON matrix is filtered
- Load web UI, run MC — verify targeting matrix tables appear after charts
- Apply Top 3 filter in web UI — verify matrix rows/columns are filtered
- Verify all fractions for a given attacker in a given event sum to 1.0
  (within rounding tolerance)
