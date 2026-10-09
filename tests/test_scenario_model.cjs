const test = require('node:test');
const assert = require('node:assert/strict');
const scenario = require('../site/scenario-model.js');
const base = {...scenario.defaults};

test('all 24 model configurations round-trip through a versioned link', () => {
  for (const stepFree of [true,false]) for (const lift of ['failed','ok','unknown'])
    for (const alternative of [true,false]) for (const backup of [true,false]) {
      const options = {stepFree,lift,alternative,backup};
      assert.deepEqual(scenario.decode(scenario.encode(options)),options);
      const url = new URL(scenario.link('https://example.org/repo/?other=kept#observations',options,base));
      assert.equal(url.pathname,'/repo/'); assert.equal(url.searchParams.get('other'),'kept');
      assert.equal(url.hash,'#experiment');
      assert.deepEqual(scenario.readLink(url.search),{current:options,baseline:base,invalid:false});
    }
});
test('unsupported, incomplete and duplicate parameters fail to the labelled default', () => {
  for (const search of ['?tf=2.sf.ok.0.0','?tf=1.sf.live.0.0','?tf=1.sf.failed.1',
    '?tf=1.sf.ok.0.0&tf=1.sf.failed.0.0','?tfb=1.sf.ok.0.0',
    '?tf=1.sf.ok.0.0&tfb=invalid','?tf=1.sf.ok.0.0&tfb=1.sf.ok.0.0&tfb=1.sf.ok.0.0']) {
    assert.deepEqual(scenario.readLink(search),{current:base,baseline:base,invalid:true});
  }
  assert.equal(scenario.readLink('?unrelated=true').invalid,false);
  for (const options of [{}, {...base,backup:1},{...base,station:'real'},{...base,lift:'live'}]) {
    assert.throws(()=>scenario.encode(options),TypeError);
    assert.throws(()=>scenario.compare(base,options),TypeError);
  }
});
test('blocked and unknown baselines never turn into numerical zero', () => {
  for (const lift of ['failed','unknown']) {
    const comparison = scenario.compare({...base,lift},{...base,alternative:true});
    assert.equal(comparison.before.sections,null); assert.equal(comparison.after.sections,5);
    assert.equal(comparison.sectionDelta,null);
    assert.equal(comparison.before.outcome,lift === 'unknown' ? 'unknown' : 'blocked');
    assert.equal(comparison.before.path,null);
    assert.equal(comparison.before.possiblePath === null,lift === 'failed');
  }
});
test('confirmed detour versus independent access differs by two path sections', () => {
  const detour={...base,alternative:true}, backup={...base,backup:true};
  assert.equal(scenario.compare(detour,backup).sectionDelta,-2);
  assert.equal(scenario.compare(backup,detour).sectionDelta,2);
  assert.equal(scenario.compare(backup,{...base,lift:'unknown'}).sectionDelta,null);
});
test('mobility changes remain explicit even when the number of sections is equal', () => {
  const comparison=scenario.compare({...base,backup:true},{...base,stepFree:false});
  assert.equal(comparison.sectionDelta,0); assert.equal(comparison.mobilityChanged,true);
  assert.ok(comparison.changes.some(change=>change.key==='stepFree'));
  assert.notDeepEqual(comparison.before.path,comparison.after.path);
});
test('comparison is deterministic, does not mutate input and exports its assumptions', () => {
  const frozen=Object.freeze({...base,alternative:true});
  const result=scenario.compare(frozen,base);
  assert.deepEqual(result,scenario.compare(frozen,base));
  assert.equal(result.unit,'path-sections'); assert.equal(result.model,'fictional-six-nodes-v1');
  assert.ok(result.boundary.includes('Keine Reiseauskunft'));
  assert.equal(result.assumptions.length,3);
  assert.equal(scenario.compare(base,base).changes.length,0);
  result.before.options.alternative=false;
  assert.equal(frozen.alternative,true);
});
