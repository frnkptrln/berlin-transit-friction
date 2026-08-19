#!/usr/bin/env python3
"""Build enriched site data JSON files for the dashboard.

Reads Gold daily summaries and Silver event data to produce:
- site/data/latest.json          — today's headline metrics
- site/data/daily-index.json     — per-day event totals (all time)
- site/data/daily-detail.json    — last 30 days with category/line/severity breakdowns
- site/data/line-stats.json      — per-line friction scores
- site/data/station-stats.json   — per-station delay/cancellation counts
- site/data/timeline.json        — hourly event buckets for sparklines
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
from transit_friction.config import OUTPUT_ROOT as BASE
GOLD_DAILY = BASE / "data/gold/daily"
SILVER_FRICTION = BASE / "data/silver/friction_events"
SILVER_DEPARTURES = BASE / "data/silver/departure_observations"
SILVER_JOURNEYS = BASE / "data/silver/journey_observations"
SITE = BASE / "site/data"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _read_gold_daily(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build():
    SITE.mkdir(parents=True, exist_ok=True)

    # ── Daily index (all time) ──────────────────────────────────────────
    daily_files = sorted(GOLD_DAILY.glob("*.json"))
    daily_index = []
    daily_details = []

    for f in daily_files:
        g = _read_gold_daily(f)
        if not g.get("date"):
            continue
        daily_index.append({
            "date": g["date"],
            "total_events": g.get("total_events", 0),
        })
        daily_details.append({
            "date": g["date"],
            "total_events": g.get("total_events", 0),
            "events_by_source": g.get("events_by_source", {}),
            "events_by_category": g.get("events_by_category", {}),
            "events_by_line": g.get("events_by_line", {}),
            "accessibility_friction": g.get("accessibility_friction", 0),
            "data_coverage": g.get("data_coverage", {}),
            "connection_watchlist_count": g.get("connection_watchlist_count", 0),
            "stations_with_most_delayed_departures": g.get("stations_with_most_delayed_departures", []),
        })

    # Keep last 30 days of detail
    daily_details = daily_details[-30:]

    # ── Latest ──────────────────────────────────────────────────────────
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    latest_gold = _read_gold_daily(GOLD_DAILY / f"{today}.json") if (GOLD_DAILY / f"{today}.json").exists() else {}

    # Fall back to most recent day if today has no data yet
    if not latest_gold and daily_files:
        latest_gold = _read_gold_daily(daily_files[-1])

    latest = {
        "date": latest_gold.get("date", today),
        "total_events": latest_gold.get("total_events", 0),
        "events_by_category": latest_gold.get("events_by_category", {}),
        "events_by_source": latest_gold.get("events_by_source", {}),
        "events_by_line": latest_gold.get("events_by_line", {}),
        "accessibility_friction": latest_gold.get("accessibility_friction", 0),
        "data_coverage": latest_gold.get("data_coverage", {}),
        "severe_events": latest_gold.get("severe", [])[:5],
        "connection_watchlist_count": latest_gold.get("connection_watchlist_count", 0),
        "worst_relation": latest_gold.get("worst_relation_by_delay_delta"),
        "relations_with_cancellations": latest_gold.get("relations_with_cancellations", []),
        "stations_with_most_delayed_departures": latest_gold.get("stations_with_most_delayed_departures", []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── Line stats (aggregated over available silver data) ──────────────
    line_friction = defaultdict(lambda: {"events": 0, "delays": 0, "cancellations": 0, "severity_sum": 0, "days_seen": set()})

    for sf in sorted(SILVER_FRICTION.glob("*.jsonl")):
        day = sf.stem
        for ev in _read_jsonl(sf):
            line_name = ev.get("line")
            if not line_name:
                continue
            lf = line_friction[line_name]
            lf["events"] += 1
            lf["days_seen"].add(day)
            cat = ev.get("category", "")
            if cat == "delay":
                lf["delays"] += 1
            elif cat == "cancellation":
                lf["cancellations"] += 1
            lf["severity_sum"] += int(ev.get("severity", 0))

    line_stats = []
    for line_name, lf in sorted(line_friction.items(), key=lambda x: -x[1]["events"]):
        line_stats.append({
            "line": line_name,
            "total_events": lf["events"],
            "delays": lf["delays"],
            "cancellations": lf["cancellations"],
            "severity_avg": round(lf["severity_sum"] / max(lf["events"], 1), 1),
            "days_active": len(lf["days_seen"]),
            "friction_score": round(lf["events"] + lf["cancellations"] * 3 + lf["severity_sum"] * 0.5, 1),
        })

    # ── Station stats (from departure observations) ─────────────────────
    station_counts = defaultdict(lambda: {"delays": 0, "cancellations": 0, "total_obs": 0})

    for sf in sorted(SILVER_DEPARTURES.glob("*.jsonl"))[-7:]:  # last 7 days
        for dep in _read_jsonl(sf):
            stop = dep.get("stop_name")
            if not stop:
                continue
            sc = station_counts[stop]
            sc["total_obs"] += 1
            if dep.get("cancelled"):
                sc["cancellations"] += 1
            if (dep.get("delay_seconds") or 0) > 0:
                sc["delays"] += 1

    station_stats = []
    for stop_name, sc in sorted(station_counts.items(), key=lambda x: -(x[1]["delays"] + x[1]["cancellations"])):
        station_stats.append({
            "station": stop_name,
            "delays": sc["delays"],
            "cancellations": sc["cancellations"],
            "total_observations": sc["total_obs"],
            "friction_rate": round((sc["delays"] + sc["cancellations"]) / max(sc["total_obs"], 1), 2),
        })

    # ── Timeline (hourly event buckets over last 7 days) ────────────────
    timeline_buckets = defaultdict(int)
    for sf in sorted(SILVER_FRICTION.glob("*.jsonl"))[-7:]:
        for ev in _read_jsonl(sf):
            ts = ev.get("collected_at", "")
            if len(ts) >= 13:
                bucket = ts[:13]  # "2026-05-08T14" → hourly bucket
                timeline_buckets[bucket] += 1

    timeline = [{"hour": k, "events": v} for k, v in sorted(timeline_buckets.items())]

    # ── Live Map GeoJSON ────────────────────────────────────────────────
    # We use a static dictionary of major hubs for MVP visualization.
    # In a full production setup, this would be joined against GTFS stops.txt.
    geo_dict = {
        "900000003201": [13.386, 52.520], # Friedrichstr
        "900000100003": [13.369, 52.525], # Hbf
        "900000024101": [13.411, 52.521], # Alexanderplatz
        "zoologischer garten": [13.332, 52.506],
        "ostkreuz": [13.469, 52.503],
        "südkreuz": [13.365, 52.475],
        "gesundbrunnen": [13.388, 52.548],
        "neukölln": [13.430, 52.469],
        "schönhauser allee": [13.414, 52.549],
    }

    features = []
    active_path = BASE / "data/state/active_events.json"
    if active_path.exists():
        try:
            active_events = json.loads(active_path.read_text(encoding="utf-8"))
            for eid, ev in active_events.items():
                lon, lat = 13.405, 52.520  # Default to Berlin center
                found_loc = False
                
                # Try to map by stop ID or stop name
                stop_name = ev.get("stop_name", "").lower()
                if stop_name in geo_dict:
                    lon, lat = geo_dict[stop_name]
                    found_loc = True
                else:
                    for key, coords in geo_dict.items():
                        if key in stop_name:
                            lon, lat = coords
                            found_loc = True
                            break
                            
                # For network-wide events, we randomly jitter around the center 
                # so they don't stack perfectly on top of each other.
                if not found_loc:
                    import random
                    lon += random.uniform(-0.05, 0.05)
                    lat += random.uniform(-0.05, 0.05)

                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lon, lat]
                    },
                    "properties": {
                        "event_id": eid,
                        "category": ev.get("category"),
                        "severity": ev.get("severity", 1),
                        "line": ev.get("line"),
                        "title": ev.get("title"),
                        "state": ev.get("event_state"),
                        "time_active_mins": int((datetime.now(timezone.utc) - datetime.fromisoformat(ev.get("first_seen_at"))).total_seconds() / 60) if ev.get("first_seen_at") else 0
                    }
                })
        except Exception as e:
            print(f"Error generating geojson: {e}")

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    # ── Write all outputs ───────────────────────────────────────────────
    (SITE / "latest.json").write_text(json.dumps(latest, indent=2, default=str), encoding="utf-8")
    (SITE / "daily-index.json").write_text(json.dumps(daily_index, indent=2), encoding="utf-8")
    (SITE / "daily-detail.json").write_text(json.dumps(daily_details, indent=2), encoding="utf-8")
    (SITE / "line-stats.json").write_text(json.dumps(line_stats, indent=2), encoding="utf-8")
    (SITE / "station-stats.json").write_text(json.dumps(station_stats, indent=2), encoding="utf-8")
    (SITE / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    (SITE / "live-map.geojson").write_text(json.dumps(geojson, indent=2), encoding="utf-8")

    print(f"site data built: {len(daily_index)} days, {len(line_stats)} lines, {len(station_stats)} stations, {len(timeline)} timeline buckets, {len(features)} live map events")


if __name__ == "__main__":
    build()
