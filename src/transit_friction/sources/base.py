from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class SourceResult:
    source_id: str
    collected_at: datetime
    success: bool
    status_code: int | None = None
    raw_records: list | dict | None = None
    normalized_events: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    bronze_path: str | None = None
    parser_version: str = "0.2"
    duration_ms: int = 0
