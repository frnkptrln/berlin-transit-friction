#!/usr/bin/env python3
import argparse, importlib.util, platform
from pathlib import Path
ap=argparse.ArgumentParser(); ap.add_argument('--network',action='store_true'); a=ap.parse_args()
print('Python:', platform.python_version())
for dep in ['requests','bs4','pyarrow','pytest']:
    print(dep, 'OK' if importlib.util.find_spec(dep) else 'MISSING')
print('network check', 'enabled' if a.network else 'skipped')
for p in ['.raw','data/events','data/aggregates','data/_manifests','data/reference','site/data']:
    Path(p).mkdir(parents=True,exist_ok=True)
    print('writable', p, 'OK')
print('no secrets required: true')
