#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys

from spice_war.sheets.template import generate_template
from spice_war.utils.validation import ValidationError, load_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a CSV template for model configuration"
    )
    parser.add_argument("state_file", help="Path to initial state JSON")
    parser.add_argument("--top", type=int, default=6, help="Top N alliances per faction (default: 6)")
    parser.add_argument("--output", metavar="PATH", help="Write CSV to PATH (default: stdout)")
    args = parser.parse_args(argv)

    try:
        alliances, schedule = load_state(args.state_file)
    except ValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    rows = generate_template(alliances, schedule, top_n=args.top)

    if args.output:
        with open(args.output, "w", newline="") as f:
            csv.writer(f).writerows(rows)
        print(f"Template written to {args.output}")
    else:
        csv.writer(sys.stdout).writerows(rows)

    return 0


if __name__ == "__main__":
    sys.exit(main())
