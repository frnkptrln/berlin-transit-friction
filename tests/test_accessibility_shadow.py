import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from transit_friction.accessibility.lifecycle import load_state
from transit_friction.accessibility.parser import parse_brokenlifts_snapshot
from transit_friction.accessibility.shadow import ShadowPaths, apply_snapshot


FIXTURE = Path(__file__).parent / "fixtures" / "brokenlifts_homepage.html"
T0 = datetime(2026, 7, 10, 9, 31, tzinfo=timezone.utc)


def paths(tmp_path):
    return ShadowPaths(
        state=tmp_path / "state.json",
        transitions=tmp_path / "transitions.jsonl",
        runs=tmp_path / "runs.jsonl",
    )


def snapshot(html: str, observed_at: datetime):
    return parse_brokenlifts_snapshot(html, observed_at=observed_at)


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_two_runs_persist_state_and_record_real_transitions(tmp_path):
    shadow_paths = paths(tmp_path)
    initial_html = FIXTURE.read_text(encoding="utf-8")

    first = apply_snapshot(snapshot(initial_html, T0), paths=shadow_paths)
    assert first["new"] == 3
    assert first["active_after"] == 3

    changed_html = (
        initial_html.replace(
            "Letzte Aktualisierung am 10.07.2026, 11:30 Uhr",
            "Letzte Aktualisierung am 10.07.2026, 11:45 Uhr",
        )
        .replace('class="broken-counter">3<', 'class="broken-counter">2<')
        .replace(
            '<a href="/station/900100003/200" class="lift-link alert">2</a>',
            '<a href="/station/900100003/200" class="lift-link">2</a>',
        )
    )
    second = apply_snapshot(
        snapshot(changed_html, T0 + timedelta(minutes=15)),
        paths=shadow_paths,
    )

    assert second["resolution_allowed"] is True
    assert second["ongoing"] == 2
    assert second["resolved"] == 1
    assert set(load_state(shadow_paths.state)) == {"280", "281"}

    transitions = read_jsonl(shadow_paths.transitions)
    assert [row["transition"] for row in transitions] == [
        "new",
        "new",
        "new",
        "resolved",
    ]
    assert transitions[-1]["asset_id"] == "200"
    assert len(read_jsonl(shadow_paths.runs)) == 2


def test_same_source_version_cannot_resolve_an_asset(tmp_path):
    shadow_paths = paths(tmp_path)
    initial_html = FIXTURE.read_text(encoding="utf-8")
    apply_snapshot(snapshot(initial_html, T0), paths=shadow_paths)

    inconsistent_html = (
        initial_html.replace('class="broken-counter">3<', 'class="broken-counter">2<')
        .replace(
            '<a href="/station/900100003/200" class="lift-link alert">2</a>',
            '<a href="/station/900100003/200" class="lift-link">2</a>',
        )
    )
    result = apply_snapshot(
        snapshot(inconsistent_html, T0 + timedelta(minutes=15)),
        paths=shadow_paths,
    )

    assert result["complete"] is True
    assert result["resolution_allowed"] is False
    assert result["resolved"] == 0
    assert set(load_state(shadow_paths.state)) == {"200", "280", "281"}


def test_incomplete_run_cannot_mutate_state_or_resolve(tmp_path):
    shadow_paths = paths(tmp_path)
    initial_html = FIXTURE.read_text(encoding="utf-8")
    apply_snapshot(snapshot(initial_html, T0), paths=shadow_paths)

    incomplete = parse_brokenlifts_snapshot(
        "<html><body>temporary error</body></html>",
        observed_at=T0 + timedelta(minutes=15),
    )
    result = apply_snapshot(incomplete, paths=shadow_paths)

    assert result["complete"] is False
    assert result["resolution_allowed"] is False
    assert result["resolved"] == 0
    assert set(load_state(shadow_paths.state)) == {"200", "280", "281"}


def test_dry_run_writes_nothing(tmp_path):
    shadow_paths = paths(tmp_path)
    result = apply_snapshot(
        snapshot(FIXTURE.read_text(encoding="utf-8"), T0),
        paths=shadow_paths,
        dry_run=True,
    )

    assert result["new"] == 3
    assert not shadow_paths.state.exists()
    assert not shadow_paths.transitions.exists()
    assert not shadow_paths.runs.exists()
