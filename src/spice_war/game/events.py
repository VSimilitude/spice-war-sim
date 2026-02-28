from __future__ import annotations

from collections import defaultdict

from spice_war.game.battle import resolve_battle
from spice_war.game.mechanics import (
    assign_brackets,
    calculate_building_count,
    calculate_theft_percentage,
)
from spice_war.models.base import BattleModel
from spice_war.utils.data_structures import Alliance, GameState


def coordinate_battle(
    attackers: list[Alliance],
    defenders: list[Alliance],
    current_state: GameState,
    day: str,
    model: BattleModel,
) -> tuple[dict[str, int], dict]:
    primary_defender = defenders[0]

    outcome, probabilities = model.determine_battle_outcome(
        current_state, attackers, defenders, day
    )

    splits = model.determine_damage_splits(
        current_state, attackers, primary_defender
    )

    transfers = resolve_battle(
        attackers=[a.alliance_id for a in attackers],
        primary_defender=primary_defender.alliance_id,
        outcome_level=outcome,
        damage_splits=splits,
        current_spice=current_state.current_spice,
    )

    defender_spice = current_state.current_spice[primary_defender.alliance_id]
    building_count = calculate_building_count(defender_spice)
    theft_pct = calculate_theft_percentage(outcome, building_count)

    battle_info = {
        "attackers": [a.alliance_id for a in attackers],
        "defenders": [primary_defender.alliance_id],
        "reinforcements": [d.alliance_id for d in defenders[1:]],
        "outcome": outcome,
        "outcome_probabilities": probabilities,
        "defender_buildings": building_count,
        "theft_percentage": theft_pct,
        "damage_splits": splits,
        "transfers": transfers,
    }

    return transfers, battle_info


def coordinate_event(
    current_state: GameState,
    attacker_faction: str,
    day: str,
    event_number: int,
    model: BattleModel,
) -> tuple[dict[str, int], dict]:
    alliances = current_state.alliances
    factions = {a.faction for a in alliances}
    defender_faction = [f for f in factions if f != attacker_faction][0]

    attacker_brackets = assign_brackets(
        alliances, attacker_faction, current_state.current_spice
    )
    defender_brackets = assign_brackets(
        alliances, defender_faction, current_state.current_spice
    )

    all_brackets = {**attacker_brackets, **defender_brackets}
    current_state.brackets = all_brackets

    alliance_map = {a.alliance_id: a for a in alliances}
    bracket_numbers = sorted(set(attacker_brackets.values()))

    total_transfers: dict[str, int] = defaultdict(int)
    all_battles = []
    all_targeting = {}
    all_reinforcements = {}
    bracket_info = {}

    for bracket_num in bracket_numbers:
        bracket_attackers = [
            alliance_map[aid]
            for aid, b in attacker_brackets.items()
            if b == bracket_num
        ]
        bracket_defenders = [
            alliance_map[aid]
            for aid, b in defender_brackets.items()
            if b == bracket_num
        ]

        if not bracket_attackers or not bracket_defenders:
            continue

        targets = model.generate_targets(
            current_state, bracket_attackers, bracket_defenders, bracket_num
        )
        all_targeting.update(targets)

        reinforcements = model.generate_reinforcements(
            current_state, targets, bracket_defenders, bracket_num
        )
        all_reinforcements.update(reinforcements)

        bracket_info[str(bracket_num)] = {
            "attackers": [a.alliance_id for a in bracket_attackers],
            "defenders": [d.alliance_id for d in bracket_defenders],
        }

        # Group battles: attackers targeting same defender
        battles_by_defender: dict[str, list[str]] = defaultdict(list)
        for attacker_id, defender_id in targets.items():
            battles_by_defender[defender_id].append(attacker_id)

        for primary_defender_id, attacker_ids in battles_by_defender.items():
            battle_attackers = [alliance_map[aid] for aid in attacker_ids]
            battle_defenders = [alliance_map[primary_defender_id]]

            # Add reinforcements
            for reinf_id, target_id in reinforcements.items():
                if target_id == primary_defender_id:
                    battle_defenders.append(alliance_map[reinf_id])

            transfers, battle_info = coordinate_battle(
                battle_attackers, battle_defenders, current_state, day, model
            )

            for aid, amount in transfers.items():
                total_transfers[aid] += amount

            all_battles.append(battle_info)

    # Apply transfers
    updated_spice = dict(current_state.current_spice)
    for aid, amount in total_transfers.items():
        updated_spice[aid] += amount

    event_info = {
        "event_number": event_number,
        "attacker_faction": attacker_faction,
        "day": day,
        "brackets": bracket_info,
        "targeting": all_targeting,
        "reinforcements": all_reinforcements,
        "battles": all_battles,
    }

    return updated_spice, event_info
