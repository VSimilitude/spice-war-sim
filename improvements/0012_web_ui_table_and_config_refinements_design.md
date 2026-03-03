# Web UI Table & Config Refinements — Design

## Overview

Five changes to `app.js`, `bridge.py`, and `style.css`. Each section below
maps to the corresponding requirement.

---

## 1. Final Rankings Table: Move Rank Column

**File:** `web/js/app.js` — `renderSingleResults()` (lines 1208–1220)

Move the `Rank` column from position 1 to position 3 (between Alliance and
Tier).

### Current header (line 1209):

```javascript
html += "<table><tr><th>Rank</th><th>Faction</th><th>Alliance</th><th>Tier</th><th>Final Spice</th></tr>";
```

### New header:

```javascript
html += "<table><tr><th>Faction</th><th>Alliance</th><th>Rank</th><th>Tier</th><th>Final Spice</th></tr>";
```

### Current row (lines 1213–1218):

```javascript
html += `<tr>
    <td>${i + 1}</td>
    <td>${esc(factions[e.id] || "")}</td>
    <td>${esc(e.id)}</td>
    <td>${e.tier}</td>
    <td>${e.spice.toLocaleString()}</td>
</tr>`;
```

### New row:

```javascript
html += `<tr>
    <td>${esc(factions[e.id] || "")}</td>
    <td>${esc(e.id)}</td>
    <td>${i + 1}</td>
    <td>${e.tier}</td>
    <td>${e.spice.toLocaleString()}</td>
</tr>`;
```

---

## 2. Spice Before/After Table: Reorder, Arrows, Sort

**File:** `web/js/app.js` — `renderEventDetail()` (lines 1241–1259)

### 2a. Column reorder + arrow indicator

Move After Rank to be between Before Rank and Before Spice. Add a colored
arrow indicator showing rank change direction.

**Current header (lines 1242–1243):**

```javascript
html += "<tr><th>Faction</th><th>Alliance</th><th>Before Rank</th><th>Before</th>"
      + "<th>After</th><th>After Rank</th><th>Change</th></tr>";
```

**New header:**

```javascript
html += "<tr><th>Faction</th><th>Alliance</th><th>Before Rank</th><th>After Rank</th>"
      + "<th>Before</th><th>After</th><th>Change</th></tr>";
```

**Arrow indicator logic** — add a helper function:

```javascript
function rankChangeIndicator(beforeRank, afterRank) {
    if (afterRank < beforeRank) {
        return '<span class="rank-up">\u2191</span>';       // ↑ green
    } else if (afterRank > beforeRank) {
        return '<span class="rank-down">\u2193</span>';     // ↓ red
    }
    return '<span class="rank-same">\u2014</span>';         // — grey
}
```

Place this near the existing helper functions (`getAllianceFaction`,
`computeRanks`, etc.) around line 1141.

**New row cells** — replace the current row body (lines 1249–1256):

```javascript
const br = beforeRanks[id];
const ar = afterRanks[id];
html += `<tr>
    <td>${esc(factions[id] || "")}</td>
    <td>${esc(id)}</td>
    <td>${br}</td>
    <td>${ar} ${rankChangeIndicator(br, ar)}</td>
    <td>${before.toLocaleString()}</td>
    <td>${after.toLocaleString()}</td>
    <td>${sign}${change.toLocaleString()}</td>
</tr>`;
```

### 2b. CSS for arrow indicators

**File:** `web/css/style.css` — add after the existing result filter styles
(~line 394):

```css
/* Rank change indicators */
.rank-up {
    color: #28a745;
    font-weight: 600;
}

.rank-down {
    color: #dc3545;
    font-weight: 600;
}

.rank-same {
    color: #999;
}
```

### 2c. Sort by After Rank

Currently the spice table iterates `Object.entries(event.spice_before)` in
arbitrary insertion order (lines 1244–1258). Sort the entries by after rank.

**Replace the `for` loop opening** at line 1244 with a sorted iteration:

```javascript
const spiceEntries = Object.entries(event.spice_before)
    .sort((a, b) => afterRanks[a[0]] - afterRanks[b[0]]);
for (const [id, before] of spiceEntries) {
```

This replaces:

```javascript
for (const [id, before] of Object.entries(event.spice_before)) {
```

---

## 3. Targeting Table: Consolidate Bracket, Add Ranks

**File:** `web/js/app.js` — `renderEventDetail()` (lines 1261–1272)

Since every attacker–defender pair in the targeting table shares a bracket,
replace the two bracket columns with a single leading Bracket column and add
rank columns for both sides.

### Current header (line 1262):

```javascript
html += "<tr><th>Attacker</th><th>Attacker Bracket</th><th>Defender</th><th>Defender Bracket</th></tr>";
```

### New header:

```javascript
html += "<tr><th>Bracket</th><th>Attacker</th><th>Attacker Rank</th><th>Defender</th><th>Defender Rank</th></tr>";
```

### Current row (lines 1265–1269):

```javascript
html += `<tr>
    <td>${esc(att)}</td>
    <td>${bracketMap[att] || "\u2014"}</td>
    <td>${esc(def_)}</td>
    <td>${bracketMap[def_] || "\u2014"}</td>
</tr>`;
```

### New row:

```javascript
html += `<tr>
    <td>${bracketMap[att] || "\u2014"}</td>
    <td>${esc(att)}</td>
    <td>${beforeRanks[att] || "\u2014"}</td>
    <td>${esc(def_)}</td>
    <td>${beforeRanks[def_] || "\u2014"}</td>
</tr>`;
```

The `beforeRanks` map is already computed at line 1236 and contains the
spice-based rank for every alliance going into the event. The bracket is the
same for attacker and defender in a pair (by construction of the bracket
system), so `bracketMap[att]` is used for the single column.

---

## 4. Battles: Show Complete Battles When Filtered

**File:** `web/js/app.js` — `renderEventDetail()` (lines 1274–1306)

The battle-level filter at line 1277 already correctly shows/hides entire
battles:

```javascript
if (allowed && !battleAlliances.some(id => allowed.has(id))) continue;
```

The problem is at line 1295 inside the transfers table, where individual
transfer rows are filtered out:

```javascript
if (allowed && !allowed.has(id)) continue;
```

### Fix

Remove the per-row filter on line 1295. When a battle passes the
battle-level filter, all transfer rows are shown.

**Delete this line:**

```javascript
                if (allowed && !allowed.has(id)) continue;
```

No other changes needed — the battle-level filter (line 1277) already
ensures only relevant battles are shown.

---

## 5. Replace Sample Model Config

Two changes: update the Python bridge function, and handle empty probability
objects in the JS form builder.

### 5a. Update `get_default_model_config()` in bridge.py

**File:** `src/spice_war/web/bridge.py` — `get_default_model_config()`
(lines 177–243)

Change the function to accept the state dict, find the top alliance per
faction by power, and generate cross-faction matchups for all unique days.

```python
def get_default_model_config(state_dict: dict | None = None) -> dict:
    config = {"random_seed": 42}

    if not state_dict:
        return config

    alliances = state_dict.get("alliances", [])
    events = state_dict.get("event_schedule", [])
    if not alliances or not events:
        return config

    # Find top alliance per faction by power
    top_by_faction: dict[str, str] = {}
    max_power: dict[str, int] = {}
    for a in alliances:
        faction = a.get("faction", "")
        power = a.get("power", 0)
        if faction not in max_power or power > max_power[faction]:
            max_power[faction] = power
            top_by_faction[faction] = a["alliance_id"]

    faction_list = list(top_by_faction.keys())
    if len(faction_list) != 2:
        return config

    top_a = top_by_faction[faction_list[0]]
    top_b = top_by_faction[faction_list[1]]

    # Build matrix for each unique day with empty probability objects
    days = list(dict.fromkeys(e.get("day", "") for e in events))
    matrix = {}
    for day in days:
        matrix[day] = {
            top_a: {top_b: {}},
            top_b: {top_a: {}},
        }

    config["battle_outcome_matrix"] = matrix
    return config
```

### 5b. Update PyBridge to pass state to `getDefaultModelConfig`

**File:** `web/js/pyodide-loader.js` — line 53

```javascript
// Before:
getDefaultModelConfig: () => callBridge("get_default_model_config"),

// After:
getDefaultModelConfig: (state) => callBridge("get_default_model_config", state || null),
```

### 5c. Update DOMContentLoaded to pass state

**File:** `web/js/app.js` — lines 40–45

```javascript
// Before:
const defaultModel = PyBridge.getDefaultModelConfig();

// After:
const defaultModel = PyBridge.getDefaultModelConfig(defaultState);
```

The shared-URL path (lines 59–62) does not need changes — it loads its own
model config from the URL payload.

### 5d. Handle empty probability objects in form builder

**File:** `web/js/app.js` — `buildOutcomeMatrix()` (lines 442–446)

Currently the form builder unconditionally calls `.toFixed(1)` on
probability values, which would produce `NaN` for empty objects:

```javascript
const full = (probs.full_success * 100).toFixed(1);
const partial = (probs.partial_success * 100).toFixed(1);
```

**Replace with null-safe formatting:**

```javascript
const full = probs.full_success != null
    ? (probs.full_success * 100).toFixed(1) : "";
const partial = probs.partial_success != null
    ? (probs.partial_success * 100).toFixed(1) : "";
```

This matches the pattern already used for `custom` and `custom_theft` on
lines 444–446, and ensures empty probability objects render as blank inputs
where heuristic placeholders will show.

---

## Implementation Order

| Step | Requirement | Files | Complexity |
|------|-------------|-------|------------|
| 1 | Issue 5 — Model config | `bridge.py`, `pyodide-loader.js`, `app.js` | Medium |
| 2 | Issue 1 — Rankings reorder | `app.js` | Trivial |
| 3 | Issue 2 — Spice table | `app.js`, `style.css` | Low |
| 4 | Issue 3 — Targeting table | `app.js` | Low |
| 5 | Issue 4 — Battle filter | `app.js` | Trivial (delete one line) |

---

## Files Changed

| File | Changes |
|------|---------|
| `web/js/app.js` | Reorder columns in 3 tables, add `rankChangeIndicator()`, sort spice entries, delete transfer filter line, null-safe probability formatting, pass state to model config |
| `web/css/style.css` | Add `.rank-up`, `.rank-down`, `.rank-same` classes |
| `src/spice_war/web/bridge.py` | Rewrite `get_default_model_config()` to accept state and generate dynamic matchups |
| `web/js/pyodide-loader.js` | Pass state parameter to `getDefaultModelConfig` |

---

## Testing

- Load the page — model config form should show 4 outcome matrix rows
  (VON↔Ghst on wednesday and saturday) with empty values and heuristic
  placeholders visible
- Run a single simulation — verify column ordering in all 3 tables
- Verify rank arrows appear with correct colors in spice table
- Verify spice table is sorted by after rank
- Verify targeting table shows single Bracket column with attacker/defender
  ranks
- Apply Top 3 filter — verify battles show all participants when any match
- Verify shared URL still works (loads model config from URL, not defaults)
