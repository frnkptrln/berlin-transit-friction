(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = () => ({
    stepFree: document.querySelector('[name="mobility"]:checked').value === 'step-free',
    lift: $('lift-state').value, alternative: $('alternative').checked, backup: $('backup').checked,
  });
  const initial = TransitScenario.readLink(location.search);
  let baseline = initial.baseline;
  function setControls(options) {
    document.querySelector('[name="mobility"][value="' + (options.stepFree ? 'step-free' : 'stairs') + '"]').checked = true;
    $('lift-state').value = options.lift; $('alternative').checked = options.alternative; $('backup').checked = options.backup;
  }
  setControls(initial.current);
  if (initial.invalid) $('scenario-notice').textContent = 'Der Szenario-Link ist ungültig oder hat eine unbekannte Version. Gezeigt wird die Startlage.';
  const copy = {
    blocked: ['Kein stufenloser Weg zum Ziel', 'Im Modell endet dein Weg am Zielbahnsteig. Der fahrende Zug allein reicht nicht.', '×'],
    unknown: ['Der Zugang ist nicht gesichert', 'Der Aufzugsstatus fehlt. Ein möglicher Weg ist noch kein bestätigter Weg.', '?'],
    detour: ['Das Ziel bleibt erreichbar. Mit Umweg.', 'Du fährst eine Station weiter, nutzt dort den Aufzug und gehst über den Außenweg zurück.', '↳'],
    direct: ['Dein Weg ist durchgehend möglich', 'Die Verbindung von der Straße bis zum Ziel ist im Modell verfügbar.', '✓'],
  };
  function update() {
    const options = state();
    const result = TransitJourney.evaluate(options);
    const selected = new Set((result.path || result.graph.slice(0, 2)).map(e => e.id));
    for (const edge of result.graph) {
      $('edge-' + edge.id).setAttribute('class', selected.has(edge.id) ? 'current' : edge.state);
    }
    $('result').dataset.outcome = result.outcome;
    const [title, description, symbol] = copy[result.outcome];
    $('result-title').textContent = title;
    $('result-copy').textContent = description;
    document.querySelector('.result-symbol').textContent = symbol;
    $('section-count').textContent = result.path ? (result.extraSections ? '+' + result.extraSections : result.path.length) : '—';
    $('section-label').textContent = result.path ? (result.extraSections ? 'zusätzliche Wegabschnitte' : 'Wegabschnitte im Modell') : result.outcome === 'unknown' ? 'Zugang ungeklärt' : 'Ziel nicht erreichbar';
    $('lift-marker').setAttribute('class', options.lift);
    $('lift-symbol').textContent = { failed: '×', ok: '✓', unknown: '?' }[options.lift];
    $('lift-map-label').textContent = { failed: '× Aufzug am Ziel ausgefallen', ok: '✓ Aufzug am Ziel in Betrieb', unknown: '? Status des Aufzugs am Ziel unbekannt' }[options.lift];
    $('network-description').textContent = title + '. ' + description + ' Schematisches, frei erfundenes Netzwerk.';
    const route = result.path ? result.path.map(e => e.label) : ['Aufzug zum Startbahnsteig', 'Fahrt zur Zielstation', options.lift === 'unknown' ? 'Zugang zur Straße: Status ungeklärt' : 'Zugang zur Straße: unterbrochen'];
    $('route-list').replaceChildren(...route.map(label => {const item = document.createElement('li'); item.textContent = label; return item;}));
    $('route-insight').textContent = !options.stepFree && options.lift !== 'ok' && !options.backup
      ? 'Die Treppe hält deinen Weg offen. Wer einen stufenlosen Zugang braucht, hat diese Alternative nicht.'
      : result.outcome === 'detour' ? 'Fünf statt drei Abschnitte. Wie anstrengend oder lang ein realer Umweg ist, hängt von den konkreten Wegen und Bedürfnissen ab.'
      : options.backup ? 'Der zweite Aufzug muss unabhängig nutzbar sein. Zwei Aufzüge hintereinander bieten diese Absicherung nicht.'
      : options.lift === 'unknown' ? 'Eine fehlende Meldung wird hier nicht als funktionierender Aufzug behandelt.'
      : options.lift === 'ok' ? 'Die Reparatur stellt den direkten Zugang wieder her. Im Modell sind keine Ausfalldauer und keine Reparaturkosten hinterlegt.'
      : 'Ergänze einen Umweg oder einen zweiten Aufzug, um den Unterschied zu sehen.';
    updateComparison(options);
  }
  function updateComparison(options) {
    const comparison = TransitScenario.compare(baseline, options);
    for (const [name, value] of [['before', comparison.before], ['after', comparison.after]]) {
      const titles = {stepFree:'Weg',lift:'Zielaufzug',alternative:'Umweg',backup:'Zweiter Aufzug'};
      $(name + '-settings').textContent = Object.keys(titles).map(key => titles[key] + ': ' + TransitScenario.describe(key,value.options[key])).join(' · ');
      $(name + '-outcome').textContent = copy[value.outcome][0];
      $(name + '-sections').textContent = value.sections === null ? 'Keine bestätigte vollständige Wegkette' : value.sections + ' Wegabschnitte im Modell';
    }
    const delta = comparison.sectionDelta;
    $('comparison-insight').textContent = !comparison.changes.length ? 'Die Einstellungen entsprechen dem gemerkten Vergleichspunkt.'
      : delta !== null ? (delta === 0 ? 'Beide Varianten haben gleich viele Wegabschnitte. Der verfügbare Zugang kann sich trotzdem unterscheiden.'
        : 'Die aktuelle Variante hat ' + Math.abs(delta) + (delta > 0 ? ' zusätzliche' : ' weniger') + ' Wegabschnitte als der Vergleichspunkt.')
      : comparison.after.path ? 'Die aktuelle Variante hat eine bestätigte Wegkette, die im Vergleichspunkt fehlt.'
      : comparison.before.path ? 'Die aktuelle Variante hat keine bestätigte Wegkette mehr.'
      : 'Keine Variante hat eine bestätigte Wegkette. Unbekannte Zugänge bleiben ungeklärt.';
    $('mobility-change').hidden = !comparison.mobilityChanged;
    $('scenario-changes').replaceChildren(...comparison.changes.map(change => {
      const item = document.createElement('li'); item.textContent = change.label + ': ' + change.before + ' → ' + change.after; return item;
    }));
    const href = TransitScenario.link(location.href, options, baseline);
    $('scenario-link').value = href;
    // A blocked History API must not disable the model or the explicit copy link.
    const pageURL = new URL(href); pageURL.hash = location.hash;
    try { if (pageURL.href !== location.href) history.replaceState(null,'',pageURL.href); } catch (_) {}
  }
  function reset() {
    baseline = {...TransitScenario.defaults}; setControls(TransitScenario.defaults);
    $('scenario-notice').textContent = ''; $('scenario-link-label').hidden = true;
    update();
  }
  document.querySelectorAll('.control-panel input,.control-panel select').forEach(el => el.addEventListener('change', update));
  $('reset').addEventListener('click', reset);
  $('remember-scenario').addEventListener('click', () => {
    baseline = {...state()}; update(); $('scenario-notice').textContent = 'Vergleichspunkt gemerkt. Verändere jetzt die Einstellungen oben.';
  });
  $('share-scenario').addEventListener('click', async () => {
    const href = TransitScenario.link(location.href,state(),baseline);
    try { await navigator.clipboard.writeText(href); $('scenario-notice').textContent = 'Vergleichslink kopiert.'; }
    catch (_) {
      $('scenario-link-label').hidden = false; $('scenario-link').value = href;
      $('scenario-link').focus(); $('scenario-link').select();
      $('scenario-notice').textContent = 'Automatisches Kopieren ist nicht verfügbar. Den markierten Link kannst du selbst kopieren.';
    }
  });
  $('download-scenario').addEventListener('click', () => {
    const comparison = TransitScenario.compare(baseline,state());
    const url = URL.createObjectURL(new Blob([JSON.stringify(comparison,null,2) + '\n'],{type:'application/json'}));
    const link = document.createElement('a'); link.href=url; link.download='wege-modell-vergleich.json'; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url),1000);
    $('scenario-notice').textContent = 'Vergleich des fiktiven Modells heruntergeladen.';
  });
  addEventListener('popstate', () => {
    const restored = TransitScenario.readLink(location.search); baseline = restored.baseline; setControls(restored.current); update();
    $('scenario-notice').textContent = restored.invalid ? 'Ungültiger Szenario-Link; Startlage wiederhergestellt.' : '';
  });
  document.querySelectorAll('[data-experiment]').forEach(button => button.addEventListener('click', () => {
    reset();
    if (button.dataset.experiment === 'backup') $('backup').checked = true;
    else $('lift-state').value = 'ok';
    update(); $('experiment').scrollIntoView({ block: 'start' });
    (button.dataset.experiment === 'backup' ? $('backup') : $('lift-state')).focus({preventScroll:true});
  }));
  update();
})();

(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const date = value => new Date(value).toLocaleString('de-DE', {timeZone: 'Europe/Berlin', day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'}) + ' Uhr (Berlin)';
  const el = (tag, text, className) => { const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; return node; };
  function show(data) {
    if (!TransitData.snapshot(data) || TransitData.freshness(data) === 'future') throw new Error('Invalid observation');
    function freshness() {
      $('snapshot-status').textContent = TransitData.freshness(data) === 'stale' ? 'Ältere Momentaufnahme · kein aktueller Zustand' : 'Datierte Momentaufnahme · keine Live-Daten';
    }
    freshness();
    setInterval(freshness, 60000);
    $('snapshot-title').textContent = 'Quelle meldete ' + data.parsed_outage_count + ' ausgefallene Aufzüge in Berlin und Brandenburg.';
    $('snapshot-note').textContent = 'Quellenstand: ' + date(data.source_updated_at) + '. Abgerufen: ' + date(data.observed_at) + '. Einmalig abgeglichene Meldeliste; keine Aussage über die Dauer oder heutige Erreichbarkeit. Für deine Fahrt den aktuellen Zustand an der Quelle prüfen.';
    $('snapshot-controls').hidden = false;
    function renderStations() {
      const query = $('station-search').value.trim().toLocaleLowerCase('de');
      const region = $('region').value;
      const all = data.stations.filter(station => region === 'all' || station.station_id.startsWith('de:11000:'));
      const selected = all.filter(station => station.station_name.toLocaleLowerCase('de').includes(query));
      const count = selected.reduce((sum, station) => sum + station.assets.length, 0);
      $('snapshot-count').textContent = count + ' gemeldete Aufzüge an ' + selected.length + ' Stationen' + (query ? ' im Suchergebnis' : ' in der Auswahl');
      const cards = selected.map(station => {
        const card = el('article', '', 'station-card');
        card.append(el('h3', station.station_name), el('p', station.assets.length + (station.assets.length === 1 ? ' Aufzug als ausgefallen gemeldet' : ' Aufzüge als ausgefallen gemeldet'), 'outage-label'));
        const list = el('ul');
        for (const asset of station.assets) {
          const item = el('li'); const link = el('a', 'Aufzug ' + asset.asset_id + ' an der Quelle ↗');
          link.href = TransitData.sourceLink(asset.source_url); item.append(link); list.append(item);
        }
        card.append(list, el('p', 'Eine Aufzugsmeldung ist kein Nachweis, dass alle Zugänge der Station ausfallen.', 'station-meta'));
        return card;
      });
      if (!cards.length) cards.push(el('p', 'Keine passende Meldung in dieser Momentaufnahme. Das belegt keinen störungsfreien Betrieb.', 'notice'));
      $('station-list').replaceChildren(...cards);
    }
    $('region').addEventListener('change', renderStations);
    $('station-search').addEventListener('input', renderStations);
    renderStations();
  }
  fetch('data/accessibility-snapshot.json', {cache:'no-store'}).then(response => {
    if (!response.ok) throw new Error('No snapshot'); return response.json();
  }).then(show).catch(() => {
    $('snapshot-status').textContent = 'Keine geprüfte Momentaufnahme verfügbar';
    $('snapshot-title').textContent = 'Aktuelle Zustände an der Quelle prüfen.';
    $('snapshot-note').textContent = 'Eine Momentaufnahme konnte nicht geladen oder geprüft werden. Das ist keine Aussage über funktionierende Aufzüge. Das Erklärmodell oben bleibt nutzbar.';
    $('snapshot-controls').hidden = true; $('station-list').replaceChildren();
  });
})();
