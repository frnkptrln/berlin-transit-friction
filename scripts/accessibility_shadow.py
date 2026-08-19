#!/usr/bin/env python3
"""Run one non-publishing accessibility observation.

Writes below ``.shadow/`` by default, which is gitignored. It never commits,
publishes, or schedules a run. The transition and observation rows it appends
use the same format as the eventual published layer, so a shadow period is a
rehearsal of the real thing rather than a different pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transit_friction.accessibility.adapter import payload_digest  # noqa: E402
from transit_friction.accessibility.parser import (  # noqa: E402
    DEFAULT_SOURCE_URL,
    parse_brokenlifts_snapshot,
)
from transit_friction.accessibility.shadow import (  # noqa: E402
    FetchResult,
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
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(".shadow"),
        help="directory holding the shadow events tree, raw buffer and run log",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    observed_at = datetime.now(timezone.utc)
    if args.input_html:
        html = args.input_html.read_text(encoding="utf-8")
        fetched = FetchResult(
            snapshot=parse_brokenlifts_snapshot(
                html, observed_at=observed_at, source_url=args.url
            ),
            payload_sha256=payload_digest(html),
        )
    else:
        fetched = fetch_snapshot(url=args.url, observed_at=observed_at)

    summary = apply_snapshot(
        fetched,
        paths=ShadowPaths.under(args.root),
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["trusted_for_resolution"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
