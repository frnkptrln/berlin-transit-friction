"""Storing a derived population as versioned reference data.

Reference data is not an event stream and not an aggregate. It is a fact about
the world that a metric was computed against, so a published number has to be
able to name the exact population it used — otherwise a rate compared across two
releases is comparing two denominators.

The partition key is therefore derived from the *content*, not from a release
date or a file hash: two archives that yield the same stations and the same
predicate share a population, and a bug fix in the frame predicate writes a new
one instead of trying to overwrite an immutable partition.

Retention: forever, tiny, and rebuildable only if the archive is still
obtainable — which is why the derived rows are kept rather than a hash of a
download nobody can fetch again.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from ..events.store import file_hash
from .frame import Population

DERIVATION_VERSION = 1

STATION_COLUMNS = (
    "station_key",
    "station_number",
    "name",
    "agency_scopes",
    "elevator_equipped",
    "elevator_edge_count",
    "has_pathway_data",
)


def _arrow_schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("station_key", pa.string()),
            pa.field("station_number", pa.string()),
            pa.field("name", pa.string()),
            pa.field("agency_scopes", pa.string()),
            pa.field("elevator_equipped", pa.bool_()),
            pa.field("elevator_edge_count", pa.int32()),
            pa.field("has_pathway_data", pa.bool_()),
        ]
    )


def station_rows(population: Population) -> list[dict]:
    return [
        {
            "station_key": s.station_key,
            "station_number": s.station_number,
            "name": s.name,
            "agency_scopes": ",".join(s.agency_scopes),
            "elevator_equipped": s.elevator_equipped,
            "elevator_edge_count": s.elevator_edge_count,
            "has_pathway_data": s.has_pathway_data,
        }
        for s in sorted(population.stations.values(), key=lambda s: s.station_key)
    ]


def population_id(population: Population) -> str:
    """Identity of a population: its rows, its predicate, its derivation.

    Not the archive's hash. A byte-different release that yields identical
    stations is the same denominator, and saying otherwise would strand every
    metric row that named the old one.
    """
    payload = json.dumps(
        {
            "derivation_version": DERIVATION_VERSION,
            "predicate": sorted(f"{a}/{t}" for a, t in population.predicate),
            "stations": station_rows(population),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def population_dir(reference_root: Path, pid: str) -> Path:
    return reference_root / "population" / f"population={pid}"


@dataclass(frozen=True, slots=True)
class WriteResult:
    population_id: str
    path: Path
    rows: int
    created: bool


def write_population(
    population: Population,
    reference_root: Path,
    *,
    source_note: str = "",
    archive_path: Path | None = None,
) -> WriteResult:
    """Write a population once. Re-deriving the same one is a no-op."""
    from ..events.store import write_parquet_with_schema

    pid = population_id(population)
    directory = population_dir(reference_root, pid)
    parquet = directory / "stations.parquet"
    manifest_path = directory / "manifest.json"
    if parquet.exists() and manifest_path.exists():
        return WriteResult(pid, parquet, len(population.stations), created=False)

    rows = station_rows(population)
    write_parquet_with_schema(_arrow_schema(), rows, parquet)

    equipped = [r for r in rows if r["elevator_equipped"]]
    manifest = {
        "population_id": pid,
        "derivation_version": DERIVATION_VERSION,
        "predicate": sorted(f"{a}/{t}" for a, t in population.predicate),
        "frame_stations": len(rows),
        "elevator_equipped": len(equipped),
        "feed_service_start": population.feed_start.isoformat() if population.feed_start else None,
        "feed_service_end": population.feed_end.isoformat() if population.feed_end else None,
        "diagnostics": population.diagnostics,
        "file_sha256": file_hash(parquet),
        "archive_sha256": file_hash(archive_path) if archive_path else None,
        "archive_name": archive_path.name if archive_path else None,
        "source_note": source_note,
        "derived_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return WriteResult(pid, parquet, len(rows), created=True)


def load_manifest(reference_root: Path, pid: str) -> dict:
    path = population_dir(reference_root, pid) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_populations(reference_root: Path) -> list[str]:
    root = reference_root / "population"
    if not root.exists():
        return []
    return sorted(
        child.name.removeprefix("population=")
        for child in root.iterdir()
        if child.is_dir() and child.name.startswith("population=")
    )


def population_for_window(
    reference_root: Path,
    window_start: date,
    window_end: date,
) -> tuple[str | None, str]:
    """The population whose feed service span covers a window.

    Returns (population_id, status). Selection is by the FEED's own service
    span, not by when we happened to adopt it: a stalled adoption must not
    silently serve last year's denominator, and a window before the first
    adoption must remain backfillable.
    """
    candidates = []
    for pid in list_populations(reference_root):
        manifest = load_manifest(reference_root, pid)
        start = manifest.get("feed_service_start")
        end = manifest.get("feed_service_end")
        if not start or not end:
            continue
        if date.fromisoformat(start) <= window_start and date.fromisoformat(end) >= window_end:
            candidates.append((manifest.get("derived_at", ""), pid))
    if not candidates:
        return None, "no_release_covers_window"
    return sorted(candidates)[-1][1], "adopted"
