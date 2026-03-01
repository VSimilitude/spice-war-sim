#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from spice_war.sheets.importer import fetch_csv_rows, import_from_csv
from spice_war.utils.validation import ValidationError, load_state, _check_model_references


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a Google Sheet or CSV file as model config JSON"
    )
    parser.add_argument("url_or_file", help="Google Sheet URL or local CSV path")
    parser.add_argument("--output", metavar="PATH", required=True, help="Write model JSON to PATH")
    parser.add_argument("--state-file", metavar="PATH", help="State file for cross-validation of alliance IDs")
    args = parser.parse_args(argv)

    try:
        rows = fetch_csv_rows(args.url_or_file)
    except Exception as e:
        print(f"Error reading input: {e}", file=sys.stderr)
        return 1

    model = import_from_csv(rows)

    if args.state_file:
        try:
            alliances, _ = load_state(args.state_file)
            alliance_ids = {a.alliance_id for a in alliances}
            _check_model_references(model, alliance_ids)
        except ValidationError as e:
            print(f"Validation error: {e}", file=sys.stderr)
            return 1

    with open(args.output, "w") as f:
        json.dump(model, f, indent=2)
        f.write("\n")

    print(f"Model config written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
