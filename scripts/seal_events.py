#!/usr/bin/env python3
"""Freeze closed days into immutable partitions, and merge old months.

Sealing turns the day's append-only JSONL buffer into one Parquet file with a
manifest recording its row count and content hash. The file is never written
again. Rollup merges 30-day-old dailies into a monthly file, but only after
every input hash verifies, and it records those hashes so the provenance chain
survives the files themselves.

See docs/partitioning.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transit_friction.config import (  # noqa: E402
    EVENTS_DIR,
    EVENT_MANIFESTS_DIR,
    RAW_LAYER_DIR,
)
from transit_friction.events.maintenance import (  # noqa: E402
    rollup_pending,
    seal_pending,
    verify_partitions,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events-root", type=Path, default=EVENTS_DIR)
    parser.add_argument("--manifest-root", type=Path, default=EVENT_MANIFESTS_DIR)
    parser.add_argument("--raw-root", type=Path, default=RAW_LAYER_DIR)
    parser.add_argument(
        "--rollup",
        action="store_true",
        help="also merge months whose newest day is at least 30 days old",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="check sealed partitions against their manifests and exit",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    problems = verify_partitions(args.events_root, args.manifest_root)
    if problems:
        for problem in problems:
            print(f"integrity: {problem}", file=sys.stderr)
        return 1
    if args.verify_only:
        print(json.dumps({"verified": True, "problems": []}, indent=2))
        return 0

    sealed = seal_pending(
        raw_root=args.raw_root,
        events_root=args.events_root,
        manifest_root=args.manifest_root,
        now=now,
        dry_run=args.dry_run,
    )
    rolled = (
        rollup_pending(
            events_root=args.events_root,
            manifest_root=args.manifest_root,
            raw_root=args.raw_root,
            now=now,
            dry_run=args.dry_run,
        )
        if args.rollup
        else []
    )

    print(
        json.dumps(
            {
                "sealed": [
                    {
                        "table": outcome.table,
                        "day": outcome.day.isoformat(),
                        "rows": outcome.row_count,
                        "staging_removed": outcome.staging_removed,
                    }
                    for outcome in sealed
                ],
                "rolled_up": [item["partition"] for item in rolled],
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
