/* ═══════════════════════════════════════════════════════════════════
   Transit Friction — Dashboard Application
   Pure vanilla JS, no dependencies. Fetches JSON from site/data/
   ═══════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  // ── Data store ────────────────────────────────────────────────────
  const DATA = {
    latest: null,
    dailyIndex: null,
    dailyDetail: null,
    lineStats: null,
    stationStats: null,
    timeline: null,
    sourceHealth: null,
    mapGeojson: null,
  };

  const BASE = './data/';

  // ── Helpers ───────────────────────────────────────────────────────
  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $$(sel, ctx) { return [...(ctx || document).querySelectorAll(sel)]; }

  function el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => {
      if (k === 'className') e.className = v;
      else if (k === 'innerHTML') e.innerHTML = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
      else e.setAttribute(k, v);
    });
    children.flat().forEach(c => {
      if (typeof c === 'string') e.appendChild(document.createTextNode(c));
      else if (c) e.appendChild(c);
    });
    return e;
  }

  function timeAgo(iso) {
    if (!iso) return 'unknown';
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  }

  function severityColor(severity) {
    const colors = ['#64748b', '#6ea8fe', '#fbbf24', '#fb923c', '#f87171'];
    return colors[Math.min(severity, 4)] || colors[0];
  }

  function categoryLabel(cat) {
    const labels = {
      delay: 'Delays',
      cancellation: 'Cancellations',
      disruption: 'Disruptions',
      construction: 'Construction',
      replacement_service: 'Replacement',
      platform_change: 'Platform Change',
      elevator_or_accessibility_issue: 'Elevator',
      skipped_stop: 'Skipped Stop',
      crowding_signal: 'Crowding',
      information_gap: 'Info Gap',
      unknown: 'Other',
    };
    return labels[cat] || cat || 'Unknown';
  }

  function categoryIcon(cat) {
    const icons = {
      delay: '⏱',
      cancellation: '✕',
      disruption: '⚠',
      construction: '🔧',
      replacement_service: '🚌',
      platform_change: '↔',
      elevator_or_accessibility_issue: '♿',
      skipped_stop: '⊘',
      crowding_signal: '👥',
    };
    return icons[cat] || '•';
  }

  // ── Data Fetching ─────────────────────────────────────────────────
  async function fetchJSON(name) {
    try {
      const r = await fetch(BASE + name + '?' + Date.now());
      if (!r.ok) return null;
      return await r.json();
    } catch { return null; }
  }

  async function loadAll() {
    const [latest, dailyIndex, dailyDetail, lineStats, stationStats, timeline, sourceHealth, mapGeojson] = await Promise.all([
      fetchJSON('latest.json'),
      fetchJSON('daily-index.json'),
      fetchJSON('daily-detail.json'),
      fetchJSON('line-stats.json'),
      fetchJSON('station-stats.json'),
      fetchJSON('timeline.json'),
      fetchJSON('source-health.json'),
      fetchJSON('live-map.geojson'),
    ]);
    DATA.latest = latest || {};
    DATA.dailyIndex = dailyIndex || [];
    DATA.dailyDetail = dailyDetail || [];
    DATA.lineStats = lineStats || [];
    DATA.stationStats = stationStats || [];
    DATA.timeline = timeline || [];
    DATA.sourceHealth = sourceHealth || {};
    DATA.mapGeojson = mapGeojson || { type: 'FeatureCollection', features: [] };
    return DATA;
  }

  // ── Canvas Chart Rendering ────────────────────────────────────────
  function drawBarChart(canvas, data, opts = {}) {
    if (!canvas || !data.length) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = rect.height;
    const pad = { top: 20, right: 16, bottom: 32, left: 40 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;

    const values = data.map(d => d.value || 0);
    const maxVal = Math.max(...values, 1);
    const barW = Math.max(2, (plotW / data.length) - 2);
    const gap = (plotW - barW * data.length) / (data.length + 1);

    // Y axis
    ctx.strokeStyle = 'rgba(80,110,180,0.15)';
    ctx.lineWidth = 1;
    ctx.fillStyle = '#505a70';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + plotH - (plotH * i / 4);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(W - pad.right, y);
      ctx.stroke();
      ctx.fillText(Math.round(maxVal * i / 4), pad.left - 6, y + 3);
    }

    // Bars
    const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
    gradient.addColorStop(0, opts.colorTop || '#4d8dff');
    gradient.addColorStop(1, opts.colorBottom || 'rgba(77,141,255,0.15)');

    data.forEach((d, i) => {
      const x = pad.left + gap + i * (barW + gap);
      const h = (d.value / maxVal) * plotH;
      const y = pad.top + plotH - h;

      ctx.fillStyle = gradient;
      ctx.beginPath();
      const r = Math.min(3, barW / 2);
      ctx.moveTo(x, y + r);
      ctx.arcTo(x, y, x + barW, y, r);
      ctx.arcTo(x + barW, y, x + barW, y + h, r);
      ctx.lineTo(x + barW, pad.top + plotH);
      ctx.lineTo(x, pad.top + plotH);
      ctx.closePath();
      ctx.fill();

      // X labels (every Nth)
      if (data.length <= 14 || i % Math.ceil(data.length / 10) === 0) {
        ctx.fillStyle = '#505a70';
        ctx.font = '9px Inter, sans-serif';
        ctx.textAlign = 'center';
        const label = d.label || '';
        ctx.fillText(label.slice(5) || label, x + barW / 2, H - 8);
      }
    });
  }

  function drawSparkline(canvas, values, color) {
    if (!canvas || !values.length) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width = canvas.offsetWidth * dpr;
    const H = canvas.height = canvas.offsetHeight * dpr;
    ctx.scale(dpr, dpr);
    const w = canvas.offsetWidth;
    const h = canvas.offsetHeight;

    const max = Math.max(...values, 1);
    const step = w / Math.max(values.length - 1, 1);

    ctx.strokeStyle = color || '#4d8dff';
    ctx.lineWidth = 1.5;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = i * step;
      const y = h - (v / max) * (h - 4) - 2;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Fill under
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, (color || '#4d8dff') + '30');
    grad.addColorStop(1, 'transparent');
    ctx.lineTo((values.length - 1) * step, h);
    ctx.lineTo(0, h);
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // ── Renderers ─────────────────────────────────────────────────────

  function renderHeader() {
    const d = DATA.latest;
    const metaEl = $('#header-meta');
    if (!metaEl) return;

    const genAt = d.generated_at;
    const isStale = genAt && (Date.now() - new Date(genAt).getTime()) > 3600000;

    metaEl.innerHTML = '';
    metaEl.appendChild(el('span', { className: 'pulse' + (isStale ? ' pulse--stale' : '') }));
    metaEl.appendChild(el('span', null, `Data: ${d.date || 'n/a'}`));
    metaEl.appendChild(el('span', null, '·'));
    metaEl.appendChild(el('span', null, `Updated ${timeAgo(genAt)}`));
  }

  function renderMetrics() {
    const d = DATA.latest;
    const cats = d.events_by_category || {};
    const coverage = d.data_coverage || {};

    setMetric('metric-total', d.total_events || 0);
    setMetric('metric-disruptions',
      (cats.cancellation || 0) + (cats.disruption || 0) + (cats.delay || 0),
      Object.keys(cats).length ? `${Object.entries(cats).map(([k,v]) => `${categoryLabel(k)}: ${v}`).join(', ')}` : 'No category data'
    );
    setMetric('metric-accessibility', cats.elevator_or_accessibility_issue || d.accessibility_friction || 0, 'Elevator signal events');
    setMetric('metric-watchlist', d.connection_watchlist_count || 0, 'Monitored relations');

    // Best/worst line
    const lineEvents = d.events_by_line || {};
    const topLine = Object.entries(lineEvents).sort((a, b) => b[1] - a[1])[0];
    const worstEl = $('#metric-worst-line');
    if (worstEl) {
      worstEl.querySelector('.metric-card__value').textContent = topLine ? topLine[0] : '—';
      const det = worstEl.querySelector('.metric-card__detail');
      if (det) det.textContent = topLine ? `${topLine[1]} events` : 'No line data yet';
    }
  }

  function setMetric(id, value, detail) {
    const card = document.getElementById(id);
    if (!card) return;
    const vEl = card.querySelector('.metric-card__value');
    if (vEl) animateNumber(vEl, value);
    if (detail) {
      const dEl = card.querySelector('.metric-card__detail');
      if (dEl) dEl.textContent = detail;
    }
  }

  function animateNumber(el, target) {
    const start = parseInt(el.textContent) || 0;
    if (start === target) { el.textContent = target; return; }
    const duration = 600;
    const t0 = performance.now();
    function tick(now) {
      const p = Math.min((now - t0) / duration, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(start + (target - start) * ease);
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  let leafletMap = null;
  function renderMap() {
    const container = document.getElementById('map');
    if (!container) return;

    if (!leafletMap) {
      // Initialize map (Dark theme tiles via CartoDB)
      leafletMap = L.map('map', {
        zoomControl: false,
        attributionControl: false
      }).setView([52.5200, 13.4050], 11);
      
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        subdomains: 'abcd',
        maxZoom: 19
      }).addTo(leafletMap);
      
      // Custom zoom control position
      L.control.zoom({ position: 'bottomright' }).addTo(leafletMap);
    }

    // Clear existing markers
    leafletMap.eachLayer((layer) => {
      if (layer instanceof L.CircleMarker) leafletMap.removeLayer(layer);
    });

    const features = DATA.mapGeojson?.features || [];
    
    // Add new markers
    features.forEach(f => {
      const p = f.properties;
      const coords = f.geometry.coordinates;
      
      let color = '#34d399'; // Default
      if (p.severity >= 4 || p.category === 'cancellation') color = '#f87171'; // Red
      else if (p.severity === 3 || p.category === 'disruption') color = '#fb923c'; // Orange
      else if (p.severity === 2 || p.category === 'delay') color = '#fbbf24'; // Yellow
      else if (p.category === 'construction') color = '#a78bfa'; // Purple

      const marker = L.circleMarker([coords[1], coords[0]], {
        radius: 6,
        fillColor: color,
        color: '#fff',
        weight: 1.5,
        opacity: 0.8,
        fillOpacity: 0.6,
        className: 'map-pulse-marker'
      }).addTo(leafletMap);

      const html = `
        <div style="font-family: 'Inter', sans-serif; font-size: 13px;">
          <strong style="display:block; margin-bottom: 4px;">${p.title || 'Disruption'}</strong>
          <span style="display:block; color: #666; font-size: 11px; margin-bottom: 2px;">Line: ${p.line || 'Multiple/Unknown'}</span>
          <span style="display:block; color: #666; font-size: 11px;">Active for ${p.time_active_mins} mins</span>
        </div>
      `;
      marker.bindPopup(html);
    });
  }

  function renderCategoryBreakdown() {
    const container = $('#category-breakdown');
    if (!container) return;

    // Aggregate across all daily details
    const totals = {};
    (DATA.dailyDetail || []).forEach(d => {
      Object.entries(d.events_by_category || {}).forEach(([k, v]) => {
        totals[k] = (totals[k] || 0) + v;
      });
    });

    if (!Object.keys(totals).length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-state__icon">📋</div>No category data yet</div>';
      return;
    }

    const sorted = Object.entries(totals).sort((a, b) => b[1] - a[1]);
    const maxVal = sorted[0][1];

    container.innerHTML = '';
    sorted.forEach(([cat, count]) => {
      const row = el('div', { style: 'display:flex;align-items:center;gap:0.75rem;margin-bottom:0.6rem;' });
      const label = el('span', { style: 'min-width:110px;font-size:0.8rem;color:#8892a8;' }, `${categoryIcon(cat)} ${categoryLabel(cat)}`);
      const barOuter = el('div', { style: 'flex:1;height:8px;background:rgba(8,12,24,0.6);border-radius:4px;overflow:hidden;' });
      const barInner = el('div', {
        style: `height:100%;width:${(count / maxVal) * 100}%;background:${severityColor(cat === 'cancellation' ? 4 : cat === 'delay' ? 2 : cat === 'disruption' ? 3 : 1)};border-radius:4px;transition:width 0.6s cubic-bezier(0.16,1,0.3,1);`
      });
      barOuter.appendChild(barInner);
      const num = el('span', { style: 'min-width:36px;text-align:right;font-size:0.8rem;font-family:JetBrains Mono,monospace;color:#e4e8f1;' }, String(count));
      row.append(label, barOuter, num);
      container.appendChild(row);
    });
  }

  function renderLineTable() {
    const tbody = $('#line-table-body');
    if (!tbody) return;

    const lines = DATA.lineStats || [];
    if (!lines.length) {
      tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><div class="empty-state__icon">🚇</div>No line data yet. Friction events need a line attribute to appear here.</div></td></tr>';
      return;
    }

    tbody.innerHTML = '';
    lines.slice(0, 20).forEach(l => {
      const tr = el('tr');
      tr.innerHTML = `
        <td><strong>${l.line}</strong></td>
        <td class="num">${l.total_events}</td>
        <td class="num">${l.delays}</td>
        <td class="num">${l.cancellations}</td>
        <td class="num">${l.severity_avg}</td>
        <td class="num" style="color:${l.friction_score > 50 ? '#f87171' : l.friction_score > 20 ? '#fbbf24' : '#34d399'}">${l.friction_score}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function renderStationChart() {
    const container = $('#station-chart');
    if (!container) return;

    const stations = (DATA.stationStats || []).slice(0, 10);
    if (!stations.length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-state__icon">🚉</div>No station data yet</div>';
      return;
    }

    const maxFriction = Math.max(...stations.map(s => s.delays + s.cancellations), 1);
    container.innerHTML = '';

    stations.forEach(s => {
      const total = s.delays + s.cancellations;
      const row = el('div', { style: 'display:flex;align-items:center;gap:0.75rem;margin-bottom:0.5rem;' });
      const name = el('span', { style: 'min-width:160px;font-size:0.8rem;color:#e4e8f1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;' }, s.station);
      const barOuter = el('div', { style: 'flex:1;height:8px;background:rgba(8,12,24,0.6);border-radius:4px;overflow:hidden;position:relative;' });

      const delayW = (s.delays / maxFriction) * 100;
      const cancelW = (s.cancellations / maxFriction) * 100;
      const delayBar = el('div', { style: `position:absolute;height:100%;width:${delayW}%;background:#fbbf24;border-radius:4px 0 0 4px;` });
      const cancelBar = el('div', { style: `position:absolute;left:${delayW}%;height:100%;width:${cancelW}%;background:#f87171;border-radius:0 4px 4px 0;` });
      barOuter.append(delayBar, cancelBar);

      const num = el('span', { style: 'min-width:36px;text-align:right;font-size:0.8rem;font-family:JetBrains Mono,monospace;color:#8892a8;' }, String(total));
      row.append(name, barOuter, num);
      container.appendChild(row);
    });
  }

  function renderTimeline() {
    const canvas = $('#chart-timeline');
    if (!canvas) return;
    const data = (DATA.timeline || []).map(d => ({
      label: d.hour,
      value: d.events,
    }));
    if (!data.length) {
      canvas.parentElement.innerHTML = '<div class="empty-state"><div class="empty-state__icon">📈</div>No hourly data yet</div>';
      return;
    }
    drawBarChart(canvas, data, {
      colorTop: '#a78bfa',
      colorBottom: 'rgba(167,139,250,0.08)',
    });
  }

  function renderSourceHealth() {
    const container = $('#source-health');
    if (!container) return;

    const health = DATA.sourceHealth || {};
    if (!Object.keys(health).length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-state__icon">📡</div>No source health data</div>';
      return;
    }

    container.innerHTML = '';
    Object.entries(health).forEach(([name, h]) => {
      const failures = h.consecutive_failures || 0;
      const dotClass = failures === 0 && h.last_success ? 'ok'
        : failures > 10 ? 'error'
        : failures > 0 ? 'warn'
        : 'unknown';

      const item = el('div', { className: 'health-item' });
      item.innerHTML = `
        <div class="health-item__name">
          <span class="health-item__dot health-item__dot--${dotClass}"></span>
          ${name.replace(/_/g, ' ')}
        </div>
        <div class="health-item__detail">
          Status: ${h.last_status_code ?? '—'} · Events: ${h.last_event_count ?? 0} · Avg: ${h.average_response_time_ms ?? 0}ms
        </div>
        <div class="health-item__detail">
          ${h.last_success ? 'Last OK: ' + timeAgo(h.last_success) : 'Never succeeded'}
          ${failures > 0 ? ` · Failures: ${failures}` : ''}
        </div>
        ${h.last_warning && h.last_warning !== 'network disabled or requests missing'
          ? `<div class="health-item__detail" style="color:#fb923c;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${h.last_warning}">⚠ ${h.last_warning.slice(0, 80)}</div>`
          : ''
        }
      `;
      container.appendChild(item);
    });
  }

  function renderWatchlist() {
    const container = $('#watchlist');
    if (!container) return;
    const d = DATA.latest;

    const worst = d.worst_relation;
    const cancelled = d.relations_with_cancellations || [];
    const stations = d.stations_with_most_delayed_departures || [];

    if (!worst && !cancelled.length && !stations.length) {
      container.innerHTML = '<div class="empty-state"><div class="empty-state__icon">🔍</div>No watchlist observations yet. Connection monitoring data will appear here when departure/journey collectors are active.</div>';
      return;
    }

    container.innerHTML = '';
    if (worst) {
      const card = el('div', { className: 'watchlist-card' });
      card.innerHTML = `
        <div class="watchlist-card__route">⏱ Worst delay: ${worst.relation_label || worst.relation_id || 'Unknown'}</div>
        <div class="watchlist-card__detail">Delay delta: ${worst.delay_delta_min ?? '—'} min</div>
      `;
      container.appendChild(card);
    }
    cancelled.forEach(r => {
      const card = el('div', { className: 'watchlist-card' });
      card.innerHTML = `
        <div class="watchlist-card__route">✕ Cancellation: ${r.relation_label || r.relation_id || 'Unknown'}</div>
      `;
      container.appendChild(card);
    });
  }

  // ── Main ──────────────────────────────────────────────────────────
  async function init() {
    await loadAll();
    renderHeader();
    renderMetrics();
    renderMap();
    renderCategoryBreakdown();
    renderLineTable();
    renderStationChart();
    renderTimeline();
    renderSourceHealth();
    renderWatchlist();

    // Entrance animations
    document.querySelectorAll('.animate-in').forEach(el => {
      el.style.opacity = '1';
    });

    // Re-draw charts on resize
    let resizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        renderTimeline();
        if (leafletMap) leafletMap.invalidateSize();
      }, 200);
    });
  }

  // Auto-refresh every 5 minutes
  setInterval(async () => {
    await loadAll();
    renderHeader();
    renderMetrics();
  }, 5 * 60 * 1000);

  // Launch
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
