"""Turning window summaries into the published aggregate layer.

Aggregates are the one place recomputation is allowed, because they are a pure
function of the events. But a recomputation that changes a published number is
itself an event: the partition carries an ``aggregate_revision`` that is bumped
only when the values actually differ, and the previous values stay in git
history. Restatement is available; silent restatement is not.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from .aggregates import UNIT
from .records import DailyMetric
from .store import (
    TABLE_DAILY_METRICS,
    read_parquet,
    sort_rows,
    TABLES,
    write_parquet,
)

DIMENSION_ALL = "all"
DIMENSION_STATION = "station"
DIMENSION_SOURCE = "source"


def _metric_uid(local_date: str, metric: str, dimension: str, dimension_id: str) -> str:
    payload = "|".join(("metric", local_date, metric, dimension, dimension_id))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def daily_metrics_path(aggregates_root: Path, day: date) -> Path:
    return aggregates_root / "daily" / f"date={day.isoformat()}" / "metrics.parquet"


def to_metric_rows(
    summary: dict,
    *,
    local_date: str,
    revision: int = 1,
    built_at: datetime | None = None,
) -> list[dict]:
    """Flatten one window summary into long-format rows."""
    window_start = datetime.fromisoformat(summary["window_start"])
    window_end = datetime.fromisoformat(summary["window_end"])
    coverages = summary.get("coverage", {})
    # The coverage stamped on a row is the worst among the sources the metric
    # depends on. Taking the worst across every source in the ledger let an
    # unrelated slow ingest brand every row with its own coverage.
    depends_on = set(summary.get("data_quality", {}).get("sources_used", coverages))
    worst_coverage = min(
        (
            item["coverage_ratio"]
            for source, item in coverages.items()
            if source in depends_on
        ),
        default=0.0,
    )

    def _row(
        metric: str,
        dimension: str,
        dimension_id: str,
        value,
        unit: str,
        *,
        publishable: bool | None = None,
        coverage_ratio: float | None = None,
    ) -> dict:
        return DailyMetric(
            metric_uid=_metric_uid(local_date, metric, dimension, dimension_id),
            local_date=local_date,
            window_start=window_start,
            window_end=window_end,
            window_hours=float(summary["window_hours"]),
            metric=metric,
            dimension=dimension,
            dimension_id=dimension_id,
            value=None if value is None else float(value),
            unit=unit,
            publishable=(
                summary["publishable"] if publishable is None else publishable
            ),
            coverage_ratio=(
                worst_coverage if coverage_ratio is None else coverage_ratio
            ),
            aggregate_revision=revision,
            tuning_fingerprint=summary["tuning_fingerprint"],
            built_at=built_at,
        ).to_dict()

    rows = [
        _row("total_outage_hours", DIMENSION_ALL, "", summary["total_outage_hours"], UNIT),
        _row(
            "total_outage_hours_min",
            DIMENSION_ALL,
            "",
            summary["total_outage_hours_min"],
            UNIT,
        ),
        _row(
            "total_outage_hours_max",
            DIMENSION_ALL,
            "",
            summary["total_outage_hours_max"],
            UNIT,
        ),
        _row("episode_count", DIMENSION_ALL, "", summary["episode_count"], "episodes"),
        _row(
            "active_at_window_end",
            DIMENSION_ALL,
            "",
            summary["active_at_window_end"],
            "episodes",
        ),
        _row(
            "episodes_with_unobserved_time",
            DIMENSION_ALL,
            "",
            summary["episodes_with_unobserved_time"],
            "episodes",
        ),
        _row(
            "unobserved_outage_hours",
            DIMENSION_ALL,
            "",
            summary["unobserved_outage_hours"],
            UNIT,
        ),
    ]

    for station, hours in (summary["outage_hours_by_station"] or {}).items():
        rows.append(_row("outage_hours", DIMENSION_STATION, station, hours, UNIT))

    # Coverage is always publishable: it is the statement about our own
    # observation, not about Berlin, and it is precisely what a reader needs
    # when everything else is null.
    for source, item in coverages.items():
        rows.append(
            _row(
                "coverage_ratio",
                DIMENSION_SOURCE,
                source,
                item["coverage_ratio"],
                "ratio",
                publishable=True,
                coverage_ratio=item["coverage_ratio"],
            )
        )
        rows.append(
            _row(
                "gap_seconds",
                DIMENSION_SOURCE,
                source,
                item["gap_seconds"],
                "seconds",
                publishable=True,
                coverage_ratio=item["coverage_ratio"],
            )
        )

    return sort_rows(TABLES[TABLE_DAILY_METRICS], rows)


def _values_of(rows: list[dict]) -> str:
    """Canonical form of what a partition asserts, ignoring build metadata."""
    return json.dumps(
        [
            {
                key: row[key]
                for key in (
                    "metric_uid",
                    "value",
                    "publishable",
                    "coverage_ratio",
                    "tuning_fingerprint",
                )
            }
            for row in sorted(rows, key=lambda item: item["metric_uid"])
        ],
        sort_keys=True,
    )


def write_daily_metrics(
    rows: list[dict],
    day: date,
    aggregates_root: Path,
    *,
    reason: str | None = None,
) -> dict:
    """Write one day's metrics, bumping the revision only if the values changed.

    Rewriting an aggregate is allowed — it is derived. Rewriting it *without a
    trace* is not, so an unchanged rebuild keeps its revision and a changed one
    announces itself.
    """
    path = daily_metrics_path(aggregates_root, day)
    revision = 1
    if path.exists():
        existing = read_parquet(path)
        if _values_of(existing) == _values_of(rows):
            return {
                "path": str(path),
                "rows": len(existing),
                "aggregate_revision": existing[0]["aggregate_revision"]
                if existing
                else 1,
                "changed": False,
            }
        revision = int(max(row["aggregate_revision"] for row in existing)) + 1

    stamped = [{**row, "aggregate_revision": revision} for row in rows]
    write_parquet(TABLE_DAILY_METRICS, stamped, path)
    return {
        "path": str(path),
        "rows": len(stamped),
        "aggregate_revision": revision,
        "changed": True,
        "reason": reason,
    }


def site_projection(
    summaries: list[tuple[str, dict]],
    accountings: dict[str, dict] | None = None,
) -> dict:
    """The small JSON the dashboard reads.

    Keeps the null-versus-zero distinction intact: a day nobody watched is
    ``null`` with a coverage figure explaining why, never a flat zero.

    ``accountings`` adds the rate — outage time against the population it
    belongs to — per local date. Without a population for a window the day
    still publishes its absolute figures and says why there is no rate, rather
    than omitting the question.
    """
    accountings = accountings or {}
    days = []
    for local_date, summary in summaries:
        account = accountings.get(local_date)
        days.append(
            {
                "date": local_date,
                "rate": account,
                "window_hours": summary["window_hours"],
                "publishable": summary["publishable"],
                "total_outage_hours": summary["total_outage_hours"],
                "total_outage_hours_min": summary["total_outage_hours_min"],
                "total_outage_hours_max": summary["total_outage_hours_max"],
                "episode_count": summary["episode_count"],
                "episodes_with_unobserved_time": summary[
                    "episodes_with_unobserved_time"
                ],
                "unobserved_outage_hours": summary["unobserved_outage_hours"],
                "quarantined_flapping_episodes": summary["data_quality"][
                    "quarantined_flapping_episodes"
                ],
                "coverage": {
                    source: round(item["coverage_ratio"], 4)
                    for source, item in summary["coverage"].items()
                },
            }
        )

    published = [day for day in days if day["publishable"]]

    # Station totals across the whole span, from the published days only: a day
    # we could not measure must not quietly lower a station's total.
    station_hours: dict[str, float] = {}
    station_names: dict[str, str] = {}
    for _, summary in summaries:
        if not summary["publishable"]:
            continue
        for station, hours in (summary["outage_hours_by_station"] or {}).items():
            station_hours[station] = station_hours.get(station, 0.0) + hours
        station_names.update(summary.get("station_names") or {})

    stations = sorted(
        (
            {
                "station_id": station,
                "station_name": station_names.get(station, station),
                "outage_hours": round(hours, 2),
            }
            for station, hours in station_hours.items()
        ),
        key=lambda item: item["outage_hours"],
        reverse=True,
    )

    # A rate object that only carries a status is not a denominator. Counting
    # it as one would overstate exactly the quantity this layer exists to keep
    # honest.
    rated = [
        day
        for day in days
        if (day.get("rate") or {}).get("denominator_hours")
    ]
    return {
        "unit": UNIT,
        "generated_from": "data/events",
        "rate_unit": "share_of_frame_elevator_station_service_hours",
        "days_with_a_denominator": len(rated),
        "rate_note": (
            "the floor is what was positively observed and no amount of "
            "blindness makes it false; the ceiling is what the unobserved "
            "station-time could hide"
        ),
        "note": (
            "null means the window was not watched well enough to support a "
            "number; it does not mean zero"
        ),
        "days": days,
        "days_published": len(published),
        "days_withheld": len(days) - len(published),
        "stations": stations,
        "stations_note": (
            "totals cover the published days only; days below the coverage "
            "threshold are excluded rather than counted as zero"
        ),
    }
