/* Saved comparisons of the fictional model only; no source observations enter here. */
(function (root) {
  'use strict';
  const journey = typeof module === 'object' && module.exports ? require('./journey-model.js') : root.TransitJourney;
  const defaults = Object.freeze({stepFree:true, lift:'failed', alternative:false, backup:false});
  const keys = ['stepFree','lift','alternative','backup'];
  const labels = {
    stepFree: 'Voraussetzung', lift: 'Aufzug am Ziel', alternative: 'Stufenloser Umweg', backup: 'Unabhängiger zweiter Aufzug',
  };
  function valid(options) {
    return options && Object.keys(options).length === 4 && keys.every(key => Object.hasOwn(options,key))
      && typeof options.stepFree === 'boolean' && typeof options.alternative === 'boolean'
      && typeof options.backup === 'boolean' && ['failed','ok','unknown'].includes(options.lift);
  }
  function describe(key, value) {
    if (key === 'stepFree') return value ? 'stufenlos durchgehend' : 'Treppen möglich';
    if (key === 'lift') return {failed:'ausgefallen',ok:'in Betrieb',unknown:'Status unbekannt'}[value];
    return value ? 'vorhanden' : 'nicht vorhanden';
  }
  function encode(options) {
    if (!valid(options)) throw new TypeError('Invalid fictional journey scenario');
    return `1.${options.stepFree ? 'sf' : 'stairs'}.${options.lift}.${Number(options.alternative)}.${Number(options.backup)}`;
  }
  function decode(code) {
    const match = /^1\.(sf|stairs)\.(failed|ok|unknown)\.([01])\.([01])$/.exec(code || '');
    return match ? {stepFree:match[1]==='sf',lift:match[2],alternative:match[3]==='1',backup:match[4]==='1'} : null;
  }
  function readLink(search) {
    const params = new URLSearchParams(search);
    const present = params.has('tf') || params.has('tfb');
    if (!present) return {current:{...defaults}, baseline:{...defaults}, invalid:false};
    const current = decode(params.get('tf')), baseline = params.has('tfb') ? decode(params.get('tfb')) : {...defaults};
    const invalid = params.getAll('tf').length !== 1 || params.getAll('tfb').length > 1 || !current || !baseline;
    return {current:invalid ? {...defaults} : current, baseline:invalid ? {...defaults} : baseline, invalid};
  }
  function link(href, current, baseline) {
    const url = new URL(href);
    url.searchParams.delete('tf'); url.searchParams.delete('tfb');
    if (encode(current) !== encode(defaults) || encode(baseline) !== encode(defaults)) {
      url.searchParams.set('tf',encode(current)); url.searchParams.set('tfb',encode(baseline));
    }
    url.hash = 'experiment';
    return url.href;
  }
  function summary(options) {
    if (!valid(options)) throw new TypeError('Invalid fictional journey scenario');
    const result = journey.evaluate(options);
    return {options:{...options}, outcome:result.outcome, sections:result.path ? result.path.length : null,
      path:result.path ? result.path.map(edge=>edge.label) : null,
      possiblePath:result.possiblePath ? result.possiblePath.map(edge=>edge.label) : null};
  }
  function compare(baseline, current) {
    const before = summary(baseline), after = summary(current);
    const changes = keys.filter(key=>baseline[key] !== current[key]).map(key=>({key,label:labels[key],
      before:describe(key,baseline[key]),after:describe(key,current[key])}));
    const sectionDelta = before.sections !== null && after.sections !== null ? after.sections - before.sections : null;
    return {schema:'transit-fictional-comparison/1', model:'fictional-six-nodes-v1', unit:'path-sections',
      boundary:'Frei erfundenes Erklärmodell. Keine Reiseauskunft, realen Stationen, Fahrzeiten, Entfernungen oder Live-Aufzugszustände.',
      assumptions:['Startzugang und Zugfahrt sind nutzbar.','Ein ergänzter Umweg setzt Nachbaraufzug und Außenweg als nutzbar voraus.',
        'Ein ergänzter zweiter Aufzug ist unabhängig, nicht Teil einer seriellen Zugangskette.'],
      before, after, changes, sectionDelta, mobilityChanged:baseline.stepFree !== current.stepFree};
  }
  const api = {defaults,valid,describe,encode,decode,readLink,link,compare};
  if (typeof module === 'object' && module.exports) module.exports=api;
  else root.TransitScenario=api;
})(typeof globalThis === 'object' ? globalThis : this);
