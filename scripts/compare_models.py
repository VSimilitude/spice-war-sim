#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from spice_war.game.monte_carlo import run_monte_carlo
from spice_war.utils.validation import ValidationError, load_model_config, load_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare multiple model configs via Monte Carlo"
    )
    parser.add_argument("state_file", help="Path to initial state JSON")
    parser.add_argument(
        "model_files", nargs="+", metavar="MODEL_FILE",
        help="Paths to model config JSONs (1+)"
    )
    parser.add_argument(
        "-n", "--num-iterations", type=int, default=1000,
        help="Iterations per model"
    )
    parser.add_argument("--base-seed", type=int, default=0)
    parser.add_argument(
        "--alliance", action="append", dest="alliances", default=None,
        help="Filter output to this alliance (repeatable)"
    )
    parser.add_argument("--output", metavar="PATH")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        alliances, schedule = load_state(args.state_file)
        alliance_ids = {a.alliance_id for a in alliances}
        model_configs = []
        for path in args.model_files:
            config = load_model_config(path, alliance_ids, alliances)
            model_configs.append(config)
    except ValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Assign labels [A], [B], [C], ...
    labels = [chr(ord("A") + i) for i in range(len(model_configs))]

    # Run MC for each model with same seed sequence
    results = {}
    for label, config in zip(labels, model_configs):
        mc_result = run_monte_carlo(
            alliances, schedule, config,
            num_iterations=args.num_iterations,
            base_seed=args.base_seed,
        )
        results[label] = mc_result

    # Determine display alliances
    all_aids = [a.alliance_id for a in alliances]
    if args.alliances:
        display_aids = [aid for aid in args.alliances if aid in alliance_ids]
        unknown = [aid for aid in args.alliances if aid not in alliance_ids]
        for aid in unknown:
            print(f"Warning: unknown alliance '{aid}'", file=sys.stderr)
    else:
        display_aids = list(all_aids)

    # Sort by first model's T1 probability desc, then mean spice desc
    first_label = labels[0]
    first_result = results[first_label]
    display_aids = sorted(
        display_aids,
        key=lambda aid: (
            first_result.tier_distribution(aid).get(1, 0),
            first_result.spice_stats(aid)["mean"],
        ),
        reverse=True,
    )

    if not args.quiet:
        _print_comparison(
            args, labels, results, display_aids, args.num_iterations
        )

    if args.output:
        _write_json(
            args.output, args, labels, results, display_aids,
            args.num_iterations,
        )

    return 0


def _print_comparison(args, labels, results, display_aids, num_iterations):
    n_models = len(labels)
    print(
        f"Comparative Monte Carlo — {num_iterations} iterations, "
        f"{n_models} models"
    )
    print()

    print("Model files:")
    for label, path in zip(labels, args.model_files):
        print(f"  [{label}] {path}")
    print()

    name_width = max(len(aid) for aid in display_aids) if display_aids else 4

    # Tier 1 Distribution table
    print("Tier 1 Distribution:")
    header = f"{'':>{name_width}}  " + "  ".join(
        f"{'[' + label + ']':>9}" for label in labels
    )
    print(header)
    for aid in display_aids:
        parts = []
        for label in labels:
            t1 = results[label].tier_distribution(aid).get(1, 0)
            parts.append(f"{t1 * 100:>8.1f}%")
        print(f"{aid:>{name_width}}  {'  '.join(parts)}")
    print()

    # Mean Spice table
    print("Mean Spice:")
    header = f"{'':>{name_width}}  " + "  ".join(
        f"{'[' + label + ']':>13}" for label in labels
    )
    print(header)
    for aid in display_aids:
        parts = []
        for label in labels:
            mean = results[label].spice_stats(aid)["mean"]
            parts.append(f"{mean:>13,}")
        print(f"{aid:>{name_width}}  {'  '.join(parts)}")


def _write_json(path, args, labels, results, display_aids, num_iterations):
    data = {
        "num_iterations": num_iterations,
        "base_seed": args.base_seed,
        "models": [
            {"file": f, "label": label}
            for f, label in zip(args.model_files, labels)
        ],
        "results": {},
    }

    for aid in display_aids:
        data["results"][aid] = {}
        for label in labels:
            data["results"][aid][label] = {
                "tier_distribution": {
                    str(tier): frac
                    for tier, frac in results[label]
                        .tier_distribution(aid).items()
                },
                "spice_stats": results[label].spice_stats(aid),
            }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    sys.exit(main())
