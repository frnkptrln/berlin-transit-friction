#!/usr/bin/env python3
from pathlib import Path
import argparse
ap=argparse.ArgumentParser(); ap.add_argument('--warn-mb',type=int,default=200); a=ap.parse_args()
base=Path('data')
files=[p for p in base.glob('**/*') if p.is_file()]
size=sum(p.stat().st_size for p in files)
print('data_bytes',size)
for layer in ['bronze','silver','gold','manifests','state']:
    d=base/layer
    s=sum(p.stat().st_size for p in d.glob('**/*') if p.is_file()) if d.exists() else 0
    print(layer,s)
largest=sorted(files,key=lambda p:p.stat().st_size, reverse=True)[:10]
for p in largest: print('largest',p,p.stat().st_size)
if size> a.warn_mb*1024*1024: print('WARNING threshold exceeded')
