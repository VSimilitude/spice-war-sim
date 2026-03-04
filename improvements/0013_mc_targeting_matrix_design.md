# MC Targeting Matrix — Design

## Overview

Four changes across `monte_carlo.py`, `run_monte_carlo.py`, `bridge.py`, and
`app.js`. During Monte Carlo aggregation, count which defender each attacker
targeted in each iteration, convert to fractions, and display per-event
matrices in the CLI, JSON output, and web UI.

---

## 1. Data Collection

**File:** `src/spice_war/game/monte_carlo.py`

### 1a. New field on `MonteCarloResult`

Add a `targeting_counts` field — a nested dict:
`dict[str, dict[str, Counter[str]]]` mapping
event number (str) → attacker_id → Counter of defender_ids.

```python
targeting_counts: dict[str, dict[str, Counter[str]]] = field(default_factory=dict)
```

### 1b. New `targeting_matrix()` method

Add a method that converts raw counts to fractions (count / num_iterations).
Returns `dict[str, dict[str, dict[str, float]]]` — event number →
attacker_id → {defender_id: fraction}. Omit zero-count pairings (they
won't appear in the Counter anyway).

```python
def targeting_matrix(self) -> dict[str, dict[str, dict[str, float]]]:
    matrix = {}
    for event_num, attackers in self.targeting_counts.items():
        matrix[event_num] = {}
        for attacker_id, defender_counts in attackers.items():
            matrix[event_num][attacker_id] = {
                def_id: count / self.num_iterations
                for def_id, count in defender_counts.items()
            }
    return matrix
```

### 1c. Collect data in MC loop

After line 66 (`war_result = simulate_war(...)`), iterate over
`war_result["event_history"]` and increment targeting counters:

```python
for event in war_result["event_history"]:
    event_num = str(event["event_number"])
    if event_num not in result.targeting_counts:
        result.targeting_counts[event_num] = {}
    for attacker_id, defender_id in event["targeting"].items():
        if attacker_id not in result.targeting_counts[event_num]:
            result.targeting_counts[event_num][attacker_id] = Counter()
        result.targeting_counts[event_num][attacker_id][defender_id] += 1
```

---

## 2. CLI Output

**File:** `scripts/run_monte_carlo.py`

### 2a. Pass `schedule` to `_print_summary()`

Update the call at line 51 and the function signature at line 59 to accept
`schedule: list` so event headings can include attacker faction and day.

### 2b. Build a power lookup

Inside `_print_summary()`, build a power map from the `alliances` list for
sorting matrix rows/columns:

```python
power_map = {a.alliance_id: a.power for a in alliances}
```

### 2c. Add `_print_targeting_matrices()` helper

Called at the end of `_print_summary()`, after the spice summary table. For
each event (in event-number order):

1. Get the event's targeting data from `result.targeting_matrix()`
2. Collect the set of attackers and defenders from the matrix
3. If `display_aids` is active, filter both sets; skip event if either is empty
4. Sort attackers and defenders by `power_map` descending
5. Print heading: `"Event N — [faction] attacks ([day])"`
6. Print matrix with defenders as column headers, attackers as row labels,
   cells showing `"XX.X%"` (or blank if no pairing)

To get event metadata (attacker_faction, day), use the `schedule` list —
event N corresponds to `schedule[N-1]`.

```python
def _print_targeting_matrices(
    alliances: list,
    schedule: list,
    result: MonteCarloResult,
    display_aids: list[str] | None = None,
) -> None:
    matrix = result.targeting_matrix()
    if not matrix:
        return

    power_map = {a.alliance_id: a.power for a in alliances}
    display_set = set(display_aids) if display_aids else None

    for event_num in sorted(matrix, key=int):
        event_data = matrix[event_num]
        idx = int(event_num) - 1
        event_cfg = schedule[idx]

        attackers = set(event_data.keys())
        defenders = set()
        for targets in event_data.values():
            defenders.update(targets.keys())

        if display_set:
            attackers &= display_set
            defenders &= display_set
        if not attackers or not defenders:
            continue

        sorted_attackers = sorted(attackers, key=lambda a: power_map.get(a, 0), reverse=True)
        sorted_defenders = sorted(defenders, key=lambda d: power_map.get(d, 0), reverse=True)

        print()
        print(f"Event {event_num} — {event_cfg.attacker_faction} attacks ({event_cfg.day})")

        name_w = max(len(a) for a in sorted_attackers)
        col_w = max(max(len(d) for d in sorted_defenders), 7)

        header = f"{'':>{name_w}}  " + "  ".join(f"{d:>{col_w}}" for d in sorted_defenders)
        print(header)

        for att in sorted_attackers:
            cells = []
            for def_ in sorted_defenders:
                frac = event_data.get(att, {}).get(def_, 0)
                cells.append(f"{frac * 100:>{col_w}.1f}%" if frac else f"{'':>{col_w}} ")
            print(f"{att:>{name_w}}  {'  '.join(cells)}")
```

---

## 3. JSON Output

### 3a. CLI JSON

**File:** `scripts/run_monte_carlo.py`

Pass `schedule` to `_write_json()`. Add a `targeting_matrix` key to the
output dict. Add a helper to filter both attacker and defender keys by the
active alliance set:

```python
def _filter_targeting_matrix(
    matrix: dict, aid_set: set[str],
) -> dict:
    filtered = {}
    for event_num, attackers in matrix.items():
        event_filtered = {}
        for att_id, defenders in attackers.items():
            if att_id not in aid_set:
                continue
            def_filtered = {d: f for d, f in defenders.items() if d in aid_set}
            if def_filtered:
                event_filtered[att_id] = def_filtered
        if event_filtered:
            filtered[event_num] = event_filtered
    return filtered
```

In `_write_json()`, compute the matrix and add to `data`:

```python
matrix = result.targeting_matrix()
data["targeting_matrix"] = _filter_targeting_matrix(matrix, aid_set)
```

### 3b. Web bridge

**File:** `src/spice_war/web/bridge.py` — `run_monte_carlo()` (line 305)

Add `targeting_matrix` to the response dict using the raw (unfiltered) matrix:

```python
"targeting_matrix": result.targeting_matrix(),
```

---

## 4. Web UI Display

**File:** `web/js/app.js`

### 4a. Render targeting matrices

In `renderMonteCarloResults()`, after the chart section (line 1400), iterate
over `result.targeting_matrix` and render one table per event.

Use `currentStateDict.event_schedule` for event metadata (attacker faction,
day). Build a power lookup from `currentStateDict.alliances` for sorting.

```javascript
if (result.targeting_matrix) {
    const powerMap = {};
    for (const a of currentStateDict.alliances) {
        powerMap[a.alliance_id] = a.power;
    }
    const byPowerDesc = (a, b) => (powerMap[b] || 0) - (powerMap[a] || 0);

    const eventNums = Object.keys(result.targeting_matrix).sort((a, b) => +a - +b);
    for (const eventNum of eventNums) {
        const eventData = result.targeting_matrix[eventNum];
        const idx = parseInt(eventNum, 10) - 1;
        const evCfg = currentStateDict.event_schedule[idx];

        let attackers = Object.keys(eventData);
        let defenders = new Set();
        for (const att of attackers) {
            for (const def_ of Object.keys(eventData[att])) defenders.add(def_);
        }
        defenders = [...defenders];

        if (allowed) {
            attackers = attackers.filter(a => allowed.has(a));
            defenders = defenders.filter(d => allowed.has(d));
        }
        if (!attackers.length || !defenders.length) continue;

        attackers.sort(byPowerDesc);
        defenders.sort(byPowerDesc);

        html += `<h3>Event ${esc(eventNum)} — ${esc(evCfg.attacker_faction)} attacks (${esc(evCfg.day)})</h3>`;
        html += "<table><tr><th></th>";
        for (const d of defenders) html += `<th>${esc(d)}</th>`;
        html += "</tr>";
        for (const att of attackers) {
            html += `<tr><td>${esc(att)}</td>`;
            for (const def_ of defenders) {
                const frac = (eventData[att] || {})[def_] || 0;
                html += `<td>${frac ? (frac * 100).toFixed(1) + "%" : ""}</td>`;
            }
            html += "</tr>";
        }
        html += "</table>";
    }
}
```

### 4b. Placement

The targeting matrix HTML is appended after the chart canvases but before
`container.innerHTML = html` (line 1402). This places it below the charts
in the rendered page, matching the requirement order.

### 4c. Alliance filter

The `allowed` set from `getFilteredAlliances()` (already computed at
line 1354) filters both attacker rows and defender columns.

---

## Files Changed

| File | Changes |
|------|---------|
| `src/spice_war/game/monte_carlo.py` | Add `targeting_counts` field, `targeting_matrix()` method, collect data in MC loop |
| `scripts/run_monte_carlo.py` | Add `_print_targeting_matrices()`, `_filter_targeting_matrix()`, pass `schedule` to summary/JSON functions, include matrix in JSON output |
| `src/spice_war/web/bridge.py` | Add `targeting_matrix` key to MC response |
| `web/js/app.js` | Render per-event targeting matrix tables after charts |

---

## Implementation Order

| Step | Requirement | Files | Complexity |
|------|-------------|-------|------------|
| 1 | Data collection | `monte_carlo.py` | Medium |
| 2 | CLI output | `run_monte_carlo.py` | Medium |
| 3 | JSON output (CLI + bridge) | `run_monte_carlo.py`, `bridge.py` | Low |
| 4 | Web UI display | `app.js` | Medium |

---

## Testing

- Run MC with default state and model — verify targeting matrices print after
  Spice Summary, one per event, with correct faction/day headings
- Verify rows/columns sorted by alliance power descending
- Run MC with `--alliance VON --alliance Ghst` — verify only those alliances
  appear as rows/columns; events with no matching attackers/defenders are
  skipped
- Run MC with `--quiet` — verify targeting matrices are suppressed
- Run MC with `--output` — verify JSON contains `targeting_matrix` key with
  structure `{event_num: {attacker: {defender: fraction}}}`
- Run MC with `--output --alliance VON` — verify JSON matrix is filtered
- Load web UI, run MC — verify targeting matrix tables appear after charts
- Apply Top 3 filter in web UI — verify matrix rows/columns are filtered
- Verify all fractions for a given attacker in a given event sum to 1.0
  (within rounding tolerance)
