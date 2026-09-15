#!/usr/bin/env python3
"""Validate the static public surface without a browser or network requests."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'

class Document(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids=set(); self.references=[]; self.lang=None
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if 'id' in attrs:
            if attrs['id'] in self.ids: raise ValueError('Duplicate ID: '+attrs['id'])
            self.ids.add(attrs['id'])
        if tag=='html': self.lang=attrs.get('lang')
        for attribute in ['src','href']:
            if attribute in attrs: self.references.append(attrs[attribute])


def main():
    documents={}
    for path in SITE.glob('*.html'):
        document=Document();document.feed(path.read_text());documents[path]=document
        assert document.lang=='de',f'{path}: missing German language declaration'
    for path,document in documents.items():
        for reference in document.references:
            url=urlparse(reference)
            if url.scheme or url.netloc:continue
            destination=(path.parent/unquote(url.path)).resolve() if url.path else path
            assert destination.is_relative_to(SITE.resolve()),f'Escaping site reference: {reference}'
            assert destination.is_file(),f'{path.name}: missing {reference}'
            if url.fragment and destination in documents:
                assert url.fragment in documents[destination].ids,f'Missing anchor: {reference}'
    for path in SITE.glob('*.js'):
        subprocess.run(['node','--check',str(path)],check=True)
    for path in (SITE/'data').glob('*.json'):
        json.loads(path.read_text())
    forbidden=['latest.json','line-stats.json','timeline.json','station-stats.json','daily-detail.json','source-health.json','daily-index.json','live-map.geojson']
    assert all(not (SITE/'data'/name).exists() for name in forbidden),'Legacy data still publicly exposed'
    assert not (SITE/'app.js').exists(),'Legacy dashboard still publicly exposed'
    print(f'Static site verified: {len(documents)} German pages, local assets, anchors, JavaScript syntax, JSON and legacy isolation.')

if __name__=='__main__': main()
