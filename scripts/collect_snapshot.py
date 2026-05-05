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
            base="https://v6.vbb.transport.rest" if source_id.startswith("vbb") else "https://v6.bvg.transport.rest"
            r=requests.get(f"{base}/stops/900000003201/departures", params={"duration":30,"remarks":True}, timeout=20)
            js=r.json() if r.ok else []
            events=[]
            for d in js[:20]:
                t=(d.get("remarks") and json.dumps(d.get("remarks"))) or ""
                cat=classify_category(t)
                if cat=="unknown":
                    continue
                title=f"{source_id} departure remark"
                events.append({"event_id":stable_event_id(source_id,cat,d.get('line',{}).get('name'),d.get('stop',{}).get('name'),title,now),"source":source_id,"collected_at":now.isoformat(),"first_seen_at":now.isoformat(),"last_seen_at":now.isoformat(),"event_state":"observed","line":d.get("line",{}).get("name"),"stop_name":d.get("stop",{}).get("name"),"category":cat,"severity":estimate_severity(cat,t),"title":title,"description":t[:300],"confidence":0.6,"lines":[],"stops":[]})
            return SourceResult(source_id, now, r.ok, r.status_code, raw_records={"count":len(js)}, normalized_events=events, duration_ms=int((time.time()-t0)*1000))
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
    if not a.dry_run:
        m=BASE_DIR/"data/manifests"/now.strftime("%Y/%m/%d")/f"{now.strftime('%H%M%S')}.json"; m.parent.mkdir(parents=True,exist_ok=True); m.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest, indent=2))

if __name__=="__main__": main()
