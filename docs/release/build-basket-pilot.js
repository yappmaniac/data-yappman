#!/usr/bin/env node
"use strict";
// Builds data/basket-pilot.json (the daily prices for the basket page) from one capped read of the pilot dataset.
//
//   node docs/release/build-basket-pilot.js --run ROWS.json [--root DIR]    write data/basket-pilot.json (never replaces newer data with older)
//   node docs/release/build-basket-pilot.js --check [--root DIR]            fail unless the committed file is well formed and matches the list
//
// ROWS.json: the array the daily read returns (limit 340; fields retailerProductId, retailer, name, price, loyaltyPrice, wasPrice,
// promotionText, inStock, scrapedAt). The pinned items and products are in data/basket-pilot-list.json (changed only by a person).
// Fails closed (writes nothing) if: the read is over the cap, a row is malformed, a price is outside 0 to 1000, the rows span more than
// one UTC day or 3 hours, more than 5% of rows are not in the list, or fewer than 3 of the 4 shops have any row.
// A cell with no row, or a row for a product whose name no longer matches the pinned one, is NOT guessed: it gets a status
// (x: not read, h: held while the match is checked, n: no price shown). No network, no clock.
const fs = require("fs");
const path = require("path");

const LIST = "data/basket-pilot-list.json";
const OUT = "data/basket-pilot.json";
const CAP = 340;
const SHOPS = ["aldi", "asda", "sainsburys", "tesco"];
const MEMBER_SHOPS = new Set(["sainsburys", "tesco"]);
const norm = s => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const readJson = (root, f) => { try { return JSON.parse(fs.readFileSync(path.join(root, f), "utf8")); } catch (e) { throw new Error(`${f}: cannot be read as JSON (${e.code || e.message})`); } };
const pence = v => Math.round(v * 100);

function loadList(root) {
  const l = readJson(root, LIST);
  if (l.schema !== 1 || !Array.isArray(l.items) || !l.items.length) throw new Error(`${LIST}: not the expected shape`);
  const ns = new Set();
  for (const it of l.items) {
    if (!Number.isInteger(it.n) || ns.has(it.n)) throw new Error(`${LIST}: item numbers must be unique integers (${it.id})`);
    ns.add(it.n);
    for (const [shop, c] of Object.entries(it.cells)) if (!SHOPS.includes(shop) || !c.id || !c.name || !/^[soduv]$/.test(c.q)) throw new Error(`${LIST}: bad cell ${it.id}/${shop}`);
  }
  return l;
}

function build(root, rows, previous) {
  const list = loadList(root);
  if (!Array.isArray(rows)) throw new Error("the read is not a list");
  if (rows.length === 0) throw new Error("the read is empty");
  if (rows.length > CAP) throw new Error(`the read has ${rows.length} rows, over the cap of ${CAP}`);
  // A capped read of the newest rows can also hold the tail of the day before (the run writes fewer rows than the cap): keep only the
  // newest run, meaning rows read within 3 hours of the newest row. Every row must still have a valid time.
  const times = rows.map(r => (r && typeof r === "object" ? Date.parse(r.scrapedAt) : NaN));
  if (times.some(t => !isFinite(t))) throw new Error("a row has no valid scrapedAt");
  const newest = Math.max(...times);
  const ignoredOlder = rows.filter((r, i) => newest - times[i] > 3 * 3600 * 1000).length;
  rows = rows.filter((r, i) => newest - times[i] <= 3 * 3600 * 1000);
  const want = new Map();                                        // shop|id -> {item, shop, cell}
  for (const it of list.items) for (const [shop, c] of Object.entries(it.cells)) want.set(`${shop}|${c.id}`, { item: it, shop, cell: c });
  const got = new Map();
  let unknown = 0, from = null, to = null;
  for (const r of rows) {
    if (!r || typeof r !== "object" || !SHOPS.includes(r.retailer) || !r.retailerProductId) throw new Error("a row has no valid retailer or product id");
    const t = Date.parse(r.scrapedAt);
    if (!isFinite(t) || !/^\d{4}-\d{2}-\d{2}T/.test(String(r.scrapedAt))) throw new Error("a row has no valid scrapedAt");
    if (r.price !== null && r.price !== undefined && !(typeof r.price === "number" && r.price > 0 && r.price < 1000)) throw new Error(`a price is outside 0 to 1000 (${r.retailerProductId})`);
    for (const k of ["loyaltyPrice", "wasPrice"]) if (r[k] !== null && r[k] !== undefined && !(typeof r[k] === "number" && r[k] > 0 && r[k] < 1000)) throw new Error(`${k} is outside 0 to 1000 (${r.retailerProductId})`);
    from = from === null ? t : Math.min(from, t); to = to === null ? t : Math.max(to, t);
    const key = `${r.retailer}|${String(r.retailerProductId)}`;
    if (!want.has(key)) { unknown++; continue; }
    const prev = got.get(key);
    if (!prev || Date.parse(prev.scrapedAt) < t) got.set(key, r);   // the latest read of a product counts
  }
  if (new Date(from).toISOString().slice(0, 10) !== new Date(to).toISOString().slice(0, 10)) throw new Error("the newest run runs across two UTC days");
  if (unknown / rows.length > 0.05) throw new Error(`${unknown} of ${rows.length} rows are not in the pinned list`);
  const shopsWithRows = new Set([...got.values()].map(r => r.retailer));
  if (shopsWithRows.size < 3) throw new Error(`only ${shopsWithRows.size} shops have rows`);
  const toMin = new Date(to).toISOString().slice(0, 16) + "Z";
  if (previous && previous.readTo && toMin < previous.readTo) throw new Error(`the read (${toMin}) is older than the current file (${previous.readTo})`);

  const cells = {};
  for (const [key, w] of want) {
    const r = got.get(key);
    const c = {};
    if (!r) c.s = "x";
    else if (norm(r.name) !== norm(w.cell.name)) c.s = "h";
    else if (r.price === null || r.price === undefined) c.s = "n";
    else {
      c.p = pence(r.price);
      if (MEMBER_SHOPS.has(w.shop) && typeof r.loyaltyPrice === "number" && pence(r.loyaltyPrice) < c.p) c.m = pence(r.loyaltyPrice);
      if (r.inStock === true) c.o = 1; else if (r.inStock === false) c.o = 2;
      // the shop showed an offer on this item (a multibuy or a was-price): flagged, never applied. Aldi's data carries no offer text.
      if ((typeof r.promotionText === "string" && r.promotionText.trim()) || (typeof r.wasPrice === "number" && r.wasPrice > 0)) c.f = 1;
    }
    if (w.cell.q === "u" && !c.s) c.s = "h";                      // product line unconfirmed: held until a person confirms it
    (cells[w.item.n] = cells[w.item.n] || {})[w.shop] = c;
  }
  return { schema: 1, listVersion: list.version, readFrom: new Date(from).toISOString().slice(0, 16) + "Z", readTo: new Date(to).toISOString().slice(0, 16) + "Z", rowsRead: rows.length, ignoredOlder, cells };
}

const dump = o => JSON.stringify(o) + "\n";

function check(root) {
  const bad = [];
  let d, list;
  try { list = loadList(root); } catch (e) { return [e.message]; }
  try { d = readJson(root, OUT); } catch (e) { return [e.message]; }
  if (fs.readFileSync(path.join(root, OUT), "utf8").replace(/\r\n/g, "\n") !== dump(d)) bad.push(`${OUT} is not in the canonical layout`);
  if (d.schema !== 1) bad.push(`${OUT}: schema must be 1`);
  if (d.listVersion !== list.version) bad.push(`${OUT} was built for list ${d.listVersion}, the list is ${list.version}`);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$/.test(d.readFrom || "") || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$/.test(d.readTo || "")) bad.push(`${OUT}: bad read times`);
  const ok = new Set(["x", "h", "n"]);
  for (const it of list.items) for (const shop of Object.keys(it.cells)) {
    const c = d.cells && d.cells[it.n] && d.cells[it.n][shop];
    if (!c) { bad.push(`${OUT}: no cell for ${it.id}/${shop}`); continue; }
    if (c.s !== undefined && !ok.has(c.s)) bad.push(`${OUT}: bad status for ${it.id}/${shop}`);
    if (c.s === undefined && !(Number.isInteger(c.p) && c.p > 0 && c.p < 100000)) bad.push(`${OUT}: ${it.id}/${shop} has neither a status nor a price`);
    if (c.m !== undefined && !(Number.isInteger(c.m) && c.m > 0 && c.m < c.p)) bad.push(`${OUT}: ${it.id}/${shop} member price is not below the regular price`);
    if (c.m !== undefined && !MEMBER_SHOPS.has(shop)) bad.push(`${OUT}: member price at a shop with no scheme (${shop})`);
    if (c.f !== undefined && c.f !== 1) bad.push(`${OUT}: bad offer flag for ${it.id}/${shop}`);
  }
  const have = Object.values(d.cells || {}).reduce((n, o) => n + Object.keys(o).length, 0);
  const want = list.items.reduce((n, it) => n + Object.keys(it.cells).length, 0);
  if (have !== want) bad.push(`${OUT} has ${have} cells, the list has ${want}`);
  return bad;
}

module.exports = { build, check, dump, loadList, LIST, OUT, CAP, SHOPS };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", run = null, doCheck = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--check") doCheck = true;
    else if (args[i] === "--run" && args[i + 1] && !args[i + 1].startsWith("--")) run = args[++i];
    else if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  try {
    if (doCheck) { const bad = check(root); if (bad.length) { console.error(bad.join("\n")); process.exit(1); } console.log("the basket pilot file agrees with the list"); }
    else if (run) {
      const rows = JSON.parse(fs.readFileSync(run, "utf8"));
      let previous = null; try { previous = readJson(root, OUT); } catch { /* first run */ }
      const out = build(root, rows, previous);
      const tmp = path.join(root, OUT + ".tmp"); fs.mkdirSync(path.dirname(tmp), { recursive: true });
      fs.writeFileSync(tmp, dump(out)); fs.renameSync(tmp, path.join(root, OUT));
      console.log(`wrote ${OUT}: ${Object.values(out.cells).reduce((n, o) => n + Object.keys(o).length, 0)} cells, read ${out.readFrom} to ${out.readTo}`);
    } else { console.error("usage: --run ROWS.json | --check"); process.exit(2); }
  } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
}
