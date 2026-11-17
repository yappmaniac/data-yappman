/* Basket check: pick items, see each shop's total. Client-side only: no network except two same-site JSON files, no cookies,
   nothing sent anywhere. Pure functions first (tested in Node), the page code last. All text is set with textContent. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Basket = factory();
})(this, function () {
  'use strict';
  var SHOPS = ['aldi', 'asda', 'sainsburys', 'tesco'];
  var NAME = { aldi: 'Aldi', asda: 'Asda', sainsburys: "Sainsbury's", tesco: 'Tesco' };
  var SCHEME = { tesco: 'Clubcard Price', sainsburys: 'Nectar Price' };
  var MAX_QTY = 20, STALE_MS = 2 * 24 * 3600 * 1000;
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

  function fmt(p) { return '£' + (p / 100).toFixed(2); }
  function dateText(iso) { var d = new Date(iso); return DAYS[d.getUTCDay()] + ' ' + d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); }
  function shortDate(iso) { var d = new Date(iso); return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()].slice(0, 3) + ' ' + d.getUTCFullYear(); }
  function timeWindow(from, to) { var a = from.slice(11, 16), b = to.slice(11, 16); return (a === b ? 'at ' + a : a + ' to ' + b) + ' UTC'; }
  function unitText(cell, p) {
    if (!cell.sz || !p) return '';
    if (cell.su === 'g') return fmt(Math.round(p / cell.sz * 1000)) + ' per kg';
    if (cell.su === 'ml') return fmt(Math.round(p / cell.sz * 1000)) + ' per litre';
    if (cell.su === 'ea') return fmt(Math.round(p / cell.sz)) + ' each';
    return '';
  }

  // One cell of the list as it stands today: what to show and whether it counts in totals.
  function cellInfo(item, shop, prices, opts, readDate) {
    var pin = item.cells[shop];
    if (!pin) return { state: 'none', text: 'No matching product at this shop.', counts: false };
    var c = (prices.cells[item.n] || {})[shop] || { s: 'x' };
    var base = { pin: pin, label: pin.q };
    if (c.s === 'x') return Object.assign(base, { state: 'none', text: 'We could not read a price for this product on ' + readDate + '.', counts: false });
    if (c.s === 'n') return Object.assign(base, { state: 'none', text: 'No price was shown for this product on ' + readDate + '.', counts: false });
    if (c.s === 'h') return Object.assign(base, { state: 'none', text: 'Held while we check the match.', counts: false });
    var useMember = !!(opts.schemes && opts.schemes[shop] && c.m);
    var price = useMember ? c.m : c.p, note = [];
    if (useMember) note.push(SCHEME[shop] + ' ' + fmt(c.m) + '; regular ' + fmt(c.p) + '.');
    else if (opts.schemes && opts.schemes[shop] && SCHEME[shop]) note.push('regular price (no member price shown)');
    var counts = true;
    if (pin.q === 'd') { counts = !!opts.includeDiff; note.push('Pack size differs (' + (pin.pack || 'size not shown') + ' here; the item is ' + item.name + ')' + (counts ? '.' : '; left out of totals unless you include different sizes.')); }
    if (pin.q === 'v') { counts = !!opts.includeDiff; note.push('Value-range product against other shops\' standard own-label' + (counts ? '.' : '; left out of totals unless you include different sizes.')); }
    if (c.f) note.push('An offer is listed for this item. The price is for one item; multibuy and card terms are not applied.');
    if (c.o === 2) note.push('Shown as out of stock on ' + readDate + ' (price shown for information; counted in the total).');
    return Object.assign(base, { state: 'priced', price: price, regular: c.p, member: c.m || 0, counts: counts, unit: unitText(pin, price), note: note, memberAvailable: !!c.m && !useMember });
  }

  function indexPicks(list, picks) {
    var byN = {}; list.items.forEach(function (it) { byN[it.n] = it; });
    return Object.keys(picks).map(function (n) { return { item: byN[n], qty: picks[n] }; }).filter(function (x) { return x.item && x.qty > 0; });
  }

  // Totals per shop and the lowest-total rule. Nothing is guessed: a cell that does not count is listed, never zero.
  function compute(list, prices, picks, opts, nowMs) {
    var readDate = shortDate(prices.readTo);
    var chosen = indexPicks(list, picks);
    var per = {}, i;
    SHOPS.forEach(function (shop) {
      var total = 0, priced = 0, missing = [];
      chosen.forEach(function (x) {
        var ci = cellInfo(x.item, shop, prices, opts, readDate);
        if (ci.state === 'priced' && ci.counts) { total += ci.price * x.qty; priced++; } else missing.push({ item: x.item, why: ci.text || (ci.note && ci.note.join(' ')) });
      });
      per[shop] = { total: total, priced: priced, of: chosen.length, missing: missing, complete: chosen.length > 0 && priced === chosen.length };
    });
    var stale = !!nowMs && (nowMs - Date.parse(prices.readTo)) > STALE_MS;
    var eligible = SHOPS.filter(function (s) { return per[s].complete; });
    var mark = { kind: 'none', shops: [] };
    if (chosen.length) {
      if (eligible.length >= 2) {
        var low = Math.min.apply(null, eligible.map(function (s) { return per[s].total; }));
        mark = { kind: 'lowest', shops: eligible.filter(function (s) { return per[s].total === low; }), count: eligible.length };
      } else if (eligible.length === 1) mark = { kind: 'only', shops: eligible };
      else mark = { kind: 'nobody', shops: [] };
    }
    // the second line: the items every shop prices
    var common = chosen.filter(function (x) { return SHOPS.every(function (s) { var ci = cellInfo(x.item, s, prices, opts, readDate); return ci.state === 'priced' && ci.counts; }); });
    var commonTotals = {};
    SHOPS.forEach(function (s) { commonTotals[s] = common.reduce(function (t, x) { return t + cellInfo(x.item, s, prices, opts, readDate).price * x.qty; }, 0); });
    // the split of the picked items by how they were matched, and the member prices not used
    var split = { s: 0, o: 0 };
    chosen.forEach(function (x) { var k = x.item.kind; split[k] = (split[k] || 0) + 1; });
    var memberNotUsed = { tesco: 0, sainsburys: 0 };
    chosen.forEach(function (x) { ['tesco', 'sainsburys'].forEach(function (s) { var ci = cellInfo(x.item, s, prices, Object.assign({}, opts, { schemes: {} }), readDate); if (ci.state === 'priced' && (prices.cells[x.item.n][s] || {}).m && !(opts.schemes && opts.schemes[s])) memberNotUsed[s]++; }); });
    return { per: per, chosen: chosen, mark: mark, stale: stale, common: common, commonTotals: commonTotals, split: split, memberNotUsed: memberNotUsed, readDate: readDate };
  }

  // How many items are priced at 4, 3, 2 or 1 shops today (default basis: cells that count).
  function coverage(list, prices) {
    var out = { 4: 0, 3: 0, 2: 0, 1: 0 }, rd = shortDate(prices.readTo);
    list.items.forEach(function (it) { var n = SHOPS.filter(function (s) { var ci = cellInfo(it, s, prices, {}, rd); return ci.state === 'priced' && ci.counts; }).length; if (n) out[n]++; });
    return out;
  }

  // Share link: #v1. then 3 characters per item (2 for its permanent number, 1 for the quantity), then ~ and three setting digits.
  var b36 = function (n, w) { var s = n.toString(36); while (s.length < w) s = '0' + s; return s; };
  function encodeShare(picks, opts) {
    var s = '#v1.';
    Object.keys(picks).map(Number).sort(function (a, b) { return a - b; }).forEach(function (n) { var q = Math.min(MAX_QTY, picks[n]); if (q > 0) s += b36(n, 2) + b36(q, 1); });
    return s + '~' + ((opts.schemes && opts.schemes.tesco) ? 1 : 0) + ((opts.schemes && opts.schemes.sainsburys) ? 1 : 0) + (opts.includeDiff ? 1 : 0);
  }
  function decodeShare(hash, list) {
    var m = /^#v1\.([0-9a-z]*)~([01]{3})$/.exec(hash || '');
    if (!m) return null;
    var known = {}, picks = {}, unknown = 0, retired = 0;
    list.items.forEach(function (it) { known[it.n] = true; });
    var retiredSet = {}; (list.retired || []).forEach(function (n) { retiredSet[n] = true; });
    if (m[1].length % 3) return null;
    for (var i = 0; i < m[1].length; i += 3) {
      var n = parseInt(m[1].slice(i, i + 2), 36), q = parseInt(m[1].slice(i + 2, i + 3), 36);
      if (!(q > 0 && q <= MAX_QTY)) continue;
      if (known[n]) picks[n] = q; else if (retiredSet[n]) retired++; else unknown++;
    }
    return { picks: picks, unknown: unknown, retired: retired, opts: { schemes: { tesco: m[2][0] === '1', sainsburys: m[2][1] === '1' }, includeDiff: m[2][2] === '1' } };
  }

  // CSV of the visitor's own list only. Row 1 is one notice cell, row 2 the column names. Cells that could be read as formulas are neutralised.
  function csvCell(v) { var s = String(v === undefined || v === null ? '' : v); if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }
  function notice(prices, opts) {
    return 'Prices read by our software, without signing in, ' + dateText(prices.readTo) + ' ' + timeWindow(prices.readFrom, prices.readTo) + '. Basis: ' + basisText(opts) +
      '. Method: https://data.yappman.com/basket/#how-this-works . Aldi, Asda, Sainsbury\'s and Tesco are named only to say where each price was read. Morrisons is named only to say it is not included. We are not affiliated with, endorsed by or supplied by any of them, and we do not have their permission. Questions or corrections: info@yappman.com. Not shopping advice.';
  }
  function basisText(opts) { var s = []; if (opts.schemes && opts.schemes.tesco) s.push('Tesco Clubcard Prices'); if (opts.schemes && opts.schemes.sainsburys) s.push("Sainsbury's Nectar Prices"); return s.length ? 'regular prices, plus ' + s.join(' and ') + ' where shown' : 'regular prices'; }
  function toCsv(list, prices, picks, opts) {
    var rows = [[notice(prices, opts)], ['Item', 'Group', 'Quantity', 'Shop', 'Product', 'Pack', 'Match', 'Price (GBP)', 'Unit price', 'Counted in total', 'Note', 'Shop link']];
    var rd = shortDate(prices.readTo), G = {}; list.groups.forEach(function (g) { G[g.id] = g.name; });
    var LABEL = { s: 'Same product', o: 'Comparable own-label', d: 'Comparable own-label, size differs', v: 'Comparable own-label, value range', u: 'Held while we check the match' };
    indexPicks(list, picks).forEach(function (x) {
      SHOPS.forEach(function (s) {
        var ci = cellInfo(x.item, s, prices, opts, rd), pin = x.item.cells[s];
        rows.push([x.item.name, G[x.item.g], x.qty, NAME[s], pin ? pin.name : '', pin ? pin.pack : '', pin ? LABEL[pin.q] : '', ci.state === 'priced' ? (ci.price / 100).toFixed(2) : '', ci.state === 'priced' ? ci.unit : '',
          ci.state === 'priced' ? (ci.counts ? 'yes' : 'no') : 'no', ci.state === 'priced' ? ci.note.join(' ') : ci.text, pin ? pin.url : '']);
      });
    });
    var r = compute(list, prices, picks, opts, 0);
    SHOPS.forEach(function (s) { rows.push(['Total at ' + NAME[s], '', '', NAME[s], '', '', '', (r.per[s].total / 100).toFixed(2), '', '', r.per[s].priced + ' of ' + r.per[s].of + ' items priced', '']); });
    return rows.map(function (row) { return row.map(csvCell).join(','); }).join('\r\n') + '\r\n';
  }
  function toText(list, prices, picks, opts) {
    var r = compute(list, prices, picks, opts, 0), G = {}; list.groups.forEach(function (g) { G[g.id] = g.name; });
    var out = ['Basket check, ' + dateText(prices.readTo), notice(prices, opts), ''];
    list.groups.forEach(function (g) {
      var rows = r.chosen.filter(function (x) { return x.item.g === g.id; });
      if (!rows.length) return;
      out.push(g.name.toUpperCase());
      rows.forEach(function (x) { out.push('  ' + x.qty + ' x ' + x.item.name); });
    });
    out.push('', 'Totals (' + basisText(opts) + ')');
    SHOPS.forEach(function (s) { out.push('  ' + NAME[s] + ': ' + fmt(r.per[s].total) + ', ' + r.per[s].priced + ' of ' + r.per[s].of + ' items priced'); });
    return out.join('\n') + '\n';
  }

  return { SHOPS: SHOPS, NAME: NAME, SCHEME: SCHEME, MAX_QTY: MAX_QTY, fmt: fmt, dateText: dateText, shortDate: shortDate, timeWindow: timeWindow, unitText: unitText, cellInfo: cellInfo,
    compute: compute, coverage: coverage, encodeShare: encodeShare, decodeShare: decodeShare, toCsv: toCsv, toText: toText, basisText: basisText, notice: notice, csvCell: csvCell };
});

/* ------------------------------ the page ------------------------------ */
(function () {
  'use strict';
  if (typeof document === 'undefined' || !document.getElementById('bk-root')) return;
  var B = this.Basket || window.Basket, S = B.SHOPS, N = B.NAME;
  var data = null, picks = {}, opts = { schemes: { tesco: false, sainsburys: false }, includeDiff: false }, KEY = 'yd-basket-v1';
  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, text, cls) { var e = document.createElement(tag); if (text !== undefined && text !== null) e.textContent = text; if (cls) e.className = cls; return e; };
  var clear = function (e) { while (e.firstChild) e.removeChild(e.firstChild); return e; };
  var remember = function () { return $('bk-remember') && $('bk-remember').checked; };
  function save() { try { if (remember()) localStorage.setItem(KEY, JSON.stringify({ picks: picks, opts: opts })); else localStorage.removeItem(KEY); } catch (e) { /* storage blocked: it still works for this visit */ } }
  function load() { try { var s = JSON.parse(localStorage.getItem(KEY) || 'null'); if (s && s.picks) { picks = s.picks; opts = s.opts || opts; if ($('bk-remember')) $('bk-remember').checked = true; } } catch (e) { /* ignore */ } }

  function renderHeader() {
    var p = data.prices, c = B.coverage(data.list, p), n = data.list.items.length;
    $('bk-head').textContent = 'Pick items from our list of ' + n + ' and see each shop\'s total. Prices were read by our software, without signing in, on ' + B.dateText(p.readTo) + ', ' + B.timeWindow(p.readFrom, p.readTo) + '. Today ' +
      c[4] + ' items are priced at all four shops, ' + c[3] + ' at three and ' + c[2] + ' at two' + (c[1] ? ' (and ' + c[1] + ' at one shop only, which cannot be compared)' : '') + '. This is four shops and ' + n + ' items, not the whole market and not everything a shop sells.';
    if (Date.now() - Date.parse(p.readTo) > 2 * 24 * 3600 * 1000) { $('bk-stale').hidden = false; $('bk-stale').textContent = 'These prices were read on ' + B.shortDate(p.readTo) + ' and may be out of date. The lowest-total mark is not shown.'; }
  }

  function cellNode(item, shop) {
    var ci = B.cellInfo(item, shop, data.prices, opts, B.shortDate(data.prices.readTo)), td = el('td', null, 'bk-cell'), pin = item.cells[shop];
    if (ci.state === 'priced') {
      td.appendChild(el('strong', B.fmt(ci.price)));
      if (ci.unit) td.appendChild(el('span', ' ' + ci.unit, 'meta'));
    } else td.appendChild(el('span', ci.text, 'meta'));
    if (pin) {
      var a = el('a', pin.name + (pin.pack ? ', ' + pin.pack : '')); a.href = pin.url; a.rel = 'noopener nofollow'; a.target = '_blank';
      var d = el('div', null, 'meta'); d.appendChild(a); td.appendChild(d);
      var LAB = { s: 'Same product', o: 'Comparable own-label', d: 'Comparable own-label, size differs', v: 'Comparable own-label, value range', u: 'Match being checked' };
      td.appendChild(el('div', LAB[pin.q], 'bk-label bk-' + pin.q));
    }
    if (ci.state === 'priced') ci.note.forEach(function (t) { td.appendChild(el('div', t, 'meta')); });
    return td;
  }

  function renderList() {
    var box = clear($('bk-list')), q = ($('bk-search').value || '').toLowerCase().trim(), shown = 0;
    data.list.groups.forEach(function (g) {
      var items = data.list.items.filter(function (it) {
        if (it.g !== g.id) return false;
        if (!q) return true;
        return (it.name + ' ' + g.name + ' ' + S.map(function (s) { return it.cells[s] ? it.cells[s].name : ''; }).join(' ')).toLowerCase().indexOf(q) >= 0;
      });
      if (!items.length) return;
      shown += items.length;
      box.appendChild(el('h3', g.name + ' (' + items.length + ')'));
      var wrap = el('div', null, 'table-wrap'), tb = el('table'), head = el('tr');
      head.appendChild(el('th', 'Item')); head.appendChild(el('th', 'How many'));
      S.forEach(function (s) { head.appendChild(el('th', N[s])); });
      var th = el('thead'); th.appendChild(head); tb.appendChild(th);
      var body = el('tbody');
      items.forEach(function (it) {
        var tr = el('tr'), first = el('td'); first.appendChild(el('strong', it.name));
        tr.appendChild(first);
        var qd = el('td'), inp = el('input'); inp.type = 'number'; inp.min = 0; inp.max = B.MAX_QTY; inp.step = 1; inp.value = picks[it.n] || 0; inp.setAttribute('aria-label', 'How many: ' + it.name);
        inp.addEventListener('input', function () { var v = Math.max(0, Math.min(B.MAX_QTY, parseInt(inp.value, 10) || 0)); if (v) picks[it.n] = v; else delete picks[it.n]; save(); renderResult(); });
        qd.appendChild(inp); tr.appendChild(qd);
        S.forEach(function (s) { tr.appendChild(cellNode(it, s)); });
        body.appendChild(tr);
      });
      tb.appendChild(body); wrap.appendChild(tb); box.appendChild(wrap);
    });
    if (!shown) box.appendChild(el('p', 'No item matches that search.'));
  }

  function renderResult() {
    var r = B.compute(data.list, data.prices, picks, opts, Date.now()), box = clear($('bk-result'));
    if (!r.chosen.length) { box.appendChild(el('p', 'Pick items below to see each shop\'s total.')); return; }
    var date = B.shortDate(data.prices.readTo), basis = B.basisText(opts);
    if (!r.stale && r.mark.kind === 'lowest') box.appendChild(el('p', 'Lowest total for your list among the ' + r.mark.count + ' shops that priced every item you picked' + (r.mark.shops.length > 1 ? ' (tie: ' + r.mark.shops.map(function (s) { return N[s]; }).join(' and ') + ')' : ': ' + N[r.mark.shops[0]]) + '. Prices read ' + date + '. Basis: ' + basis + '. Your list: ' + r.split.s + ' same product, ' + r.split.o + ' comparable own-label. ', 'bk-mark'));
    else if (!r.stale && r.mark.kind === 'only') box.appendChild(el('p', 'Only ' + N[r.mark.shops[0]] + ' priced everything you picked, so there is no lowest total to show.', 'bk-mark'));
    else if (!r.stale && r.mark.kind === 'nobody') box.appendChild(el('p', 'No shop priced everything you picked. Totals below cover different numbers of items and cannot be compared.', 'bk-mark'));
    else if (r.stale) box.appendChild(el('p', 'The lowest-total mark is not shown because these prices are more than two days old.', 'bk-mark'));
    if (!r.stale && r.mark.kind === 'lowest') { var a = el('a', 'How items are matched.'); a.href = '#matching'; box.lastChild.appendChild(a); }
    var tb = el('table'), th = el('tr');
    ['Shop', 'Total', 'Items priced', 'Not priced'].forEach(function (h) { th.appendChild(el('th', h)); }); tb.appendChild(th);
    S.forEach(function (s) {
      var p = r.per[s], tr = el('tr');
      tr.appendChild(el('td', N[s])); tr.appendChild(el('td', B.fmt(p.total)));
      tr.appendChild(el('td', p.priced + ' of ' + p.of));
      tr.appendChild(el('td', p.missing.length ? p.missing.map(function (m) { return m.item.name; }).join('; ') : 'none'));
      tb.appendChild(tr);
    });
    var wrap = el('div', null, 'table-wrap'); wrap.appendChild(tb); box.appendChild(wrap);
    if (r.common.length && r.common.length !== r.chosen.length) {
      box.appendChild(el('p', 'Over the ' + r.common.length + ' items all four shops priced on ' + date + ', ' + basis + ': ' + S.map(function (s) { return N[s] + ' ' + B.fmt(r.commonTotals[s]); }).join(', ') + '.'));
    }
    if (!(opts.schemes.tesco || opts.schemes.sainsburys) && (r.memberNotUsed.tesco || r.memberNotUsed.sainsburys)) {
      box.appendChild(el('p', r.memberNotUsed.tesco + ' of your items showed a lower Clubcard Price and ' + r.memberNotUsed.sainsburys + ' a lower Nectar Price. They are not in these totals.', 'meta'));
    }
  }

  function renderTools() {
    var t = clear($('bk-tools'));
    var btn = function (label, fn) { var b = el('button', label); b.type = 'button'; b.className = 'btn btn-ghost'; b.addEventListener('click', fn); t.appendChild(b); return b; };
    var msg = el('span', '', 'meta'); msg.setAttribute('role', 'status');
    btn('Copy my list', function () { var s = B.toText(data.list, data.prices, picks, opts); (navigator.clipboard ? navigator.clipboard.writeText(s) : Promise.reject()).then(function () { msg.textContent = ' Copied.'; }, function () { msg.textContent = ' Could not copy: select the text in the print view instead.'; }); });
    btn('Print my list', function () { window.print(); });
    btn('Download CSV', function () {
      var blob = new Blob(['﻿' + B.toCsv(data.list, data.prices, picks, opts)], { type: 'text/csv;charset=utf-8' }), a = el('a'); a.href = URL.createObjectURL(blob); a.download = 'basket-check-' + data.prices.readTo.slice(0, 10) + '.csv'; document.body.appendChild(a); a.click(); document.body.removeChild(a);
    });
    btn('Copy link to my list', function () { var u = location.origin + location.pathname + B.encodeShare(picks, opts); (navigator.clipboard ? navigator.clipboard.writeText(u) : Promise.reject()).then(function () { msg.textContent = ' Link copied. Anyone with the link sees your list.'; }, function () { msg.textContent = ' Could not copy the link.'; }); });
    btn('Clear my list', function () { picks = {}; save(); renderAll(); });
    t.appendChild(msg);
  }

  function renderOptions() {
    var o = clear($('bk-opts'));
    var chk = function (id, label, checked, fn) { var l = el('label'), i = el('input'); i.type = 'checkbox'; i.id = id; i.checked = checked; i.addEventListener('change', function () { fn(i.checked); save(); renderAll(); }); l.appendChild(i); l.appendChild(document.createTextNode(' ' + label)); o.appendChild(l); o.appendChild(el('br')); };
    o.appendChild(el('p', 'Price basis: Regular prices (as read without signing in and without a loyalty card).'));
    chk('bk-club', 'Include Tesco Clubcard Prices: you need a Clubcard.', opts.schemes.tesco, function (v) { opts.schemes.tesco = v; });
    chk('bk-nectar', "Include Sainsbury's Nectar Prices: you need a Nectar card or the app.", opts.schemes.sainsburys, function (v) { opts.schemes.sainsburys = v; });
    o.appendChild(el('p', 'We hold no member prices for Aldi or Asda. Member prices are counted only where one was shown without signing in. We never sign in. Offers personal to you are not included. Schemes change.', 'meta'));
    chk('bk-diff', 'Include items whose pack size differs or that are a value-range product (shown with a note; left out by default).', opts.includeDiff, function (v) { opts.includeDiff = v; });
    var b = el('button', 'Reset to regular prices'); b.type = 'button'; b.className = 'btn btn-ghost'; b.addEventListener('click', function () { opts = { schemes: { tesco: false, sainsburys: false }, includeDiff: false }; save(); renderAll(); }); o.appendChild(b);
  }

  function renderAll() { renderHeader(); renderOptions(); renderTools(); renderList(); renderResult(); }

  function start(list, prices) {
    data = { list: list, prices: prices };
    load();
    var shared = B.decodeShare(location.hash, list);
    if (shared) { picks = shared.picks; opts = shared.opts; var n = shared.unknown + shared.retired; if (n) { var w = $('bk-share-note'); w.hidden = false; w.textContent = n + ' item' + (n > 1 ? 's' : '') + ' in this link ' + (n > 1 ? 'are' : 'is') + ' no longer in our list and ' + (n > 1 ? 'were' : 'was') + ' left out.'; } }
    $('bk-search').addEventListener('input', renderList);
    if ($('bk-remember')) $('bk-remember').addEventListener('change', save);
    renderAll();
    $('bk-status').textContent = '';
  }
  function fail() { $('bk-status').textContent = 'The prices could not be loaded just now. Please try again later.'; }
  var get = function (u) { return fetch(u, { credentials: 'omit', cache: 'no-cache' }).then(function (r) { return r.ok ? r.json() : Promise.reject(); }); };
  Promise.all([get('/data/basket-pilot-list.json'), get('/data/basket-pilot.json')]).then(function (a) { start(a[0], a[1]); }).catch(fail);
}).call(typeof window !== 'undefined' ? window : this);
