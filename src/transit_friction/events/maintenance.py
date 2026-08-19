"""Sealing and rollup as scheduled operations.

The rules that decide *when* a partition may be sealed or rolled up live here
rather than in a workflow file, so they can be tested without a runner and
cannot quietly differ between the shadow period and production.

Two refusals matter:

* the day currently being collected is never sealed, because rows for it are
  still arriving;
* a month is never rolled up while any of its days is unsealed or still has an
  open buffer, because the merge would silently lose them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .config import DEFAULT_TUNING, TuningParameters
from .store import (
    TABLES,
    daily_path,
    list_daily_partitions,
    monthly_path,
    read_jsonl,
    rollup_manifest_path,
    rollup_month,
    seal_day,
    seal_manifest_path,
    staging_path,
)

#: Hours after midnight UTC before a day may be sealed. A run that starts at
#: 23:58 and finishes at 00:01 must land in the right partition first.
SEAL_GRACE_HOURS = 3

#: A month is rolled up once its newest day is this old.
ROLLUP_AFTER_DAYS = 30


@dataclass(frozen=True, slots=True)
class SealOutcome:
    table: str
    day: date
    row_count: int
    content_sha256: str
    staging_removed: bool


def staging_days(raw_root: Path, table: str) -> list[date]:
    directory = raw_root / "staging"
    if not directory.exists():
        return []
    days: list[date] = []
    for path in sorted(directory.glob(f"{table}-*.jsonl")):
        try:
            days.append(date.fromisoformat(path.stem.removeprefix(f"{table}-")))
        except ValueError:
            continue
    return sorted(days)


def collected_days(
    raw_root: Path,
    tables: tuple[str, ...] = tuple(TABLES),
) -> list[date]:
    """Every day any table buffered something.

    Taken across tables on purpose. A day on which we polled but nothing changed
    has an observations buffer and no transitions buffer, and it must still get
    an empty transitions partition: a missing partition means "we do not know",
    while an empty one means "we looked and nothing changed". Those are
    different claims and the archive has to be able to make both.
    """
    days: set[date] = set()
    for table in tables:
        days.update(staging_days(raw_root, table))
    return sorted(days)


def sealable_days(
    raw_root: Path,
    table: str,
    *,
    now: datetime,
    grace_hours: int = SEAL_GRACE_HOURS,
    tables: tuple[str, ...] = tuple(TABLES),
) -> list[date]:
    """Days whose buffer is closed enough to freeze.

    A day may be sealed once the grace period after its end has elapsed — not
    merely once the calendar has turned over. A collector run that started at
    23:58 and finishes at 00:01 must land in the right partition first.
    """
    return [
        day
        for day in collected_days(raw_root, tables)
        if datetime.combine(day, time.min, tzinfo=timezone.utc)
        + timedelta(days=1, hours=grace_hours)
        <= now.astimezone(timezone.utc)
    ]


def seal_pending(
    *,
    raw_root: Path,
    events_root: Path,
    manifest_root: Path,
    now: datetime | None = None,
    tables: tuple[str, ...] = tuple(TABLES),
    tuning: TuningParameters = DEFAULT_TUNING,
    grace_hours: int = SEAL_GRACE_HOURS,
    dry_run: bool = False,
) -> list[SealOutcome]:
    """Seal every closed day, then discard its buffer.

    The buffer is only removed once the partition and its manifest exist, so a
    crash between the two leaves work to redo rather than data to mourn.
    """
    now = now or datetime.now(timezone.utc)
    outcomes: list[SealOutcome] = []

    for table in tables:
        for day in sealable_days(
            raw_root, table, now=now, grace_hours=grace_hours, tables=tables
        ):
            rows = read_jsonl(staging_path(raw_root, table, day))
            if dry_run:
                outcomes.append(
                    SealOutcome(
                        table=table,
                        day=day,
                        row_count=len(rows),
                        content_sha256="",
                        staging_removed=False,
                    )
                )
                continue

            manifest = seal_day(
                table,
                day,
                raw_root=raw_root,
                events_root=events_root,
                manifest_root=manifest_root,
                tuning=tuning,
                rows=rows,
            )
            removed = False
            buffer_path = staging_path(raw_root, table, day)
            if daily_path(events_root, table, day).exists() and seal_manifest_path(
                manifest_root, table, day
            ).exists():
                removed = buffer_path.exists()
                buffer_path.unlink(missing_ok=True)
            outcomes.append(
                SealOutcome(
                    table=table,
                    day=day,
                    row_count=manifest["row_count"],
                    content_sha256=manifest["content_sha256"],
                    staging_removed=removed,
                )
            )

    return outcomes


def rollupable_months(
    events_root: Path,
    manifest_root: Path,
    raw_root: Path,
    table: str,
    *,
    now: datetime,
    after_days: int = ROLLUP_AFTER_DAYS,
) -> list[str]:
    """Months old enough to merge, and complete enough to merge safely."""
    by_month: dict[str, list[date]] = defaultdict(list)
    for day in list_daily_partitions(events_root, table):
        by_month[day.strftime("%Y-%m")].append(day)

    # Any buffered day in the month blocks it, sealed or not: a day that never
    # got a partition would be silently absent from the merged file, and the
    # monthly manifest would then claim to represent a month it is missing.
    buffered_months = {
        day.strftime("%Y-%m") for day in staging_days(raw_root, table)
    }
    cutoff = now.astimezone(timezone.utc).date() - timedelta(days=after_days)

    eligible: list[str] = []
    for month, days in sorted(by_month.items()):
        if max(days) > cutoff:
            continue
        if month in buffered_months:
            continue
        if not all(
            seal_manifest_path(manifest_root, table, day).exists() for day in days
        ):
            continue
        if monthly_path(events_root, table, month).exists():
            continue
        eligible.append(month)
    return eligible


def rollup_pending(
    *,
    events_root: Path,
    manifest_root: Path,
    raw_root: Path,
    now: datetime | None = None,
    tables: tuple[str, ...] = tuple(TABLES),
    tuning: TuningParameters = DEFAULT_TUNING,
    after_days: int = ROLLUP_AFTER_DAYS,
    dry_run: bool = False,
) -> list[dict]:
    """Merge every eligible month. Aborts on any mismatch rather than proceeding."""
    now = now or datetime.now(timezone.utc)
    manifests: list[dict] = []
    for table in tables:
        for month in rollupable_months(
            events_root, manifest_root, raw_root, table, now=now, after_days=after_days
        ):
            if dry_run:
                manifests.append({"table": table, "partition": f"month={month}"})
                continue
            manifests.append(
                rollup_month(
                    table,
                    month,
                    events_root=events_root,
                    manifest_root=manifest_root,
                    tuning=tuning,
                )
            )
    return manifests


def verify_partitions(
    events_root: Path,
    manifest_root: Path,
    tables: tuple[str, ...] = tuple(TABLES),
) -> list[str]:
    """Check every sealed partition still matches the hash recorded for it.

    Returns the problems found. An empty list is the only acceptable result:
    the append-only claim is only worth what this check says it is.
    """
    from .store import file_hash

    problems: list[str] = []
    for table in tables:
        root = events_root / table
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            parquet = child / f"{table}.parquet"
            if not parquet.exists():
                problems.append(f"{child} has no {table}.parquet")
                continue

            if child.name.startswith("date="):
                day = date.fromisoformat(child.name.removeprefix("date="))
                manifest_file = seal_manifest_path(manifest_root, table, day)
            elif child.name.startswith("month="):
                manifest_file = rollup_manifest_path(
                    manifest_root, table, child.name.removeprefix("month=")
                )
            else:
                problems.append(f"{child} is not a recognised partition")
                continue

            if not manifest_file.exists():
                problems.append(f"{parquet} has no manifest")
                continue
            import json

            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if file_hash(parquet) != manifest["file_sha256"]:
                problems.append(f"{parquet} does not match its manifest hash")
    return problems
