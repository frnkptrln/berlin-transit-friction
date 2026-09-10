import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_accessibility_snapshot', ROOT / 'scripts/build_accessibility_snapshot.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def capture():
    return (ROOT / 'tests/fixtures/brokenlifts_homepage.html').read_text()


def kwargs(html):
    from transit_friction.accessibility.parser import parse_brokenlifts_snapshot
    now = datetime.now(timezone.utc)
    source = parse_brokenlifts_snapshot(html, observed_at=now).source_updated_at
    return dict(observed_at=source+timedelta(minutes=1),source_url='https://brokenlifts.org/',review_note='Fixture review',reviewed_at=source+timedelta(minutes=2))


def test_snapshot_is_a_dated_statement_with_no_duration_or_rate():
    html=capture()
    data=module.project_snapshot(html,**kwargs(html))
    assert data['kind']=='reviewed_source_snapshot'
    assert data['parsed_outage_count']==data['advertised_outage_count']==3
    assert len(data['payload_sha256'])==64
    assert 'duration' not in data and 'rate' not in data
    assert all(s['region']=='other_or_unknown' for s in data['stations'])


def test_snapshot_rejects_incomplete_source_and_future_or_stale_provider_clock():
    html=capture(); args=kwargs(html)
    with pytest.raises(ValueError,match='Incomplete'):
        module.project_snapshot('<html>error</html>',**args)
    with pytest.raises(ValueError,match='future'):
        module.project_snapshot(html,**{**args,'observed_at':args['observed_at']-timedelta(hours=1)})
    with pytest.raises(ValueError,match='hour old'):
        module.project_snapshot(html,**{**args,'observed_at':args['observed_at']+timedelta(hours=2)})


def test_snapshot_requires_review_and_trusted_public_source():
    html=capture(); args=kwargs(html)
    with pytest.raises(ValueError,match='review note'):
        module.project_snapshot(html,**{**args,'review_note':''})
    with pytest.raises(ValueError,match='HTTPS'):
        module.project_snapshot(html,**{**args,'source_url':'https://user:pass@brokenlifts.org/'})
