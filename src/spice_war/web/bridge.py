from __future__ import annotations

import csv
import io

from spice_war.game.monte_carlo import run_monte_carlo as run_monte_carlo_impl
from spice_war.game.simulator import simulate_war
from spice_war.models.configurable import ConfigurableModel, heuristic_from_ratio
from spice_war.utils.data_structures import Alliance, EventConfig
from spice_war.utils.validation import ValidationError, _check_model_references

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


def _validate_state_structure(state_dict: dict) -> None:
    if not isinstance(state_dict, dict):
        raise ValidationError("State must be a JSON object")
    if "alliances" not in state_dict:
        raise ValidationError("State must contain 'alliances'")
    if "event_schedule" not in state_dict:
        raise ValidationError("State must contain 'event_schedule'")
    if not state_dict["alliances"]:
        raise ValidationError("State must contain at least one alliance")
    if not state_dict["event_schedule"]:
        raise ValidationError("State must contain at least one event")

    factions = {a["faction"] for a in state_dict["alliances"] if "faction" in a}
    if len(factions) != 2:
        raise ValidationError(
            f"State must contain exactly 2 factions, found {len(factions)}: "
            f"{sorted(factions)}"
        )

    for i, event in enumerate(state_dict["event_schedule"]):
        if "attacker_faction" in event and event["attacker_faction"] not in factions:
            raise ValidationError(
                f"Event #{i + 1}: attacker_faction '{event['attacker_faction']}' "
                f"is not one of the state's factions: {sorted(factions)}"
            )

    ids = [a.get("alliance_id") for a in state_dict["alliances"]]
    dupes = [aid for aid in ids if ids.count(aid) > 1]
    if dupes:
        raise ValidationError(
            f"Duplicate alliance_id(s): {sorted(set(dupes))}"
        )


def _build_alliances(state_dict: dict) -> list[Alliance]:
    alliances = []
    for i, raw in enumerate(state_dict.get("alliances", [])):
        required = ["alliance_id", "faction", "power", "starting_spice", "daily_rate"]
        missing = [k for k in required if k not in raw]
        if missing:
            raise ValidationError(
                f"Alliance #{i + 1}: missing required fields: {missing}"
            )
        if raw["alliance_id"] == "*":
            raise ValidationError(
                f"Alliance #{i + 1}: '*' is reserved and cannot be used "
                f"as an alliance_id"
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
    return alliances


def _build_schedule(state_dict: dict) -> list[EventConfig]:
    schedule = []
    for i, raw in enumerate(state_dict.get("event_schedule", [])):
        required = ["attacker_faction", "day", "days_before"]
        missing = [k for k in required if k not in raw]
        if missing:
            raise ValidationError(
                f"Event #{i + 1}: missing required fields: {missing}"
            )
        day = raw["day"].lower()
        if day not in ("wednesday", "saturday"):
            raise ValidationError(
                f"Event #{i + 1}: day must be 'wednesday' or 'saturday', "
                f"got '{raw['day']}'"
            )
        schedule.append(
            EventConfig(
                attacker_faction=raw["attacker_faction"],
                day=day,
                days_before=raw["days_before"],
            )
        )
    return schedule


def _validate_model_dict(model_dict: dict, alliances: list[Alliance]) -> None:
    if not isinstance(model_dict, dict):
        raise ValidationError("Model config must be a JSON object")

    unknown = set(model_dict.keys()) - _ALLOWED_MODEL_KEYS
    if unknown:
        raise ValidationError(f"Unknown model config keys: {sorted(unknown)}")

    alliance_ids = {a.alliance_id for a in alliances}
    faction_ids = {a.faction for a in alliances}
    _check_model_references(model_dict, alliance_ids, faction_ids)


def get_default_state() -> dict:
    return {
        "alliances": [
            {"alliance_id": "Ghst", "faction": "Scarlet Legion", "power": 18304755237, "starting_spice": 5800174, "daily_rate": 157799, "name": "GhostSquad", "server": "Warzone #1386"},
            {"alliance_id": "Hot", "faction": "Scarlet Legion", "power": 15509667992, "starting_spice": 5118099, "daily_rate": 146477, "name": "Hot", "server": "Warzone #1386"},
            {"alliance_id": "SPXP", "faction": "Scarlet Legion", "power": 16562165406, "starting_spice": 5093970, "daily_rate": 154614, "name": "Sul Phoenix Prime", "server": "Warzone #1387"},
            {"alliance_id": "NexA", "faction": "Scarlet Legion", "power": 16757937967, "starting_spice": 4998750, "daily_rate": 143222, "name": "Next Age", "server": "Warzone #1387"},
            {"alliance_id": "fate", "faction": "Scarlet Legion", "power": 13861525348, "starting_spice": 4915438, "daily_rate": 119082, "name": "fate united", "server": "Warzone #1386"},
            {"alliance_id": "VNSA", "faction": "Scarlet Legion", "power": 11707788035, "starting_spice": 4823688, "daily_rate": 133615, "name": "VictoryAndStayAllied", "server": "Warzone #1389"},
            {"alliance_id": "BGs", "faction": "Scarlet Legion", "power": 11849958414, "starting_spice": 4748905, "daily_rate": 136512, "name": "Beginnerwarriors", "server": "Warzone #1390"},
            {"alliance_id": "jOy", "faction": "Scarlet Legion", "power": 14603203224, "starting_spice": 4288650, "daily_rate": 134464, "name": "Journey Of Yay", "server": "Warzone #1389"},
            {"alliance_id": "PxGv", "faction": "Scarlet Legion", "power": 10712442643, "starting_spice": 4224801, "daily_rate": 130000, "name": "たぬ森", "server": "Warzone #1390"},
            {"alliance_id": "KORK", "faction": "Scarlet Legion", "power": 14076516849, "starting_spice": 4206112, "daily_rate": 139754, "name": "KOR킹덤", "server": "Warzone #1386"},
            {"alliance_id": "sWAT", "faction": "Scarlet Legion", "power": 12856038089, "starting_spice": 4039662, "daily_rate": 121722, "name": "LandOfMisfits", "server": "Warzone #1386"},
            {"alliance_id": "DNEX", "faction": "Scarlet Legion", "power": 11824278763, "starting_spice": 3957615, "daily_rate": 131172, "name": "Dream Nexus", "server": "Warzone #1390"},
            {"alliance_id": "LEO1", "faction": "Scarlet Legion", "power": 13696552623, "starting_spice": 3894624, "daily_rate": 113651, "name": "Lion Empire Order", "server": "Warzone #1387"},
            {"alliance_id": "YYAN", "faction": "Scarlet Legion", "power": 12008557793, "starting_spice": 3874582, "daily_rate": 130000, "name": "Ying Yang", "server": "Warzone #1387"},
            {"alliance_id": "ktme", "faction": "Scarlet Legion", "power": 9921270354, "starting_spice": 3761820, "daily_rate": 130000, "name": "killtime", "server": "Warzone #1389"},
            {"alliance_id": "FRTG", "faction": "Scarlet Legion", "power": 12105090104, "starting_spice": 3636314, "daily_rate": 130000, "name": "FRTG is in the house", "server": "Warzone #1387"},
            {"alliance_id": "fabl", "faction": "Scarlet Legion", "power": 12084632146, "starting_spice": 3555199, "daily_rate": 107416, "name": "TEAM仕事人", "server": "Warzone #1390"},
            {"alliance_id": "SWEH", "faction": "Scarlet Legion", "power": 7757184703, "starting_spice": 3419720, "daily_rate": 130000, "name": "Sweet Home", "server": "Warzone #1389"},
            {"alliance_id": "ICGO", "faction": "Scarlet Legion", "power": 9862550440, "starting_spice": 3389236, "daily_rate": 133863, "name": "いちご", "server": "Warzone #1390"},
            {"alliance_id": "1CES", "faction": "Scarlet Legion", "power": 12846831524, "starting_spice": 3349282, "daily_rate": 123814, "name": "ICEBERG ALLIANCE", "server": "Warzone #1389"},
            {"alliance_id": "MY81", "faction": "Scarlet Legion", "power": 6842480858, "starting_spice": 3265844, "daily_rate": 108761, "name": "VNTG", "server": "Warzone #1389"},
            {"alliance_id": "SPXR", "faction": "Scarlet Legion", "power": 12597390606, "starting_spice": 3250816, "daily_rate": 111308, "name": "Sul Phoenix Rising", "server": "Warzone #1387"},
            {"alliance_id": "LoFi", "faction": "Scarlet Legion", "power": 9267253950, "starting_spice": 3218082, "daily_rate": 123974, "name": "LoFi Land", "server": "Warzone #1389"},
            {"alliance_id": "HOpE", "faction": "Scarlet Legion", "power": 8661455980, "starting_spice": 3211327, "daily_rate": 115968, "name": "HeartOfPeaceEnergy", "server": "Warzone #1389"},
            {"alliance_id": "STrH", "faction": "Scarlet Legion", "power": 9645958335, "starting_spice": 3161049, "daily_rate": 111803, "name": "STAR HAVEN", "server": "Warzone #1390"},
            {"alliance_id": "MUDD", "faction": "Scarlet Legion", "power": 7739968188, "starting_spice": 3086130, "daily_rate": 130000, "name": "Bayou Mudwrestlers", "server": "Warzone #1386"},
            {"alliance_id": "VON", "faction": "Golden Tribe", "power": 19075548647, "starting_spice": 5824987, "daily_rate": 148953, "name": "Chosen", "server": "Warzone #1395"},
            {"alliance_id": "TWAO", "faction": "Golden Tribe", "power": 15025271013, "starting_spice": 4793663, "daily_rate": 152739, "name": "TOGETHER WE ARE ONE", "server": "Warzone #1412"},
            {"alliance_id": "UTW", "faction": "Golden Tribe", "power": 17711900592, "starting_spice": 4016572, "daily_rate": 149661, "name": "UTW", "server": "Warzone #1395"},
            {"alliance_id": "RAG3", "faction": "Golden Tribe", "power": 17034821954, "starting_spice": 3837892, "daily_rate": 166290, "name": "Raging Legion", "server": "Warzone #1397"},
            {"alliance_id": "hAnA", "faction": "Golden Tribe", "power": 11089698546, "starting_spice": 3630082, "daily_rate": 129140, "name": "Happy and New age", "server": "Warzone #1397"},
            {"alliance_id": "DEED", "faction": "Golden Tribe", "power": 13589238775, "starting_spice": 3379123, "daily_rate": 150652, "name": "NICE", "server": "Warzone #1401"},
            {"alliance_id": "PPLE", "faction": "Golden Tribe", "power": 14584581500, "starting_spice": 3341114, "daily_rate": 132784, "name": "Pukkas People", "server": "Warzone #1395"},
            {"alliance_id": "SPir", "faction": "Golden Tribe", "power": 9955939718, "starting_spice": 3284859, "daily_rate": 126027, "name": "The Shrimp pirates", "server": "Warzone #1395"},
            {"alliance_id": "GDZO", "faction": "Golden Tribe", "power": 15541988443, "starting_spice": 3231142, "daily_rate": 151288, "name": "GodZofOlympuS", "server": "Warzone #1401"},
            {"alliance_id": "ZFKs", "faction": "Golden Tribe", "power": 11696793473, "starting_spice": 2759819, "daily_rate": 112865, "name": "The Unbroken", "server": "Warzone #1397"},
            {"alliance_id": "hvm6", "faction": "Golden Tribe", "power": 10273632363, "starting_spice": 2646641, "daily_rate": 113289, "name": "heavymetal666", "server": "Warzone #1397"},
            {"alliance_id": "BdE", "faction": "Golden Tribe", "power": 13431477273, "starting_spice": 2535945, "daily_rate": 114139, "name": "Big Dig Energy", "server": "Warzone #1395"},
            {"alliance_id": "USA5", "faction": "Golden Tribe", "power": 11666656368, "starting_spice": 2435559, "daily_rate": 136712, "name": "Americans United", "server": "Warzone #1397"},
            {"alliance_id": "DMUW", "faction": "Golden Tribe", "power": 9550866798, "starting_spice": 2430273, "daily_rate": 119764, "name": "天命戰鬥士", "server": "Warzone #1412"},
            {"alliance_id": "KAG3", "faction": "Golden Tribe", "power": 8415527016, "starting_spice": 2413101, "daily_rate": 105293, "name": "Khaos legion", "server": "Warzone #1397"},
            {"alliance_id": "Bo5S", "faction": "Golden Tribe", "power": 11083279867, "starting_spice": 2395667, "daily_rate": 119764, "name": "BOSS UNITED", "server": "Warzone #1412"},
            {"alliance_id": "VNFs", "faction": "Golden Tribe", "power": 10041951216, "starting_spice": 2314462, "daily_rate": 120153, "name": "VN Fire Star", "server": "Warzone #1412"},
            {"alliance_id": "HULK", "faction": "Golden Tribe", "power": 10500670352, "starting_spice": 2311050, "daily_rate": 109291, "name": "HeroicUnity LastKill", "server": "Warzone #1395"},
            {"alliance_id": "AR35", "faction": "Golden Tribe", "power": 12109016820, "starting_spice": 2183895, "daily_rate": 90575, "name": "LEGION OF ARES", "server": "Warzone #1397"},
            {"alliance_id": "LATZ", "faction": "Golden Tribe", "power": 9790611718, "starting_spice": 1991282, "daily_rate": 112334, "name": "Elite Origins", "server": "Warzone #1401"},
        ],
        "event_schedule": [
            {"attacker_faction": "Scarlet Legion", "day": "wednesday", "days_before": 4},
            {"attacker_faction": "Golden Tribe", "day": "saturday", "days_before": 3},
        ],
    }


def get_default_model_config(state_dict: dict | None = None) -> dict:
    config: dict = {"random_seed": 42}

    if not state_dict:
        return config

    alliances = state_dict.get("alliances", [])
    events = state_dict.get("event_schedule", [])
    if not alliances or not events:
        return config

    # Find top alliance per faction by power
    top_by_faction: dict[str, str] = {}
    max_power: dict[str, int] = {}
    for a in alliances:
        faction = a.get("faction", "")
        power = a.get("power", 0)
        if faction not in max_power or power > max_power[faction]:
            max_power[faction] = power
            top_by_faction[faction] = a["alliance_id"]

    faction_list = list(top_by_faction.keys())
    if len(faction_list) != 2:
        return config

    top_a = top_by_faction[faction_list[0]]
    top_b = top_by_faction[faction_list[1]]

    # Build matrix for each unique day with empty probability objects
    days = list(dict.fromkeys(e.get("day", "") for e in events))
    matrix: dict = {}
    for day in days:
        matrix[day] = {
            top_a: {top_b: {}},
            top_b: {top_a: {}},
        }

    config["battle_outcome_matrix"] = matrix
    return config


def validate_state(state_dict: dict) -> dict:
    try:
        _validate_state_structure(state_dict)
        alliances = _build_alliances(state_dict)
        schedule = _build_schedule(state_dict)
        return {
            "ok": True,
            "alliances": [
                {
                    "alliance_id": a.alliance_id,
                    "faction": a.faction,
                    "power": a.power,
                    "starting_spice": a.starting_spice,
                    "daily_rate": a.daily_spice_rate,
                }
                for a in alliances
            ],
            "event_schedule": [
                {
                    "event_number": i + 1,
                    "attacker_faction": e.attacker_faction,
                    "day": e.day,
                    "days_before": e.days_before,
                }
                for i, e in enumerate(schedule)
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def validate_model_config(model_dict: dict, state_dict: dict) -> dict:
    try:
        alliances = _build_alliances(state_dict)
        _validate_model_dict(model_dict, alliances)
        return {"ok": True, "config": model_dict}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_single(
    state_dict: dict, model_dict: dict, seed: int | None = None
) -> dict:
    try:
        _validate_state_structure(state_dict)
        alliances = _build_alliances(state_dict)
        schedule = _build_schedule(state_dict)
        _validate_model_dict(model_dict, alliances)

        config = dict(model_dict)
        if seed is not None:
            config["random_seed"] = seed
        elif "random_seed" not in config:
            config["random_seed"] = 0

        model = ConfigurableModel(config, alliances)
        result = simulate_war(alliances, schedule, model)

        return {
            "ok": True,
            "seed": config["random_seed"],
            "final_spice": result["final_spice"],
            "rankings": result["rankings"],
            "event_history": result["event_history"],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_monte_carlo(
    state_dict: dict,
    model_dict: dict,
    num_iterations: int = 1000,
    base_seed: int = 0,
) -> dict:
    try:
        _validate_state_structure(state_dict)
        alliances = _build_alliances(state_dict)
        schedule = _build_schedule(state_dict)
        _validate_model_dict(model_dict, alliances)

        result = run_monte_carlo_impl(
            alliances, schedule, model_dict,
            num_iterations=num_iterations,
            base_seed=base_seed,
        )

        return {
            "ok": True,
            "num_iterations": result.num_iterations,
            "base_seed": result.base_seed,
            "tier_distribution": {
                aid: {
                    str(tier): frac
                    for tier, frac in result.tier_distribution(aid).items()
                }
                for aid in result.tier_counts
            },
            "spice_stats": {
                aid: result.spice_stats(aid)
                for aid in result.tier_counts
            },
            "targeting_matrix": result.targeting_matrix(),
            "raw_results": result.per_iteration,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def compute_heuristic(attacker_power: float, defender_power: float, day: str) -> dict:
    """Compute heuristic battle probabilities for a power ratio and day."""
    ratio = attacker_power / defender_power if defender_power > 0 else 0.0
    probs = heuristic_from_ratio(ratio, day)
    return {
        "full": round(probs["full_success"] * 100),
        "partial": round(probs["partial_success"] * 100),
    }


def import_csv(csv_text: str) -> dict:
    try:
        from spice_war.sheets.importer import import_from_csv

        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        config = import_from_csv(rows)
        return {"ok": True, "config": config}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def generate_template_csv(state_dict: dict, top_n: int = 6) -> dict:
    try:
        from spice_war.sheets.template import generate_template

        alliances = _build_alliances(state_dict)
        schedule = _build_schedule(state_dict)
        rows = generate_template(alliances, schedule, top_n=top_n)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(rows)
        return {"ok": True, "csv": output.getvalue()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
