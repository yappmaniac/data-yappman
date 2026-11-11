// Tests for docs/release/build-endpoints.js.   node --test docs/release/build-endpoints.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const cp = require("child_process");
const { build, check, write, auCsv, V1, AU_COLUMNS } = require("./build-endpoints.js");

const SCRIPT = path.join(__dirname, "build-endpoints.js");
const meta = (v, base = "2026-W41") => ({ vintage: v, publishedAt: "2026-11-09T14:32:07Z", revision: 1, recordType: "meta", title: "AU Online Shelf-Price Index", base });
const row = (v, rt, ret, cls, level, extra = {}) => ({ vintage: v, publishedAt: "2026-11-09T14:32:07Z", revision: 1, recordType: rt, retailer: ret, class: cls, level, weekOnWeekPct: null, fourWeekPct: null, matched: 10, matchedShare: 1, status: "ok", ...extra });
const UKCSV = "vintage,publishedAt,revision,recordType,retailer,class,level,weekOnWeekPct,fourWeekPct,matched,matchedShare,status,entered,left,relinked,missingPackSize,base\n2026-W45,2026-11-09T12:49:02Z,1,headline,,,99.7347,0.0109,,74668,0.99,ok,,,,,2026-W42\n";
function site(au = [meta("2026-W45"), row("2026-W45", "headline", "", "", 100.1408, { weekOnWeekPct: -0.4973 }), row("2026-W45", "retailer", "coles", "", 99.5), row("2026-W45", "class", "", "dairy-eggs", 101)], ukCsv = UKCSV) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "endpoints-"));
  fs.mkdirSync(path.join(root, "data"));
  fs.writeFileSync(path.join(root, "data/uk-shelf-price-index.csv"), ukCsv);
  fs.writeFileSync(path.join(root, "data/uk-shelf-price-index.json"), JSON.stringify([meta("2026-W45", "2026-W42"), row("2026-W45", "headline", "", "", 99.7347)], null, 0) + "\n");
  fs.writeFileSync(path.join(root, "data/au-shelf-price-index.json"), JSON.stringify(au) + "\n");
  return root;
}
const rd = (root, f) => fs.readFileSync(path.join(root, f));

test("writes the v1 files: UK and AU JSON and UK CSV are byte copies; the AU CSV has the 12 core columns plus base", () => {
  const root = site(); write(root, build(root));
  for (const f of ["uk-shelf-price-index.csv", "uk-shelf-price-index.json", "au-shelf-price-index.json"]) assert.ok(rd(root, `${V1}/${f}`).equals(rd(root, `data/${f}`)), f);
  const lines = rd(root, `${V1}/au-shelf-price-index.csv`).toString().trim().split("\n");
  assert.strictEqual(lines[0], AU_COLUMNS.join(",")); assert.strictEqual(AU_COLUMNS.length, 13);
  assert.strictEqual(lines[1], "2026-W45,2026-11-09T14:32:07Z,1,headline,,,100.1408,-0.4973,,10,1,ok,2026-W41");
  assert.strictEqual(lines.length, 4);
});

test("the manifest: latest week, publication date, row counts, and the size and SHA-256 of every file; no clock", () => {
  const root = site(); write(root, build(root));
  const m = JSON.parse(rd(root, `${V1}/manifest.json`));
  assert.strictEqual(m.schema, 1); assert.strictEqual(m.version, "v1");
  assert.deepStrictEqual(m.datasets.map(d => [d.id, d.latestVintage, d.publishedAt, d.rows]), [["uk-shelf-price-index", "2026-W45", "2026-11-09", 1], ["au-shelf-price-index", "2026-W45", "2026-11-09", 3]]);
  for (const d of m.datasets) for (const f of d.files) { const b = rd(root, f.path.slice(1)); assert.strictEqual(f.bytes, b.length); assert.strictEqual(f.sha256, crypto.createHash("sha256").update(b).digest("hex")); }
  assert.doesNotMatch(JSON.stringify(m), /generatedAt|"time"|token/);
});

test("deterministic: a rebuild is byte-identical", () => {
  const root = site(); write(root, build(root));
  const first = ["manifest.json", "au-shelf-price-index.csv"].map(f => rd(root, `${V1}/${f}`));
  write(root, build(root));
  assert.ok(first[0].equals(rd(root, `${V1}/manifest.json`)) && first[1].equals(rd(root, `${V1}/au-shelf-price-index.csv`)));
});

test("CRLF in a checkout does not change the output: the files are read as LF, as they are committed and served", () => {
  const lfRoot = site(), crRoot = site();
  for (const f of ["data/uk-shelf-price-index.csv", "data/uk-shelf-price-index.json", "data/au-shelf-price-index.json"]) fs.writeFileSync(path.join(crRoot, f), rd(crRoot, f).toString().replace(/\n/g, "\r\n"));
  write(lfRoot, build(lfRoot)); write(crRoot, build(crRoot));
  for (const f of ["manifest.json", "uk-shelf-price-index.csv", "uk-shelf-price-index.json", "au-shelf-price-index.csv"]) assert.ok(rd(lfRoot, `${V1}/${f}`).equals(rd(crRoot, `${V1}/${f}`)), f);
  assert.deepStrictEqual(check(crRoot), []);
});

test("--check passes after a build; fails when a v1 file is edited or missing, or the data moves on", () => {
  const root = site(); write(root, build(root));
  assert.deepStrictEqual(check(root), []);
  fs.appendFileSync(path.join(root, `${V1}/uk-shelf-price-index.csv`), "x\n");
  assert.match(check(root).join("\n"), /uk-shelf-price-index\.csv is not what the data files give/);
  write(root, build(root)); fs.unlinkSync(path.join(root, `${V1}/manifest.json`));
  assert.match(check(root).join("\n"), /manifest\.json does not exist/);
  write(root, build(root));
  fs.writeFileSync(path.join(root, "data/au-shelf-price-index.json"), JSON.stringify([meta("2026-W46"), row("2026-W46", "headline", "", "", 100)]));
  assert.match(check(root).join("\n"), /au-shelf-price-index\.csv is not what the data files give/);
});

test("the AU CSV refuses a field that is not a plain name, week or date (no quoting, no formula injection), and bad input", () => {
  assert.throws(() => auCsv([meta("2026-W45"), row("2026-W45", "class", "", "=cmd|' /C calc'!A0", 1)]), /not a plain name/);
  assert.throws(() => auCsv([meta("2026-W45"), row("2026-W45", "class", "", 'a,b', 1)]), /not a plain name/);
  assert.throws(() => auCsv([row("2026-W45", "headline", "", "", 1)]), /before the first meta/);
  assert.throws(() => auCsv([meta("2026-W45", "bad")]), /no valid base/);
  assert.throws(() => auCsv([meta("2026-W45")]), /no rows/);
  assert.throws(() => auCsv([meta("2026-W45"), row("2026-W45", "headline", "", "", Infinity)]), /not finite/);
});

test("missing or malformed inputs stop the build and write nothing", () => {
  const root = site(); fs.unlinkSync(path.join(root, "data/au-shelf-price-index.json"));
  assert.throws(() => build(root), /cannot be read/);
  const r2 = site(); fs.writeFileSync(path.join(r2, "data/uk-shelf-price-index.json"), "{}");
  assert.throws(() => build(r2), /not an array/);
  const r3 = site(); const res = cp.spawnSync(process.execPath, [SCRIPT, "--root", r3, "--bogus"], { encoding: "utf8" });
  assert.strictEqual(res.status, 2);
  fs.unlinkSync(path.join(r3, "data/au-shelf-price-index.json"));
  const res2 = cp.spawnSync(process.execPath, [SCRIPT, "--root", r3], { encoding: "utf8" });
  assert.strictEqual(res2.status, 1); assert.match(res2.stderr, /NOTHING WRITTEN/); assert.ok(!fs.existsSync(path.join(r3, V1)));
});

test("the page recipes name files that exist, and the page links only to files the build writes", () => {
  const top = path.join(__dirname, "..", "..");
  const page = path.join(top, "data/v1/index.html");
  if (!fs.existsSync(page)) return;
  const html = fs.readFileSync(page, "utf8");
  const written = new Set([...build(top).keys()].map(f => "/" + f));
  for (const m of html.matchAll(/(?:href|src)="(\/data\/v1\/[^"#]+)"/g)) assert.ok(written.has(m[1]), m[1]);
  for (const m of html.matchAll(/https:\/\/data\.yappman\.com\/data\/v1\/([a-z-]+\.csv)/g)) assert.ok(written.has("/data/v1/" + m[1]), m[1]);
  assert.match(html, /IMPORTDATA\("https:\/\/data\.yappman\.com\/data\/v1\/uk-shelf-price-index\.csv"\)/);
});

test("the committed v1 files agree with the committed data files (when the site has them)", () => {
  const top = path.join(__dirname, "..", "..");
  if (!fs.existsSync(path.join(top, V1, "manifest.json"))) return;
  assert.deepStrictEqual(check(top), []);
});

test("the script uses only fs, path and crypto: no network, eval or child process", () => {
  const src = fs.readFileSync(SCRIPT, "utf8");
  assert.doesNotMatch(src, /require\(["'](https?|net|dgram|dns|tls|child_process|vm|worker_threads)["']\)/);
  assert.doesNotMatch(src, /\beval\s*\(|new Function|fetch\s*\(|process\.env/);
  assert.deepStrictEqual([...src.matchAll(/require\(["']([^"']+)["']\)/g)].map(m => m[1]).sort(), ["crypto", "fs", "path"]);
});
