# Statistical Fairness Test — Requirements

## Summary

An integration test that runs a symmetric 10v10 war scenario across many seeds (heuristic-only model) and verifies that outcomes are statistically fair — no alliance has a systematic advantage over any other.

## Scenario Setup

### Alliances

20 identical alliances: 10 red, 10 blue.

| Field | Value |
|-------|-------|
| `power` | 100 |
| `starting_spice` | 1,000,000 |
| `daily_rate` | 50,000 |

Alliance IDs: `red_01`–`red_10`, `blue_01`–`blue_10`.

This puts all alliances into a single bracket per faction (bracket cutoff is 10).

### Event Schedule

Standard 4-week, 8-event war. Each faction attacks 4 times — twice on wednesday (easier) and twice on saturday (harder) — so neither faction has a schedule advantage:

| Event | Attacker | Day | days_before |
|-------|----------|-----|-------------|
| 1 | red | wednesday | 3 |
| 2 | blue | saturday | 4 |
| 3 | blue | wednesday | 3 |
| 4 | red | saturday | 4 |
| 5 | blue | wednesday | 3 |
| 6 | red | saturday | 4 |
| 7 | red | wednesday | 3 |
| 8 | blue | saturday | 4 |

### Model

No model file — all decisions use default heuristics. Each run uses a different seed (0 through N-1).

## Seed Count

Default: 1000 seeds (0–999). Should be overridable via a constant at the top of the test file for quick iteration.

## Statistics to Collect

### 1. Final Spice Distribution

For each alliance, across all seeds:
- **Mean final spice**
- **Standard deviation of final spice**
- **Min and max final spice**

**Fairness expectation:** All alliances should have approximately the same mean final spice. Since the schedule is symmetric (each faction gets 2 wednesday + 2 saturday attacks), the per-faction grand means should also be close.

### 2. Rank Distribution

For each alliance, across all seeds, count how often it finishes in each rank position (1st through 20th).

**Fairness expectation:** Within each faction, each alliance should occupy each intra-faction rank (1st–10th among its faction) with roughly equal frequency (~10% each for 10 alliances across 10 ranks). A chi-squared goodness-of-fit test against uniform distribution can formalize this.

### 3. Tier Distribution

For each alliance, across all seeds, count how often it finishes in each tier (1–5).

**Fairness expectation:** Within each faction, all alliances should have approximately the same tier distribution.

### 4. Battle Outcome Rates

Across all battles in all seeds:
- Count of `full_success`, `partial_success`, and `fail` outcomes, broken down by day (wednesday vs saturday).

**Fairness expectation:** Outcome rates should be consistent with the heuristic probabilities for equal-power alliances:
- Wednesday (power ratio 1.0): ~50% full, ~35% partial, ~15% fail
- Saturday (power ratio 1.0): ~25% full, ~40% partial, ~35% fail

## Test Assertions

All assertions should use tolerances wide enough to avoid flaky tests but tight enough to catch real bugs.

### Within-Faction Spice Symmetry

For each faction, the coefficient of variation (std/mean) of the per-alliance mean final spice values should be small — below **2%**.

In other words: take the 10 mean-final-spice values for red alliances; their spread should be tight.

### Rank Uniformity

For each faction, apply a chi-squared test for uniformity of the rank distribution (10 alliances × 10 ranks × N seeds). Use a conservative significance level (p < 0.001) to avoid flakiness. The test should **fail** if the chi-squared p-value is below 0.001 for any alliance, indicating a non-uniform rank distribution.

### Battle Outcome Rates

Per-day outcome rates across all seeds should be within **5 percentage points** of the heuristic-predicted values.

## Test Output

The test should print a summary table to stdout (visible with `pytest -s`) even on success, so the statistics are easy to inspect:

```
=== Statistical Fairness Test (1000 seeds) ===

Final Spice (mean ± std):
  red_01:  1,234,567 ± 234,567
  red_02:  1,230,123 ± 231,456
  ...
  blue_01: 1,100,234 ± 212,345
  ...
  Red faction mean:  1,232,000
  Blue faction mean: 1,098,000

Rank Distribution (chi-squared p-values, uniform null):
  red_01:  p=0.45
  red_02:  p=0.72
  ...

Battle Outcomes:
  Wednesday: full=50.2%  partial=34.8%  fail=15.0%  (expected: 50/35/15)
  Saturday:  full=25.3%  partial=39.7%  fail=35.0%  (expected: 25/40/35)
```

## File Location

`tests/test_statistical_fairness.py`

## Pytest Integration

- Mark with `@pytest.mark.slow` so it can be excluded from fast test runs (`pytest -m "not slow"`).
- Should run in under 60 seconds for 1000 seeds.
