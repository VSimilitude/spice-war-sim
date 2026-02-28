from spice_war.game.battle import resolve_battle


class TestResolveBattle:
    def test_single_attacker_full_success(self):
        # 2M spice → 3 buildings → full_success = 25%
        transfers = resolve_battle(
            attackers=["a1"],
            primary_defender="d1",
            outcome_level="full_success",
            damage_splits={"a1": 1.0},
            current_spice={"a1": 500_000, "d1": 2_000_000},
        )
        assert transfers["a1"] == 500_000  # 2M * 25%
        assert transfers["d1"] == -500_000

    def test_single_attacker_partial_success(self):
        # 2M spice → 3 buildings → partial_success = 15%
        transfers = resolve_battle(
            attackers=["a1"],
            primary_defender="d1",
            outcome_level="partial_success",
            damage_splits={"a1": 1.0},
            current_spice={"a1": 500_000, "d1": 2_000_000},
        )
        assert transfers["a1"] == 300_000  # 2M * 15%
        assert transfers["d1"] == -300_000

    def test_single_attacker_fail(self):
        transfers = resolve_battle(
            attackers=["a1"],
            primary_defender="d1",
            outcome_level="fail",
            damage_splits={"a1": 1.0},
            current_spice={"a1": 500_000, "d1": 2_000_000},
        )
        assert transfers["a1"] == 0
        assert transfers["d1"] == 0

    def test_multiple_attackers(self):
        # 2M spice → 3 buildings → full_success = 25% = 500k total
        transfers = resolve_battle(
            attackers=["a1", "a2"],
            primary_defender="d1",
            outcome_level="full_success",
            damage_splits={"a1": 0.6, "a2": 0.4},
            current_spice={"a1": 500_000, "a2": 400_000, "d1": 2_000_000},
        )
        assert transfers["a1"] == 300_000
        assert transfers["a2"] == 200_000
        assert transfers["d1"] == -500_000

    def test_transfers_sum_to_zero(self):
        transfers = resolve_battle(
            attackers=["a1", "a2", "a3"],
            primary_defender="d1",
            outcome_level="full_success",
            damage_splits={"a1": 0.5, "a2": 0.3, "a3": 0.2},
            current_spice={"a1": 0, "a2": 0, "a3": 0, "d1": 3_165_000},
        )
        assert sum(transfers.values()) == 0

    def test_zero_spice_defender(self):
        transfers = resolve_battle(
            attackers=["a1"],
            primary_defender="d1",
            outcome_level="full_success",
            damage_splits={"a1": 1.0},
            current_spice={"a1": 500_000, "d1": 0},
        )
        assert transfers["a1"] == 0
        assert transfers["d1"] == 0

    def test_low_spice_no_buildings(self):
        # 100k spice → 0 buildings → full_success = 10%
        transfers = resolve_battle(
            attackers=["a1"],
            primary_defender="d1",
            outcome_level="full_success",
            damage_splits={"a1": 1.0},
            current_spice={"a1": 0, "d1": 100_000},
        )
        assert transfers["a1"] == 10_000
        assert transfers["d1"] == -10_000
