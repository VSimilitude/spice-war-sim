import json
import sys
from pathlib import Path

import pytest

from spice_war.models.configurable import ConfigurableModel
from spice_war.utils.data_structures import Alliance, GameState
from spice_war.utils.validation import ValidationError, load_model_config

FIXTURES = Path(__file__).parent / "fixtures"
STATE_FILE = FIXTURES / "sample_state.json"
MODEL_FILE = FIXTURES / "sample_model.json"


# ── Shared Helpers ────────────────────────────────────────────────


def _alliance(aid, faction="red", power=100, spice=1_000_000, rate=50_000):
    return Alliance(
        alliance_id=aid,
        faction=faction,
        power=power,
        starting_spice=spice,
        daily_spice_rate=rate,
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


def _write_model(tmp_path, data, name="model.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return str(path)


# ── Feature A: Faction-Level Targeting Strategy ───────────────────


class TestFeatureA:
    """Tests A1–A7: faction_targeting_strategy."""

    def _make_factions(self):
        """Two red attackers, two blue defenders with different spice."""
        return [
            _alliance("R1", "red", power=100, spice=1_000_000),
            _alliance("R2", "red", power=100, spice=1_000_000),
            _alliance("B1", "blue", power=80, spice=5_000_000),
            _alliance("B2", "blue", power=80, spice=2_000_000),
        ]

    def test_a1_faction_strategy_applied(self):
        """Red uses highest_spice, blue uses default (expected_value)."""
        alliances = self._make_factions()
        config = {
            "random_seed": 0,
            "faction_targeting_strategy": {"red": "highest_spice"},
            "targeting_strategy": "expected_value",
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)

        # Red attacks blue — both red attackers should target B1 (highest spice)
        red_attackers = [a for a in alliances if a.faction == "red"]
        blue_defenders = [a for a in alliances if a.faction == "blue"]
        targets = model.generate_targets(state, red_attackers, blue_defenders, 1)

        # With highest_spice, highest-power attacker gets B1 first
        assert targets["R1"] == "B1"
        assert targets["R2"] == "B2"

    def test_a2_per_alliance_override_wins(self):
        """default_targets for R1 overrides faction_targeting_strategy."""
        alliances = self._make_factions()
        # B2 has less spice so highest_spice wouldn't pick it first
        config = {
            "random_seed": 0,
            "faction_targeting_strategy": {"red": "highest_spice"},
            "default_targets": {"R1": {"target": "B2"}},
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)

        red_attackers = [a for a in alliances if a.faction == "red"]
        blue_defenders = [a for a in alliances if a.faction == "blue"]
        targets = model.generate_targets(state, red_attackers, blue_defenders, 1)

        assert targets["R1"] == "B2"  # pinned by default_targets
        assert targets["R2"] == "B1"  # highest_spice from faction strategy

    def test_a3_event_override_wins(self):
        """event_targets overrides faction_targeting_strategy."""
        alliances = self._make_factions()
        config = {
            "random_seed": 0,
            "faction_targeting_strategy": {"red": "highest_spice"},
            "event_targets": {"1": {"R1": {"target": "B2"}}},
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, event_number=1)

        red_attackers = [a for a in alliances if a.faction == "red"]
        blue_defenders = [a for a in alliances if a.faction == "blue"]
        targets = model.generate_targets(state, red_attackers, blue_defenders, 1)

        assert targets["R1"] == "B2"  # pinned by event_targets

    def test_a4_global_fallback(self):
        """Faction not in faction_targeting_strategy uses global strategy."""
        alliances = self._make_factions()
        config = {
            "random_seed": 0,
            "faction_targeting_strategy": {"red": "highest_spice"},
            "targeting_strategy": "expected_value",
        }
        model = ConfigurableModel(config, alliances)
        # Blue attacks red — blue not in faction_targeting_strategy, uses EV
        state = _state(alliances)
        blue_attackers = [a for a in alliances if a.faction == "blue"]
        red_defenders = [a for a in alliances if a.faction == "red"]
        targets = model.generate_targets(state, blue_attackers, red_defenders, 1)

        # Both should use expected_value (global fallback)
        assert "B1" in targets
        assert "B2" in targets

    def test_a5_both_factions_configured(self):
        """Each faction can have a different strategy."""
        alliances = self._make_factions()
        config = {
            "random_seed": 0,
            "faction_targeting_strategy": {
                "red": "highest_spice",
                "blue": "expected_value",
            },
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)

        red_attackers = [a for a in alliances if a.faction == "red"]
        blue_defenders = [a for a in alliances if a.faction == "blue"]
        targets = model.generate_targets(state, red_attackers, blue_defenders, 1)

        # Red uses highest_spice → R1 gets B1 (highest)
        assert targets["R1"] == "B1"

    def test_a6_validation_unknown_faction(self, tmp_path):
        """Faction name not in alliances raises ValidationError."""
        alliances = self._make_factions()
        alliance_ids = {a.alliance_id for a in alliances}
        path = _write_model(tmp_path, {
            "faction_targeting_strategy": {"unknown_faction": "highest_spice"},
        })
        with pytest.raises(ValidationError, match="unknown faction"):
            load_model_config(path, alliance_ids, alliances)

    def test_a7_validation_invalid_strategy(self, tmp_path):
        """Invalid strategy value raises ValidationError."""
        alliances = self._make_factions()
        alliance_ids = {a.alliance_id for a in alliances}
        path = _write_model(tmp_path, {
            "faction_targeting_strategy": {"red": "invalid_strategy"},
        })
        with pytest.raises(ValidationError, match="must be one of"):
            load_model_config(path, alliance_ids, alliances)


# ── Feature B: Wildcard Battle Outcome Overrides ──────────────────


class TestFeatureB:
    """Tests B1–B12: wildcard '*' in battle_outcome_matrix."""

    def _make_alliances(self):
        return [
            _alliance("Ghst", "red", power=100, spice=1_000_000),
            _alliance("RAG3", "red", power=90, spice=800_000),
            _alliance("VON", "blue", power=95, spice=1_200_000),
            _alliance("UTW", "blue", power=85, spice=900_000),
        ]

    def test_b1_attacker_default_applied(self):
        """Ghst with '*' wildcard gets full_success against any defender."""
        alliances = self._make_alliances()
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {"*": {"full_success": 1.0}},
                },
            },
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, day="wednesday")

        # Ghst vs VON
        outcome, probs = model.determine_battle_outcome(
            state, [alliances[0]], [alliances[2]], "wednesday"
        )
        assert probs["full_success"] == 1.0
        assert outcome == "full_success"

        # Ghst vs UTW
        outcome, probs = model.determine_battle_outcome(
            state, [alliances[0]], [alliances[3]], "wednesday"
        )
        assert probs["full_success"] == 1.0

    def test_b2_defender_default_applied(self):
        """'*' → VON causes all attackers to fail against VON."""
        alliances = self._make_alliances()
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "*": {"VON": {"full_success": 0.0, "partial_success": 0.0}},
                },
            },
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, day="wednesday")

        # Any attacker vs VON should fail
        outcome, probs = model.determine_battle_outcome(
            state, [alliances[0]], [alliances[2]], "wednesday"
        )
        assert probs["full_success"] == 0.0
        assert probs["partial_success"] == 0.0
        assert probs["fail"] == 1.0

    def test_b3_exact_pairing_wins_over_attacker_default(self):
        """Explicit Ghst→RAG3 overrides Ghst→'*'."""
        alliances = self._make_alliances()
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {
                        "*": {"full_success": 1.0},
                        "VON": {"full_success": 0.0, "partial_success": 0.0},
                    },
                },
            },
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, day="wednesday")

        # Ghst vs VON: explicit entry → 0%
        _, probs_von = model.determine_battle_outcome(
            state, [alliances[0]], [alliances[2]], "wednesday"
        )
        assert probs_von["full_success"] == 0.0

        # Ghst vs UTW: wildcard → 100%
        _, probs_utw = model.determine_battle_outcome(
            state, [alliances[0]], [alliances[3]], "wednesday"
        )
        assert probs_utw["full_success"] == 1.0

    def test_b4_exact_pairing_wins_over_defender_default(self):
        """Explicit VON→Ghst overrides '*'→Ghst."""
        alliances = self._make_alliances()
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "*": {"Ghst": {"full_success": 0.0, "partial_success": 0.0}},
                    "VON": {"Ghst": {"full_success": 1.0}},
                },
            },
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, day="wednesday")

        # VON vs Ghst: explicit → 100%
        _, probs_von = model.determine_battle_outcome(
            state, [alliances[2]], [alliances[0]], "wednesday"
        )
        assert probs_von["full_success"] == 1.0

        # RAG3 vs Ghst: defender default → 0%
        _, probs_rag = model.determine_battle_outcome(
            state, [alliances[1]], [alliances[0]], "wednesday"
        )
        assert probs_rag["full_success"] == 0.0

    def test_b5_heuristic_fallback(self):
        """No wildcard or explicit entry → heuristic."""
        alliances = self._make_alliances()
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {"*": {"full_success": 1.0}},
                },
            },
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, day="wednesday")

        # RAG3 vs VON: no entry, no wildcard for RAG3 → heuristic
        _, probs = model.determine_battle_outcome(
            state, [alliances[1]], [alliances[2]], "wednesday"
        )
        # Heuristic: ratio = 90/95 ≈ 0.947
        expected = model._heuristic_probabilities(alliances[1], alliances[2], "wednesday")
        assert abs(probs["full_success"] - expected["full_success"]) < 0.001

    def test_b6_custom_outcome_in_wildcard(self):
        """Wildcard with custom outcome."""
        alliances = self._make_alliances()
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {"*": {"custom": 1.0, "custom_theft_percentage": 15}},
                },
            },
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, day="wednesday")

        outcome, probs = model.determine_battle_outcome(
            state, [alliances[0]], [alliances[2]], "wednesday"
        )
        assert probs["custom"] == 1.0
        assert probs["custom_theft_percentage"] == 15
        assert outcome == "custom"

    def test_b7_different_days_independent(self):
        """Wildcard on wednesday doesn't affect saturday."""
        alliances = self._make_alliances()
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {"*": {"full_success": 1.0}},
                },
            },
        }
        model = ConfigurableModel(config, alliances)

        # Wednesday: wildcard applies
        state_wed = _state(alliances, day="wednesday")
        _, probs_wed = model.determine_battle_outcome(
            state_wed, [alliances[0]], [alliances[2]], "wednesday"
        )
        assert probs_wed["full_success"] == 1.0

        # Saturday: no entry → heuristic
        state_sat = _state(alliances, day="saturday")
        _, probs_sat = model.determine_battle_outcome(
            state_sat, [alliances[0]], [alliances[2]], "saturday"
        )
        expected = model._heuristic_probabilities(alliances[0], alliances[2], "saturday")
        assert abs(probs_sat["full_success"] - expected["full_success"]) < 0.001

    def test_b8_competing_wildcards_rejected(self, tmp_path):
        """Attacker default + defender default overlap → ValidationError."""
        alliances = self._make_alliances()
        alliance_ids = {a.alliance_id for a in alliances}
        path = _write_model(tmp_path, {
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {"*": {"full_success": 1.0}},
                    "*": {"VON": {"full_success": 0.0, "partial_success": 0.0}},
                },
            },
        })
        with pytest.raises(ValidationError, match="competing wildcards"):
            load_model_config(path, alliance_ids, alliances)

    def test_b9_competing_wildcards_with_explicit_ok(self, tmp_path):
        """Same overlap but with explicit pairing → passes validation."""
        alliances = self._make_alliances()
        alliance_ids = {a.alliance_id for a in alliances}
        path = _write_model(tmp_path, {
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {
                        "*": {"full_success": 1.0},
                        "VON": {"full_success": 1.0},
                    },
                    "*": {"VON": {"full_success": 0.0, "partial_success": 0.0}},
                },
            },
        })
        # Should not raise
        config = load_model_config(path, alliance_ids, alliances)
        assert "battle_outcome_matrix" in config

    def test_b10_wildcard_probabilities_validated(self, tmp_path):
        """Wildcard pairing with sum > 1.0 → ValidationError."""
        alliances = self._make_alliances()
        alliance_ids = {a.alliance_id for a in alliances}
        path = _write_model(tmp_path, {
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {"*": {"full_success": 0.8, "partial_success": 0.5}},
                },
            },
        })
        with pytest.raises(ValidationError, match="exceeding 1.0"):
            load_model_config(path, alliance_ids, alliances)

    def test_b11_esv_uses_wildcards(self):
        """ESV calculation incorporates wildcard entries."""
        alliances = self._make_alliances()
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {"*": {"full_success": 1.0}},
                },
            },
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, day="wednesday")

        esv = model._calculate_esv(alliances[0], alliances[2], state)
        # With 100% full_success, ESV = defender_spice * theft_pct / 100
        assert esv > 0

        # Compare to what heuristic would give — wildcard ESV should be higher
        # since 100% full_success > heuristic probability
        model_no_wc = ConfigurableModel({"random_seed": 0}, alliances)
        esv_heuristic = model_no_wc._calculate_esv(alliances[0], alliances[2], state)
        assert esv >= esv_heuristic

    def test_b12_multi_attacker_averaging_with_wildcards(self):
        """Multiple attackers with wildcard entries are averaged correctly."""
        alliances = self._make_alliances()
        config = {
            "random_seed": 0,
            "battle_outcome_matrix": {
                "wednesday": {
                    "Ghst": {"*": {"full_success": 1.0}},
                    # RAG3 has no entry → heuristic
                },
            },
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, day="wednesday")

        # Two attackers: Ghst (wildcard 100%) + RAG3 (heuristic)
        _, probs = model.determine_battle_outcome(
            state, [alliances[0], alliances[1]], [alliances[2]], "wednesday"
        )

        heuristic = model._heuristic_probabilities(alliances[1], alliances[2], "wednesday")
        expected_full = (1.0 + heuristic["full_success"]) / 2
        assert abs(probs["full_success"] - expected_full) < 0.001


# ── Feature C: Comparative Monte Carlo ────────────────────────────


class TestFeatureC:
    """Tests C1–C8: compare_models.py."""

    def test_c1_two_models_compared(self, tmp_path, capsys):
        from scripts.compare_models import main as compare_main

        m1 = _write_model(tmp_path, {"targeting_strategy": "expected_value"}, "m1.json")
        m2 = _write_model(tmp_path, {"targeting_strategy": "highest_spice"}, "m2.json")

        rc = compare_main([
            str(STATE_FILE), m1, m2,
            "-n", "10", "--base-seed", "0",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[A]" in out
        assert "[B]" in out
        assert "Tier 1 Distribution:" in out
        assert "Mean Spice:" in out

    def test_c2_three_models(self, tmp_path, capsys):
        from scripts.compare_models import main as compare_main

        m1 = _write_model(tmp_path, {"targeting_strategy": "expected_value"}, "m1.json")
        m2 = _write_model(tmp_path, {"targeting_strategy": "highest_spice"}, "m2.json")
        m3 = _write_model(tmp_path, {}, "m3.json")

        rc = compare_main([
            str(STATE_FILE), m1, m2, m3,
            "-n", "10", "--base-seed", "0",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[A]" in out
        assert "[B]" in out
        assert "[C]" in out

    def test_c3_same_model_twice(self, tmp_path, capsys):
        from scripts.compare_models import main as compare_main

        m = _write_model(tmp_path, {"targeting_strategy": "expected_value"}, "m.json")
        output_path = tmp_path / "out.json"

        rc = compare_main([
            str(STATE_FILE), m, m,
            "-n", "10", "--base-seed", "0",
            "--output", str(output_path),
        ])
        assert rc == 0

        with open(output_path) as f:
            data = json.load(f)

        # All values should be identical
        for aid, model_results in data["results"].items():
            a_stats = model_results["A"]["spice_stats"]
            b_stats = model_results["B"]["spice_stats"]
            assert a_stats["mean"] == b_stats["mean"]
            assert model_results["A"]["tier_distribution"] == model_results["B"]["tier_distribution"]

    def test_c4_alliance_filter(self, tmp_path, capsys):
        from scripts.compare_models import main as compare_main

        m = _write_model(tmp_path, {}, "m.json")

        rc = compare_main([
            str(STATE_FILE), m, m,
            "-n", "10", "--base-seed", "0",
            "--alliance", "RedWolves", "--alliance", "BlueLions",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "RedWolves" in out
        assert "BlueLions" in out
        assert "RedFalcons" not in out
        assert "BlueShields" not in out

    def test_c5_json_output_structure(self, tmp_path):
        from scripts.compare_models import main as compare_main

        m1 = _write_model(tmp_path, {"targeting_strategy": "expected_value"}, "m1.json")
        m2 = _write_model(tmp_path, {"targeting_strategy": "highest_spice"}, "m2.json")
        output_path = tmp_path / "out.json"

        compare_main([
            str(STATE_FILE), m1, m2,
            "-n", "10", "--base-seed", "0",
            "--output", str(output_path),
        ])

        with open(output_path) as f:
            data = json.load(f)

        assert data["num_iterations"] == 10
        assert data["base_seed"] == 0
        assert len(data["models"]) == 2
        assert data["models"][0]["label"] == "A"
        assert data["models"][1]["label"] == "B"
        assert "results" in data

        # Check per-alliance per-model structure
        for aid, model_results in data["results"].items():
            for label in ["A", "B"]:
                assert "tier_distribution" in model_results[label]
                assert "spice_stats" in model_results[label]

    def test_c6_quiet_mode(self, tmp_path, capsys):
        from scripts.compare_models import main as compare_main

        m = _write_model(tmp_path, {}, "m.json")

        rc = compare_main([
            str(STATE_FILE), m, m,
            "-n", "10", "--quiet",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert out == ""

    def test_c7_same_seeds_across_models(self, tmp_path):
        from scripts.compare_models import main as compare_main

        m = _write_model(tmp_path, {"targeting_strategy": "expected_value"}, "m.json")
        output_path = tmp_path / "out.json"

        compare_main([
            str(STATE_FILE), m, m,
            "-n", "10", "--base-seed", "42",
            "--output", str(output_path),
        ])

        with open(output_path) as f:
            data = json.load(f)

        # Same model + same seeds → identical results
        for aid, model_results in data["results"].items():
            assert model_results["A"] == model_results["B"]

    def test_c8_sort_order(self, tmp_path, capsys):
        from scripts.compare_models import main as compare_main

        m = _write_model(tmp_path, {}, "m.json")

        rc = compare_main([
            str(STATE_FILE), m, m,
            "-n", "50", "--base-seed", "0",
        ])
        assert rc == 0
        out = capsys.readouterr().out

        # Parse the tier 1 table to verify sort order
        lines = out.split("\n")
        t1_start = None
        for i, line in enumerate(lines):
            if "Tier 1 Distribution:" in line:
                t1_start = i + 1  # skip header row
                break

        assert t1_start is not None
        # Skip column header line
        t1_lines = []
        for line in lines[t1_start + 1:]:
            line = line.strip()
            if not line or "Mean Spice:" in line:
                break
            t1_lines.append(line)

        assert len(t1_lines) >= 2

        # Extract T1 values for first model
        t1_values = []
        for line in t1_lines:
            parts = line.split()
            # First part is alliance name, rest are percentages
            pct = float(parts[1].rstrip("%"))
            t1_values.append(pct)

        # Verify descending order
        for i in range(len(t1_values) - 1):
            assert t1_values[i] >= t1_values[i + 1] or t1_values[i] == t1_values[i + 1]


# ── Feature D: Alliance-Filtered Output ───────────────────────────


class TestFeatureD:
    """Tests D1–D7: --alliance filter on run_monte_carlo.py and run_battle.py."""

    def test_d1_single_alliance_filter_mc(self, capsys):
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from run_monte_carlo import main as mc_main

        rc = mc_main([
            str(STATE_FILE), str(MODEL_FILE),
            "-n", "10", "--base-seed", "0",
            "--alliance", "RedWolves",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "RedWolves" in out
        assert "BlueLions" not in out
        assert "BlueShields" not in out
        assert "RedFalcons" not in out

    def test_d2_multiple_alliance_filter(self, capsys):
        from run_monte_carlo import main as mc_main

        rc = mc_main([
            str(STATE_FILE), str(MODEL_FILE),
            "-n", "10", "--base-seed", "0",
            "--alliance", "RedWolves", "--alliance", "BlueLions",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "RedWolves" in out
        assert "BlueLions" in out
        assert "RedFalcons" not in out
        assert "BlueShields" not in out

    def test_d3_no_filter_shows_all(self, capsys):
        from run_monte_carlo import main as mc_main

        rc = mc_main([
            str(STATE_FILE), str(MODEL_FILE),
            "-n", "10", "--base-seed", "0",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "RedWolves" in out
        assert "RedFalcons" in out
        assert "BlueLions" in out
        assert "BlueShields" in out

    def test_d4_unknown_alliance_warns(self, capsys):
        from run_monte_carlo import main as mc_main

        rc = mc_main([
            str(STATE_FILE), str(MODEL_FILE),
            "-n", "10", "--base-seed", "0",
            "--alliance", "FAKE",
        ])
        assert rc == 0
        err = capsys.readouterr().err
        assert "Warning" in err
        assert "FAKE" in err

    def test_d5_simulation_unchanged(self, tmp_path):
        from run_monte_carlo import main as mc_main

        # Run with filter
        out_filtered = tmp_path / "filtered.json"
        mc_main([
            str(STATE_FILE), str(MODEL_FILE),
            "-n", "10", "--base-seed", "0",
            "--alliance", "RedWolves",
            "--output", str(out_filtered),
            "--quiet",
        ])

        # Run without filter
        out_full = tmp_path / "full.json"
        mc_main([
            str(STATE_FILE), str(MODEL_FILE),
            "-n", "10", "--base-seed", "0",
            "--output", str(out_full),
            "--quiet",
        ])

        with open(out_filtered) as f:
            filtered = json.load(f)
        with open(out_full) as f:
            full = json.load(f)

        # RedWolves values should be identical
        assert filtered["tier_distribution"]["RedWolves"] == full["tier_distribution"]["RedWolves"]
        assert filtered["spice_stats"]["RedWolves"] == full["spice_stats"]["RedWolves"]

    def test_d6_json_output_filtered(self, tmp_path):
        from run_monte_carlo import main as mc_main

        output_path = tmp_path / "out.json"
        mc_main([
            str(STATE_FILE), str(MODEL_FILE),
            "-n", "10", "--base-seed", "0",
            "--alliance", "RedWolves",
            "--output", str(output_path),
            "--quiet",
        ])

        with open(output_path) as f:
            data = json.load(f)

        assert "RedWolves" in data["tier_distribution"]
        assert "BlueLions" not in data["tier_distribution"]
        assert "RedWolves" in data["spice_stats"]
        assert "BlueLions" not in data["spice_stats"]

    def test_d7_run_battle_support(self, capsys):
        from run_battle import main as battle_main

        rc = battle_main([
            str(STATE_FILE), str(MODEL_FILE),
            "--seed", "42",
            "--alliance", "RedWolves",
        ])
        assert rc == 0
        out = capsys.readouterr().out

        # Check initial state and final results only show RedWolves
        lines = out.split("\n")

        # Find "Initial State:" section
        initial_lines = []
        in_initial = False
        for line in lines:
            if "Initial State:" in line:
                in_initial = True
                continue
            if in_initial:
                if line.strip() == "":
                    break
                initial_lines.append(line)

        # Only RedWolves should appear in initial state
        for line in initial_lines:
            assert "RedWolves" in line
            assert "BlueLions" not in line

        # Find "Final Results:" section
        final_lines = []
        in_final = False
        for line in lines:
            if "Final Results:" in line:
                in_final = True
                continue
            if in_final:
                if line.strip() == "":
                    break
                final_lines.append(line)

        for line in final_lines:
            assert "RedWolves" in line
