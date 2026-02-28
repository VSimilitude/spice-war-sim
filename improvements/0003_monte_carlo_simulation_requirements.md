# Monte Carlo Simulation — Requirements

## Goal

Run the existing war simulation many times with varying random seeds to produce
probability distributions: how often does each alliance land in each ranking
tier?

## Scope

One new module (`game/monte_carlo.py`), one new CLI script
(`scripts/run_monte_carlo.py`), and associated tests. No changes to existing
game logic or model code.

---

## 1. Core Engine — `run_monte_carlo()`

**Location:** `src/spice_war/game/monte_carlo.py`

```python
def run_monte_carlo(
    alliances: list[Alliance],
    event_schedule: list[EventConfig],
    model_config: dict,
    num_iterations: int,
    base_seed: int = 0,
) -> MonteCarloResult:
```

**Behavior:**

- For each iteration `i` in `range(num_iterations)`:
  1. Copy `model_config` and set `random_seed` to `base_seed + i`.
  2. Construct a fresh `ConfigurableModel` with the updated config.
  3. Call `simulate_war(alliances, event_schedule, model)`.
  4. Record `final_spice` and `rankings` (tier assignments) from the result.
- Return a `MonteCarloResult` containing the aggregated data.

**Notes:**

- Each iteration is independent — the only thing that changes between runs is
  the random seed.
- The model config's original `random_seed` (if any) is ignored; `base_seed`
  takes precedence.

---

## 2. Result Data Structure — `MonteCarloResult`

**Location:** `src/spice_war/utils/data_structures.py` (or in `monte_carlo.py`)

A dataclass (or similar) holding:

| Field | Type | Description |
|---|---|---|
| `num_iterations` | `int` | Total number of runs |
| `base_seed` | `int` | Starting seed |
| `tier_counts` | `dict[str, Counter[int]]` | Per-alliance counter: tier → count |
| `spice_totals` | `dict[str, list[int]]` | Per-alliance list of final spice values (one per iteration) |

### Derived methods / properties

| Method | Returns | Description |
|---|---|---|
| `tier_distribution(alliance_id)` | `dict[int, float]` | Fraction of iterations the alliance finished in each tier (1–5) |
| `spice_stats(alliance_id)` | `dict` | `{"mean", "median", "min", "max", "p25", "p75"}` over final spice |
| `rank_summary()` | `dict[str, dict[int, float]]` | `tier_distribution` for every alliance |
| `most_likely_tier(alliance_id)` | `int` | The tier with the highest frequency |

---

## 3. CLI — `scripts/run_monte_carlo.py`

```
usage: run_monte_carlo.py STATE_FILE [MODEL_FILE]
                          [-n NUM] [--base-seed SEED]
                          [--output PATH] [--quiet]
```

| Argument | Default | Description |
|---|---|---|
| `STATE_FILE` | *(required)* | Path to initial state JSON |
| `MODEL_FILE` | *(optional)* | Path to model config JSON |
| `-n`, `--num-iterations` | `1000` | Number of simulation runs |
| `--base-seed` | `0` | Starting seed for the sequence |
| `--output` | *(none)* | Write full JSON results to file |
| `--quiet` | `false` | Suppress the summary table |

### Default stdout output

A tier probability table plus spice summary, e.g.:

```
Monte Carlo Simulation — 1000 iterations (seeds 0–999)

Tier Distribution (% of iterations):
                 Tier 1    Tier 2    Tier 3    Tier 4    Tier 5
RedWolves        62.3%     28.1%      8.4%      1.2%      0.0%
BlueLions        18.7%     41.2%     30.5%      9.6%      0.0%
RedFalcons       11.4%     19.3%     42.8%     26.5%      0.0%
BlueShields       7.6%     11.4%     18.3%     62.7%      0.0%

Spice Summary:
                    Mean      Median         Min         Max
RedWolves      4,215,300   4,180,000   2,950,000   5,620,000
BlueLions      3,410,200   3,390,000   1,800,000   5,100,000
RedFalcons     2,890,500   2,870,000   1,200,000   4,500,000
BlueShields    2,100,800   2,050,000     600,000   3,800,000
```

### JSON output (`--output`)

```json
{
  "num_iterations": 1000,
  "base_seed": 0,
  "tier_distribution": {
    "RedWolves": {"1": 0.623, "2": 0.281, "3": 0.084, "4": 0.012, "5": 0.0},
    ...
  },
  "spice_stats": {
    "RedWolves": {"mean": 4215300, "median": 4180000, "min": 2950000, "max": 5620000, "p25": 3800000, "p75": 4600000},
    ...
  },
  "raw_results": [
    {"seed": 0, "final_spice": {"RedWolves": 4200000, ...}, "rankings": {"RedWolves": 1, ...}},
    ...
  ]
}
```

---

## 4. Tests

**Location:** `tests/test_monte_carlo.py`

| # | Test | Validates |
|---|---|---|
| 1 | **Deterministic with same base seed** | Running twice with identical inputs produces identical `MonteCarloResult` |
| 2 | **Different base seed → different results** | Changing `base_seed` produces different tier distributions |
| 3 | **Iteration count respected** | `len(result.spice_totals[aid])` == `num_iterations` for every alliance |
| 4 | **Tier counts sum to num_iterations** | For each alliance, `sum(tier_counts[aid].values()) == num_iterations` |
| 5 | **Tier distribution sums to 1.0** | `sum(tier_distribution(aid).values()) ≈ 1.0` |
| 6 | **Spice stats correctness** | Manually compute stats for a small run (n=5) and compare |
| 7 | **Most likely tier** | Verify `most_likely_tier()` returns the tier with highest count |
| 8 | **CLI runs without error** | Invoke `main()` with sample fixtures, check exit code 0 |
| 9 | **CLI --output writes valid JSON** | Parse the output file and verify structure matches spec |
| 10 | **CLI --quiet suppresses stdout** | Capture stdout and verify it's empty |

---

## 5. Non-Goals (for now)

- **Parallel / multiprocessing execution** — keep it single-threaded for
  simplicity. Can be added later if performance is a concern.
- **Varying model configs across iterations** — each iteration uses the same
  model config (only the seed changes). Scenario sweeps (e.g., testing
  different outcome matrices) are a separate feature.
- **Progress bars / live output** — stdout is only printed at the end.
- **Statistical significance tests** — we report raw frequencies, not
  confidence intervals.
