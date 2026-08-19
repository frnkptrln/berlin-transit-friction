"""Writing and reading the append-only tables.

Two phases, because Parquet cannot be appended to without rewriting it — and
rewriting a file 288 times a day is both the overwrite we forbade and a reliable
way to lose data to a runner killed mid-write:

``append``
    Newline-delimited JSON in the ephemeral raw layer. A write buffer, not a
    data layer.
``seal``
    One Parquet file per day, written once, with a manifest recording its row
    count and content hash. Never touched again.

Rollup merges 30-day-old daily partitions into a monthly file. It is the only
operation permitted to remove a file from the events tree, it verifies every
input hash first, and it preserves those hashes in its manifest so the
append-only claim stays checkable after the daily files are gone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .config import DEFAULT_TUNING, TuningParameters
from .records import Observation, Transition
from .schema import SCHEMA_VERSION

STORE_VERSION = "1.0.0"

TABLE_TRANSITIONS = "transitions"
TABLE_OBSERVATIONS = "observations"


@dataclass(frozen=True, slots=True)
class TableSpec:
    name: str
    uid_field: str
    partition_field: str
    sort_fields: tuple[str, ...]
    timestamp_fields: tuple[str, ...]
    list_fields: tuple[str, ...]
    bool_fields: tuple[str, ...]
    int_fields: tuple[str, ...]
    record_cls: type


TABLES: dict[str, TableSpec] = {
    TABLE_TRANSITIONS: TableSpec(
        name=TABLE_TRANSITIONS,
        uid_field="transition_uid",
        partition_field="t_latest",
        sort_fields=("entity_uid", "recorded_at", "t_latest", "transition_uid"),
        timestamp_fields=(
            "t_earliest",
            "t_latest",
            "t_source",
            "recorded_at",
            "ingested_at",
        ),
        list_fields=("quality_flags",),
        bool_fields=(),
        int_fields=("schema_version", "gap_before_s"),
        record_cls=Transition,
    ),
    TABLE_OBSERVATIONS: TableSpec(
        name=TABLE_OBSERVATIONS,
        uid_field="observation_id",
        partition_field="attempted_at",
        sort_fields=("source_id", "attempted_at", "observation_id"),
        timestamp_fields=("attempted_at", "observed_at", "source_updated_at"),
        list_fields=("warnings",),
        bool_fields=("complete", "trusted_for_resolution"),
        int_fields=(
            "schema_version",
            "entity_count",
            "advertised_count",
            "http_status",
            "latency_ms",
            "gap_before_s",
        ),
        record_cls=Observation,
    ),
}


class SealError(RuntimeError):
    """Raised instead of writing something that would break the contract."""


# --- staging ----------------------------------------------------------------


def append_rows(path: Path, rows: Iterable[dict]) -> int:
    """Append rows to the ephemeral JSONL buffer."""
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def staging_path(raw_root: Path, table: str, day: date) -> Path:
    return raw_root / "staging" / f"{table}-{day.isoformat()}.jsonl"


# --- paths ------------------------------------------------------------------


def daily_path(events_root: Path, table: str, day: date) -> Path:
    return events_root / table / f"date={day.isoformat()}" / f"{table}.parquet"


def monthly_path(events_root: Path, table: str, month: str) -> Path:
    return events_root / table / f"month={month}" / f"{table}.parquet"


def seal_manifest_path(manifest_root: Path, table: str, day: date) -> Path:
    return manifest_root / "seal" / f"{table}-{day.isoformat()}.json"


def rollup_manifest_path(manifest_root: Path, table: str, month: str) -> Path:
    return manifest_root / "rollup" / f"{table}-{month}.json"


# --- helpers ----------------------------------------------------------------


def _canonical(rows: Sequence[dict]) -> str:
    return json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_hash(rows: Sequence[dict]) -> str:
    """Hash of the row set itself, independent of file encoding.

    Parquet output is not byte-identical across writer versions, so idempotency
    is decided on content rather than on the file digest.
    """
    return hashlib.sha256(_canonical(rows).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _partition_day(spec: TableSpec, row: dict) -> date:
    value = row[spec.partition_field]
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    return moment.astimezone(timezone.utc).date()


def validate_rows(spec: TableSpec, rows: Sequence[dict]) -> list[dict]:
    """Round-trip every row through its record type.

    Rejects the seal rather than dropping rows: a partition that silently lost
    the rows it could not parse is worse than one that was never written.
    """
    validated = []
    for index, row in enumerate(rows):
        try:
            record = spec.record_cls.from_dict(row)
        except Exception as exc:  # noqa: BLE001 - re-raised with position
            raise SealError(f"row {index} is invalid: {exc}") from exc
        validated.append(record.to_dict())
    return validated


def deduplicate(spec: TableSpec, rows: Sequence[dict]) -> list[dict]:
    """Keep the earliest ingestion of each uid, so re-runs are no-ops."""
    best: dict[str, dict] = {}
    for row in rows:
        uid = row[spec.uid_field]
        existing = best.get(uid)
        if existing is None:
            best[uid] = row
            continue
        if (row.get("ingested_at") or "") < (existing.get("ingested_at") or ""):
            best[uid] = row
    return list(best.values())


def sort_rows(spec: TableSpec, rows: Sequence[dict]) -> list[dict]:
    def key(row: dict) -> tuple:
        return tuple(str(row.get(name) or "") for name in spec.sort_fields)

    return sorted(rows, key=key)


# --- arrow ------------------------------------------------------------------


def arrow_schema(table: str):
    """Parquet schema for a table. Imported lazily so the core needs no pyarrow."""
    import pyarrow as pa

    if table == TABLE_TRANSITIONS:
        names = [
            ("transition_uid", pa.string()),
            ("schema_version", pa.int16()),
            ("entity_uid", pa.string()),
            ("entity_type", pa.string()),
            ("source_id", pa.string()),
            ("source_native_id", pa.string()),
            ("transition_type", pa.string()),
            ("from_state", pa.string()),
            ("to_state", pa.string()),
            ("t_earliest", pa.timestamp("us", tz="UTC")),
            ("t_latest", pa.timestamp("us", tz="UTC")),
            ("t_source", pa.timestamp("us", tz="UTC")),
            ("recorded_at", pa.timestamp("us", tz="UTC")),
            ("certainty", pa.string()),
            ("evidence", pa.string()),
            ("observation_id", pa.string()),
            ("prev_observation_id", pa.string()),
            ("gap_before_s", pa.int32()),
            ("episode_id", pa.string()),
            ("station_id", pa.string()),
            ("station_name", pa.string()),
            ("line_id", pa.string()),
            ("status_text", pa.string()),
            ("quality_flags", pa.list_(pa.string())),
            ("corrects_transition_uid", pa.string()),
            ("correction_reason", pa.string()),
            ("run_id", pa.string()),
            ("parser_version", pa.string()),
            ("ingested_at", pa.timestamp("us", tz="UTC")),
        ]
    else:
        names = [
            ("observation_id", pa.string()),
            ("schema_version", pa.int16()),
            ("run_id", pa.string()),
            ("source_id", pa.string()),
            ("attempted_at", pa.timestamp("us", tz="UTC")),
            ("observed_at", pa.timestamp("us", tz="UTC")),
            ("source_updated_at", pa.timestamp("us", tz="UTC")),
            ("outcome", pa.string()),
            ("complete", pa.bool_()),
            ("trusted_for_resolution", pa.bool_()),
            ("entity_count", pa.int32()),
            ("advertised_count", pa.int32()),
            ("http_status", pa.int16()),
            ("latency_ms", pa.int32()),
            ("payload_sha256", pa.string()),
            ("gap_before_s", pa.int32()),
            ("warnings", pa.list_(pa.string())),
            ("collector_version", pa.string()),
            ("parser_version", pa.string()),
        ]
    return pa.schema([pa.field(name, dtype) for name, dtype in names])


def to_arrow(table: str, rows: Sequence[dict]):
    import pyarrow as pa

    schema = arrow_schema(table)
    columns = {}
    for field in schema:
        values = []
        for row in rows:
            value = row.get(field.name)
            if isinstance(value, str) and pa.types.is_timestamp(field.type):
                value = datetime.fromisoformat(value)
            values.append(value)
        columns[field.name] = pa.array(values, type=field.type)
    return pa.table(columns, schema=schema)


def write_parquet(table: str, rows: Sequence[dict], path: Path) -> None:
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".parquet.tmp")
    pq.write_table(
        to_arrow(table, rows),
        temporary,
        compression="zstd",
        compression_level=3,
        use_dictionary=True,
        write_statistics=True,
        write_page_checksum=True,
    )
    temporary.replace(path)


def read_parquet(path: Path) -> list[dict]:
    import pyarrow.parquet as pq

    rows = pq.read_table(path).to_pylist()
    for row in rows:
        for key, value in list(row.items()):
            if isinstance(value, datetime):
                row[key] = value.isoformat()
    return rows


# --- sealing ----------------------------------------------------------------


def seal_day(
    table: str,
    day: date,
    *,
    raw_root: Path,
    events_root: Path,
    manifest_root: Path,
    tuning: TuningParameters = DEFAULT_TUNING,
    rows: Sequence[dict] | None = None,
) -> dict:
    """Convert one day's staging buffer into an immutable partition.

    Sealing an already-sealed day is a no-op when the content matches, and an
    error when it does not — a sealed partition is never silently replaced.
    """
    spec = TABLES[table]
    source_rows = rows if rows is not None else read_jsonl(
        staging_path(raw_root, table, day)
    )

    prepared = sort_rows(spec, deduplicate(spec, validate_rows(spec, source_rows)))
    for row in prepared:
        if _partition_day(spec, row) != day:
            raise SealError(
                f"row {row[spec.uid_field]} belongs to "
                f"{_partition_day(spec, row)}, not to partition {day}"
            )

    digest = content_hash(prepared)
    target = daily_path(events_root, table, day)
    manifest_file = seal_manifest_path(manifest_root, table, day)

    if manifest_file.exists():
        existing = json.loads(manifest_file.read_text(encoding="utf-8"))
        if existing.get("content_sha256") == digest and target.exists():
            return existing
        raise SealError(
            f"partition {table}/date={day} is already sealed with different "
            f"content; corrections are new rows, never a rewrite"
        )

    write_parquet(table, prepared, target)

    timestamps = [
        row[spec.partition_field]
        for row in prepared
        if row.get(spec.partition_field)
    ]
    manifest = {
        "table": table,
        "partition": f"date={day.isoformat()}",
        "path": str(target.relative_to(events_root.parent))
        if events_root.parent in target.parents
        else str(target),
        "row_count": len(prepared),
        "content_sha256": digest,
        "file_sha256": file_hash(target),
        "min_partition_ts": min(timestamps) if timestamps else None,
        "max_partition_ts": max(timestamps) if timestamps else None,
        "distinct_entities": len(
            {row.get("entity_uid") for row in prepared if row.get("entity_uid")}
        ),
        "schema_version": SCHEMA_VERSION,
        "tuning_fingerprint": tuning.fingerprint(),
        "store_version": STORE_VERSION,
    }
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


# --- rollup -----------------------------------------------------------------


def list_daily_partitions(events_root: Path, table: str) -> list[date]:
    root = events_root / table
    if not root.exists():
        return []
    days = []
    for child in root.iterdir():
        if child.is_dir() and child.name.startswith("date="):
            days.append(date.fromisoformat(child.name.removeprefix("date=")))
    return sorted(days)


def rollup_month(
    table: str,
    month: str,
    *,
    events_root: Path,
    manifest_root: Path,
    tuning: TuningParameters = DEFAULT_TUNING,
    delete_dailies: bool = True,
) -> dict:
    """Merge a month of sealed daily partitions into one immutable file.

    Aborts on any mismatch rather than proceeding. Every absorbed file's hash
    and row count is recorded in the manifest, so the daily files can be removed
    without the provenance chain being removed with them.
    """
    spec = TABLES[table]
    target = monthly_path(events_root, table, month)
    manifest_file = rollup_manifest_path(manifest_root, table, month)
    if manifest_file.exists() and target.exists():
        return json.loads(manifest_file.read_text(encoding="utf-8"))

    days = [day for day in list_daily_partitions(events_root, table)
            if day.strftime("%Y-%m") == month]
    if not days:
        raise SealError(f"no sealed daily partitions for {table} in {month}")

    absorbed: list[dict] = []
    merged: list[dict] = []
    for day in days:
        seal_file = seal_manifest_path(manifest_root, table, day)
        if not seal_file.exists():
            raise SealError(f"missing seal manifest for {table} {day}")
        seal = json.loads(seal_file.read_text(encoding="utf-8"))
        path = daily_path(events_root, table, day)
        actual = file_hash(path)
        if actual != seal["file_sha256"]:
            raise SealError(
                f"{path} no longer matches its seal manifest; refusing to roll up"
            )
        rows = read_parquet(path)
        if len(rows) != seal["row_count"]:
            raise SealError(f"{path} row count changed since sealing")
        merged.extend(rows)
        absorbed.append(
            {
                "partition": f"date={day.isoformat()}",
                "row_count": seal["row_count"],
                "file_sha256": seal["file_sha256"],
                "content_sha256": seal["content_sha256"],
            }
        )

    uids = [row[spec.uid_field] for row in merged]
    if len(set(uids)) != len(uids):
        raise SealError("duplicate uid across daily partitions; refusing to roll up")
    if len(merged) != sum(item["row_count"] for item in absorbed):
        raise SealError("merged row count does not match the daily manifests")

    prepared = sort_rows(spec, merged)
    write_parquet(table, prepared, target)

    verified = read_parquet(target)
    if sorted(row[spec.uid_field] for row in verified) != sorted(uids):
        raise SealError("monthly file did not re-read to the same rows")

    manifest = {
        "table": table,
        "partition": f"month={month}",
        "row_count": len(prepared),
        "content_sha256": content_hash(prepared),
        "file_sha256": file_hash(target),
        "absorbed": absorbed,
        "schema_version": SCHEMA_VERSION,
        "tuning_fingerprint": tuning.fingerprint(),
        "store_version": STORE_VERSION,
    }
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if delete_dailies:
        for day in days:
            path = daily_path(events_root, table, day)
            path.unlink()
            if not any(path.parent.iterdir()):
                path.parent.rmdir()

    return manifest


# --- reading ----------------------------------------------------------------


def read_table(
    table: str,
    events_root: Path,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict]:
    """Read a table across daily and monthly partitions.

    The two partition key names differ, so a naive scan can never load a day
    twice — once from its own file and once from the month that absorbed it.
    """
    spec = TABLES[table]
    root = events_root / table
    if not root.exists():
        return []

    rows: list[dict] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        parquet = child / f"{table}.parquet"
        if parquet.exists():
            rows.extend(read_parquet(parquet))

    if start or end:
        def within(row: dict) -> bool:
            value = row.get(spec.partition_field)
            if not value:
                return False
            moment = datetime.fromisoformat(value)
            if start and moment < start:
                return False
            if end and moment >= end:
                return False
            return True

        rows = [row for row in rows if within(row)]

    return sort_rows(spec, rows)


def load_transitions(events_root: Path, **kwargs) -> list[Transition]:
    return [
        Transition.from_dict(row)
        for row in read_table(TABLE_TRANSITIONS, events_root, **kwargs)
    ]


def load_observations(events_root: Path, **kwargs) -> list[Observation]:
    return [
        Observation.from_dict(row)
        for row in read_table(TABLE_OBSERVATIONS, events_root, **kwargs)
    ]
