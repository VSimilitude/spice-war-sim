# Web UI Table & Config Refinements — Requirements

## Goal

Improve table column ordering and content across results tables, fix battle
filtering to show complete battles, and replace the sample model config with
a minimal prepopulated outcome matrix.

---

## 1. Final Rankings Table: Move Rank Column

**Current column order:**
`Rank | Faction | Alliance | Tier | Final Spice`

**New column order:**
`Faction | Alliance | Rank | Tier | Final Spice`

Move the Rank column from the first position to between Alliance and Tier.

---

## 2. Spice Before/After Table: Reorder After Rank & Add Arrow Indicator

### 2a. Move After Rank column

**Current column order:**
`Faction | Alliance | Before Rank | Before | After | After Rank | Change`

**New column order:**
`Faction | Alliance | Before Rank | After Rank | Before | After | Change`

Move After Rank to be between Before Rank and Before Spice.

### 2b. Add rank change arrow indicator

Add an up/down/neutral arrow indicator to the After Rank column value:

| Condition | Arrow |
|-----------|-------|
| After Rank < Before Rank (improved) | Green up arrow |
| After Rank > Before Rank (worsened) | Red down arrow |
| After Rank == Before Rank (unchanged) | Grey neutral indicator (dash or horizontal arrow) |

The indicator should appear alongside the rank number in the After Rank cell
(e.g. `3 ↑` or `5 ↓`).

### 2c. Sort by After Rank

The Spice Before/After table should be sorted by After Rank (ascending), so
the highest-ranked alliance after the event appears first.

---

## 3. Targeting Table: Consolidate Bracket, Add Ranks

### 3a. Consolidate to single Bracket column

**Current column order:**
`Attacker | Attacker Bracket | Defender | Defender Bracket`

**New column order:**
`Bracket | Attacker | Attacker Rank | Defender | Defender Rank`

Since attacker and defender in the same targeting pair share a bracket,
consolidate into a single Bracket column as the first column.

### 3b. Add Attacker Rank and Defender Rank columns

Add the spice-based rank (before the event) for both the attacker and
defender. These use the same rank values as the "Before Rank" in the spice
table.

---

## 4. Battles: Show Complete Battles When Filtered

**Current behavior:**
When a filter is active (e.g. Top 3 per faction), the battle transfers table
filters out individual alliances that don't match the filter. This means you
can see a battle where some participants are missing from the transfers table.

**New behavior:**
If any alliance involved in a battle (attacker or defender) matches the
filter, show the entire battle including all participants in the transfers
table. The filter should only determine whether a battle is shown or hidden
as a whole — not which rows appear within it.

This applies to the transfers table within each battle detail. The existing
battle-level filter (which shows/hides entire battle blocks) already works
correctly and should remain unchanged.

---

## 5. Replace Sample Model Config with Minimal Prepopulated Matrix

### 5a. Remove the sample model config

The current default model config contains sample data across all sections
(targeting strategies, faction overrides, default targets, event targets,
reinforcements, outcome matrix, damage weights). This is no longer needed.

Replace it with a minimal config containing only the outcome matrix
(plus a random seed).

### 5b. Prepopulate with top-1 matchups

Prepopulate the battle outcome matrix with the top 1 alliance by power from
each faction targeting the top 1 alliance from the opposing faction, on both
days. Leave the probability fields empty (no values) so that the heuristic
hint placeholders are visible.

For the current default state this means:
- Top Golden Tribe by power: **VON** (19.1B)
- Top Scarlet Legion by power: **Ghst** (18.3B)

Prepopulated outcome matrix rows:

| Day | Attacker | Defender | Full % | Partial % |
|-----|----------|----------|--------|-----------|
| wednesday | VON | Ghst | *(empty)* | *(empty)* |
| wednesday | Ghst | VON | *(empty)* | *(empty)* |
| saturday | VON | Ghst | *(empty)* | *(empty)* |
| saturday | Ghst | VON | *(empty)* | *(empty)* |

### 5c. Dynamic generation from state

The prepopulated rows should be generated dynamically based on the current
state data (not hardcoded alliance IDs). Find the highest-power alliance in
each faction and generate the cross-faction matchups for all unique days in
the event schedule.

The default model config function already has access to the state (or the
generation can happen client-side after state is loaded). If generating
server-side, the function signature may need to accept the state as a
parameter.

### 5d. Minimal default config structure

The new default model config should contain only:

```json
{
    "random_seed": 42,
    "battle_outcome_matrix": {
        "wednesday": {
            "<top_faction_A>": {
                "<top_faction_B>": {}
            },
            "<top_faction_B>": {
                "<top_faction_A>": {}
            }
        },
        "saturday": {
            "<top_faction_A>": {
                "<top_faction_B>": {}
            },
            "<top_faction_B>": {
                "<top_faction_A>": {}
            }
        }
    }
}
```

All other sections (targeting strategies, default targets, event targets,
reinforcements, damage weights) should be omitted — they will use engine
defaults.

---

## 6. Implementation Priority

Recommended order:

1. **Issue 5** — Replace sample model config (independent of other changes)
2. **Issue 1** — Final rankings column reorder (simple)
3. **Issue 2** — Spice table reorder, arrows, sorting
4. **Issue 3** — Targeting table consolidation
5. **Issue 4** — Battle filter fix

---

## 7. Scope

### In scope
- `app.js` — Results rendering functions, default model config handling
- `bridge.py` — `get_default_model_config()` function
- `style.css` — Arrow indicator styling (if needed)

### Out of scope
- Python game engine changes
- Changes to form builder / validation logic
- Changes to Monte Carlo results tables
- Changes to URL sharing
