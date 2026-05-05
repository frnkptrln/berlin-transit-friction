from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class FrictionEvent(BaseModel):
    event_id: str
    source: str
    collected_at: datetime
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    mode: str | None = None
    operator: str | None = None
    line: str | None = None
    direction: str | None = None
    stop_id: str | None = None
    stop_name: str | None = None
    category: str
    severity: int = Field(ge=0, le=4)
    title: str
    description: str | None = None
    raw_reference: str | None = None
    url: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    raw: dict | None = None
