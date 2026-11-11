// Tests for docs/release/build-cpi-page.js.   node --test docs/release/build-cpi-page.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const { build, check, write, OUT, CPI } = require("./build-cpi-page.js");

const SCRIPT = path.join(__dirname, "build-cpi-page.js");
const TPL = '<!DOCTYPE html>\n<html>\n<head>\n<title>x</title>\n<meta name="description" content="x">\n<meta property="og:title" content="x">\n<meta property="og:description" content="x">\n<meta property="og:url" content="x">\n<link rel="canonical" href="x">\n</head>\n<body><nav><button class="nav-top active" aria-current="true">T</button></nav>\n<main id="main" tabindex="-1">\n<h1>t</h1>\n</main>\n<footer>f</footer>\n</body></html>\n';
const meta = (v, base) => ({ vintage: v, publishedAt: "2026-11-09T12:49:02Z", revision: 1, recordType: "meta", base });
const row = (v, rt, cls, level, wow, status = "ok") => ({ vintage: v, recordType: rt, retailer: "", class: cls, level, weekOnWeekPct: wow, status });
const REF = { schema: 1, retrievedOn: "2026-11-11", series: [
  { market: "uk", publisher: "Office for National Statistics", name: "CPI annual rate, food", seriesId: "D7G8", period: "September 2026", month: "2026-09", value: 1.3, unit: "%", publishedOn: "2026-10-21", nextRelease: "2026-11-18", url: "https://www.ons.gov.uk/x" },
  { market: "au", publisher: "Australian Bureau of Statistics", name: "CPI, food, 12 months", seriesId: null, period: "September 2026", month: "2026-09", value: 3.2, unit: "%", publishedOn: "2026-10-28", nextRelease: null, url: "https://www.abs.gov.au/x" },
] };
function site(ref = REF) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cpi-"));
  fs.mkdirSync(path.join(root, "data")); fs.mkdirSync(path.join(root, "notices/w41-skipped"), { recursive: true });
  fs.writeFileSync(path.join(root, "notices/w41-skipped/index.html"), TPL);
  fs.writeFileSync(path.join(root, "data/uk-shelf-price-index.json"), JSON.stringify([meta("2026-W45", "2026-W42"), row("2026-W45", "headline", "", 99.7347, 0.0109), row("2026-W45", "subtotal", "food-soft-drinks", 99.9, 0.05)]));
  fs.writeFileSync(path.join(root, "data/au-shelf-price-index.json"), JSON.stringify([meta("2026-W45", "2026-W41"), row("2026-W45", "headline", "", 100.1408, -0.4973)]));
  fs.writeFileSync(path.join(root, CPI), JSON.stringify(ref));
  return root;
}

test("our figures come from the index files and the official figures from the reference file, each with its period and date", () => {
  const p = build(site()).get(OUT);
  assert.match(p, /<td>2026-W45<\/td><td class="num">99\.7<\/td><td>\+0\.01% on the week before<\/td><td>2026-W42<\/td><td>9 November 2026<\/td>/);
  assert.match(p, /food and soft drinks subtotal<\/td><td>2026-W45<\/td><td class="num">99\.9<\/td>/);
  assert.match(p, /<td class="num">100\.1<\/td><td>-0\.50% on the week before<\/td><td>2026-W41<\/td>/);
  assert.match(p, /<td>Office for National Statistics<\/td><td>CPI annual rate, food \(series D7G8\)<\/td><td>September 2026<\/td><td class="num">\+1\.3<\/td>/);
  assert.match(p, /<td>21 October 2026<\/td><td><a href="https:\/\/www\.ons\.gov\.uk\/x">source<\/a>/);
  assert.match(p, /next ONS release is 18 November 2026/); assert.match(p, /Copied by hand on 11 November 2026/);
});

test("the page draws no conclusion and makes no accuracy or tracking claim", () => {
  const p = build(site()).get(OUT);
  assert.match(p, /draws no conclusion/); assert.match(p, /not comparable/); assert.match(p, /only week 39 of the closed series/);
  assert.match(p, /Open Government Licence v3\.0/); assert.match(p, /Australian Bureau of Statistics, <a href="https:\/\/creativecommons\.org\/licenses\/by\/4\.0\/">CC BY 4\.0/);
  assert.doesNotMatch(p, /\b(accurate|accuracy|tracks|predict|leading indicator|ahead of|confirms|matches CPI|nowcast|official)\b/i);
});

test("a source link outside ons.gov.uk and abs.gov.au, a bad value, a bad date or a missing field stops the build", () => {
  const bad = [
    s => (s.url = "https://example.com/x"), s => (s.value = "1.3"), s => (s.publishedOn = "21 Oct"), s => delete s.period, s => (s.market = "nz"),
  ];
  for (const mut of bad) { const ref = JSON.parse(JSON.stringify(REF)); mut(ref.series[0]); assert.throws(() => build(site(ref))); }
  assert.throws(() => build(site({ schema: 2, series: [] })), /expected shape/);
});

test("a CPI series for another month stops the build, so the period sentence cannot go stale", () => {
  const ref = JSON.parse(JSON.stringify(REF)); ref.series[0].month = "2026-10"; ref.series[0].period = "October 2026";
  assert.throws(() => build(site(ref)), /rewrite it in build-cpi-page\.js/);
});

test("our side must have exactly one headline row (and the UK subtotal) for the latest week", () => {
  const root = site();
  fs.writeFileSync(path.join(root, "data/au-shelf-price-index.json"), JSON.stringify([meta("2026-W45", "2026-W41")]));
  assert.throws(() => build(root), /expected one headline row/);
  const r2 = site();
  fs.writeFileSync(path.join(r2, "data/uk-shelf-price-index.json"), JSON.stringify([meta("2026-W45", "2026-W42"), row("2026-W45", "headline", "", 99.7, 0.01)]));
  assert.throws(() => build(r2), /subtotal food-soft-drinks/);
});

test("deterministic; --check passes after a build and fails when the reference or the index moves", () => {
  const root = site(); write(root, build(root));
  const first = fs.readFileSync(path.join(root, OUT), "utf8"); write(root, build(root));
  assert.strictEqual(fs.readFileSync(path.join(root, OUT), "utf8"), first);
  assert.deepStrictEqual(check(root), []);
  const ref = JSON.parse(JSON.stringify(REF)); ref.series[0].value = 1.4; fs.writeFileSync(path.join(root, CPI), JSON.stringify(ref));
  assert.match(check(root).join("\n"), /is not what the data files give/);
  const r = cp.spawnSync(process.execPath, [SCRIPT, "--check", "--root", root], { encoding: "utf8" }); assert.strictEqual(r.status, 1);
});

test("the committed page and reference file agree (when the site has them)", () => {
  const top = path.join(__dirname, "..", "..");
  if (!fs.existsSync(path.join(top, OUT))) return;
  assert.deepStrictEqual(check(top), []);
});

test("the script uses only fs and path: no network, eval or child process", () => {
  const src = fs.readFileSync(SCRIPT, "utf8");
  assert.doesNotMatch(src, /require\(["'](https?|net|dgram|dns|tls|child_process|vm|worker_threads)["']\)/);
  assert.doesNotMatch(src, /\beval\s*\(|new Function|fetch\s*\(|process\.env/);
  assert.deepStrictEqual([...src.matchAll(/require\(["']([^"']+)["']\)/g)].map(m => m[1]).sort(), ["fs", "path"]);
});
