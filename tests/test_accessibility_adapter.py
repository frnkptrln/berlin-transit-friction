"""The adapter is the only place the two vocabularies meet."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from transit_friction.accessibility.adapter import (
    SOURCE_ID,
    payload_digest,
    to_source_snapshot,
)
from transit_friction.accessibility.models import OutageSnapshot
from transit_friction.accessibility.parser import parse_brokenlifts_snapshot
from transit_friction.events.identity import entity_uid

FIXTURE = Path(__file__).parent / "fixtures" / "brokenlifts_homepage.html"
T0 = datetime(2026, 7, 10, 9, 31, tzinfo=timezone.utc)


def _parsed():
    return parse_brokenlifts_snapshot(FIXTURE.read_text(encoding="utf-8"), observed_at=T0)


def test_outages_become_entities_with_stable_identity():
    snapshot = to_source_snapshot(_parsed(), run_id="r1")
    assert snapshot.source_id == SOURCE_ID
    assert {entity.source_native_id for entity in snapshot.entities} == {
        "200",
        "280",
        "281",
    }
    for entity in snapshot.entities:
        assert entity_uid(SOURCE_ID, "elevator", entity.source_native_id)
        assert entity.station_id
        assert entity.station_name


def test_a_complete_page_is_ok_and_carries_its_advertised_count():
    snapshot = to_source_snapshot(_parsed(), run_id="r1")
    assert snapshot.outcome == "ok"
    assert snapshot.complete is True
    assert snapshot.advertised_count == 3
    assert snapshot.source_updated_at is not None


def test_an_unparseable_page_is_incomplete_not_failed():
    parsed = parse_brokenlifts_snapshot("<html></html>", observed_at=T0)
    snapshot = to_source_snapshot(parsed, run_id="r1")
    assert snapshot.outcome == "incomplete"
    assert snapshot.complete is False
    assert snapshot.observed_at == T0, "we did read a response, it just made no sense"


def test_a_transport_failure_has_observed_nothing():
    """Never getting to look is different from looking and seeing nothing."""
    failed = OutageSnapshot.failed(
        source_url="https://example.invalid",
        observed_at=T0,
        warning="source fetch failed: boom",
    )
    snapshot = to_source_snapshot(failed, run_id="r1", outcome="http_error")
    assert snapshot.observed_at is None
    assert snapshot.entities == ()
    assert snapshot.attempted_at == T0
    assert snapshot.warnings


def test_the_adapter_refuses_a_contradictory_outcome():
    with pytest.raises(ValueError, match="parse error"):
        to_source_snapshot(_parsed(), run_id="r1", outcome="parse_error")


def test_payload_digest_survives_the_payload():
    html = FIXTURE.read_text(encoding="utf-8")
    assert payload_digest(html) == payload_digest(html.encode("utf-8"))
    assert payload_digest(html) != payload_digest(html + " ")
    assert payload_digest(None) is None


def test_status_text_absent_rather_than_empty():
    """An empty string is a value; a missing description is not."""
    parsed = _parsed()
    snapshot = to_source_snapshot(parsed, run_id="r1")
    for entity in snapshot.entities:
        assert entity.status_text is None or entity.status_text.strip()
