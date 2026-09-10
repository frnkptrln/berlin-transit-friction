const test = require('node:test');
const assert = require('node:assert/strict');
const {evaluate} = require('../site/journey-model.js');
const contract = require('../site/data-contract.js');
const fs = require('node:fs');

test('single lift failure disconnects the required step-free journey', () => {
  const result=evaluate(); assert.equal(result.outcome,'blocked'); assert.equal(result.path,null);
});
test('stairs preserve a path only when stairs are possible', () => {
  const result=evaluate({stepFree:false}); assert.equal(result.outcome,'direct'); assert.equal(result.path.at(-1).id,'stairs');
  assert.equal(evaluate({stepFree:true}).outcome,'blocked');
});
test('accessible alternative has five sections instead of three, not invented minutes', () => {
  const result=evaluate({alternative:true}); assert.equal(result.outcome,'detour'); assert.equal(result.extraSections,2);
  assert.deepEqual(result.path.map(e=>e.id),['entry','ride','extra-ride','extra-lift','return']);
});
test('independent backup restores the direct path while original lift is still broken', () => {
  const result=evaluate({backup:true,alternative:true}); assert.equal(result.outcome,'direct'); assert.equal(result.path.at(-1).id,'backup'); assert.equal(result.graph.find(e=>e.id==='lift').state,'failed');
});
test('repair restores original direct path', () => {assert.equal(evaluate({lift:'ok'}).path.at(-1).id,'lift');});
test('unknown never becomes confirmed reachable without an alternative', () => {
  const result=evaluate({lift:'unknown'}); assert.equal(result.outcome,'unknown'); assert.equal(result.path,null); assert.ok(result.possiblePath);
  assert.equal(evaluate({lift:'unknown',alternative:true}).outcome,'detour');
  assert.equal(evaluate({lift:'unknown',backup:true}).outcome,'direct');
});
test('all 24 combinations return contiguous usable paths ending at the goal', () => {
  for(const stepFree of [true,false]) for(const lift of ['ok','failed','unknown']) for(const alternative of [true,false]) for(const backup of [true,false]) {
    const result=evaluate({stepFree,lift,alternative,backup});
    if(!result.path)continue;
    let current='start';for(const edge of result.path){assert.equal(edge.from,current);assert.equal(edge.state,'ok');if(stepFree)assert.notEqual(edge.id,'stairs');current=edge.to;}assert.equal(current,'goal');
  }
});
const published=JSON.parse(fs.readFileSync(new URL('../site/data/accessibility-snapshot.json',`file://${__filename}`),'utf8'));
test('published source snapshot conserves counts and independent station/asset identity', () => {assert.equal(contract.snapshot(published),true);});
test('malformed or incomplete snapshots cannot be presented as observations', () => {
  assert.equal(contract.snapshot({...published,complete:false}),false);
  assert.equal(contract.snapshot({...published,advertised_outage_count:999}),false);
  const copy=structuredClone(published);copy.stations[0].assets.push(copy.stations[0].assets[0]);assert.equal(contract.snapshot(copy),false);
});
test('only public HTTPS source links can be used', () => {
  for(const unsafe of ['javascript:alert(1)','https://brokenlifts.org.attacker.test/','https://user:pass@brokenlifts.org/','http://brokenlifts.org/'])assert.equal(contract.sourceLink(unsafe),null);
  assert.equal(contract.sourceLink('https://brokenlifts.org/stations'),'https://brokenlifts.org/stations');
});
test('a snapshot cannot remain labelled current when it ages or is future dated', () => {
  const now=Date.parse(published.reviewed_at);assert.equal(contract.freshness(published,now+7200000),'stale');
  assert.equal(contract.freshness(published,Date.parse(published.source_updated_at)-1000),'future');
});
const daily = data => contract.daily({schema_version:1,unit:'outage-hours',aggregation:'union_per_station',...data});
test('empty daily projection is valid but missing data is not', () => {assert.equal(daily({days:[]}),true);assert.equal(contract.daily(null),false);});
const day={depends_on:['brokenlifts'],coverage_publishable:{brokenlifts:true},date:'2026-09-10',window_hours:24,publishable:true,coverage:{brokenlifts:1},total_outage_hours:2,total_outage_hours_min:1,total_outage_hours_max:3,episode_count:1};
test('published duration bounds and coverage must be finite and ordered', () => {
  assert.equal(daily({days:[day]}),true);
  assert.equal(daily({days:[{...day,total_outage_hours_min:4}]}),false);
  assert.equal(daily({days:[{...day,total_outage_hours:null}]}),false);
  assert.equal(daily({days:[{...day,coverage:{brokenlifts:1.2}}]}),false);
  assert.equal(daily({days:[day,day]}),false);
});
test('withheld days stay valid null windows including DST day lengths', () => {
  for(const hours of [23,24,25])assert.equal(daily({days:[{...day,window_hours:hours,publishable:false,total_outage_hours:null}]}),true);
});
test('mislabelled units, zero coverage, impossible dates and omitted days are rejected', () => {
  assert.equal(daily({unit:'lift-hours',days:[day]}),false);
  assert.equal(daily({days:[{...day,coverage:{}}]}),false);
  assert.equal(daily({days:[{...day,coverage:{brokenlifts:0}}]}),false);
  assert.equal(daily({days:[{...day,coverage_publishable:{brokenlifts:false}}]}),false);
  assert.equal(daily({days:[{...day,date:'2026-02-30'}]}),false);
  assert.equal(daily({days:[day,{...day,date:'2026-09-12'}]}),false);
});
