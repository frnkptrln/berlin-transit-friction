"""When a partition may be frozen, and when it may not."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from conftest import Harness, lift

from transit_friction.events import store
from transit_friction.events.maintenance import (
    collected_days,
    rollup_pending,
    rollupable_months,
    seal_pending,
    verify_partitions,
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


def _buffer(roots, table: str, day: date, rows: list[dict]) -> None:
    store.append_rows(store.staging_path(roots["raw_root"], table, day), rows)


def _history() -> Harness:
    harness = Harness()
    for step in range(0, 75, 5):
        harness.poll(step, [L1] if 5 <= step < 60 else [])
    return harness


def test_the_day_being_collected_is_never_sealed(roots):
    harness = _history()
    _buffer(roots, "observations", DAY, [r.to_dict() for r in harness.observations])
    outcomes = seal_pending(
        now=datetime(2026, 8, 19, 12, tzinfo=timezone.utc), **roots
    )
    assert outcomes == [], "rows for today are still arriving"


def test_a_closed_day_is_sealed_after_the_grace_period(roots):
    harness = _history()
    _buffer(roots, "observations", DAY, [r.to_dict() for r in harness.observations])
    _buffer(roots, "transitions", DAY, [r.to_dict() for r in harness.transitions])

    early = seal_pending(now=datetime(2026, 8, 20, 1, tzinfo=timezone.utc), **roots)
    assert early == [], "a run that started before midnight may still be finishing"

    outcomes = seal_pending(
        now=datetime(2026, 8, 20, 4, tzinfo=timezone.utc), **roots
    )
    assert {outcome.table for outcome in outcomes} == {"transitions", "observations"}
    assert all(outcome.staging_removed for outcome in outcomes)


def test_a_day_with_no_transitions_still_gets_a_partition(roots):
    """A missing partition means "we do not know"; an empty one means "nothing changed"."""
    harness = Harness()
    for step in range(0, 60, 5):
        harness.poll(step, [])
    _buffer(roots, "observations", DAY, [r.to_dict() for r in harness.observations])
    assert harness.transitions == []
    assert collected_days(roots["raw_root"]) == [DAY]

    seal_pending(now=datetime(2026, 8, 20, 4, tzinfo=timezone.utc), **roots)
    path = store.daily_path(roots["events_root"], "transitions", DAY)
    assert path.exists()
    assert store.read_parquet(path) == []


def test_sealing_twice_is_a_no_op(roots):
    harness = _history()
    _buffer(roots, "transitions", DAY, [r.to_dict() for r in harness.transitions])
    now = datetime(2026, 8, 20, 4, tzinfo=timezone.utc)
    first = seal_pending(now=now, **roots)
    second = seal_pending(now=now, **roots)
    assert first
    assert second == [], "the buffer is gone, so there is nothing left to seal"


def test_verification_catches_a_tampered_partition(roots):
    harness = _history()
    _buffer(roots, "transitions", DAY, [r.to_dict() for r in harness.transitions])
    seal_pending(now=datetime(2026, 8, 20, 4, tzinfo=timezone.utc), **roots)
    assert verify_partitions(roots["events_root"], roots["manifest_root"]) == []

    victim = store.daily_path(roots["events_root"], "transitions", DAY)
    victim.write_bytes(victim.read_bytes() + b"\x00")
    problems = verify_partitions(roots["events_root"], roots["manifest_root"])
    assert len(problems) == 1
    assert "does not match its manifest" in problems[0]


# --- rollup eligibility -----------------------------------------------------


def _seal_a_month(roots, days: list[date]) -> None:
    for day in days:
        rows = [
            {
                **row.to_dict(),
                "transition_uid": f"{row.transition_uid}-{day.isoformat()}",
                "t_earliest": datetime.combine(
                    day, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
                "t_latest": datetime.combine(
                    day, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
                "recorded_at": datetime.combine(
                    day, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat(),
            }
            for row in _history().transitions
        ]
        store.seal_day("transitions", day, rows=rows, **roots)


def test_a_recent_month_is_not_rolled_up(roots):
    days = [date(2026, 8, 1), date(2026, 8, 2)]
    _seal_a_month(roots, days)
    eligible = rollupable_months(
        roots["events_root"],
        roots["manifest_root"],
        roots["raw_root"],
        "transitions",
        now=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    assert eligible == []


def test_an_old_complete_month_is_rolled_up(roots):
    days = [date(2026, 6, 1), date(2026, 6, 2)]
    _seal_a_month(roots, days)
    manifests = rollup_pending(
        now=datetime(2026, 8, 20, tzinfo=timezone.utc),
        tables=("transitions",),
        **roots,
    )
    assert [item["partition"] for item in manifests] == ["month=2026-06"]
    assert store.monthly_path(roots["events_root"], "transitions", "2026-06").exists()


def test_a_month_with_an_open_buffer_is_not_rolled_up(roots):
    """Merging while a day is still unsealed would silently lose it."""
    days = [date(2026, 6, 1), date(2026, 6, 2)]
    _seal_a_month(roots, days)
    _buffer(roots, "transitions", date(2026, 6, 3), [])
    store.append_rows(
        store.staging_path(roots["raw_root"], "transitions", date(2026, 6, 3)),
        [{"placeholder": True}],
    )
    eligible = rollupable_months(
        roots["events_root"],
        roots["manifest_root"],
        roots["raw_root"],
        "transitions",
        now=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    assert eligible == []


def test_an_already_rolled_up_month_is_left_alone(roots):
    days = [date(2026, 6, 1), date(2026, 6, 2)]
    _seal_a_month(roots, days)
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    rollup_pending(now=now, tables=("transitions",), **roots)
    again = rollup_pending(now=now, tables=("transitions",), **roots)
    assert again == []
