# MC Targeting Matrix — Requirements

## Goal

Add a per-event attacker/defender targeting matrix to Monte Carlo simulation
output, showing the percentage of iterations in which each attacker targeted
each defender. Display in both the Python CLI output and the web UI.

---

## 1. Data Collection

During MC aggregation, count targeting pairings per event across all iterations.
For each event, record the fraction of iterations in which each attacker
targeted each defender. Only include pairings that occurred at least once.

---

## 2. Python CLI Output

### 2a. Print targeting matrix per event

After the existing Tier Distribution and Spice Summary tables, print a
targeting matrix for each event.

- One matrix per event
- Header shows event number, attacking faction, and day
- Attackers down the left side (rows), defenders across the top (columns)
- Both rows and columns sorted by alliance power (descending)
- Each cell shows the percentage of iterations with that pairing

### 2b. Respect --alliance filter

If `--alliance` filters are active, show only the filtered alliances as
rows/columns in the matrix. If no attackers or no defenders remain after
filtering for a given event, skip that event's matrix.

### 2c. Respect --quiet flag

The targeting matrices should be suppressed when `--quiet` is used, same as
the other summary tables.

---

## 3. JSON Output

### 3a. Include targeting matrix in JSON output

Add a `targeting_matrix` key to the JSON output (both `--output` file and
web bridge response). Keyed by event number (as string). Each entry maps
attacker_id → {defender_id: fraction}. Omit pairings with 0 occurrences.

### 3b. Respect --alliance filter in JSON

When `--alliance` filters are active, include only filtered alliances in the
matrix (both as attackers and defenders).

---

## 4. Web UI Display

### 4a. Render targeting matrices

After the existing Tier Distribution and Spice Statistics tables (and their
charts), render a targeting matrix table for each event.

Each table should have:
- A heading: "Event N — [Faction] attacks ([day])"
- Defenders as column headers, sorted by power descending
- Attackers as row labels, sorted by power descending
- Cells showing percentage values

### 4b. Apply existing alliance filter

The targeting matrices should respect the same result filter (All / Top 3 /
Top 5 / Top 10 per faction) used by the other MC results tables. Filter both
rows and columns.

---

## 5. Scope

### In scope
- `monte_carlo.py` — Data collection and `MonteCarloResult` changes
- `run_monte_carlo.py` — CLI output
- `bridge.py` — Web bridge response
- `app.js` — Web UI rendering

### Out of scope
- Changes to single-run output
- Changes to the targeting/reinforcement logic itself
