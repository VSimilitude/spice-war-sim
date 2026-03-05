# Model Generation

## Overview
This document describes how we model and generate the inputs required by the simulation engine. These are **modeling choices**, not core game rules, and are designed to be configurable and adjustable. See [architecture.md](architecture.md) for simulation data structures and component interfaces.

The simulation engine doesn't care which method you use, as long as the output conforms to the required input format.

## Model Configuration Reference

The model is instantiated with a config dict and alliance data. All config keys are optional — unconfigured values fall back to power-based heuristics.

```python
config = {
    "battle_outcome_matrix": { ... },
    "event_targets": { ... },
    "event_reinforcements": { ... },
    "default_targets": { ... },
    "faction_targeting_strategy": { ... },
    "targeting_strategy": "expected_value",
    "damage_weights": { ... },
    "random_seed": 42,
    "targeting_temperature": 0.0,
    "power_noise": 0.0,
    "outcome_noise": 0.0
}
model = ConfigurableModel(config, alliances)
```

### battle_outcome_matrix

Probabilities for each attacker-defender pairing, keyed by day. `partial_success` is optional per pairing (derived as `(1 - full_success) * 0.4` if omitted). Unconfigured pairings use power-based heuristic (see [Section 1, Method 2](#method-2-power-based-heuristic-fallback)).

Supports `"*"` wildcard entries: attacker default (`"A" -> "*"`) catches any defender for attacker A; defender default (`"*" -> "D"`) catches any attacker targeting D. Exact pairings take priority over wildcards. Competing wildcards (ambiguous pairings matched by both an attacker-default and defender-default) are rejected at validation time.

```json
{
  "battle_outcome_matrix": {
    "wednesday": {
      "attacker_id": {
        "defender_id": {
          "full_success": 0.7,
          "partial_success": 0.2
        },
        "*": {
          "full_success": 0.5
        }
      },
      "*": {
        "strong_defender_id": {
          "full_success": 0.1
        }
      }
    },
    "saturday": { ... }
  }
}
```

Supports a `custom` outcome type with a user-specified theft percentage that bypasses the building-based formula:

```json
{
  "full_success": 0.3,
  "custom": 0.4,
  "custom_theft_percentage": 15
}
```

Resolution order: exact pairing → attacker wildcard (`A -> "*"`) → defender wildcard (`"*" -> D`) → heuristic.

### event_targets

Explicit attacker → defender targeting for specific events. Values can be a plain defender ID string, or an object with `"target"` or `"strategy"` key. Unconfigured events cascade to lower targeting levels.

```json
{
  "event_targets": {
    "1": {
      "attacker_id": "defender_id",
      "attacker_id_2": {"strategy": "highest_spice"}
    },
    "5": {
      "attacker_id": {"target": "defender_id_3"}
    }
  }
}
```

### default_targets

Per-alliance default target or strategy, used when `event_targets` has no entry for this attacker at this event:

```json
{
  "default_targets": {
    "attacker_id": "defender_id",
    "attacker_id_2": {"strategy": "expected_value"}
  }
}
```

### faction_targeting_strategy

Per-faction targeting strategy override, used when neither `event_targets` nor `default_targets` resolve for an attacker:

```json
{
  "faction_targeting_strategy": {
    "red": "highest_spice",
    "blue": "expected_value"
  }
}
```

### targeting_strategy

Global targeting algorithm. Options: `"expected_value"` (default) or `"highest_spice"`. Used when no higher-priority targeting level matches.

### event_reinforcements

Explicit reinforcement assignments for specific events. Unconfigured events use default most-attacked rule (see [Section 3, Reinforcement generation](#method-2-power-based-rule-default)).

```json
{
  "event_reinforcements": {
    "1": {
      "untargeted_defender_id": "targeted_defender_id"
    }
  }
}
```

### damage_weights

Per-alliance damage contribution weights for splitting stolen spice among multiple attackers. If ALL attackers in a battle have a weight configured, weights are used; otherwise the power-based heuristic applies. See [Section 2](#2-damage-distribution-generation).

```json
{
  "damage_weights": {
    "alliance_A": 1.0,
    "alliance_B": 1.5
  }
}
```

### random_seed

Integer seed for reproducible outcome rolling. Same seed + same config = same results.

### Monte Carlo Randomness Parameters

Three optional parameters that add controlled randomness for Monte Carlo analysis. All default to `0` (deterministic, backward-compatible).

- **`targeting_temperature`** (number, >= 0): Softmax-weighted random target selection over candidate defenders. `0` = deterministic ESV/highest-spice. Higher values = more random. Pinned targets unaffected.
- **`power_noise`** (number, >= 0): Per-event effective power fluctuation. Each alliance's effective power = `base_power * (1 + uniform(-noise, +noise))`. Affects heuristic probabilities, ESV calculations, and damage splits. Matrix-configured probabilities unaffected.
- **`outcome_noise`** (number, >= 0): Per-pairing probability offsets, pre-generated with a separate RNG (`seed + 1,000,000`). Applied to all probability sources. Clamped to [0,1] with normalization.

### Alliance data used by model

- **`power`** (number): Alliance strength. Used by all heuristic fallbacks when user config is not provided.

## Modeling Scope

### Available Indicators
We have limited information to predict battle outcomes:

1. **Total Alliance Power**: Combined strength of all alliance members (most reliable indicator)
2. **Total Alliance Gift Level**: Cumulative spending/investment (proxy for engagement; reserved for Phase 2+)
3. **Number of Alliance Members**: Typically 95-100 for top alliances (limited discriminatory value)
4. **Day of Week**: Wednesday is generally easier for attackers; Saturday is harder

### What We Don't Model
- Individual player actions during battles
- Specific building defense values or HP
- Timing within a battle (order of attacks, respawns, etc.)
- Player skill or coordination quality
- Specific troop types, abilities, or gear
- Resource expenditure during battle (healing items, buffs, etc.)

### What We Do Model
- Alliance-level power comparisons
- Probabilistic battle outcomes
- Spice theft based on buildings destroyed
- Attacker coordination (simplified via probability averaging)
- Day-of-week difficulty variations
- Defensive reinforcements (power contribution)

## 1. Battle Outcome Generation

The engine needs: **outcome level** (full_success, partial_success, or fail) for each battle.

### Method 1: Battle Outcome Matrix (User-Configured)

Configure probabilities for each attacker-defender pairing:

```json
{
  "battle_outcome_matrix": {
    "wednesday": {
      "alliance_A": {
        "alliance_X": {
          "full_success": 0.7,
          "partial_success": 0.2
        }
      }
    },
    "saturday": {
      "alliance_A": {
        "alliance_X": {
          "full_success": 0.5,
          "partial_success": 0.3
        }
      }
    }
  }
}
```

**Structure:** `day -> attacker -> defender -> probabilities`

**Usage:**
1. Look up pairing in matrix
2. Roll random number to select outcome
3. fail probability is implicit (1 - full - partial)

**Deriving partial_success when only full_success is provided:**

The formula `partial_success = (1 - full_success) * 0.4` distributes 40% of the remaining probability to partial success. Intuitively: the better the attacker (higher full_success), the less likely a partial result — they either win big or get shut down. Examples:
- `full_success: 0.7` → `partial_success: 0.12` (fail: 0.18)
- `full_success: 0.4` → `partial_success: 0.24` (fail: 0.36)
- `full_success: 0.1` → `partial_success: 0.36` (fail: 0.54)

### Method 2: Power-Based Heuristic (Fallback)

If pairing not in matrix, use dual clamped linear functions based on power ratio
(`attacker.power / defender.power`), with separate parameters per day. Each day
has two clamped linear functions: one for `full_success` probability and one for
cumulative partial probability (chance of at least partial success).
`partial_success` is derived as the difference between the two.

```python
def _heuristic_probabilities(self, attacker, defender, day):
    ratio = attacker.power / defender.power

    if day == "wednesday":
        full = max(0.0, min(1.0, 2.5 * ratio - 2.0))
        cumulative_partial = max(0.0, min(1.0, 1.75 * ratio - 0.9))
    else:  # saturday
        full = max(0.0, min(1.0, 3.25 * ratio - 3.0))
        cumulative_partial = max(0.0, min(1.0, 1.75 * ratio - 1.1))

    partial = max(0.0, cumulative_partial - full)
    return {"full_success": full, "partial_success": partial}
```

**Approximate behavior (Wednesday — easier for attackers):**
| Ratio | Example       | full_success | partial_only | fail |
|-------|---------------|-------------|-------------|------|
| 1.20  | 18B vs 15B    | 1.00        | 0.00        | 0.00 |
| 1.07  | 16B vs 15B    | 0.67        | 0.30        | 0.03 |
| 1.00  | 15B vs 15B    | 0.50        | 0.25        | 0.25 |
| 0.67  | 10B vs 15B    | 0.00        | 0.27        | 0.73 |

**Approximate behavior (Saturday — harder for attackers):**
| Ratio | Example       | full_success | partial_only | fail |
|-------|---------------|-------------|-------------|------|
| 1.20  | 18B vs 15B    | 0.90        | 0.10        | 0.00 |
| 1.07  | 16B vs 15B    | 0.47        | 0.30        | 0.23 |
| 1.00  | 15B vs 15B    | 0.25        | 0.40        | 0.35 |
| 0.67  | 10B vs 15B    | 0.00        | 0.07        | 0.93 |

**Notes:**
- Wednesday uses shallower slopes, reflecting easier attacking conditions
- Saturday uses a steeper full_success slope, making full victories harder to achieve
- Heuristic parameters can be tuned if needed

### Handling Multiple Attackers

When A+B both attack X:
1. Look up: A vs X, B vs X (using matrix or heuristic)
2. Combine probabilities (simple average):
   ```python
   combined_full = (prob_A_full + prob_B_full) / 2
   combined_partial = (prob_A_partial + prob_B_partial) / 2
   ```
3. Use combined probabilities for the battle

## 2. Damage Distribution Generation

The engine needs: **split fractions** for each multi-attacker battle.

### Method 1: Damage Weights (Model Config)

Configure weights in the model config's `damage_weights` dict:

```json
{
  "damage_weights": {
    "alliance_A": 1.0,
    "alliance_B": 1.5
  }
}
```

**Calculate splits:**
```python
total_weight = sum(weights[a.id] for a in attackers)
splits = {a.id: weights[a.id] / total_weight for a in attackers}
```

**Example:** A (weight=1.0), B (weight=1.5) → A gets 40%, B gets 60%

### Method 2: Power-Based Heuristic (Fallback)

If weights not fully specified, derive effective weights using a clamped linear
function of each attacker's power ratio vs the primary defender. This is
day-independent since it compares attackers against the same defender.

```python
def determine_damage_splits(self, state, attackers, primary_defender):
    # Use damage_weight only if ALL attackers have it configured
    all_have_weights = all(
        a.damage_weight is not None for a in attackers
    )

    if all_have_weights:
        weights = {a.id: a.damage_weight for a in attackers}
    else:
        weights = {}
        for a in attackers:
            ratio = a.power / primary_defender.power
            weights[a.id] = max(0.0, min(1.0, 1.5 * ratio - 1.0))

    total = sum(weights.values())
    return {aid: w / total for aid, w in weights.items()}
```

**Approximate behavior (vs 15B defender):**
| Attackers | Ratios | Eff. Weights | Split | Raw Power Split |
|-----------|--------|-------------|-------|-----------------|
| 18B + 16B | 1.20, 1.07 | 0.80, 0.60 | 57/43 | 53/47 |
| 18B + 12B | 1.20, 0.80 | 0.80, 0.20 | 80/20 | 60/40 |
| 16B + 12B | 1.07, 0.80 | 0.60, 0.20 | 75/25 | 57/43 |
| 18B + 16B + 12B | 1.20, 1.07, 0.80 | 0.80, 0.60, 0.20 | 50/37/13 | 39/35/26 |

**Notes:**
- The heuristic uses slope 1.5 (average of M3 outcome slopes) to scale power ratios
- Attackers below ratio ~0.67 contribute zero effective weight
- Weights and power are never mixed — it's all-or-nothing on user-supplied weights

## 3. Targeting Generation

The engine needs: **targets mapping** (attacker → defender) for each event.

### 4-Level Targeting Resolution

Each attacker's target is resolved by checking four levels in order. The first match wins:

1. **`event_targets[event_number][attacker_id]`** — per-event explicit pin
2. **`default_targets[attacker_id]`** — per-alliance default
3. **`faction_targeting_strategy[attacker_faction]`** — per-faction algorithm
4. **`targeting_strategy`** — global algorithm (default: `"expected_value"`)

Values at levels 1-2 can be a plain defender ID string, or `{"target": "defender_id"}`, or `{"strategy": "algorithm_name"}`.

### Method 1: Expected Value Targeting (Default)

The default `"expected_value"` strategy maximizes Expected Spice Value (ESV) per attacker:

```
ESV(attacker, defender) = Σ (probability × theft_amount) for each outcome
```

Attackers choose targets in descending power order. Tie-breaking: higher spice, then alphabetical ID.

### Method 2: Highest Spice Targeting

The `"highest_spice"` strategy uses the original 1:1 heuristic:

```python
def generate_targets(bracket_attackers, bracket_defenders):
    attackers = sorted(bracket_attackers, key=lambda a: a.power, reverse=True)
    defenders = sorted(bracket_defenders, key=lambda d: d.current_spice, reverse=True)

    targets = {}
    assigned_defenders = set()

    for attacker in attackers:
        for defender in defenders:
            if defender.id not in assigned_defenders:
                targets[attacker.id] = defender.id
                assigned_defenders.add(defender.id)
                break

    return targets
```

**Reinforcement generation:**

Un-targeted defenders reinforce the most-attacked battle, respecting the max
reinforcement limit (`num_attackers - 1` per battle). Ties broken by highest spice.

```python
def generate_reinforcements(targets, bracket_defenders):
    targeted = set(targets.values())
    untargeted = [d for d in bracket_defenders if d.id not in targeted]

    # Count attackers per defender and find most-attacked
    target_counts = Counter(targets.values())
    most_attacked = max(target_counts, key=lambda d: (target_counts[d],
        next(a.current_spice for a in bracket_defenders if a.id == d)))

    reinforcements = {}
    max_reinforcements = target_counts[most_attacked] - 1
    for d in untargeted[:max_reinforcements]:
        reinforcements[d.id] = most_attacked

    return reinforcements
```

## 4. Alliance Configuration Generation

### From Game Data

If you have real game data:
```python
alliance = {
    "alliance_id": from_game_data.id,
    "power": from_game_data.total_power,
    "gift_level": from_game_data.total_gifts,
    "starting_spice": from_game_data.current_spice
}
```

### Synthetic (For Testing)

Generate random or patterned data:
```python
def generate_test_alliance(faction, rank):
    return {
        "alliance_id": f"faction{faction}_rank{rank}",
        "faction": faction,
        "power": 1_000_000 - (rank * 50_000),  # Decreasing by rank
        "starting_spice": 200_000,
        "daily_spice_rate": 50_000
    }
```

## 5. Event Schedule Generation

### Standard Schedule

Alternating attackers:
```python
events = []
for week in range(1, 5):
    events.append({
        "event_id": (week-1)*2 + 1,
        "day": "wednesday",
        "week": week,
        "attacker_faction": 1 if week % 2 == 1 else 2,
        "defender_faction": 2 if week % 2 == 1 else 1
    })
    events.append({
        "event_id": (week-1)*2 + 2,
        "day": "saturday",
        "week": week,
        "attacker_faction": 2 if week % 2 == 1 else 1,
        "defender_faction": 1 if week % 2 == 1 else 2
    })
```

## Calibration and Tuning

The modeling choices should be:
1. **Testable**: Run scenarios and compare to expected/historical outcomes
2. **Adjustable**: Easy to modify probabilities and heuristics
3. **Transparent**: Clear what assumptions drive results
4. **Configurable**: Users can override defaults for specific scenarios

## Future Refinements

Potential improvements to modeling accuracy:
- [ ] Gift level as a factor in heuristics
- [ ] Historical battle data analysis to calibrate default probabilities
- [ ] Machine learning model trained on past battles (if data available)
- [ ] More sophisticated multi-attacker combination formulas
- [ ] Activity level indicators (% of alliance expected to participate)
- [ ] Contribution-based damage splits considering battle performance

## Summary

**Current implementation:**
1. Battle outcomes: Matrix-based (with wildcard `"*"` support and `custom` outcome type) + dual clamped linear heuristic fallback
2. Damage splits: Weight-based (in model config `damage_weights`) + clamped linear power heuristic fallback
3. Targets: 4-level resolution (event → alliance → faction → global) with ESV default strategy
4. Alliance data: User-provided or synthetic test data
5. Event schedule: Standard alternating pattern
6. Monte Carlo randomness: targeting temperature, power noise, outcome noise

All methods produce the same output format defined in [architecture.md](architecture.md) that the simulation engine consumes.
