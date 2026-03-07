"""Statistical fairness test for symmetric 10v10 war scenarios.

Runs NUM_SEEDS simulations with identical alliances and a symmetric schedule,
then asserts that no alliance has a systematic advantage.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pytest
from scipy.stats import chisquare

from spice_war.game.simulator import simulate_war
from spice_war.models.configurable import ConfigurableModel
from spice_war.utils.data_structures import Alliance, EventConfig

pytestmark = pytest.mark.slow

# ── Configuration ────────────────────────────────────────────────────────────

NUM_SEEDS = 1000

# Assertion thresholds
MAX_WITHIN_FACTION_CV = 0.02       # 2%
CHI_SQUARED_MIN_P = 0.001          # reject uniformity below this
OUTCOME_RATE_TOLERANCE = 0.05      # 5 percentage points

# Expected heuristic outcome rates (power ratio 1.0)
EXPECTED_RATES = {
    "wednesday": {"full_success": 0.40, "partial_success": 0.15, "fail": 0.45},
    "saturday":  {"full_success": 0.55, "partial_success": 0.25, "fail": 0.20},
}

# ── Data Container ───────────────────────────────────────────────────────────


@dataclass
class FairnessResults:
    alliances: list[Alliance]
    final_spice: dict[str, list[int]] = field(default_factory=dict)
    intra_faction_ranks: dict[str, list[int]] = field(default_factory=dict)
    tiers: dict[str, list[int]] = field(default_factory=dict)
    battle_outcomes: dict[str, Counter] = field(default_factory=dict)
    num_seeds: int = 0


# ── Scenario Construction ────────────────────────────────────────────────────


def _build_alliances() -> list[Alliance]:
    alliances = []
    for faction in ("red", "blue"):
        for i in range(1, 11):
            alliances.append(
                Alliance(
                    alliance_id=f"{faction}_{i:02d}",
                    faction=faction,
                    power=100,
                    starting_spice=1_000_000,
                    daily_spice_rate=50_000,
                )
            )
    return alliances


def _build_schedule() -> list[EventConfig]:
    return [
        EventConfig(attacker_faction="red",  day="wednesday", days_before=3),
        EventConfig(attacker_faction="blue", day="saturday",  days_before=4),
        EventConfig(attacker_faction="blue", day="wednesday", days_before=3),
        EventConfig(attacker_faction="red",  day="saturday",  days_before=4),
        EventConfig(attacker_faction="blue", day="wednesday", days_before=3),
        EventConfig(attacker_faction="red",  day="saturday",  days_before=4),
        EventConfig(attacker_faction="red",  day="wednesday", days_before=3),
        EventConfig(attacker_faction="blue", day="saturday",  days_before=4),
    ]


# ── Simulation Loop ─────────────────────────────────────────────────────────


def _run_simulations(
    alliances: list[Alliance],
    schedule: list[EventConfig],
    num_seeds: int,
) -> FairnessResults:
    results = FairnessResults(alliances=alliances, num_seeds=num_seeds)

    # Initialize collections
    for a in alliances:
        results.final_spice[a.alliance_id] = []
        results.intra_faction_ranks[a.alliance_id] = []
        results.tiers[a.alliance_id] = []
    results.battle_outcomes = {"wednesday": Counter(), "saturday": Counter()}

    for seed in range(num_seeds):
        model = ConfigurableModel({"random_seed": seed}, alliances)
        result = simulate_war(alliances, schedule, model)

        # Collect final spice
        for a in alliances:
            results.final_spice[a.alliance_id].append(
                result["final_spice"][a.alliance_id]
            )

        # Compute intra-faction ranks
        for faction in ("red", "blue"):
            faction_aids = [
                a.alliance_id for a in alliances if a.faction == faction
            ]
            sorted_aids = sorted(
                faction_aids,
                key=lambda aid: (-result["final_spice"][aid], aid),
            )
            for rank, aid in enumerate(sorted_aids, 1):
                results.intra_faction_ranks[aid].append(rank)

        # Collect tiers
        for a in alliances:
            results.tiers[a.alliance_id].append(
                result["rankings"][a.alliance_id]
            )

        # Collect battle outcomes
        for event in result["event_history"]:
            day = event["day"]
            for battle in event["battles"]:
                results.battle_outcomes[day][battle["outcome"]] += 1

    return results


# ── Summary Output ───────────────────────────────────────────────────────────


def _print_summary(results: FairnessResults) -> None:
    print(f"\n=== Statistical Fairness Test ({results.num_seeds} seeds) ===")

    # Final Spice
    print("\nFinal Spice (mean ± std):")
    faction_means: dict[str, float] = {"red": 0.0, "blue": 0.0}
    faction_counts: dict[str, int] = {"red": 0, "blue": 0}

    for a in results.alliances:
        aid = a.alliance_id
        values = results.final_spice[aid]
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = variance ** 0.5
        print(f"  {aid}: {mean:>12,.0f} ± {std:>10,.0f}")
        faction_means[a.faction] += mean
        faction_counts[a.faction] += 1

    for faction in ("red", "blue"):
        grand_mean = faction_means[faction] / faction_counts[faction]
        print(f"  {faction.capitalize()} faction mean: {grand_mean:>12,.0f}")

    # Rank Distribution
    print("\nRank Distribution (chi-squared p-values, uniform null):")
    for a in results.alliances:
        aid = a.alliance_id
        rank_counts = Counter(results.intra_faction_ranks[aid])
        observed = [rank_counts.get(r, 0) for r in range(1, 11)]
        _, p_value = chisquare(observed)
        print(f"  {aid}: p={p_value:.4f}")

    # Battle Outcomes
    print("\nBattle Outcomes:")
    for day in ("wednesday", "saturday"):
        counts = results.battle_outcomes[day]
        total = sum(counts.values())
        if total == 0:
            continue
        full_pct = counts["full_success"] / total * 100
        partial_pct = counts["partial_success"] / total * 100
        fail_pct = counts["fail"] / total * 100
        exp = EXPECTED_RATES[day]
        print(
            f"  {day.capitalize():>12}: "
            f"full={full_pct:5.1f}%  partial={partial_pct:5.1f}%  fail={fail_pct:5.1f}%  "
            f"(expected: {exp['full_success']*100:.0f}/"
            f"{exp['partial_success']*100:.0f}/"
            f"{exp['fail']*100:.0f})"
        )

    print()


# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def fairness_results():
    alliances = _build_alliances()
    schedule = _build_schedule()
    results = _run_simulations(alliances, schedule, NUM_SEEDS)
    _print_summary(results)
    return results


# ── Tests ────────────────────────────────────────────────────────────────────


def test_within_faction_spice_cv(fairness_results):
    """Within each faction, per-alliance mean spice values should be tight (CV < 2%)."""
    for faction in ("red", "blue"):
        faction_aids = [
            a.alliance_id
            for a in fairness_results.alliances
            if a.faction == faction
        ]
        means = []
        for aid in faction_aids:
            values = fairness_results.final_spice[aid]
            means.append(sum(values) / len(values))

        grand_mean = sum(means) / len(means)
        variance = sum((m - grand_mean) ** 2 for m in means) / len(means)
        std = variance ** 0.5
        cv = std / grand_mean

        assert cv < MAX_WITHIN_FACTION_CV, (
            f"{faction} faction CV = {cv:.4f} exceeds {MAX_WITHIN_FACTION_CV}"
        )


def test_rank_uniformity(fairness_results):
    """Each alliance's intra-faction rank distribution should be uniform."""
    for a in fairness_results.alliances:
        aid = a.alliance_id
        rank_counts = Counter(fairness_results.intra_faction_ranks[aid])
        observed = [rank_counts.get(r, 0) for r in range(1, 11)]
        _, p_value = chisquare(observed)

        assert p_value >= CHI_SQUARED_MIN_P, (
            f"{aid} rank distribution is non-uniform: p={p_value:.6f} < {CHI_SQUARED_MIN_P}"
        )


def test_battle_outcome_rates(fairness_results):
    """Per-day outcome rates should be within tolerance of heuristic predictions."""
    for day in ("wednesday", "saturday"):
        counts = fairness_results.battle_outcomes[day]
        total = sum(counts.values())
        assert total > 0, f"No battles recorded for {day}"

        for outcome, expected_rate in EXPECTED_RATES[day].items():
            observed_rate = counts[outcome] / total
            diff = abs(observed_rate - expected_rate)

            assert diff <= OUTCOME_RATE_TOLERANCE, (
                f"{day} {outcome}: observed={observed_rate:.3f}, "
                f"expected={expected_rate:.3f}, diff={diff:.3f} > {OUTCOME_RATE_TOLERANCE}"
            )
