from __future__ import annotations

import random
from collections import Counter

from spice_war.models.base import BattleModel
from spice_war.utils.data_structures import Alliance, GameState


class ConfigurableModel(BattleModel):
    def __init__(self, config: dict, alliances: list[Alliance]):
        self.config = config
        self.alliances = {a.alliance_id: a for a in alliances}
        seed = config.get("random_seed", 0)
        self.rng = random.Random(seed)

    # ── M1: Targeting ──────────────────────────────────────────────

    def generate_targets(
        self,
        state: GameState,
        bracket_attackers: list[Alliance],
        bracket_defenders: list[Alliance],
        bracket_number: int,
    ) -> dict[str, str]:
        event_targets = self.config.get("event_targets", {})
        event_key = str(state.event_number)

        if event_key in event_targets:
            configured = event_targets[event_key]
            attacker_ids = {a.alliance_id for a in bracket_attackers}
            filtered = {k: v for k, v in configured.items() if k in attacker_ids}
            if filtered:
                return filtered

        return self._default_targets(bracket_attackers, bracket_defenders, state)

    def _default_targets(
        self,
        bracket_attackers: list[Alliance],
        bracket_defenders: list[Alliance],
        state: GameState,
    ) -> dict[str, str]:
        attackers = sorted(bracket_attackers, key=lambda a: a.power, reverse=True)
        defenders = sorted(
            bracket_defenders,
            key=lambda d: state.current_spice[d.alliance_id],
            reverse=True,
        )

        targets: dict[str, str] = {}
        assigned: set[str] = set()
        for attacker in attackers:
            for defender in defenders:
                if defender.alliance_id not in assigned:
                    targets[attacker.alliance_id] = defender.alliance_id
                    assigned.add(defender.alliance_id)
                    break

        return targets

    # ── M2: Reinforcements ─────────────────────────────────────────

    def generate_reinforcements(
        self,
        state: GameState,
        targets: dict[str, str],
        bracket_defenders: list[Alliance],
        bracket_number: int,
    ) -> dict[str, str]:
        event_reinforcements = self.config.get("event_reinforcements", {})
        event_key = str(state.event_number)

        if event_key in event_reinforcements:
            configured = event_reinforcements[event_key]
            defender_ids = {d.alliance_id for d in bracket_defenders}
            filtered = {k: v for k, v in configured.items() if k in defender_ids}
            if filtered:
                return filtered

        return self._default_reinforcements(targets, bracket_defenders, state)

    def _default_reinforcements(
        self,
        targets: dict[str, str],
        bracket_defenders: list[Alliance],
        state: GameState,
    ) -> dict[str, str]:
        targeted_set = set(targets.values())
        untargeted = [
            d for d in bracket_defenders if d.alliance_id not in targeted_set
        ]

        if not untargeted:
            return {}

        target_counts = Counter(targets.values())
        if not target_counts:
            return {}

        # Sort candidates by (attacker_count desc, spice desc) for tie-breaking
        candidates = sorted(
            target_counts.keys(),
            key=lambda did: (
                target_counts[did],
                state.current_spice.get(did, 0),
            ),
            reverse=True,
        )
        most_attacked = candidates[0]
        max_reinforcements = target_counts[most_attacked] - 1

        reinforcements: dict[str, str] = {}
        for d in untargeted[:max_reinforcements]:
            reinforcements[d.alliance_id] = most_attacked

        return reinforcements

    # ── M3: Battle Outcome ─────────────────────────────────────────

    def determine_battle_outcome(
        self,
        state: GameState,
        attackers: list[Alliance],
        defenders: list[Alliance],
        day: str,
    ) -> tuple[str, dict[str, float]]:
        primary_defender = defenders[0]
        matrix = self.config.get("battle_outcome_matrix", {})

        probs_list = []
        for attacker in attackers:
            probs = self._lookup_or_heuristic(
                matrix, attacker, primary_defender, day
            )
            probs_list.append(probs)

        if len(probs_list) == 1:
            combined = probs_list[0]
        else:
            combined = {
                "full_success": sum(p["full_success"] for p in probs_list)
                / len(probs_list),
                "partial_success": sum(p["partial_success"] for p in probs_list)
                / len(probs_list),
            }

        combined["fail"] = max(
            0.0, 1.0 - combined["full_success"] - combined["partial_success"]
        )

        roll = self.rng.random()
        if roll < combined["full_success"]:
            outcome = "full_success"
        elif roll < combined["full_success"] + combined["partial_success"]:
            outcome = "partial_success"
        else:
            outcome = "fail"

        return outcome, combined

    def _lookup_or_heuristic(
        self,
        matrix: dict,
        attacker: Alliance,
        defender: Alliance,
        day: str,
    ) -> dict[str, float]:
        day_matrix = matrix.get(day, {})
        attacker_entry = day_matrix.get(attacker.alliance_id, {})
        pairing = attacker_entry.get(defender.alliance_id)

        if pairing is not None:
            full = pairing["full_success"]
            if "partial_success" in pairing:
                partial = pairing["partial_success"]
            else:
                partial = (1.0 - full) * 0.4
            return {"full_success": full, "partial_success": partial}

        return self._heuristic_probabilities(attacker, defender, day)

    def _heuristic_probabilities(
        self, attacker: Alliance, defender: Alliance, day: str
    ) -> dict[str, float]:
        ratio = attacker.power / defender.power

        if day == "wednesday":
            full = max(0.0, min(1.0, 2.5 * ratio - 2.0))
            cumulative_partial = max(0.0, min(1.0, 1.75 * ratio - 0.9))
        else:  # saturday
            full = max(0.0, min(1.0, 3.25 * ratio - 3.0))
            cumulative_partial = max(0.0, min(1.0, 1.75 * ratio - 1.1))

        partial = max(0.0, cumulative_partial - full)
        return {"full_success": full, "partial_success": partial}

    # ── M4: Damage Splits ──────────────────────────────────────────

    def determine_damage_splits(
        self,
        state: GameState,
        attackers: list[Alliance],
        primary_defender: Alliance,
    ) -> dict[str, float]:
        if len(attackers) == 1:
            return {attackers[0].alliance_id: 1.0}

        damage_weights_config = self.config.get("damage_weights", {})
        all_have_weights = all(
            a.alliance_id in damage_weights_config for a in attackers
        )

        if all_have_weights:
            weights = {
                a.alliance_id: damage_weights_config[a.alliance_id]
                for a in attackers
            }
        else:
            weights = {}
            for a in attackers:
                ratio = a.power / primary_defender.power
                weights[a.alliance_id] = max(0.0, min(1.0, 1.5 * ratio - 1.0))

        total = sum(weights.values())
        if total == 0:
            equal = 1.0 / len(attackers)
            return {a.alliance_id: equal for a in attackers}

        return {aid: w / total for aid, w in weights.items()}
