"""Identifiers on both sides of the join, and how they are made to meet.

The outage source names stations with bare DHID numbers (``900100003``). The
GTFS feed names them with prefixed ids (``de:11000:900100003::7``) whose
platforms hang off a parent station. Neither side can be transformed into the
other by string surgery alone, and the ways of getting it slightly wrong are
quiet ones: they produce a plausible id that resolves to a real but different
station, or split one station into several that each look like they have no
elevator.

Everything here therefore refuses rather than guesses.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

#: The three id shapes the outage source and its history are known to use.
SEVEN_DIGIT = re.compile(r"^9\d{6}$")
NINE_DIGIT = re.compile(r"^9\d{8}$")
TWELVE_DIGIT = re.compile(r"^9000\d{8}$")

#: ``de:11000:900100003::7``, ``de:12054:900220010:1:50:A``, ``de:11000:900100003``
DHID = re.compile(r"^(?P<prefix>[a-z]{2}):(?P<ags>\d{4,8}):(?P<number>\d+)(?::.*)?$")

#: How deep a parent_station chain may be before we refuse to follow it. The
#: current feed's deepest chain is 1; the bound exists so a future feed with a
#: cycle or a surprise hierarchy stops the ingest instead of silently producing
#: a station key nobody intended.
MAX_PARENT_DEPTH = 4


class IdentityError(ValueError):
    """Raised instead of transforming an id whose shape is not recognised."""


def canonical_station_number(raw: str) -> str:
    """Reduce a station id to its canonical 9-digit DHID number.

    Accepts exactly three shapes and refuses everything else. Blind slicing —
    taking characters 4 onward from any 12-character string — is specifically
    avoided: the feed's own pathway node ids are plain 12-digit values like
    ``000300001054``, and none of the 13,617 of them begins with ``9000``, so
    slicing would turn a node id into a plausible station number.
    """
    value = (raw or "").strip()
    if NINE_DIGIT.match(value):
        return value
    if TWELVE_DIGIT.match(value):
        return "9" + value[4:]
    if SEVEN_DIGIT.match(value):
        return "9" + "00" + value[1:]
    raise IdentityError(f"unrecognised station id shape: {raw!r}")


def parse_dhid(stop_id: str) -> tuple[str, str, str] | None:
    """Split a prefixed stop id into (prefix, AGS, number), or None."""
    match = DHID.match(stop_id or "")
    if match is None:
        return None
    return match.group("prefix"), match.group("ags"), match.group("number")


def station_key_of(prefix: str, ags: str, number: str) -> str:
    """The station's identity in the feed's own namespace.

    Never reconstruct this as ``"de:11000:" + number``: S Potsdam Hauptbahnhof
    is ``de:12054:900230999`` and Brandenburg S-Bahn stations are in scope, so
    hard-coding Berlin's AGS silently drops them.
    """
    return f"{prefix}:{ags}:{number}"


@dataclass(frozen=True, slots=True)
class StationIndex:
    """Maps a bare station number to the feed's station key.

    ``defects`` records numbers the feed parented inconsistently — some platform
    rows carrying a parent_station and others not, all under the same name. That
    is a feed defect with a determinate answer (the parent its own rows declare),
    not an ambiguity, and it is resolved and counted rather than fatal.
    ``ambiguous`` records the ones with no determinate answer; those block.
    """

    by_number: dict[str, str]
    stop_to_station: dict[str, str]
    defects: dict[str, str] = field(default_factory=dict)
    ambiguous: dict[str, tuple[str, ...]] = field(default_factory=dict)
    max_depth_seen: int = 0

    def resolve(self, raw_station_id: str) -> str | None:
        """Station key for an outage-source station id, or None if unknown."""
        return self.by_number.get(canonical_station_number(raw_station_id))


def _walk_to_root(
    stop_id: str,
    parents: dict[str, str],
) -> tuple[str, int]:
    current, depth, seen = stop_id, 0, {stop_id}
    while True:
        parent = parents.get(current) or ""
        if not parent or parent in seen:
            return current, depth
        depth += 1
        if depth > MAX_PARENT_DEPTH:
            raise IdentityError(
                f"parent_station chain from {stop_id!r} exceeds depth "
                f"{MAX_PARENT_DEPTH}; refusing to guess the station"
            )
        seen.add(parent)
        current = parent


def build_station_index(
    stops: dict[str, dict],
) -> StationIndex:
    """Index every station number in a feed to exactly one station key.

    ``stops`` maps stop_id to a row with at least ``parent_station`` and
    ``stop_name``. Grouping by the numeric component alone is not enough:
    ``de:11000:900003200`` (a Hauptbahnhof platform) declares its parent as
    ``de:11000:900003201``, and grouping by own number would split the station
    into siblings that each appear to have no elevator.
    """
    parents = {sid: (row.get("parent_station") or "") for sid, row in stops.items()}

    resolved_key: dict[str, str] = {}
    max_depth = 0
    for sid in stops:
        root, depth = _walk_to_root(sid, parents)
        max_depth = max(max_depth, depth)
        parsed = parse_dhid(root)
        resolved_key[sid] = (
            station_key_of(*parsed) if parsed else root
        )

    by_number_candidates: dict[str, set[str]] = defaultdict(set)
    declared_candidates: dict[str, set[str]] = defaultdict(set)
    names: dict[str, set[str]] = defaultdict(set)
    for sid, row in stops.items():
        parsed = parse_dhid(sid)
        if parsed is None or parsed[0] != "de":
            continue
        number = parsed[2]
        by_number_candidates[number].add(resolved_key[sid])
        names[number].add(row.get("stop_name") or "")
        if parents.get(sid):
            declared_candidates[number].add(resolved_key[sid])

    by_number: dict[str, str] = {}
    defects: dict[str, str] = {}
    ambiguous: dict[str, tuple[str, ...]] = {}
    for number, candidates in by_number_candidates.items():
        if len(candidates) == 1:
            by_number[number] = next(iter(candidates))
            continue
        declared = declared_candidates.get(number, set())
        if len(declared) == 1:
            # Some rows name a parent and others were left orphaned. The feed
            # has told us the answer once; the orphans follow it.
            chosen = next(iter(declared))
            by_number[number] = chosen
            defects[number] = chosen
            continue
        ambiguous[number] = tuple(sorted(candidates))

    return StationIndex(
        by_number=by_number,
        stop_to_station=resolved_key,
        defects=defects,
        ambiguous=ambiguous,
        max_depth_seen=max_depth,
    )
