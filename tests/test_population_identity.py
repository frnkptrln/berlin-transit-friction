"""Identifiers meet across the join, or they refuse to."""

from __future__ import annotations

import pytest

from transit_friction.population.identity import (
    IdentityError,
    build_station_index,
    canonical_station_number,
    parse_dhid,
    station_key_of,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("900100003", "900100003"),        # 9-digit, the current shape
        ("900000100003", "900100003"),     # 12-digit legacy
        ("9003201", "900003201"),          # 7-digit legacy
    ],
)
def test_the_three_known_shapes_canonicalise(raw, expected):
    assert canonical_station_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "de:11000:900100003",   # a prefixed id is not a bare number
        "000300001054",         # a pathway node id, 12 digits, not a station
        "12345",
        "",
        "900100003x",
    ],
)
def test_an_unrecognised_shape_is_refused_not_transformed(raw):
    """Blind slicing turns a node id into a plausible station number."""
    with pytest.raises(IdentityError):
        canonical_station_number(raw)


def test_a_node_id_can_never_become_a_station_number():
    """The specific corruption the shape check exists to prevent.

    Taking characters 4 onward from any 12-character string — what a widely
    copied helper does — maps 000300001054 to 0001054 and then to something
    that looks like a real station.
    """
    with pytest.raises(IdentityError):
        canonical_station_number("000300001054")


def test_dhid_parsing_tolerates_every_suffix_shape_in_the_feed():
    assert parse_dhid("de:11000:900100003") == ("de", "11000", "900100003")
    assert parse_dhid("de:11000:900100003::7") == ("de", "11000", "900100003")
    assert parse_dhid("de:12054:900220010:1:50:A") == ("de", "12054", "900220010")
    assert parse_dhid("000300001054") is None


def test_the_station_key_keeps_the_feeds_own_region():
    """Never rebuild a key as 'de:11000:' + number.

    S Potsdam Hauptbahnhof is de:12054:900230999, and Brandenburg S-Bahn
    stations are in scope — hard-coding Berlin's AGS drops them silently.
    """
    assert station_key_of("de", "12054", "900230999") == "de:12054:900230999"


# --- the index --------------------------------------------------------------


def _stops(rows):
    return {sid: dict(parent_station=p, stop_name=n, location_type=lt)
            for sid, p, n, lt in rows}


def test_platforms_resolve_to_their_parent_station():
    """Grouping by the number alone splits a station into false siblings."""
    index = build_station_index(_stops([
        ("de:11000:900003201", "", "Hauptbahnhof", "1"),
        ("de:11000:900003200::1", "de:11000:900003201", "Hauptbahnhof", "0"),
        ("de:11000:900003200::2", "de:11000:900003201", "Hauptbahnhof", "0"),
    ]))
    assert index.by_number["900003200"] == "de:11000:900003201"
    assert index.by_number["900003201"] == "de:11000:900003201"
    assert index.ambiguous == {}


def test_an_inconsistently_parented_number_is_resolved_not_rejected():
    """A real defect in the live feed, on five numbers.

    Some platform rows carry a parent and others were left orphaned, under one
    name. The feed has told us the answer once; the orphans follow it. Treating
    this as fatal would block a perfectly usable release.
    """
    index = build_station_index(_stops([
        ("de:11000:900057103::1", "de:11000:900058103", "S+U Yorckstr.", "0"),
        ("de:11000:900057103::3", "", "S+U Yorckstr.", "0"),
    ]))
    assert index.by_number["900057103"] == "de:11000:900058103"
    assert index.defects == {"900057103": "de:11000:900058103"}
    assert index.ambiguous == {}


def test_a_number_pointing_at_two_different_stations_is_ambiguous():
    index = build_station_index(_stops([
        ("de:11000:900000001::1", "de:11000:900000010", "Somewhere", "0"),
        ("de:11000:900000001::2", "de:11000:900000020", "Elsewhere", "0"),
    ]))
    assert "900000001" in index.ambiguous
    assert "900000001" not in index.by_number


def test_a_parent_chain_deeper_than_the_bound_refuses():
    rows = [(f"de:11000:90000000{i}", f"de:11000:90000000{i + 1}", "Deep", "0")
            for i in range(6)]
    with pytest.raises(IdentityError, match="exceeds depth"):
        build_station_index(_stops(rows))


def test_the_index_reports_how_deep_it_had_to_go():
    index = build_station_index(_stops([
        ("de:11000:900000010", "", "Parent", "1"),
        ("de:11000:900000001::1", "de:11000:900000010", "Child", "0"),
    ]))
    assert index.max_depth_seen == 1
