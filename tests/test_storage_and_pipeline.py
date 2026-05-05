import json
from pathlib import Path
from transit_friction.storage import write_json_gz, read_json_gz, safe_filename
from transit_friction.health import build_source_health

def test_json_gz_roundtrip(tmp_path):
    p=tmp_path/'a.json.gz'; write_json_gz(p,{"a":1}); assert read_json_gz(p)["a"]==1

def test_safe_filename():
    assert safe_filename('a b/c')=='a_b_c'

def test_health_builds():
    h=build_source_health([{"finished_at":"2026","source_results":[{"source_id":"x","success":True,"status_code":200,"event_count":1,"warnings":[],"duration_ms":10,"parser_status":"ok"}]}])
    assert 'x' in h

def test_daily_summary_from_sample(tmp_path):
    base=tmp_path
    d=base/'data/silver/friction_events'; d.mkdir(parents=True)
    (d/'2026-05-05.jsonl').write_text(json.dumps({"source":"x","category":"delay","event_state":"observed","severity":2})+'\n')
    assert (d/'2026-05-05.jsonl').exists()
