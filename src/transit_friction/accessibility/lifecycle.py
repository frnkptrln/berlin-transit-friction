from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .models import ElevatorOutageObservation, OutageSnapshot, require_aware

STATE_VERSION = 1


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _outage_id(asset_id: str, first_seen_at: datetime) -> str:
    payload = f"brokenlifts|{asset_id}|{first_seen_at.isoformat()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class ActiveOutage:
    outage_id: str
    asset_id: str
    station_id: str
    station_name: str
    status_text: str
    source_url: str
    first_seen_at: datetime
    last_seen_at: datetime
    source_updated_at: datetime
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(self.first_seen_at, "first_seen_at")
        require_aware(self.last_seen_at, "last_seen_at")
        require_aware(self.source_updated_at, "source_updated_at")
        if self.resolved_at is not None:
            require_aware(self.resolved_at, "resolved_at")

    @classmethod
    def from_observation(cls, observation: ElevatorOutageObservation) -> "ActiveOutage":
        return cls(
            outage_id=_outage_id(observation.asset_id, observation.observed_at),
            asset_id=observation.asset_id,
            station_id=observation.station_id,
            station_name=observation.station_name,
            status_text=observation.status_text,
            source_url=observation.source_url,
            first_seen_at=observation.observed_at,
            last_seen_at=observation.observed_at,
            source_updated_at=observation.source_updated_at,
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "outage_id": self.outage_id,
            "asset_id": self.asset_id,
            "station_id": self.station_id,
            "station_name": self.station_name,
            "status_text": self.status_text,
            "source_url": self.source_url,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "source_updated_at": self.source_updated_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ActiveOutage":
        return cls(
            outage_id=payload["outage_id"],
            asset_id=payload["asset_id"],
            station_id=payload["station_id"],
            station_name=payload["station_name"],
            status_text=payload.get("status_text", ""),
            source_url=payload["source_url"],
            first_seen_at=_parse_datetime(payload["first_seen_at"]),
            last_seen_at=_parse_datetime(payload["last_seen_at"]),
            source_updated_at=_parse_datetime(payload["source_updated_at"]),
            resolved_at=_parse_datetime(payload.get("resolved_at")),
        )


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    active: dict[str, ActiveOutage]
    new: tuple[ActiveOutage, ...]
    ongoing: tuple[ActiveOutage, ...]
    resolved: tuple[ActiveOutage, ...]
    resolution_allowed: bool


def reconcile(
    active: dict[str, ActiveOutage],
    snapshot: OutageSnapshot,
) -> ReconcileResult:
    next_active = dict(active)
    new: list[ActiveOutage] = []
    ongoing: list[ActiveOutage] = []

    latest_source_timestamp = max(
        (outage.source_updated_at for outage in active.values()),
        default=None,
    )
    resolution_allowed = bool(
        snapshot.complete
        and snapshot.source_updated_at is not None
        and (
            latest_source_timestamp is None
            or snapshot.source_updated_at > latest_source_timestamp
        )
    )

    observed_ids: set[str] = set()
    for observation in snapshot.outages:
        observed_ids.add(observation.asset_id)
        current = next_active.get(observation.asset_id)
        if current is None:
            current = ActiveOutage.from_observation(observation)
            next_active[observation.asset_id] = current
            new.append(current)
            continue

        updated = replace(
            current,
            station_id=observation.station_id,
            station_name=observation.station_name,
            status_text=observation.status_text,
            source_url=observation.source_url,
            last_seen_at=max(current.last_seen_at, observation.observed_at),
            source_updated_at=max(
                current.source_updated_at, observation.source_updated_at
            ),
        )
        next_active[observation.asset_id] = updated
        ongoing.append(updated)

    resolved: list[ActiveOutage] = []
    if resolution_allowed:
        for asset_id in sorted(set(next_active) - observed_ids):
            outage = next_active.pop(asset_id)
            resolved.append(replace(outage, resolved_at=snapshot.observed_at))

    return ReconcileResult(
        active=next_active,
        new=tuple(new),
        ongoing=tuple(ongoing),
        resolved=tuple(resolved),
        resolution_allowed=resolution_allowed,
    )


def load_state(path: Path) -> dict[str, ActiveOutage]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != STATE_VERSION:
        raise ValueError("unsupported accessibility state version")
    return {
        asset_id: ActiveOutage.from_dict(outage)
        for asset_id, outage in payload.get("active", {}).items()
    }


def save_state(path: Path, active: dict[str, ActiveOutage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_VERSION,
        "active": {
            asset_id: outage.to_dict()
            for asset_id, outage in sorted(active.items())
        },
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
