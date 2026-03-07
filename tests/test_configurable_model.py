import pytest

from spice_war.models.configurable import ConfigurableModel
from spice_war.utils.data_structures import Alliance, GameState


def _alliance(aid, faction="red", power=15_000_000_000, spice=500_000):
    return Alliance(
        alliance_id=aid,
        faction=faction,
        power=power,
        starting_spice=spice,
        daily_spice_rate=50_000,
    )


def _state(alliances, spice=None, event_number=1, day="wednesday"):
    if spice is None:
        spice = {a.alliance_id: a.starting_spice for a in alliances}
    return GameState(
        current_spice=spice,
        brackets={},
        event_number=event_number,
        day=day,
        event_history=[],
        alliances=alliances,
    )


# ── M3 Heuristic Tests ──────────────────────────────────────────


class TestM3Heuristic:
    def test_wednesday_equal_power(self):
        """Ratio 1.0 on Wednesday → full=0.40, partial=0.15"""
        a = _alliance("a1", power=15e9)
        d = _alliance("d1", "blue", power=15e9)
        model = ConfigurableModel({"random_seed": 0}, [a, d])
        probs = model._heuristic_probabilities(a, d, "wednesday")
        assert abs(probs["full_success"] - 0.40) < 0.01
        assert abs(probs["partial_success"] - 0.15) < 0.01

    def test_wednesday_strong_attacker(self):
        """Ratio 1.20 on Wednesday → full≈0.67, partial≈0.26"""
        a = _alliance("a1", power=18e9)
        d = _alliance("d1", "blue", power=15e9)
        model = ConfigurableModel({"random_seed": 0}, [a, d])
        probs = model._heuristic_probabilities(a, d, "wednesday")
        assert abs(probs["full_success"] - 0.67) < 0.01
        assert abs(probs["partial_success"] - 0.26) < 0.01

    def test_wednesday_weak_attacker(self):
        """Ratio 0.67 on Wednesday → full≈0.0, partial≈0.0"""
        a = _alliance("a1", power=10e9)
        d = _alliance("d1", "blue", power=15e9)
        model = ConfigurableModel({"random_seed": 0}, [a, d])
        probs = model._heuristic_probabilities(a, d, "wednesday")
        assert abs(probs["full_success"] - 0.0) < 0.02
        assert abs(probs["partial_success"] - 0.0) < 0.02

    def test_saturday_equal_power(self):
        """Ratio 1.0 on Saturday → full≈0.55, partial≈0.25"""
        a = _alliance("a1", power=15e9)
        d = _alliance("d1", "blue", power=15e9)
        model = ConfigurableModel({"random_seed": 0}, [a, d])
        probs = model._heuristic_probabilities(a, d, "saturday")
        assert abs(probs["full_success"] - 0.55) < 0.01
        assert abs(probs["partial_success"] - 0.25) < 0.01

    def test_saturday_strong_attacker(self):
        """Ratio 1.20 on Saturday → full≈0.88, partial≈0.12"""
        a = _alliance("a1", power=18e9)
        d = _alliance("d1", "blue", power=15e9)
        model = ConfigurableModel({"random_seed": 0}, [a, d])
        probs = model._heuristic_probabilities(a, d, "saturday")
        assert abs(probs["full_success"] - 0.88) < 0.01
        assert abs(probs["partial_success"] - 0.12) < 0.01

    def test_saturday_weak_attacker(self):
        """Ratio 0.67 on Saturday → full≈0.01, partial≈0.25"""
        a = _alliance("a1", power=10e9)
        d = _alliance("d1", "blue", power=15e9)
        model = ConfigurableModel({"random_seed": 0}, [a, d])
        probs = model._heuristic_probabilities(a, d, "saturday")
        assert abs(probs["full_success"] - 0.01) < 0.02
        assert abs(probs["partial_success"] - 0.25) < 0.02


class TestM3MatrixLookup:
    def test_full_lookup(self):
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "a1": {"d1": {"full_success": 0.7, "partial_success": 0.2}}
                }
            },
        }
        a = _alliance("a1")
        d = _alliance("d1", "blue")
        model = ConfigurableModel(config, [a, d])
        probs = model._lookup_or_heuristic(
            config["battle_outcome_matrix"], a, d, "wednesday"
        )
        assert probs["full_success"] == 0.7
        assert probs["partial_success"] == 0.2

    def test_derive_partial_from_full_only(self):
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {"a1": {"d1": {"full_success": 0.7}}}
            },
        }
        a = _alliance("a1")
        d = _alliance("d1", "blue")
        model = ConfigurableModel(config, [a, d])
        probs = model._lookup_or_heuristic(
            config["battle_outcome_matrix"], a, d, "wednesday"
        )
        assert probs["full_success"] == 0.7
        assert abs(probs["partial_success"] - 0.12) < 0.001


class TestM3MultiAttacker:
    def test_averaging(self):
        a1 = _alliance("a1", power=18e9)
        a2 = _alliance("a2", power=12e9)
        d1 = _alliance("d1", "blue", power=15e9)
        model = ConfigurableModel({"random_seed": 42}, [a1, a2, d1])
        state = _state([a1, a2, d1])

        # a1 ratio=1.2: full=0.67, cumul=0.93, partial=0.26
        # a2 ratio=0.8: full=0.13, cumul=0.17, partial=0.04
        # average: full=0.40, partial=0.15
        _, probs = model.determine_battle_outcome(state, [a1, a2], [d1], "wednesday")
        assert abs(probs["full_success"] - 0.40) < 0.01
        assert abs(probs["partial_success"] - 0.15) < 0.01


# ── M4 Tests ─────────────────────────────────────────────────────


class TestM4DamageSplits:
    def test_single_attacker(self):
        a = _alliance("a1")
        d = _alliance("d1", "blue")
        model = ConfigurableModel({"random_seed": 0}, [a, d])
        state = _state([a, d])
        splits = model.determine_damage_splits(state, [a], d)
        assert splits == {"a1": 1.0}

    def test_weight_based_splits(self):
        a1 = _alliance("a1")
        a2 = _alliance("a2")
        d = _alliance("d1", "blue")
        config = {"random_seed": 0, "damage_weights": {"a1": 1.0, "a2": 1.5}}
        model = ConfigurableModel(config, [a1, a2, d])
        state = _state([a1, a2, d])
        splits = model.determine_damage_splits(state, [a1, a2], d)
        assert abs(splits["a1"] - 0.4) < 0.001
        assert abs(splits["a2"] - 0.6) < 0.001

    def test_power_heuristic_splits(self):
        """18B + 16B vs 15B → ratios 1.20, 1.07 → weights 0.80, 0.60 → 57/43"""
        a1 = _alliance("a1", power=18e9)
        a2 = _alliance("a2", power=16e9)
        d = _alliance("d1", "blue", power=15e9)
        model = ConfigurableModel({"random_seed": 0}, [a1, a2, d])
        state = _state([a1, a2, d])
        splits = model.determine_damage_splits(state, [a1, a2], d)
        # weights: 1.5*1.2-1=0.8, 1.5*1.067-1=0.6 → 0.8/1.4≈0.571
        assert abs(splits["a1"] - 0.571) < 0.01
        assert abs(splits["a2"] - 0.429) < 0.01

    def test_power_heuristic_with_weak_attacker(self):
        """18B + 12B vs 15B → ratios 1.20, 0.80 → weights 0.80, 0.20 → 80/20"""
        a1 = _alliance("a1", power=18e9)
        a2 = _alliance("a2", power=12e9)
        d = _alliance("d1", "blue", power=15e9)
        model = ConfigurableModel({"random_seed": 0}, [a1, a2, d])
        state = _state([a1, a2, d])
        splits = model.determine_damage_splits(state, [a1, a2], d)
        assert abs(splits["a1"] - 0.80) < 0.01
        assert abs(splits["a2"] - 0.20) < 0.01


# ── M1 Tests ─────────────────────────────────────────────────────


class TestM1Targeting:
    def test_default_1to1(self):
        a1 = _alliance("a1", power=200)
        a2 = _alliance("a2", power=100)
        d1 = _alliance("d1", "blue", spice=500_000)
        d2 = _alliance("d2", "blue", spice=300_000)
        model = ConfigurableModel({"random_seed": 0}, [a1, a2, d1, d2])
        state = _state([a1, a2, d1, d2])
        targets = model.generate_targets(state, [a1, a2], [d1, d2], 1)
        # a1 (higher power) targets d1 (higher spice), a2 targets d2
        assert targets["a1"] == "d1"
        assert targets["a2"] == "d2"

    def test_config_override(self):
        a1 = _alliance("a1", power=200)
        d1 = _alliance("d1", "blue", spice=300_000)
        d2 = _alliance("d2", "blue", spice=500_000)
        config = {"random_seed": 0, "event_targets": {"1": {"a1": "d2"}}}
        model = ConfigurableModel(config, [a1, d1, d2])
        state = _state([a1, d1, d2], event_number=1)
        targets = model.generate_targets(state, [a1], [d1, d2], 1)
        assert targets["a1"] == "d2"


# ── M2 Tests ─────────────────────────────────────────────────────


class TestM2Reinforcements:
    def test_most_attacked_rule(self):
        a1 = _alliance("a1")
        a2 = _alliance("a2")
        d1 = _alliance("d1", "blue", spice=500_000)
        d2 = _alliance("d2", "blue", spice=300_000)
        model = ConfigurableModel({"random_seed": 0}, [a1, a2, d1, d2])
        state = _state([a1, a2, d1, d2])
        # Both attackers target d1
        targets = {"a1": "d1", "a2": "d1"}
        reinforcements = model.generate_reinforcements(state, targets, [d1, d2], 1)
        # d2 is untargeted, d1 has 2 attackers → max reinforcements = 1
        assert reinforcements == {"d2": "d1"}

    def test_no_untargeted(self):
        a1 = _alliance("a1")
        d1 = _alliance("d1", "blue")
        model = ConfigurableModel({"random_seed": 0}, [a1, d1])
        state = _state([a1, d1])
        targets = {"a1": "d1"}
        reinforcements = model.generate_reinforcements(state, targets, [d1], 1)
        assert reinforcements == {}

    def test_max_reinforcement_limit(self):
        a1 = _alliance("a1")
        a2 = _alliance("a2")
        d1 = _alliance("d1", "blue", spice=500_000)
        d2 = _alliance("d2", "blue", spice=300_000)
        d3 = _alliance("d3", "blue", spice=200_000)
        model = ConfigurableModel({"random_seed": 0}, [a1, a2, d1, d2, d3])
        state = _state([a1, a2, d1, d2, d3])
        # 2 attackers on d1 → max reinforcements = 1
        targets = {"a1": "d1", "a2": "d1"}
        reinforcements = model.generate_reinforcements(
            state, targets, [d1, d2, d3], 1
        )
        # Only 1 reinforcement even though 2 are untargeted
        assert len(reinforcements) == 1

    def test_config_override(self):
        d1 = _alliance("d1", "blue")
        d2 = _alliance("d2", "blue")
        config = {
            "random_seed": 0,
            "event_reinforcements": {"1": {"d2": "d1"}},
        }
        model = ConfigurableModel(config, [d1, d2])
        state = _state([d1, d2], event_number=1)
        reinforcements = model.generate_reinforcements(
            state, {"a1": "d1"}, [d1, d2], 1
        )
        assert reinforcements == {"d2": "d1"}
