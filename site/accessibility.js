/* Renders the accessibility dashboard from the aggregate projection.
 *
 * The design rule throughout: a day we could not measure is drawn as a day we
 * could not measure. It is never interpolated across, never plotted at zero,
 * and never quietly dropped so the line looks continuous.
 */
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const tip = document.getElementById("tip");
  const app = document.getElementById("app");

  const fmt = (v, d = 1) =>
    v === null || v === undefined ? "—" : v.toLocaleString("en-GB", {
      minimumFractionDigits: d, maximumFractionDigits: d,
    });
  const pct = (v) => (v * 100).toFixed(v >= 0.995 ? 0 : 1) + "%";
  const el = (tag, attrs = {}, text) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const html = (tag, cls, inner) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (inner !== undefined) node.innerHTML = inner;
    return node;
  };
  const shortDate = (iso) =>
    new Date(iso + "T12:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short" });

  // --- coverage grading -----------------------------------------------------
  // Three states, each with a shape as well as a colour, so the rail never
  // depends on hue alone.
  function grade(day) {
    const c = day.coverage ? Object.values(day.coverage)[0] ?? 0 : 0;
    if (!day.publishable) return { key: "insufficient", label: "Insufficient coverage", colour: "var(--status-critical)", ratio: c };
    if (c >= 0.999) return { key: "full", label: "Fully watched", colour: "var(--status-good)", ratio: c };
    return { key: "partial", label: "Partly watched", colour: "var(--status-warning)", ratio: c };
  }

  function showTip(evt, lines) {
    tip.innerHTML = lines;
    tip.style.opacity = "1";
    const pad = 14;
    const rect = tip.getBoundingClientRect();
    let x = evt.clientX + pad;
    let y = evt.clientY + pad;
    if (x + rect.width > window.innerWidth - 8) x = evt.clientX - rect.width - pad;
    if (y + rect.height > window.innerHeight - 8) y = evt.clientY - rect.height - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  const hideTip = () => { tip.style.opacity = "0"; };

  // --- the time series ------------------------------------------------------
  function timeSeries(days) {
    const W = 960, H = 322, padL = 68, padR = 18, padT = 30, plotH = 226;
    const railY = plotH + padT + 26, railH = 18;
    const band = (W - padL - padR) / days.length;
    const xLeft = (i) => padL + band * i;
    const xMid = (i) => padL + band * (i + 0.5);

    const highest = days.reduce(
      (m, d) => Math.max(m, d.total_outage_hours_max ?? 0), 0);
    const step = [1, 2, 5, 10, 12, 24, 48, 96].find((s) => highest / s <= 5) || 120;
    const yMax = Math.max(step, Math.ceil(highest / step) * step);
    const y = (v) => padT + plotH - (v / yMax) * plotH;

    const svg = el("svg", {
      viewBox: `0 0 ${W} ${H}`, width: W, height: H,
      role: "img",
      "aria-label": "Daily elevator outage-hours with uncertainty bounds and a coverage rail",
    });

    const defs = el("defs");
    const pattern = el("pattern", {
      id: "nodata", width: 8, height: 8,
      patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)",
    });
    pattern.appendChild(el("rect", { width: 8, height: 8, fill: "var(--surface-1)" }));
    pattern.appendChild(el("line", {
      x1: 0, y1: 0, x2: 0, y2: 8, stroke: "var(--hatch)", "stroke-width": 2,
    }));
    defs.appendChild(pattern);
    svg.appendChild(defs);

    // gridlines and y ticks — hairline, solid, recessive
    for (let v = 0; v <= yMax; v += step) {
      svg.appendChild(el("line", {
        x1: padL, x2: W - padR, y1: y(v), y2: y(v),
        stroke: v === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1,
      }));
      const label = el("text", {
        x: padL - 10, y: y(v) + 4, "text-anchor": "end",
        fill: "var(--text-muted)", "font-size": 11,
        style: "font-variant-numeric: tabular-nums",
      }, String(v));
      svg.appendChild(label);
    }
    svg.appendChild(el("text", {
      x: padL - 10, y: padT - 14, "text-anchor": "end",
      fill: "var(--text-muted)", "font-size": 11,
    }, "hours"));

    // days we could not measure: drawn, not skipped
    days.forEach((d, i) => {
      if (d.publishable) return;
      svg.appendChild(el("rect", {
        x: xLeft(i), y: padT, width: band, height: plotH,
        fill: "url(#nodata)", opacity: 0.5,
      }));
    });

    // uncertainty band, then the midpoint line, broken across unmeasured days
    const runs = [];
    let run = [];
    days.forEach((d, i) => {
      if (d.publishable && d.total_outage_hours !== null) run.push(i);
      else { if (run.length) runs.push(run); run = []; }
    });
    if (run.length) runs.push(run);

    runs.forEach((idx) => {
      const top = idx.map((i) => `${xMid(i)},${y(days[i].total_outage_hours_max)}`);
      const bottom = idx.slice().reverse().map((i) => `${xMid(i)},${y(days[i].total_outage_hours_min)}`);
      svg.appendChild(el("polygon", {
        points: top.concat(bottom).join(" "),
        fill: "var(--series-1)", opacity: 0.16,
      }));
      svg.appendChild(el("polyline", {
        points: idx.map((i) => `${xMid(i)},${y(days[i].total_outage_hours)}`).join(" "),
        fill: "none", stroke: "var(--series-1)", "stroke-width": 2,
        "stroke-linejoin": "round", "stroke-linecap": "round",
      }));
      if (idx.length === 1) {
        const i = idx[0];
        svg.appendChild(el("circle", {
          cx: xMid(i), cy: y(days[i].total_outage_hours), r: 4,
          fill: "var(--series-1)", stroke: "var(--surface-1)", "stroke-width": 2,
        }));
      }
    });

    // one direct label: the worst day
    let peak = -1;
    days.forEach((d, i) => {
      if (d.publishable && d.total_outage_hours !== null &&
          (peak < 0 || d.total_outage_hours > days[peak].total_outage_hours)) peak = i;
    });
    if (peak >= 0 && days[peak].total_outage_hours > 0) {
      const px = xMid(peak), py = y(days[peak].total_outage_hours);
      svg.appendChild(el("circle", {
        cx: px, cy: py, r: 4.5, fill: "var(--series-1)",
        stroke: "var(--surface-1)", "stroke-width": 2,
      }));
      svg.appendChild(el("text", {
        x: Math.min(px, W - padR - 46), y: py - 12,
        "text-anchor": px > W - padR - 60 ? "end" : "middle",
        fill: "var(--text-primary)", "font-size": 12, "font-weight": 600,
      }, `${fmt(days[peak].total_outage_hours)} h`));
    }

    // x ticks, roughly weekly; the final tick is dropped when it would collide
    const last = days.length - 1;
    const showLast = last % 7 >= 3;
    days.forEach((d, i) => {
      if (i % 7 !== 0 && !(i === last && showLast)) return;
      svg.appendChild(el("text", {
        x: xMid(i), y: padT + plotH + 16, "text-anchor": "middle",
        fill: "var(--text-muted)", "font-size": 11,
      }, shortDate(d.date)));
    });

    // coverage rail — colour plus shape, aligned to the same x bands
    svg.appendChild(el("text", {
      x: padL - 10, y: railY + railH - 2, "text-anchor": "end",
      fill: "var(--text-muted)", "font-size": 11,
    }, "watched"));
    days.forEach((d, i) => {
      const g = grade(d);
      const w = Math.max(2, band - 2); // 2px surface gap between neighbours
      if (g.key === "insufficient") {
        svg.appendChild(el("rect", {
          x: xLeft(i) + 1, y: railY, width: w, height: railH, rx: 2,
          fill: "url(#nodata)", stroke: g.colour, "stroke-width": 1.5,
        }));
      } else {
        // The cell's height is the share of the day we were watching, so the
        // shape carries the information and the colour only confirms it.
        svg.appendChild(el("rect", {
          x: xLeft(i) + 1, y: railY, width: w, height: railH, rx: 2,
          fill: "var(--grid)",
        }));
        const filled = Math.max(2, railH * g.ratio);
        svg.appendChild(el("rect", {
          x: xLeft(i) + 1, y: railY + (railH - filled), width: w, height: filled,
          rx: 2, fill: g.colour, opacity: g.key === "full" ? 0.55 : 0.95,
        }));
      }
    });

    // hover: one generous target per day, covering plot and rail
    days.forEach((d, i) => {
      const hit = el("rect", {
        x: xLeft(i), y: padT, width: band, height: railY + railH - padT,
        fill: "transparent", style: "cursor: crosshair",
      });
      const g = grade(d);
      hit.addEventListener("mousemove", (e) => showTip(e, `
        <div class="t-date">${shortDate(d.date)} ${d.date.slice(0, 4)}</div>
        <div class="t-row">${d.publishable
          ? `${fmt(d.total_outage_hours)} outage-hours <span style="color:var(--text-muted)">(${fmt(d.total_outage_hours_min)}–${fmt(d.total_outage_hours_max)})</span>`
          : "no figure — the day was not watched well enough"}</div>
        <div class="t-row">${d.publishable ? `${d.episode_count} outage${d.episode_count === 1 ? "" : "s"}` : ""}</div>
        <div class="t-flag">${g.label} · ${pct(g.ratio)} of a ${d.window_hours}-hour day${
          d.unobserved_outage_hours ? ` · ${fmt(d.unobserved_outage_hours)} h unobserved` : ""}${
          d.quarantined_flapping_episodes ? ` · ${d.quarantined_flapping_episodes} flapping asset withheld` : ""}</div>
      `));
      hit.addEventListener("mouseleave", hideTip);
      svg.appendChild(hit);
    });

    return svg;
  }

  // --- station breakdown ----------------------------------------------------
  function stationBars(stations) {
    const rows = stations.slice(0, 8);
    const rowH = 34, padL = 200, padR = 60, W = 960;
    const H = rows.length * rowH + 8;
    const max = rows.reduce((m, s) => Math.max(m, s.outage_hours), 0) || 1;
    const svg = el("svg", {
      viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
      "aria-label": "Outage-hours by station",
    });

    rows.forEach((s, i) => {
      const y = i * rowH + 4;
      const w = ((W - padL - padR) * s.outage_hours) / max;
      svg.appendChild(el("text", {
        x: padL - 12, y: y + 17, "text-anchor": "end",
        fill: "var(--text-secondary)", "font-size": 12.5,
      }, s.station_name));
      // ≤24px thick, 4px rounded data-end, square at the baseline
      const bar = el("path", {
        d: `M${padL},${y + 2} H${padL + Math.max(0, w - 4)} a4,4 0 0 1 4,4 v12 a4,4 0 0 1 -4,4 H${padL} Z`,
        fill: "var(--series-1)",
      });
      svg.appendChild(bar);
      svg.appendChild(el("text", {
        x: padL + w + 10, y: y + 17, fill: "var(--text-primary)", "font-size": 12.5,
        style: "font-variant-numeric: tabular-nums",
      }, `${fmt(s.outage_hours, 0)} h`));

      const hit = el("rect", {
        x: padL, y, width: W - padL - padR, height: rowH - 4,
        fill: "transparent", style: "cursor: default",
      });
      hit.addEventListener("mousemove", (e) => showTip(e, `
        <div class="t-date">${s.station_name}</div>
        <div class="t-row">${fmt(s.outage_hours)} outage-hours</div>
        <div class="t-flag">across published days only</div>`));
      hit.addEventListener("mouseleave", hideTip);
      svg.appendChild(hit);
    });
    return svg;
  }

  // --- page -----------------------------------------------------------------
  function render(data) {
    if (!data || !data.days || !data.days.length) {
      app.appendChild(html("div", "card empty",
        "<h2>No collection has run</h2><p class=\"sub\">This page renders " +
        "<code>site/data/accessibility-daily.json</code>, which is produced from the " +
        "event ledger. Until a reviewed shadow period has run, there is nothing to show — " +
        "and an empty dashboard is the honest state, not a broken one.</p>"));
      return;
    }
    if (data.demo) document.getElementById("demo-banner").hidden = false;

    const days = data.days;
    const published = days.filter((d) => d.publishable);
    const totalMid = published.reduce((s, d) => s + (d.total_outage_hours || 0), 0);
    const totalMin = published.reduce((s, d) => s + (d.total_outage_hours_min || 0), 0);
    const totalMax = published.reduce((s, d) => s + (d.total_outage_hours_max || 0), 0);
    const worst = published.reduce((m, d) => (m && m.total_outage_hours >= d.total_outage_hours ? m : d), null);
    // Counted in days: an episode touching several days appears in each of
    // their counts, so summing them would inflate the figure.
    const flappingDays = days.filter((d) => (d.quarantined_flapping_episodes || 0) > 0).length;
    const unobserved = days.reduce((s, d) => s + (d.unobserved_outage_hours || 0), 0);

    // KPI row
    const kpis = html("div", "kpis");
    kpis.appendChild(html("div", "tile hero",
      `<div class="label">Outage-hours, ${published.length} measured days</div>
       <div class="value">${fmt(totalMid, 0)}</div>
       <div class="note">between ${fmt(totalMin, 0)} and ${fmt(totalMax, 0)} — polling cannot date a change to the second</div>`));
    kpis.appendChild(html("div", "tile",
      `<div class="label">Worst day</div>
       <div class="value">${worst ? fmt(worst.total_outage_hours, 0) + " h" : "—"}</div>
       <div class="note">${worst ? shortDate(worst.date) : "no measured day"}</div>`));
    kpis.appendChild(html("div", "tile",
      `<div class="label">Days withheld</div>
       <div class="value">${data.days_withheld}</div>
       <div class="note">of ${days.length} — coverage too low to support a figure</div>`));
    kpis.appendChild(html("div", "tile",
      `<div class="label">Unobserved outage time</div>
       <div class="value">${fmt(unobserved, 1)} h</div>
       <div class="note">inside episodes we lost sight of</div>`));
    app.appendChild(kpis);

    // time series
    const chart = html("section");
    const card = html("div", "card");
    card.appendChild(html("h2", null, "Elevator outage-hours per day"));
    card.appendChild(html("p", "sub",
      "The line is the midpoint estimate; the band is the range the observations actually " +
      "support. Hatched days were not watched well enough to carry a figure — the line stops " +
      "rather than crossing them, because a gap in collection is not a quiet day."));
    const scroller = html("div", "scroller");
    scroller.appendChild(timeSeries(days));
    card.appendChild(scroller);

    const legend = html("ul", "legend");
    legend.innerHTML = `
      <li><span class="key line" style="background:var(--series-1)"></span> Outage-hours (midpoint)</li>
      <li><span class="key" style="background:var(--series-1);opacity:.16"></span> Range the data supports</li>
      <li><span class="key" style="background:var(--status-good);opacity:.55"></span> Fully watched</li>
      <li><span class="key" style="background:linear-gradient(to top, var(--status-warning) 55%, var(--grid) 55%)"></span> Partly watched — cell height is the share seen</li>
      <li><span class="key" style="border:1.5px solid var(--status-critical)"></span> Insufficient — no figure</li>`;
    card.appendChild(legend);
    chart.appendChild(card);
    app.appendChild(chart);

    // stations
    if (data.stations && data.stations.length) {
      const s = html("section");
      const c = html("div", "card");
      c.appendChild(html("h2", null, "Where the hours fell"));
      c.appendChild(html("p", "sub", data.stations_note || ""));
      const sc = html("div", "scroller");
      sc.appendChild(stationBars(data.stations));
      c.appendChild(sc);
      s.appendChild(c);
      app.appendChild(s);
    }

    // data quality
    const dq = html("section");
    const dqc = html("div", "card");
    dqc.appendChild(html("h2", null, "What this page is not sure about"));
    dqc.appendChild(html("p", "sub",
      "Kept beside the numbers rather than in a footnote, because it is the part " +
      "that decides how much the numbers are worth."));
    dqc.appendChild(html("ul", null, `
      <li><strong>${data.days_withheld}</strong> day(s) carry no figure: coverage fell below the publishing threshold.</li>
      <li><strong>${fmt(unobserved, 1)} h</strong> of outage time fell inside a window where the source was unreachable, so its duration is bounded rather than known.</li>
      <li><strong>${flappingDays}</strong> day(s) contained outages from an asset the source flipped repeatedly; those are excluded from the headline figures and reported here instead.</li>
      <li>Every duration is a range. A change observed by polling is known to an interval, never to an instant.</li>`));
    dq.appendChild(dqc);
    app.appendChild(dq);

    // table view
    const tv = html("details");
    tv.appendChild(html("summary", null, "Table view — every value on this page"));
    const wrap = html("div", "scroller");
    let rows = "";
    days.forEach((d) => {
      const g = grade(d);
      rows += `<tr>
        <td>${d.date}</td>
        <td class="${d.publishable ? "" : "withheld"}">${d.publishable ? fmt(d.total_outage_hours) : "withheld"}</td>
        <td>${d.publishable ? fmt(d.total_outage_hours_min) : "—"}</td>
        <td>${d.publishable ? fmt(d.total_outage_hours_max) : "—"}</td>
        <td>${d.publishable ? d.episode_count : "—"}</td>
        <td>${pct(g.ratio)}</td>
        <td>${d.window_hours}</td>
        <td>${g.label}</td></tr>`;
    });
    wrap.appendChild(html("table", null,
      `<thead><tr><th>Date</th><th>Outage-hours</th><th>Low</th><th>High</th>
       <th>Outages</th><th>Coverage</th><th>Window h</th><th>State</th></tr></thead>
       <tbody>${rows}</tbody>`));
    tv.appendChild(wrap);
    app.appendChild(tv);
  }

  const embedded = window.__DEMO_DATA__;
  if (embedded) {
    render(embedded);
  } else {
    fetch("data/accessibility-daily.json")
      .then((r) => (r.ok ? r.json() : null))
      .then(render)
      .catch(() => render(null));
  }
})();
