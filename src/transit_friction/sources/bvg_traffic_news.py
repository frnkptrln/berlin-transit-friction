from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

from transit_friction.config import DEFAULT_TIMEOUT, BASE_DIR
from transit_friction.storage import write_json_gz, sha256_bytes
from transit_friction.sources.base import SourceResult
from transit_friction.normalize.events import stable_event_id

URL = "https://www.bvg.de/de/verbindungen/stoerungsmeldungen"


def parse_html(html: str) -> list[dict]:
    if not BeautifulSoup:
        return []
    soup = BeautifulSoup(html, "html.parser")
    events = []
    
    # Very basic defensive parsing for a common Next.js/React structure
    # This will likely need adjustment as BVG updates their DOM, 
    # but serves as the required MVP scraper.
    for article in soup.find_all(["article", "div"], class_=lambda x: x and ("message" in x.lower() or "disruption" in x.lower() or "stoerung" in x.lower())):
        text = article.get_text(separator=" ", strip=True)
        if not text:
            continue
            
        events.append({
            "raw_text": text,
            "html_snippet": str(article)[:500]
        })
    return events


def normalize_events(raw_events: list[dict], now: datetime) -> list[dict]:
    normalized = []
    for raw in raw_events:
        text = raw["raw_text"].lower()
        
        # Heuristic categorization
        category = "disruption"
        if "bau" in text or "sperrung" in text:
            category = "construction"
        elif "ersatz" in text or "sev" in text:
            category = "replacement_service"
        elif "ausfall" in text:
            category = "cancellation"
        elif "verspätung" in text:
            category = "delay"
            
        severity = 2
        if category in ["cancellation", "replacement_service"]:
            severity = 3
        if "massiv" in text or "alle linien" in text:
            severity = 4

        # Extract lines (e.g. U8, M10, 100)
        import re
        lines = list(set(re.findall(r'\b([USM]\d{1,2}|\d{3}|X\d{1,2}|N\d{1,2})\b', raw["raw_text"])))
        
        for line in (lines if lines else [None]):
            title = f"BVG Traffic News: {category.capitalize()}"
            eid = stable_event_id("bvg_traffic_news", category, line, None, title, now)
            normalized.append({
                "event_id": eid,
                "source": "bvg_traffic_news",
                "collected_at": now.isoformat(),
                "first_seen_at": now.isoformat(),
                "last_seen_at": now.isoformat(),
                "event_state": "observed",
                "line": line,
                "lines": lines,
                "category": category,
                "severity": severity,
                "title": title,
                "description": raw["raw_text"][:500],
                "confidence": 0.8,
            })
    return normalized


def collect(now: datetime | None = None) -> SourceResult:
    now = now or datetime.now(timezone.utc)
    source_id = "bvg_traffic_news"
    
    if requests is None or BeautifulSoup is None:
        return SourceResult(
            source_id=source_id,
            collected_at=now,
            success=False,
            warnings=["requests or beautifulsoup4 missing"],
            duration_ms=0
        )
        
    t0 = datetime.now()
    try:
        r = requests.get(URL, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": "transit-friction/0.2"})
        duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        
        if not r.ok:
            return SourceResult(
                source_id=source_id,
                collected_at=now,
                success=False,
                status_code=r.status_code,
                warnings=[f"HTTP {r.status_code}"],
                duration_ms=duration_ms
            )
            
        html = r.text
        raw_events = parse_html(html)
        
        raw_record = {
            "url": URL,
            "status_code": r.status_code,
            "html_length": len(html),
            "sha256": sha256_bytes(html.encode("utf-8")),
            "extracted_count": len(raw_events),
            "samples": raw_events[:3]
        }
        
        normalized = normalize_events(raw_events, now)
        
        return SourceResult(
            source_id=source_id,
            collected_at=now,
            success=True,
            status_code=r.status_code,
            raw_records=raw_record,
            normalized_events=normalized,
            duration_ms=duration_ms
        )
    except Exception as e:
        duration_ms = int((datetime.now() - t0).total_seconds() * 1000)
        return SourceResult(
            source_id=source_id,
            collected_at=now,
            success=False,
            warnings=[str(e)],
            errors=[str(e)],
            duration_ms=duration_ms
        )
