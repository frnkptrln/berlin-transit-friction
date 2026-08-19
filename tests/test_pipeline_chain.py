"""The operational chain, through the actual command-line entry points.

Unit tests cover the rules; this covers the wiring — that the three scripts
agree on paths, formats and ordering, and that none of them writes into the
repository.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from transit_friction.accessibility.adapter import to_source_snapshot
from transit_friction.accessibility.models import (
    ElevatorOutageObservation,
    OutageSnapshot,
)
from transit_friction.events.detect import detect
from transit_friction.events.store import (
    TABLE_OBSERVATIONS,
    TABLE_TRANSITIONS,
    append_rows,
    staging_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)
DAYS = 4


def _run(script: str, *args: str) -> dict:
    result = subprocess.run(
        ["python", f"scripts/{script}", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    return json.loads(result.stdout)


def _outage(asset: str, at: datetime) -> ElevatorOutageObservation:
    return ElevatorOutageObservation(
        asset_id=asset,
        station_id="900100003",
        station_name="S+U Alexanderplatz",
        status_text="ausser Betrieb",
        source_url=f"https://brokenlifts.org/station/900100003/{asset}",
        source_updated_at=at - timedelta(minutes=2),
        observed_at=at,
    )


@pytest.fixture
def collected(tmp_path) -> Path:
    """Four days of polling: one outage on day 1, a source failure on day 2."""
    raw = tmp_path / "raw"
    states, cursor, pending = {}, None, {}
    for day in range(DAYS):
        for step in range(0, 1440, 30):
            at = START + timedelta(days=day, minutes=step)
            failed = day == 2 and 3 * 60 <= step < 6 * 60
            if failed:
                parsed = OutageSnapshot.failed(
                    source_url="https://brokenlifts.org/",
                    observed_at=at,
                    warning="source fetch failed: 503",
                )
                snapshot = to_source_snapshot(
                    parsed, run_id=f"r{day}-{step}", outcome="http_error"
                )
            else:
                outages = (
                    (_outage("200", at),)
                    if day == 1 and 8 * 60 <= step < 17 * 60
                    else ()
                )
                parsed = OutageSnapshot(
                    source_url="https://brokenlifts.org/",
                    observed_at=at,
                    source_updated_at=at - timedelta(minutes=2),
                    outages=outages,
                    complete=True,
                    advertised_count=len(outages),
                )
                snapshot = to_source_snapshot(parsed, run_id=f"r{day}-{step}")

            result = detect(snapshot, states, cursor, pending)
            states, cursor, pending = result.states, result.cursor, result.pending
            append_rows(
                staging_path(raw, TABLE_OBSERVATIONS, at.date()),
                [result.observation.to_dict()],
            )
            for row in result.transitions:
                append_rows(
                    staging_path(raw, TABLE_TRANSITIONS, row.t_latest.date()),
                    [row.to_dict()],
                )
    return tmp_path


def _seal(root: Path, *extra: str) -> dict:
    return _run(
        "seal_events.py",
        "--events-root", str(root / "events"),
        "--manifest-root", str(root / "_manifests"),
        "--raw-root", str(root / "raw"),
        *extra,
    )


def _aggregate(root: Path, *extra: str) -> dict:
    return _run(
        "build_aggregates.py",
        "--events-root", str(root / "events"),
        "--raw-root", str(root / "raw"),
        "--aggregates-root", str(root / "aggregates"),
        "--site-root", str(root / "site"),
        "--until", "2026-08-14",
        "--days", "3",
        *extra,
    )


def test_the_chain_runs_end_to_end(collected):
    sealed = _seal(collected)
    tables = {item["table"] for item in sealed["sealed"]}
    assert tables == {"transitions", "observations"}
    assert not list((collected / "raw" / "staging").glob("*.jsonl")), (
        "every buffer that existed was consumed"
    )
    empty = [item for item in sealed["sealed"] if item["rows"] == 0]
    assert empty, "days on which nothing changed still get a partition"

    aggregated = _aggregate(collected)
    assert aggregated["sources"] == ["brokenlifts"]
    # The day with the three-hour source failure falls below the coverage
    # threshold and is withheld rather than reported as a calm day.
    assert aggregated["days_published"] == 2
    assert aggregated["days_withheld"] == 1

    checked = subprocess.run(
        [
            "python", "scripts/check_retention.py",
            "--events-root", str(collected / "events"),
            "--manifest-root", str(collected / "_manifests"),
            "--raw-root", str(collected / "raw"),
            "--aggregates-root", str(collected / "aggregates"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stdout


def test_the_measured_outage_matches_what_was_collected(collected):
    _seal(collected)
    _aggregate(collected)
    projection = json.loads(
        (collected / "site" / "accessibility-daily.json").read_text(encoding="utf-8")
    )
    by_date = {day["date"]: day for day in projection["days"]}

    # The outage ran 08:00-17:00 UTC on 2026-08-13, which is 09:00-18:00 Berlin.
    assert by_date["2026-08-13"]["total_outage_hours"] == pytest.approx(9.0, abs=0.6)
    assert by_date["2026-08-12"]["total_outage_hours"] == 0
    assert by_date["2026-08-12"]["episode_count"] == 0


def test_a_source_failure_shows_up_as_coverage_not_as_calm(collected):
    _seal(collected)
    _aggregate(collected)
    projection = json.loads(
        (collected / "site" / "accessibility-daily.json").read_text(encoding="utf-8")
    )
    by_date = {day["date"]: day for day in projection["days"]}
    withheld = by_date["2026-08-14"]
    assert withheld["coverage"]["brokenlifts"] < 0.9
    assert withheld["publishable"] is False
    assert withheld["total_outage_hours"] is None, (
        "a three-hour blind spot must not be published as a quiet day"
    )
    assert "does not mean zero" in projection["note"]


def test_sealing_is_idempotent_through_the_cli(collected):
    first = _seal(collected)
    second = _seal(collected)
    assert first["sealed"]
    assert second["sealed"] == [], "the buffers are gone; nothing is left to seal"


def test_a_tampered_partition_stops_the_chain(collected):
    _seal(collected)
    victim = next((collected / "events" / "transitions").glob("date=*/*.parquet"))
    victim.write_bytes(victim.read_bytes() + b"\x00")

    result = subprocess.run(
        [
            "python", "scripts/seal_events.py",
            "--events-root", str(collected / "events"),
            "--manifest-root", str(collected / "_manifests"),
            "--raw-root", str(collected / "raw"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "does not match its manifest" in result.stderr


def test_the_chain_writes_nothing_into_the_repository(collected):
    before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    _seal(collected)
    _aggregate(collected)
    after = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert before == after
