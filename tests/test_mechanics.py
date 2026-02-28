import pytest

from spice_war.game.mechanics import (
    assign_brackets,
    calculate_building_count,
    calculate_final_rankings,
    calculate_theft_percentage,
)
from spice_war.utils.data_structures import Alliance


def _alliance(aid, faction="red", power=100, spice=0):
    return Alliance(
        alliance_id=aid,
        faction=faction,
        power=power,
        starting_spice=spice,
        daily_spice_rate=0,
    )


class TestBuildingCount:
    def test_below_first_threshold(self):
        assert calculate_building_count(0) == 0
        assert calculate_building_count(149_999) == 0

    def test_boundary_one_building(self):
        assert calculate_building_count(150_000) == 1
        assert calculate_building_count(704_999) == 1

    def test_boundary_two_buildings(self):
        assert calculate_building_count(705_000) == 2
        assert calculate_building_count(1_804_999) == 2

    def test_boundary_three_buildings(self):
        assert calculate_building_count(1_805_000) == 3
        assert calculate_building_count(3_164_999) == 3

    def test_boundary_four_buildings(self):
        assert calculate_building_count(3_165_000) == 4
        assert calculate_building_count(10_000_000) == 4


class TestTheftPercentage:
    def test_full_success(self):
        assert calculate_theft_percentage("full_success", 0) == 10.0
        assert calculate_theft_percentage("full_success", 1) == 15.0
        assert calculate_theft_percentage("full_success", 2) == 20.0
        assert calculate_theft_percentage("full_success", 3) == 25.0
        assert calculate_theft_percentage("full_success", 4) == 30.0

    def test_partial_success(self):
        assert calculate_theft_percentage("partial_success", 0) == 0.0
        assert calculate_theft_percentage("partial_success", 1) == 5.0
        assert calculate_theft_percentage("partial_success", 2) == 10.0
        assert calculate_theft_percentage("partial_success", 3) == 15.0
        assert calculate_theft_percentage("partial_success", 4) == 20.0

    def test_fail(self):
        for bc in range(5):
            assert calculate_theft_percentage("fail", bc) == 0.0


class TestAssignBrackets:
    def test_single_bracket(self):
        alliances = [_alliance(f"a{i}", "red") for i in range(5)]
        spice = {f"a{i}": (5 - i) * 100_000 for i in range(5)}
        brackets = assign_brackets(alliances, "red", spice)
        assert all(b == 1 for b in brackets.values())

    def test_multiple_brackets(self):
        alliances = [_alliance(f"a{i}", "red") for i in range(25)]
        spice = {f"a{i}": (25 - i) * 100_000 for i in range(25)}
        brackets = assign_brackets(alliances, "red", spice)
        # Top 10 by spice → bracket 1, next 10 → bracket 2, last 5 → bracket 3
        assert brackets["a0"] == 1  # highest spice
        assert brackets["a9"] == 1
        assert brackets["a10"] == 2
        assert brackets["a19"] == 2
        assert brackets["a20"] == 3

    def test_filters_by_faction(self):
        alliances = [
            _alliance("r1", "red"),
            _alliance("b1", "blue"),
            _alliance("r2", "red"),
        ]
        spice = {"r1": 300_000, "b1": 500_000, "r2": 200_000}
        brackets = assign_brackets(alliances, "red", spice)
        assert "b1" not in brackets
        assert brackets["r1"] == 1
        assert brackets["r2"] == 1


class TestFinalRankings:
    def test_basic_tiers(self):
        alliances = [_alliance(f"a{i}") for i in range(25)]
        spice = {f"a{i}": (25 - i) * 100_000 for i in range(25)}
        rankings = calculate_final_rankings(alliances, spice)
        assert rankings["a0"] == 1   # rank 1
        assert rankings["a1"] == 2   # rank 2
        assert rankings["a2"] == 2   # rank 3
        assert rankings["a3"] == 3   # rank 4
        assert rankings["a9"] == 3   # rank 10
        assert rankings["a10"] == 4  # rank 11
        assert rankings["a19"] == 4  # rank 20
        assert rankings["a20"] == 5  # rank 21
        assert rankings["a24"] == 5  # rank 25

    def test_cross_faction(self):
        alliances = [
            _alliance("r1", "red"),
            _alliance("b1", "blue"),
            _alliance("r2", "red"),
        ]
        spice = {"r1": 300_000, "b1": 500_000, "r2": 100_000}
        rankings = calculate_final_rankings(alliances, spice)
        assert rankings["b1"] == 1  # highest
        assert rankings["r1"] == 2
        assert rankings["r2"] == 2
