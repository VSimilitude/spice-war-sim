# Strategy Exploration Tools — Requirements

## Goal

Four features to make model comparison and "what-if" scenario exploration
faster and less manual.

---

## Feature A: Faction-Level Targeting Strategy

### Motivation

Currently `targeting_strategy` is global — setting it to `"highest_spice"`
affects both factions. To make only Scarlet Legion use `highest_spice` while
Golden Tribe uses the default, you'd need 19 individual `default_targets`
entries. A per-faction setting eliminates this.

### Model Config

New optional key `faction_targeting_strategy`:

```json
{
  "faction_targeting_strategy": {
    "Scarlet Legion": "highest_spice"
  }
}
```

Values are the same as `targeting_strategy`: `"expected_value"` or
`"highest_spice"`.

### Resolution Order (updated)

For each attacker in a given event:

1. `event_targets[event_number][attacker_id]` — most specific
2. `default_targets[attacker_id]` — global per-alliance
3. `faction_targeting_strategy[attacker_faction]` — per-faction
4. `targeting_strategy` — global default algorithm

### Validation

- Keys in `faction_targeting_strategy` must match a faction present in the
  state file's alliances.
- Values must be one of the valid strategy names.

### Tests

| # | Test | Validates |
|---|------|-----------|
| A1 | **Faction strategy applied** | SL alliances use `highest_spice` when `faction_targeting_strategy` sets it, GT alliances use default |
| A2 | **Per-alliance override wins** | `default_targets` entry for an SL alliance overrides `faction_targeting_strategy` |
| A3 | **Event override wins** | `event_targets` entry overrides `faction_targeting_strategy` |
| A4 | **Global fallback** | Faction not in `faction_targeting_strategy` falls through to `targeting_strategy` |
| A5 | **Both factions configured** | Each faction can have a different strategy |
| A6 | **Validation: unknown faction** | Faction name not in alliances raises error |
| A7 | **Validation: invalid strategy** | Invalid strategy value raises error |

---

## Feature B: Wildcard Battle Outcome Overrides

### Motivation

The `battle_outcome_matrix` requires specifying every attacker→defender pair.
To model "Ghst wins all attacks," you'd need an entry for Ghst against every
GT alliance on every day. Wildcard support (`"*"`) lets you express this
naturally inside the existing matrix structure.

### Model Config

The existing `battle_outcome_matrix` gains support for `"*"` as a wildcard
at the defender position (attacker default) and at the attacker position
(defender default):

```json
{
  "battle_outcome_matrix": {
    "wednesday": {
      "Ghst": {
        "*": {"full_success": 1.0},
        "RAG3": {"custom": 1.0, "custom_theft_percentage": 15}
      }
    },
    "saturday": {
      "Ghst": {"*": {"full_success": 1.0}},
      "*": {"Ghst": {"full_success": 0.0, "partial_success": 0.0}},
      "VON": {"Ghst": {"full_success": 1.0}}
    }
  }
}
```

- `"Ghst": {"*": {...}}` — outcome when Ghst attacks any defender not
  explicitly listed under Ghst for that day.
- `"*": {"Ghst": {...}}` — outcome when any attacker not explicitly listed
  attacks Ghst on that day.

The probability format is identical to existing pairings (`full_success`,
`partial_success`, `custom`, `custom_theft_percentage`).

### Resolution Order (for outcome lookup)

For a battle on a given day between attacker A and defender D:

1. **Exact pairing:** `matrix[day][A][D]` — most specific, always wins
2. **Attacker default:** `matrix[day][A]["*"]` — A's catch-all for any defender
3. **Defender default:** `matrix[day]["*"][D]` — catch-all for anyone attacking D
4. **Heuristic fallback** — power-based formula

Each level is tried only if the previous did not match.

**Specificity rule:** an explicit entry always beats a wildcard. In the
example above, `"VON": {"Ghst": {"full_success": 1.0}}` overrides
`"*": {"Ghst": {...}}` when VON attacks Ghst, because the VON→Ghst pairing
is more specific than the catch-all.

### Competing Wildcards

If a battle between A and D would match **both** an attacker default
(`matrix[day][A]["*"]`) and a defender default (`matrix[day]["*"][D]`), this
is ambiguous. Rather than inventing a precedence rule, validation rejects
this at load time and requires the user to add an explicit
`matrix[day][A][D]` entry to disambiguate.

**Example that fails validation:**

```json
{
  "wednesday": {
    "Ghst": {"*": {"full_success": 1.0}},
    "*": {"VON": {"full_success": 0.0, "partial_success": 0.0}}
  }
}
```

Ghst attacking VON matches both wildcards. Fix by adding an explicit pairing:

```json
{
  "wednesday": {
    "Ghst": {
      "*": {"full_success": 1.0},
      "VON": {"full_success": 1.0}
    },
    "*": {"VON": {"full_success": 0.0, "partial_success": 0.0}}
  }
}
```

Now Ghst→VON uses the explicit entry. All other attackers against VON use
the defender default. Ghst against anyone else uses the attacker default.

### Validation

- `"*"` is reserved — cannot be used as an actual alliance ID.
- Wildcard pairing probabilities follow the same rules as regular pairings
  (sum ≤ 1.0, `custom` requires `custom_theft_percentage`, etc.).
- **Competing wildcard check:** for each day, for each attacker A that has a
  `"*"` defender default, and each defender D that appears under the `"*"`
  attacker default — if there is no explicit `matrix[day][A][D]` entry,
  raise a validation error identifying the ambiguous pairing and suggesting
  the user add an explicit entry.

### Tests

| # | Test | Validates |
|---|------|-----------|
| B1 | **Attacker default applied** | Ghst with `"*": {full_success: 1.0}` gets full_success against every opponent on that day |
| B2 | **Defender default applied** | `"*": {"VON": {full: 0, partial: 0}}` causes all attackers to fail against VON |
| B3 | **Exact pairing wins over attacker default** | Ghst has `"*"` catch-all + explicit `"RAG3"` entry — RAG3 pairing uses the explicit entry |
| B4 | **Exact pairing wins over defender default** | `"*": {"Ghst": fail}` + explicit `"VON": {"Ghst": full}` — VON→Ghst uses explicit entry |
| B5 | **Heuristic fallback** | Alliance with no wildcard or explicit entry uses power-based heuristic |
| B6 | **Custom outcome in wildcard** | `"*": {custom: 1.0, custom_theft_percentage: 15}` works |
| B7 | **Different days independent** | Wildcard on wednesday doesn't affect saturday lookups |
| B8 | **Validation: competing wildcards rejected** | Attacker default + defender default overlap without explicit pairing raises error |
| B9 | **Validation: competing wildcards with explicit pairing OK** | Same overlap but with explicit pairing passes validation |
| B10 | **Validation: wildcard probabilities** | Same probability rules as regular pairings (sum ≤ 1.0, custom requires theft %) |
| B11 | **ESV uses wildcards** | Expected value targeting incorporates wildcard entries when computing ESV |
| B12 | **Multi-attacker averaging with wildcards** | Multiple attackers with wildcard entries are averaged correctly |

---

## Feature C: Comparative Monte Carlo

### Motivation

Comparing scenarios currently requires running separate MCs, then manually
extracting and diffing results. A dedicated comparison mode runs N models
against the same state and shows deltas side-by-side.

### CLI

New script: `scripts/compare_models.py`

```
usage: compare_models.py STATE_FILE MODEL_FILE [MODEL_FILE ...]
                         [-n NUM] [--base-seed SEED]
                         [--alliance AID [...]]
                         [--output PATH] [--quiet]
```

| Argument | Default | Description |
|---|---|---|
| `STATE_FILE` | *(required)* | Path to initial state JSON |
| `MODEL_FILE` | *(1+ required)* | Paths to model config JSONs |
| `-n` | `1000` | Iterations per model |
| `--base-seed` | `0` | Starting seed (same for all models) |
| `--alliance` | *(all)* | Filter output to these alliances (repeatable) |
| `--output` | *(none)* | Write JSON comparison to file |
| `--quiet` | `false` | Suppress stdout summary |

### Stdout Output

```
Comparative Monte Carlo — 1000 iterations, 3 models

Model files:
  [A] model_base.json
  [B] model_highest_spice.json
  [C] model_split_targets.json

Tier 1 Distribution:
              [A]       [B]       [C]
Ghst       12.2%     83.3%     72.8%
 UTW       45.9%      9.4%     14.1%
SPXP       35.0%      1.0%      0.0%
RAG3        6.9%      6.1%     13.1%

Mean Spice:
              [A]           [B]           [C]
Ghst     8,378,805     8,371,653     8,378,805
 UTW     8,425,224     6,284,109     7,106,503
...
```

Alliances are sorted by first model's T1 probability descending, then by
mean spice descending.

### JSON Output (`--output`)

```json
{
  "num_iterations": 1000,
  "base_seed": 0,
  "models": [
    {"file": "model_base.json", "label": "A"},
    {"file": "model_highest_spice.json", "label": "B"},
    {"file": "model_split_targets.json", "label": "C"}
  ],
  "results": {
    "Ghst": {
      "A": {"tier_distribution": {...}, "spice_stats": {...}},
      "B": {"tier_distribution": {...}, "spice_stats": {...}},
      "C": {"tier_distribution": {...}, "spice_stats": {...}}
    }
  }
}
```

### Tests

| # | Test | Validates |
|---|------|-----------|
| C1 | **Two models compared** | Runs two models, output shows both columns side-by-side |
| C2 | **Three+ models** | Runs three models, one column each |
| C3 | **Same model twice** | Identical values in both columns |
| C4 | **Alliance filter** | `--alliance Ghst --alliance UTW` shows only those two |
| C5 | **JSON output structure** | `--output` writes valid JSON matching spec |
| C6 | **Quiet mode** | `--quiet` suppresses stdout |
| C7 | **Same seeds across models** | All models use identical seed sequences |
| C8 | **Sort order** | Alliances sorted by first model's T1 desc, then mean spice desc |

---

## Feature D: Alliance-Filtered Output

### Motivation

The full 40-alliance output is noisy when you only care about 1–3 alliances.
A filter flag on both `run_monte_carlo.py` and `run_battle.py` shows only the
alliances you specify.

### CLI Changes

Both `run_monte_carlo.py` and `run_battle.py` gain a new repeatable flag:

```
--alliance AID    Show only this alliance in output (repeatable)
```

Examples:
```
run_monte_carlo.py state.json model.json --alliance Hot --alliance Ghst
run_battle.py state.json model.json --alliance Hot
```

### Behavior

- When `--alliance` is specified, all stdout tables (tier distribution, spice
  summary, event details, final results) show only the listed alliances.
- Alliances not in the filter are still simulated — only the output is
  filtered. The simulation is unchanged.
- If an `--alliance` value doesn't match any alliance ID in the state file,
  print a warning to stderr and continue.
- JSON output (`--output`) is also filtered to the specified alliances when
  the flag is present.
- When no `--alliance` flag is given, behavior is unchanged (show all).

### Tests

| # | Test | Validates |
|---|------|-----------|
| D1 | **Single alliance filter** | `--alliance Hot` shows only Hot in output |
| D2 | **Multiple alliance filter** | `--alliance Hot --alliance Ghst` shows both |
| D3 | **No filter shows all** | Omitting `--alliance` shows every alliance |
| D4 | **Unknown alliance warns** | `--alliance FAKE` prints warning, runs normally |
| D5 | **Simulation unchanged** | Filtered output produces same values as unfiltered for the selected alliances |
| D6 | **JSON output filtered** | `--output` JSON contains only filtered alliances |
| D7 | **run_battle.py support** | Filter works on single-run output too |

---

## Non-Goals

- **Sensitivity sweeps** — automatically varying a parameter across a range.
- **Conditional targeting rules** — "target X if they're in top 3."
- **Coalition modeling** — automatic optimal allocation across alliances.
- **Parallel/multiprocessing MC** — keep single-threaded for now.
