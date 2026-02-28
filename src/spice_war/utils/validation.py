from __future__ import annotations

import json
from pathlib import Path

from spice_war.utils.data_structures import Alliance, EventConfig

_REQUIRED_ALLIANCE_KEYS = {"alliance_id", "faction", "power", "starting_spice", "daily_rate"}
_ALLOWED_ALLIANCE_KEYS = _REQUIRED_ALLIANCE_KEYS | {"name", "server"}

_REQUIRED_EVENT_KEYS = {"attacker_faction", "day", "days_before"}
_ALLOWED_EVENT_KEYS = _REQUIRED_EVENT_KEYS

_ALLOWED_STATE_KEYS = {"alliances", "event_schedule"}
_ALLOWED_MODEL_KEYS = {
    "random_seed",
    "battle_outcome_matrix",
    "event_targets",
    "event_reinforcements",
    "damage_weights",
}


class ValidationError(Exception):
    pass


def load_state(path: str | Path) -> tuple[list[Alliance], list[EventConfig]]:
    data = _load_json(path)

    unknown = set(data.keys()) - _ALLOWED_STATE_KEYS
    if unknown:
        raise ValidationError(f"Unknown keys in state file: {sorted(unknown)}")

    if "alliances" not in data:
        raise ValidationError("State file missing required key: 'alliances'")
    if "event_schedule" not in data:
        raise ValidationError("State file missing required key: 'event_schedule'")

    raw_alliances = data["alliances"]
    if not raw_alliances:
        raise ValidationError("State file 'alliances' must not be empty")

    alliances = []
    for i, raw in enumerate(raw_alliances):
        unknown_a = set(raw.keys()) - _ALLOWED_ALLIANCE_KEYS
        if unknown_a:
            raise ValidationError(
                f"Unknown keys in alliance #{i + 1}: {sorted(unknown_a)}"
            )
        missing = _REQUIRED_ALLIANCE_KEYS - set(raw.keys())
        if missing:
            raise ValidationError(
                f"Alliance #{i + 1} missing required fields: {sorted(missing)}"
            )
        alliances.append(
            Alliance(
                alliance_id=raw["alliance_id"],
                faction=raw["faction"],
                power=raw["power"],
                starting_spice=raw["starting_spice"],
                daily_spice_rate=raw["daily_rate"],
                name=raw.get("name"),
                server=raw.get("server"),
            )
        )

    raw_schedule = data["event_schedule"]
    if not raw_schedule:
        raise ValidationError("Event schedule must not be empty")

    schedule = []
    for i, raw in enumerate(raw_schedule):
        unknown_e = set(raw.keys()) - _ALLOWED_EVENT_KEYS
        if unknown_e:
            raise ValidationError(
                f"Unknown keys in event #{i + 1}: {sorted(unknown_e)}"
            )
        missing = _REQUIRED_EVENT_KEYS - set(raw.keys())
        if missing:
            raise ValidationError(
                f"Event #{i + 1} missing required fields: {sorted(missing)}"
            )
        schedule.append(
            EventConfig(
                attacker_faction=raw["attacker_faction"],
                day=raw["day"],
                days_before=raw["days_before"],
            )
        )

    # Both factions present
    schedule_factions = {e.attacker_faction for e in schedule}
    alliance_factions = {a.faction for a in alliances}
    for faction in schedule_factions:
        if faction not in alliance_factions:
            raise ValidationError(
                f"Event schedule references faction '{faction}' but no alliances belong to it"
            )
    # Need at least 2 factions
    if len(alliance_factions & schedule_factions) < 2:
        # Check that defenders also exist
        all_factions_in_schedule = set()
        for a in alliances:
            all_factions_in_schedule.add(a.faction)
        if len(all_factions_in_schedule) < 2:
            raise ValidationError(
                "State file must contain alliances from at least two factions"
            )

    return alliances, schedule


def load_model_config(
    path: str | Path | None,
    alliance_ids: set[str],
) -> dict:
    if path is None:
        return {}

    data = _load_json(path)

    unknown = set(data.keys()) - _ALLOWED_MODEL_KEYS
    if unknown:
        raise ValidationError(f"Unknown keys in model file: {sorted(unknown)}")

    # Cross-reference alliance IDs
    _check_model_references(data, alliance_ids)

    return data


def _check_model_references(data: dict, alliance_ids: set[str]) -> None:
    errors = []

    # Check battle_outcome_matrix
    matrix = data.get("battle_outcome_matrix", {})
    for day, attackers in matrix.items():
        for attacker_id, defenders in attackers.items():
            if attacker_id not in alliance_ids:
                errors.append(
                    f"battle_outcome_matrix references unknown alliance '{attacker_id}'"
                )
            for defender_id in defenders:
                if defender_id not in alliance_ids:
                    errors.append(
                        f"battle_outcome_matrix references unknown alliance '{defender_id}'"
                    )

    # Check event_targets
    for event_num, targets in data.get("event_targets", {}).items():
        for attacker_id, defender_id in targets.items():
            if attacker_id not in alliance_ids:
                errors.append(
                    f"event_targets references unknown alliance '{attacker_id}'"
                )
            if defender_id not in alliance_ids:
                errors.append(
                    f"event_targets references unknown alliance '{defender_id}'"
                )

    # Check event_reinforcements
    for event_num, reinfs in data.get("event_reinforcements", {}).items():
        for src_id, dest_id in reinfs.items():
            if src_id not in alliance_ids:
                errors.append(
                    f"event_reinforcements references unknown alliance '{src_id}'"
                )
            if dest_id not in alliance_ids:
                errors.append(
                    f"event_reinforcements references unknown alliance '{dest_id}'"
                )

    # Check damage_weights
    for aid in data.get("damage_weights", {}):
        if aid not in alliance_ids:
            errors.append(
                f"damage_weights references unknown alliance '{aid}'"
            )

    if errors:
        raise ValidationError("\n".join(errors))


def _load_json(path: str | Path) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise ValidationError(f"File not found: {path}")
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid JSON in {path}: {e}")
