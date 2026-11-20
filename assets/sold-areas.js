/* Median sold prices by local authority and region, by year and quarter: pick a region, an authority (or the whole region), years or
   quarters, and one split, and see the periods. Client-side only: it reads same-site files (the latest index, then a region's files),
   sets no cookie, stores nothing and sends nothing. Pure functions first (tested in Node), the page code last. All text is set with
   textContent. Years come from the JSON files; quarters come from the CSV files (the quarterly JSON files are not published). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SoldAreas = factory();
})(this, function () {
  'use strict';
  var BASE = '/data/sold-prices/area-history/';
  var YEAR_SPLITS = ['all', 'detached', 'semi-detached', 'terraced', 'flat', 'freehold', 'leasehold', 'new-build', 'existing'];
  var QUARTER_SPLITS = ['all', 'detached', 'semi-detached', 'terraced', 'flat'];
  var SPLIT_LABEL = { all: 'All sales', detached: 'Detached', 'semi-detached': 'Semi-detached', terraced: 'Terraced', flat: 'Flats',
    freehold: 'Freehold', leasehold: 'Leasehold', 'new-build': 'New-build', existing: 'Existing homes' };
  var COLUMNS = ['periodType', 'period', 'geography', 'code', 'name', 'split', 'sales', 'median', 'lowerQuartile', 'upperQuartile', 'lowSample'];
  var KEY_RE = /^ah_(?:regions|[EW][0-9]{8,}_year|[EW][0-9]{8,}_qtr_(?:1995-2009|2010-onwards))$/;

  function pounds(n) { return typeof n === 'number' ? '£' + Math.round(n).toLocaleString('en-GB') : '–'; }   // a withheld figure shows as a dash
  function monthOk(m) { return typeof m === 'string' && /^[0-9]{4}-(0[1-9]|1[0-2])$/.test(m); }

  function entryOf(index, key) {
    if (!index || !Array.isArray(index.files) || typeof key !== 'string' || !KEY_RE.test(key)) return null;
    for (var i = 0; i < index.files.length; i++) if (index.files[i].key === key) return index.files[i];
    return null;
  }
  // The only files this page ever asks for are named from the index, never from the address bar. A quarterly file is asked for as CSV only.
  function fileUrl(index, key, ext) {
    var e = entryOf(index, key);
    if (!e || !monthOk(index.month)) return null;
    if (ext === 'csv' || (ext === 'json' && e.kind !== 'authority-quarter')) return BASE + index.month + '/' + key + '.' + ext;
    return null;
  }
  function regionsOf(index) {
    if (!index || !Array.isArray(index.files)) return [];
    return index.files.filter(function (e) { return e.kind === 'authority-year'; })
      .map(function (e) { return { code: e.region, name: e.regionName, authorities: e.authorities }; })
      .sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });
  }
  function quarterKeys(index, region) {
    return (index && Array.isArray(index.files) ? index.files : []).filter(function (e) { return e.kind === 'authority-quarter' && e.region === region; })
      .map(function (e) { return e.key; });
  }

  // RFC 4180 reader: quoted cells, doubled quotes, \n or \r\n line ends.
  function parseCsv(text) {
    var rows = [], row = [], cell = '', q = false, i = 0, c;
    while (i < text.length) {
      c = text.charAt(i);
      if (q) {
        if (c === '"') { if (text.charAt(i + 1) === '"') { cell += '"'; i += 2; continue; } q = false; i++; continue; }
        cell += c; i++; continue;
      }
      if (c === '"') { q = true; i++; continue; }
      if (c === ',') { row.push(cell); cell = ''; i++; continue; }
      if (c === '\r') { i++; continue; }
      if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; i++; continue; }
      cell += c; i++;
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    return rows;
  }
  function num(s) { return s === '' ? null : Number(s); }
  function rowsFromCsv(text) {
    var table = parseCsv(text);
    if (!table.length || table[0].join(',') !== COLUMNS.join(',')) throw new Error('unexpected CSV header');
    return table.slice(1).filter(function (r) { return r.length === COLUMNS.length; }).map(function (r) {
      return { periodType: r[0], period: r[1], geography: r[2], code: r[3], name: r[4], split: r[5], sales: Number(r[6]),
        median: num(r[7]), lowerQuartile: num(r[8]), upperQuartile: num(r[9]), lowSample: r[10] === 'true' };
    });
  }

  // The authorities of a region's yearly rows: code and name, by name.
  function authoritiesOf(rows) {
    var seen = {}, out = [];
    rows.forEach(function (r) { if (r.geography === 'authority' && !seen[r.code]) { seen[r.code] = 1; out.push({ code: r.code, name: r.name }); } });
    return out.sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });
  }
  function splitsFor(rows, code, periodType) {
    var has = {}, order = periodType === 'quarter' ? QUARTER_SPLITS : YEAR_SPLITS;
    rows.forEach(function (r) { if (r.code === code && r.periodType === periodType) has[r.split] = 1; });
    return order.filter(function (s) { return has[s]; });
  }
  // The rows of one area, one period type and one split, oldest period first (periods sort as text: 2024, 2024-Q3).
  function rowsFor(rows, code, periodType, split) {
    return rows.filter(function (r) { return r.code === code && r.periodType === periodType && r.split === split; })
      .sort(function (a, b) { return a.period < b.period ? -1 : a.period > b.period ? 1 : 0; });
  }
  function noteFor(row) { return row.lowSample ? (row.median === null ? 'Fewer than 5 sales: figures withheld' : 'Small sample: fewer than 20 sales') : ''; }

  return { BASE: BASE, YEAR_SPLITS: YEAR_SPLITS, QUARTER_SPLITS: QUARTER_SPLITS, SPLIT_LABEL: SPLIT_LABEL, COLUMNS: COLUMNS, pounds: pounds, entryOf: entryOf,
    fileUrl: fileUrl, regionsOf: regionsOf, quarterKeys: quarterKeys, parseCsv: parseCsv, rowsFromCsv: rowsFromCsv, authoritiesOf: authoritiesOf,
    splitsFor: splitsFor, rowsFor: rowsFor, noteFor: noteFor };
});

/* ------------------------------ the page ------------------------------ */
(function () {
  'use strict';
  if (typeof document === 'undefined' || !document.getElementById('sa-app')) return;
  var A = (typeof window !== 'undefined' && window.SoldAreas) || this.SoldAreas;
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, text, cls) { var e = document.createElement(tag); if (text !== undefined && text !== null) e.textContent = text; if (cls) e.className = cls; return e; };
  var clear = function (e) { while (e.firstChild) e.removeChild(e.firstChild); return e; };
  var index = null, regionRows = null, cache = {}, current = null, regionNames = {};     // cache: region code -> { year: rows, quarter: rows|null }

  function option(sel, value, label) { var o = el('option', label); o.value = value; sel.appendChild(o); }
  function fetchOk(url) { return fetch(url, { credentials: 'omit', cache: 'no-cache' }).then(function (r) { return r.ok ? r : Promise.reject(); }); }
  function getJson(url) { return fetchOk(url).then(function (r) { return r.json(); }); }
  function getText(url) { return fetchOk(url).then(function (r) { return r.text(); }); }
  function fail() { $('sa-status').textContent = 'The table could not be loaded just now. The CSV and JSON downloads below still work. Please try again later.'; }

  function loadRegionRows() {
    if (regionRows) return Promise.resolve(regionRows);
    return getJson(A.fileUrl(index, 'ah_regions', 'json')).then(function (d) {
      if (!d || !Array.isArray(d.rows)) return Promise.reject(); regionRows = d.rows; return regionRows;
    });
  }
  function loadYears(region) {
    if (cache[region] && cache[region].year) return Promise.resolve(cache[region].year);
    return getJson(A.fileUrl(index, 'ah_' + region + '_year', 'json')).then(function (d) {
      if (!d || !Array.isArray(d.rows) || d.area !== region) return Promise.reject();
      (cache[region] = cache[region] || {}).year = d.rows; return d.rows;
    });
  }
  function loadQuarters(region) {
    if (cache[region] && cache[region].quarter) return Promise.resolve(cache[region].quarter);
    return Promise.all(A.quarterKeys(index, region).map(function (k) { return getText(A.fileUrl(index, k, 'csv')).then(A.rowsFromCsv); }))
      .then(function (parts) { var all = [].concat.apply([], parts); (cache[region] = cache[region] || {}).quarter = all; return all; });
  }

  function selected() {
    var region = $('sa-region').value, area = $('sa-area').value, type = $('sa-period').value;
    return { region: region, area: area, type: type };
  }
  function rowsOfArea(s) {      // a promise of every row of the chosen area and period type
    if (s.area === s.region) return loadRegionRows();
    return s.type === 'quarter' ? loadQuarters(s.region) : loadYears(s.region);
  }
  function renderTable(rows, s) {
    var split = $('sa-split').value, shown = A.rowsFor(rows, s.area, s.type, split), body = clear($('sa-body'));
    var label = $('sa-area').options[$('sa-area').selectedIndex].textContent;
    $('sa-table').hidden = !shown.length;
    $('sa-period-head').textContent = s.type === 'quarter' ? 'Quarter' : 'Year';
    clear($('sa-caption')).appendChild(document.createTextNode(label + ', ' + (A.SPLIT_LABEL[split] || split) + ': median sold price by ' + s.type + ' (nominal pounds, standard sales only)'));
    shown.forEach(function (r) {
      var tr = el('tr');
      tr.appendChild(el('td', r.period));
      tr.appendChild(el('td', r.sales.toLocaleString('en-GB'), 'num'));
      tr.appendChild(el('td', A.pounds(r.lowerQuartile), 'num'));
      tr.appendChild(el('td', A.pounds(r.median), 'num'));
      tr.appendChild(el('td', A.pounds(r.upperQuartile), 'num'));
      tr.appendChild(el('td', A.noteFor(r)));
      body.appendChild(tr);
    });
  }
  function refresh(keepSplit) {
    var s = selected();
    $('sa-status').textContent = 'Loading…';
    rowsOfArea(s).then(function (rows) {
      var sel = $('sa-split'), keep = sel.value, splits = A.splitsFor(rows, s.area, s.type);
      clear(sel); splits.forEach(function (x) { option(sel, x, A.SPLIT_LABEL[x] || x); });
      sel.value = keepSplit && splits.indexOf(keep) >= 0 ? keep : (splits.indexOf('all') >= 0 ? 'all' : splits[0]);
      sel.disabled = !splits.length;
      current = { rows: rows, s: s };
      $('sa-status').textContent = '';
      renderTable(rows, s);
    }).catch(fail);
  }
  function pickRegion() {
    var region = $('sa-region').value, name = regionNames[region] || region;
    $('sa-status').textContent = 'Loading ' + name + '…';
    loadYears(region).then(function (rows) {
      var sel = clear($('sa-area'));
      option(sel, region, 'All of ' + name + ' (region)');
      A.authoritiesOf(rows).forEach(function (a) { option(sel, a.code, a.name); });
      sel.disabled = false; $('sa-period').disabled = false;
      var files = clear($('sa-files'));
      files.appendChild(document.createTextNode(name + ': '));
      [['ah_' + region + '_year', 'json', 'years, JSON'], ['ah_' + region + '_year', 'csv', 'years, CSV']].concat(A.quarterKeys(index, region).map(function (k) { return [k, 'csv', 'quarters ' + k.replace(/^.*_qtr_/, '') + ', CSV']; }))
        .forEach(function (p, i) { if (i) files.appendChild(document.createTextNode(' · ')); var a = el('a', p[2]); a.href = A.fileUrl(index, p[0], p[1]); files.appendChild(a); });
      refresh(false);
    }).catch(fail);
  }
  getJson(A.BASE + 'index.json').then(function (idx) {
    if (!idx || !Array.isArray(idx.files) || !idx.files.length) return Promise.reject();
    index = idx;
    var sel = clear($('sa-region'));
    A.regionsOf(idx).forEach(function (r) { regionNames[r.code] = r.name; option(sel, r.code, r.name + ' (' + r.authorities + (r.authorities === 1 ? ' authority)' : ' authorities)')); });
    sel.disabled = false;
    sel.addEventListener('change', pickRegion);
    $('sa-area').addEventListener('change', function () { refresh(true); });
    $('sa-period').addEventListener('change', function () { refresh(false); });
    $('sa-split').addEventListener('change', function () { if (current) renderTable(current.rows, current.s); });
    pickRegion();
  }).catch(fail);
}).call(typeof window !== 'undefined' ? window : this);
