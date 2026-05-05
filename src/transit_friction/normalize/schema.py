from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field

class FrictionEvent(BaseModel):
    event_id: str
    source: str
    source_event_id: str | None = None
    source_url: str | None = None
    raw_hash: str | None = None
    collected_at: datetime
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    event_state: str = "unknown"
    line: str | None = None
    lines: list[str] = []
    stop_id: str | None = None
    stop_name: str | None = None
    stops: list[str] = []
    mode: str | None = None
    operator: str | None = None
    category: str
    severity: int = Field(ge=0, le=4)
    title: str
    description: str | None = None
    confidence: float = Field(ge=0, le=1)
    uncertainty_notes: str | None = None
