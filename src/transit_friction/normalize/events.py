from __future__ import annotations

import hashlib
from datetime import datetime


def stable_event_id(source, category, line, stop_name, title, valid_from):
    key = "|".join([
        source or "",
        category or "",
        line or "",
        stop_name or "",
        title or "",
        valid_from.isoformat() if isinstance(valid_from, datetime) else str(valid_from or ""),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def classify_category(raw_text: str | None) -> str:
    t = (raw_text or "").lower()
    if any(k in t for k in ["cancel", "ausfall"]):
        return "cancellation"
    if any(k in t for k in ["delay", "verspät", "spaet"]):
        return "delay"
    if any(k in t for k in ["construction", "bau", "maintenance"]):
        return "construction"
    if any(k in t for k in ["replacement bus", "ersatzverkehr"]):
        return "replacement_service"
    if any(k in t for k in ["platform", "gleis"]):
        return "platform_change"
    if any(k in t for k in ["lift", "elevator", "aufzug", "barrier-free"]):
        return "elevator_or_accessibility_issue"
    if any(k in t for k in ["skip stop", "entfällt halt"]):
        return "skipped_stop"
    if any(k in t for k in ["crowd", "overcrowd"]):
        return "crowding_signal"
    if t.strip():
        return "disruption"
    return "unknown"


def estimate_severity(category: str, text: str | None) -> int:
    t = (text or "").lower()
    if category in {"construction", "information_gap"}:
        base = 1
    elif category in {"delay", "platform_change", "elevator_or_accessibility_issue"}:
        base = 2
    elif category in {"cancellation", "replacement_service", "skipped_stop", "disruption"}:
        base = 3
    elif category == "crowding_signal":
        base = 1
    else:
        base = 0
    if any(k in t for k in ["major", "network", "all lines", "massive"]):
        return 4
    return max(0, min(4, base))
