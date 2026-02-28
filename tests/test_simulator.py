from spice_war.game.simulator import process_between_events, simulate_war
from spice_war.models.base import BattleModel
from spice_war.utils.data_structures import Alliance, EventConfig, GameState


def _alliance(aid, faction="red", power=100, spice=500_000, daily_rate=50_000):
    return Alliance(
        alliance_id=aid,
        faction=faction,
        power=power,
        starting_spice=spice,
        daily_spice_rate=daily_rate,
    )


class MockModel(BattleModel):
    def __init__(self, outcome="full_success"):
        self._outcome = outcome

    def generate_targets(self, state, bracket_attackers, bracket_defenders, bracket_number):
        targets = {}
        defenders = sorted(bracket_defenders, key=lambda d: state.current_spice[d.alliance_id], reverse=True)
        for i, a in enumerate(bracket_attackers):
            if i < len(defenders):
                targets[a.alliance_id] = defenders[i].alliance_id
        return targets

    def generate_reinforcements(self, state, targets, bracket_defenders, bracket_number):
        return {}

    def determine_battle_outcome(self, state, attackers, defenders, day):
        probs = {"full_success": 1.0, "partial_success": 0.0, "fail": 0.0}
        if self._outcome != "full_success":
            probs = {"full_success": 0.0, "partial_success": 0.0, "fail": 1.0}
        return self._outcome, probs

    def determine_damage_splits(self, state, attackers, primary_defender):
        n = len(attackers)
        return {a.alliance_id: 1.0 / n for a in attackers}


class TestPassiveIncome:
    def test_basic(self):
        spice = {"a1": 100_000, "a2": 200_000}
        rates = {"a1": 50_000, "a2": 30_000}
        result = process_between_events(spice, 3, rates)
        assert result["a1"] == 250_000
        assert result["a2"] == 290_000

    def test_zero_days(self):
        spice = {"a1": 100_000}
        rates = {"a1": 50_000}
        result = process_between_events(spice, 0, rates)
        assert result["a1"] == 100_000


class TestSimulateWar:
    def test_full_simulation(self):
        a1 = _alliance("a1", "red", power=200, spice=1_000_000, daily_rate=50_000)
        a2 = _alliance("a2", "blue", power=100, spice=1_000_000, daily_rate=50_000)
        schedule = [
            EventConfig(attacker_faction="red", day="wednesday", days_before=3),
            EventConfig(attacker_faction="blue", day="saturday", days_before=4),
        ]
        model = MockModel(outcome="full_success")
        result = simulate_war([a1, a2], schedule, model)

        assert "final_spice" in result
        assert "rankings" in result
        assert "event_history" in result
        assert len(result["event_history"]) == 2

        # Verify spice changed from starting values
        assert result["final_spice"]["a1"] != a1.starting_spice
        assert result["final_spice"]["a2"] != a2.starting_spice

    def test_reproducibility(self):
        """Same inputs + same seed → same results."""
        from spice_war.models.configurable import ConfigurableModel

        a1 = _alliance("a1", "red", power=150, spice=1_000_000)
        a2 = _alliance("a2", "blue", power=120, spice=800_000)
        schedule = [
            EventConfig(attacker_faction="red", day="wednesday", days_before=3),
            EventConfig(attacker_faction="blue", day="saturday", days_before=4),
        ]

        model1 = ConfigurableModel({"random_seed": 42}, [a1, a2])
        result1 = simulate_war([a1, a2], schedule, model1)

        model2 = ConfigurableModel({"random_seed": 42}, [a1, a2])
        result2 = simulate_war([a1, a2], schedule, model2)

        assert result1["final_spice"] == result2["final_spice"]
        assert result1["rankings"] == result2["rankings"]

    def test_event_history_records_spice(self):
        a1 = _alliance("a1", "red", power=200, spice=500_000)
        a2 = _alliance("a2", "blue", power=100, spice=500_000)
        schedule = [
            EventConfig(attacker_faction="red", day="wednesday", days_before=3),
        ]
        model = MockModel(outcome="full_success")
        result = simulate_war([a1, a2], schedule, model)
        event = result["event_history"][0]
        assert "spice_before" in event
        assert "spice_after" in event
        assert event["spice_before"]["a1"] == 500_000 + 3 * 50_000
