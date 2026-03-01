# Strategy Exploration Tools — Design

## Overview

Four features for faster model comparison and scenario exploration. Feature A adds per-faction targeting strategy to the existing resolution hierarchy. Feature B adds wildcard support (`"*"`) to the battle outcome matrix. Feature C adds a comparative Monte Carlo CLI that runs multiple models side-by-side. Feature D adds alliance-filtered output to the existing CLIs. Changes touch three existing files, add one new script, and add one new test file.

---

## Feature A: Faction-Level Targeting Strategy

### 1. `src/spice_war/utils/validation.py`

Add `"faction_targeting_strategy"` to `_ALLOWED_MODEL_KEYS`.

```python
_ALLOWED_MODEL_KEYS = {
    "random_seed",
    "battle_outcome_matrix",
    "event_targets",
    "event_reinforcements",
    "damage_weights",
    "targeting_strategy",
    "default_targets",
    "faction_targeting_strategy",
}
```

New validation block in `_check_model_references()`, after the `targeting_strategy` check. Needs the set of known factions, so `load_model_config()` must pass faction information through. Two options:

**Option chosen:** Pass `alliances` (the full list) to `_check_model_references()` instead of just `alliance_ids`. Extract faction set inside the function.

```python
def load_model_config(
    path: str | Path | None,
    alliance_ids: set[str],
    alliances: list[Alliance] | None = None,
) -> dict:
```

The optional `alliances` parameter preserves backward compatibility — existing callers that only pass `alliance_ids` continue to work. When `alliances` is provided, `_check_model_references()` can derive the faction set.

```python
def _check_model_references(
    data: dict,
    alliance_ids: set[str],
    faction_ids: set[str] | None = None,
) -> None:
```

New validation block:

```python
# Check faction_targeting_strategy
faction_strategy = data.get("faction_targeting_strategy", {})
for faction_name, strat in faction_strategy.items():
    if faction_ids is not None and faction_name not in faction_ids:
        errors.append(
            f"faction_targeting_strategy references unknown faction "
            f"'{faction_name}'"
        )
    if strat not in _VALID_STRATEGIES:
        errors.append(
            f"faction_targeting_strategy[{faction_name}] must be one of "
            f"{sorted(_VALID_STRATEGIES)}, got '{strat}'"
        )
```

### 2. `src/spice_war/models/configurable.py`

Insert a new resolution level in `_resolve_attacker()` between level 2 (default_targets) and level 3 (global strategy). The method needs access to the attacker's faction, so look it up from `self.alliances`.

```python
def _resolve_attacker(
    self,
    attacker_id: str,
    event_overrides: dict,
    default_targets_config: dict,
    global_strategy: str,
    defender_ids: set[str],
) -> tuple[str | None, str]:
    """Returns (pinned_target_or_None, strategy)."""
    # Level 1: event_targets override
    if attacker_id in event_overrides:
        entry = event_overrides[attacker_id]
        target, strategy = self._parse_override(entry)
        if target is not None:
            if target in defender_ids:
                return target, ""
        else:
            return None, strategy

    # Level 2: default_targets
    if attacker_id in default_targets_config:
        entry = default_targets_config[attacker_id]
        target, strategy = self._parse_override(entry)
        if target is not None:
            if target in defender_ids:
                return target, ""
        else:
            return None, strategy

    # Level 3: faction_targeting_strategy  ← NEW
    faction_strategy = self.config.get("faction_targeting_strategy", {})
    attacker = self.alliances.get(attacker_id)
    if attacker and attacker.faction in faction_strategy:
        return None, faction_strategy[attacker.faction]

    # Level 4: global strategy
    return None, global_strategy
```

No other changes needed in this file for Feature A. The existing `generate_targets()` loop already calls `_resolve_attacker()` and dispatches based on the returned strategy string.

---

## Feature B: Wildcard Battle Outcome Overrides

### 1. `src/spice_war/utils/validation.py`

#### Allow `"*"` in matrix iteration

The existing `_check_model_references()` loop iterates over attacker and defender IDs in the matrix and validates them against `alliance_ids`. Add `"*"` as a valid key that bypasses the alliance-existence check, but still validate the pairing values.

```python
# Check battle_outcome_matrix
matrix = data.get("battle_outcome_matrix", {})
for day, attackers in matrix.items():
    for attacker_id, defenders in attackers.items():
        if attacker_id != "*" and attacker_id not in alliance_ids:
            errors.append(
                f"battle_outcome_matrix references unknown alliance "
                f"'{attacker_id}'"
            )
        for defender_id, pairing in defenders.items():
            if defender_id != "*" and defender_id not in alliance_ids:
                errors.append(
                    f"battle_outcome_matrix references unknown alliance "
                    f"'{defender_id}'"
                )

            # ... existing pairing validation (unchanged) ...
```

#### Competing wildcard check

After the existing pairing-level validation, add a new loop that checks for ambiguous wildcard pairings:

```python
# Check for competing wildcards
for day, attackers in matrix.items():
    wildcard_defender_entry = attackers.get("*", {})
    wildcard_defender_ids = set(wildcard_defender_entry.keys())

    for attacker_id, defenders in attackers.items():
        if attacker_id == "*":
            continue
        if "*" not in defenders:
            continue
        # attacker_id has a wildcard defender default
        # Check each defender in the "*" attacker default
        for defender_id in wildcard_defender_ids:
            if defender_id == "*":
                continue
            # Does this attacker have an explicit entry for this defender?
            if defender_id not in defenders:
                errors.append(
                    f"battle_outcome_matrix[{day}]: competing wildcards "
                    f"for {attacker_id} vs {defender_id} — "
                    f"{attacker_id} has '*' default and '*' has "
                    f"{defender_id} default. Add an explicit "
                    f"matrix[{day}][{attacker_id}][{defender_id}] entry "
                    f"to disambiguate."
                )
```

#### Reject `"*"` as an alliance ID

Add a check in `load_state()` during alliance parsing:

```python
if raw["alliance_id"] == "*":
    raise ValidationError(
        f"Alliance #{i + 1}: '*' is reserved and cannot be used as "
        f"an alliance_id"
    )
```

### 2. `src/spice_war/models/configurable.py`

#### Rework `_lookup_or_heuristic()`

Add wildcard resolution between exact pairing lookup and heuristic fallback.

```python
def _lookup_or_heuristic(
    self,
    matrix: dict,
    attacker: Alliance,
    defender: Alliance,
    day: str,
) -> dict[str, float]:
    day_matrix = matrix.get(day, {})

    # 1. Exact pairing
    attacker_entry = day_matrix.get(attacker.alliance_id, {})
    pairing = attacker_entry.get(defender.alliance_id)
    if pairing is not None:
        return self._parse_pairing(pairing)

    # 2. Attacker default (A → "*")
    wildcard_pairing = attacker_entry.get("*")
    if wildcard_pairing is not None:
        return self._parse_pairing(wildcard_pairing)

    # 3. Defender default ("*" → D)
    wildcard_attacker = day_matrix.get("*", {})
    defender_pairing = wildcard_attacker.get(defender.alliance_id)
    if defender_pairing is not None:
        return self._parse_pairing(defender_pairing)

    # 4. Heuristic fallback
    return self._heuristic_probabilities(attacker, defender, day)
```

Extract the pairing-parsing logic into a helper to avoid duplication:

```python
def _parse_pairing(self, pairing: dict) -> dict[str, float]:
    full = pairing.get("full_success", 0.0)
    result = {"full_success": full}

    if "partial_success" in pairing:
        result["partial_success"] = pairing["partial_success"]
    elif "custom" not in pairing:
        result["partial_success"] = (1.0 - full) * 0.4
    else:
        result["partial_success"] = 0.0

    if "custom" in pairing:
        result["custom"] = pairing["custom"]
        result["custom_theft_percentage"] = pairing["custom_theft_percentage"]

    return result
```

#### ESV with wildcards

`_calculate_esv()` calls `_lookup_or_heuristic()`, which now includes wildcard resolution. No changes needed — wildcards flow through automatically (tests B11–B12).

---

## Feature C: Comparative Monte Carlo

### New script: `scripts/compare_models.py`

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from spice_war.game.monte_carlo import run_monte_carlo
from spice_war.utils.validation import ValidationError, load_model_config, load_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare multiple model configs via Monte Carlo"
    )
    parser.add_argument("state_file", help="Path to initial state JSON")
    parser.add_argument(
        "model_files", nargs="+", metavar="MODEL_FILE",
        help="Paths to model config JSONs (1+)"
    )
    parser.add_argument(
        "-n", "--num-iterations", type=int, default=1000,
        help="Iterations per model"
    )
    parser.add_argument("--base-seed", type=int, default=0)
    parser.add_argument(
        "--alliance", action="append", dest="alliances", default=None,
        help="Filter output to this alliance (repeatable)"
    )
    parser.add_argument("--output", metavar="PATH")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        alliances, schedule = load_state(args.state_file)
        alliance_ids = {a.alliance_id for a in alliances}
        model_configs = []
        for path in args.model_files:
            config = load_model_config(path, alliance_ids, alliances)
            model_configs.append(config)
    except ValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Assign labels [A], [B], [C], ...
    labels = [chr(ord("A") + i) for i in range(len(model_configs))]

    # Run MC for each model with same seed sequence
    results = {}
    for label, config in zip(labels, model_configs):
        mc_result = run_monte_carlo(
            alliances, schedule, config,
            num_iterations=args.num_iterations,
            base_seed=args.base_seed,
        )
        results[label] = mc_result

    # Determine display alliances
    all_aids = [a.alliance_id for a in alliances]
    if args.alliances:
        display_aids = [aid for aid in args.alliances if aid in alliance_ids]
        unknown = [aid for aid in args.alliances if aid not in alliance_ids]
        for aid in unknown:
            print(f"Warning: unknown alliance '{aid}'", file=sys.stderr)
    else:
        display_aids = all_aids

    # Sort by first model's T1 probability desc, then mean spice desc
    first_label = labels[0]
    first_result = results[first_label]
    display_aids = sorted(
        display_aids,
        key=lambda aid: (
            first_result.tier_distribution(aid).get(1, 0),
            first_result.spice_stats(aid)["mean"],
        ),
        reverse=True,
    )

    if not args.quiet:
        _print_comparison(
            args, labels, results, display_aids, args.num_iterations
        )

    if args.output:
        _write_json(
            args.output, args, labels, results, display_aids,
            args.num_iterations,
        )

    return 0
```

#### `_print_comparison()`

```python
def _print_comparison(args, labels, results, display_aids, num_iterations):
    n_models = len(labels)
    print(
        f"Comparative Monte Carlo — {num_iterations} iterations, "
        f"{n_models} models"
    )
    print()

    print("Model files:")
    for label, path in zip(labels, args.model_files):
        print(f"  [{label}] {path}")
    print()

    name_width = max(len(aid) for aid in display_aids) if display_aids else 4

    # Tier 1 Distribution table
    print("Tier 1 Distribution:")
    header = f"{'':>{name_width}}  " + "  ".join(
        f"{'[' + label + ']':>9}" for label in labels
    )
    print(header)
    for aid in display_aids:
        parts = []
        for label in labels:
            t1 = results[label].tier_distribution(aid).get(1, 0)
            parts.append(f"{t1 * 100:>8.1f}%")
        print(f"{aid:>{name_width}}  {'  '.join(parts)}")
    print()

    # Mean Spice table
    print("Mean Spice:")
    header = f"{'':>{name_width}}  " + "  ".join(
        f"{'[' + label + ']':>13}" for label in labels
    )
    print(header)
    for aid in display_aids:
        parts = []
        for label in labels:
            mean = results[label].spice_stats(aid)["mean"]
            parts.append(f"{mean:>13,}")
        print(f"{aid:>{name_width}}  {'  '.join(parts)}")
```

#### `_write_json()`

```python
def _write_json(path, args, labels, results, display_aids, num_iterations):
    data = {
        "num_iterations": num_iterations,
        "base_seed": args.base_seed,
        "models": [
            {"file": f, "label": label}
            for f, label in zip(args.model_files, labels)
        ],
        "results": {},
    }

    for aid in display_aids:
        data["results"][aid] = {}
        for label in labels:
            data["results"][aid][label] = {
                "tier_distribution": {
                    str(tier): frac
                    for tier, frac in results[label]
                        .tier_distribution(aid).items()
                },
                "spice_stats": results[label].spice_stats(aid),
            }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
```

#### Notes

- Each model gets an independent `run_monte_carlo()` call with the same `base_seed` and `num_iterations`. The seed sequence is `base_seed + 0, base_seed + 1, ...` for every model, ensuring fair comparison.
- No changes to `run_monte_carlo()` or `MonteCarloResult` — the comparative logic is entirely in the new script.
- Labels are uppercase letters: A, B, C, ... (supports up to 26 models, more than enough).

---

## Feature D: Alliance-Filtered Output

### 1. `scripts/run_monte_carlo.py`

Add `--alliance` argument:

```python
parser.add_argument(
    "--alliance", action="append", dest="alliances", default=None,
    help="Show only this alliance in output (repeatable)"
)
```

Derive `display_aids` after loading:

```python
all_aids = [a.alliance_id for a in alliances]
alliance_id_set = {a.alliance_id for a in alliances}

if args.alliances:
    display_aids = [aid for aid in args.alliances if aid in alliance_id_set]
    unknown = [aid for aid in args.alliances if aid not in alliance_id_set]
    for aid in unknown:
        print(f"Warning: unknown alliance '{aid}'", file=sys.stderr)
else:
    display_aids = None  # means show all
```

Modify `_print_summary()` to accept an optional `display_aids` parameter. When provided, filter `sorted_aids` to only include those alliances:

```python
def _print_summary(
    alliances: list,
    result: MonteCarloResult,
    display_aids: list[str] | None = None,
) -> None:
    # ... header unchanged ...

    sorted_aids = sorted(
        [a.alliance_id for a in alliances],
        key=lambda aid: result.spice_stats(aid)["mean"],
        reverse=True,
    )
    if display_aids is not None:
        display_set = set(display_aids)
        sorted_aids = [aid for aid in sorted_aids if aid in display_set]

    # ... rest uses sorted_aids (unchanged) ...
```

Modify `_write_json()` similarly — filter alliance keys in the output dicts:

```python
def _write_json(
    path: str,
    result: MonteCarloResult,
    display_aids: list[str] | None = None,
) -> None:
    aid_set = set(display_aids) if display_aids else set(result.tier_counts)

    data = {
        "num_iterations": result.num_iterations,
        "base_seed": result.base_seed,
        "tier_distribution": {
            aid: {str(tier): frac for tier, frac in dist.items()}
            for aid, dist in result.rank_summary().items()
            if aid in aid_set
        },
        "spice_stats": {
            aid: result.spice_stats(aid)
            for aid in result.tier_counts
            if aid in aid_set
        },
        "raw_results": [
            {
                "seed": entry["seed"],
                "final_spice": {
                    k: v for k, v in entry["final_spice"].items()
                    if k in aid_set
                },
                "rankings": {
                    k: v for k, v in entry["rankings"].items()
                    if k in aid_set
                },
            }
            for entry in result.per_iteration
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
```

### 2. `scripts/run_battle.py`

Add `--alliance` argument:

```python
parser.add_argument(
    "--alliance", action="append", dest="alliances", default=None,
    help="Show only this alliance in output (repeatable)"
)
```

Derive `display_aids` and `display_set` the same way as in `run_monte_carlo.py` (with stderr warning for unknowns).

Pass to `_print_summary()`:

```python
def _print_summary(args, alliances, schedule, seed, result, display_aids=None):
```

Filter in two places:

1. **Initial state table:** filter `alliances` list for display.
2. **Final results table:** filter the `alliances` list.
3. **Per-event tables** (pre-battle spice, post-event spice, transfers): filter to `display_set`.

For bracket/targeting/battle detail blocks: show all battles (since context is needed), but filter the per-alliance lines within them. Alternatively, since battles always involve pairs, show a battle block only if at least one participant is in the filter. The simpler approach: show all event structure but filter individual alliance lines.

```python
if display_aids is not None:
    display_set = set(display_aids)
    show_alliances = [a for a in alliances if a.alliance_id in display_set]
else:
    show_alliances = alliances
```

Use `show_alliances` instead of `alliances` when iterating for display purposes (initial state, pre-battle spice, post-event spice, final results). The battle detail blocks are shown for all battles (they describe events, not alliances).

Similarly filter `_build_replay()` / JSON output:

```python
def _build_replay(alliances, schedule, seed, result, display_aids=None):
    aid_set = set(display_aids) if display_aids else {a.alliance_id for a in alliances}
    return {
        "seed": seed,
        "initial_state": {
            "alliances": [
                { ... }
                for a in alliances if a.alliance_id in aid_set
            ],
            # event_schedule unchanged
        },
        "events": result["event_history"],  # keep full event history
        "final_spice": {
            k: v for k, v in result["final_spice"].items()
            if k in aid_set
        },
        "rankings": {
            k: v for k, v in result["rankings"].items()
            if k in aid_set
        },
    }
```

### Notes

- Simulation runs unchanged — filtering is output-only.
- Unknown alliance IDs produce a warning to stderr but don't prevent execution.
- When `--alliance` is not given, behavior is identical to current (show all).
- Feature C (`compare_models.py`) gets `--alliance` built-in from the start (described in Feature C section above).

---

## Tests — `tests/test_strategy_exploration.py`

New test file covering all four features. Uses inline fixtures.

### Shared helpers

```python
from spice_war.models.configurable import ConfigurableModel
from spice_war.utils.data_structures import Alliance, GameState
from spice_war.utils.validation import ValidationError, load_model_config


def _make_alliances(specs):
    """Build alliances from (id, faction, power, starting_spice, daily_rate)."""
    return [
        Alliance(aid, faction, power, spice, rate)
        for aid, faction, power, spice, rate in specs
    ]

def _make_state(alliances, event_number=1, day="wednesday", spice_overrides=None):
    spice = {a.alliance_id: a.starting_spice for a in alliances}
    if spice_overrides:
        spice.update(spice_overrides)
    return GameState(
        current_spice=spice, brackets={},
        event_number=event_number, day=day,
        event_history=[], alliances=alliances,
    )
```

### Feature A tests

| # | Test | Implementation |
|---|------|----------------|
| A1 | **Faction strategy applied** | Config: `faction_targeting_strategy: {"red": "highest_spice"}`, global strategy `"expected_value"`. Two red attackers, two blue defenders. Red attackers should use `highest_spice`, blue attackers (if any) should use `expected_value`. Verify by constructing a scenario where `highest_spice` and `expected_value` produce different targets. |
| A2 | **Per-alliance override wins** | Config: `faction_targeting_strategy: {"red": "highest_spice"}`, `default_targets: {"A1": {"strategy": "expected_value"}}`. A1 (red) should use `expected_value`, not `highest_spice`. A2 (red) should use `highest_spice`. |
| A3 | **Event override wins** | Config: `faction_targeting_strategy: {"red": "highest_spice"}`, `event_targets: {"1": {"A1": {"strategy": "expected_value"}}}`. A1 in event 1 uses `expected_value`. A1 in event 2 uses `highest_spice` (faction level). |
| A4 | **Global fallback** | Config: `faction_targeting_strategy: {"red": "highest_spice"}`, `targeting_strategy: "expected_value"`. Blue attacker (not in `faction_targeting_strategy`) falls through to global `expected_value`. |
| A5 | **Both factions configured** | Config: `faction_targeting_strategy: {"red": "highest_spice", "blue": "expected_value"}`. Each faction uses its configured strategy. |
| A6 | **Validation: unknown faction** | Write temp JSON with `faction_targeting_strategy: {"unknown_faction": "highest_spice"}`. Call `load_model_config()`. Assert `ValidationError` mentioning `"unknown faction"`. |
| A7 | **Validation: invalid strategy** | Write temp JSON with `faction_targeting_strategy: {"red": "invalid"}`. Call `load_model_config()`. Assert `ValidationError` mentioning strategy name. |

### Feature B tests

| # | Test | Implementation |
|---|------|----------------|
| B1 | **Attacker default applied** | Matrix: `"wednesday": {"Ghst": {"*": {"full_success": 1.0}}}`. Call `determine_battle_outcome()` for Ghst attacking any defender on Wednesday. Assert full_success probability is 1.0. |
| B2 | **Defender default applied** | Matrix: `"wednesday": {"*": {"VON": {"full_success": 0.0, "partial_success": 0.0}}}`. Any attacker vs VON on Wednesday. Assert fail probability is 1.0. |
| B3 | **Exact pairing wins over attacker default** | Matrix: Ghst has `"*": {"full_success": 1.0}` and `"RAG3": {"full_success": 0.0}`. Ghst vs RAG3 uses explicit entry (0% full). Ghst vs others uses wildcard (100% full). |
| B4 | **Exact pairing wins over defender default** | Matrix: `"*": {"Ghst": {fail}}` + `"VON": {"Ghst": {full: 1.0}}`. VON vs Ghst uses explicit (100% full), others vs Ghst use wildcard (fail). |
| B5 | **Heuristic fallback** | No wildcard or explicit entry for a pairing. Assert probabilities match heuristic formula. |
| B6 | **Custom outcome in wildcard** | Matrix: `"Ghst": {"*": {"custom": 1.0, "custom_theft_percentage": 15}}`. Assert custom outcome probabilities returned. |
| B7 | **Different days independent** | Wildcard on Wednesday for Ghst. No entry on Saturday. Assert Saturday uses heuristic. |
| B8 | **Validation: competing wildcards rejected** | Matrix with `Ghst → "*"` and `"*" → VON` but no explicit `Ghst → VON`. Assert `ValidationError` with `"competing wildcards"`. |
| B9 | **Competing wildcards with explicit pairing OK** | Same as B8 but with explicit `Ghst → VON` entry. Assert validation passes. |
| B10 | **Validation: wildcard probabilities** | Wildcard pairing with sum > 1.0. Assert `ValidationError` with `"exceeding 1.0"`. |
| B11 | **ESV uses wildcards** | Attacker has `"*"` wildcard giving 100% full_success. Call `_calculate_esv()`. Assert ESV matches full-theft calculation (not heuristic). |
| B12 | **Multi-attacker averaging with wildcards** | Two attackers, one with wildcard, one with heuristic. Call `determine_battle_outcome()`. Assert combined probabilities reflect averaging of both. |

### Feature C tests

Tests call `compare_models.main()` directly, using fixture state and temp model files.

| # | Test | Implementation |
|---|------|----------------|
| C1 | **Two models compared** | Create two model files with different `targeting_strategy`. Run `main()` with both. Capture stdout. Assert both `[A]` and `[B]` columns present. |
| C2 | **Three+ models** | Three model files. Assert `[A]`, `[B]`, `[C]` all present. |
| C3 | **Same model twice** | Same file passed twice. Assert `[A]` and `[B]` columns have identical values. |
| C4 | **Alliance filter** | `--alliance Ghst --alliance UTW`. Assert only those two alliances appear in output. |
| C5 | **JSON output structure** | `--output path`. Load JSON. Assert keys: `num_iterations`, `base_seed`, `models`, `results`. Assert `models` has correct file/label pairs. Assert `results` has per-alliance per-model structure. |
| C6 | **Quiet mode** | `--quiet`. Capture stdout. Assert empty. |
| C7 | **Same seeds across models** | Two models, `--output path`. Load JSON. For each iteration, confirm both models used the same seed (implicit — `run_monte_carlo` uses `base_seed + i`). Verify by running identical models and checking identical results. |
| C8 | **Sort order** | Assert alliances in stdout are sorted by first model's T1 probability descending, then mean spice descending. Parse the tier 1 table and verify order. |

### Feature D tests

Tests call existing CLI `main()` functions with `--alliance` args, capturing stdout/stderr.

| # | Test | Implementation |
|---|------|----------------|
| D1 | **Single alliance filter (MC)** | `run_monte_carlo.main([..., "--alliance", "Hot"])`. Assert only "Hot" appears in tier/spice tables. |
| D2 | **Multiple alliance filter** | `--alliance Hot --alliance Ghst`. Assert both appear, others don't. |
| D3 | **No filter shows all** | Omit `--alliance`. Assert all alliances in output. |
| D4 | **Unknown alliance warns** | `--alliance FAKE`. Capture stderr. Assert `"Warning"` and `"FAKE"` present. Assert exit code 0 (runs normally). |
| D5 | **Simulation unchanged** | Run MC with `--alliance Hot` and without. Compare Hot's tier distribution — must be identical. |
| D6 | **JSON output filtered** | `--alliance Hot --output path`. Load JSON. Assert only Hot in tier_distribution and spice_stats keys. |
| D7 | **run_battle.py support** | `run_battle.main([..., "--alliance", "Hot"])`. Assert only Hot in initial state and final results sections. |

### Test details

- Feature A tests (A1–A7) construct inline configs and call `generate_targets()` or `load_model_config()`.
- Feature B tests (B1–B12) construct inline matrix configs with `"*"` entries and call `determine_battle_outcome()` or `_calculate_esv()`.
- Feature C tests (C1–C8) write temp model JSONs via `tmp_path`, call `compare_models.main()`, and capture stdout via `capsys`.
- Feature D tests (D1–D7) use the existing fixture state file and call CLI `main()` functions with `capsys` for stdout and `capfd` for stderr.
- Validation tests (A6, A7, B8, B9, B10) use `pytest.raises(ValidationError)`.

---

## File Changes Summary

| File | Change |
|------|--------|
| `src/spice_war/utils/validation.py` | Add `faction_targeting_strategy` to allowed keys; validate faction existence and strategy values; allow `"*"` in matrix keys; add competing wildcard check; reject `"*"` as alliance ID |
| `src/spice_war/models/configurable.py` | Add faction_targeting_strategy resolution in `_resolve_attacker()`; rework `_lookup_or_heuristic()` for wildcard resolution; extract `_parse_pairing()` helper |
| `scripts/run_monte_carlo.py` | Add `--alliance` flag; filter `_print_summary()` and `_write_json()` output |
| `scripts/run_battle.py` | Add `--alliance` flag; filter `_print_summary()` and `_build_replay()` output |
| `scripts/compare_models.py` | New file — comparative Monte Carlo CLI |
| `tests/test_strategy_exploration.py` | New file — 34 tests (A1–A7, B1–B12, C1–C8, D1–D7) |

No changes to `data_structures.py`, `base.py`, `battle.py`, `mechanics.py`, `events.py`, `simulator.py`, or `monte_carlo.py`.

## Backward Compatibility

All changes are additive:

- **No `faction_targeting_strategy` key:** Resolution skips level 3 and falls through to global strategy, identical to current behavior.
- **No wildcards in matrix:** `_lookup_or_heuristic()` checks for `"*"` entries that don't exist, then falls through to heuristic — same path as before.
- **`_parse_pairing()` extraction:** Factoring the pairing-parsing logic into a helper doesn't change behavior; all existing exact-match lookups return the same result.
- **No `--alliance` flag:** `display_aids` is `None`, all alliances shown — unchanged behavior.
- **`load_model_config()` signature:** New `alliances` parameter is optional with default `None`, so all existing callers continue to work.
