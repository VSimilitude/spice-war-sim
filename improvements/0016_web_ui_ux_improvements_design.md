# Web UI UX Improvements — Design

## Overview

Two small UX changes to the web interface: (1) default the MC result filter
to "Top 10" instead of "All", preserving any manual override until page
reload; (2) make the Alliances and Event Schedule sections inside the game
state editor collapsible, with Alliances collapsed by default.

Both changes are JS/HTML-only — no Python or CSS changes required. The
existing `<details>` pattern already used by the model form and the Edit JSON
toggle provides the collapsible mechanism. The filter default is a one-line
initializer change plus updating which HTML button starts with the `active`
class.

---

## 1. Default Result Filter to Top 10

### 1a. `web/js/app.js` — initial `resultFilter` variable (line 21)

Change the default from `"all"` to `"top10"`:

```javascript
let resultFilter = "top10";
```

### 1b. `web/index.html` — filter button markup (lines 88–91)

Move the `active` class from the "All" button to the "Top 10" button:

```html
<button class="filter-btn" data-filter="all">All</button>
<button class="filter-btn" data-filter="top3">Top 3 per faction</button>
<button class="filter-btn" data-filter="top5">Top 5 per faction</button>
<button class="filter-btn active" data-filter="top10">Top 10 per faction</button>
```

No other changes needed — the existing click handler already sets
`resultFilter` from `data-filter` and toggles the `active` class, so manual
overrides are preserved for the session lifetime.

---

## 2. Collapsible Game State Sections

### 2a. `web/js/app.js` — `renderStateSummary()` (line 131)

Wrap each section in a `<details>` element. Alliances gets no `open`
attribute (collapsed by default); Event Schedule gets `open`:

```javascript
function renderStateSummary(container, result) {
    let html = '<details><summary>Alliances</summary><table><tr>';
    html += "<th>ID</th><th>Faction</th><th>Power</th><th>Starting Spice</th><th>Daily Rate</th>";
    html += "</tr>";
    for (const a of result.alliances) {
        html += `<tr>
            <td>${esc(a.alliance_id)}</td>
            <td>${esc(a.faction)}</td>
            <td>${a.power}</td>
            <td>${a.starting_spice.toLocaleString()}</td>
            <td>${a.daily_rate.toLocaleString()}</td>
        </tr>`;
    }
    html += "</table></details>";

    html += '<details open><summary>Event Schedule</summary><table><tr>';
    html += "<th>#</th><th>Attacker</th><th>Day</th><th>Days Before</th>";
    html += "</tr>";
    for (const e of result.event_schedule) {
        html += `<tr>
            <td>${e.event_number}</td>
            <td>${esc(e.attacker_faction)}</td>
            <td>${esc(e.day)}</td>
            <td>${e.days_before}</td>
        </tr>`;
    }
    html += "</table></details>";

    container.innerHTML = html;
    container.classList.remove("hidden");
}
```

The `<details>` element provides the toggle indicator (browser-native
disclosure triangle) and collapsible behavior with no additional JS. The
existing CSS for `details` and `summary` (lines 162–172 in `style.css`)
already styles border, padding, cursor, and font-weight — these state
summary sections will inherit the same look as the Edit JSON toggle and
model form sections.

---

## Files Changed

| File | Changes |
|------|---------|
| `web/js/app.js` | Change `resultFilter` default to `"top10"`; wrap alliance and event tables in `<details>` elements in `renderStateSummary()` |
| `web/index.html` | Move `active` class from "All" filter button to "Top 10" filter button |

---

## Implementation Order

| Step | Area | Files | Complexity |
|------|------|-------|------------|
| 1 | Filter default | `app.js`, `index.html` | Trivial |
| 2 | Collapsible sections | `app.js` | Low |

---

## Testing (manual)

- Load page — Alliances section is collapsed, Event Schedule is expanded
- Click Alliances heading — section expands; click again — collapses
- Click Event Schedule heading — section collapses; click again — expands
- Run MC — results appear with Top 10 filter active (button highlighted)
- Select "All" filter — results update to show all alliances
- Re-run MC — filter stays on "All" (manual override preserved)
- Reload page — filter resets to Top 10, Alliances re-collapsed
