"""The retention policy, as checks that fail a build."""

from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import Harness, lift

from transit_friction.events import store
from transit_friction.events.retention import (
    MAX_DAILY_PARTITION_BYTES,
    check_manifests,
    check_no_value_without_coverage,
    check_raw_expired,
    check_raw_never_staged,
    check_sealed_not_modified,
    check_size_budgets,
    check_uid_uniqueness,
    run_all,
)

L1 = lift()
DAY = date(2026, 8, 19)


@pytest.fixture
def roots(tmp_path):
    return {
        "raw_root": tmp_path / "raw",
        "events_root": tmp_path / "events",
        "manifest_root": tmp_path / "_manifests",
    }


def _seal(roots, day: date = DAY):
    harness = Harness()
    for step in range(0, 75, 5):
        harness.poll(step, [L1] if 5 <= step < 60 else [])
    store.seal_day(
        "transitions", day, rows=[row.to_dict() for row in harness.transitions], **roots
    )


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    return tmp_path


# --- rule 1: the raw layer is never committed -------------------------------


def test_a_staged_raw_file_fails(tmp_path):
    repo = _repo(tmp_path)
    raw = repo / ".raw" / "staging"
    raw.mkdir(parents=True)
    (raw / "transitions-2026-08-19.jsonl").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".raw"], cwd=repo, check=True)

    result = check_raw_never_staged(repo)
    assert not result.ok
    assert "must not be committed" in result.problems[0]


def test_a_clean_index_passes(tmp_path):
    assert check_raw_never_staged(_repo(tmp_path)).ok


def test_the_check_is_skipped_outside_a_checkout(tmp_path):
    result = check_raw_never_staged(tmp_path / "nowhere")
    assert result.skipped or result.ok


# --- rule 2: seven days ------------------------------------------------------


def test_an_expired_raw_file_fails(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    stale = raw / "old.jsonl"
    stale.write_text("{}\n", encoding="utf-8")
    old = (datetime.now(timezone.utc) - timedelta(days=9)).timestamp()
    import os

    os.utime(stale, (old, old))

    result = check_raw_expired(raw)
    assert not result.ok
    assert "the raw layer keeps 7" in result.problems[0]


def test_a_fresh_raw_file_passes(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "today.jsonl").write_text("{}\n", encoding="utf-8")
    assert check_raw_expired(raw).ok


# --- rules 3 and 5: integrity ------------------------------------------------


def test_a_tampered_partition_fails(roots):
    _seal(roots)
    assert check_manifests(roots["events_root"], roots["manifest_root"]).ok
    victim = store.daily_path(roots["events_root"], "transitions", DAY)
    victim.write_bytes(victim.read_bytes() + b"\x00")
    assert not check_manifests(roots["events_root"], roots["manifest_root"]).ok


def test_a_duplicate_uid_across_partitions_fails(roots):
    _seal(roots, DAY)
    rows = store.read_parquet(store.daily_path(roots["events_root"], "transitions", DAY))
    other = DAY + timedelta(days=1)
    shifted = [
        {
            **row,
            "t_latest": (
                datetime.fromisoformat(row["t_latest"]) + timedelta(days=1)
            ).isoformat(),
            "t_earliest": (
                datetime.fromisoformat(row["t_earliest"]) + timedelta(days=1)
            ).isoformat(),
            "recorded_at": (
                datetime.fromisoformat(row["recorded_at"]) + timedelta(days=1)
            ).isoformat(),
        }
        for row in rows
    ]
    store.seal_day("transitions", other, rows=shifted, **roots)

    result = check_uid_uniqueness(roots["events_root"])
    assert not result.ok
    assert "appears in both" in result.problems[0]


def test_distinct_partitions_pass(roots):
    _seal(roots)
    assert check_uid_uniqueness(roots["events_root"]).ok


# --- rule 4: append only -----------------------------------------------------


def test_modifying_a_sealed_partition_fails(tmp_path):
    repo = _repo(tmp_path)
    events = repo / "data" / "events" / "transitions" / "date=2026-08-19"
    events.mkdir(parents=True)
    target = events / "transitions.parquet"
    target.write_bytes(b"one")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seal"], cwd=repo, check=True)

    target.write_bytes(b"two")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    result = check_sealed_not_modified(repo)
    assert not result.ok
    assert "append-only" in result.problems[0]


def test_adding_a_partition_passes(tmp_path):
    repo = _repo(tmp_path)
    events = repo / "data" / "events" / "transitions" / "date=2026-08-19"
    events.mkdir(parents=True)
    (events / "transitions.parquet").write_bytes(b"one")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    assert check_sealed_not_modified(repo).ok


def test_rollup_may_remove_a_daily_partition(tmp_path):
    repo = _repo(tmp_path)
    events = repo / "data" / "events" / "transitions" / "date=2026-06-01"
    events.mkdir(parents=True)
    (events / "transitions.parquet").write_bytes(b"one")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seal"], cwd=repo, check=True)

    (events / "transitions.parquet").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    assert check_sealed_not_modified(repo).ok, (
        "rollup is the one permitted deletion; the manifest keeps the hashes"
    )


# --- rule 6: no number without coverage --------------------------------------


def test_a_value_published_without_coverage_fails(tmp_path):
    partition = tmp_path / "daily" / "date=2026-08-19"
    partition.mkdir(parents=True)
    rows = [
        {
            "metric_uid": "a",
            "schema_version": 1,
            "local_date": "2026-08-19",
            "window_start": "2026-08-18T22:00:00+00:00",
            "window_end": "2026-08-19T22:00:00+00:00",
            "window_hours": 24.0,
            "metric": "total_outage_hours",
            "dimension": "all",
            "dimension_id": "",
            "value": 3.0,
            "unit": "outage-hours",
            "publishable": False,
            "coverage_ratio": 0.2,
            "aggregate_revision": 1,
            "tuning_fingerprint": "abc",
            "built_at": None,
        }
    ]
    store.write_parquet("daily_metrics", rows, partition / "metrics.parquet")

    result = check_no_value_without_coverage(tmp_path)
    assert not result.ok
    assert "below the coverage threshold" in result.problems[0]


def test_no_aggregates_yet_passes(tmp_path):
    assert check_no_value_without_coverage(tmp_path).ok


# --- rule 7: budgets ---------------------------------------------------------


def test_an_oversized_daily_partition_fails(roots, monkeypatch):
    _seal(roots)
    monkeypatch.setattr(
        "transit_friction.events.retention.MAX_DAILY_PARTITION_BYTES", 10
    )
    result = check_size_budgets(roots["events_root"])
    assert not result.ok
    assert "per-day trigger" in result.problems[0]


def test_a_small_tree_passes(roots):
    _seal(roots)
    assert check_size_budgets(roots["events_root"]).ok
    assert MAX_DAILY_PARTITION_BYTES > 0


# --- the whole set -----------------------------------------------------------


def test_a_healthy_tree_passes_every_check(tmp_path):
    repo = _repo(tmp_path)
    roots = {
        "raw_root": repo / ".raw",
        "events_root": repo / "data" / "events",
        "manifest_root": repo / "data" / "_manifests",
    }
    _seal(roots)
    results = run_all(
        repo=repo,
        aggregates_root=repo / "data" / "aggregates",
        **roots,
    )
    assert len(results) == 7
    assert all(result.ok for result in results), [
        (result.name, result.problems) for result in results if not result.ok
    ]
