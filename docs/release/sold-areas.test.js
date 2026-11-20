// Tests for assets/sold-areas.js (the area history page's picker).   node --test docs/release/sold-areas.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const A = require("../../assets/sold-areas.js");
const ROOT = path.join(__dirname, "..", "..");

const INDEX = { month: "2026-10", files: [
  { key: "ah_E12000001_year", region: "E12000001", regionName: "North East", kind: "authority-year", block: null, rows: 3, authorities: 12 },
  { key: "ah_E12000001_qtr_1995-2009", region: "E12000001", regionName: "North East", kind: "authority-quarter", block: "1995-2009", rows: 1, authorities: 12 },
  { key: "ah_E12000001_qtr_2010-onwards", region: "E12000001", regionName: "North East", kind: "authority-quarter", block: "2010-onwards", rows: 1, authorities: 12 },
  { key: "ah_W92000004_year", region: "W92000004", regionName: "Wales", kind: "authority-year", block: null, rows: 1, authorities: 22 },
  { key: "ah_regions", region: null, regionName: null, kind: "region", block: null, rows: 5, authorities: 34 },
] };

test("pounds shows a withheld figure as a dash", () => {
  assert.equal(A.pounds(null), "–"); assert.equal(A.pounds(undefined), "–");
  assert.equal(A.pounds(250000), "£250,000"); assert.equal(A.pounds(0), "£0");
});

test("file addresses come only from the index: a listed key, a published extension, never a quarterly JSON", () => {
  assert.equal(A.fileUrl(INDEX, "ah_E12000001_year", "json"), "/data/sold-prices/area-history/2026-10/ah_E12000001_year.json");
  assert.equal(A.fileUrl(INDEX, "ah_E12000001_year", "csv"), "/data/sold-prices/area-history/2026-10/ah_E12000001_year.csv");
  assert.equal(A.fileUrl(INDEX, "ah_E12000001_qtr_2010-onwards", "csv"), "/data/sold-prices/area-history/2026-10/ah_E12000001_qtr_2010-onwards.csv");
  assert.equal(A.fileUrl(INDEX, "ah_E12000001_qtr_2010-onwards", "json"), null);
  assert.equal(A.fileUrl(INDEX, "ah_regions", "json").endsWith("/ah_regions.json"), true);
  assert.equal(A.fileUrl(INDEX, "ah_E12000002_year", "json"), null);                 // not listed
  assert.equal(A.fileUrl(INDEX, "../../etc/passwd", "json"), null);
  assert.equal(A.fileUrl(INDEX, "ah_E12000001_year", "html"), null);
  assert.equal(A.fileUrl({ month: "../x", files: INDEX.files }, "ah_regions", "csv"), null);
  assert.equal(A.fileUrl(null, "ah_regions", "csv"), null);
});

test("regions come from the yearly entries, by name; quarterly keys belong to their region", () => {
  assert.deepStrictEqual(A.regionsOf(INDEX).map(r => r.name), ["North East", "Wales"]);
  assert.deepStrictEqual(A.quarterKeys(INDEX, "E12000001"), ["ah_E12000001_qtr_1995-2009", "ah_E12000001_qtr_2010-onwards"]);
  assert.deepStrictEqual(A.quarterKeys(INDEX, "W92000004"), []);
});

const HEADER = A.COLUMNS.join(",");
test("the CSV reader handles quoted names with commas, doubled quotes, blanks and CRLF; a wrong header throws", () => {
  const text = HEADER + '\r\nquarter,2024-Q3,authority,E06000001,"Bristol, City of",flat,7,100000,,200000,true\r\nyear,2024,region,E12000001,North East,all,1200,200000,150000,260000,false\r\n';
  const rows = A.rowsFromCsv(text);
  assert.equal(rows.length, 2);
  assert.deepStrictEqual(rows[0], { periodType: "quarter", period: "2024-Q3", geography: "authority", code: "E06000001", name: "Bristol, City of", split: "flat", sales: 7,
    median: 100000, lowerQuartile: null, upperQuartile: 200000, lowSample: true });
  assert.equal(rows[1].lowSample, false);
  assert.equal(A.parseCsv('a,"b ""c"" d"\n')[0][1], 'b "c" d');
  assert.throws(() => A.rowsFromCsv("a,b\n1,2\n"), /header/);
});

const R = (periodType, period, code, split, extra) => Object.assign({ periodType, period, geography: "authority", code, name: code === "E06000002" ? "Alpha" : "Beta", split, sales: 30, median: 1, lowerQuartile: 1, upperQuartile: 1, lowSample: false }, extra);
test("authorities by name; splits in the page's order and only those present; rows by period, oldest first", () => {
  const rows = [R("year", "2024", "E06000009", "all"), R("year", "2023", "E06000002", "flat"), R("year", "2024", "E06000002", "all"), R("year", "2023", "E06000002", "all"), R("year", "2024", "E06000002", "new-build"), R("quarter", "2024-Q1", "E06000002", "all")];
  assert.deepStrictEqual(A.authoritiesOf(rows).map(a => a.name), ["Alpha", "Beta"]);
  assert.deepStrictEqual(A.splitsFor(rows, "E06000002", "year"), ["all", "flat", "new-build"]);
  assert.deepStrictEqual(A.splitsFor(rows, "E06000002", "quarter"), ["all"]);
  assert.deepStrictEqual(A.rowsFor(rows, "E06000002", "year", "all").map(r => r.period), ["2023", "2024"]);
  assert.deepStrictEqual(A.rowsFor([R("quarter", "2024-Q3", "E06000002", "all"), R("quarter", "2024-Q1", "E06000002", "all"), R("quarter", "2023-Q4", "E06000002", "all")], "E06000002", "quarter", "all").map(r => r.period), ["2023-Q4", "2024-Q1", "2024-Q3"]);
  assert.deepStrictEqual(A.splitsFor([R("quarter", "2024-Q1", "E06000002", "freehold")], "E06000002", "quarter"), []);   // quarters carry the four types only
});

test("the note says withheld under 5 sales and small sample under 20", () => {
  assert.equal(A.noteFor({ lowSample: true, median: null }), "Fewer than 5 sales: figures withheld");
  assert.equal(A.noteFor({ lowSample: true, median: 5 }), "Small sample: fewer than 20 sales");
  assert.equal(A.noteFor({ lowSample: false, median: 5 }), "");
});

test("the script sets no cookie, uses no storage and sends nothing (GET same-site files only); text is set with textContent", () => {
  const src = fs.readFileSync(path.join(ROOT, "assets/sold-areas.js"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  assert.doesNotMatch(src, /document\.cookie|localStorage|sessionStorage|indexedDB|XMLHttpRequest|sendBeacon|\binnerHTML\b|insertAdjacentHTML|\beval\s*\(|new Function/);
  assert.doesNotMatch(src, /method\s*:\s*['"](POST|PUT|PATCH|DELETE)/i);
  assert.doesNotMatch(src, /https?:\/\//);
  assert.match(src, /credentials: 'omit'/);
});
