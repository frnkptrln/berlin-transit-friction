"""Append-only in practice: seal once, verify, roll up, never rewrite."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from conftest import Harness, at, lift

from transit_friction.events import store
from transit_friction.events.store import SealError

L1 = lift()
DAY = date(2026, 8, 19)


@pytest.fixture
def roots(tmp_path):
    return {
        "raw_root": tmp_path / "raw",
        "events_root": tmp_path / "events",
        "manifest_root": tmp_path / "_manifests",
    }


def _history() -> Harness:
    """One outage, opened at the poll at 5 and closed from the poll at 60.

    Polled densely so that no coverage gap is involved: the gap behaviour has
    its own tests, and here we only care about storage.
    """
    harness = Harness()
    for step in range(0, 75, 5):
        harness.poll(step, [L1] if 5 <= step < 60 else [])
    return harness


def _rows(harness: Harness, table: str) -> list[dict]:
    if table == store.TABLE_TRANSITIONS:
        return [row.to_dict() for row in harness.transitions]
    return [row.to_dict() for row in harness.observations]


# --- staging ----------------------------------------------------------------


def test_staging_appends_without_rewriting(roots):
    path = store.staging_path(roots["raw_root"], "transitions", DAY)
    harness = _history()
    rows = _rows(harness, store.TABLE_TRANSITIONS)
    store.append_rows(path, rows[:1])
    first_size = path.stat().st_size
    store.append_rows(path, rows[1:])
    assert path.stat().st_size > first_size
    assert len(store.read_jsonl(path)) == len(rows)


# --- sealing ----------------------------------------------------------------


def test_seal_writes_a_manifest_with_a_content_hash(roots):
    rows = _rows(_history(), store.TABLE_TRANSITIONS)
    manifest = store.seal_day("transitions", DAY, rows=rows, **roots)
    assert manifest["row_count"] == len(rows)
    assert len(manifest["content_sha256"]) == 64
    assert len(manifest["file_sha256"]) == 64
    assert manifest["distinct_entities"] == 1
    assert store.daily_path(roots["events_root"], "transitions", DAY).exists()


def test_seal_is_idempotent(roots):
    rows = _rows(_history(), store.TABLE_TRANSITIONS)
    first = store.seal_day("transitions", DAY, rows=rows, **roots)
    second = store.seal_day("transitions", DAY, rows=rows, **roots)
    assert first["content_sha256"] == second["content_sha256"]


def test_seal_refuses_to_replace_a_sealed_partition(roots):
    harness = _history()
    rows = _rows(harness, store.TABLE_TRANSITIONS)
    store.seal_day("transitions", DAY, rows=rows, **roots)
    with pytest.raises(SealError, match="already sealed"):
        store.seal_day("transitions", DAY, rows=rows[:1], **roots)


def test_seal_deduplicates_replayed_rows(roots):
    rows = _rows(_history(), store.TABLE_TRANSITIONS)
    manifest = store.seal_day("transitions", DAY, rows=rows * 3, **roots)
    assert manifest["row_count"] == len(rows)


def test_seal_rejects_an_invalid_row_instead_of_dropping_it(roots):
    rows = _rows(_history(), store.TABLE_TRANSITIONS)
    rows[-1]["evidence"] = "source_degraded"  # a close that cannot be justified
    with pytest.raises(SealError, match="is invalid"):
        store.seal_day("transitions", DAY, rows=rows, **roots)


def test_seal_rejects_a_row_from_another_day(roots):
    rows = _rows(_history(), store.TABLE_TRANSITIONS)
    with pytest.raises(SealError, match="belongs to"):
        store.seal_day("transitions", DAY + timedelta(days=1), rows=rows, **roots)


def test_an_empty_day_is_still_sealed(roots):
    """A missing partition means "we do not know"; an empty one means "nothing changed"."""
    manifest = store.seal_day("transitions", DAY, rows=[], **roots)
    assert manifest["row_count"] == 0
    assert store.daily_path(roots["events_root"], "transitions", DAY).exists()


def test_sealed_rows_survive_the_round_trip(roots):
    harness = _history()
    store.seal_day(
        "transitions", DAY, rows=_rows(harness, store.TABLE_TRANSITIONS), **roots
    )
    restored = store.load_transitions(roots["events_root"])
    assert sorted(row.transition_type for row in restored) == sorted(harness.types)
    assert sorted(row.bracket_seconds for row in restored) == sorted(
        row.bracket_seconds for row in harness.transitions
    )
    by_uid = {row.transition_uid: row for row in restored}
    for original in harness.transitions:
        assert by_uid[original.transition_uid].quality_flags == original.quality_flags
        assert by_uid[original.transition_uid].recorded_at == original.recorded_at


def test_observations_round_trip_too(roots):
    harness = _history()
    store.seal_day(
        "observations", DAY, rows=_rows(harness, store.TABLE_OBSERVATIONS), **roots
    )
    restored = store.load_observations(roots["events_root"])
    assert len(restored) == len(harness.observations)
    assert [row.outcome for row in restored] == [
        row.outcome for row in harness.observations
    ]
    assert restored[0].trusted_for_resolution is True


# --- rollup -----------------------------------------------------------------


def _seal_three_days(roots) -> list[date]:
    days = []
    for offset in range(3):
        day = date(2026, 6, 1) + timedelta(days=offset)
        harness = Harness()
        harness.poll(0, [])
        harness.poll(5, [L1])
        rows = []
        for row in harness.transitions:
            payload = row.to_dict()
            shift = timedelta(days=(day - date(2026, 8, 19)).days)
            payload["t_earliest"] = (row.t_earliest + shift).isoformat()
            payload["t_latest"] = (row.t_latest + shift).isoformat()
            payload["transition_uid"] = f"{row.transition_uid}-{offset}"
            rows.append(payload)
        store.seal_day("transitions", day, rows=rows, **roots)
        days.append(day)
    return days


def test_rollup_merges_and_records_what_it_absorbed(roots):
    days = _seal_three_days(roots)
    manifest = store.rollup_month("transitions", "2026-06", **{
        k: v for k, v in roots.items() if k != "raw_root"
    })
    assert manifest["row_count"] == 3
    assert len(manifest["absorbed"]) == 3
    for entry, day in zip(manifest["absorbed"], days):
        assert entry["partition"] == f"date={day.isoformat()}"
        assert len(entry["file_sha256"]) == 64


def test_rollup_removes_the_dailies_but_not_their_fingerprints(roots):
    days = _seal_three_days(roots)
    manifest = store.rollup_month("transitions", "2026-06", **{
        k: v for k, v in roots.items() if k != "raw_root"
    })
    for day in days:
        assert not store.daily_path(roots["events_root"], "transitions", day).exists()
    assert store.monthly_path(roots["events_root"], "transitions", "2026-06").exists()
    assert all(entry["content_sha256"] for entry in manifest["absorbed"])


def test_rollup_refuses_a_tampered_partition(roots):
    days = _seal_three_days(roots)
    victim = store.daily_path(roots["events_root"], "transitions", days[1])
    victim.write_bytes(victim.read_bytes() + b"\x00")
    with pytest.raises(SealError, match="no longer matches its seal manifest"):
        store.rollup_month("transitions", "2026-06", **{
            k: v for k, v in roots.items() if k != "raw_root"
        })


def test_rollup_refuses_without_a_manifest(roots):
    days = _seal_three_days(roots)
    store.seal_manifest_path(roots["manifest_root"], "transitions", days[0]).unlink()
    with pytest.raises(SealError, match="missing seal manifest"):
        store.rollup_month("transitions", "2026-06", **{
            k: v for k, v in roots.items() if k != "raw_root"
        })


def test_reading_after_rollup_does_not_double_count(roots):
    _seal_three_days(roots)
    before = len(store.load_transitions(roots["events_root"]))
    store.rollup_month("transitions", "2026-06", **{
        k: v for k, v in roots.items() if k != "raw_root"
    })
    assert len(store.load_transitions(roots["events_root"])) == before


def test_rollup_is_idempotent(roots):
    _seal_three_days(roots)
    kwargs = {k: v for k, v in roots.items() if k != "raw_root"}
    first = store.rollup_month("transitions", "2026-06", **kwargs)
    second = store.rollup_month("transitions", "2026-06", **kwargs)
    assert first["content_sha256"] == second["content_sha256"]


def test_rollup_needs_something_to_roll_up(roots):
    with pytest.raises(SealError, match="no sealed daily partitions"):
        store.rollup_month("transitions", "2026-06", **{
            k: v for k, v in roots.items() if k != "raw_root"
        })


# --- reading ----------------------------------------------------------------


def test_reading_can_be_bounded_by_time(roots):
    harness = _history()
    store.seal_day(
        "transitions", DAY, rows=_rows(harness, store.TABLE_TRANSITIONS), **roots
    )
    rows = store.read_table(
        "transitions", roots["events_root"], start=at(0), end=at(30)
    )
    assert len(rows) == 1
    assert rows[0]["transition_type"] == "opened"


def test_manifest_records_the_tuning_that_produced_the_partition(roots):
    rows = _rows(_history(), store.TABLE_TRANSITIONS)
    store.seal_day("transitions", DAY, rows=rows, **roots)
    manifest = json.loads(
        store.seal_manifest_path(roots["manifest_root"], "transitions", DAY).read_text()
    )
    assert len(manifest["tuning_fingerprint"]) == 16
    assert manifest["schema_version"] == 1
