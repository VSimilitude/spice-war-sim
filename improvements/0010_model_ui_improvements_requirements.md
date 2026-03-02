# Model Config UI Improvements — Requirements

## Goal

Replace the raw JSON textarea for model configuration with structured, form-based
inputs. Make the Game State JSON editor collapsible (default collapsed) to reduce
page clutter while keeping the summary tables always visible.

## Problem

The current Model Config editor is a raw JSON textarea. Users must hand-edit
deeply nested JSON to configure targeting strategies, outcome probabilities,
reinforcements, and damage weights. This is error-prone and unintuitive,
especially for the `battle_outcome_matrix` which nests 4 levels deep
(`day → attacker → defender → probabilities`).

The Game State textarea also takes up significant vertical space even though
most users only need to load it once and then reference the summary tables.

---

## 1. Collapsible State Editor

**Current:** Game State section always shows the textarea + summary tables.

**New:**
- Wrap the textarea in a collapsible toggle, labeled "Edit JSON"
- Default to **collapsed**
- The summary tables (Alliances, Event Schedule) remain **always visible**
  outside the collapsible
- Upload JSON button remains always accessible (outside the collapsible)
- Validation badge and error messages remain outside the collapsible

**Layout:**

```
Game State [Valid]
[Upload JSON]

  Alliances table (always visible)
  Event Schedule table (always visible)

  > Edit JSON (collapsed by default)
    +------------------------+
    | { "alliances": [...]   |  (textarea, hidden until expanded)
    +------------------------+
```

---

## 2. Model Config — Sectioned Form

Replace the single textarea with a sectioned form. Each section maps to one
model config key. Use a vertical accordion layout so sections can be
expanded/collapsed independently.

### Current Model Config Keys

| Key | Type | Complexity |
|-----|------|-----------|
| `random_seed` | number | Trivial |
| `targeting_strategy` | `"expected_value"` \| `"highest_spice"` | Trivial |
| `faction_targeting_strategy` | `{ faction: strategy }` | Low |
| `default_targets` | `{ alliance: target_or_strategy }` | Medium |
| `event_targets` | `{ event#: { alliance: target_or_strategy } }` | Medium |
| `event_reinforcements` | `{ event#: { defender: reinforce_target } }` | Medium |
| `battle_outcome_matrix` | `{ day: { attacker: { defender: probs } } }` | High |
| `damage_weights` | `{ alliance: weight }` | Low |

### 2a. General Settings

Simple inline controls:

| Field | Control |
|-------|---------|
| Random Seed | Number input (placeholder "auto") |
| Global Targeting Strategy | Dropdown: `expected_value`, `highest_spice` |

### 2b. Faction Targeting Strategy

One row per faction (auto-populated from validated state):

| Faction | Strategy |
|---------|----------|
| Golden Tribe | Dropdown: `(use global default)`, `expected_value`, `highest_spice` |
| Scarlet Legion | Dropdown: `(use global default)`, `expected_value`, `highest_spice` |

- `(use global default)` means omit from config (no key emitted)

### 2c. Default Targets (per-alliance defaults)

A table showing configured overrides, with an "Add" button for new rows:

| Alliance | Type | Value |
|----------|------|-------|
| Dropdown (alliance list) | Dropdown: `Pin to target` / `Use strategy` | Alliance dropdown or strategy dropdown |
| [+ Add default target] | | |

- "Pin to target" emits `{ "target": "VON" }`
- "Use strategy" emits `{ "strategy": "expected_value" }`
- Each row has a remove (x) button
- Removing all rows omits `default_targets` from config

### 2d. Event Targets (per-event overrides)

One sub-section per event (from the event schedule):

```
Event 1 — Golden Tribe attacks (Wednesday)
  | Alliance | Type           | Value         |
  |----------|----------------|---------------|
  | UTW      | Pin to target  | Ghst          |
  | RAG3     | Use strategy   | highest_spice |
  | [+ Add]  |                |               |

Event 2 — Scarlet Legion attacks (Saturday)
  (no overrides configured)
  [+ Add override]
```

- Alliance dropdown only shows attacking-faction alliances for that event
- Defender/target dropdown shows opposing-faction alliances
- Empty events are omitted from config

### 2e. Event Reinforcements (per-event)

One sub-section per event:

```
Event 1 — Golden Tribe attacks (Wednesday)
  | Defender     | Reinforce (join battle of) |
  |--------------|---------------------------|
  | hAnA         | Ghst                      |
  | [+ Add]      |                           |
```

- Both dropdowns show defending-faction alliances for that event
- Empty events are omitted from config

### 2f. Battle Outcome Matrix

Editable table grouped by day:

```
Wednesday outcomes:
  Attacker  | Defender | Full %  | Partial % | Custom % | Custom Theft % |
  ----------|----------|---------|-----------|----------|----------------|
  VON       | Ghst     |  55     |  25       |          |                |
  VON       | * (any)  |  65     |  20       |          |                |
  UTW       | Ghst     |  45     |  30       |          |                |
  SPXP      | VON      |  40     |  30       |  10      |  8.0           |
  * (any)   | MY81     |  75     |  15       |          |                |
  [+ Add row]

Saturday outcomes:
  (similar)
  [+ Add row]
```

- Attacker/Defender dropdowns include all alliance IDs plus `* (any)` wildcard
- Probabilities entered as **percentages** (55 = 55%) — converted to decimals
  (0.55) in the JSON output
- Custom % and Custom Theft % columns show for any row; blank means not used
- Inline validation: full + partial + custom should be <= 100%
- Brief help text or tooltip explaining lookup priority:
  exact match → attacker wildcard → defender wildcard → heuristic fallback

### 2g. Damage Weights

Simple table:

| Alliance | Weight |
|----------|--------|
| Dropdown (alliance list) | Number input (0-1) |
| [+ Add] | |

- Brief help text: "Only relevant when multiple attackers target the same
  defender. Weights are normalized to sum to 1."
- Each row has a remove (x) button

---

## 3. Raw JSON Toggle

- A toggle button: "Edit as JSON" / "Back to form"
- When active, shows the raw JSON textarea (populated from current form state)
- Edits in JSON sync back to the form when switching back
- Serves as escape hatch for power users
- Upload JSON and Import CSV populate the JSON view, then sync to form

---

## 4. Form <-> JSON Synchronization

- Any form change regenerates the JSON and re-validates via
  `PyBridge.validateModelConfig`
- Switching from JSON view to form view: parse JSON and populate form fields
- If JSON contains values the form can't represent, show a warning and
  keep the JSON view active
- Same 300ms debounce on validation as current implementation

---

## 5. CSV Import / Upload Integration

- "Upload JSON" populates raw JSON, then syncs to form
- "Import CSV" populates raw JSON, then syncs to form
- "Download CSV Template" works as before
- These buttons remain visible regardless of form/JSON toggle state

---

## 6. Interaction Details

- **Accordion behavior**: Each model section (2a-2g) is a collapsible panel.
  Multiple can be open at once.
- **Add/remove rows**: "Add" button appends an empty row. Each row has a
  remove (x) button.
- **Alliance dropdowns**: Auto-populated from validated state. If state is
  invalid, show "Load valid state first" message.
- **Validation**: Real-time (300ms debounce). Status badge updates on form
  changes.
- **Empty defaults**: A new model config starts with just `random_seed` and
  `targeting_strategy: "expected_value"`. All other sections empty.
- **Percentage display**: Outcome matrix shown as percentages in form (55%)
  but stored as decimals in JSON (0.55).

---

## 7. Scope

### In scope
- All changes to `web/index.html`, `web/js/app.js`, `web/css/style.css`
- Collapsible state editor
- Form-based model config editor with all sections above
- Raw JSON toggle as fallback
- Form <-> JSON sync

### Out of scope
- Changes to the Python backend / `bridge.py`
- Drag-and-drop row reordering
- Undo/redo within the form
- Changes to the results display or run controls
- Mobile-specific layouts
