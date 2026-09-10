/* Validation shared by both public views. Unknown is not coerced to zero. */
(function (root) {
  'use strict';
  const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  const timestamp = value => typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
  function sourceLink(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && ['brokenlifts.org', 'www.brokenlifts.org'].includes(url.hostname) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function snapshot(data) {
    if (!data || data.schema_version !== 1 || data.kind !== 'reviewed_source_snapshot' || data.complete !== true || !sourceLink(data.source_url) || !timestamp(data.observed_at) || !timestamp(data.source_updated_at) || !timestamp(data.reviewed_at) || Date.parse(data.observed_at) < Date.parse(data.source_updated_at) || Date.parse(data.reviewed_at) < Date.parse(data.observed_at) || !Array.isArray(data.stations)) return false;
    if (!Number.isInteger(data.parsed_outage_count) || data.parsed_outage_count < 0 || data.parsed_outage_count !== data.advertised_outage_count) return false;
    const assets = new Set(); const stations = new Set();
    for (const station of data.stations) {
      if (typeof station.station_id !== 'string' || stations.has(station.station_id) || typeof station.station_name !== 'string' || !station.station_name.trim() || !Array.isArray(station.assets) || !station.assets.length) return false;
      stations.add(station.station_id);
      for (const asset of station.assets) {
        if (typeof asset.asset_id !== 'string' || assets.has(asset.asset_id) || !sourceLink(asset.source_url)) return false;
        assets.add(asset.asset_id);
      }
    }
    return assets.size === data.parsed_outage_count;
  }
  function freshness(data, now = Date.now()) {
    const age = now - Date.parse(data.source_updated_at);
    if (age < 0 || Date.parse(data.observed_at) > now || Date.parse(data.reviewed_at) > now) return 'future';
    return age > 3600000 ? 'stale' : 'dated';
  }
  function daily(data) {
    if (!data || data.schema_version !== 1 || data.unit !== 'outage-hours' || data.aggregation !== 'union_per_station' || !Array.isArray(data.days)) return false;
    const ordered = data.days.map(day => day?.date).sort();
    for (let i=1; i<ordered.length; i++) if (Date.parse(ordered[i])-Date.parse(ordered[i-1]) !== 86400000) return false;
    const dates = new Set();
    return data.days.every(day => {
      if (!day || !/^\d{4}-\d{2}-\d{2}$/.test(day.date) || dates.has(day.date) || ![23,24,25].includes(day.window_hours) || typeof day.publishable !== 'boolean' || !day.coverage || typeof day.coverage !== 'object' || Array.isArray(day.coverage)) return false;
      const parsedDate = new Date(day.date);
      if (!Number.isFinite(parsedDate.getTime()) || parsedDate.toISOString().slice(0,10) !== day.date) return false;
      dates.add(day.date);
      if (!Object.values(day.coverage).every(v => finite(v) && v <= 1)) return false;
      if (!day.publishable) return true;
      if (!Array.isArray(day.depends_on) || !day.depends_on.length || !day.coverage_publishable || !day.depends_on.every(source => day.coverage[source] > 0 && day.coverage_publishable[source] === true)) return false;
      return ['total_outage_hours','total_outage_hours_min','total_outage_hours_max','episode_count'].every(key => finite(day[key])) && day.total_outage_hours_min <= day.total_outage_hours && day.total_outage_hours <= day.total_outage_hours_max;
    });
  }
  const api = { sourceLink, snapshot, freshness, daily };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TransitData = api;
})(typeof globalThis === 'object' ? globalThis : this);
