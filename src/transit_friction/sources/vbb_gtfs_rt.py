from __future__ import annotations
import hashlib
from datetime import datetime, timezone
try:
    import requests
    from google.transit import gtfs_realtime_pb2
except ImportError:
    requests = None
    gtfs_realtime_pb2 = None

from transit_friction.config import DEFAULT_TIMEOUT, USER_AGENT
from transit_friction.sources.base import SourceResult
from transit_friction.normalize.events import stable_event_id

GTFS_URL = "https://production.gtfsrt.vbb.de/data"


def collect(now: datetime | None = None) -> SourceResult:
    now = now or datetime.now(timezone.utc)
    source_id = "vbb_gtfs_rt"

    if requests is None or gtfs_realtime_pb2 is None:
        return SourceResult(
            source_id=source_id,
            collected_at=now,
            success=False,
            warnings=["requests or gtfs-realtime-bindings missing"],
            duration_ms=0
        )

    t0 = datetime.now()
    try:
        headers = {"User-Agent": USER_AGENT}
        r = requests.get(GTFS_URL, headers=headers, timeout=DEFAULT_TIMEOUT)
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

        payload = r.content
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(payload)

        raw_record = {
            "collected_at": now.isoformat(),
            "source": source_id,
            "endpoint": GTFS_URL,
            "status_code": r.status_code,
            "content_length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "entity_count": len(feed.entity),
            "parser_status": "full_parse",
            "warnings": []
        }

        normalized = []
        for entity in feed.entity:
            # Check for alerts
            if entity.HasField('alert'):
                alert = entity.alert
                text = ""
                if alert.header_text.translation:
                    text += alert.header_text.translation[0].text + " "
                if alert.description_text.translation:
                    text += alert.description_text.translation[0].text
                
                if not text:
                    continue
                    
                category = "disruption"
                severity = 2
                if alert.effect == gtfs_realtime_pb2.Alert.NO_SERVICE:
                    category = "cancellation"
                    severity = 3
                elif alert.effect == gtfs_realtime_pb2.Alert.REDUCED_SERVICE:
                    category = "replacement_service"
                elif alert.effect == gtfs_realtime_pb2.Alert.SIGNIFICANT_DELAYS:
                    category = "delay"

                eid = stable_event_id(source_id, category, None, None, f"GTFS Alert: {entity.id}", now)
                normalized.append({
                    "event_id": eid,
                    "source": source_id,
                    "collected_at": now.isoformat(),
                    "first_seen_at": now.isoformat(),
                    "last_seen_at": now.isoformat(),
                    "event_state": "observed",
                    "category": category,
                    "severity": severity,
                    "title": f"GTFS Alert: {category}",
                    "description": text[:500],
                    "confidence": 0.9,
                })

            # Check for TripUpdates (Delays)
            elif entity.HasField('trip_update'):
                tu = entity.trip_update
                for stu in tu.stop_time_update:
                    if stu.HasField('departure') and stu.departure.HasField('delay'):
                        delay = stu.departure.delay
                        if delay >= 300:  # 5 minutes+ delay
                            category = "delay"
                            severity = 2 if delay < 900 else 3
                            title = "GTFS Trip Delay"
                            stop_id = stu.stop_id
                            route_id = tu.trip.route_id
                            
                            eid = stable_event_id(source_id, category, route_id, stop_id, title, now)
                            normalized.append({
                                "event_id": eid,
                                "source": source_id,
                                "collected_at": now.isoformat(),
                                "first_seen_at": now.isoformat(),
                                "last_seen_at": now.isoformat(),
                                "event_state": "observed",
                                "line": route_id,
                                "stop_name": stop_id,
                                "category": category,
                                "severity": severity,
                                "title": title,
                                "description": f"Delay of {delay} seconds on route {route_id} at stop {stop_id}",
                                "confidence": 0.9,
                            })

        return SourceResult(
            source_id=source_id,
            collected_at=now,
            success=True,
            status_code=r.status_code,
            raw_records=raw_record,
            normalized_events=normalized[:1000],  # Cap to prevent explosive growth
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
