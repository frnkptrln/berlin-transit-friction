/* An explicitly fictional network. Costs count edges, never minutes/metres. */
(function (root) {
  'use strict';
  const nodes = {
    start: 'Start · Straße', origin: 'Start · Bahnsteig',
    destination: 'Zielstation · Bahnsteig', goal: 'Ziel · Straße',
    next: 'Nachbarstation · Bahnsteig', exit: 'Nachbarstation · Straße',
  };
  function edges(options) {
    const { stepFree = true, lift = 'failed', alternative = false, backup = false } = options;
    return [
      { id: 'entry', from: 'start', to: 'origin', label: 'Aufzug zum Bahnsteig', state: 'ok' },
      { id: 'ride', from: 'origin', to: 'destination', label: 'Fahrt zur Zielstation', state: 'ok' },
      { id: 'lift', from: 'destination', to: 'goal', label: 'Aufzug am Ziel', state: lift },
      { id: 'stairs', from: 'destination', to: 'goal', label: 'Treppe am Ziel', state: stepFree ? 'excluded' : 'ok' },
      { id: 'backup', from: 'destination', to: 'goal', label: 'Zweiter, unabhängiger Aufzug', state: backup ? 'ok' : 'excluded' },
      { id: 'extra-ride', from: 'destination', to: 'next', label: 'Eine Station weiterfahren', state: alternative ? 'ok' : 'excluded' },
      { id: 'extra-lift', from: 'next', to: 'exit', label: 'Aufzug der Nachbarstation', state: alternative ? 'ok' : 'excluded' },
      { id: 'return', from: 'exit', to: 'goal', label: 'Über einen stufenlosen Außenweg zurück', state: alternative ? 'ok' : 'excluded' },
    ];
  }
  function shortestPath(graph, allowUnknown = false) {
    const queue = [{ node: 'start', path: [] }];
    const visited = new Set(['start']);
    while (queue.length) {
      const current = queue.shift();
      if (current.node === 'goal') return current.path;
      for (const edge of graph) {
        if (edge.state !== 'ok' && !(allowUnknown && edge.state === 'unknown')) continue;
        if (edge.from !== current.node || visited.has(edge.to)) continue;
        visited.add(edge.to);
        queue.push({ node: edge.to, path: [...current.path, edge] });
      }
    }
    return null;
  }
  function evaluate(options = {}) {
    const graph = edges(options);
    const path = shortestPath(graph);
    const possiblePath = shortestPath(graph, true);
    const baseline = shortestPath(edges({ ...options, lift: 'ok' }));
    return {
      graph, path, possiblePath,
      outcome: path ? (path.length > baseline.length ? 'detour' : 'direct') : possiblePath ? 'unknown' : 'blocked',
      extraSections: path ? path.length - baseline.length : null,
      baselineSections: baseline.length,
    };
  }
  const api = { nodes, edges, shortestPath, evaluate };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TransitJourney = api;
})(typeof globalThis === 'object' ? globalThis : this);
