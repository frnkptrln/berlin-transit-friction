#!/usr/bin/env python3
"""Fail the build when a write would break the retention contract.

Implements the seven enforcement rules in RETENTION.md. A policy that is only
written down is the policy the legacy pipeline had.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transit_friction.config import (  # noqa: E402
    AGGREGATES_DIR,
    BASE_DIR,
    EVENTS_DIR,
    EVENT_MANIFESTS_DIR,
    RAW_LAYER_DIR,
)
from transit_friction.events.retention import run_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=BASE_DIR)
    parser.add_argument("--events-root", type=Path, default=EVENTS_DIR)
    parser.add_argument("--manifest-root", type=Path, default=EVENT_MANIFESTS_DIR)
    parser.add_argument("--raw-root", type=Path, default=RAW_LAYER_DIR)
    parser.add_argument("--aggregates-root", type=Path, default=AGGREGATES_DIR)
    args = parser.parse_args()

    results = run_all(
        repo=args.repo,
        events_root=args.events_root,
        manifest_root=args.manifest_root,
        raw_root=args.raw_root,
        aggregates_root=args.aggregates_root,
    )

    failed = 0
    for result in results:
        if result.skipped:
            print(f"  skip  {result.name}: {result.skipped}")
        elif result.ok:
            print(f"  ok    {result.name}")
        else:
            failed += 1
            print(f"  FAIL  {result.name}")
            for problem in result.problems:
                print(f"          {problem}")

    print(f"\n{len(results) - failed}/{len(results)} retention checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
