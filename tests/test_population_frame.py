"""Deriving a denominator from a feed, on a miniature of the real one."""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from transit_friction.population.accounting import denominator_seconds
from transit_friction.population.crosswalk import (
    OUT_OF_SCOPE,
    UNMATCHED_MALFORMED,
    UNMATCHED_UNKNOWN_ID,
    build_crosswalk,
)
from transit_friction.population.frame import derive_population
from transit_friction.population.identity import IdentityError
from transit_friction.population.store import (
    population_for_window,
    population_id,
    write_population,
)

# Stations: two U-Bahn (one with a lift, one without), one S-Bahn with a lift,
# one tram-only station that must stay out of the frame, and a Brandenburg
# S-Bahn station under a different AGS.
STOPS = [
    # stop_id, parent, name, location_type, wheelchair_boarding
    ("de:11000:900100003", "", "S+U Alexanderplatz", "1", "0"),
    ("de:11000:900100003::1", "de:11000:900100003", "S+U Alexanderplatz", "0", "0"),
    ("de:11000:900009101", "", "U Amrumer Str.", "1", "0"),
    ("de:11000:900009101::1", "de:11000:900009101", "U Amrumer Str.", "0", "0"),
    ("de:11000:900007102", "", "S Gesundbrunnen", "1", "0"),
    ("de:11000:900007102::1", "de:11000:900007102", "S Gesundbrunnen", "0", "0"),
    ("de:12054:900230999", "", "S Potsdam Hbf", "1", "0"),
    ("de:12054:900230999::1", "de:12054:900230999", "S Potsdam Hbf", "0", "0"),
    ("de:11000:900999001", "", "Tramhalt", "1", "0"),
    ("de:11000:900999001::1", "de:11000:900999001", "Tramhalt", "0", "0"),
    # a lift node, plain 12-digit, must never be read as a station number
    ("000300001054", "de:11000:900100003", "Aufzug", "3", ""),
]

ROUTES = [
    ("U2", "796", "400", "U2"),
    ("S1", "1", "109", "S1"),
    ("S7", "1", "109", "S7"),
    ("M4", "796", "900", "M4"),   # tram: same agency, out of scope by route type
]

TRIPS = [
    ("U2", "t-u2", "weekday"),
    ("S1", "t-s1", "weekday"),
    ("S7", "t-s7", "weekday"),
    ("M4", "t-m4", "weekday"),
]

STOP_TIMES = [
    ("t-u2", "de:11000:900100003::1", "05:00:00"),
    ("t-u2", "de:11000:900009101::1", "24:30:00"),   # past midnight, on purpose
    ("t-s1", "de:11000:900007102::1", "04:30:00"),
    ("t-s1", "de:11000:900100003::1", "23:00:00"),
    ("t-s1", "de:11000:900007102::1", "22:30:00"),
    ("t-s7", "de:12054:900230999::1", "06:00:00"),
    ("t-s7", "de:12054:900230999::1", "22:00:00"),
    ("t-m4", "de:11000:900999001::1", "06:00:00"),
]

# Alexanderplatz and Gesundbrunnen have lifts; Amrumer Str. has pathway data
# but no elevator edge; Potsdam has a lift.
PATHWAYS = [
    ("p1", "de:11000:900100003::1", "000300001054", "5"),
    ("p2", "000300001054", "de:11000:900100003::1", "5"),
    ("p3", "de:11000:900007102::1", "de:11000:900007102", "5"),
    ("p4", "de:12054:900230999::1", "de:12054:900230999", "5"),
    ("p5", "de:11000:900009101::1", "de:11000:900009101", "1"),  # stairs only
]


def _csv(rows, header):
    return "\n".join([",".join(header)] + [",".join(r) for r in rows]) + "\n"


@pytest.fixture
def archive(tmp_path) -> Path:
    path = tmp_path / "mini-gtfs.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("agency.txt", _csv(
            [("796", "BVG", "https://bvg.de", "Europe/Berlin"),
             ("1", "S-Bahn Berlin GmbH", "https://s-bahn-berlin.de", "Europe/Berlin")],
            ("agency_id", "agency_name", "agency_url", "agency_timezone")))
        z.writestr("stops.txt", _csv(STOPS, (
            "stop_id", "parent_station", "stop_name", "location_type",
            "wheelchair_boarding")))
        z.writestr("routes.txt", _csv(ROUTES, (
            "route_id", "agency_id", "route_type", "route_short_name")))
        z.writestr("trips.txt", _csv(TRIPS, ("route_id", "trip_id", "service_id")))
        z.writestr("stop_times.txt", _csv(
            [(t, s, d, d) for t, s, d in STOP_TIMES],
            ("trip_id", "stop_id", "arrival_time", "departure_time")))
        z.writestr("pathways.txt", _csv(PATHWAYS, (
            "pathway_id", "from_stop_id", "to_stop_id", "pathway_mode")))
        z.writestr("calendar.txt", _csv(
            [("weekday", "1", "1", "1", "1", "1", "0", "0", "20260601", "20260630")],
            ("service_id", "monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday", "start_date", "end_date")))
    return path


# --- the frame --------------------------------------------------------------


def test_the_frame_is_scoped_by_agency_and_route_type(archive):
    """route_type alone pulls in operators hundreds of kilometres away."""
    population = derive_population(archive)
    names = {s.name for s in population.stations.values()}
    assert "Tramhalt" not in names, "a tram stop has no elevator to lose"
    assert names == {
        "S+U Alexanderplatz", "U Amrumer Str.", "S Gesundbrunnen", "S Potsdam Hbf"
    }


def test_a_brandenburg_station_stays_in_scope(archive):
    """Rebuilding keys as 'de:11000:' + number would drop it silently."""
    population = derive_population(archive)
    assert "de:12054:900230999" in population.frame_keys


def test_elevator_equipment_comes_from_pathway_mode_five(archive):
    population = derive_population(archive)
    equipped = {population.stations[k].name for k in population.equipped_keys}
    assert equipped == {"S+U Alexanderplatz", "S Gesundbrunnen", "S Potsdam Hbf"}


def test_no_elevator_edge_and_no_pathway_data_are_counted_apart(archive):
    """One is evidence about the station; the other is evidence about the feed."""
    population = derive_population(archive)
    assert population.diagnostics["in_frame_without_elevator_edge"] == 1
    assert population.diagnostics["in_frame_without_pathway_data"] == 0


def test_a_lift_node_does_not_become_a_station(archive):
    population = derive_population(archive)
    assert all(k.startswith("de:") for k in population.frame_keys)


# --- service time -----------------------------------------------------------


def test_the_denominator_is_service_time_not_clock_time(archive):
    """A station is not accountable for its lifts when nothing runs."""
    population = derive_population(archive)
    day = date(2026, 6, 8)  # a Monday
    alexanderplatz = "de:11000:900100003"
    seconds = population.service_seconds(alexanderplatz, day)
    assert seconds == 18 * 3600, "05:00 to 23:00"
    assert seconds < 24 * 3600


def test_a_service_day_may_run_past_midnight(archive):
    population = derive_population(archive)
    seconds = population.service_seconds("de:11000:900009101", date(2026, 6, 8))
    assert seconds == 0, "a single departure is a zero-width span"


def test_a_day_with_no_service_contributes_no_denominator(archive):
    """A station closed for works stays in the frame and adds nothing."""
    population = derive_population(archive)
    saturday = date(2026, 6, 6)
    assert population.service_seconds("de:11000:900100003", saturday) == 0.0
    assert "de:11000:900100003" in population.frame_keys


def test_the_denominator_sums_only_equipped_stations(archive):
    population = derive_population(archive)
    day = date(2026, 6, 8)
    total = denominator_seconds(population, [day])
    by_hand = sum(
        population.service_seconds(k, day) for k in population.equipped_keys
    )
    assert total == by_hand


# --- the crosswalk ----------------------------------------------------------


def test_source_ids_resolve_to_frame_stations(archive):
    population = derive_population(archive, with_service_spans=False)
    report = build_crosswalk(population, ["900100003", "900000100003", "900230999"])
    assert report.match_rate == 1.0
    assert report.resolutions["900000100003"].station_key == "de:11000:900100003"


def test_every_failure_mode_has_its_own_verdict(archive):
    population = derive_population(archive, with_service_spans=False)
    report = build_crosswalk(
        population, ["de:11000:900100003", "900555555", "900999001", "900100003"]
    )
    verdicts = {i: r.verdict for i, r in report.resolutions.items()}
    assert verdicts["de:11000:900100003"] == UNMATCHED_MALFORMED
    assert verdicts["900555555"] == UNMATCHED_UNKNOWN_ID
    assert verdicts["900999001"] == OUT_OF_SCOPE, "a real station, outside the frame"
    assert report.match_rate == 0.25


def test_out_of_scope_is_not_pooled_with_a_broken_join(archive):
    """One says the frame is too narrow; the other says the join is broken."""
    population = derive_population(archive, with_service_spans=False)
    report = build_crosswalk(population, ["900999001"]).to_dict()
    assert report["out_of_scope"] == 1
    assert report["unmatched_unknown_id"] == 0
    assert report["out_of_scope_stations"][0]["station_key"] == "de:11000:900999001"


def test_nothing_is_dropped_silently(archive):
    population = derive_population(archive, with_service_spans=False)
    report = build_crosswalk(population, ["900555555", "nonsense"])
    assert report.distinct_source_station_ids_seen == 2
    assert set(report.to_dict()["unmatched_ids"]) == {"900555555", "nonsense"}


# --- storage ----------------------------------------------------------------


def test_a_population_is_identified_by_its_content(archive, tmp_path):
    population = derive_population(archive, with_service_spans=False)
    first = write_population(population, tmp_path / "reference")
    again = write_population(population, tmp_path / "reference")
    assert first.created is True and again.created is False
    assert first.population_id == population_id(population)


def test_a_different_predicate_is_a_different_population(archive, tmp_path):
    a = derive_population(archive, with_service_spans=False)
    b = derive_population(
        archive, predicate=(("1", "109"),), with_service_spans=False
    )
    assert population_id(a) != population_id(b)


def test_the_population_for_a_window_is_chosen_by_the_feeds_own_span(archive, tmp_path):
    population = derive_population(archive)
    root = tmp_path / "reference"
    written = write_population(population, root)
    inside, status = population_for_window(root, date(2026, 6, 8), date(2026, 6, 9))
    assert (inside, status) == (written.population_id, "adopted")
    outside, status = population_for_window(root, date(2027, 1, 1), date(2027, 1, 2))
    assert outside is None and status == "no_release_covers_window"


def test_a_feed_missing_a_required_member_is_refused(tmp_path):
    path = tmp_path / "broken.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("stops.txt", "stop_id\n")
    with pytest.raises(IdentityError, match="missing"):
        derive_population(path)


def test_edges_and_links_are_counted_apart(archive):  # noqa: F811
    """Neither is an elevator count, and the gap between them says why.

    Every pathway_mode=5 row in the real feed is one-directional, so a single
    connection appears twice. Collapsing to distinct node pairs halves the
    figure and it is still an upper bound: across the 144 U-Bahn stations the
    real feed yields 401 links against BVG's published 204 lifts.
    """
    population = derive_population(archive, with_service_spans=False)
    alexanderplatz = population.stations["de:11000:900100003"]
    assert alexanderplatz.elevator_edge_count == 2, "two directed rows"
    assert alexanderplatz.elevator_link_count == 1, "one connection"
    assert population.diagnostics["elevator_edges_in_frame"] > (
        population.diagnostics["elevator_links_in_frame"]
    )
