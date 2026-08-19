"""The shadow runner against the real fixture, through the events layer."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from transit_friction.accessibility.shadow import (
    FetchResult,
    ShadowPaths,
    apply_snapshot,
)
from transit_friction.accessibility.parser import parse_brokenlifts_snapshot
from transit_friction.events.state import fold_transitions
from transit_friction.events.store import load_pending, load_recent_transitions

FIXTURE = Path(__file__).parent / "fixtures" / "brokenlifts_homepage.html"
T0 = datetime(2026, 7, 10, 9, 31, tzinfo=timezone.utc)
SOURCE = "brokenlifts"


def paths(tmp_path) -> ShadowPaths:
    return ShadowPaths.under(tmp_path)


def snapshot(html: str, observed_at: datetime):
    return parse_brokenlifts_snapshot(html, observed_at=observed_at)


def run(html: str, at: datetime, shadow_paths: ShadowPaths, **kwargs) -> dict:
    return apply_snapshot(
        FetchResult(snapshot=snapshot(html, at)),
        paths=shadow_paths,
        run_id=f"run-{at.isoformat()}",
        **kwargs,
    )


def states(shadow_paths: ShadowPaths) -> dict:
    return fold_transitions(
        load_recent_transitions(shadow_paths.events_root, shadow_paths.raw_root)
    )


def native_ids(shadow_paths: ShadowPaths, state: str) -> set[str]:
    return {
        entity.source_native_id
        for entity in states(shadow_paths).values()
        if entity.state == state
    }


def cleared_html(html: str, minutes: int = 15) -> str:
    """The fixture with asset 200 no longer flagged, and the page clock moved on."""
    hour, minute = divmod(11 * 60 + 30 + minutes, 60)
    return (
        html.replace(
            "Letzte Aktualisierung am 10.07.2026, 11:30 Uhr",
            f"Letzte Aktualisierung am 10.07.2026, {hour:02d}:{minute:02d} Uhr",
        )
        .replace('class="broken-counter">3<', 'class="broken-counter">2<')
        .replace(
            '<a href="/station/900100003/200" class="lift-link alert">2</a>',
            '<a href="/station/900100003/200" class="lift-link">2</a>',
        )
    )


def test_first_run_opens_every_observed_outage(tmp_path):
    shadow_paths = paths(tmp_path)
    summary = run(FIXTURE.read_text(encoding="utf-8"), T0, shadow_paths)

    assert summary["transitions"] == {"opened": 3}
    assert summary["impaired_after"] == 3
    assert summary["trusted_for_resolution"] is True
    assert native_ids(shadow_paths, "impaired") == {"200", "280", "281"}


def test_state_survives_a_new_process(tmp_path):
    """No state file is carried between runs; the ledger is the state."""
    shadow_paths = paths(tmp_path)
    html = FIXTURE.read_text(encoding="utf-8")
    run(html, T0, shadow_paths)

    second = run(html, T0 + timedelta(minutes=15), shadow_paths)
    assert second["transitions"] == {}, "nothing changed, so nothing is written"
    assert second["impaired_after"] == 3


def test_a_single_absence_does_not_close_an_outage(tmp_path):
    """Closing is conservative: a false close would split one outage into two."""
    shadow_paths = paths(tmp_path)
    html = FIXTURE.read_text(encoding="utf-8")
    run(html, T0, shadow_paths)

    summary = run(cleared_html(html, 15), T0 + timedelta(minutes=15), shadow_paths)
    assert summary["transitions"] == {}
    assert summary["pending_confirmation"] == 1
    assert native_ids(shadow_paths, "impaired") == {"200", "280", "281"}


def test_a_confirmed_absence_closes_the_outage(tmp_path):
    shadow_paths = paths(tmp_path)
    html = FIXTURE.read_text(encoding="utf-8")
    run(html, T0, shadow_paths)
    for step in (15, 25):
        run(cleared_html(html, step), T0 + timedelta(minutes=step), shadow_paths)

    assert native_ids(shadow_paths, "impaired") == {"280", "281"}
    closed = [
        row
        for row in load_recent_transitions(
            shadow_paths.events_root, shadow_paths.raw_root
        )
        if row.transition_type == "closed"
    ]
    assert len(closed) == 1
    assert closed[0].source_native_id == "200"
    assert closed[0].evidence == "absent_from_complete_snapshot"
    assert closed[0].t_latest == T0 + timedelta(minutes=15), (
        "dated at the first absence, not at the confirmation"
    )


def test_debounce_state_survives_between_runs(tmp_path):
    """A fresh process each poll must still be able to reach a confirmation."""
    shadow_paths = paths(tmp_path)
    html = FIXTURE.read_text(encoding="utf-8")
    run(html, T0, shadow_paths)
    run(cleared_html(html, 15), T0 + timedelta(minutes=15), shadow_paths)

    stored = load_pending(shadow_paths.raw_root, SOURCE)
    assert len(stored) == 1
    assert next(iter(stored.values())).target_state == "ok"
    assert next(iter(stored.values())).count == 1


def test_a_stale_page_cannot_close_an_outage(tmp_path):
    """The counter dropped but the page clock did not move."""
    shadow_paths = paths(tmp_path)
    html = FIXTURE.read_text(encoding="utf-8")
    run(html, T0, shadow_paths)

    inconsistent = html.replace(
        'class="broken-counter">3<', 'class="broken-counter">2<'
    ).replace(
        '<a href="/station/900100003/200" class="lift-link alert">2</a>',
        '<a href="/station/900100003/200" class="lift-link">2</a>',
    )
    for step in (15, 25, 35):
        run(inconsistent, T0 + timedelta(minutes=step), shadow_paths)

    assert native_ids(shadow_paths, "impaired") == {"200", "280", "281"}


def test_an_incomplete_page_cannot_close_an_outage(tmp_path):
    shadow_paths = paths(tmp_path)
    run(FIXTURE.read_text(encoding="utf-8"), T0, shadow_paths)

    for step in (15, 25, 35):
        summary = run(
            "<html><body>temporary error</body></html>",
            T0 + timedelta(minutes=step),
            shadow_paths,
        )
        assert summary["complete"] is False
        assert summary["trusted_for_resolution"] is False

    # Past the trust gap they become unknown, which is the honest answer — but
    # never ok, and never with a closing row.
    assert native_ids(shadow_paths, "ok") == set()
    assert not [
        row
        for row in load_recent_transitions(
            shadow_paths.events_root, shadow_paths.raw_root
        )
        if row.to_state == "ok"
    ]


def test_a_long_outage_of_the_source_makes_state_unknown(tmp_path):
    shadow_paths = paths(tmp_path)
    run(FIXTURE.read_text(encoding="utf-8"), T0, shadow_paths)
    run(
        "<html><body>temporary error</body></html>",
        T0 + timedelta(hours=3),
        shadow_paths,
    )
    assert native_ids(shadow_paths, "unknown") == {"200", "280", "281"}
    assert native_ids(shadow_paths, "impaired") == set()


def test_dry_run_writes_nothing(tmp_path):
    shadow_paths = paths(tmp_path)
    summary = run(
        FIXTURE.read_text(encoding="utf-8"), T0, shadow_paths, dry_run=True
    )

    assert summary["transitions"] == {"opened": 3}
    assert not shadow_paths.events_root.exists()
    assert not shadow_paths.raw_root.exists()
    assert not shadow_paths.runs.exists()


def test_every_run_is_recorded_even_when_it_failed(tmp_path):
    shadow_paths = paths(tmp_path)
    run(FIXTURE.read_text(encoding="utf-8"), T0, shadow_paths)
    run("<html></html>", T0 + timedelta(minutes=15), shadow_paths)

    logged = [
        json.loads(line)
        for line in shadow_paths.runs.read_text(encoding="utf-8").splitlines()
    ]
    assert len(logged) == 2
    assert [row["trusted_for_resolution"] for row in logged] == [True, False]
