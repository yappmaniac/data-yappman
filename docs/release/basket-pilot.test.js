// Tests for the basket check: docs/release/build-basket-pilot.js, build-basket-page.js and assets/basket.js.   node --test docs/release/basket-pilot.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const B = require("../../assets/basket.js");
const pilot = require("./build-basket-pilot.js");
const pageBuilder = require("./build-basket-page.js");

const ROOT = path.join(__dirname, "..", "..");
const TPL = '<!DOCTYPE html>\n<html>\n<head>\n<title>x</title>\n<meta name="description" content="x">\n<meta property="og:title" content="x">\n<meta property="og:description" content="x">\n<meta property="og:url" content="x">\n<link rel="canonical" href="x">\n<link rel="stylesheet" href="/assets/site.css">\n</head>\n<body>\n<a class="nav-top active" aria-current="true">Trust</a>\n<main id="main" tabindex="-1">\nold\n</main>\n<footer>f</footer>\n</body>\n</html>\n';

// a small list: item 0 priced at all four shops, item 1 at three (not Aldi), item 2 with a size-differs cell, item 3 unconfirmed at Tesco
const cell = (id, name, q, extra = {}) => ({ id, name, pack: "1kg", url: "https://example.com/" + id, q, sz: 1000, su: "g", ...extra });
const LIST = {
  schema: 1, version: "t1", checkedOn: "2026-11-17", retired: [9],
  groups: [{ id: "g1", name: "Group one" }, { id: "g2", name: "Group two" }],
  shops: ["aldi", "asda", "sainsburys", "tesco"],
  items: [
    { n: 0, id: "a", g: "g1", name: "Item A, 1 kg", kind: "o", cells: { aldi: cell("a1", "Aldi A", "o"), asda: cell("a2", "Asda A", "o"), sainsburys: cell("a3", "Sains A", "o"), tesco: cell("a4", "Tesco A", "o") } },
    { n: 1, id: "b", g: "g1", name: "Item B, 1 kg", kind: "s", cells: { asda: cell("b2", "Brand B", "s"), sainsburys: cell("b3", "Brand B", "s"), tesco: cell("b4", "Brand B", "s") } },
    { n: 2, id: "c", g: "g2", name: "Item C, 1 kg", kind: "o", cells: { aldi: cell("c1", "Aldi C", "d", { d: 14 }), asda: cell("c2", "Asda C", "o"), sainsburys: cell("c3", "Sains C", "v"), tesco: cell("c4", "Tesco C", "o") } },
    { n: 3, id: "d", g: "g2", name: "Item D, 1 kg", kind: "o", cells: { aldi: cell("d1", "Aldi D", "o"), asda: cell("d2", "Asda D", "o"), tesco: cell("d4", "Tesco D", "u") } },
  ],
};
const row = (retailer, id, name, price, extra = {}) => ({ retailer, retailerProductId: id, name, price, loyaltyPrice: null, wasPrice: null, promotionText: null, inStock: true, scrapedAt: "2026-11-17T08:10:36Z", ...extra });
function fullRows() {
  const rows = [];
  for (const it of LIST.items) for (const [shop, c] of Object.entries(it.cells)) rows.push(row(shop, c.id, c.name, 2 + it.n + { aldi: -1, asda: 0, sainsburys: 0.1, tesco: 0.2 }[shop]));
  return rows;
}
function site(list = LIST, prices = null) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bk-"));
  fs.mkdirSync(path.join(root, "data")); fs.mkdirSync(path.join(root, "notices/w41-skipped"), { recursive: true });
  fs.writeFileSync(path.join(root, "notices/w41-skipped/index.html"), TPL);
  fs.writeFileSync(path.join(root, pilot.LIST), JSON.stringify(list));
  if (prices) fs.writeFileSync(path.join(root, pilot.OUT), pilot.dump(prices));
  return root;
}
const prices = (rows = fullRows(), previous = null) => pilot.build(site(), rows, previous);
const NOW = Date.parse("2026-11-17T09:00:00Z");

// ---- the daily builder -------------------------------------------------------------------------------------------------------------

test("a full read gives a price for every cell, in pence, with the read window", () => {
  const p = prices();
  assert.strictEqual(p.readFrom, "2026-11-17T08:10Z"); assert.strictEqual(p.readTo, "2026-11-17T08:10Z"); assert.strictEqual(p.listVersion, "t1");
  assert.deepStrictEqual(p.cells[0].aldi, { p: 100, o: 1 }); assert.deepStrictEqual(p.cells[0].tesco, { p: 220, o: 1 });
  assert.strictEqual(Object.values(p.cells).reduce((n, o) => n + Object.keys(o).length, 0), 14);
});

test("an unconfirmed cell is held, a missing row is 'not read', a changed product name is held, a null price is 'no price': never guessed", () => {
  const rows = fullRows().filter(r => !(r.retailer === "asda" && r.retailerProductId === "b2"));
  rows.find(r => r.retailerProductId === "a3").name = "Something else entirely";
  rows.find(r => r.retailerProductId === "a1").price = null;
  const p = prices(rows);
  assert.strictEqual(p.cells[3].tesco.s, "h");      // unconfirmed pin
  assert.strictEqual(p.cells[1].asda.s, "x");       // no row
  assert.strictEqual(p.cells[0].sainsburys.s, "h"); // name changed since the pin
  assert.strictEqual(p.cells[0].aldi.s, "n");       // the page showed no price
});

test("member prices are kept only at the two shops with a scheme and only when below the regular price", () => {
  const rows = fullRows();
  rows.find(r => r.retailerProductId === "a4").loyaltyPrice = 1.5;     // Tesco, below 2.00
  rows.find(r => r.retailerProductId === "a3").loyaltyPrice = 5;       // Sainsbury's, above: ignored
  rows.find(r => r.retailerProductId === "a2").loyaltyPrice = 0.5;     // Asda has no scheme: ignored
  const p = prices(rows);
  assert.strictEqual(p.cells[0].tesco.m, 150); assert.strictEqual(p.cells[0].sainsburys.m, undefined); assert.strictEqual(p.cells[0].asda.m, undefined);
});

test("the builder fails closed and writes nothing on a bad read", () => {
  const bad = (rows, re, prev) => assert.throws(() => prices(rows, prev), re);
  bad([], /empty/); bad("x", /not a list/);
  bad(Array.from({ length: 341 }, () => fullRows()[0]), /over the cap of 340/);
  bad([...fullRows(), row("tesco", "zzz", "x", 0)], /outside 0 to 1000/);
  bad([...fullRows(), row("tesco", "zzz", "x", 5000)], /outside 0 to 1000/);
  bad([...fullRows(), { retailer: "lidl", retailerProductId: "1", price: 1, scrapedAt: "2026-11-17T08:10:36Z" }], /no valid retailer/);
  bad(fullRows().map(r => ({ ...r, scrapedAt: "2026-11-17T23:50:00Z" })).concat(fullRows().slice(0, 1).map(r => ({ ...r, scrapedAt: "2026-11-18T00:10:00Z" }))), /runs across two UTC days/);
  bad([{ ...fullRows()[0], scrapedAt: "garbage" }], /no valid scrapedAt/);
  bad(fullRows().filter(r => r.retailer === "aldi" || r.retailer === "asda"), /only 2 shops have rows/);
  bad([...fullRows(), ...Array.from({ length: 4 }, (_, i) => row("tesco", "u" + i, "unknown", 1))], /not in the pinned list/);
  bad(fullRows(), /older than the current file/, { readTo: "2026-11-18T08:10Z" });
});

test("a capped read that also holds the tail of the day before uses only the newest run", () => {
  const older = fullRows().slice(0, 5).map(r => ({ ...r, price: 9.99, scrapedAt: "2026-11-16T08:10:36Z" }));
  const p = prices([...fullRows(), ...older]);
  assert.strictEqual(p.ignoredOlder, 5); assert.strictEqual(p.rowsRead, 14); assert.strictEqual(p.cells[0].aldi.p, 100);
});

test("re-running the same read is allowed (equal is not older)", () => {
  const first = prices();
  assert.deepStrictEqual(prices(fullRows(), first), first);
});

test("a repeated row for a product counts once: the latest read wins", () => {
  const rows = fullRows(); rows.push({ ...rows[0], price: 9, scrapedAt: "2026-11-17T08:30:00Z" });
  assert.strictEqual(prices(rows).cells[0].aldi.p, 900);
});

test("--check passes on a built file and finds a tampered or stale one", () => {
  const root = site(LIST, prices());
  assert.deepStrictEqual(pilot.check(root), []);
  const f = path.join(root, pilot.OUT), d = JSON.parse(fs.readFileSync(f, "utf8"));
  d.cells[0].tesco.m = 999; fs.writeFileSync(f, pilot.dump(d));
  assert.match(pilot.check(root).join("\n"), /member price is not below the regular price/);
  d.cells[0].tesco = {}; fs.writeFileSync(f, pilot.dump(d));
  assert.match(pilot.check(root).join("\n"), /neither a status nor a price/);
  d.listVersion = "old"; fs.writeFileSync(f, pilot.dump(d));
  assert.match(pilot.check(root).join("\n"), /was built for list old/);
});

test("the committed list and prices agree (when present)", () => {
  if (!fs.existsSync(path.join(ROOT, pilot.OUT))) return;
  assert.deepStrictEqual(pilot.check(ROOT), []);
});

test("the command line writes atomically, refuses an older read and leaves the file alone", () => {
  const root = site(), rows = path.join(root, "rows.json");
  fs.writeFileSync(rows, JSON.stringify(fullRows()));
  const script = path.join(__dirname, "build-basket-pilot.js");
  assert.match(cp.execFileSync("node", [script, "--run", rows, "--root", root], { encoding: "utf8" }), /wrote data\/basket-pilot\.json: 14 cells/);
  const before = fs.readFileSync(path.join(root, pilot.OUT), "utf8");
  fs.writeFileSync(rows, JSON.stringify(fullRows().map(r => ({ ...r, scrapedAt: "2026-11-16T08:10:36Z" }))));
  const r = cp.spawnSync("node", [script, "--run", rows, "--root", root], { encoding: "utf8" });
  assert.strictEqual(r.status, 1); assert.match(r.stderr, /NOTHING WRITTEN\. the read .* is older/);
  assert.strictEqual(fs.readFileSync(path.join(root, pilot.OUT), "utf8"), before);
});

// ---- the page builder ---------------------------------------------------------------------------------------------------------------

test("the page is built from the template, names the four shops alphabetically, holds no prices and has the approved fixed lines", () => {
  const p = pageBuilder.build(site()).get(pageBuilder.OUT);
  assert.ok(p.includes("<title>Basket check: everyday items at Aldi, Asda, Sainsbury&#39;s and Tesco — Yappman Data</title>") || p.includes("<title>Basket check: everyday items at Aldi, Asda, Sainsbury's and Tesco — Yappman Data</title>"));
  assert.match(p, /Morrisons is not in this comparison\./);
  assert.match(p, /Aldi, Asda, Sainsbury&rsquo;s and Tesco are named only to say where each price was read\. Morrisons is named only to say it is not included\. We are not affiliated with, endorsed by or supplied by any of them, and we do not have their permission\./);
  assert.match(p, /A person checked every match on 17 November 2026\./);
  assert.match(p, /write to <a href="mailto:info@yappman\.com">info@yappman\.com<\/a>; we normally reply within one working day\. If a shop asks us in writing to stop, we stop collecting and showing its prices the day we read the message\./);
  assert.match(p, /<link rel="stylesheet" href="\/assets\/basket\.css">/); assert.match(p, /<script src="\/assets\/basket\.js" defer><\/script>/);
  assert.doesNotMatch(p, /£\d|&pound;\d/); assert.doesNotMatch(p, /nav-top active/);
  assert.match(p, /like-for-like check of 4 everyday items/);
});

test("an offer shown by the shop is flagged (multibuy text or a was-price), never applied, and the note says so", () => {
  const rows = fullRows();
  rows.find(r => r.retailerProductId === "a4").promotionText = "Any 2 for £4";
  rows.find(r => r.retailerProductId === "a2").wasPrice = 3;
  rows.find(r => r.retailerProductId === "a3").promotionText = "   ";           // blank text is no offer
  const p = prices(rows);
  assert.strictEqual(p.cells[0].tesco.f, 1); assert.strictEqual(p.cells[0].asda.f, 1); assert.strictEqual(p.cells[0].sainsburys.f, undefined);
  assert.strictEqual(p.cells[0].tesco.p, 220);                                  // the price is still the one-item price
  const ci = B.cellInfo(LIST.items[0], "tesco", p, opts(), "17 Nov 2026");
  assert.match(ci.note.join(" "), /An offer is listed for this item\. The price is for one item; multibuy and card terms are not applied\./);
  assert.strictEqual(ci.price, 220);
  assert.strictEqual(B.cellInfo(LIST.items[0], "sainsburys", p, opts(), "x").note.length, 0);
});

test("the Prices text says what the price is, that a price cut is included, that card and multibuy are not used, and states the Aldi limit", () => {
  const p = pageBuilder.build(site()).get(pageBuilder.OUT);
  assert.match(p, /Each price is for one item without a loyalty card, as read without signing in\. A temporary price cut is already included\. Multi-buy offers, vouchers and personal offers are never applied\. Loyalty-card prices are left out unless you switch them on on this page\. An Aldi price may be a cut that is not marked\./);
  assert.doesNotMatch(p, /product information|the shop shows|shop&rsquo;s own product/i);
  assert.doesNotMatch(p, /Tesco and Sainsbury&rsquo;s: prices are read|Prices are read once a day/);  // held back until confirmed (list.statements)
  assert.doesNotMatch(p.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<footer[\s\S]*<\/footer>/, ""), /product page|read this page|shows everyone|shown to everyone|the website set|from each shop's website/i);
});

test("the page text, script and styles contain none of the banned words", () => {
  const html = pageBuilder.build(site()).get(pageBuilder.OUT).replace(/<script[\s\S]*?<\/script>/g, " ").replace(/<footer[\s\S]*<\/footer>/, " ").replace(/<[^>]*>/g, " ");
  const jsSrc = fs.readFileSync(path.join(ROOT, "assets/basket.js"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const js = [...jsSrc.matchAll(/'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"/g)].map(m => m[1] || m[2] || "").filter(t => /\s/.test(t.trim()) && t.length > 8).join("\n");   // the sentences a visitor can read
  const css = fs.readFileSync(path.join(ROOT, "assets/basket.css"), "utf8");
  for (const [what, text] of [["page", html], ["script strings", js]]) for (const re of pageBuilder.BANNED) assert.doesNotMatch(text, re, `${what} contains ${re}`);
  assert.doesNotMatch(css, /@import|url\(/);
});

test("the builder refuses text with a banned word, and --check finds a stale page", () => {
  const root = site();
  pageBuilder.write(root, pageBuilder.build(root));
  assert.deepStrictEqual(pageBuilder.check(root), []);
  fs.appendFileSync(path.join(root, pageBuilder.OUT), "x");
  assert.match(pageBuilder.check(root)[0], /is not what the list gives/);
  const l2 = JSON.parse(JSON.stringify(LIST)); l2.checkedOn = "17 November";
  assert.throws(() => pageBuilder.build(site(l2)), /bad date/);
});

// ---- the page logic (assets/basket.js) -----------------------------------------------------------------------------------------------

const opts = (o = {}) => ({ schemes: {}, includeDiff: false, ...o });
const calc = (picks, o = opts(), p = prices(), now = NOW) => B.compute(LIST, p, picks, o, now);

test("the lowest-total mark goes to the lowest total among the shops that priced EVERY picked item, ties shown as ties", () => {
  const r = calc({ 0: 1, 1: 1 });                       // Aldi has no item B: not eligible
  assert.strictEqual(r.mark.kind, "lowest"); assert.deepStrictEqual(r.mark.shops, ["asda"]); assert.strictEqual(r.mark.count, 3);
  assert.strictEqual(r.per.aldi.complete, false); assert.strictEqual(r.per.aldi.priced, 1);
  const tie = prices(fullRows().map(r => (r.retailer === "sainsburys" ? { ...r, price: 3 } : r.retailer === "asda" ? { ...r, price: 3 } : r)));
  assert.deepStrictEqual(calc({ 1: 1 }, opts(), tie).mark.shops.slice().sort(), ["asda", "sainsburys"]);
});

test("only one shop pricing everything gives no 'lowest'; none gives the 'cannot be compared' line", () => {
  const r = calc({ 1: 1, 3: 1 });                                             // B: Asda, Sainsbury's, Tesco. D: Aldi and Asda only (Tesco held, Sainsbury's has no cell)
  assert.strictEqual(r.mark.kind, "only"); assert.deepStrictEqual(r.mark.shops, ["asda"]);
  assert.strictEqual(calc({ 3: 1 }).mark.kind, "lowest");                     // item D alone: Aldi and Asda both price it
  const noAsdaD = prices(fullRows().filter(x => x.retailerProductId !== "d2"));
  assert.strictEqual(calc({ 1: 1, 3: 1 }, opts(), noAsdaD).mark.kind, "nobody");
});

test("an item no shop prices at all leaves every shop incomplete", () => {
  const p = prices(fullRows().filter(r => r.retailerProductId !== "b2" && r.retailerProductId !== "b3" && r.retailerProductId !== "b4"));
  assert.strictEqual(calc({ 1: 1 }, opts(), p).mark.kind, "nobody");
});

test("the mark is not shown on prices older than two days; totals are still computed", () => {
  const r = calc({ 0: 1 }, opts(), prices(), Date.parse("2026-11-20T09:00:00Z"));
  assert.strictEqual(r.stale, true); assert.ok(r.per.aldi.total > 0);
  assert.strictEqual(calc({ 0: 1 }, opts(), prices(), Date.parse("2026-11-19T07:00:00Z")).stale, false);
});

test("a size-differs or value-range cell is shown with a note but left out of totals unless the visitor includes different sizes", () => {
  const off = calc({ 2: 1 }), on = calc({ 2: 1 }, opts({ includeDiff: true }));
  assert.strictEqual(off.per.aldi.priced, 0); assert.strictEqual(off.per.sainsburys.priced, 0); assert.strictEqual(off.per.asda.priced, 1);
  assert.strictEqual(on.per.aldi.priced, 1); assert.strictEqual(on.per.sainsburys.priced, 1);
  const ci = B.cellInfo(LIST.items[2], "aldi", prices(), opts(), "17 Nov 2026");
  assert.strictEqual(ci.state, "priced"); assert.strictEqual(ci.counts, false); assert.match(ci.note.join(" "), /Pack size differs \(1kg here; the item is Item C, 1 kg\); left out of totals unless you include different sizes\./);
  assert.match(B.cellInfo(LIST.items[2], "sainsburys", prices(), opts(), "d").note.join(" "), /Value-range product/);
});

test("a missing cell always says why, in the fixed words, never blank or zero", () => {
  const rows = fullRows().filter(r => r.retailerProductId !== "a2"); rows.find(r => r.retailerProductId === "a1").price = null;
  const p = prices(rows), rd = "17 Nov 2026";
  assert.strictEqual(B.cellInfo(LIST.items[1], "aldi", p, opts(), rd).text, "No matching product at this shop.");
  assert.strictEqual(B.cellInfo(LIST.items[0], "asda", p, opts(), rd).text, "We could not read a price for this product on 17 Nov 2026.");
  assert.strictEqual(B.cellInfo(LIST.items[0], "aldi", p, opts(), rd).text, "No price was shown for this product on 17 Nov 2026.");
  assert.strictEqual(B.cellInfo(LIST.items[3], "tesco", p, opts(), rd).text, "Held while we check the match.");
});

test("member prices count only when the scheme is ticked, are labelled in the cell, and fall back to the regular price with a marker", () => {
  const rows = fullRows(); rows.find(r => r.retailerProductId === "a4").loyaltyPrice = 1.5;
  const p = prices(rows), rd = "17 Nov 2026";
  const off = B.cellInfo(LIST.items[0], "tesco", p, opts(), rd), on = B.cellInfo(LIST.items[0], "tesco", p, opts({ schemes: { tesco: true } }), rd);
  assert.strictEqual(off.price, 220); assert.strictEqual(on.price, 150);
  assert.match(on.note.join(" "), /Clubcard Price £1\.50; regular £2\.20\./);
  assert.match(B.cellInfo(LIST.items[1], "tesco", p, opts({ schemes: { tesco: true } }), rd).note.join(" "), /regular price \(no member price shown\)/);
  assert.strictEqual(B.cellInfo(LIST.items[0], "asda", p, opts({ schemes: { asda: true } }), rd).note.length, 0);   // Asda has no scheme in the data
  assert.strictEqual(calc({ 0: 1 }, opts(), p).memberNotUsed.tesco, 1);                                           // "N of your items showed a lower Clubcard Price"
  assert.strictEqual(calc({ 0: 1 }, opts({ schemes: { tesco: true } }), p).memberNotUsed.tesco, 0);
});

test("the second line totals the items every shop priced; the split counts same product and comparable own-label", () => {
  const r = calc({ 0: 1, 1: 2, 3: 1 });
  assert.strictEqual(r.common.length, 1); assert.strictEqual(r.commonTotals.aldi, 100);
  assert.deepStrictEqual(r.split, { s: 1, o: 2 });
});

test("how many items are priced at four, three, two and one shops uses only cells that count", () => {
  const c = B.coverage(LIST, prices());
  assert.strictEqual(c[4], 1);            // item A
  assert.strictEqual(c[3], 1);            // item B
  assert.strictEqual(c[2], 2);            // item D (Aldi, Asda) and item C (Asda, Tesco: the size-differs and value-range cells do not count)
});

test("unit prices are worked out from price and pack size, per kg, per litre or each, and omitted when no size is known", () => {
  assert.strictEqual(B.unitText({ sz: 500, su: "g" }, 150), "£3.00 per kg");
  assert.strictEqual(B.unitText({ sz: 2000, su: "ml" }, 265), "£1.33 per litre");
  assert.strictEqual(B.unitText({ sz: 12, su: "ea" }, 300), "£0.25 each");
  assert.strictEqual(B.unitText({}, 300), "");
});

test("the share link round-trips, is 3 characters per item, ignores unknown ids, says retired ones are gone and rejects junk", () => {
  const picks = { 0: 1, 1: 20, 3: 7 }, o = opts({ schemes: { tesco: true, sainsburys: false }, includeDiff: true });
  const h = B.encodeShare(picks, o);
  assert.strictEqual(h.length, "#v1.".length + 9 + "~101".length);
  const d = B.decodeShare(h, LIST);
  assert.deepStrictEqual(d.picks, picks); assert.deepStrictEqual(d.opts, { schemes: { tesco: true, sainsburys: false }, includeDiff: true });
  const withUnknown = B.decodeShare("#v1.0010zz1~000".slice(0, 0) + "#v1." + "001" + "0z1" + "091~000", LIST);
  assert.deepStrictEqual(withUnknown.picks, { 0: 1 }); assert.strictEqual(withUnknown.unknown, 1); assert.strictEqual(withUnknown.retired, 1);
  for (const bad of ["", "#", "#v2.001~000", "#v1.00~000", "#v1.001~00", "#v1.001~002", "#v1.0021~000".slice(0, 12) + "x"]) assert.strictEqual(B.decodeShare(bad, LIST), null, bad);
  assert.ok(B.encodeShare(Object.fromEntries(Array.from({ length: 100 }, (_, i) => [i, 3])), opts()).length < 320);   // 100 items
});

test("the CSV has the notice row, the column row, only the visitor's items, and neutralises formula-like cells", () => {
  const l2 = JSON.parse(JSON.stringify(LIST)); l2.items[0].cells.aldi.name = '=HYPERLINK("x")';
  const csv = B.toCsv(l2, prices(), { 0: 2 }, opts());
  const lines = csv.split("\r\n");
  assert.match(lines[0], /^"Prices read by our software, without signing in, Tuesday 17 November 2026 at 08:10 UTC\. Basis: regular prices\. Method: https:\/\/data\.yappman\.com\/basket\/#how-this-works \. Aldi, Asda, Sainsbury's and Tesco are named only/);
  assert.match(lines[0], /Morrisons is named only to say it is not included\..*info@yappman\.com/);
  assert.match(lines[1], /^Item,Group,Quantity,Shop,Product,Pack,Match,Price \(GBP\),Unit price,Counted in total,Note,Shop link$/);
  assert.ok(lines.some(l => l.includes("'=HYPERLINK(")));
  assert.ok(!csv.includes("Item B")); assert.match(csv, /Total at Aldi/);
  assert.strictEqual(B.csvCell("a,b"), '"a,b"'); assert.strictEqual(B.csvCell('say "x"'), '"say ""x"""');
});

test("the copied list has the date, the basis, the notice and the totals, grouped by our groups", () => {
  const t = B.toText(LIST, prices(), { 0: 1, 2: 3 }, opts({ schemes: { tesco: true } }));
  assert.match(t, /Basket check, Tuesday 17 November 2026/); assert.match(t, /GROUP ONE\n {2}1 x Item A, 1 kg/); assert.match(t, /GROUP TWO\n {2}3 x Item C, 1 kg/);
  assert.match(t, /Tesco Clubcard Prices where shown/); assert.match(t, /Aldi: £/);
});

test("the script sends nothing: no cookie, no beacon, no network beyond the two same-site files, one storage key, no new scripts", () => {
  const src = fs.readFileSync(path.join(ROOT, "assets/basket.js"), "utf8");
  assert.doesNotMatch(src, /document\.cookie|sendBeacon|XMLHttpRequest|WebSocket|createElement\(['"]script|innerHTML|insertAdjacentHTML|eval\(|new Function|umami|gtag|analytics/i);
  assert.deepStrictEqual([...src.matchAll(/get\('(\/[^']+)'\)/g)].map(m => m[1]).sort(), ["/data/basket-pilot-list.json", "/data/basket-pilot.json"]);
  assert.strictEqual((src.match(/fetch\(/g) || []).length, 1);
  assert.deepStrictEqual([...new Set([...src.matchAll(/localStorage\.\w+\(([A-Za-z']+)/g)].map(m => m[1]))], ["KEY"]);
  assert.match(src, /KEY = 'yd-basket-v1'/);
});

test("the Where sentence appears only when the list file says the store setting is confirmed", () => {
  const off = pageBuilder.build(site()).get(pageBuilder.OUT);
  assert.doesNotMatch(off, /Asda and Aldi: prices are read/);
  const on = pageBuilder.build(site({ ...LIST, statements: { storeSetting: true, dailyRead: false } })).get(pageBuilder.OUT);
  assert.match(on, /Tesco and Sainsbury&rsquo;s: prices are read with no store chosen\. Asda and Aldi: prices are read for one fixed store or service area, so they may differ from the price at your local store\./);
});

// ---- taking one shop off the page (removedShops in the list file; docs/release/basket-remove-shop.js) -------------------------------

const remover = require("./basket-remove-shop.js");
const LISTR = (removed = []) => ({ ...LIST, statements: { storeSetting: true, dailyRead: false }, removedShops: removed });
const textOf = html => html.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<[^>]*>/g, " ");
const siteR = (removed = []) => { const root = site(LISTR(removed), prices()); fs.mkdirSync(path.join(root, "basket"), { recursive: true }); return root; };

test("with no shop removed the page and the script behave exactly as before", () => {
  assert.strictEqual(pageBuilder.build(site(LISTR())).get(pageBuilder.OUT), pageBuilder.build(site({ ...LIST, statements: { storeSetting: true, dailyRead: false } })).get(pageBuilder.OUT));
  assert.deepStrictEqual(B.setRemoved([]), ["aldi", "asda", "sainsburys", "tesco"]);
  assert.deepStrictEqual(B.setRemoved(undefined), ["aldi", "asda", "sainsburys", "tesco"]);
});

test("a removed shop is named nowhere on the page except as not included", () => {
  const p = pageBuilder.build(site(LISTR(["asda"]))).get(pageBuilder.OUT), t = textOf(p);
  assert.match(p, /<title>Basket check: everyday items at Aldi, Sainsbury&#39;s and Tesco|<title>Basket check: everyday items at Aldi, Sainsbury's and Tesco/);
  assert.match(p, /<h1>Basket check: everyday items at Aldi, Sainsbury&rsquo;s and Tesco<\/h1>/);
  assert.match(t, /Aldi, Sainsbury&rsquo;s and Tesco are listed in alphabetical order/);
  assert.match(t, /Asda and Morrisons are not in this comparison\./);
  assert.match(t, /at three shops\./);
  assert.match(t, /Tesco and Sainsbury&rsquo;s: prices are read with no store chosen\. Aldi: prices are read for one fixed store or service area/);
  assert.match(t, /Aldi, Sainsbury&rsquo;s and Tesco are named only to say where each price was read\. Asda and Morrisons are named only to say they are not included\./);
  assert.strictEqual((t.match(/Asda/g) || []).length, 2, "Asda appears only in the two not-included sentences");
  assert.doesNotMatch(p.match(/<meta name="description"[^>]*>/)[0], /Asda/);
});

test("removing a scheme shop drops its scheme name; removing Aldi drops the Aldi-only notes", () => {
  const noTesco = textOf(pageBuilder.build(site(LISTR(["tesco"]))).get(pageBuilder.OUT));
  assert.match(noTesco, /Nectar Prices is the shop&rsquo;s own scheme name\./); assert.doesNotMatch(noTesco, /Clubcard/);
  assert.match(noTesco, /Sainsbury&rsquo;s: prices are read with no store chosen\. Asda and Aldi: prices are read/);
  const noAldi = textOf(pageBuilder.build(site(LISTR(["aldi"]))).get(pageBuilder.OUT));
  assert.doesNotMatch(noAldi, /An Aldi price may be a cut|Aldi stock is not shown/);
  assert.match(noAldi, /Asda: prices are read for one fixed store or service area/);
});

test("the list file is refused if removedShops is not a list of its own shops, or fewer than two shops would stay", () => {
  assert.throws(() => pageBuilder.build(site(LISTR(["lidl"]))), /removedShops must name shops from the list/);
  assert.throws(() => pageBuilder.build(site(LISTR(["asda", "asda"]))), /once each/);
  assert.throws(() => pageBuilder.build(site(LISTR(["aldi", "asda", "tesco"]))), /at least two shops must stay/);
  assert.match(textOf(pageBuilder.build(site(LISTR(["aldi", "asda"]))).get(pageBuilder.OUT)), /at two shops\./);
});

test("the page script leaves a removed shop out of totals, the lowest-total mark, the CSV and the copied text", () => {
  const p = prices(), picks = { 0: 1, 1: 2 }, o = () => ({ schemes: { tesco: false, sainsburys: false }, includeDiff: false });
  try {
    B.setRemoved(["aldi"]);
    assert.deepStrictEqual(B.SHOPS, ["asda", "sainsburys", "tesco"]);
    const r = B.compute(LIST, p, picks, o(), NOW);
    assert.deepStrictEqual(Object.keys(r.per), ["asda", "sainsburys", "tesco"]);
    assert.strictEqual(r.mark.kind, "lowest"); assert.strictEqual(r.mark.count, 3); assert.deepStrictEqual(r.mark.shops, ["asda"]);
    const csv = B.toCsv(LIST, p, picks, o()), txt = B.toText(LIST, p, picks, o());
    assert.doesNotMatch(csv.split("\r\n").slice(1).join("\n"), /Aldi/);                       // no Aldi row or total
    assert.match(csv.split("\r\n")[0], /Asda, Sainsbury's and Tesco are named only to say where each price was read\. Aldi and Morrisons are named only to say they are not included\./);
    assert.doesNotMatch(txt.split("\n").slice(2).join("\n"), /Aldi/);
    const cov = B.coverage(LIST, p);
    assert.strictEqual(cov[4], 0); assert.strictEqual(cov[3] + cov[2] + cov[1], 4);          // counted over the three shops shown
    B.setRemoved(["tesco"]);
    assert.strictEqual(B.compute(LIST, p, picks, o(), NOW).memberNotUsed.tesco, 0);
  } finally { B.setRemoved([]); }
  assert.deepStrictEqual(Object.keys(B.compute(LIST, p, picks, o(), NOW).per), ["aldi", "asda", "sainsburys", "tesco"]);
});

test("the removal script changes the one list entry, clears that shop's prices and rebuilds the page; the checks still pass", () => {
  const root = siteR();
  const listBefore = fs.readFileSync(path.join(root, pilot.LIST), "utf8");
  const r = remover.apply(root, "asda", false);
  assert.deepStrictEqual(r.after, ["asda"]); assert.strictEqual(r.cells, 4); assert.strictEqual(r.changed, true);
  const listAfter = fs.readFileSync(path.join(root, pilot.LIST), "utf8");
  assert.strictEqual(listAfter, listBefore.replace('"removedShops":[]', '"removedShops":["asda"]'));   // one entry, nothing else
  const d = JSON.parse(fs.readFileSync(path.join(root, pilot.OUT), "utf8"));
  for (const c of Object.values(d.cells)) if (c.asda) assert.deepStrictEqual(c.asda, { s: "x" });
  assert.ok(d.cells[0].tesco.p > 0 && d.cells[0].aldi.p > 0);                                   // the other shops are untouched
  assert.deepStrictEqual(pilot.check(root), []); assert.deepStrictEqual(pageBuilder.check(root), []);
  assert.match(fs.readFileSync(path.join(root, pageBuilder.OUT), "utf8"), /everyday items at Aldi, Sainsbury&rsquo;s and Tesco<\/h1>/);
  assert.strictEqual(remover.apply(root, "asda", false).changed, false);                        // a second run changes nothing
  assert.strictEqual(fs.readFileSync(path.join(root, pilot.LIST), "utf8"), listAfter);
});

test("the removal script refuses an unknown shop or a third removal and changes nothing; restore puts the shop back on the page", () => {
  const root = siteR();
  const snap = () => [pilot.LIST, pilot.OUT].map(f => fs.readFileSync(path.join(root, f), "utf8")).join("|");
  const s0 = snap();
  assert.throws(() => remover.apply(root, "lidl", false), /is not one of the shops/); assert.strictEqual(snap(), s0);
  remover.apply(root, "asda", false); remover.apply(root, "aldi", false);
  const s2 = snap();
  assert.throws(() => remover.apply(root, "tesco", false), /at least two shops must stay/); assert.strictEqual(snap(), s2);
  const r = remover.apply(root, "asda", true);
  assert.deepStrictEqual(r.after, ["aldi"]);
  assert.match(fs.readFileSync(path.join(root, pageBuilder.OUT), "utf8"), /everyday items at Asda, Sainsbury&rsquo;s and Tesco<\/h1>/);
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(path.join(root, pilot.OUT), "utf8")).cells[0].asda, { s: "x" });   // prices return with the next daily read
  const noEntry = site(LIST, prices());
  assert.throws(() => remover.apply(noEntry, "asda", false), /expected exactly one "removedShops"/);
});

test("the live list file carries the removedShops entry, empty, exactly once", () => {
  const s = fs.readFileSync(path.join(ROOT, pilot.LIST), "utf8");
  assert.strictEqual((s.match(/"removedShops":\[\]/g) || []).length, 1);
  assert.deepStrictEqual(JSON.parse(s).removedShops, []);
});
