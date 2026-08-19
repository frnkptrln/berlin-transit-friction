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
    DATA_DIR,
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
from transit_friction.population.accounting import account  # noqa: E402
from transit_friction.population.crosswalk import build_crosswalk  # noqa: E402
from transit_friction.population.frame import derive_population  # noqa: E402
from transit_friction.population.monitoring import (  # noqa: E402
    Monitoring,
    from_fault_listings,
)
from transit_friction.population.store import (  # noqa: E402
    load_manifest,
    population_for_window,
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
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=DATA_DIR / "reference",
        help="where derived populations live; without one the days publish "
        "absolute figures and say there is no denominator",
    )
    parser.add_argument(
        "--gtfs-archive",
        type=Path,
        help="derive the population from this archive instead of reading a "
        "stored one (useful before the first population has been written)",
    )
    parser.add_argument("--date", help="a single Berlin-local day, YYYY-MM-DD")
    parser.add_argument("--until", help="last Berlin-local day, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--depends-on",
        default="brokenlifts",
        help="comma-separated observation sources this metric is computed from; "
        "coverage of any other source in the ledger must not gate it",
    )
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
    observed_sources = sorted({row.source_id for row in observations})
    depends_on = [s for s in args.depends_on.split(",") if s.strip()]
    missing = [s for s in depends_on if s not in observed_sources]
    if missing:
        print(
            json.dumps(
                {
                    "error": "no observations for a declared dependency",
                    "missing": missing,
                    "observed": observed_sources,
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    # Coverage is computed for every source so the ledger stays legible, but
    # only the declared dependencies decide whether a value may be published.
    sources = observed_sources
    episodes = build_episodes(transitions, as_of=span_end)

    # The denominator, if one covers this span. Selected by the feed's own
    # service window, so a stalled adoption cannot serve last year's population.
    population = denominator_status = population_id = None
    if args.gtfs_archive:
        population = derive_population(args.gtfs_archive)
        denominator_status, population_id = "derived", "adhoc"
    else:
        population_id, denominator_status = population_for_window(
            args.reference_root, min(days), max(days)
        )
        if population_id:
            manifest = load_manifest(args.reference_root, population_id)
            archive = manifest.get("archive_name")
            denominator_status = (
                "adopted" if archive else "adopted_without_archive"
            )

    written: list[dict] = []
    summaries: list[tuple[str, dict]] = []
    accountings: dict[str, dict] = {}
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
            depends_on=depends_on,
        )
        summaries.append((day.isoformat(), summary))

        if population is not None:
            seen = sorted({e.station_id for e in episodes if e.station_id})
            crosswalk = build_crosswalk(population, seen)
            # Today the only evidence a source covers a station is that it once
            # named it in a fault list. That is a lower bound on coverage, so
            # the ceiling stays at 1 and no point estimate is expressible.
            covered = {
                crosswalk.resolutions[i].station_key
                for i in seen
                if crosswalk.resolutions[i].matched
            }
            accounting = account(
                population=population,
                crosswalk=crosswalk,
                episodes=episodes,
                days=[day],
                window_start=window_start,
                window_end=window_end,
                as_of=min(span_end, window_end),
                monitoring=Monitoring(
                    sources={
                        "brokenlifts": from_fault_listings(
                            "brokenlifts", covered, window_end
                        )
                    }
                ),
                population_id=population_id or "",
            )
            payload = accounting.to_dict()
            payload["denominator_status"] = denominator_status
            accountings[day.isoformat()] = payload
        elif denominator_status:
            accountings[day.isoformat()] = {"denominator_status": denominator_status}

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

    projection = site_projection(summaries, accountings)
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
                "depends_on": depends_on,
                "episodes_considered": len(episodes),
                "partitions_written": [
                    item for item in written if item.get("changed")
                ],
                "partitions_unchanged": sum(
                    1 for item in written if not item.get("changed")
                ),
                "days_published": projection["days_published"],
                "denominator_status": denominator_status,
                "population_id": population_id,
                "days_with_a_denominator": projection["days_with_a_denominator"],
                "days_withheld": projection["days_withheld"],
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
