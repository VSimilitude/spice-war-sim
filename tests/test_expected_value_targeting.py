import pytest

from spice_war.models.configurable import ConfigurableModel
from spice_war.utils.data_structures import Alliance, GameState
from spice_war.utils.validation import ValidationError, load_model_config


def _alliance(aid, faction="red", power=15e9, spice=500_000, rate=50_000):
    return Alliance(
        alliance_id=aid,
        faction=faction,
        power=power,
        starting_spice=spice,
        daily_spice_rate=rate,
    )


def _state(alliances, event_number=1, day="wednesday", spice_overrides=None):
    spice = {a.alliance_id: a.starting_spice for a in alliances}
    if spice_overrides:
        spice.update(spice_overrides)
    return GameState(
        current_spice=spice,
        brackets={},
        event_number=event_number,
        day=day,
        event_history=[],
        alliances=alliances,
    )


# ── ESV Algorithm Tests (1–11) ─────────────────────────────────


class TestESVAlgorithm:
    def test_01_weak_attacker_avoids_strong_defender(self):
        """Attacker with low power picks beatable defender over rich-but-strong one."""
        # A (12B) vs X (18B, 3M) → ratio 0.667, ESV ≈ 120,150
        # A (12B) vs Y (10B, 2M) → ratio 1.2, ESV = 400,000
        a = _alliance("A", power=12e9)
        dx = _alliance("X", "blue", power=18e9, spice=3_000_000)
        dy = _alliance("Y", "blue", power=10e9, spice=2_000_000)
        model = ConfigurableModel({}, [a, dx, dy])
        state = _state([a, dx, dy])
        targets = model.generate_targets(state, [a], [dx, dy], 1)
        assert targets["A"] == "Y"

    def test_02_strong_attacker_picks_richest(self):
        """Attacker who can beat everyone picks the richest defender."""
        a = _alliance("A", power=20e9)
        dx = _alliance("X", "blue", power=15e9, spice=3_000_000)
        dy = _alliance("Y", "blue", power=10e9, spice=1_000_000)
        model = ConfigurableModel({}, [a, dx, dy])
        state = _state([a, dx, dy])
        targets = model.generate_targets(state, [a], [dx, dy], 1)
        assert targets["A"] == "X"

    def test_03_equal_power_bracket(self):
        """Equal power ratios → falls back to highest-spice ordering."""
        a1 = _alliance("A1", power=15e9)
        a2 = _alliance("A2", power=15e9)
        a3 = _alliance("A3", power=15e9)
        d1 = _alliance("D1", "blue", power=15e9, spice=3_000_000)
        d2 = _alliance("D2", "blue", power=15e9, spice=2_000_000)
        d3 = _alliance("D3", "blue", power=15e9, spice=1_000_000)
        all_a = [a1, a2, a3]
        model = ConfigurableModel({}, all_a + [d1, d2, d3])
        state = _state(all_a + [d1, d2, d3])
        targets = model.generate_targets(state, all_a, [d1, d2, d3], 1)
        # All attackers have same power → processed in some order
        # ESV proportional to spice (same probs), so best target is richest
        # First attacker gets D1, second D2, third D3
        assert set(targets.values()) == {"D1", "D2", "D3"}

    def test_04_esv_calculation_correctness(self):
        """Direct ESV calculation matches hand-computed values."""
        # Attacker 15B vs Defender 15B, 2M spice, Wednesday
        # ratio = 1.0
        # full = max(0, min(1, 2.5*1.0 - 2.0)) = 0.5
        # cumul_partial = max(0, min(1, 1.75*1.0 - 0.9)) = 0.85
        # partial = 0.85 - 0.5 = 0.35
        # building_count(2M) = 3 (>= 1,805,000)
        # full theft = 3*5+10 = 25% → 2M * 0.25 = 500,000
        # partial theft = 3*5 = 15% → 2M * 0.15 = 300,000
        # ESV = 0.5*500,000 + 0.35*300,000 = 250,000 + 105,000 = 355,000
        a = _alliance("A", power=15e9)
        d = _alliance("D", "blue", power=15e9, spice=2_000_000)
        model = ConfigurableModel({}, [a, d])
        state = _state([a, d])
        esv = model._calculate_esv(a, d, state)
        assert esv == pytest.approx(355_000.0)

    def test_05_building_count_affects_esv(self):
        """Higher building count (more spice) → higher theft % → higher ESV."""
        # Defender A: 3.2M spice → 4 buildings, full theft = 30%
        # Defender B: 600K spice → 1 building, full theft = 15%
        # Same attacker power 20B, defender power 10B → ratio 2.0
        # full prob = min(1, 2.5*2.0 - 2.0) = 1.0
        # ESV_A = 1.0 * (3,200,000 * 0.30) = 960,000
        # ESV_B = 1.0 * (600,000 * 0.15) = 90,000
        a = _alliance("A", power=20e9)
        da = _alliance("DA", "blue", power=10e9, spice=3_200_000)
        db = _alliance("DB", "blue", power=10e9, spice=600_000)
        model = ConfigurableModel({}, [a, da, db])
        state = _state([a, da, db])
        targets = model.generate_targets(state, [a], [da, db], 1)
        assert targets["A"] == "DA"

    def test_06_priority_order_respected(self):
        """Highest-power attacker picks first."""
        # A1 (20B) picks first, A2 (10B) picks from remaining
        # D_X (15B, 3M), D_Y (8B, 2M)
        # A1 can beat both; X has more spice → A1 picks X
        # A2 gets Y
        a1 = _alliance("A1", power=20e9)
        a2 = _alliance("A2", power=10e9)
        dx = _alliance("X", "blue", power=15e9, spice=3_000_000)
        dy = _alliance("Y", "blue", power=8e9, spice=2_000_000)
        model = ConfigurableModel({}, [a1, a2, dx, dy])
        state = _state([a1, a2, dx, dy])
        targets = model.generate_targets(state, [a1, a2], [dx, dy], 1)
        assert targets["A1"] == "X"
        assert targets["A2"] == "Y"

    def test_07_tiebreaking_by_spice_then_id(self):
        """Equal ESV → higher spice wins; equal spice → alphabetical id wins."""
        # Two defenders with same power and same spice → same ESV
        # Alphabetical: "Alpha" < "Beta" → Alpha wins
        a = _alliance("A", power=15e9)
        d_alpha = _alliance("Alpha", "blue", power=15e9, spice=2_000_000)
        d_beta = _alliance("Beta", "blue", power=15e9, spice=2_000_000)
        model = ConfigurableModel({}, [a, d_alpha, d_beta])
        state = _state([a, d_alpha, d_beta])
        targets = model.generate_targets(state, [a], [d_alpha, d_beta], 1)
        assert targets["A"] == "Alpha"

        # Now Alpha has more spice → Alpha still wins (spice tiebreak)
        state2 = _state([a, d_alpha, d_beta], spice_overrides={"Alpha": 2_100_000})
        targets2 = model.generate_targets(state2, [a], [d_alpha, d_beta], 1)
        assert targets2["A"] == "Alpha"

    def test_08_matrix_probabilities_used(self):
        """Matrix entry overrides heuristic for ESV calculation."""
        # Without matrix: attacker (10B) vs defender (15B) → weak, low ESV
        # With matrix: set 100% full_success for one pairing
        a = _alliance("A", power=10e9)
        dx = _alliance("X", "blue", power=15e9, spice=1_000_000)
        dy = _alliance("Y", "blue", power=15e9, spice=2_000_000)
        config = {
            "battle_outcome_matrix": {
                "wednesday": {
                    "A": {
                        "X": {"full_success": 1.0, "partial_success": 0.0},
                    }
                }
            }
        }
        model = ConfigurableModel(config, [a, dx, dy])
        state = _state([a, dx, dy])

        # X: matrix says 100% full, 1M spice, 2 buildings → 20% theft → ESV = 200,000
        esv_x = model._calculate_esv(a, dx, state)
        # Y: heuristic for 10/15 = 0.667 ratio → low probs
        esv_y = model._calculate_esv(a, dy, state)
        assert esv_x > esv_y

        targets = model.generate_targets(state, [a], [dx, dy], 1)
        assert targets["A"] == "X"

    def test_09_custom_outcome_included_in_esv(self):
        """Custom outcome contributes to ESV."""
        a = _alliance("A", power=10e9)
        d = _alliance("D", "blue", power=15e9, spice=2_000_000)
        config = {
            "battle_outcome_matrix": {
                "wednesday": {
                    "A": {
                        "D": {
                            "full_success": 0.0,
                            "partial_success": 0.0,
                            "custom": 0.5,
                            "custom_theft_percentage": 20.0,
                        }
                    }
                }
            }
        }
        model = ConfigurableModel(config, [a, d])
        state = _state([a, d])
        esv = model._calculate_esv(a, d, state)
        # custom contribution: 0.5 * (2,000,000 * 0.20) = 200,000
        assert esv == pytest.approx(200_000.0)

    def test_10_single_attacker_single_defender(self):
        """Trivial case — only one option."""
        a = _alliance("A", power=5e9)
        d = _alliance("D", "blue", power=20e9, spice=1_000_000)
        model = ConfigurableModel({}, [a, d])
        state = _state([a, d])
        targets = model.generate_targets(state, [a], [d], 1)
        assert targets["A"] == "D"

    def test_11_all_defenders_too_strong(self):
        """All ESVs are 0 — still assigns targets via tie-breaking."""
        # ratio = 1/20 = 0.05 → all probs 0 → all ESV 0
        # Tie-break: highest spice → D1 (3M), then D2 (2M)
        a1 = _alliance("A1", power=1e9)
        a2 = _alliance("A2", power=1e9)
        d1 = _alliance("D1", "blue", power=20e9, spice=3_000_000)
        d2 = _alliance("D2", "blue", power=20e9, spice=2_000_000)
        model = ConfigurableModel({}, [a1, a2, d1, d2])
        state = _state([a1, a2, d1, d2])
        targets = model.generate_targets(state, [a1, a2], [d1, d2], 1)
        assert set(targets.values()) == {"D1", "D2"}
        # Both attackers same power → first alphabetically picks first
        # A1 < A2, but they have same power so sort is stable / implementation-defined
        # Key assertion: both defenders get assigned
        assert len(targets) == 2


# ── Configuration & Resolution Tests (12–20) ───────────────────


class TestConfigResolution:
    def test_12_targeting_strategy_highest_spice(self):
        """Setting highest_spice uses original heuristic."""
        # A1 (12B) vs X (18B, 3M) and Y (10B, 2M)
        # ESV would pick Y, but highest_spice picks X (more spice)
        a1 = _alliance("A1", power=20e9)
        a2 = _alliance("A2", power=15e9)
        a3 = _alliance("A3", power=10e9)
        d1 = _alliance("D1", "blue", power=15e9, spice=3_000_000)
        d2 = _alliance("D2", "blue", power=15e9, spice=2_000_000)
        d3 = _alliance("D3", "blue", power=15e9, spice=1_000_000)
        config = {"targeting_strategy": "highest_spice"}
        all_a = [a1, a2, a3]
        all_d = [d1, d2, d3]
        model = ConfigurableModel(config, all_a + all_d)
        state = _state(all_a + all_d)
        targets = model.generate_targets(state, all_a, all_d, 1)
        # Highest power → highest spice, 1:1
        assert targets["A1"] == "D1"
        assert targets["A2"] == "D2"
        assert targets["A3"] == "D3"

    def test_13_targeting_strategy_expected_value_explicit(self):
        """Explicit expected_value behaves same as default."""
        a = _alliance("A", power=12e9)
        dx = _alliance("X", "blue", power=18e9, spice=3_000_000)
        dy = _alliance("Y", "blue", power=10e9, spice=2_000_000)
        config_explicit = {"targeting_strategy": "expected_value"}
        config_default = {}

        model_explicit = ConfigurableModel(config_explicit, [a, dx, dy])
        model_default = ConfigurableModel(config_default, [a, dx, dy])
        state = _state([a, dx, dy])

        targets_explicit = model_explicit.generate_targets(state, [a], [dx, dy], 1)
        targets_default = model_default.generate_targets(state, [a], [dx, dy], 1)
        assert targets_explicit == targets_default

    def test_14_default_targets_fixed_pin(self):
        """default_targets pin overrides algorithm for every event."""
        a1 = _alliance("A1", power=12e9)
        a2 = _alliance("A2", power=10e9)
        d1 = _alliance("D1", "blue", power=18e9, spice=3_000_000)
        d2 = _alliance("D2", "blue", power=10e9, spice=2_000_000)
        config = {"default_targets": {"A1": {"target": "D1"}}}
        model = ConfigurableModel(config, [a1, a2, d1, d2])

        # Event 1
        state1 = _state([a1, a2, d1, d2], event_number=1)
        targets1 = model.generate_targets(state1, [a1, a2], [d1, d2], 1)
        assert targets1["A1"] == "D1"
        assert targets1["A2"] == "D2"

        # Event 2 — pin still applies
        state2 = _state([a1, a2, d1, d2], event_number=2)
        targets2 = model.generate_targets(state2, [a1, a2], [d1, d2], 1)
        assert targets2["A1"] == "D1"

    def test_15_default_targets_per_alliance_strategy(self):
        """Per-alliance strategy override in default_targets."""
        # A1 uses highest_spice, A2 uses default ESV
        a1 = _alliance("A1", power=12e9)
        a2 = _alliance("A2", power=12e9)
        # D1: strong, rich. D2: weak, less rich.
        d1 = _alliance("D1", "blue", power=18e9, spice=3_000_000)
        d2 = _alliance("D2", "blue", power=10e9, spice=2_000_000)
        config = {"default_targets": {"A1": {"strategy": "highest_spice"}}}
        model = ConfigurableModel(config, [a1, a2, d1, d2])
        state = _state([a1, a2, d1, d2])
        targets = model.generate_targets(state, [a1, a2], [d1, d2], 1)
        # A1 uses highest_spice → picks D1 (3M > 2M)
        # A2 uses ESV → D2 is the only remaining defender
        assert targets["A1"] == "D1"
        assert targets["A2"] == "D2"

    def test_16_event_targets_overrides_default_pin(self):
        """event_targets pin overrides default_targets pin for that event."""
        a1 = _alliance("A1", power=12e9)
        d1 = _alliance("D1", "blue", power=10e9, spice=2_000_000)
        d2 = _alliance("D2", "blue", power=10e9, spice=1_000_000)
        config = {
            "default_targets": {"A1": {"target": "D1"}},
            "event_targets": {"3": {"A1": {"target": "D2"}}},
        }
        model = ConfigurableModel(config, [a1, d1, d2])

        # Event 3: event override → D2
        state3 = _state([a1, d1, d2], event_number=3)
        targets3 = model.generate_targets(state3, [a1], [d1, d2], 1)
        assert targets3["A1"] == "D2"

        # Event 1: default pin → D1
        state1 = _state([a1, d1, d2], event_number=1)
        targets1 = model.generate_targets(state1, [a1], [d1, d2], 1)
        assert targets1["A1"] == "D1"

    def test_17_event_targets_strategy_overrides_default_pin(self):
        """event_targets strategy override unpins alliance for that event."""
        a1 = _alliance("A1", power=12e9)
        d1 = _alliance("D1", "blue", power=18e9, spice=3_000_000)
        d2 = _alliance("D2", "blue", power=10e9, spice=2_000_000)
        config = {
            "default_targets": {"A1": {"target": "D1"}},
            "event_targets": {"3": {"A1": {"strategy": "expected_value"}}},
        }
        model = ConfigurableModel(config, [a1, d1, d2])

        # Event 3: strategy override → ESV picks D2 (more beatable)
        state3 = _state([a1, d1, d2], event_number=3)
        targets3 = model.generate_targets(state3, [a1], [d1, d2], 1)
        assert targets3["A1"] == "D2"

        # Event 1: default pin → D1
        state1 = _state([a1, d1, d2], event_number=1)
        targets1 = model.generate_targets(state1, [a1], [d1, d2], 1)
        assert targets1["A1"] == "D1"

    def test_18_pinned_target_not_in_bracket(self):
        """Pin ignored when target isn't in current defender list."""
        a1 = _alliance("A1", power=12e9)
        d1 = _alliance("D1", "blue", power=10e9, spice=2_000_000)
        d_other = _alliance("D_other", "blue", power=10e9, spice=1_000_000)
        config = {"default_targets": {"A1": {"target": "D_other"}}}
        model = ConfigurableModel(config, [a1, d1, d_other])

        # D_other not in bracket defenders
        state = _state([a1, d1, d_other])
        targets = model.generate_targets(state, [a1], [d1], 1)
        # Pin invalid → falls through to global strategy (ESV) → picks D1
        assert targets["A1"] == "D1"

    def test_19_pins_resolved_before_algorithm(self):
        """Pinned defenders are removed from algorithm pool."""
        # A1 pinned to D1. A2 uses ESV. D1 is best ESV target for A2.
        a1 = _alliance("A1", power=10e9)
        a2 = _alliance("A2", power=20e9)
        d1 = _alliance("D1", "blue", power=10e9, spice=3_000_000)
        d2 = _alliance("D2", "blue", power=10e9, spice=1_000_000)
        config = {"default_targets": {"A1": {"target": "D1"}}}
        model = ConfigurableModel(config, [a1, a2, d1, d2])
        state = _state([a1, a2, d1, d2])
        targets = model.generate_targets(state, [a1, a2], [d1, d2], 1)
        assert targets["A1"] == "D1"  # pinned
        assert targets["A2"] == "D2"  # D1 already claimed

    def test_20_partial_event_targets_plus_default_targets(self):
        """Complex config: mix of pins, strategies, and global fallback."""
        a1 = _alliance("A1", power=15e9)
        a2 = _alliance("A2", power=12e9)
        a3 = _alliance("A3", power=10e9)
        d1 = _alliance("D1", "blue", power=18e9, spice=3_000_000)
        d2 = _alliance("D2", "blue", power=10e9, spice=2_000_000)
        d3 = _alliance("D3", "blue", power=8e9, spice=1_000_000)
        config = {
            "targeting_strategy": "expected_value",
            "default_targets": {
                "A1": {"target": "D1"},
                "A2": {"strategy": "highest_spice"},
            },
            "event_targets": {
                "3": {"A1": {"strategy": "expected_value"}},
            },
        }
        all_a = [a1, a2, a3]
        all_d = [d1, d2, d3]
        model = ConfigurableModel(config, all_a + all_d)

        # Event 1: A1→D1 (pin), A2→highest_spice, A3→ESV (global)
        state1 = _state(all_a + all_d, event_number=1)
        targets1 = model.generate_targets(state1, all_a, all_d, 1)
        assert targets1["A1"] == "D1"  # pinned
        # A2 highest_spice from remaining {D2, D3} → D2 (2M > 1M)
        assert targets1["A2"] == "D2"
        # A3 ESV from remaining {D3} → D3
        assert targets1["A3"] == "D3"

        # Event 3: A1→ESV (event override), A2→highest_spice, A3→ESV (global)
        state3 = _state(all_a + all_d, event_number=3)
        targets3 = model.generate_targets(state3, all_a, all_d, 1)
        # A1 uses ESV now (not pinned for event 3)
        # All three use algorithms, processed by power order: A1(15B), A2(12B), A3(10B)
        # A2 uses highest_spice; A1, A3 use ESV
        assert "A1" in targets3
        assert "A2" in targets3
        assert "A3" in targets3
        assert set(targets3.values()) == {"D1", "D2", "D3"}


# ── Validation Error Tests (21–22) ─────────────────────────────


class TestValidationErrors:
    def test_21_invalid_targeting_strategy(self, tmp_path):
        """Unrecognized strategy value raises ValidationError."""
        import json

        config = {"targeting_strategy": "unknown"}
        path = tmp_path / "model.json"
        path.write_text(json.dumps(config))
        with pytest.raises(ValidationError, match="targeting_strategy"):
            load_model_config(path, {"A1", "D1"})

    def test_22_invalid_override_dict(self, tmp_path):
        """Override dict missing target/strategy raises ValidationError."""
        import json

        config = {"default_targets": {"A1": {"invalid_key": "value"}}}
        path = tmp_path / "model.json"
        path.write_text(json.dumps(config))
        with pytest.raises(ValidationError, match="'target' or 'strategy'"):
            load_model_config(path, {"A1", "D1"})
