#!/usr/bin/env python3
"""Derive the denominator population from a static GTFS archive.

Turns "216 outage-hours" into a figure with a stated denominator: which
stations are in scope, which of them have an elevator at all, and how long each
is actually in service. Writes versioned reference data keyed on its content, so
a published number can always name the population it was computed against.

Reads an archive; talks to no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transit_friction.config import DATA_DIR  # noqa: E402
from transit_friction.population.frame import (  # noqa: E402
    DEFAULT_FRAME_PREDICATE,
    derive_population,
)
from transit_friction.population.store import (  # noqa: E402
    list_populations,
    load_manifest,
    population_id,
    write_population,
)


def _predicate(raw: str) -> tuple[tuple[str, str], ...]:
    pairs = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        agency, _, route_type = item.partition("/")
        if not agency or not route_type:
            raise argparse.ArgumentTypeError(
                f"expected agency_id/route_type, got {item!r}"
            )
        pairs.append((agency, route_type))
    return tuple(pairs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archive", type=Path, nargs="?", help="a GTFS .zip")
    parser.add_argument(
        "--reference-root", type=Path, default=DATA_DIR / "reference"
    )
    parser.add_argument(
        "--predicate",
        type=_predicate,
        default=DEFAULT_FRAME_PREDICATE,
        help="comma-separated agency_id/route_type pairs defining the frame "
        "(default: 796/400,1/109 — BVG U-Bahn and S-Bahn Berlin)",
    )
    parser.add_argument("--note", default="", help="where this archive came from")
    parser.add_argument("--list", action="store_true", help="list stored populations")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.list:
        print(json.dumps(
            [load_manifest(args.reference_root, p) for p in list_populations(args.reference_root)],
            indent=2,
        ))
        return 0

    if args.archive is None:
        parser.error("an archive is required unless --list is given")

    population = derive_population(args.archive, predicate=args.predicate)
    pid = population_id(population)
    summary = {
        "population_id": pid,
        "predicate": sorted(f"{a}/{t}" for a, t in args.predicate),
        "feed_service_start": population.feed_start.isoformat() if population.feed_start else None,
        "feed_service_end": population.feed_end.isoformat() if population.feed_end else None,
        **population.diagnostics,
        "dry_run": args.dry_run,
    }

    if not args.dry_run:
        result = write_population(
            population, args.reference_root,
            source_note=args.note, archive_path=args.archive,
        )
        summary["written"] = result.created
        summary["path"] = str(result.path)

    print(json.dumps(summary, indent=2))
    # An archive with no pathways cannot supply an elevator denominator. Say so
    # in the exit code rather than writing a population of zero equipped stations.
    return 0 if population.diagnostics["elevator_equipped"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
