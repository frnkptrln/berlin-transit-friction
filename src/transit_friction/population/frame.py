"""Deriving the denominator population from a static GTFS archive.

Three questions, answered from the feed and nothing else:

**Which stations are in scope.** By agency *and* route type, never route type
alone: ``route_type=109`` on its own pulls in Mitteldeutsche Regiobahn stations
hundreds of kilometres away, and an "all Berlin stations" frame would divide
elevator outages by tram stops that have no elevator to lose.

**Which of them have an elevator.** From ``pathways.txt`` rows with
``pathway_mode=5``. Absence of an elevator edge at a station whose pathways are
otherwise described is evidence; absence of pathway data altogether is not, and
the two are counted separately so the second can never be read as the first.

**How long each is in service.** First to last departure per service day, not
24 hours of clock. A clock denominator deflates the rate by roughly an eighth on
a weekday, in one direction, using data the ingest already reads.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .identity import (
    IdentityError,
    StationIndex,
    build_station_index,
    parse_dhid,
)

#: (agency_id, route_type) pairs that define the frame. Agency-scoped on
#: purpose — see the module docstring.
DEFAULT_FRAME_PREDICATE: tuple[tuple[str, str], ...] = (
    ("796", "400"),  # Berliner Verkehrsbetriebe, U-Bahn
    ("1", "109"),    # S-Bahn Berlin GmbH, S-Bahn
)

ELEVATOR_PATHWAY_MODE = "5"

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True, slots=True)
class Station:
    station_key: str
    station_number: str
    name: str
    agency_scopes: tuple[str, ...]
    elevator_equipped: bool
    elevator_edge_count: int
    has_pathway_data: bool


@dataclass(frozen=True, slots=True)
class Population:
    """One derived denominator population, from one archive."""

    stations: dict[str, Station]
    index: StationIndex
    service_spans: dict[tuple[str, str], tuple[int, int]]
    service_dates: dict[str, frozenset[str]]
    feed_start: date | None
    feed_end: date | None
    predicate: tuple[tuple[str, str], ...]
    diagnostics: dict = field(default_factory=dict)

    @property
    def frame_keys(self) -> frozenset[str]:
        return frozenset(self.stations)

    @property
    def equipped_keys(self) -> frozenset[str]:
        return frozenset(k for k, s in self.stations.items() if s.elevator_equipped)

    def service_seconds(self, station_key: str, day: date) -> float:
        """Seconds between the first and last departure at a station on a date.

        Returns 0.0 when nothing is scheduled — a station closed for works
        contributes no denominator that day, but stays in the frame so its
        outages remain attributable.
        """
        services = self.service_dates.get(day.isoformat(), frozenset())
        spans = [
            self.service_spans[(station_key, service)]
            for service in services
            if (station_key, service) in self.service_spans
        ]
        if not spans:
            return 0.0
        return float(max(hi for _, hi in spans) - min(lo for lo, _ in spans))


def _reader(archive: zipfile.ZipFile, name: str):
    return csv.DictReader(io.TextIOWrapper(archive.open(name), "utf-8-sig"))


def _seconds(value: str) -> int | None:
    """GTFS times run past 24:00:00 when a service day crosses midnight."""
    parts = (value or "").split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None


def _service_dates(archive: zipfile.ZipFile) -> dict[str, frozenset[str]]:
    by_date: dict[str, set[str]] = defaultdict(set)
    names = archive.namelist()

    if "calendar.txt" in names:
        for row in _reader(archive, "calendar.txt"):
            start = date.fromisoformat(
                f"{row['start_date'][:4]}-{row['start_date'][4:6]}-{row['start_date'][6:]}"
            )
            end = date.fromisoformat(
                f"{row['end_date'][:4]}-{row['end_date'][4:6]}-{row['end_date'][6:]}"
            )
            active = [i for i, day in enumerate(WEEKDAYS) if row.get(day) == "1"]
            if not active:
                continue
            current = start
            while current <= end:
                if current.weekday() in active:
                    by_date[current.isoformat()].add(row["service_id"])
                current += timedelta(days=1)

    if "calendar_dates.txt" in names:
        for row in _reader(archive, "calendar_dates.txt"):
            stamp = row["date"]
            key = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
            if row.get("exception_type") == "1":
                by_date[key].add(row["service_id"])
            elif row.get("exception_type") == "2":
                by_date[key].discard(row["service_id"])

    return {day: frozenset(services) for day, services in by_date.items()}


def derive_population(
    archive_path: Path,
    *,
    predicate: tuple[tuple[str, str], ...] = DEFAULT_FRAME_PREDICATE,
    with_service_spans: bool = True,
) -> Population:
    """Read one GTFS archive into a population. Streams the large members."""
    archive = zipfile.ZipFile(archive_path)
    names = archive.namelist()
    for required in ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt"):
        if required not in names:
            raise IdentityError(f"archive is missing {required}")

    stops = {
        row["stop_id"]: {
            "parent_station": row.get("parent_station") or "",
            "stop_name": row.get("stop_name") or "",
            "location_type": row.get("location_type") or "0",
        }
        for row in _reader(archive, "stops.txt")
    }
    index = build_station_index(stops)
    if index.ambiguous:
        raise IdentityError(
            f"{len(index.ambiguous)} station numbers resolve to more than one "
            f"station and the feed does not say which: "
            f"{sorted(index.ambiguous)[:5]}"
        )

    def key_for_stop(stop_id: str) -> str:
        parsed = parse_dhid(stop_id)
        if parsed and parsed[0] == "de":
            mapped = index.by_number.get(parsed[2])
            if mapped:
                return mapped
        return index.stop_to_station.get(stop_id, stop_id)

    scope_of_route: dict[str, str] = {}
    for row in _reader(archive, "routes.txt"):
        pair = (row.get("agency_id") or "", row.get("route_type") or "")
        if pair in predicate:
            scope_of_route[row["route_id"]] = f"{pair[0]}/{pair[1]}"

    scope_of_trip: dict[str, str] = {}
    service_of_trip: dict[str, str] = {}
    for row in _reader(archive, "trips.txt"):
        scope = scope_of_route.get(row["route_id"])
        if scope:
            scope_of_trip[row["trip_id"]] = scope
            service_of_trip[row["trip_id"]] = row.get("service_id") or ""

    scopes_of_station: dict[str, set[str]] = defaultdict(set)
    spans: dict[tuple[str, str], tuple[int, int]] = {}
    rows_scanned = 0
    for row in _reader(archive, "stop_times.txt"):
        rows_scanned += 1
        scope = scope_of_trip.get(row["trip_id"])
        if scope is None:
            continue
        station = key_for_stop(row["stop_id"])
        scopes_of_station[station].add(scope)
        if not with_service_spans:
            continue
        moment = _seconds(row.get("departure_time") or row.get("arrival_time") or "")
        if moment is None:
            continue
        pair = (station, service_of_trip[row["trip_id"]])
        current = spans.get(pair)
        spans[pair] = (
            moment if current is None else min(current[0], moment),
            moment if current is None else max(current[1], moment),
        )

    elevator_edges: dict[str, int] = defaultdict(int)
    stations_with_pathways: set[str] = set()
    pathway_rows = 0
    if "pathways.txt" in names:
        for row in _reader(archive, "pathways.txt"):
            pathway_rows += 1
            endpoints = {key_for_stop(row["from_stop_id"]), key_for_stop(row["to_stop_id"])}
            stations_with_pathways |= endpoints
            if row.get("pathway_mode") == ELEVATOR_PATHWAY_MODE:
                for endpoint in endpoints:
                    elevator_edges[endpoint] += 1

    names_by_key: dict[str, str] = {}
    for stop_id, row in stops.items():
        key = key_for_stop(stop_id)
        if row["location_type"] == "1" or key not in names_by_key:
            names_by_key.setdefault(key, row["stop_name"])
        if row["location_type"] == "1":
            names_by_key[key] = row["stop_name"]

    stations: dict[str, Station] = {}
    for key, scopes in scopes_of_station.items():
        parsed = parse_dhid(key)
        stations[key] = Station(
            station_key=key,
            station_number=parsed[2] if parsed else key,
            name=names_by_key.get(key, key),
            agency_scopes=tuple(sorted(scopes)),
            elevator_equipped=elevator_edges.get(key, 0) > 0,
            elevator_edge_count=elevator_edges.get(key, 0),
            has_pathway_data=key in stations_with_pathways,
        )

    service_dates = _service_dates(archive) if with_service_spans else {}
    covered = sorted(service_dates) if service_dates else []

    equipped = [s for s in stations.values() if s.elevator_equipped]
    diagnostics = {
        "stop_times_rows": rows_scanned,
        "pathway_rows": pathway_rows,
        "frame_stations": len(stations),
        "elevator_equipped": len(equipped),
        "in_frame_without_elevator_edge": sum(
            1 for s in stations.values()
            if not s.elevator_equipped and s.has_pathway_data
        ),
        "in_frame_without_pathway_data": sum(
            1 for s in stations.values() if not s.has_pathway_data
        ),
        "station_numbers_indexed": len(index.by_number),
        "parenting_defects_resolved": len(index.defects),
        "max_parent_depth": index.max_depth_seen,
        "has_pathways": "pathways.txt" in names,
        "has_levels": "levels.txt" in names,
    }

    return Population(
        stations=stations,
        index=index,
        service_spans=spans,
        service_dates=service_dates,
        feed_start=date.fromisoformat(covered[0]) if covered else None,
        feed_end=date.fromisoformat(covered[-1]) if covered else None,
        predicate=predicate,
        diagnostics=diagnostics,
    )
