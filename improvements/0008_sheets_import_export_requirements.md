# Google Sheets Import/Export — Requirements

## Goal

Allow users to configure model files (battle outcome probabilities, targeting
overrides, etc.) in Google Sheets or a spreadsheet editor instead of editing
JSON by hand. Two new scripts:

1. **Template generator** — reads a state file and outputs a CSV pre-populated
   with alliance names, ready to paste into Google Sheets.
2. **Sheet importer** — reads a public Google Sheet URL or local CSV and
   converts it to model config JSON.

## Motivation

Model JSON files are tedious to author by hand. Alliance IDs must be typed
exactly, the nested `battle_outcome_matrix` structure is error-prone, and
there's no way to see all configurable fields at a glance. A spreadsheet
workflow lets users fill in a pre-populated template where alliance names are
already listed — they just enter probabilities and targeting overrides in the
blank cells.

---

## 1. Template Generator

### CLI

```
usage: generate_sheet_template.py STATE_FILE [--top N] [--output PATH]
```

| Argument | Default | Description |
|---|---|---|
| `STATE_FILE` | *(required)* | Path to initial state JSON |
| `--top N` | `6` | Number of top alliances per faction to include |
| `--output PATH` | stdout | Write CSV to file instead of stdout |

### Output Sections

The generated CSV contains these sections in order:

1. **Header** — title and description text (ignored by importer)
2. **Scalars** — `random_seed` (default `42`) and `targeting_strategy`
   (default `expected_value`), one per row as `key, value`
3. **default_targets** — description text, then a table with columns
   `alliance, type, value`. Pre-populated with top-N alliances per faction
   (type/value blank for user to fill in).
4. **event_targets** — description text, then a table with columns
   `event, alliance, type, value`. Pre-populated with top-N attacking
   alliances for each event in the schedule.
5. **battle_outcome_matrix** — 4 probability grids, one per
   (day, attacker_faction → defender_faction) combination. Grids appear in the
   same order as the `probability_grid.py` script: Wednesday grids first, then
   Saturday, with factions in sorted order within each day. Each grid consists
   of:
   - A title row: `Wednesday: Golden Tribe → Scarlet Legion`
   - A header row with defender alliance IDs as columns
   - Data rows with attacker alliance IDs as row labels and integer
     percentages (0–100) as cell values

   Cell values are **full_success probability only**, pre-populated with
   heuristic values using the existing formulas (`max(0, min(1, 2.5r - 2.0))`
   for Wednesday, `max(0, min(1, 3.25r - 3.0))` for Saturday, where
   `r = attacker_power / defender_power`). The model derives `partial_success`
   automatically via its legacy formula when only `full_success` is specified.
   Uses the same top-N alliance filtering as other sections.

### Alliance Ordering

Alliances are sorted by power descending within each faction. Factions appear
in the order they first occur in the state file.

---

## 2. Sheet Importer

### CLI

```
usage: import_sheet.py URL_OR_FILE --output PATH [--state-file PATH]
```

| Argument | Default | Description |
|---|---|---|
| `URL_OR_FILE` | *(required)* | Google Sheet URL or local CSV file path |
| `--output PATH` | *(required)* | Write model config JSON to this path |
| `--state-file PATH` | *(optional)* | State file for cross-validation of alliance IDs |

### Google Sheet URL Detection

URLs matching the pattern `/spreadsheets/d/<SHEET_ID>/` are recognized as
Google Sheets. The importer constructs an export URL
(`https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv`) and
fetches via `urllib`. All other inputs are treated as local file paths.

### Parsing Rules

The importer uses a state-machine approach to parse CSV rows:

- **Scalar keys** (`random_seed`, `targeting_strategy`) are recognized when
  cell A exactly matches a known key. Cell B is the value.
- **Section headers** (`default_targets`, `event_targets`) are recognized when
  cell A starts with a known section name. The next non-blank row is treated
  as column headers, then data rows follow until a blank row or a new section.
- **Grid title rows** are recognized when cell A matches the pattern
  `{Day}: {faction} → {faction}` (e.g. `Wednesday: Golden Tribe → Scarlet
  Legion`). This starts a new grid context, extracting the day name
  (lowercased). The next non-blank row is treated as the header row containing
  defender alliance IDs. Subsequent rows until a blank row or next section are
  data rows: cell A is the attacker alliance ID, remaining cells are
  full_success percentages.
- **All other rows** (title, descriptions, comments starting with `#`, blank
  rows) are skipped.

### Skip Rules

- `default_targets`: rows with blank `type` column are skipped.
- `event_targets`: rows with blank `type` column are skipped.
- **Probability grids**: blank/empty cells are omitted from the matrix (the
  model falls back to heuristic calculation at runtime). Integer percentages
  are converted to decimals by dividing by 100.

### Output Schema

The importer produces a dict matching the existing model JSON schema:

```json
{
  "random_seed": 42,
  "targeting_strategy": "expected_value",
  "default_targets": {
    "ALLIANCE_ID": {"target": "DEFENDER_ID"}
  },
  "event_targets": {
    "1": {
      "ALLIANCE_ID": {"target": "DEFENDER_ID"}
    }
  },
  "battle_outcome_matrix": {
    "wednesday": {
      "ATTACKER_ID": {
        "DEFENDER_ID": {
          "full_success": 0.45
        }
      }
    }
  }
}
```

Note: only `full_success` is populated from the grid. The model derives
`partial_success` automatically via its legacy formula when `partial_success`
is not explicitly specified.

### Cross-Validation

When `--state-file` is provided, the importer loads the state file and calls
`_check_model_references` from `validation.py` to verify all alliance IDs in
the model config exist in the state file. Exits with error on mismatch.

---

## 3. Tests

### Template

| # | Test | Validates |
|---|------|-----------|
| 1 | **Sections present** | Output contains all expected section markers |
| 2 | **Alliances sorted by power** | Within each faction, alliances appear in descending power order |
| 3 | **Top-N respected** | Passing `top_n=2` limits to 2 alliances per faction |
| 4 | **Descriptions included** | Descriptive text appears for each section |
| 5 | **Event targets correct attackers** | Each event lists only the attacking faction's alliances |
| 6 | **Probability grid structure** | 4 grids present with correct title rows, defender headers, and heuristic values |

### Importer

| # | Test | Validates |
|---|------|-----------|
| 7 | **Scalar parsing** | `random_seed` parsed as int, `targeting_strategy` as string |
| 8 | **default_targets parsing** | `target` and `strategy` types correctly parsed |
| 9 | **event_targets parsing** | Event number, alliance, type, value all captured |
| 10 | **Probability grid parsing** | Grid title rows recognized, day extracted, attacker/defender IDs and percentages parsed correctly |
| 11 | **Percentage-to-decimal conversion** | Integer percentages (0–100) converted to floats (0.0–1.0); blank cells omitted |
| 12 | **Blank row skipping** | Multiple blank rows between sections don't break parsing |
| 13 | **Description row skipping** | Free-text rows are ignored |
| 14 | **Empty input** | Empty CSV produces empty dict |
| 15 | **Google URL extraction** | Sheet ID extracted from URL, export URL constructed correctly |
| 16 | **Local file reading** | CSV file read and parsed correctly |

### Round-Trip

| # | Test | Validates |
|---|------|-----------|
| 17 | **Generate then import** | Template → fill values → import → correct model dict |
| 18 | **CSV serialization round-trip** | Template → write CSV → read CSV → import preserves values |

### CLI

| # | Test | Validates |
|---|------|-----------|
| 19 | **Template CLI basic run** | Generates output file with correct alliance names |
| 20 | **Template CLI invalid state** | Returns exit code 1 on bad state file |
| 21 | **Import CLI basic run** | Produces valid model JSON |
| 22 | **Import CLI with state validation** | Unknown alliance ID triggers validation error (exit 1) |
| 23 | **Import CLI missing input** | Nonexistent file returns exit code 1 |

---

## 4. Scope Exclusions

- **`partial_success` and `custom` outcomes** — not included in the grid
  workflow. The model derives `partial_success` automatically from
  `full_success` via its legacy formula. Users needing `custom` outcomes
  (with `custom_theft_percentage`) should edit the model JSON directly.
- **`damage_weights`** — not included in the template or importer. These are
  rarely configured and don't fit the tabular format well.
- **`event_reinforcements`** — not included for the same reason.
- **Authenticated Google Sheets** — only public sheets (or CSV export links)
  are supported. No OAuth flow.
- **Multi-sheet/tab support** — only the first sheet is exported from Google
  Sheets.
- **Changes to existing files** — all new code. Imports from existing modules
  but no modifications to them.
