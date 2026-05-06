#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, time
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
from transit_friction.config import BASE_DIR
from transit_friction.storage import write_json_gz, write_jsonl, sha256_bytes
from transit_friction.sources.base import SourceResult
from transit_friction.normalize.events import classify_category, estimate_severity, stable_event_id

try:
    import requests
except Exception:
    requests = None

FREQUENT = ["vbb_gtfs_rt","brokenlifts","vbb_transport_rest","bvg_transport_rest"]
HOURLY = ["bvg_traffic_news","sbahn_disruptions","viz_public_transport","bvg_disturbed_network_wfs","vbb_fahrinfo_api"]
ALL = list(dict.fromkeys(FREQUENT+HOURLY))
PROBE_STOPS = ["900000003201", "900000100003", "900000024101"]  # Friedrichstr, Hbf, Alexanderplatz


def _collect_departure_events(source_id: str, departures: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    events = []
    sightings = []
    for d in departures:
        remarks_blob = d.get("remarks") or []
        remark_text = json.dumps(remarks_blob, ensure_ascii=False) if remarks_blob else ""
        category = classify_category(remark_text)
        reason = "remarks"

        delay_seconds = d.get("delay")
        cancelled = bool(d.get("cancelled"))
        if cancelled:
            category = "cancellation"
            remark_text = f"{remark_text} cancelled=true".strip()
            reason = "cancelled_field"
        elif category == "unknown" and isinstance(delay_seconds, (int, float)) and abs(delay_seconds) >= 300:
            category = "delay"
            remark_text = f"{remark_text} delay_seconds={int(delay_seconds)}".strip()
            reason = "delay_field"

        if category == "unknown":
            continue

        title = f"{source_id} departure signal"
        events.append({
            "event_id": stable_event_id(source_id, category, d.get("line", {}).get("name"), d.get("stop", {}).get("name"), title, now),
            "source": source_id,
            "collected_at": now.isoformat(),
            "first_seen_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "event_state": "observed",
            "line": d.get("line", {}).get("name"),
            "stop_name": d.get("stop", {}).get("name"),
            "category": category,
            "severity": estimate_severity(category, remark_text),
            "title": title,
            "description": remark_text[:300] if remark_text else "Derived from realtime departure fields.",
            "confidence": 0.6 if remarks_blob else 0.5,
            "lines": [],
            "stops": [],
        })
        sightings.append({
            "source": source_id,
            "line": d.get("line", {}).get("name"),
            "stop_name": d.get("stop", {}).get("name"),
            "when": d.get("when") or d.get("plannedWhen"),
            "category": category,
            "reason": reason,
            "delay_seconds": delay_seconds,
            "cancelled": cancelled,
            "remark_excerpt": remark_text[:300],
        })
    return events, sightings

def fetch(source_id, no_network=False):
    t0=time.time(); now=datetime.now(timezone.utc)
    if no_network or requests is None:
        return SourceResult(source_id, now, False, warnings=["network disabled or requests missing"], errors=[], duration_ms=int((time.time()-t0)*1000))
    try:
        if source_id=="vbb_gtfs_rt":
            url="https://production.gtfsrt.vbb.de/data"; r=requests.get(url,timeout=20)
            payload=r.content
            raw={"collected_at":now.isoformat(),"source":source_id,"endpoint":url,"status_code":r.status_code,"content_length":len(payload),"sha256":sha256_bytes(payload),"entity_count":None,"parser_status":"metadata_only","warnings":[]}
            return SourceResult(source_id, now, r.ok, r.status_code, raw_records=raw, duration_ms=int((time.time()-t0)*1000), warnings=[] if r.ok else ["http failure"])
        if source_id=="brokenlifts":
            url="https://brokenlifts.org/"; r=requests.get(url,timeout=20)
            txt=r.text[:20000]
            rec={"url":url,"status_code":r.status_code,"snippet":txt[:1000],"contains_lift":("lift" in txt.lower() or "aufzug" in txt.lower())}
            events=[]
            if rec["contains_lift"]:
                cat="elevator_or_accessibility_issue"; title="Potential elevator outage signals"
                events.append({"event_id":stable_event_id(source_id,cat,None,None,title,now),"source":source_id,"collected_at":now.isoformat(),"first_seen_at":now.isoformat(),"last_seen_at":now.isoformat(),"event_state":"observed","category":cat,"severity":2,"title":title,"description":"Keyword signal from BrokenLifts landing content.","confidence":0.3,"lines":[],"stops":[]})
            return SourceResult(source_id, now, r.ok, r.status_code, raw_records=rec, normalized_events=events, duration_ms=int((time.time()-t0)*1000))
        if source_id in {"vbb_transport_rest","bvg_transport_rest"}:
            base_candidates = (
                ["https://v6.vbb.transport.rest", "https://v5.vbb.transport.rest"]
                if source_id.startswith("vbb")
                else ["https://v6.bvg.transport.rest", "https://v5.bvg.transport.rest"]
            )
            all_departures = []
            status_code = None
            endpoint = None
            last_error = None
            for base in base_candidates:
                try:
                    for stop_id in PROBE_STOPS:
                        endpoint = f"{base}/stops/{stop_id}/departures"
                        r = requests.get(endpoint, params={"duration": 120, "remarks": True}, timeout=20)
                        status_code = r.status_code
                        if r.ok:
                            all_departures.extend(r.json() or [])
                    if all_departures:
                        break
                except Exception as e:
                    last_error = str(e)
            events, sightings = _collect_departure_events(source_id, all_departures, now)
            success = bool(all_departures)
            warnings = []
            if not success:
                warnings.append(last_error or "no departures returned from configured transport.rest endpoints")
            return SourceResult(source_id, now, success, status_code, raw_records={"count":len(all_departures), "endpoint": endpoint, "sightings_count": len(sightings), "sightings_preview": sightings[:25]}, normalized_events=events, duration_ms=int((time.time()-t0)*1000), warnings=warnings)
        return SourceResult(source_id, now, False, warnings=["not implemented"], errors=["not implemented"], duration_ms=int((time.time()-t0)*1000))
    except Exception as e:
        return SourceResult(source_id, now, False, warnings=[str(e)], errors=[str(e)], duration_ms=int((time.time()-t0)*1000))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--source"); ap.add_argument("--all", action="store_true"); ap.add_argument("--frequent",action="store_true"); ap.add_argument("--hourly",action="store_true"); ap.add_argument("--daily",action="store_true"); ap.add_argument("--no-network",action="store_true"); ap.add_argument("--date"); ap.add_argument("--dry-run",action="store_true")
    a=ap.parse_args(); now=datetime.now(timezone.utc)
    run_id=now.strftime("%Y%m%dT%H%M%SZ")
    ids=[a.source] if a.source else (ALL if a.all else FREQUENT if a.frequent or (not a.hourly and not a.daily) else HOURLY)
    bronze=[]; silver=[]; results=[]; warns=[]
    for sid in ids:
        res=fetch(sid, a.no_network); results.append(res)
        if res.warnings: warns.extend([f"{sid}: {w}" for w in res.warnings])
        if not a.dry_run and res.raw_records is not None:
            b=BASE_DIR/"data/bronze"/sid/now.strftime("%Y/%m/%d")/f"{now.strftime('%H%M%S')}.json.gz"; write_json_gz(b,res.raw_records); bronze.append(str(b.relative_to(BASE_DIR)))
        if res.normalized_events: silver.extend(res.normalized_events)
    silver_path=BASE_DIR/"data/silver/friction_events"/f"{(a.date or now.strftime('%Y-%m-%d'))}.jsonl"
    if not a.dry_run and silver: write_jsonl(silver_path, silver, append=True)
    manifest={"run_id":run_id,"started_at":now.isoformat(),"finished_at":datetime.now(timezone.utc).isoformat(),"git_sha":"unknown","sources_attempted":ids,"sources_succeeded":[r.source_id for r in results if r.success],"sources_failed":[r.source_id for r in results if not r.success],"source_results":[{"source_id":r.source_id,"success":r.success,"status_code":r.status_code,"event_count":len(r.normalized_events),"warnings":r.warnings,"duration_ms":r.duration_ms,"parser_status":r.parser_version} for r in results],"bronze_files_written":bronze,"silver_files_written":[str(silver_path.relative_to(BASE_DIR))] if silver and not a.dry_run else [],"normalized_event_count":len(silver),"warnings":warns,"dependency_warnings":[] if requests else ["requests missing"],"rate_limit_notes":"conservative MVP polling","raw_storage_policy":"compact_json_gz_no_raw_protobuf"}
    manifest_path = BASE_DIR/"data/manifests"/now.strftime("%Y/%m/%d")/f"{now.strftime('%H%M%S')}.json"
    manifest["manifest_path"] = str(manifest_path.relative_to(BASE_DIR))
    if not a.dry_run:
        manifest_path.parent.mkdir(parents=True,exist_ok=True)
        manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest, indent=2))

if __name__=="__main__": main()
