(function () {
  'use strict';
  const app = document.getElementById('app');
  const fmt = value => value == null ? '—' : value.toLocaleString('de-DE', {maximumFractionDigits:1});
  const make = (tag, text, cls) => {const node = document.createElement(tag); if(text !== undefined) node.textContent = text; if(cls) node.className = cls; return node;};
  function empty(failed = false) {
    app.replaceChildren();
    const box = make('section', undefined, 'data-empty');
    box.append(make('h2', failed ? 'Die Datengrundlage ist nicht verfügbar.' : 'Noch kein belastbarer Verlauf.'));
    box.append(make('p', failed ? 'Die Zeitreihe konnte nicht geladen oder geprüft werden. Daraus folgt weder ein störungsfreier Betrieb noch eine Ausfallzahl.' : 'Für tägliche Ausfallzeiten liegen noch nicht genügend geprüfte Beobachtungen vor. Einzelne Momentaufnahmen reichen dafür nicht aus. Deshalb stehen hier noch keine Zeitreihe und keine Rangliste.'));
    const link = make('a', 'Datierte Momentaufnahme ansehen →', 'outline-link'); link.href = 'index.html#beobachtungen'; box.append(link); app.append(box);
  }
  function render(data) {
    if (!TransitData.daily(data)) {empty(true); return;}
    if (!data.days.length) {empty(); return;}
    app.replaceChildren();
    document.getElementById('demo-banner').hidden = data.demo !== true;
    const days = [...data.days].sort((a,b) => a.date.localeCompare(b.date));
    const published = days.filter(day => day.publishable);
    const sum = key => published.reduce((value, day) => value + day[key], 0);
    const kpis = make('div', undefined, 'kpis');
    const metrics = [
      ['Stationsstunden mit Ausfall', published.length ? fmt(sum('total_outage_hours')) + ' h' : '—', published.length ? 'Mittelwert der Grenzen: ' + fmt(sum('total_outage_hours_min')) + ' bis ' + fmt(sum('total_outage_hours_max')) + ' h; nur ausreichend beobachtete Tage.' : 'Kein Tag trägt eine belastbare Ausfallzeit.'],
      ['Tage mit ausreichender Abdeckung', String(published.length) + ' / ' + days.length, 'Ausgelassene Tage werden nicht als Null behandelt.'],
      ['Zeitraum', days[0].date + ' – ' + days.at(-1).date, 'Kalendertage in Berlin; Daten aus dem erfassten Quellenbereich.'],
    ];
    for (const [label, value, note] of metrics) {
      const tile = make('div', undefined, 'tile'); tile.append(make('p', label, 'label'), make('p', value, 'value'), make('p', note, 'note'));
      if(label === 'Zeitraum') tile.querySelector('.value').style.fontSize = '1.3rem'; kpis.append(tile);
    }
    app.append(kpis);
    const card = make('section', undefined, 'data-card');
    card.append(make('h2', 'Ausfallzeit und ihre Grenzen'), make('p', 'Die Linie zeigt die Mitte des belegbaren Intervalls. Senkrechte Bänder zeigen Unter- und Obergrenze. Schraffierte Tage bleiben ohne Wert; Linien überspringen keine Lücken.'));
    const scroll = make('div', undefined, 'chart-scroll'); scroll.append(chart(days)); card.append(scroll);
    const legend = make('ul', undefined, 'chart-legend'); ['Mittelpunkt','Belegbares Intervall','Keine ausreichende Beobachtung'].forEach(text => legend.append(make('li',text))); card.append(legend); app.append(card);
    const tableBox = make('section', undefined, 'data-card'); tableBox.append(make('h2','Alle Werte mit Abdeckung'));
    const wrap = make('div', undefined, 'table-scroll'); const table = make('table'); table.append(make('caption','Tageswerte · Einheit: Stationsstunden mit mindestens einem gemeldeten Aufzugsausfall'));
    const head = make('thead'); const row = make('tr');
    ['Tag','Mittelpunkt','Untergrenze','Obergrenze','Quellenabdeckung','Taglänge'].forEach(label => {const th=make('th',label); th.scope='col'; row.append(th);}); head.append(row);table.append(head);
    const body=make('tbody');
    days.forEach(day => {
      const tr=make('tr'); const th=make('th',day.date); th.scope='row'; tr.append(th);
      const values=[day.publishable ? fmt(day.total_outage_hours)+' h' : 'Kein Wert',day.publishable ? fmt(day.total_outage_hours_min)+' h' : '—',day.publishable ? fmt(day.total_outage_hours_max)+' h' : '—',Object.entries(day.coverage).map(([source,coverage])=> source+': '+fmt(coverage*100)+' %').join('; ') || 'Keine Beobachtung',fmt(day.window_hours)+' h'];
      values.forEach(value=>tr.append(make('td',value,day.publishable ? '' : 'withheld')));body.append(tr);
    });table.append(body);wrap.append(table);tableBox.append(wrap);app.append(tableBox);
    if (Array.isArray(data.stations) && data.stations.length && published.length) {
      const stationBox=make('section',undefined,'data-card');stationBox.append(make('h2','Verteilung auf beobachtete Stationen'),make('p','Summen ausschließlich aus Tagen mit ausreichender Quellenabdeckung. Keine Rangliste der Zugänglichkeit oder Zuverlässigkeit. Unterschiedliche Stationsausstattung und fehlende Beobachtungen bleiben unberücksichtigt.'));
      const table=make('table');table.append(make('caption','Gemeldete Ausfallzeit nach Station'));
      const body=make('tbody');
      data.stations.forEach(station=>{if(typeof station.station_name!=='string' || typeof station.outage_hours!=='number' || !Number.isFinite(station.outage_hours) || station.outage_hours<0) return;const row=make('tr');const label=make('th',station.station_name);label.scope='row';row.append(label,make('td',fmt(station.outage_hours)+' h'));body.append(row);});
      table.append(body);const wrap=make('div',undefined,'table-scroll');wrap.append(table);stationBox.append(wrap);app.append(stationBox);
    }
  }
  function chart(days) {
    const ns='http://www.w3.org/2000/svg';
    const svgNode=(tag,attrs={},text)=>{const node=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,value));if(text!==undefined)node.textContent=text;return node;};
    const width=1000,height=320,left=60,top=25,bottom=255,band=900/days.length;
    const highest=Math.max(1,...days.filter(day=>day.publishable).map(day=>day.total_outage_hours_max));
    const max=Math.ceil(highest/5)*5;
    const x=index=>left+(index+.5)*band;const y=value=>bottom-value/max*(bottom-top);
    const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':'Ausfallzeiten mit Unsicherheitsintervallen. Alle Werte stehen in der folgenden Tabelle.'});
    const defs=svgNode('defs');const pattern=svgNode('pattern',{id:'unobserved',width:8,height:8,patternUnits:'userSpaceOnUse',patternTransform:'rotate(45)'});pattern.append(svgNode('rect',{width:8,height:8,fill:'#eef2f6'}),svgNode('path',{d:'M0 0 V8',stroke:'#b6c2cd','stroke-width':2}));defs.append(pattern);svg.append(defs);
    for(let i=0;i<=5;i++){const value=max*i/5;svg.append(svgNode('line',{x1:left,x2:960,y1:y(value),y2:y(value),stroke:'#d6dee4'}),svgNode('text',{x:left-10,y:y(value)+4,'text-anchor':'end',fill:'#536575','font-size':14},fmt(value)));}
    svg.append(svgNode('text',{x:left,y:15,fill:'#536575','font-size':14},'Stationsstunden'));
    days.forEach((day,index)=>{
      if(!day.publishable) svg.append(svgNode('rect',{x:left+index*band,y:top,width:band,height:bottom-top,fill:'url(#unobserved)'}));
      else {
        svg.append(svgNode('line',{x1:x(index),x2:x(index),y1:y(day.total_outage_hours_min),y2:y(day.total_outage_hours_max),stroke:'#a3bdf7','stroke-width':Math.max(3,Math.min(16,band*.6))}));
        if(index>0&&days[index-1].publishable&&Date.parse(day.date)-Date.parse(days[index-1].date)===86400000)svg.append(svgNode('line',{x1:x(index-1),x2:x(index),y1:y(days[index-1].total_outage_hours),y2:y(day.total_outage_hours),stroke:'#164ed9','stroke-width':2}));
        svg.append(svgNode('circle',{cx:x(index),cy:y(day.total_outage_hours),r:3,fill:'#164ed9'}));
      }
      if(index % Math.max(1,Math.ceil(days.length/7))===0) svg.append(svgNode('text',{x:x(index),y:285,'text-anchor':'middle',fill:'#536575','font-size':14},day.date.slice(8)+'.'+day.date.slice(5,7)+'.'));
    });return svg;
  }
  // Synthetic fixtures must opt in visibly; production data never silently falls back to a demo.
  if(window.__DEMO_DATA__) render({...window.__DEMO_DATA__,demo:true});
  else fetch('data/accessibility-daily.json',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error('Unavailable');return response.json();}).then(render).catch(()=>empty(true));
})();
