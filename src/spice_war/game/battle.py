from __future__ import annotations

from spice_war.game.mechanics import calculate_building_count, calculate_theft_percentage


def resolve_battle(
    attackers: list[str],
    primary_defender: str,
    outcome_level: str,
    damage_splits: dict[str, float],
    current_spice: dict[str, int],
) -> dict[str, int]:
    defender_spice = current_spice[primary_defender]
    building_count = calculate_building_count(defender_spice)
    theft_pct = calculate_theft_percentage(outcome_level, building_count)
    total_stolen = int(defender_spice * theft_pct / 100.0)

    transfers: dict[str, int] = {}
    distributed = 0
    sorted_attackers = sorted(attackers)
    for i, attacker_id in enumerate(sorted_attackers):
        if i == len(sorted_attackers) - 1:
            share = total_stolen - distributed
        else:
            share = int(total_stolen * damage_splits[attacker_id])
            distributed += share
        transfers[attacker_id] = share

    transfers[primary_defender] = -total_stolen
    return transfers
