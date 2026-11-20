/* Median sold prices by postcode district and year: pick an area, a district and a split, and see the years.
   Client-side only: it reads same-site JSON files (the latest index, then one area's file), sets no cookie, stores nothing and sends
   nothing. Pure functions first (tested in Node), the page code last. All text is set with textContent. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SoldHistory = factory();
})(this, function () {
  'use strict';
  var BASE = '/data/sold-prices/history/';
  var SPLITS = ['all', 'detached', 'semi-detached', 'terraced', 'flat', 'freehold', 'leasehold', 'new-build', 'existing'];
  var SPLIT_LABEL = { all: 'All sales', detached: 'Detached', 'semi-detached': 'Semi-detached', terraced: 'Terraced', flat: 'Flats',
    freehold: 'Freehold', leasehold: 'Leasehold', 'new-build': 'New-build', existing: 'Existing homes' };

  function pounds(n) { return typeof n === 'number' ? '£' + Math.round(n).toLocaleString('en-GB') : '–'; }   // a withheld figure shows as a dash
  function isArea(index, area) { return !!index && Array.isArray(index.areas) && index.areas.some(function (a) { return a.area === area; }); }
  function monthOk(m) { return typeof m === 'string' && /^[0-9]{4}-(0[1-9]|1[0-2])$/.test(m); }
  // The only two files this page ever asks for are named from the index, never from the address bar.
  function areaUrl(index, area, ext) { return !!index && monthOk(index.month) && isArea(index, area) && (ext === 'json' || ext === 'csv') ? BASE + index.month + '/history_' + area + '.' + ext : null; }

  function districtsOf(doc) {
    var seen = {}, out = [];
    doc.rows.forEach(function (r) { if (!seen[r.district]) { seen[r.district] = 1; out.push(r.district); } });
    return out.sort(function (a, b) { return a < b ? -1 : a > b ? 1 : 0; });
  }
  function splitsOf(doc, district) {
    var has = {};
    doc.rows.forEach(function (r) { if (r.district === district) has[r.split] = 1; });
    return SPLITS.filter(function (s) { return has[s]; });
  }
  // The rows of one district and one split, by year (only years with sales are in the file).
  function rowsFor(doc, district, split) {
    return doc.rows.filter(function (r) { return r.district === district && r.split === split; }).sort(function (a, b) { return a.year - b.year; });
  }
  function noteFor(row) { return row.lowSample ? (row.median === null ? 'Fewer than 5 sales: figures withheld' : 'Small sample: fewer than 20 sales') : ''; }

  return { BASE: BASE, SPLITS: SPLITS, SPLIT_LABEL: SPLIT_LABEL, pounds: pounds, isArea: isArea, areaUrl: areaUrl, districtsOf: districtsOf, splitsOf: splitsOf, rowsFor: rowsFor, noteFor: noteFor };
});

/* ------------------------------ the page ------------------------------ */
(function () {
  'use strict';
  if (typeof document === 'undefined' || !document.getElementById('sh-app')) return;
  var H = (typeof window !== 'undefined' && window.SoldHistory) || this.SoldHistory;
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, text, cls) { var e = document.createElement(tag); if (text !== undefined && text !== null) e.textContent = text; if (cls) e.className = cls; return e; };
  var clear = function (e) { while (e.firstChild) e.removeChild(e.firstChild); return e; };
  var index = null, doc = null, cache = {};

  function option(sel, value, label) { var o = el('option', label); o.value = value; sel.appendChild(o); }
  function get(url) { return fetch(url, { credentials: 'omit', cache: 'no-cache' }).then(function (r) { return r.ok ? r.json() : Promise.reject(); }); }
  function fail() { $('sh-status').textContent = 'The table could not be loaded just now. The CSV and JSON downloads below still work. Please try again later.'; }

  function renderTable() {
    var d = $('sh-district').value, s = $('sh-split').value;
    var rows = doc ? H.rowsFor(doc, d, s) : [], body = clear($('sh-body'));
    $('sh-table').hidden = !rows.length;
    clear($('sh-caption')).appendChild(document.createTextNode(d + ', ' + (H.SPLIT_LABEL[s] || s) + ': median sold price by year (nominal pounds, standard sales only)'));
    rows.forEach(function (r) {
      var tr = el('tr');
      tr.appendChild(el('td', String(r.year)));
      tr.appendChild(el('td', r.sales.toLocaleString('en-GB'), 'num'));
      tr.appendChild(el('td', H.pounds(r.lowerQuartile), 'num'));
      tr.appendChild(el('td', H.pounds(r.median), 'num'));
      tr.appendChild(el('td', H.pounds(r.upperQuartile), 'num'));
      tr.appendChild(el('td', H.noteFor(r)));
      body.appendChild(tr);
    });
  }
  function fillSplits() {
    var sel = clear($('sh-split')), splits = H.splitsOf(doc, $('sh-district').value), keep = sel.value;
    splits.forEach(function (s) { option(sel, s, H.SPLIT_LABEL[s] || s); });
    sel.value = splits.indexOf('all') >= 0 ? 'all' : splits[0];
    sel.disabled = !splits.length;
    renderTable();
  }
  function showArea(area, document_) {
    doc = document_;
    var dsel = clear($('sh-district')), ds = H.districtsOf(doc);
    ds.forEach(function (d) { option(dsel, d, d); });
    dsel.disabled = !ds.length;
    var files = clear($('sh-files')), csv = H.areaUrl(index, area, 'csv'), js = H.areaUrl(index, area, 'json');
    files.appendChild(document.createTextNode('Whole area ' + area + ': '));
    [[csv, 'CSV'], [js, 'JSON']].forEach(function (p, i) { if (i) files.appendChild(document.createTextNode(' and ')); var a = el('a', p[1]); a.href = p[0]; files.appendChild(a); });
    $('sh-status').textContent = '';
    fillSplits();
  }
  function pickArea() {
    var area = $('sh-area').value;
    if (!H.isArea(index, area)) return;
    if (cache[area]) { showArea(area, cache[area]); return; }
    $('sh-status').textContent = 'Loading area ' + area + '…';
    get(H.areaUrl(index, area, 'json')).then(function (d) {
      if (!d || !Array.isArray(d.rows) || d.area !== area) return Promise.reject();
      cache[area] = d; showArea(area, d);
    }).catch(fail);
  }
  get(H.BASE + 'index.json').then(function (idx) {
    if (!idx || !Array.isArray(idx.areas) || !idx.areas.length) return Promise.reject();
    index = idx;
    var sel = clear($('sh-area'));
    idx.areas.forEach(function (a) { option(sel, a.area, a.area + ' (' + a.districts + (a.districts === 1 ? ' district)' : ' districts)')); });
    sel.disabled = false;
    sel.addEventListener('change', pickArea);
    $('sh-district').addEventListener('change', fillSplits);
    $('sh-split').addEventListener('change', renderTable);
    pickArea();
  }).catch(fail);
}).call(typeof window !== 'undefined' ? window : this);
