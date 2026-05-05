from __future__ import annotations
import gzip, hashlib, json, re
from pathlib import Path


def write_json_gz(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def read_json_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_jsonl(path: Path, rows, append=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def safe_filename(v: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", v)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact_snapshot(records):
    return {"record_count": len(records) if isinstance(records, list) else 1, "records": records}
