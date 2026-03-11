# Tier-Aware Targeting — Web UI Design

## Overview

Expose `rank_aware` and `maximize_tier` targeting strategies in the web UI.
Changes are confined to `web/js/app.js` and `web/css/style.css`. No Python
or bridge changes needed — 0018 already added the new strategies and config
keys to validation and bridge allowed-key sets.

All changes follow existing patterns: template-literal HTML builders,
delegated event handling on `#model-form`, and `collectFormData()` →
`syncFormToJson()` → `scheduleModelValidation()` pipeline.

---

## 1. Shared Strategy Options Constant

### 1a. `app.js` — top-level constant

Replace inline `<option>` lists with a single source of truth. Defined near
the top of the file, after the `let` declarations:

```js
const STRATEGIES = [
    { value: "expected_value", label: "expected_value" },
    { value: "highest_spice", label: "highest_spice" },
    { value: "rank_aware", label: "rank_aware" },
    { value: "maximize_tier", label: "maximize_tier" },
];
```

### 1b. Helper: `strategyOptions()`

New helper that generates `<option>` tags from `STRATEGIES`, used everywhere
a strategy dropdown appears:

```js
function strategyOptions(selected, { includeDefault = false } = {}) {
    let html = "";
    if (includeDefault) {
        html += `<option value="" ${selected === "" ? "selected" : ""}>(use global default)</option>`;
    }
    for (const s of STRATEGIES) {
        html += `<option value="${s.value}" ${selected === s.value ? "selected" : ""}>${s.label}</option>`;
    }
    return html;
}
```

---

## 2. Update `strategyDropdown()`

Replace the existing function at line ~705:

```js
function strategyDropdown(selected, className) {
    return `
    <select class="${className}">
        ${strategyOptions(selected)}
    </select>`;
}
```

This is used by `defaultTargetRow()` and `eventTargetRow()` for "Use
strategy" dropdowns. No other changes needed in those functions — they
already call `strategyDropdown()`.

---

## 3. Update `buildGeneralSettings()`

### 3a. Strategy dropdown — use `strategyOptions()`

Replace the two hardcoded `<option>` tags inside `#form-strategy`:

```js
<select id="form-strategy" data-field="targeting_strategy">
    ${strategyOptions(strategy)}
</select>
```

### 3b. Maximize-tier conditional fields

Read saved values from `modelFormData` (preserved across strategy toggles):

```js
const topN = modelFormData.tier_optimization_top_n ?? 5;
const fallback = modelFormData.tier_optimization_fallback ?? "rank_aware";
const showTierOpts = strategy === "maximize_tier";
```

Insert a new block immediately after the `</select>` of the strategy
dropdown, still inside the same `<label>` wrapper's parent `form-grid`:

```js
<div id="maximize-tier-options" class="${showTierOpts ? "" : "hidden"}">
    <p class="help-text"><strong>Top N</strong> alliances (by spice within
        the attacking faction) evaluate each candidate target by simulating
        the rest of the war. Alliances outside the top N use the
        <strong>fallback strategy</strong>. Higher N = more accurate but
        slower Monte Carlo runs.</p>
    <label>Top N Alliances
        <input type="number" id="form-tier-top-n" value="${topN}"
               placeholder="5" min="1" step="1"
               data-field="tier_optimization_top_n">
    </label>
    <label>Fallback Strategy
        <select id="form-tier-fallback" data-field="tier_optimization_fallback">
            ${strategyOptions(fallback).replace(
                /option value="maximize_tier".*?<\/option>/s, ""
            )}
        </select>
    </label>
</div>
```

The fallback dropdown excludes `maximize_tier` (it would cause infinite
recursion in the engine). Strip it from the generated options with a
regex replace on the HTML string. Alternatively, use a dedicated
`fallbackStrategyOptions()` helper that filters `STRATEGIES` to exclude
`maximize_tier`:

```js
function fallbackStrategyOptions(selected) {
    return STRATEGIES
        .filter(s => s.value !== "maximize_tier")
        .map(s => `<option value="${s.value}" ${selected === s.value ? "selected" : ""}>${s.label}</option>`)
        .join("");
}
```

**Recommended:** use the dedicated helper — cleaner than regex on HTML.

### 3c. Help text update

Replace the strategy help text `<span class="help-text">` inside the
"Global Targeting Strategy" label:

```html
<span class="help-text">Fallback algorithm when no explicit target is set.
    <strong>Expected Value</strong> maximizes expected spice stolen.
    <strong>Highest Spice</strong> targets the richest defender.
    <strong>Rank Aware</strong> optimizes for tier/rank improvement rather
    than raw spice. <strong>Maximize Tier</strong> runs forward simulations
    of the remaining war for the top N alliances to find the target yielding
    the best final tier.</span>
```

---

## 4. Update `buildFactionTargeting()`

Replace the three hardcoded `<option>` tags in each faction row's
`<select>`:

```js
<select data-field="faction_targeting_strategy" data-faction="${esc(faction)}">
    ${strategyOptions(val, { includeDefault: true })}
</select>
```

No other changes to this function.

---

## 5. Toggle Visibility on Strategy Change

### 5a. `attachFormHandlers()` — new change handler

Add a clause to the existing delegated `change` listener on the form
(line ~785). Insert after the existing `dt-type` toggle block:

```js
// Show/hide maximize_tier options when global strategy changes
if (e.target.id === "form-strategy") {
    const tierOpts = document.getElementById("maximize-tier-options");
    if (tierOpts) {
        tierOpts.classList.toggle("hidden", e.target.value !== "maximize_tier");
    }
}
```

This fires on every strategy dropdown change. The `hidden` class is
already defined in `style.css` as `display: none`.

### 5b. Value preservation

When the user switches away from `maximize_tier`, the fields are hidden
but their DOM elements remain with current values. When `collectFormData()`
runs, it skips the tier fields (see §6b). When the user switches back,
the fields reappear with their previous values intact — no extra storage
needed.

When the form is fully rebuilt via `buildModelForm()` → `buildGeneralSettings()`,
the values are read from `modelFormData` which retains them (see §6c).

---

## 6. Update `collectFormData()`

### 6a. Location

In the `collectFormData()` function (line ~900), after the existing
general-settings block that reads seed and strategy.

### 6b. Conditional emission

```js
// Tier optimization fields (only when maximize_tier is active)
if (data.targeting_strategy === "maximize_tier") {
    const topNVal = document.getElementById("form-tier-top-n")?.value;
    if (topNVal !== "" && topNVal != null) {
        data.tier_optimization_top_n = parseInt(topNVal, 10);
    }
    const fallbackVal = document.getElementById("form-tier-fallback")?.value;
    if (fallbackVal) {
        data.tier_optimization_fallback = fallbackVal;
    }
}
```

When the strategy is not `maximize_tier`, neither key appears in the
generated JSON. The backend validation rejects these keys when the
strategy is not `maximize_tier`, so this is required for correctness,
not just cleanliness.

### 6c. Stash values for rebuild

The existing flow is: `collectFormData()` overwrites `modelFormData`
with the collected `data` dict (line ~1084). This means when strategy
is not `maximize_tier`, the tier fields vanish from `modelFormData`.

To preserve values across toggles, stash them before overwriting:

```js
// At the top of collectFormData(), before building `data`:
const _savedTierTopN = modelFormData?.tier_optimization_top_n;
const _savedTierFallback = modelFormData?.tier_optimization_fallback;
```

Then after the main collection, before `modelFormData = data`:

```js
// Preserve tier fields in modelFormData even when not emitted to JSON,
// so rebuilding the form restores them.
if (data.targeting_strategy !== "maximize_tier") {
    if (_savedTierTopN != null) data._tier_optimization_top_n = _savedTierTopN;
    if (_savedTierFallback != null) data._tier_optimization_fallback = _savedTierFallback;
}
```

Then in `buildGeneralSettings()`, read from both keys:

```js
const topN = modelFormData.tier_optimization_top_n
          ?? modelFormData._tier_optimization_top_n
          ?? 5;
const fallback = modelFormData.tier_optimization_fallback
              ?? modelFormData._tier_optimization_fallback
              ?? "rank_aware";
```

The underscore-prefixed keys are UI-only — they never appear in the JSON
textarea because `syncFormToJson()` serializes `modelFormData` which for
non-maximize_tier strategies won't have the non-prefixed keys. Wait — that
won't work because `modelFormData = data` includes the underscore keys
and `JSON.stringify` would emit them.

**Better approach:** Store stashed values in a separate module-level
variable, not in `modelFormData`:

```js
let _tierOptsStash = { top_n: 5, fallback: "rank_aware" };
```

In `collectFormData()`, always read the DOM values into the stash (when
elements exist):

```js
const topNEl = document.getElementById("form-tier-top-n");
const fallbackEl = document.getElementById("form-tier-fallback");
if (topNEl?.value) _tierOptsStash.top_n = parseInt(topNEl.value, 10);
if (fallbackEl?.value) _tierOptsStash.fallback = fallbackEl.value;
```

Only emit to `data` when the strategy is `maximize_tier`:

```js
if (data.targeting_strategy === "maximize_tier") {
    data.tier_optimization_top_n = _tierOptsStash.top_n;
    data.tier_optimization_fallback = _tierOptsStash.fallback;
}
```

In `buildGeneralSettings()`:

```js
const topN = modelFormData.tier_optimization_top_n ?? _tierOptsStash.top_n;
const fallback = modelFormData.tier_optimization_fallback ?? _tierOptsStash.fallback;
```

This keeps `modelFormData` clean (only real config keys) while preserving
UI state across toggles.

---

## 7. JSON-to-Form Sync

### 7a. `syncJsonToForm()` — no changes needed

The existing flow parses JSON into `modelFormData` and calls
`buildModelForm()`. Since `buildGeneralSettings()` reads
`tier_optimization_top_n` and `tier_optimization_fallback` from
`modelFormData`, uploaded/pasted JSON with these fields will
automatically populate the form and show the conditional section
(because `strategy === "maximize_tier"` controls visibility).

### 7b. Stash initialization from loaded JSON

When JSON is loaded (upload, URL hash, or toggle), update the stash:

```js
// In syncJsonToForm(), after modelFormData = parsed:
if (parsed.tier_optimization_top_n != null) {
    _tierOptsStash.top_n = parsed.tier_optimization_top_n;
}
if (parsed.tier_optimization_fallback != null) {
    _tierOptsStash.fallback = parsed.tier_optimization_fallback;
}
```

This ensures the stash is seeded from loaded configs, so switching away
and back preserves the loaded values.

---

## 8. Targeting Resolution Deep-Dive Update

In `buildEventTargets()` (line ~416), update the "How targeting
resolution works" `<details>` block. Add a note after the ordered list:

```html
<p class="help-text">Available strategies at every level:
    <code>expected_value</code>, <code>highest_spice</code>,
    <code>rank_aware</code>, <code>maximize_tier</code>.</p>
```

Insert after the existing closing `</p>` of the "Within each
algorithm..." paragraph.

---

## 9. Performance Warning

### 9a. Warning banner HTML

Add a hidden div inside the run controls area. In `index.html`, after
the MC run button:

```html
<div id="mc-tier-warning" class="tier-warning hidden">
    <strong>Note:</strong> <code>maximize_tier</code> runs forward
    simulations for each targeting decision, which increases Monte Carlo
    run time significantly. Consider using <code>rank_aware</code> for
    faster results, or reducing iterations.
</div>
```

### 9b. Show/hide logic

In `runMonteCarlo()`, before `setRunning(true)`, check if
`maximize_tier` is active at any level:

```js
function hasMaximizeTier(modelDict) {
    if (modelDict.targeting_strategy === "maximize_tier") return true;
    const fts = modelDict.faction_targeting_strategy || {};
    if (Object.values(fts).includes("maximize_tier")) return true;
    // Not checking event_targets/default_targets — too granular to warn about
    return false;
}
```

```js
const warningEl = document.getElementById("mc-tier-warning");
if (warningEl) {
    warningEl.classList.toggle("hidden", !hasMaximizeTier(modelDict));
}
```

The warning appears each time MC is run with `maximize_tier` active, and
hides when it's not. Simple — no localStorage dismissal needed. If the
user sees it, they've already clicked Run and will see it alongside the
progress/results.

### 9c. CSS

```css
.tier-warning {
    margin: 0.5rem 0;
    padding: 0.5rem 0.75rem;
    background: var(--bg-secondary, #2a2a2a);
    border-left: 3px solid #e6a817;
    font-size: 0.85rem;
}
```

Uses the existing `--bg-secondary` variable and a yellow/amber accent
to distinguish from error messages (which use red).

---

## 10. Files Changed

| File | Changes |
|------|---------|
| `web/js/app.js` | Add `STRATEGIES` constant and `strategyOptions()` / `fallbackStrategyOptions()` helpers. Update `strategyDropdown()`, `buildGeneralSettings()`, `buildFactionTargeting()`. Add `maximize-tier-options` conditional block. Add strategy-change handler in `attachFormHandlers()`. Update `collectFormData()` with tier field collection + stash. Update `syncJsonToForm()` with stash init. Update targeting resolution deep-dive text. Add `hasMaximizeTier()` check in `runMonteCarlo()`. |
| `web/css/style.css` | Add `.tier-warning` style. |
| `web/index.html` | Add `#mc-tier-warning` div in run controls section. |

---

## 11. Implementation Order

| Step | What | Complexity |
|------|------|------------|
| 1 | `STRATEGIES` constant + `strategyOptions()` + `fallbackStrategyOptions()` | Trivial |
| 2 | Update `strategyDropdown()` to use `strategyOptions()` | Trivial |
| 3 | Update `buildGeneralSettings()` — new options + conditional block + help text | Moderate |
| 4 | Update `buildFactionTargeting()` — use `strategyOptions()` | Trivial |
| 5 | Add change handler in `attachFormHandlers()` | Low |
| 6 | `_tierOptsStash` + `collectFormData()` updates | Moderate |
| 7 | `syncJsonToForm()` stash seeding | Low |
| 8 | Targeting resolution deep-dive text | Trivial |
| 9 | Performance warning (HTML + JS + CSS) | Low |

Steps 1–4 deliver visible dropdown changes. Step 5–6 make the conditional
fields functional. Steps 7–9 are polish.
