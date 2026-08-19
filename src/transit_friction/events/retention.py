"""The retention policy as executable checks.

``RETENTION.md`` lists seven enforcement rules. A policy that is only written
down is the policy the legacy pipeline had, so each rule is a function here and
the CLI fails the build when any of them does.

Every check returns problems rather than raising, so one run reports everything
wrong at once instead of the first thing it tripped over.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .maintenance import verify_partitions
from .store import TABLES, read_parquet

#: RETENTION.md: the raw layer is ephemeral and never committed.
RAW_RETENTION_DAYS = 7

#: docs/decisions/0001 section 5: the triggers that reopen the hosting decision.
MAX_EVENTS_BYTES = 250 * 1024 * 1024
MAX_DAILY_PARTITION_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    problems: tuple[str, ...]
    skipped: str | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


def _git(args: list[str], repo: Path) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def check_raw_never_staged(repo: Path, raw_dir_name: str = ".raw") -> CheckResult:
    """Rule 1: no path under the raw layer may be staged, ever."""
    result = _git(["diff", "--cached", "--name-only"], repo)
    if result is None or result.returncode != 0:
        return CheckResult("raw_never_staged", (), skipped="not a git checkout")
    staged = [line for line in result.stdout.splitlines() if line.strip()]
    offenders = [
        path
        for path in staged
        if path.startswith(f"{raw_dir_name}/") or f"/{raw_dir_name}/" in path
    ]
    return CheckResult(
        "raw_never_staged",
        tuple(f"{path} is in the ephemeral raw layer and must not be committed"
              for path in offenders),
    )


def check_raw_expired(raw_root: Path, *, now: datetime | None = None) -> CheckResult:
    """Rule 2: raw files older than the retention window must be gone."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RAW_RETENTION_DAYS)
    if not raw_root.exists():
        return CheckResult("raw_expired", ())
    problems = []
    for path in raw_root.rglob("*"):
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified < cutoff:
            problems.append(
                f"{path} is {(now - modified).days} days old; the raw layer keeps "
                f"{RAW_RETENTION_DAYS}"
            )
    return CheckResult("raw_expired", tuple(problems))


def check_manifests(events_root: Path, manifest_root: Path) -> CheckResult:
    """Rule 3: every partition has a manifest whose hash still matches."""
    return CheckResult("manifests_match", tuple(verify_partitions(events_root, manifest_root)))


def check_sealed_not_modified(repo: Path, events_dir: str = "data/events") -> CheckResult:
    """Rule 4: a diff touching an existing events file fails; additions only."""
    result = _git(
        ["diff", "--cached", "--name-status", "--", events_dir], repo
    )
    if result is None or result.returncode != 0:
        return CheckResult("sealed_not_modified", (), skipped="not a git checkout")
    problems = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        if status.startswith("A"):
            continue
        if status.startswith("D") and "/date=" in path:
            # Rollup removes daily partitions, which is the one permitted
            # deletion; the rollup manifest keeps their fingerprints.
            continue
        problems.append(
            f"{path} is {status}, but sealed events are append-only; a "
            f"correction is a new row, never a rewrite"
        )
    return CheckResult("sealed_not_modified", tuple(problems))


def check_uid_uniqueness(events_root: Path) -> CheckResult:
    """Rule 5: uids are unique within and across partitions."""
    problems = []
    for table, spec in TABLES.items():
        root = events_root / table
        if not root.exists():
            continue
        seen: dict[str, str] = {}
        for child in sorted(root.iterdir()):
            parquet = child / f"{table}.parquet"
            if not child.is_dir() or not parquet.exists():
                continue
            for row in read_parquet(parquet):
                uid = row[spec.uid_field]
                if uid in seen:
                    problems.append(
                        f"{table}: {uid} appears in both {seen[uid]} and {child.name}"
                    )
                    continue
                seen[uid] = child.name
    return CheckResult("uid_uniqueness", tuple(problems))


def check_no_value_without_coverage(aggregates_root: Path) -> CheckResult:
    """Rule 6: no number is published for a window that was not watched."""
    problems = []
    daily = aggregates_root / "daily"
    if not daily.exists():
        return CheckResult("no_value_without_coverage", ())
    for child in sorted(daily.iterdir()):
        path = child / "metrics.parquet"
        if not child.is_dir() or not path.exists():
            continue
        for row in read_parquet(path):
            if row["value"] is not None and not row["publishable"]:
                problems.append(
                    f"{child.name}: {row['metric']} carries a value although the "
                    f"window is below the coverage threshold"
                )
    return CheckResult("no_value_without_coverage", tuple(problems))


def _tree_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def check_size_budgets(events_root: Path) -> CheckResult:
    """Rule 7: growth fails a build instead of accumulating for 66 days."""
    problems = []
    total = _tree_bytes(events_root)
    if total > MAX_EVENTS_BYTES:
        problems.append(
            f"data/events is {total / 1024 / 1024:.1f} MB, past the "
            f"{MAX_EVENTS_BYTES / 1024 / 1024:.0f} MB trigger in "
            f"docs/decisions/0001; reopen the hosting decision"
        )
    for table in TABLES:
        root = events_root / table
        if not root.exists():
            continue
        for child in root.glob("date=*"):
            parquet = child / f"{table}.parquet"
            if parquet.exists() and parquet.stat().st_size > MAX_DAILY_PARTITION_BYTES:
                problems.append(
                    f"{parquet} is {parquet.stat().st_size / 1024 / 1024:.1f} MB, "
                    f"past the 5 MB per-day trigger"
                )
    return CheckResult("size_budgets", tuple(problems))


def run_all(
    *,
    repo: Path,
    events_root: Path,
    manifest_root: Path,
    raw_root: Path,
    aggregates_root: Path,
    now: datetime | None = None,
) -> list[CheckResult]:
    return [
        check_raw_never_staged(repo),
        check_raw_expired(raw_root, now=now),
        check_manifests(events_root, manifest_root),
        check_sealed_not_modified(repo),
        check_uid_uniqueness(events_root),
        check_no_value_without_coverage(aggregates_root),
        check_size_budgets(events_root),
    ]
