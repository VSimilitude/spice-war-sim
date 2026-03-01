from __future__ import annotations

from spice_war.utils.data_structures import Alliance, EventConfig


def generate_template(
    alliances: list[Alliance],
    schedule: list[EventConfig],
    top_n: int = 6,
) -> list[list[str]]:
    """Generate CSV rows for a model config template.

    Produces sections for scalars, default_targets, event_targets,
    and battle_outcome_matrix, with descriptive text and pre-populated
    alliance names sorted by power descending within each faction.
    """
    factions = _factions_from_alliances(alliances)
    by_faction = _alliances_by_faction(alliances)

    rows: list[list[str]] = []

    # --- Header ---
    rows.append(["Spice War Model Configuration Template"])
    rows.append([
        "Fill in the blank cells below. Rows with blank required fields are"
        " ignored on import. Description rows (like this one) are skipped"
        " automatically."
    ])
    rows.append([])

    # --- Scalars ---
    rows.append(["random_seed", "42"])
    rows.append(["targeting_strategy", "expected_value"])
    rows.append([])

    # --- default_targets ---
    rows.append([
        "default_targets: Override the default targeting for specific alliances."
        " Set type to 'target' (with a specific alliance_id as value) or"
        " 'strategy' (with 'expected_value' or 'highest_spice' as value)."
    ])
    rows.append(["alliance", "type", "value"])
    for faction in factions:
        for a in by_faction[faction][:top_n]:
            rows.append([a.alliance_id, "", ""])
    rows.append([])

    # --- event_targets ---
    rows.append([
        "event_targets: Override targeting for a specific event."
        " Set type to 'target' (with a specific alliance_id as value) or"
        " 'strategy' (with 'expected_value' or 'highest_spice' as value)."
    ])
    rows.append(["event", "alliance", "type", "value"])
    for i, event in enumerate(schedule, 1):
        attackers = by_faction.get(event.attacker_faction, [])[:top_n]
        for a in attackers:
            rows.append([str(i), a.alliance_id, "", ""])
    rows.append([])

    # --- battle_outcome_matrix ---
    rows.append([
        "battle_outcome_matrix: Full-success probabilities as integer"
        " percentages (0-100). Blank cells use heuristic values."
        " partial_success is derived automatically."
    ])
    rows.append([])

    # Unique days from schedule, ordered wednesday before saturday
    seen_days: set[str] = set()
    days: list[str] = []
    for event in schedule:
        if event.day not in seen_days:
            seen_days.add(event.day)
            days.append(event.day)
    _day_order = {"wednesday": 0, "saturday": 1}
    days.sort(key=lambda d: _day_order.get(d, 2))

    sorted_factions = sorted(factions)

    for day in days:
        for atk_faction in sorted_factions:
            for def_faction in sorted_factions:
                if atk_faction == def_faction:
                    continue
                attackers = by_faction.get(atk_faction, [])[:top_n]
                defenders = by_faction.get(def_faction, [])[:top_n]

                title = f"{day.capitalize()}: {atk_faction} \u2192 {def_faction}"
                rows.append([title])

                # Header row: blank first cell + defender IDs
                rows.append([""] + [d.alliance_id for d in defenders])

                # Data rows: attacker ID + heuristic percentages
                for atk in attackers:
                    row = [atk.alliance_id]
                    for def_ in defenders:
                        pct = round(
                            _heuristic_full(atk.power, def_.power, day) * 100
                        )
                        row.append(str(pct))
                    rows.append(row)

                rows.append([])  # blank separator between grids

    return rows


def _factions_from_alliances(alliances: list[Alliance]) -> list[str]:
    """Return faction names in order of first appearance."""
    seen: set[str] = set()
    result: list[str] = []
    for a in alliances:
        if a.faction not in seen:
            seen.add(a.faction)
            result.append(a.faction)
    return result


def _alliances_by_faction(
    alliances: list[Alliance],
) -> dict[str, list[Alliance]]:
    """Group alliances by faction, sorted by power descending."""
    groups: dict[str, list[Alliance]] = {}
    for a in alliances:
        groups.setdefault(a.faction, []).append(a)
    for faction in groups:
        groups[faction].sort(key=lambda a: a.power, reverse=True)
    return groups


def _heuristic_full(atk_power: float, def_power: float, day: str) -> float:
    """Compute heuristic full_success probability."""
    ratio = atk_power / def_power
    if day == "wednesday":
        return max(0.0, min(1.0, 2.5 * ratio - 2.0))
    else:
        return max(0.0, min(1.0, 3.25 * ratio - 3.0))
