from __future__ import annotations


_BUILDING_THRESHOLDS = [
    (3_165_000, 4),
    (1_805_000, 3),
    (705_000, 2),
    (150_000, 1),
]


def calculate_building_count(spice_amount: int) -> int:
    for threshold, count in _BUILDING_THRESHOLDS:
        if spice_amount >= threshold:
            return count
    return 0


def calculate_theft_percentage(outcome_level: str, building_count: int) -> float:
    if outcome_level == "full_success":
        return building_count * 5.0 + 10.0
    elif outcome_level == "partial_success":
        return building_count * 5.0
    else:  # fail
        return 0.0


def assign_brackets(
    alliances: list, faction: str, current_spice: dict[str, int]
) -> dict[str, int]:
    faction_alliances = [a for a in alliances if a.faction == faction]
    sorted_alliances = sorted(
        faction_alliances, key=lambda a: current_spice[a.alliance_id], reverse=True
    )
    brackets = {}
    for rank_zero, alliance in enumerate(sorted_alliances):
        brackets[alliance.alliance_id] = rank_zero // 10 + 1
    return brackets


def calculate_final_rankings(
    alliances: list, current_spice: dict[str, int]
) -> dict[str, int]:
    sorted_alliances = sorted(
        alliances, key=lambda a: current_spice[a.alliance_id], reverse=True
    )
    rankings = {}
    for rank_zero, alliance in enumerate(sorted_alliances):
        rank = rank_zero + 1
        if rank == 1:
            tier = 1
        elif rank <= 3:
            tier = 2
        elif rank <= 10:
            tier = 3
        elif rank <= 20:
            tier = 4
        else:
            tier = 5
        rankings[alliance.alliance_id] = tier
    return rankings
