#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transit_friction.accessibility.parser import (  # noqa: E402
    DEFAULT_SOURCE_URL,
    parse_brokenlifts_snapshot,
)
from transit_friction.accessibility.shadow import (  # noqa: E402
    ShadowPaths,
    apply_snapshot,
    fetch_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one non-publishing accessibility shadow observation."
    )
    parser.add_argument("--url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--input-html", type=Path)
    parser.add_argument("--state", type=Path, default=Path(".shadow/state.json"))
    parser.add_argument(
        "--transitions",
        type=Path,
        default=Path(".shadow/transitions.jsonl"),
    )
    parser.add_argument("--runs", type=Path, default=Path(".shadow/runs.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    observed_at = datetime.now(timezone.utc)
    if args.input_html:
        snapshot = parse_brokenlifts_snapshot(
            args.input_html.read_text(encoding="utf-8"),
            observed_at=observed_at,
            source_url=args.url,
        )
    else:
        snapshot = fetch_snapshot(url=args.url, observed_at=observed_at)

    summary = apply_snapshot(
        snapshot,
        paths=ShadowPaths(
            state=args.state,
            transitions=args.transitions,
            runs=args.runs,
        ),
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if snapshot.complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
