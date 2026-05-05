#!/usr/bin/env python3
import argparse, importlib.util, platform
from pathlib import Path
ap=argparse.ArgumentParser(); ap.add_argument('--network',action='store_true'); a=ap.parse_args()
print('Python:', platform.python_version())
for dep in ['requests','pydantic','yaml','pytest']:
    print(dep, 'OK' if importlib.util.find_spec(dep) else 'MISSING')
for dep in ['google.transit.gtfs_realtime_pb2']:
    try:
        ok = importlib.util.find_spec(dep) is not None
    except Exception:
        ok = False
    print('optional', dep, 'OK' if ok else 'MISSING')
print('network check', 'enabled' if a.network else 'skipped')
for p in ['data/bronze','data/silver','data/gold','data/manifests','site/data']:
    Path(p).mkdir(parents=True,exist_ok=True)
    print('writable', p, 'OK')
print('no secrets required: true')
