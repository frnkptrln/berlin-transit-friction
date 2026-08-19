#!/usr/bin/env python3
"""Build daily metrics from the event ledger.

Storage is partitioned in UTC; meaning is reported in Berlin local time, so
windows run midnight to midnight in Europe/Berlin and are 23 or 25 hours long
twice a year. Every row states its window length rather than assuming 24.

Nothing here reads a source. Aggregates are a pure function of the events, and
deleting them entirely must be repairable by re-running this.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transit_friction.config import (  # noqa: E402
    AGGREGATES_DIR,
    EVENTS_DIR,
    RAW_LAYER_DIR,
    SITE_DATA_DIR,
)
from transit_friction.events.aggregates import (  # noqa: E402
    build_window_summary,
    local_day_window,
)
from transit_friction.events.coverage import compute_coverage  # noqa: E402
from transit_friction.events.episodes import build_episodes  # noqa: E402
from transit_friction.events.publish import (  # noqa: E402
    site_projection,
    to_metric_rows,
    write_daily_metrics,
)
from transit_friction.events.store import (  # noqa: E402
    load_recent_observations,
    load_recent_transitions,
)


def _days(args) -> list[date]:
    if args.date:
        return [date.fromisoformat(args.date)]
    end = date.fromisoformat(args.until) if args.until else (
        datetime.now(timezone.utc).date() - timedelta(days=1)
    )
    return [end - timedelta(days=offset) for offset in range(args.days - 1, -1, -1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events-root", type=Path, default=EVENTS_DIR)
    parser.add_argument("--raw-root", type=Path, default=RAW_LAYER_DIR)
    parser.add_argument("--aggregates-root", type=Path, default=AGGREGATES_DIR)
    parser.add_argument("--site-root", type=Path, default=SITE_DATA_DIR)
    parser.add_argument("--date", help="a single Berlin-local day, YYYY-MM-DD")
    parser.add_argument("--until", help="last Berlin-local day, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--reason", help="why this rebuild happened, recorded when values change"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    built_at = datetime.now(timezone.utc)
    days = _days(args)
    span_start, _ = local_day_window(min(days))
    _, span_end = local_day_window(max(days))

    transitions = load_recent_transitions(
        args.events_root, args.raw_root, end=span_end
    )
    observations = load_recent_observations(
        args.events_root, args.raw_root, end=span_end
    )
    sources = sorted({row.source_id for row in observations})
    episodes = build_episodes(transitions, as_of=span_end)

    written: list[dict] = []
    summaries: list[tuple[str, dict]] = []
    for day in days:
        window_start, window_end = local_day_window(day)
        coverages = {
            source: compute_coverage(observations, source, window_start, window_end)
            for source in sources
        }
        summary = build_window_summary(
            episodes,
            coverages,
            window_start=window_start,
            window_end=window_end,
            as_of=min(span_end, window_end),
        )
        summaries.append((day.isoformat(), summary))
        if args.dry_run:
            continue
        written.append(
            write_daily_metrics(
                to_metric_rows(
                    summary, local_date=day.isoformat(), built_at=built_at
                ),
                day,
                args.aggregates_root,
                reason=args.reason,
            )
        )

    projection = site_projection(summaries)
    if not args.dry_run:
        args.site_root.mkdir(parents=True, exist_ok=True)
        (args.site_root / "accessibility-daily.json").write_text(
            json.dumps(projection, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "days": [day.isoformat() for day in days],
                "sources": sources,
                "episodes_considered": len(episodes),
                "partitions_written": [
                    item for item in written if item.get("changed")
                ],
                "partitions_unchanged": sum(
                    1 for item in written if not item.get("changed")
                ),
                "days_published": projection["days_published"],
                "days_withheld": projection["days_withheld"],
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
