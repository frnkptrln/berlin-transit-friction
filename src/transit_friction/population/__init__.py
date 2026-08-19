"""The denominator: which stations a rate is divided by, and how long they run.

Outage hours alone answer no question a reader has. This package supplies the
population they are divided by — derived from a static GTFS release, versioned
by its content, and joined to the outage source by explicit rules that refuse
rather than guess.

See ``docs/denominator.md``.
"""

from __future__ import annotations

from .accounting import Accounting, account, denominator_seconds
from .crosswalk import CrosswalkReport, Resolution, build_crosswalk, resolve
from .frame import DEFAULT_FRAME_PREDICATE, Population, Station, derive_population
from .identity import (
    IdentityError,
    StationIndex,
    build_station_index,
    canonical_station_number,
    parse_dhid,
    station_key_of,
)
from .store import population_for_window, population_id, write_population

__all__ = [
    "Accounting",
    "CrosswalkReport",
    "DEFAULT_FRAME_PREDICATE",
    "IdentityError",
    "Population",
    "Resolution",
    "Station",
    "StationIndex",
    "account",
    "build_crosswalk",
    "build_station_index",
    "canonical_station_number",
    "denominator_seconds",
    "derive_population",
    "parse_dhid",
    "population_for_window",
    "population_id",
    "resolve",
    "station_key_of",
    "write_population",
]
