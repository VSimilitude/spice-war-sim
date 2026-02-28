from spice_war.game.events import coordinate_battle, coordinate_event
from spice_war.models.base import BattleModel
from spice_war.utils.data_structures import Alliance, GameState


def _alliance(aid, faction="red", power=100, spice=500_000):
    return Alliance(
        alliance_id=aid,
        faction=faction,
        power=power,
        starting_spice=spice,
        daily_spice_rate=50_000,
    )


class MockModel(BattleModel):
    def __init__(self, outcome="full_success", splits=None, targets=None, reinforcements=None):
        self._outcome = outcome
        self._splits = splits or {}
        self._targets = targets or {}
        self._reinforcements = reinforcements or {}

    def generate_targets(self, state, bracket_attackers, bracket_defenders, bracket_number):
        if self._targets:
            return self._targets
        targets = {}
        defenders = sorted(bracket_defenders, key=lambda d: state.current_spice[d.alliance_id], reverse=True)
        for i, a in enumerate(bracket_attackers):
            if i < len(defenders):
                targets[a.alliance_id] = defenders[i].alliance_id
        return targets

    def generate_reinforcements(self, state, targets, bracket_defenders, bracket_number):
        return self._reinforcements

    def determine_battle_outcome(self, state, attackers, defenders, day):
        probs = {"full_success": 0.8, "partial_success": 0.15, "fail": 0.05}
        return self._outcome, probs

    def determine_damage_splits(self, state, attackers, primary_defender):
        if self._splits:
            return self._splits
        n = len(attackers)
        return {a.alliance_id: 1.0 / n for a in attackers}


class TestCoordinateBattle:
    def test_single_battle(self):
        a1 = _alliance("a1")
        d1 = _alliance("d1", "blue", spice=2_000_000)
        state = GameState(
            current_spice={"a1": 500_000, "d1": 2_000_000},
            brackets={}, event_number=1, day="wednesday",
            event_history=[], alliances=[a1, d1],
        )
        model = MockModel(outcome="full_success")
        transfers, info = coordinate_battle([a1], [d1], state, "wednesday", model)
        # 2M spice, 3 buildings, full_success → 25% = 500k
        assert transfers["a1"] == 500_000
        assert transfers["d1"] == -500_000
        assert info["outcome"] == "full_success"


class TestCoordinateEvent:
    def test_2v2_event(self):
        a1 = _alliance("a1", "red", power=200, spice=500_000)
        a2 = _alliance("a2", "red", power=100, spice=400_000)
        d1 = _alliance("d1", "blue", power=150, spice=2_000_000)
        d2 = _alliance("d2", "blue", power=80, spice=1_000_000)
        alliances = [a1, a2, d1, d2]
        state = GameState(
            current_spice={"a1": 500_000, "a2": 400_000, "d1": 2_000_000, "d2": 1_000_000},
            brackets={}, event_number=1, day="wednesday",
            event_history=[], alliances=alliances,
        )
        model = MockModel(outcome="full_success")
        updated_spice, info = coordinate_event(state, "red", "wednesday", 1, model)

        # a1 (higher power) → d1 (higher spice, 2M, 3 bldgs → 25% = 500k)
        # a2 → d2 (1M, 2 bldgs → 20% = 200k)
        assert updated_spice["a1"] == 500_000 + 500_000
        assert updated_spice["d1"] == 2_000_000 - 500_000
        assert updated_spice["a2"] == 400_000 + 200_000
        assert updated_spice["d2"] == 1_000_000 - 200_000

    def test_event_with_reinforcements(self):
        a1 = _alliance("a1", "red", power=200, spice=500_000)
        a2 = _alliance("a2", "red", power=100, spice=400_000)
        d1 = _alliance("d1", "blue", power=150, spice=2_000_000)
        d2 = _alliance("d2", "blue", power=80, spice=1_000_000)
        alliances = [a1, a2, d1, d2]
        state = GameState(
            current_spice={"a1": 500_000, "a2": 400_000, "d1": 2_000_000, "d2": 1_000_000},
            brackets={}, event_number=1, day="wednesday",
            event_history=[], alliances=alliances,
        )
        # Both attackers target d1, d2 reinforces d1
        model = MockModel(
            outcome="full_success",
            targets={"a1": "d1", "a2": "d1"},
            reinforcements={"d2": "d1"},
            splits={"a1": 0.6, "a2": 0.4},
        )
        updated_spice, info = coordinate_event(state, "red", "wednesday", 1, model)

        # d1 has 2M, 3 buildings, full_success → 25% = 500k
        assert updated_spice["a1"] == 500_000 + 300_000   # 60% of 500k
        assert updated_spice["a2"] == 400_000 + 200_000   # 40% of 500k
        assert updated_spice["d1"] == 2_000_000 - 500_000
        assert updated_spice["d2"] == 1_000_000            # reinforcer loses nothing
        assert info["reinforcements"] == {"d2": "d1"}
