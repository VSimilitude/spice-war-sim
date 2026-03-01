"""Display attacker/defender full success probability grids from a state file.

Usage:
    .venv/bin/python scripts/probability_grid.py <state_file>
    .venv/bin/python scripts/probability_grid.py data/s3_state_20260228_5pm.json
"""

from __future__ import annotations

import json
import sys


def heuristic_full(atk_power: float, def_power: float, day: str) -> float:
    ratio = atk_power / def_power
    if day == "wednesday":
        return max(0.0, min(1.0, 2.5 * ratio - 2.0))
    else:
        return max(0.0, min(1.0, 3.25 * ratio - 3.0))


def fmt(val: float) -> str:
    pct = val * 100
    if pct == 0:
        return "  - "
    elif pct >= 99.95:
        return " 100"
    else:
        return f"{pct:4.0f}"


def print_grid(
    title: str,
    attackers: list[tuple[str, float]],
    defenders: list[tuple[str, float]],
    day: str,
) -> None:
    print(f"\n{'=' * 40}")
    print(f"  {title}")
    print(f"  (heuristic full_success %)")
    print(f"{'=' * 40}")

    col_w = 5
    header = "ATK\\DEF " + "".join(f"{did:>{col_w}}" for did, _ in defenders)
    print(header)
    print("-" * len(header))

    for atk_id, atk_pow in attackers:
        row = f"{atk_id:<8}"
        for _, def_pow in defenders:
            val = heuristic_full(atk_pow, def_pow, day)
            row += f"{fmt(val):>{col_w}}"
        print(row)


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <state_file>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    factions: dict[str, list[tuple[str, float]]] = {}
    for a in data["alliances"]:
        factions.setdefault(a["faction"], []).append(
            (a["alliance_id"], a["power"])
        )

    for faction in factions:
        factions[faction].sort(key=lambda x: -x[1])

    faction_names = sorted(factions.keys())
    if len(faction_names) != 2:
        print(f"Expected 2 factions, got {len(faction_names)}", file=sys.stderr)
        sys.exit(1)

    for day in ("wednesday", "saturday"):
        for atk_faction in faction_names:
            def_faction = [f for f in faction_names if f != atk_faction][0]
            title = f"{day.capitalize()}: {atk_faction} \u2192 {def_faction}"
            print_grid(title, factions[atk_faction], factions[def_faction], day)


if __name__ == "__main__":
    main()
