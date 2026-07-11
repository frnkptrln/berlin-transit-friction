from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class ElevatorOutageObservation:
    asset_id: str
    station_id: str
    station_name: str
    status_text: str
    source_url: str
    source_updated_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("asset_id is required")
        if not self.station_id:
            raise ValueError("station_id is required")
        if not self.station_name:
            raise ValueError("station_name is required")
        require_aware(self.source_updated_at, "source_updated_at")
        require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class OutageSnapshot:
    source_url: str
    observed_at: datetime
    source_updated_at: datetime | None
    outages: tuple[ElevatorOutageObservation, ...]
    complete: bool
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if self.source_updated_at is not None:
            require_aware(self.source_updated_at, "source_updated_at")
        if self.complete and self.source_updated_at is None:
            raise ValueError("a complete snapshot needs source_updated_at")

    @classmethod
    def failed(
        cls,
        *,
        source_url: str,
        observed_at: datetime,
        warning: str,
    ) -> "OutageSnapshot":
        return cls(
            source_url=source_url,
            observed_at=observed_at,
            source_updated_at=None,
            outages=(),
            complete=False,
            warnings=(warning,),
        )
