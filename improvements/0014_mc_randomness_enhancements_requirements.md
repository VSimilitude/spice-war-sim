# MC Randomness Enhancements — Requirements

## Goal

Add three new sources of randomness to Monte Carlo simulations — **stochastic
targeting**, **per-event power fluctuation**, and **outcome probability
noise** — controlled by optional model config fields. All features use the
existing seeded RNG so results remain fully deterministic for a given seed.

## Motivation

Currently the only randomness in an MC run is the battle outcome roll. All
other decisions — targeting, damage splits, heuristic probabilities — are
deterministic functions of game state. This means MC runs with different seeds
only explore different outcome-roll paths while strategy and context stay
fixed.

Adding randomness to targeting, power, and outcome probabilities lets MC
simulations explore a much wider space of plausible scenarios:

- **Stochastic targeting** models the uncertainty in which alliance attacks
  which defender. In practice, attackers don't always pick the
  theoretically-optimal target.
- **Power fluctuation** models variance in alliance strength from event to
  event — morale, readiness, coordination quality. This ripples through
  heuristic battle probabilities and damage splits.
- **Outcome probability noise** models uncertainty in the predicted battle
  probabilities themselves — whether configured via the matrix or derived
  from heuristics. A 40% full success chance might really be anywhere from
  35% to 45%.

---

## 1. Stochastic Targeting

### 1.1 Config

A new optional field `targeting_temperature` controls randomness in algorithm-
based target selection (ESV and highest-spice strategies):

```json
{
  "targeting_temperature": 0.5
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `targeting_temperature` | float >= 0 | `0.0` | Controls randomness in target selection. 0 = deterministic (current behavior). Higher values = more random. |

### 1.2 Behavioral Rules

- **Temperature 0** (default): Current behavior — always pick the best target.
  Full backward compatibility.
- **Temperature > 0**: Use softmax-weighted random selection over candidate
  defenders, where weights are derived from each defender's score (ESV or
  spice) and the temperature.
- **Pinned targets are unaffected** — `event_targets` and `default_targets`
  with explicit `{"target": "..."}` pins bypass the algorithm entirely and
  are never randomized.
- **Per-alliance strategy overrides are respected** — if an alliance has
  `{"strategy": "highest_spice"}`, stochastic selection applies to that
  strategy's scores, not ESV.

### 1.3 Softmax Selection

For a set of candidate defenders with scores $s_1, s_2, \ldots, s_n$ and
temperature $T$:

1. Compute weights: $w_i = e^{s_i / T}$
2. Normalize: $p_i = w_i / \sum_j w_j$
3. Select defender randomly weighted by $p_i$

To avoid numerical overflow, subtract the maximum score before exponentiating:
$w_i = e^{(s_i - s_{max}) / T}$

**Score normalization**: ESV values and raw spice values can be very large
(millions). To make the temperature parameter intuitive across different game
states, normalize scores before applying softmax:

1. Compute $s_{max} = \max(s_1, \ldots, s_n)$
2. If $s_{max} > 0$: normalized score $\hat{s}_i = s_i / s_{max}$ (range 0–1)
3. If $s_{max} = 0$: all normalized scores are 0 (uniform selection)

The temperature then operates on the 0–1 range:
- $T = 0.1$: strongly favor the best target (near-deterministic)
- $T = 0.5$: moderate randomness
- $T = 1.0$: high randomness, roughly proportional to score
- $T \gg 1$: approaches uniform random selection

### 1.4 Edge Cases

- **Single candidate defender**: Selected deterministically regardless of
  temperature (no choice to randomize).
- **All scores zero**: All candidates are equally weighted (uniform random
  selection via `self.rng`).
- **Priority order preserved**: Attackers still pick in descending power order.
  Each attacker's stochastic selection is over the remaining unassigned
  defenders.

---

## 2. Per-Event Power Fluctuation

### 2.1 Config

A new optional field `power_noise` controls per-event random fluctuation
applied to alliance power values:

```json
{
  "power_noise": 0.1
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `power_noise` | float >= 0 | `0.0` | Maximum fractional deviation applied to power each event. 0 = no fluctuation (current behavior). |

### 2.2 Behavioral Rules

- At the start of each event (before targeting, battles, and all model
  decisions), generate a temporary effective power for each alliance:
  $p_{eff} = p_{base} \times (1 + u)$ where $u \sim \text{Uniform}(-noise, +noise)$
- These effective power values are used for **all model calculations within
  that event**: heuristic probability lookup, ESV computation, damage split
  heuristics.
- The base `Alliance.power` values are **never modified** — effective powers
  are scoped to the event and discarded afterward.
- **power_noise 0** (default): No fluctuation. Current behavior. Full backward
  compatibility.

### 2.3 Scope of Effect

Power fluctuation affects all model decisions that depend on alliance power:
heuristic battle probabilities, ESV-based targeting, attacker priority
ordering, and heuristic damage splits.

**Not affected** (these depend on spice, not power): building count, theft
percentage, bracket assignment, reinforcement logic.

### 2.4 Edge Cases

- **power_noise causes power to go negative**: Not possible — the minimum
  multiplier is $(1 - noise)$, and power values are always positive. Even at
  `power_noise: 0.99`, the minimum multiplier is 0.01.
- **power_noise > 1.0**: Allowed but unusual. Multiplier range would be
  $(1 - noise, 1 + noise)$, so power could be near zero or doubled+.
- **Matrix-configured probabilities**: Unaffected — power fluctuation only
  changes the heuristic fallback. If a matrix entry exists for a specific
  pairing, those probabilities are used as-is.

---

## 3. Outcome Probability Noise

### 3.1 Config

A new optional field `outcome_noise` controls random perturbation of battle
outcome probabilities on a per-pairing basis:

```json
{
  "outcome_noise": 0.05
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `outcome_noise` | float >= 0 | `0.0` | Maximum absolute deviation applied to each outcome probability per pairing. 0 = no perturbation (current behavior). |

### 3.2 Behavioral Rules

- Each attacker-defender pairing gets its own set of perturbation offsets:
  $\delta_i \sim \text{Uniform}(-noise, +noise)$ for `full_success`,
  `partial_success`, and `custom`.
- A given pairing's offsets are **constant for the entire simulation** —
  if the same attacker fights the same defender in multiple events, the
  same offsets apply each time. Different seeds produce different offsets.
- When computing battle outcome probabilities (from any source — matrix,
  heuristic, or multi-attacker averaging), apply the pairing's offsets:
  $p'_i = p_i + \delta_i$
- Clamp each perturbed probability to $[0, 1]$.
- Recompute `fail` as $\max(0, 1 - \sum p'_i)$. If the perturbed non-fail
  probabilities sum to more than 1, normalize them proportionally to sum to
  1 and set `fail` to 0.
- **Applies to all probability sources** — matrix-configured, heuristic, and
  multi-attacker averaged probabilities are all perturbed. This is the key
  difference from `power_noise`, which only affects heuristic-derived
  probabilities.
- **outcome_noise 0** (default): No perturbation. Current behavior. Full
  backward compatibility.

### 3.3 Edge Cases

- **Probability already at 0 or 1**: Perturbation can shift it away from the
  boundary (e.g., 0 + 0.03 = 0.03), but clamping prevents negative values.
- **Large noise value**: With `outcome_noise: 0.5`, probabilities can shift
  dramatically. Allowed but expected to be used with small values (0.02–0.10).
- **Custom outcome**: If present in a pairing, `custom` probability is
  perturbed independently. The `custom_theft_percentage` is not perturbed.
  Pairings without a custom outcome are unaffected by any custom offset.
- **Multi-attacker battles**: When multiple attackers target the same
  defender, each attacker's per-pairing offsets are applied to their
  individual probabilities first, then the perturbed probabilities are
  averaged. Clamping and normalization happen after averaging.
- **Interaction with power_noise**: Both can be active simultaneously.
  `power_noise` changes the heuristic-derived base probabilities per event,
  then `outcome_noise` applies the pairing's fixed offsets on top.

---

## 4. Determinism

All three features use the existing seeded RNG. When set to 0 (default), none
consume any RNG calls, preserving the existing call sequence and full backward
compatibility. Results are fully deterministic for a given seed.

---

## 5. Tests

### Stochastic Targeting

| # | Test | Validates |
|---|------|-----------|
| 1 | **Temperature 0 matches current behavior** | With `targeting_temperature: 0`, targeting is identical to existing deterministic behavior |
| 2 | **Temperature > 0 produces varied targets** | Running the same scenario with different seeds and `targeting_temperature: 0.5` produces different target assignments |
| 3 | **High temperature approaches uniform** | With very high temperature, target distribution across many seeds is approximately uniform |
| 4 | **Low temperature strongly favors best** | With `targeting_temperature: 0.1`, the best target is selected in the vast majority of seeds |
| 5 | **Pinned targets unaffected** | Explicit target pins in `event_targets` / `default_targets` are always respected regardless of temperature |
| 6 | **Single defender deterministic** | Only one candidate defender — selected regardless of temperature |
| 7 | **All scores zero gives uniform** | All defenders have 0 ESV — selection is uniform random |
| 8 | **Deterministic with seed** | Same seed + same temperature → identical target assignments |
| 9 | **Priority order preserved** | Strongest attacker still picks first; stochastic selection only affects *which* defender they pick |
| 10 | **Works with highest_spice strategy** | Temperature applies to spice-based scores, not just ESV |

### Power Fluctuation

| # | Test | Validates |
|---|------|-----------|
| 11 | **power_noise 0 matches current behavior** | With `power_noise: 0`, all results identical to existing behavior |
| 12 | **power_noise produces varied outcomes** | Same scenario with different seeds and `power_noise: 0.1` produces different battle outcomes |
| 13 | **Base power unchanged** | After simulation, `Alliance.power` values are identical to their original values |
| 14 | **Effective power within expected range** | With `power_noise: 0.1`, effective powers are within `[0.9 * base, 1.1 * base]` |
| 15 | **Effective power consistent within event** | Same event number uses same effective powers for targeting, battle outcome, and damage splits |
| 16 | **Different events get different powers** | Event 1 and event 2 use different effective power values |
| 17 | **Deterministic with seed** | Same seed + same noise → identical effective powers and results |
| 18 | **Matrix probabilities unaffected** | Explicit matrix entries are used as-is; only heuristic paths use effective power |
| 19 | **Damage splits use effective power** | Heuristic damage splits reflect fluctuated power, not base power |
| 20 | **Heuristic probabilities use effective power** | Power ratio in heuristic formula uses effective power values |

### Outcome Probability Noise

| # | Test | Validates |
|---|------|-----------|
| 21 | **outcome_noise 0 matches current behavior** | With `outcome_noise: 0`, all results identical to existing behavior |
| 22 | **outcome_noise produces varied outcomes** | Same scenario with different seeds and `outcome_noise: 0.05` produces different battle outcomes |
| 23 | **Per-pairing offsets are independent** | Two different attacker-defender pairings get different perturbation offsets |
| 24 | **Same pairing consistent across events** | If the same attacker fights the same defender in two events, the same offsets apply both times |
| 25 | **Different seeds produce different offsets** | Two simulations with different seeds get different offsets for the same pairing |
| 26 | **Perturbed probabilities stay valid** | After perturbation, all probabilities are >= 0 and sum to <= 1 (plus fail) |
| 27 | **Applies to matrix-configured probabilities** | Explicit matrix entries are perturbed, unlike power_noise |
| 28 | **Applies to heuristic probabilities** | Heuristic-derived probabilities are also perturbed |
| 29 | **Custom outcome perturbed** | Custom probability is perturbed; custom_theft_percentage is not |
| 30 | **Normalization when sum exceeds 1** | Large noise that pushes total above 1 results in proportional normalization and fail = 0 |
| 31 | **Deterministic with seed** | Same seed + same noise → identical offsets and results |
| 32 | **Interaction with power_noise** | Both active — power_noise changes base heuristic per event, outcome_noise applies pairing's fixed offsets on top |

### Combined

| # | Test | Validates |
|---|------|-----------|
| 33 | **All three features together** | `targeting_temperature: 0.5` + `power_noise: 0.1` + `outcome_noise: 0.05` — simulation runs without error and produces varied results across seeds |
| 34 | **No features (backward compat)** | Config with no noise/temperature fields produces identical results to current code |
| 35 | **Full MC sweep** | Running N simulations with all features produces a distribution of final rankings, not identical results |

---

## 6. Non-Goals

- **Per-alliance temperature or noise** — a single global value for each
  parameter is sufficient. Per-alliance tuning can be added later if needed.
- **Noise on other parameters** — daily spice rate noise, theft percentage
  jitter, reinforcement randomization, and custom_theft_percentage noise are
  out of scope for this change.
- **New targeting strategies** — this enhances existing strategies with
  randomness, not adding new strategy types.
- **Changes to the `BattleModel` interface** — all changes are internal to
  `ConfigurableModel`.
