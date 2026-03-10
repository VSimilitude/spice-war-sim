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
    "targeting_strategy",
    "default_targets",
    "faction_targeting_strategy",
    "targeting_temperature",
    "power_noise",
    "outcome_noise",
    "tier_optimization_top_n",
    "tier_optimization_fallback",
}

_VALID_STRATEGIES = {"expected_value", "highest_spice", "rank_aware", "maximize_tier"}

_VALID_FALLBACK_STRATEGIES = {"expected_value", "highest_spice", "rank_aware"}


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
        if raw["alliance_id"] == "*":
            raise ValidationError(
                f"Alliance #{i + 1}: '*' is reserved and cannot be used as "
                f"an alliance_id"
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
    alliances: list[Alliance] | None = None,
) -> dict:
    if path is None:
        return {}

    data = _load_json(path)

    unknown = set(data.keys()) - _ALLOWED_MODEL_KEYS
    if unknown:
        raise ValidationError(f"Unknown keys in model file: {sorted(unknown)}")

    # Derive faction IDs if alliances provided
    faction_ids = {a.faction for a in alliances} if alliances else None

    # Cross-reference alliance IDs
    _check_model_references(data, alliance_ids, faction_ids)

    return data


_ALLOWED_PAIRING_KEYS = {
    "full_success", "partial_success", "custom", "custom_theft_percentage",
}


def _check_model_references(
    data: dict,
    alliance_ids: set[str],
    faction_ids: set[str] | None = None,
) -> None:
    errors = []

    # Check battle_outcome_matrix
    matrix = data.get("battle_outcome_matrix", {})
    for day, attackers in matrix.items():
        for attacker_id, defenders in attackers.items():
            if attacker_id != "*" and attacker_id not in alliance_ids:
                errors.append(
                    f"battle_outcome_matrix references unknown alliance '{attacker_id}'"
                )
            for defender_id, pairing in defenders.items():
                if defender_id != "*" and defender_id not in alliance_ids:
                    errors.append(
                        f"battle_outcome_matrix references unknown alliance '{defender_id}'"
                    )

                unknown_keys = set(pairing.keys()) - _ALLOWED_PAIRING_KEYS
                if unknown_keys:
                    errors.append(
                        f"battle_outcome_matrix[{day}][{attacker_id}][{defender_id}] "
                        f"has unknown keys: {sorted(unknown_keys)}"
                    )

                custom_prob = pairing.get("custom")
                custom_theft = pairing.get("custom_theft_percentage")

                if custom_prob is not None and custom_theft is None:
                    errors.append(
                        f"battle_outcome_matrix[{day}][{attacker_id}][{defender_id}] "
                        f"has 'custom' but missing 'custom_theft_percentage'"
                    )

                if custom_theft is not None:
                    if not (0 <= custom_theft <= 100):
                        errors.append(
                            f"battle_outcome_matrix[{day}][{attacker_id}][{defender_id}] "
                            f"'custom_theft_percentage' must be between 0 and 100, "
                            f"got {custom_theft}"
                        )

                total = (
                    pairing.get("full_success", 0)
                    + pairing.get("partial_success", 0)
                    + pairing.get("custom", 0)
                )
                if total > 1.0 + 1e-9:
                    errors.append(
                        f"battle_outcome_matrix[{day}][{attacker_id}][{defender_id}] "
                        f"probabilities sum to {total}, exceeding 1.0"
                    )

    # Check targeting_strategy
    strategy = data.get("targeting_strategy")
    if strategy is not None and strategy not in _VALID_STRATEGIES:
        errors.append(
            f"targeting_strategy must be one of {sorted(_VALID_STRATEGIES)}, "
            f"got '{strategy}'"
        )

    # Check default_targets
    for alliance_id, override in data.get("default_targets", {}).items():
        if alliance_id not in alliance_ids:
            errors.append(
                f"default_targets references unknown alliance '{alliance_id}'"
            )
        if not isinstance(override, dict):
            errors.append(
                f"default_targets[{alliance_id}] must be a dict, "
                f"got {type(override).__name__}"
            )
            continue
        if "target" in override:
            if len(override) != 1:
                errors.append(
                    f"default_targets[{alliance_id}] has 'target' with extra keys: "
                    f"{sorted(set(override.keys()) - {'target'})}"
                )
            if override["target"] not in alliance_ids:
                errors.append(
                    f"default_targets[{alliance_id}] references unknown "
                    f"target '{override['target']}'"
                )
        elif "strategy" in override:
            if len(override) != 1:
                errors.append(
                    f"default_targets[{alliance_id}] has 'strategy' with extra keys: "
                    f"{sorted(set(override.keys()) - {'strategy'})}"
                )
            if override["strategy"] not in _VALID_STRATEGIES:
                errors.append(
                    f"default_targets[{alliance_id}] strategy must be one of "
                    f"{sorted(_VALID_STRATEGIES)}, got '{override['strategy']}'"
                )
        else:
            errors.append(
                f"default_targets[{alliance_id}] must have exactly one key: "
                f"'target' or 'strategy'"
            )

    # Check event_targets
    for event_num, targets in data.get("event_targets", {}).items():
        for attacker_id, value in targets.items():
            if attacker_id not in alliance_ids:
                errors.append(
                    f"event_targets references unknown alliance '{attacker_id}'"
                )
            if isinstance(value, str):
                if value not in alliance_ids:
                    errors.append(
                        f"event_targets references unknown alliance '{value}'"
                    )
            elif isinstance(value, dict):
                if "target" in value:
                    if len(value) != 1:
                        errors.append(
                            f"event_targets[{event_num}][{attacker_id}] has "
                            f"'target' with extra keys: "
                            f"{sorted(set(value.keys()) - {'target'})}"
                        )
                    if value["target"] not in alliance_ids:
                        errors.append(
                            f"event_targets[{event_num}][{attacker_id}] references "
                            f"unknown target '{value['target']}'"
                        )
                elif "strategy" in value:
                    if len(value) != 1:
                        errors.append(
                            f"event_targets[{event_num}][{attacker_id}] has "
                            f"'strategy' with extra keys: "
                            f"{sorted(set(value.keys()) - {'strategy'})}"
                        )
                    if value["strategy"] not in _VALID_STRATEGIES:
                        errors.append(
                            f"event_targets[{event_num}][{attacker_id}] strategy "
                            f"must be one of {sorted(_VALID_STRATEGIES)}, "
                            f"got '{value['strategy']}'"
                        )
                else:
                    errors.append(
                        f"event_targets[{event_num}][{attacker_id}] must be a "
                        f"string or dict with 'target' or 'strategy'"
                    )
            else:
                errors.append(
                    f"event_targets[{event_num}][{attacker_id}] must be a "
                    f"string or dict, got {type(value).__name__}"
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

    # Check faction_targeting_strategy
    faction_strategy = data.get("faction_targeting_strategy", {})
    for faction_name, strat in faction_strategy.items():
        if faction_ids is not None and faction_name not in faction_ids:
            errors.append(
                f"faction_targeting_strategy references unknown faction "
                f"'{faction_name}'"
            )
        if strat not in _VALID_STRATEGIES:
            errors.append(
                f"faction_targeting_strategy[{faction_name}] must be one of "
                f"{sorted(_VALID_STRATEGIES)}, got '{strat}'"
            )

    # Check MC randomness parameters
    for key in ("targeting_temperature", "power_noise", "outcome_noise"):
        val = data.get(key)
        if val is not None:
            if not isinstance(val, (int, float)):
                errors.append(f"'{key}' must be a number, got {type(val).__name__}")
            elif val < 0:
                errors.append(f"'{key}' must be non-negative, got {val}")

    # Check tier_optimization_* fields
    top_n = data.get("tier_optimization_top_n")
    fallback = data.get("tier_optimization_fallback")
    strategy_for_tier = data.get("targeting_strategy", "expected_value")

    if (top_n is not None or fallback is not None) \
            and strategy_for_tier != "maximize_tier":
        errors.append(
            "'tier_optimization_top_n' and 'tier_optimization_fallback' "
            "are only valid when targeting_strategy is 'maximize_tier', "
            f"got targeting_strategy='{strategy_for_tier}'"
        )

    if top_n is not None:
        if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n <= 0:
            errors.append(
                "'tier_optimization_top_n' must be a positive integer, "
                f"got {top_n!r}"
            )

    if fallback is not None:
        if fallback not in _VALID_FALLBACK_STRATEGIES:
            errors.append(
                f"'tier_optimization_fallback' must be one of "
                f"{sorted(_VALID_FALLBACK_STRATEGIES)}, got '{fallback}'"
            )

    # Check for competing wildcards in battle_outcome_matrix
    for day, attackers in matrix.items():
        wildcard_defender_entry = attackers.get("*", {})
        wildcard_defender_ids = set(wildcard_defender_entry.keys())

        for attacker_id, defenders in attackers.items():
            if attacker_id == "*":
                continue
            if "*" not in defenders:
                continue
            # attacker_id has a wildcard defender default
            # Check each defender in the "*" attacker default
            for defender_id in wildcard_defender_ids:
                if defender_id == "*":
                    continue
                # Does this attacker have an explicit entry for this defender?
                if defender_id not in defenders:
                    errors.append(
                        f"battle_outcome_matrix[{day}]: competing wildcards "
                        f"for {attacker_id} vs {defender_id} — "
                        f"{attacker_id} has '*' default and '*' has "
                        f"{defender_id} default. Add an explicit "
                        f"matrix[{day}][{attacker_id}][{defender_id}] entry "
                        f"to disambiguate."
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
