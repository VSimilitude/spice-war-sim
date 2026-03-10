import copy

import pytest

from spice_war.game.simulator import simulate_war
from spice_war.models.configurable import ConfigurableModel
from spice_war.utils.data_structures import Alliance, EventConfig, GameState
from spice_war.utils.validation import ValidationError, load_model_config


def _alliance(aid, faction="red", power=15e9, spice=500_000, rate=50_000):
    return Alliance(
        alliance_id=aid,
        faction=faction,
        power=power,
        starting_spice=spice,
        daily_spice_rate=rate,
    )


def _state(alliances, event_number=1, day="wednesday", spice_overrides=None,
           event_schedule=None):
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
        event_schedule=event_schedule,
    )


# ── rank_aware Strategy Tests (1–10) ─────────────────────────────


class TestRankAware:
    def test_01_prefers_tier_improving_target_over_higher_esv(self):
        """Attacker near tier boundary picks target whose double-shift
        crosses the boundary, over a higher-ESV target that doesn't."""
        # ATK at rank 4 (tier 3) with 2M. DEF_B at rank 3 (tier 2) with 2.5M.
        # Attacking DEF_B: ESV ~306K, double-shift → ATK=2.306M > DEF_B=2.194M
        #   → ATK moves to rank 3 (tier 2). Score = 1001.
        # Attacking DEF_A: ESV ~360K (higher!), but DEF_B still at 2.5M
        #   → ATK=2.360M < 2.5M → ATK stays rank 4 (tier 3). Score = 0.
        above1 = _alliance("TOP1", "red", power=20e9, spice=5_000_000)
        above2 = _alliance("TOP2", "blue", power=20e9, spice=4_000_000)
        def_b = _alliance("DEF_B", "blue", power=15e9, spice=2_500_000)
        attacker = _alliance("ATK", "red", power=15e9, spice=2_000_000)
        def_a = _alliance("DEF_A", "blue", power=10e9, spice=1_800_000)
        alliances = [above1, above2, def_b, attacker, def_a]

        config = {"targeting_strategy": "rank_aware"}
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)

        esv_a = model._calculate_esv(attacker, def_a, state)
        esv_b = model._calculate_esv(attacker, def_b, state)
        assert esv_a > esv_b, "DEF_A should have higher ESV"

        targets = model.generate_targets(state, [attacker], [def_a, def_b], 1)
        assert targets["ATK"] == "DEF_B"

    def test_02_prefers_rank_improving_when_tier_equal(self):
        # Two defenders — attacking either keeps same tier but one gives better rank
        a = _alliance("A", "red", power=15e9, spice=2_000_000)
        # D1 is ranked just above A → attacking gives rank improvement
        d1 = _alliance("D1", "blue", power=15e9, spice=2_050_000)
        # D2 is ranked far below → attacking gives no rank improvement
        d2 = _alliance("D2", "blue", power=15e9, spice=500_000)
        # Filler to keep both in same tier
        top = _alliance("TOP", "red", power=20e9, spice=5_000_000)
        alliances = [top, d1, a, d2]

        config = {"targeting_strategy": "rank_aware"}
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)
        targets = model.generate_targets(state, [a], [d1, d2], 1)
        assert targets["A"] == "D1"

    def test_03_falls_back_to_esv_when_no_rank_improvement(self):
        # Attacker at rank 40+ (tier 5) — no target can change tier/rank
        filler = []
        for i in range(38):
            filler.append(_alliance(
                f"F{i:02d}", "red" if i % 2 == 0 else "blue",
                power=20e9, spice=5_000_000 - i * 50_000,
            ))
        a = _alliance("A", "red", power=5e9, spice=100_000)
        # D1 weaker, less spice → higher ESV due to better ratio
        d1 = _alliance("D1", "blue", power=3e9, spice=200_000)
        # D2 stronger, more spice → lower ESV
        d2 = _alliance("D2", "blue", power=20e9, spice=400_000)
        alliances = filler + [a, d1, d2]

        config = {"targeting_strategy": "rank_aware"}
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)

        esv_d1 = model._calculate_esv(a, d1, state)
        esv_d2 = model._calculate_esv(a, d2, state)
        assert esv_d1 > esv_d2

        targets = model.generate_targets(state, [a], [d1, d2], 1)
        assert targets["A"] == "D1"

    def test_04_close_competitor_preferred(self):
        """Defender just above attacker in ranking is preferred over a
        higher-ESV defender far away, because double-shift crosses tier boundary."""
        # Same structure as test_01: A at rank 4, D_CLOSE at rank 3.
        # Double-shift from attacking D_CLOSE crosses the tier 2/3 boundary.
        # D_FAR has higher ESV but can't push A past D_CLOSE.
        top1 = _alliance("TOP1", "red", power=20e9, spice=5_000_000)
        top2 = _alliance("TOP2", "blue", power=20e9, spice=4_000_000)
        d_close = _alliance("D_CLOSE", "blue", power=15e9, spice=2_500_000)
        a = _alliance("A", "red", power=15e9, spice=2_000_000)
        d_far = _alliance("D_FAR", "blue", power=10e9, spice=1_800_000)
        alliances = [top1, top2, d_close, a, d_far]

        config = {"targeting_strategy": "rank_aware"}
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)
        targets = model.generate_targets(state, [a], [d_close, d_far], 1)
        assert targets["A"] == "D_CLOSE"

    def test_05_projected_standings_account_for_gain_and_loss(self):
        # Verify the attacker gains and defender loses in projected standings
        a = _alliance("A", "red", power=15e9, spice=2_000_000)
        d = _alliance("D", "blue", power=15e9, spice=2_100_000)
        alliances = [d, a]

        model = ConfigurableModel({}, alliances)
        state = _state(alliances)

        esv = model._calculate_esv(a, d, state)
        transfer = round(esv)
        assert transfer > 0

        # Before: D > A. After: A gains, D loses.
        projected_a = state.current_spice["A"] + transfer
        projected_d = state.current_spice["D"] - transfer
        assert projected_a > state.current_spice["A"]
        assert projected_d < state.current_spice["D"]

    def test_06_rankings_are_global(self):
        # Rank computation includes all alliances from both factions
        a = _alliance("A", "red", power=15e9, spice=1_000_000)
        d = _alliance("D", "blue", power=15e9, spice=1_100_000)
        other_red = _alliance("R2", "red", power=20e9, spice=3_000_000)
        other_blue = _alliance("B2", "blue", power=20e9, spice=2_500_000)
        alliances = [other_red, other_blue, d, a]

        rank, tier = ConfigurableModel._rank_and_tier("A", {
            a.alliance_id: a.starting_spice
            for a in alliances
        })
        # A has 1M (lowest) → rank 4 among 4 alliances
        assert rank == 4

    def test_07_tiebreaking_by_esv_then_spice_then_id(self):
        # Set up alliances so that two defenders give the same rank-aware score
        a = _alliance("A", "red", power=15e9, spice=100_000)
        # Both far away in ranking, same score (0)
        d1 = _alliance("D1", "blue", power=15e9, spice=200_000)
        d2 = _alliance("D2", "blue", power=15e9, spice=200_000)
        alliances = [a, d1, d2]

        config = {"targeting_strategy": "rank_aware"}
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)
        targets = model.generate_targets(state, [a], [d1, d2], 1)
        # Equal score, equal ESV (same power/spice), equal spice → alphabetical: D1
        assert targets["A"] == "D1"

    def test_08_respects_targeting_temperature(self):
        a = _alliance("A", "red", power=15e9, spice=2_000_000)
        d1 = _alliance("D1", "blue", power=15e9, spice=2_100_000)
        d2 = _alliance("D2", "blue", power=10e9, spice=500_000)
        alliances = [a, d1, d2]

        config = {
            "targeting_strategy": "rank_aware",
            "targeting_temperature": 0.5,
            "random_seed": 42,
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)
        # With temperature, should still produce a valid target
        targets = model.generate_targets(state, [a], [d1, d2], 1)
        assert targets["A"] in ("D1", "D2")

    def test_09_works_in_4_level_resolution(self):
        a1 = _alliance("A1", "red", power=15e9, spice=2_000_000)
        a2 = _alliance("A2", "red", power=12e9, spice=1_500_000)
        d1 = _alliance("D1", "blue", power=15e9, spice=2_100_000)
        d2 = _alliance("D2", "blue", power=10e9, spice=500_000)
        alliances = [a1, a2, d1, d2]

        # rank_aware via faction_targeting_strategy
        config = {
            "faction_targeting_strategy": {"red": "rank_aware"},
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)
        targets = model.generate_targets(state, [a1, a2], [d1, d2], 1)
        assert len(targets) == 2

        # rank_aware via default_targets strategy
        config2 = {
            "default_targets": {"A1": {"strategy": "rank_aware"}},
        }
        model2 = ConfigurableModel(config2, alliances)
        targets2 = model2.generate_targets(state, [a1, a2], [d1, d2], 1)
        assert len(targets2) == 2

    def test_10_single_defender_in_bracket(self):
        a = _alliance("A", "red", power=15e9, spice=2_000_000)
        d = _alliance("D", "blue", power=15e9, spice=100_000)
        alliances = [a, d]

        config = {"targeting_strategy": "rank_aware"}
        model = ConfigurableModel(config, alliances)
        state = _state(alliances)
        targets = model.generate_targets(state, [a], [d], 1)
        assert targets["A"] == "D"


# ── maximize_tier Strategy Tests (11–22) ──────────────────────────


def _make_war_scenario():
    """Small 6-alliance scenario with 2 events remaining."""
    alliances = [
        _alliance("A1", "red", power=18e9, spice=3_000_000, rate=100_000),
        _alliance("A2", "red", power=15e9, spice=2_500_000, rate=100_000),
        _alliance("A3", "red", power=12e9, spice=2_000_000, rate=100_000),
        _alliance("D1", "blue", power=17e9, spice=2_800_000, rate=100_000),
        _alliance("D2", "blue", power=14e9, spice=2_200_000, rate=100_000),
        _alliance("D3", "blue", power=10e9, spice=1_500_000, rate=100_000),
    ]
    schedule = [
        EventConfig("red", "wednesday", 3),
        EventConfig("blue", "saturday", 3),
    ]
    return alliances, schedule


class TestMaximizeTier:
    def test_11_picks_target_that_improves_final_tier(self):
        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 3,
            "tier_optimization_fallback": "rank_aware",
            "random_seed": 42,
        }
        model = ConfigurableModel(config, alliances)
        attackers = [a for a in alliances if a.faction == "red"]
        defenders = [a for a in alliances if a.faction == "blue"]
        state = _state(alliances, event_schedule=schedule)
        targets = model.generate_targets(state, attackers, defenders, 1)
        assert len(targets) == 3
        assert set(targets.values()) <= {"D1", "D2", "D3"}

    def test_12_top_n_within_faction(self):
        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 2,
            "tier_optimization_fallback": "expected_value",
            "random_seed": 0,
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, event_schedule=schedule)
        top_n = model._get_top_n_ids(state, "red")
        # A1 (3M) and A2 (2.5M) are top 2 in red faction
        assert top_n == {"A1", "A2"}

    def test_13_top_n_attackers_resolve_first(self):
        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 1,
            "tier_optimization_fallback": "expected_value",
            "random_seed": 0,
        }
        model = ConfigurableModel(config, alliances)
        attackers = [a for a in alliances if a.faction == "red"]
        defenders = [a for a in alliances if a.faction == "blue"]
        state = _state(alliances, event_schedule=schedule)
        targets = model.generate_targets(state, attackers, defenders, 1)
        # A1 is top-1 and picks first via forward sim
        assert "A1" in targets
        assert len(targets) == 3

    def test_14_forward_sim_deterministic(self):
        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 3,
            "random_seed": 0,
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, event_schedule=schedule)
        result1 = model._forward_sim_tier("A1", "D1", state)
        result2 = model._forward_sim_tier("A1", "D1", state)
        assert result1 == result2

    def test_15_forward_sim_doesnt_mutate_state(self):
        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 3,
            "random_seed": 42,
        }
        model = ConfigurableModel(config, alliances)
        attackers = [a for a in alliances if a.faction == "red"]
        defenders = [a for a in alliances if a.faction == "blue"]
        state = _state(alliances, event_schedule=schedule)
        spice_before = dict(state.current_spice)
        model.generate_targets(state, attackers, defenders, 1)
        assert state.current_spice == spice_before

    def test_16_rng_isolation(self):
        alliances, schedule = _make_war_scenario()
        # Run with maximize_tier
        config_mt = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 2,
            "random_seed": 42,
        }
        model_mt = ConfigurableModel(config_mt, alliances)
        model_mt.set_effective_powers()
        attackers = [a for a in alliances if a.faction == "red"]
        defenders = [a for a in alliances if a.faction == "blue"]
        state = _state(alliances, event_schedule=schedule)
        model_mt.generate_targets(state, attackers, defenders, 1)
        # Capture RNG state after maximize_tier targeting
        roll_mt = model_mt.rng.random()

        # Run with rank_aware (no forward sims)
        config_ra = {
            "targeting_strategy": "rank_aware",
            "random_seed": 42,
        }
        model_ra = ConfigurableModel(config_ra, alliances)
        model_ra.set_effective_powers()
        model_ra.generate_targets(state, attackers, defenders, 1)
        roll_ra = model_ra.rng.random()

        # Both should produce the same next RNG value since forward sims
        # use separate RNG
        assert roll_mt == roll_ra

    def test_17_fewer_than_n_in_faction(self):
        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 10,  # More than 3 red alliances
            "random_seed": 0,
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, event_schedule=schedule)
        top_n = model._get_top_n_ids(state, "red")
        # All 3 red alliances should be top-N
        assert top_n == {"A1", "A2", "A3"}

    def test_18_tiebreaking_by_rank_then_esv_then_id(self):
        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 3,
            "random_seed": 0,
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, event_schedule=schedule)
        # Just verify it runs without error and produces valid targets
        attackers = [a for a in alliances if a.faction == "red"]
        defenders = [a for a in alliances if a.faction == "blue"]
        targets = model.generate_targets(state, attackers, defenders, 1)
        assert set(targets.keys()) == {"A1", "A2", "A3"}
        assert set(targets.values()) <= {"D1", "D2", "D3"}

    def test_19_top_n_config(self):
        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 1,
            "random_seed": 0,
        }
        model = ConfigurableModel(config, alliances)
        state = _state(alliances, event_schedule=schedule)
        top_n = model._get_top_n_ids(state, "red")
        assert len(top_n) == 1
        assert "A1" in top_n  # Highest spice in red

    def test_20_fallback_config(self):
        alliances, schedule = _make_war_scenario()
        # Use highest_spice as fallback, only top-1 uses forward sim
        config_hs = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 1,
            "tier_optimization_fallback": "highest_spice",
            "random_seed": 0,
        }
        model_hs = ConfigurableModel(config_hs, alliances)
        attackers = [a for a in alliances if a.faction == "red"]
        defenders = [a for a in alliances if a.faction == "blue"]
        state = _state(alliances, event_schedule=schedule)
        targets_hs = model_hs.generate_targets(state, attackers, defenders, 1)

        # Use expected_value as fallback
        config_ev = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 1,
            "tier_optimization_fallback": "expected_value",
            "random_seed": 0,
        }
        model_ev = ConfigurableModel(config_ev, alliances)
        targets_ev = model_ev.generate_targets(state, attackers, defenders, 1)

        # Both should produce valid assignments
        assert set(targets_hs.keys()) == {"A1", "A2", "A3"}
        assert set(targets_ev.keys()) == {"A1", "A2", "A3"}

    def test_21_works_with_outer_mc_loop(self):
        from spice_war.game.monte_carlo import run_monte_carlo

        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 2,
            "tier_optimization_fallback": "rank_aware",
        }
        result = run_monte_carlo(
            alliances, schedule, config,
            num_iterations=5, base_seed=0,
        )
        assert result.num_iterations == 5
        # All alliances should have tier counts
        for a in alliances:
            assert a.alliance_id in result.tier_counts

    def test_22_all_top_n_pinned(self):
        alliances, schedule = _make_war_scenario()
        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 2,
            "tier_optimization_fallback": "expected_value",
            "random_seed": 0,
            # Pin the top 2 (A1, A2)
            "default_targets": {
                "A1": {"target": "D1"},
                "A2": {"target": "D2"},
            },
        }
        model = ConfigurableModel(config, alliances)
        attackers = [a for a in alliances if a.faction == "red"]
        defenders = [a for a in alliances if a.faction == "blue"]
        state = _state(alliances, event_schedule=schedule)
        targets = model.generate_targets(state, attackers, defenders, 1)
        assert targets["A1"] == "D1"
        assert targets["A2"] == "D2"
        assert targets["A3"] == "D3"


# ── Configuration & Validation Tests (23–27) ──────────────────────


class TestTierTargetingValidation:
    def test_23_rank_aware_accepted_everywhere(self, tmp_path):
        import json

        # targeting_strategy
        config = {"targeting_strategy": "rank_aware"}
        path = tmp_path / "m1.json"
        path.write_text(json.dumps(config))
        result = load_model_config(path, {"A", "D"})
        assert result["targeting_strategy"] == "rank_aware"

        # default_targets strategy
        config2 = {"default_targets": {"A": {"strategy": "rank_aware"}}}
        path2 = tmp_path / "m2.json"
        path2.write_text(json.dumps(config2))
        result2 = load_model_config(path2, {"A", "D"})
        assert result2["default_targets"]["A"]["strategy"] == "rank_aware"

        # event_targets strategy
        config3 = {"event_targets": {"1": {"A": {"strategy": "rank_aware"}}}}
        path3 = tmp_path / "m3.json"
        path3.write_text(json.dumps(config3))
        result3 = load_model_config(path3, {"A", "D"})
        assert result3["event_targets"]["1"]["A"]["strategy"] == "rank_aware"

        # faction_targeting_strategy
        alliances = [_alliance("A", "red"), _alliance("D", "blue")]
        config4 = {"faction_targeting_strategy": {"red": "rank_aware"}}
        path4 = tmp_path / "m4.json"
        path4.write_text(json.dumps(config4))
        result4 = load_model_config(path4, {"A", "D"}, alliances=alliances)
        assert result4["faction_targeting_strategy"]["red"] == "rank_aware"

    def test_24_maximize_tier_accepted_everywhere(self, tmp_path):
        import json

        config = {
            "targeting_strategy": "maximize_tier",
            "tier_optimization_top_n": 5,
        }
        path = tmp_path / "m1.json"
        path.write_text(json.dumps(config))
        result = load_model_config(path, {"A", "D"})
        assert result["targeting_strategy"] == "maximize_tier"

        # default_targets strategy
        config2 = {"default_targets": {"A": {"strategy": "maximize_tier"}}}
        path2 = tmp_path / "m2.json"
        path2.write_text(json.dumps(config2))
        result2 = load_model_config(path2, {"A", "D"})
        assert result2["default_targets"]["A"]["strategy"] == "maximize_tier"

        # event_targets strategy
        config3 = {"event_targets": {"1": {"A": {"strategy": "maximize_tier"}}}}
        path3 = tmp_path / "m3.json"
        path3.write_text(json.dumps(config3))
        result3 = load_model_config(path3, {"A", "D"})
        assert result3["event_targets"]["1"]["A"]["strategy"] == "maximize_tier"

        # faction_targeting_strategy
        alliances = [_alliance("A", "red"), _alliance("D", "blue")]
        config4 = {"faction_targeting_strategy": {"red": "maximize_tier"}}
        path4 = tmp_path / "m4.json"
        path4.write_text(json.dumps(config4))
        result4 = load_model_config(path4, {"A", "D"}, alliances=alliances)
        assert result4["faction_targeting_strategy"]["red"] == "maximize_tier"

    def test_25_invalid_top_n(self, tmp_path):
        import json

        for bad_val in [0, -1, "five", True]:
            config = {
                "targeting_strategy": "maximize_tier",
                "tier_optimization_top_n": bad_val,
            }
            path = tmp_path / "bad.json"
            path.write_text(json.dumps(config))
            with pytest.raises(ValidationError, match="tier_optimization_top_n"):
                load_model_config(path, {"A", "D"})

    def test_26_invalid_fallback(self, tmp_path):
        import json

        for bad_val in ["maximize_tier", "invalid", ""]:
            config = {
                "targeting_strategy": "maximize_tier",
                "tier_optimization_fallback": bad_val,
            }
            path = tmp_path / "bad.json"
            path.write_text(json.dumps(config))
            with pytest.raises(ValidationError, match="tier_optimization_fallback"):
                load_model_config(path, {"A", "D"})

    def test_27_maximize_tier_fields_rejected_for_other_strategies(self, tmp_path):
        import json

        config = {
            "targeting_strategy": "expected_value",
            "tier_optimization_top_n": 5,
        }
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(config))
        with pytest.raises(ValidationError, match="only valid when"):
            load_model_config(path, {"A", "D"})


# ── Backward Compatibility Tests (28–29) ──────────────────────────


class TestBackwardCompatibility:
    def test_28_default_behavior_unchanged(self):
        a = _alliance("A", power=12e9)
        dx = _alliance("X", "blue", power=18e9, spice=3_000_000)
        dy = _alliance("Y", "blue", power=10e9, spice=2_000_000)
        alliances = [a, dx, dy]

        # No config → expected_value
        model = ConfigurableModel({}, alliances)
        state = _state(alliances)
        targets = model.generate_targets(state, [a], [dx, dy], 1)
        # Same as test_01 in test_expected_value_targeting.py
        assert targets["A"] == "Y"

    def test_29_existing_strategies_unaffected(self):
        a1 = _alliance("A1", power=20e9)
        a2 = _alliance("A2", power=15e9)
        d1 = _alliance("D1", "blue", power=15e9, spice=3_000_000)
        d2 = _alliance("D2", "blue", power=15e9, spice=2_000_000)
        alliances = [a1, a2, d1, d2]

        # expected_value
        model_ev = ConfigurableModel(
            {"targeting_strategy": "expected_value"}, alliances
        )
        state = _state(alliances)
        targets_ev = model_ev.generate_targets(state, [a1, a2], [d1, d2], 1)

        # highest_spice
        model_hs = ConfigurableModel(
            {"targeting_strategy": "highest_spice"}, alliances
        )
        targets_hs = model_hs.generate_targets(state, [a1, a2], [d1, d2], 1)

        # Both should produce valid, distinct assignments
        assert set(targets_ev.values()) == {"D1", "D2"}
        assert set(targets_hs.values()) == {"D1", "D2"}
        # highest_spice: A1 picks first → D1 (3M)
        assert targets_hs["A1"] == "D1"
