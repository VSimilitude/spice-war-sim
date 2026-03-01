# Custom Battle Outcome — Design

## Overview

Adds a `custom` outcome type to the battle system. When configured in the outcome matrix, a battle can resolve as `"custom"` with a user-specified theft percentage, bypassing the building-based formula. Changes touch five existing files; no new files.

## Changes by File

### 1. `src/spice_war/utils/validation.py`

Add pairing-level validation inside `_check_model_references()`. Currently the function only checks that alliance IDs exist — it does not inspect pairing values.

```python
_ALLOWED_PAIRING_KEYS = {
    "full_success", "partial_success", "custom", "custom_theft_percentage",
}
```

New validation logic appended to `_check_model_references()`, after the existing alliance ID checks on the matrix:

```python
for day, attackers in matrix.items():
    for attacker_id, defenders in attackers.items():
        for defender_id, pairing in defenders.items():
            unknown_keys = set(pairing.keys()) - _ALLOWED_PAIRING_KEYS
            if unknown_keys:
                errors.append(
                    f"battle_outcome_matrix[{day}][{attacker_id}][{defender_id}] "
                    f"has unknown keys: {sorted(unknown_keys)}"
                )

            custom_prob = pairing.get("custom")
            custom_theft = pairing.get("custom_theft_percentage")

            if custom_prob is not None and custom_theft is None:
                errors.append(
                    f"battle_outcome_matrix[{day}][{attacker_id}][{defender_id}] "
                    f"has 'custom' but missing 'custom_theft_percentage'"
                )

            if custom_theft is not None:
                if not (0 <= custom_theft <= 100):
                    errors.append(
                        f"battle_outcome_matrix[{day}][{attacker_id}][{defender_id}] "
                        f"'custom_theft_percentage' must be between 0 and 100, got {custom_theft}"
                    )

            total = (
                pairing.get("full_success", 0)
                + pairing.get("partial_success", 0)
                + pairing.get("custom", 0)
            )
            if total > 1.0 + 1e-9:
                errors.append(
                    f"battle_outcome_matrix[{day}][{attacker_id}][{defender_id}] "
                    f"probabilities sum to {total}, exceeding 1.0"
                )
```

### Notes

- The 1e-9 epsilon on the total check avoids false positives from floating-point addition (e.g. `0.3 + 0.3 + 0.4`).
- `custom_theft_percentage` without `custom` is harmless (ignored), so we don't error on it. Only the reverse (`custom` without `custom_theft_percentage`) is invalid.
- Unknown pairing keys are rejected to catch typos early.

---

### 2. `src/spice_war/models/configurable.py`

#### `_lookup_or_heuristic()` (lines 162–181)

When a matrix pairing contains `custom`, include it in the returned dict.

```python
def _lookup_or_heuristic(
    self,
    matrix: dict,
    attacker: Alliance,
    defender: Alliance,
    day: str,
) -> dict[str, float]:
    day_matrix = matrix.get(day, {})
    attacker_entry = day_matrix.get(attacker.alliance_id, {})
    pairing = attacker_entry.get(defender.alliance_id)

    if pairing is not None:
        full = pairing.get("full_success", 0.0)
        partial = pairing.get("partial_success")
        result = {"full_success": full}

        if partial is not None:
            result["partial_success"] = partial
        elif "custom" not in pairing:
            # Legacy behavior: derive partial only when neither partial
            # nor custom is explicitly configured
            result["partial_success"] = (1.0 - full) * 0.4
        else:
            result["partial_success"] = 0.0

        if "custom" in pairing:
            result["custom"] = pairing["custom"]
            result["custom_theft_percentage"] = pairing["custom_theft_percentage"]

        return result

    return self._heuristic_probabilities(attacker, defender, day)
```

#### Key change: `partial_success` derivation

Currently, when `partial_success` is omitted from a matrix pairing, it's derived as `(1 - full) * 0.4`. The requirements say:

> When `full_success` is omitted from a pairing that has `custom`, `partial_success` is **not** derived from it — both default to 0.

This design generalizes that: if `custom` is present and `partial_success` is absent, partial defaults to 0.0 rather than being derived. The derived-partial behavior only applies to legacy pairings (no `custom`, no explicit `partial_success`). This avoids confusing interactions where adding a `custom` entry to a pairing silently changes the derived `partial_success` value.

#### `determine_battle_outcome()` (lines 121–160)

Multi-attacker averaging and outcome roll both need to handle `custom`.

```python
def determine_battle_outcome(
    self,
    state: GameState,
    attackers: list[Alliance],
    defenders: list[Alliance],
    day: str,
) -> tuple[str, dict[str, float]]:
    primary_defender = defenders[0]
    matrix = self.config.get("battle_outcome_matrix", {})

    probs_list = []
    for attacker in attackers:
        probs = self._lookup_or_heuristic(
            matrix, attacker, primary_defender, day
        )
        probs_list.append(probs)

    if len(probs_list) == 1:
        combined = probs_list[0]
    else:
        combined = {
            "full_success": sum(p["full_success"] for p in probs_list)
            / len(probs_list),
            "partial_success": sum(p["partial_success"] for p in probs_list)
            / len(probs_list),
        }

        # Average custom probability across all attackers (0 for those without)
        custom_probs = [p.get("custom", 0.0) for p in probs_list]
        custom_avg = sum(custom_probs) / len(probs_list)

        if custom_avg > 0:
            combined["custom"] = custom_avg
            # Average theft % only across attackers that have it
            theft_pcts = [
                p["custom_theft_percentage"]
                for p in probs_list
                if "custom_theft_percentage" in p
            ]
            combined["custom_theft_percentage"] = (
                sum(theft_pcts) / len(theft_pcts)
            )

    combined["fail"] = max(
        0.0,
        1.0
        - combined["full_success"]
        - combined["partial_success"]
        - combined.get("custom", 0.0),
    )

    # Outcome roll
    roll = self.rng.random()
    cumulative = combined["full_success"]
    if roll < cumulative:
        outcome = "full_success"
    else:
        cumulative += combined["partial_success"]
        if roll < cumulative:
            outcome = "partial_success"
        elif "custom" in combined:
            cumulative += combined["custom"]
            if roll < cumulative:
                outcome = "custom"
            else:
                outcome = "fail"
        else:
            outcome = "fail"

    return outcome, combined
```

#### Multi-attacker averaging — worked example

Two attackers A and B target the same defender:
- A: `custom: 0.4, custom_theft_percentage: 20`
- B: no custom entry

Result:
- `custom` probability: `(0.4 + 0.0) / 2 = 0.2`
- `custom_theft_percentage`: `20 / 1 = 20` (only A contributes — B doesn't dilute)

If both had custom:
- A: `custom: 0.4, custom_theft_percentage: 20`
- B: `custom: 0.6, custom_theft_percentage: 10`

Result:
- `custom` probability: `(0.4 + 0.6) / 2 = 0.5`
- `custom_theft_percentage`: `(20 + 10) / 2 = 15`

---

### 3. `src/spice_war/game/mechanics.py`

#### `calculate_theft_percentage()` (lines 19–25)

Add an optional `custom_theft_percentage` parameter and a `"custom"` branch.

```python
def calculate_theft_percentage(
    outcome_level: str,
    building_count: int,
    custom_theft_percentage: float | None = None,
) -> float:
    if outcome_level == "custom":
        return custom_theft_percentage
    if outcome_level == "full_success":
        return building_count * 5.0 + 10.0
    elif outcome_level == "partial_success":
        return building_count * 5.0
    else:  # fail
        return 0.0
```

The caller is responsible for passing `custom_theft_percentage` when `outcome_level == "custom"`. This is always available from the probabilities dict returned by `determine_battle_outcome()`.

---

### 4. `src/spice_war/game/battle.py`

#### `resolve_battle()` (lines 6–30)

Add an optional `custom_theft_percentage` parameter and pass it through.

```python
def resolve_battle(
    attackers: list[str],
    primary_defender: str,
    outcome_level: str,
    damage_splits: dict[str, float],
    current_spice: dict[str, int],
    custom_theft_percentage: float | None = None,
) -> dict[str, int]:
    defender_spice = current_spice[primary_defender]
    building_count = calculate_building_count(defender_spice)
    theft_pct = calculate_theft_percentage(
        outcome_level, building_count, custom_theft_percentage
    )
    total_stolen = int(defender_spice * theft_pct / 100.0)

    # ... remainder unchanged
```

---

### 5. `src/spice_war/game/events.py`

#### `coordinate_battle()` (lines 15–56)

Extract `custom_theft_percentage` from the probabilities dict and thread it through to `resolve_battle()` and the `battle_info` output.

```python
def coordinate_battle(
    attackers: list[Alliance],
    defenders: list[Alliance],
    current_state: GameState,
    day: str,
    model: BattleModel,
) -> tuple[dict[str, int], dict]:
    primary_defender = defenders[0]

    outcome, probabilities = model.determine_battle_outcome(
        current_state, attackers, defenders, day
    )

    splits = model.determine_damage_splits(
        current_state, attackers, primary_defender
    )

    custom_theft_pct = probabilities.get("custom_theft_percentage")

    transfers = resolve_battle(
        attackers=[a.alliance_id for a in attackers],
        primary_defender=primary_defender.alliance_id,
        outcome_level=outcome,
        damage_splits=splits,
        current_spice=current_state.current_spice,
        custom_theft_percentage=custom_theft_pct,
    )

    defender_spice = current_state.current_spice[primary_defender.alliance_id]
    building_count = calculate_building_count(defender_spice)
    theft_pct = calculate_theft_percentage(outcome, building_count, custom_theft_pct)

    battle_info = {
        "attackers": [a.alliance_id for a in attackers],
        "defenders": [primary_defender.alliance_id],
        "reinforcements": [d.alliance_id for d in defenders[1:]],
        "outcome": outcome,
        "outcome_probabilities": probabilities,
        "defender_buildings": building_count,
        "theft_percentage": theft_pct,
        "damage_splits": splits,
        "transfers": transfers,
    }

    return transfers, battle_info
```

#### Notes

- `custom_theft_percentage` flows naturally through `probabilities` — no new parameter needed on `coordinate_battle()`.
- `battle_info["outcome_probabilities"]` already includes `custom` and `custom_theft_percentage` from the combined dict, matching the requirements' JSON output format.
- `theft_percentage` in `battle_info` reflects the custom value when outcome is `"custom"`, and the standard building-based value otherwise.

---

## Tests — `tests/test_custom_outcome.py`

New test file. Uses inline fixtures rather than JSON files — custom outcomes are a model-config feature, so building configs programmatically in the tests is clearer than maintaining fixture files.

### Helper

```python
from spice_war.models.configurable import ConfigurableModel
from spice_war.utils.data_structures import Alliance, GameState

def _make_alliances():
    return [
        Alliance("a1", "red", 100.0, 4_000_000, 50_000),
        Alliance("a2", "red", 100.0, 4_000_000, 50_000),
        Alliance("d1", "blue", 100.0, 4_000_000, 50_000),
    ]

def _make_state(alliances, spice_overrides=None):
    spice = {a.alliance_id: a.starting_spice for a in alliances}
    if spice_overrides:
        spice.update(spice_overrides)
    return GameState(
        current_spice=spice,
        brackets={},
        event_number=1,
        day="wednesday",
        event_history=[],
        alliances=alliances,
    )
```

### Test Implementations

| # | Test | Implementation |
|---|------|----------------|
| 1 | **Custom-only pairing** | Config with `custom: 1.0, custom_theft_percentage: 15`. Run `determine_battle_outcome()` — assert outcome is `"custom"`. Probabilities should have `full_success: 0`, `partial_success: 0`, `custom: 1.0`, `fail: 0`. |
| 2 | **Custom theft percentage applied** | Config with `custom: 1.0, custom_theft_percentage: 15`. Defender has 4,000,000 spice. Call `resolve_battle()` with `outcome_level="custom", custom_theft_percentage=15`. Assert total transferred = `int(4_000_000 * 15 / 100) = 600_000`. |
| 3 | **Custom coexists with standard outcomes** | Config with `full_success: 0.3, custom: 0.5, custom_theft_percentage: 10`. Run 100 iterations with sequential seeds. Collect outcomes. Assert both `"full_success"` and `"custom"` appear at least once. Assert `"partial_success"` count is 0 (not configured, defaults to 0 because `custom` is present). |
| 4 | **Fail is implicit remainder** | Config with `full: 0.2, partial: 0.1, custom: 0.3, custom_theft_percentage: 10`. Call `determine_battle_outcome()`. Assert `probabilities["fail"] == pytest.approx(0.4)`. |
| 5 | **Heuristic never produces custom** | No matrix entry for the pairing. Run 50 iterations. Assert no outcome is `"custom"`. Assert `"custom"` not in probabilities dict. |
| 6 | **Multi-attacker averaging** | Two attackers: A1 has `custom: 0.4, custom_theft_percentage: 20`, A2 has `custom: 0.6, custom_theft_percentage: 10`. Assert combined `custom == 0.5` and `custom_theft_percentage == 15.0`. |
| 7 | **Multi-attacker partial custom** | A1 has `custom: 0.4, custom_theft_percentage: 20`, A2 has no custom entry. Assert combined `custom == 0.2` and `custom_theft_percentage == 20.0` (not diluted). |
| 8 | **Validation: custom without theft %** | Config with `custom: 0.5` but no `custom_theft_percentage`. Call `load_model_config()`. Assert `ValidationError` with message matching `"missing 'custom_theft_percentage'"`. |
| 9 | **Validation: probabilities exceed 1.0** | Config with `full: 0.5, partial: 0.3, custom: 0.4`. Call `load_model_config()`. Assert `ValidationError` with message matching `"exceeding 1.0"`. |
| 10 | **Custom theft 0%** | Config with `custom: 1.0, custom_theft_percentage: 0`. Call `resolve_battle()` with `outcome_level="custom", custom_theft_percentage=0`. Assert all transfers are 0. |
| 11 | **Custom theft 30%** | Config with `custom: 1.0, custom_theft_percentage: 30`. Defender has 4,000,000 spice. Call `resolve_battle()` with custom_theft_percentage=30. Assert total transferred = `int(4_000_000 * 30 / 100) = 1_200_000`. |
| 12 | **Custom-only no derived partial** | Config with only `custom: 0.8, custom_theft_percentage: 15` (no `full_success`, no `partial_success`). Call `determine_battle_outcome()`. Assert `probabilities["partial_success"] == 0.0` and `probabilities["full_success"] == 0.0`. |
| 13 | **Deterministic with seed** | Config with `custom: 0.5, custom_theft_percentage: 15, random_seed: 42`. Run `determine_battle_outcome()` 10 times, record outcomes. Reset with same seed, run again. Assert identical outcome sequences. |

### Test details

- Tests 1–5, 12 test the outcome determination path end-to-end through `ConfigurableModel.determine_battle_outcome()`.
- Tests 2, 10, 11 test `resolve_battle()` directly with explicit `custom_theft_percentage` — these validate the mechanics layer independently.
- Tests 6, 7 test multi-attacker by calling `determine_battle_outcome()` with a 2-attacker list and inspecting the returned probabilities.
- Tests 8, 9 test validation by calling `load_model_config()` with invalid configs wrapped in `pytest.raises(ValidationError)`.
- Test 3 uses 100 seeds rather than checking exact seed-to-outcome mappings, since we only need to confirm both outcomes are reachable.
- Test 13 validates determinism by constructing two `ConfigurableModel` instances with the same seed and comparing outcome sequences.

---

## File Changes Summary

| File | Change |
|------|--------|
| `src/spice_war/utils/validation.py` | Add pairing-level validation for custom fields |
| `src/spice_war/models/configurable.py` | Handle `custom` in lookup, averaging, and outcome roll |
| `src/spice_war/game/mechanics.py` | Add `custom` branch + optional param to `calculate_theft_percentage()` |
| `src/spice_war/game/battle.py` | Thread `custom_theft_percentage` through `resolve_battle()` |
| `src/spice_war/game/events.py` | Extract and pass `custom_theft_percentage` in `coordinate_battle()` |
| `tests/test_custom_outcome.py` | New file — 13 tests |

No changes to `data_structures.py`, `base.py`, `simulator.py`, or CLI scripts.

## Backward Compatibility

All changes are additive:
- `calculate_theft_percentage()` and `resolve_battle()` gain an optional parameter defaulting to `None` — existing callers are unaffected.
- The outcome roll checks `"custom" in combined` before testing the custom probability band — standard-only pairings follow the exact same code path as before.
- The `partial_success` derivation change (not derived when `custom` is present) only applies to pairings that explicitly include `custom`, which don't exist in any current configs.
- Validation of pairing keys is new, but only triggers for the `battle_outcome_matrix` structure, and existing configs only use `full_success`/`partial_success` which are in the allowed set.
