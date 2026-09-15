from datetime import datetime, timezone
from pathlib import Path

from transit_friction.accessibility.parser import parse_brokenlifts_snapshot


FIXTURE = Path(__file__).parent / "fixtures" / "brokenlifts_homepage.html"
MODERN_FIXTURE = Path(__file__).parent / "fixtures" / "brokenlifts_modern.html"
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


def test_invalid_source_calendar_date_is_an_incomplete_observation():
    html = FIXTURE.read_text(encoding="utf-8").replace("10.07.2026", "31.02.2026")
    snapshot = parse_brokenlifts_snapshot(html, observed_at=OBSERVED_AT)
    assert snapshot.complete is False
    assert snapshot.source_updated_at is None


def test_unparsed_alert_cannot_be_hidden_by_a_matching_counter():
    html = FIXTURE.read_text(encoding="utf-8").replace(
        "</ul>",
        '<li><a class="lift-link alert" href="/new-path/999">Lift</a></li></ul>',
    )
    snapshot = parse_brokenlifts_snapshot(html, observed_at=OBSERVED_AT)
    assert len(snapshot.outages) == snapshot.advertised_count == 3
    assert snapshot.complete is False
    assert "outage row without station link" in snapshot.warnings


def test_missing_station_name_is_incomplete_instead_of_crashing():
    html = FIXTURE.read_text(encoding="utf-8").replace("S+U Alexanderplatz Bhf", "")
    snapshot = parse_brokenlifts_snapshot(html, observed_at=OBSERVED_AT)
    assert snapshot.complete is False
    assert "outage row without station name" in snapshot.warnings


def test_modern_page_uses_dhids_and_explicit_broken_assets():
    snapshot = parse_brokenlifts_snapshot(
        MODERN_FIXTURE.read_text(encoding="utf-8"), observed_at=OBSERVED_AT
    )
    assert snapshot.complete is True
    assert snapshot.warnings == ()
    assert snapshot.source_updated_at.isoformat() == "2026-09-10T19:57:00+02:00"
    assert [outage.asset_id for outage in snapshot.outages] == ["5373", "6391"]
    assert snapshot.outages[0].station_id == "de:11000:900100003"
    assert snapshot.outages[0].station_name == "S+U Alexanderplatz Bhf"
    assert snapshot.outages[0].source_url.endswith("/station/de:11000:900100003/5373")


def test_modern_partial_page_cannot_resolve_missing_assets():
    html = MODERN_FIXTURE.read_text(encoding="utf-8").replace(
        'class="broken-count">2<', 'class="broken-count">35<'
    )
    snapshot = parse_brokenlifts_snapshot(html, observed_at=OBSERVED_AT)
    assert snapshot.complete is False
    assert "advertised 35 outages but parsed 2 unique assets" in snapshot.warnings


def test_modern_duplicate_asset_cannot_pass_completeness():
    html = MODERN_FIXTURE.read_text(encoding="utf-8").replace(
        "</div>\n    </li>",
        '</div><a class="elevator-link elevator-broken" '
        'href="/station/de:11000:900100003/5373">2</a>\n    </li>',
        1,
    )
    snapshot = parse_brokenlifts_snapshot(html, observed_at=OBSERVED_AT)
    assert snapshot.complete is False
    assert "duplicate asset_id 5373" in snapshot.warnings


def test_modern_asset_cannot_inherit_another_station_name():
    html = MODERN_FIXTURE.read_text(encoding="utf-8").replace(
        'href="/station/de:11000:900100003/5373"',
        'href="/station/de:12054:900100003/5373"',
    )
    snapshot = parse_brokenlifts_snapshot(html, observed_at=OBSERVED_AT)
    assert snapshot.complete is False
    assert "asset station differs from its station row" in snapshot.warnings
    assert "5373" not in {row.asset_id for row in snapshot.outages}
