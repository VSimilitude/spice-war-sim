# System Architecture

## Overview
This document defines the component structure for the Spice Wars simulation system. The architecture separates pure game mechanics from model-driven decisions, while allowing model components to be invoked mid-simulation with access to current game state.

## Design Principles

1. **No component mixes game mechanics and model logic**: Each component is clearly one or the other
2. **Game mechanics components can call model components**: At decision points, mechanics invoke model components and pass current state
3. **Model components are pluggable**: Can be swapped, configured, or overridden
4. **Model decisions can be state-dependent**: Models receive current game state, allowing decisions like "try harder if rank is at stake"
5. **Testability**: Game mechanics testable with mock model components; model components testable with synthetic state

## Interaction Pattern

```
Game Mechanics Component              Model Component
        │                                    │
        │  "I need a decision"               │
        │  (here's the current state)        │
        ├───────────────────────────────────→│
        │                                    │  considers state,
        │                                    │  config, heuristics
        │         decision result            │
        │←───────────────────────────────────┤
        │                                    │
        │  applies decision using            │
        │  game mechanics rules              │
        │                                    │
```

**Key insight**: The simulation doesn't require all decisions upfront. Model decisions are made just-in-time, with full visibility into how the war is going.

## Game Mechanics Components

These implement core game rules. They contain NO model logic, but they DO call model components at decision points.

### 1. Building Count Calculator
**Purpose**: Determine number of side buildings based on spice amount

**Input**: `spice_amount` (number)
**Output**: `building_count` (0-4)

**Logic**: Uses thresholds from game_mechanics.md
- 0 buildings: < 150k
- 1 building: 150k - 705k
- 2 buildings: 705k - 1,805k
- 3 buildings: 1,805k - 3,165k
- 4 buildings: ≥ 3,165k

### 2. Theft Percentage Mapper
**Purpose**: Convert outcome level to actual theft percentage

**Input**: `outcome_level`, `building_count`, optional `custom_theft_percentage`
**Output**: `theft_percentage` (0-30)

**Logic**:
- full_success: (building_count × 5%) + 10% (center)
- partial_success: (building_count × 5%)
- custom: uses `custom_theft_percentage` directly (0-100%, bypasses building formula)
- fail: 0%

### 3. Bracket Assigner
**Purpose**: Assign alliances to brackets based on spice rankings within faction

**Input**: `alliances` (with current spice), `faction`
**Output**: `brackets` (dict: alliance_id → bracket_number)

**Logic**: Sort by spice descending, bracket = (rank - 1) // 10 + 1

### 4. Final Ranking Calculator
**Purpose**: Determine final success tier

**Input**: `alliances` (with final spice)
**Output**: `rankings` (dict: alliance_id → tier 1-5)

**Logic**: Rank 1→Tier 1, 2-3→Tier 2, 4-10→Tier 3, 11-20→Tier 4, 21+→Tier 5

### 5. Single Battle Resolver
**Purpose**: Resolve one battle and calculate spice transfers

**Input**:
- `attackers` (list of alliance_ids)
- `defenders` (list of alliance_ids, primary defender first)
- `outcome_level` ("full_success", "partial_success", or "fail")
- `damage_splits` (dict: attacker_id → fraction, sum = 1.0)
- `current_spice` (dict: alliance_id → spice)

**Output**: `spice_transfers` (dict: alliance_id → spice change)

**Logic**:
1. Get building count for primary defender (calls Building Count Calculator)
2. Map outcome_level + building_count → theft_percentage (calls Theft Percentage Mapper)
3. Calculate total_stolen = primary_defender_spice × theft_percentage
4. Distribute among attackers using damage_splits
5. Return transfers

### 6. Battle Coordinator
**Purpose**: Orchestrate a single battle by gathering model decisions and invoking resolution

**Calls model components for**:
- Battle outcome
- Damage splits (if multiple attackers)

**Input**:
- `attackers` (list of alliance_ids)
- `defenders` (list of alliance_ids, primary defender first)
- `current_state` (all alliance data, spice totals, event history)
- `day` ("wednesday" or "saturday")
- `model` (model component interface)

**Output**: `spice_transfers` (dict: alliance_id → spice change)

**Logic**:
1. Ask model: determine battle outcome (passing attackers, defenders, current state, day)
2. Ask model: determine damage splits (passing attackers, current state)
3. Call Single Battle Resolver with outcome + splits
4. Return spice transfers

### 7. Event Coordinator
**Purpose**: Resolve all battles in one event

**Calls model components for**:
- Targeting decisions (per bracket)
- Reinforcement assignments (per bracket)

**Input**:
- `current_state` (all alliance data, spice totals, brackets)
- `attacker_faction` (1 or 2)
- `day` ("wednesday" or "saturday")
- `model` (model component interface)

**Output**: `updated_spice` (dict: alliance_id → new spice)

**Logic**:
1. Determine brackets (call Bracket Assigner for each faction)
2. For each bracket:
   a. Get attackers and defenders in this bracket
   b. Ask model: generate targets for this bracket (passing bracket alliances, current state)
   c. Ask model: generate reinforcements for this bracket (passing bracket alliances, targets, current state)
   d. Group battles (attackers targeting same defender)
   e. For each battle: call Battle Coordinator (passing attackers, defenders, state, day, model)
3. Aggregate all spice transfers across all brackets
4. Apply to current_spice and return

### 8. Between-Event Processor
**Purpose**: Apply passive spice generation and update brackets

**Input**:
- `current_spice` (dict)
- `days_elapsed` (number)
- `daily_rates` (dict: alliance_id → rate)

**Output**:
- `updated_spice` (dict)
- `new_brackets` (dict)

**Logic**:
1. For each alliance: spice += daily_rate × days_elapsed
2. Call Bracket Assigner for each faction

### 9. War Simulator
**Purpose**: Run complete 4-week simulation

**Input**:
- `alliances` (list: initial alliance data)
- `event_schedule` (list: which faction attacks each event)
- `model` (model component interface)

**Output**:
- `final_state`:
  - `final_spice`: per alliance
  - `rankings`: tier assignments
  - `event_history`: spice totals after each event

**Logic**:
1. Initialize spice from starting values
2. For each event (1-8):
   a. Call Event Coordinator (passing current state + model)
   b. Call Between-Event Processor
   c. Record state in history
3. Call Final Ranking Calculator
4. Return final state

## Simulation Data Structures

### Alliance Configuration

Each alliance requires:

```json
{
  "alliance_id": "alliance_A",
  "name": "Alliance Alpha",
  "server": "server_1",
  "faction": "red",
  "power": 1000000,
  "gift_level": 50000,
  "starting_spice": 200000,
  "daily_spice_rate": 50000
}
```

**Required fields (used by game mechanics):**
- `alliance_id` (string): Unique identifier
- `faction` (string): Which faction the alliance belongs to (e.g. `"red"`, `"blue"`)
- `starting_spice` (number): Initial spice at event start
- `daily_spice_rate` (number): Passive spice generation per day

**Optional fields (used by model components):**
- `name` (string): Human-readable name
- `server` (string): Server identifier
- `power` (number): Alliance strength
- `gift_level` (number): Spending indicator

> **Note:** `damage_weight` is configured in the model config's `damage_weights` dict, not on the alliance. See [model_generation.md](model_generation.md).

### Event Schedule

Defines which faction attacks on each of the 8 battle events:

```json
[
  {"attacker_faction": "red",  "day": "wednesday", "days_before": 3},
  {"attacker_faction": "blue", "day": "saturday",  "days_before": 4}
]
```

**Required fields per event:**
- `attacker_faction` (string): Which faction attacks (must match a faction in `alliances`)
- `day` (string): `"wednesday"` or `"saturday"`
- `days_before` (integer): Days of passive spice accumulation before this event

See [state_file_format.md](state_file_format.md) for the full input format specification.

### Game State (Passed to Model)

The model receives current game state at each decision point:

```json
{
  "current_spice": {"alliance_A": 350000, "alliance_B": 280000},
  "brackets": {"alliance_A": 1, "alliance_B": 1},
  "event_number": 5,
  "day": "wednesday",
  "event_history": [
    {"event_id": 1, "spice_after": {}},
    {"event_id": 2, "spice_after": {}}
  ],
  "alliances": []
}
```

This allows models to make state-dependent decisions (e.g., adjust strategy based on current rankings).

## Model Components

These make modeling decisions. They receive current game state and return decisions. They contain NO game mechanics logic.

### Model Construction and Config

The model is instantiated once with user configuration, then passed to the War Simulator:

```python
config = {
    "battle_outcome_matrix": { ... },       # See M3 below
    "event_targets": { ... },               # See M1 below
    "event_reinforcements": { ... },        # See M2 below
    "random_seed": 42,                      # For reproducible outcomes
    "targeting_strategy": "expected_value",  # Global targeting algorithm
    "default_targets": { ... },             # Per-alliance default targets
    "faction_targeting_strategy": { ... },  # Per-faction strategy overrides
    "damage_weights": { ... },              # Damage contribution weights
    "targeting_temperature": 0.0,           # MC stochastic targeting
    "power_noise": 0.0,                     # MC power fluctuation
    "outcome_noise": 0.0                    # MC outcome probability noise
}

model = ConfigurableModel(config, alliances)
simulator = WarSimulator(alliances, event_schedule, model)
```

**Config sources:**
- `battle_outcome_matrix`: Probabilities per attacker-defender pairing. Supports `"*"` wildcards.
- `event_targets`: Explicit targeting for specific events (optional)
- `event_reinforcements`: Explicit reinforcements for specific events (optional)
- `default_targets`: Per-alliance default target or strategy (optional)
- `faction_targeting_strategy`: Per-faction targeting strategy override (optional)
- `targeting_strategy`: Global targeting algorithm — `"expected_value"` (default) or `"highest_spice"`
- `damage_weights`: Per-alliance damage contribution weights (optional)
- `random_seed`: Controls randomness in outcome rolling
- `targeting_temperature`, `power_noise`, `outcome_noise`: Monte Carlo randomness controls (default 0)
- `alliances`: Alliance data including `power`, `gift_level` (used for fallback heuristics)

### M1. Targeting Generator

**Purpose**: Decide which attackers target which defenders within a bracket

**Receives at call time (from Event Coordinator):**
- `state`: Current game state (spice totals, event history, event_number)
- `bracket_attackers`: List of attacking alliances in this bracket
- `bracket_defenders`: List of defending alliances in this bracket
- `bracket_number`: Which bracket (1, 2, 3, etc.)

**Has from construction:**
- `config.event_targets`: User-configured targets per event (optional)
- `config.default_targets`: Per-alliance default target or strategy (optional)
- `config.faction_targeting_strategy`: Per-faction strategy override (optional)
- `config.targeting_strategy`: Global strategy — `"expected_value"` (default) or `"highest_spice"`

**Returns:**
- `targets` (dict): attacker_id → defender_id

**Logic — 4-level targeting resolution per attacker:**
1. **`event_targets`**: Check `config.event_targets[event_number][attacker_id]` — per-event explicit pin
2. **`default_targets`**: Check `config.default_targets[attacker_id]` — per-alliance default (target string or `{"strategy": "..."}`)
3. **`faction_targeting_strategy`**: Check `config.faction_targeting_strategy[attacker_faction]` — per-faction algorithm
4. **`targeting_strategy`**: Fall back to global algorithm (default: `"expected_value"`)

**Targeting algorithms:**
- **`"expected_value"`** (default): Maximizes Expected Spice Value (ESV) = sum of (probability × theft_amount) for each defender. Attackers choose in descending power order; ties broken by higher spice then alphabetical ID.
- **`"highest_spice"`**: Original heuristic — 1:1 assignment to highest-spice unassigned defender, attackers sorted by power descending.

**User config format for event_targets:**
```json
{
  "event_targets": {
    "1": {
      "alliance_A": "alliance_X",
      "alliance_B": {"strategy": "highest_spice"}
    }
  },
  "default_targets": {
    "alliance_C": "alliance_Y"
  },
  "faction_targeting_strategy": {
    "red": "highest_spice"
  },
  "targeting_strategy": "expected_value"
}
```

**Notes:**
- Config is optional at every level — unconfigured attackers cascade to the next level
- Override values can be a target string (pin to defender) or `{"strategy": "algorithm_name"}` or `{"target": "defender_id"}`

### M2. Reinforcement Generator

**Purpose**: Decide which un-targeted defenders reinforce which battles

**Receives at call time (from Event Coordinator):**
- `state`: Current game state
- `targets`: The targeting decisions just made for this bracket (from M1)
- `bracket_defenders`: All defending alliances in this bracket
- `bracket_number`: Which bracket

**Has from construction:**
- `config.event_reinforcements`: User-configured reinforcements per event (optional)

**Returns:**
- `reinforcements` (dict): un-targeted defender_id → defender_id of battle to reinforce

**Logic:**
1. Determine which defenders are un-targeted (not in `targets.values()`)
2. Check if `config.event_reinforcements[current_event_number]` exists
   - If yes: use user-configured reinforcements
   - If no: apply default reinforcement rule
3. **Default rule (most-attacked)**:
   a. Count how many attackers each defender has
   b. Assign each un-targeted defender to the most-attacked battle
   c. Ties broken by highest spice (reinforce the richest target)
   d. Respect max reinforcement limit (num_attackers - 1 per battle)
4. Return reinforcements dict

**User config format for event_reinforcements:**
```json
{
  "event_reinforcements": {
    "1": {
      "alliance_Z": "alliance_X"
    }
  }
}
```

### M3. Battle Outcome Generator

**Purpose**: Determine the outcome level for a single battle

**Receives at call time (from Battle Coordinator):**
- `state`: Current game state (spice totals, event history, rankings)
- `attackers`: List of attacking alliance data (id, power, gift_level, etc.)
- `defenders`: List of defending alliance data (primary defender first)
- `day`: "wednesday" or "saturday"

**Has from construction:**
- `config.battle_outcome_matrix`: User-configured probabilities per pairing
- `config.random_seed`: For reproducible random rolling
- `alliances`: Alliance power/gift_level data (for fallback heuristic)

**Returns:**
- `outcome_level` (string): `"full_success"`, `"partial_success"`, `"custom"`, or `"fail"`
- `custom_theft_percentage` (number, optional): Only present when outcome is `"custom"`

**Logic:**
1. **Look up probabilities for each attacker-defender pairing**:
   - For each attacker, check `config.battle_outcome_matrix[day][attacker_id][primary_defender_id]`
   - Also checks wildcard `"*"` entries: attacker default (`A -> "*"`) → defender default (`"*" -> D`) → heuristic
   - If found with both values: use configured `{full_success: prob, partial_success: prob}`
   - If found with only `full_success`: derive `partial_success = (1 - full_success) * 0.4`
   - If `custom` is present: use `{full_success, partial_success, custom}` with optional `custom_theft_percentage`
   - If not found: use power-based heuristic fallback (see [model_generation.md](model_generation.md))

2. **Combine probabilities for multiple attackers** (if > 1 attacker):
   - Average the `full_success` probabilities across all attackers
   - Average the `partial_success` probabilities across all attackers

3. **Roll outcome**:
   - Generate random number [0, 1)
   - If < full_success_prob → "full_success"
   - Else if < full_success_prob + partial_success_prob → "partial_success"
   - Else → "fail"

4. Return outcome_level

**Notes:**
- `fail` probability is always implicit (1 - full - partial - custom)
- `custom` outcome uses `custom_theft_percentage` instead of the building-based formula
- Random seed ensures reproducibility across runs with same config
- See [model_generation.md](model_generation.md) for config format, heuristic formulas, and reference tables

### M4. Damage Split Generator

**Purpose**: Determine how stolen spice is split among multiple attackers

**Receives at call time (from Battle Coordinator):**
- `state`: Current game state
- `attackers`: List of attacking alliance data

**Has from construction:**
- `config.damage_weights`: Per-alliance damage weight overrides (optional, in model config)

**Returns:**
- `splits` (dict): attacker_id → fraction (sum = 1.0)

**Logic:**
1. Check if ALL attackers in this battle have a weight in `config.damage_weights`
   - If yes: use configured weights
   - If no: use power-based heuristic fallback (see [model_generation.md](model_generation.md))
2. Calculate total_weight = sum of all attacker weights
3. Return `{attacker_id: weight / total_weight}` for each attacker

**Notes:**
- For single-attacker battles, this is trivially `{attacker_id: 1.0}`
- The Battle Coordinator can skip calling this for single-attacker battles
- Weights and power are never mixed — it's all-or-nothing on user-supplied weights
- `damage_weights` lives in the model config, not on the alliance data
- See [model_generation.md](model_generation.md) for heuristic formula and reference tables

### Model Implementations

#### ConfigurableModel
Implements M1-M4 as described above:
- Constructed with user config + alliance data
- Each method checks user config first, falls back to heuristic
- Uses random seed for reproducible outcome rolling
- Supports ESV and highest-spice targeting strategies with 4-level resolution
- Supports wildcard `"*"` entries in outcome matrix
- Supports `custom` outcome type with user-specified theft percentages
- Supports Monte Carlo randomness: stochastic targeting (temperature), power fluctuation (noise), outcome probability noise

## Data Flow

```
                     ┌──────────────────┐
                     │  User Config /   │
                     │  Model Settings  │
                     └────────┬─────────┘
                              │
                     ┌────────▼─────────┐
                     │   BattleModel    │
                     │  (pluggable)     │
                     └────────┬─────────┘
                              │ called by mechanics
                              │ at decision points
┌─────────────────────────────┼──────────────────────┐
│ War Simulator (9)           │                      │
│  │                          │                      │
│  ├─→ Event Coordinator (7) ←┘                      │
│  │    │  asks model for: targets, reinforcements   │
│  │    │                                            │
│  │    └─→ Battle Coordinator (6)                   │
│  │         │  asks model for: outcome, splits      │
│  │         │                                       │
│  │         └─→ Single Battle Resolver (5)          │
│  │              ├─→ Building Count Calculator (1)  │
│  │              └─→ Theft Percentage Mapper (2)    │
│  │                                                 │
│  ├─→ Between-Event Processor (8)                   │
│  │    └─→ Bracket Assigner (3)                     │
│  │                                                 │
│  └─→ Final Ranking Calculator (4)                  │
│                                                    │
│           Game Mechanics Layer                     │
└────────────────────────────────────────────────────┘
```

## Module Organization

```
src/spice_war/
├── game/
│   ├── mechanics.py      # Components 1-4: Pure calculations
│   ├── battle.py         # Component 5: Single battle resolution
│   ├── events.py         # Components 6-7: Event coordination
│   ├── simulator.py      # Components 8-9: Between-event + war simulator
│   └── monte_carlo.py    # Monte Carlo simulation engine
├── models/
│   ├── base.py           # BattleModel abstract interface
│   └── configurable.py   # ConfigurableModel with all targeting/outcome logic
├── sheets/
│   ├── importer.py       # CSV/Google Sheets → model config JSON
│   └── template.py       # State file → CSV template generator
├── utils/
│   ├── data_structures.py # Alliance, EventConfig, GameState dataclasses
│   └── validation.py     # JSON loading + input validation
└── web/
    └── bridge.py         # Dict-in/dict-out bridge for Pyodide web UI
```

## Testing Strategy

**Game mechanics**: Test with mock model that returns predetermined values
- Verify mechanics apply correctly regardless of what model decides
- Example: "Given model returns full_success, verify correct spice transfer"

**Model components**: Test with synthetic game state
- Verify model makes expected decisions given specific state
- Example: "Given specific power ratios, verify ESV targeting picks optimal target"

**Integration**: Test full simulation with known model + known initial state
- Verify end-to-end results match expectations

**Statistical fairness**: 1000-seed symmetric scenario verifies outcomes are unbiased
- Within-faction spice CV < 2%, rank uniformity chi-squared p >= 0.001

**Monte Carlo**: Verify tier distribution convergence and targeting matrix accuracy

## Additional Components

### Monte Carlo Engine
Runs the war simulation N times with varying seeds (`base_seed + i`) to produce probability distributions. See `game/monte_carlo.py`.

- `MonteCarloResult` tracks `tier_counts`, `spice_totals`, `per_iteration`, and `targeting_counts`
- Derived methods: `tier_distribution()`, `spice_stats()`, `rank_summary()`, `most_likely_tier()`, `targeting_matrix()`

### Web Interface
Browser-based UI running entirely client-side via Pyodide (Python in WebAssembly). See [web_interface_design.md](web_interface_design.md).

### CSV Pipeline
Import/export model configs via CSV for Google Sheets workflow. See [cli_reference.md](cli_reference.md).