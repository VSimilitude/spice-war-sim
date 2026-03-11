# Tier-Aware Targeting — Web UI Requirements

## Goal

Expose the `rank_aware` and `maximize_tier` targeting strategies (0018) in the
web UI model config editor. Users should be able to select the new strategies
from dropdowns, configure `maximize_tier`-specific options, and see updated help
text explaining the new options — all without touching raw JSON.

---

## 1. Strategy Dropdowns — Add New Options

### 1a. Global Targeting Strategy

The `General Settings` strategy dropdown (currently `expected_value`,
`highest_spice`) gains two new options:

| Value | Display Label |
|-------|---------------|
| `expected_value` | expected_value |
| `highest_spice` | highest_spice |
| `rank_aware` | rank_aware |
| `maximize_tier` | maximize_tier |

Order matters — list from simplest to most advanced.

### 1b. Faction Targeting Strategy

Each faction row's strategy dropdown (currently `(use global default)`,
`expected_value`, `highest_spice`) gains the same two new options:

| Value | Display Label |
|-------|---------------|
| *(empty)* | (use global default) |
| `expected_value` | expected_value |
| `highest_spice` | highest_spice |
| `rank_aware` | rank_aware |
| `maximize_tier` | maximize_tier |

### 1c. Default Targets — "Use strategy" dropdown

When a default target row's type is set to "Use strategy", the strategy
dropdown gains the two new options.

### 1d. Event Targets — "Use strategy" dropdown

Same as 1c, for per-event target overrides.

---

## 2. Maximize Tier Options — Conditional Fields

### 2a. Show when `maximize_tier` is selected

When the **global** targeting strategy is set to `maximize_tier`, show two
additional fields in General Settings immediately below the strategy dropdown:

| Field | Control | Default | Description |
|-------|---------|---------|-------------|
| Top N Alliances | Number input (min 1, step 1) | 5 | Number of top alliances (by faction spice) that use forward projection |
| Fallback Strategy | Dropdown: `rank_aware`, `expected_value`, `highest_spice` | rank_aware | Strategy for alliances outside the top N |

### 2b. Hide when other strategies selected

When the global strategy is anything other than `maximize_tier`, these two
fields must be hidden and their values excluded from the generated JSON. If the
user switches away from `maximize_tier`, the fields disappear but their values
are preserved in memory so switching back restores them.

### 2c. Validation

- `tier_optimization_top_n` must be a positive integer. Show inline error for
  0 or negative values.
- `tier_optimization_fallback` must be one of `expected_value`, `highest_spice`,
  `rank_aware`. The dropdown enforces this — no free-text input.
- Backend validation via `validateModelConfig` already rejects these fields
  when the global strategy is not `maximize_tier`.

---

## 3. JSON Serialization

### 3a. Emit new fields

When `maximize_tier` is the global strategy, the form-to-JSON serializer emits:

```json
{
  "targeting_strategy": "maximize_tier",
  "tier_optimization_top_n": 5,
  "tier_optimization_fallback": "rank_aware"
}
```

### 3b. Omit when defaults

- Omit `tier_optimization_top_n` if value equals the default (5) — or always
  emit when `maximize_tier` is active. Either approach is acceptable since the
  backend handles defaults.
- Omit `tier_optimization_fallback` if value equals the default (`rank_aware`)
  — same caveat.

**Recommended:** Always emit both fields when `maximize_tier` is active, for
clarity.

### 3c. JSON-to-form sync

When loading JSON (via upload, import, or JSON toggle) that contains
`tier_optimization_top_n` or `tier_optimization_fallback`, populate the
corresponding form fields and ensure the `maximize_tier` conditional section is
visible.

---

## 4. Help Text Updates

### 4a. Strategy help text (General Settings)

Replace the current strategy help text:

> Fallback algorithm when no explicit target is set. **Expected Value**
> maximizes expected spice stolen; **Highest Spice** targets the richest
> defender.

With:

> Fallback algorithm when no explicit target is set. **Expected Value**
> maximizes expected spice stolen. **Highest Spice** targets the richest
> defender. **Rank Aware** optimizes for tier/rank improvement rather than raw
> spice. **Maximize Tier** runs forward simulations of the remaining war for
> the top N alliances to find the target yielding the best final tier.

### 4b. Maximize tier conditional help

When the `maximize_tier` fields are visible, show a brief help blurb:

> **Top N** alliances (by spice within the attacking faction) evaluate each
> candidate target by simulating the rest of the war. Alliances outside the
> top N use the **fallback strategy**. Higher N = more accurate but slower
> Monte Carlo runs.

### 4c. Targeting resolution deep-dive

Update the "How targeting resolution works" collapsible in Event Targets to
mention the new strategies as valid values at each level. No structural change
needed — just ensure the text doesn't imply only two strategies exist.

---

## 5. Performance Warning

### 5a. Show warning for maximize_tier + Monte Carlo

When the user clicks "Run Monte Carlo" with `maximize_tier` as the global (or
any faction-level) strategy, show an inline warning near the run button:

> **Note:** `maximize_tier` runs forward simulations for each targeting
> decision, which increases Monte Carlo run time significantly. Consider using
> `rank_aware` for faster results, or reducing iterations.

This is informational only — do not block the run.

### 5b. Dismiss behavior

The warning appears once per session (localStorage flag) or once per run
configuration change. It should not repeatedly nag.

---

## 6. Scope

### In scope
- `web/js/app.js` — Strategy dropdown options, conditional `maximize_tier`
  fields, form-to-JSON and JSON-to-form sync, help text updates, performance
  warning
- `web/css/style.css` — Styling for conditional fields and warning banner
  (if needed)

### Out of scope
- Python engine changes (already implemented in 0018)
- Bridge changes (already implemented in 0018)
- CLI changes
- Changes to results display
- Mobile-specific layouts

---

## 7. Testing (manual)

### Strategy selection
- Select each of the 4 strategies in the global dropdown — JSON updates
  correctly
- Select `rank_aware` / `maximize_tier` in faction targeting dropdown — JSON
  includes the value under `faction_targeting_strategy`
- Add a default target row with type "Use strategy" and select `rank_aware` —
  JSON emits `{"strategy": "rank_aware"}`
- Add an event target row with type "Use strategy" and select `maximize_tier`
  — JSON emits `{"strategy": "maximize_tier"}`

### Conditional fields
- Select `maximize_tier` — Top N and Fallback fields appear
- Change Top N to 3 — JSON shows `"tier_optimization_top_n": 3`
- Change Fallback to `expected_value` — JSON shows
  `"tier_optimization_fallback": "expected_value"`
- Switch strategy to `rank_aware` — Top N and Fallback fields disappear; JSON
  no longer contains `tier_optimization_*` keys
- Switch back to `maximize_tier` — fields reappear with previously set values

### JSON round-trip
- Upload a JSON file containing `maximize_tier` config — form shows
  `maximize_tier` selected with correct Top N and Fallback values
- Toggle to JSON view, edit `tier_optimization_top_n` to 7, toggle back —
  form shows 7
- Toggle to JSON view, change strategy to `expected_value`, toggle back —
  conditional fields hidden

### Help text
- Verify updated strategy description mentions all 4 strategies
- Verify `maximize_tier` conditional help appears/disappears with the fields

### Performance warning
- Select `maximize_tier`, click Run Monte Carlo — warning appears
- Select `rank_aware`, click Run Monte Carlo — no warning
- Select `maximize_tier` via faction targeting (not global), click Run Monte
  Carlo — warning appears
