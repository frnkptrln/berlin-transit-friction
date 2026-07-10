from datetime import datetime, timezone
from pathlib import Path

from transit_friction.accessibility.parser import parse_brokenlifts_snapshot


FIXTURE = Path(__file__).parent / "fixtures" / "brokenlifts_homepage.html"
OBSERVED_AT = datetime(2026, 7, 10, 9, 31, tzinfo=timezone.utc)


def test_parser_extracts_stable_assets_and_source_time():
    snapshot = parse_brokenlifts_snapshot(
        FIXTURE.read_text(encoding="utf-8"),
        observed_at=OBSERVED_AT,
    )

    assert snapshot.complete is True
    assert snapshot.source_updated_at.isoformat() == "2026-07-10T11:30:00+02:00"
    assert [outage.asset_id for outage in snapshot.outages] == ["200", "280", "281"]
    assert snapshot.outages[0].station_id == "900100003"
    assert snapshot.outages[0].station_name == "S+U Alexanderplatz Bhf"
    assert snapshot.outages[1].status_text == "Fährt in Kürze wieder."


def test_count_mismatch_marks_snapshot_incomplete():
    html = FIXTURE.read_text(encoding="utf-8").replace(
        'class="broken-counter">3<', 'class="broken-counter">4<'
    )
    snapshot = parse_brokenlifts_snapshot(html, observed_at=OBSERVED_AT)

    assert snapshot.complete is False
    assert "advertised 4 outages but parsed 3 unique assets" in snapshot.warnings


def test_missing_list_cannot_be_complete():
    snapshot = parse_brokenlifts_snapshot(
        '<p class="broken-update">Letzte Aktualisierung am 10.07.2026, 11:30 Uhr</p>',
        observed_at=OBSERVED_AT,
    )

    assert snapshot.complete is False
    assert snapshot.outages == ()
    assert "outage list missing" in snapshot.warnings
