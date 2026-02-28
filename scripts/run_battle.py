#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spice_war.game.simulator import simulate_war
from spice_war.models.configurable import ConfigurableModel
from spice_war.utils.validation import ValidationError, load_model_config, load_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Spice Wars simulation")
    parser.add_argument("state_file", help="Path to initial state JSON")
    parser.add_argument("model_file", nargs="?", default=None, help="Path to model config JSON")
    parser.add_argument("--output", metavar="PATH", help="Write JSON replay log to PATH")
    parser.add_argument("--seed", type=int, default=None, help="Override random seed")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout summary")
    args = parser.parse_args(argv)

    try:
        alliances, schedule = load_state(args.state_file)
        alliance_ids = {a.alliance_id for a in alliances}
        model_config = load_model_config(args.model_file, alliance_ids)
    except ValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.seed is not None:
        model_config["random_seed"] = args.seed

    seed = model_config.get("random_seed", 0)
    model = ConfigurableModel(model_config, alliances)
    result = simulate_war(alliances, schedule, model)

    if not args.quiet:
        _print_summary(args, alliances, schedule, seed, result)

    if args.output:
        replay = _build_replay(alliances, schedule, seed, result)
        with open(args.output, "w") as f:
            json.dump(replay, f, indent=2)

    return 0


def _print_summary(args, alliances, schedule, seed, result):
    # Header
    print(f"State: {args.state_file}")
    if args.model_file:
        print(f"Model: {args.model_file}")
    else:
        print("Model: (none, using heuristics)")
    print(f"Seed:  {seed}")
    print()

    # Initial state
    name_width = max(len(a.alliance_id) for a in alliances)
    print("Initial State:")
    for a in alliances:
        print(
            f"  {a.alliance_id:<{name_width}}  "
            f"faction={a.faction:<5} "
            f"power={a.power:>5}  "
            f"spice={a.starting_spice:>12,}  "
            f"daily_rate={a.daily_spice_rate:>8,}"
        )
    print()

    # Per-event blocks
    for event in result["event_history"]:
        event_num = event["event_number"]
        attacker_faction = event["attacker_faction"]
        day = event["day"]
        days_before = event["days_before"]
        spice_before = event["spice_before"]
        spice_after = event["spice_after"]

        print(f"Event {event_num}: {attacker_faction} attacks on {day} (+{days_before} days income)")

        print("  Pre-battle spice:")
        for a in alliances:
            print(f"    {a.alliance_id:<{name_width}}  {spice_before[a.alliance_id]:>12,}")

        # Bracket / targeting / reinforcements
        targeting = event["targeting"]
        reinforcements = event["reinforcements"]
        brackets = event["brackets"]

        for bracket_num in sorted(brackets.keys(), key=int):
            bracket = brackets[bracket_num]
            print(f"  Bracket {bracket_num}:")
            # Show each attacker's target
            for attacker_id in bracket["attackers"]:
                if attacker_id in targeting:
                    defender_id = targeting[attacker_id]
                    a_spice = spice_before[attacker_id]
                    d_spice = spice_before[defender_id]
                    print(
                        f"    {attacker_id} ({a_spice:,})"
                        f"  -> {defender_id} ({d_spice:,})"
                    )
            # Show reinforcements in this bracket
            for reinf_id, target_id in reinforcements.items():
                if reinf_id in [d for d in bracket["defenders"]]:
                    r_spice = spice_before[reinf_id]
                    print(f"    {'':>{name_width}}       reinforced by: {reinf_id} ({r_spice:,})")

        # Per-battle results
        for battle in event["battles"]:
            attacker_str = " + ".join(battle["attackers"])
            defender_str = " + ".join(battle["defenders"])
            if battle["reinforcements"]:
                reinf_str = " + ".join(battle["reinforcements"])
                defender_str += f" (+ {reinf_str})"

            outcome = battle["outcome"]
            outcome_prob = battle["outcome_probabilities"][outcome]
            buildings = battle["defender_buildings"]
            theft = battle["theft_percentage"]

            print(f"  Battle: {attacker_str} vs {defender_str}")
            print(f"    Outcome: {outcome} ({outcome_prob:.0%})")
            print(f"    Defender buildings: {buildings}, Theft: {theft:.0f}%")

            if len(battle["attackers"]) > 1:
                splits_parts = [
                    f"{aid} {frac:.0%}"
                    for aid, frac in battle["damage_splits"].items()
                ]
                print(f"    Splits: {', '.join(splits_parts)}")

            print("    Transfers:")
            all_ids = battle["attackers"] + battle["defenders"] + battle["reinforcements"]
            for aid in all_ids:
                amount = battle["transfers"].get(aid, 0)
                if amount >= 0:
                    print(f"      {aid:<{name_width}}  +{amount:>10,}")
                else:
                    print(f"      {aid:<{name_width}}  {amount:>11,}")

        print("  Post-event spice:")
        for a in alliances:
            print(f"    {a.alliance_id:<{name_width}}  {spice_after[a.alliance_id]:>12,}")
        print()

    # Final results
    print("Final Results:")
    for a in alliances:
        spice = result["final_spice"][a.alliance_id]
        tier = result["rankings"][a.alliance_id]
        print(
            f"  {a.alliance_id:<{name_width}}  "
            f"spice={spice:>12,}  "
            f"tier={tier}"
        )


def _build_replay(alliances, schedule, seed, result):
    return {
        "seed": seed,
        "initial_state": {
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
                    "attacker_faction": e.attacker_faction,
                    "day": e.day,
                    "days_before": e.days_before,
                }
                for e in schedule
            ],
        },
        "events": result["event_history"],
        "final_spice": result["final_spice"],
        "rankings": result["rankings"],
    }


if __name__ == "__main__":
    sys.exit(main())
