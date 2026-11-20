// Tests for assets/sold-history.js (the history page's picker).   node --test docs/release/sold-history.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const H = require("../../assets/sold-history.js");

const ROOT = path.join(__dirname, "..", "..");
const row = (year, district, split, sales, median = null) => ({ year, district, localAuthorityCodes: "E08000035", split, sales, median, lowerQuartile: median === null ? null : median - 1000, upperQuartile: median === null ? null : median + 1000, lowSample: sales < 20 });
const DOC = { area: "LS", rows: [row(2015, "LS6", "all", 30, 200000), row(2014, "LS6", "all", 12, 190000), row(2014, "LS6", "flat", 3), row(2014, "LS1", "all", 50, 150000), row(2014, "LS6", "new-build", 7, 210000)] };
const INDEX = { month: "2026-10", areas: [{ area: "LS", districts: 2, rows: 5 }, { area: "E", districts: 1, rows: 2 }] };

test("a withheld figure shows as a dash, a figure as whole pounds", () => {
  assert.strictEqual(H.pounds(null), "–"); assert.strictEqual(H.pounds(undefined), "–");
  assert.strictEqual(H.pounds(200000), "£200,000"); assert.strictEqual(H.pounds(199999.6), "£200,000");
});

test("districts and splits come from the file: sorted districts, the nine splits in their order, only those present", () => {
  assert.deepStrictEqual(H.districtsOf(DOC), ["LS1", "LS6"]);
  assert.deepStrictEqual(H.splitsOf(DOC, "LS6"), ["all", "flat", "new-build"]);
  assert.deepStrictEqual(H.splitsOf(DOC, "LS1"), ["all"]);
  assert.deepStrictEqual(H.splitsOf(DOC, "XX9"), []);
  assert.deepStrictEqual(H.SPLITS, ["all", "detached", "semi-detached", "terraced", "flat", "freehold", "leasehold", "new-build", "existing"]);
  for (const s of H.SPLITS) assert.ok(H.SPLIT_LABEL[s], s);
});

test("rows for one district and one split come back by year, and splits are never mixed", () => {
  assert.deepStrictEqual(H.rowsFor(DOC, "LS6", "all").map(r => r.year), [2014, 2015]);
  assert.deepStrictEqual(H.rowsFor(DOC, "LS6", "flat").map(r => r.sales), [3]);
  assert.deepStrictEqual(H.rowsFor(DOC, "LS6", "terraced"), []);
});

test("the note says what the row is: withheld under 5, small sample under 20, nothing otherwise", () => {
  assert.match(H.noteFor(row(2014, "LS6", "flat", 3)), /Fewer than 5 sales: figures withheld/);
  assert.match(H.noteFor(row(2014, "LS6", "all", 12, 190000)), /Small sample: fewer than 20 sales/);
  assert.strictEqual(H.noteFor(row(2014, "LS6", "all", 20, 190000)), "");
});

test("a file address is built only from the index's own month and an area the index lists", () => {
  assert.strictEqual(H.areaUrl(INDEX, "LS", "json"), "/data/sold-prices/history/2026-10/history_LS.json");
  assert.strictEqual(H.areaUrl(INDEX, "E", "csv"), "/data/sold-prices/history/2026-10/history_E.csv");
  for (const bad of ["ZZ", "../x", "LS/../..", "", "ls", "LS%2F", null, undefined, "L"]) assert.strictEqual(H.areaUrl(INDEX, bad, "json"), null, String(bad));
  assert.strictEqual(H.areaUrl(INDEX, "LS", "html"), null);
  assert.strictEqual(H.areaUrl({ month: "../2026", areas: INDEX.areas }, "LS", "json"), null);
  assert.strictEqual(H.areaUrl({ month: "2026-13", areas: INDEX.areas }, "LS", "json"), null);
  assert.strictEqual(H.areaUrl(null, "LS", "json"), null);
});

test("the script sets text only, stores nothing, sends nothing and reads only same-site files", () => {
  const src = fs.readFileSync(path.join(ROOT, "assets/sold-history.js"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function|createElement\(['"]script/);
  assert.doesNotMatch(src, /localStorage|sessionStorage|document\.cookie|sendBeacon|XMLHttpRequest|WebSocket|umami|gtag|analytics|indexedDB/i);
  const urls = src.match(/https?:\/\/[^\s'"]+/g) || [];
  assert.deepStrictEqual(urls, []);
  assert.match(src, /credentials: 'omit'/);
});

test("the page and the stylesheet carry nothing the script does not need, and the page links the two assets", () => {
  const page = fs.readFileSync(path.join(ROOT, "sold-prices/history/index.html"), "utf8");
  assert.match(page, /<script src="\/assets\/sold-history\.js" defer><\/script>/);
  assert.match(page, /<link rel="stylesheet" href="\/assets\/sold-history\.css">/);
  for (const id of ["sh-app", "sh-status", "sh-area", "sh-district", "sh-split", "sh-files", "sh-table", "sh-caption", "sh-body"]) assert.ok(page.includes(`id="${id}"`), id);
  const css = fs.readFileSync(path.join(ROOT, "assets/sold-history.css"), "utf8");
  assert.doesNotMatch(css, /@import|url\(/);
});
