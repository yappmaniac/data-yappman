// Tests for docs/release/build-freshness.js.   node --test docs/release/build-freshness.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const { build, check, write, parseArgs, svg, DATASETS, OUT_JSON, badgePath } = require("./build-freshness.js");

const SCRIPT = path.join(__dirname, "build-freshness.js");
const head = (v, at, over = {}) => ({ vintage: v, publishedAt: at, revision: 1, recordType: "headline", retailer: "", class: "", level: 99.7, weekOnWeekPct: 0.01, matched: 74668, status: "ok", ...over });
function site(uk = [head("2026-W44", "2026-11-02T08:20:48Z"), head("2026-W45", "2026-11-09T12:49:02Z")], au = [head("2026-W45", "2026-11-09T14:32:07Z")]) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "fresh-"));
  fs.mkdirSync(path.join(root, "data"));
  fs.writeFileSync(path.join(root, "data/uk-shelf-price-index-headline.json"), JSON.stringify([{ vintage: "2026-W45", recordType: "meta" }, ...uk]));
  fs.writeFileSync(path.join(root, "data/au-shelf-price-index.json"), JSON.stringify([{ vintage: "2026-W45", recordType: "meta" }, ...au, { recordType: "retailer", vintage: "2026-W45", level: 1 }]));
  return root;
}
const run = (root, today = "2026-11-11", age = 21) => write(root, build(root, today, age));
const read = (root, f) => fs.readFileSync(path.join(root, f), "utf8");

test("writes the JSON and one badge per dataset, with only the week and the publication date", () => {
  const root = site(); run(root);
  const j = JSON.parse(read(root, OUT_JSON));
  assert.strictEqual(j.schema, 1); assert.strictEqual(j.latestPublishedAt, "2026-11-09");
  assert.deepStrictEqual(j.datasets.map(d => [d.dataset, d.isoWeek, d.publishedAt]), [["uk-shelf-price-index", "2026-W45", "2026-11-09"], ["au-shelf-price-index", "2026-W45", "2026-11-09"]]);
  assert.deepStrictEqual(Object.keys(j.datasets[0]).sort(), ["dataset", "files", "isoWeek", "page", "publishedAt", "title"]);
  assert.doesNotMatch(JSON.stringify(j), /"(level|matched|retailer|token|storeId|taskId|userId|generatedAt)"/i);
  for (const ds of DATASETS) { const s = read(root, badgePath(ds.id)); assert.match(s, /<svg [^>]*role="img"/); assert.match(s, /2026-W45 · 9 Nov 2026/); }
});

test("deterministic: a rerun is byte-identical, whatever the clock says", () => {
  const root = site(); run(root, "2026-11-11");
  const first = [OUT_JSON, ...DATASETS.map(d => badgePath(d.id))].map(f => read(root, f));
  run(root, "2026-11-12");
  assert.deepStrictEqual([OUT_JSON, ...DATASETS.map(d => badgePath(d.id))].map(f => read(root, f)), first);
});

test("the newest week by name wins, not the last row in the file", () => {
  const root = site([head("2026-W45", "2026-11-09T12:49:02Z"), head("2026-W44", "2026-11-02T08:20:48Z")]); run(root);
  assert.strictEqual(JSON.parse(read(root, OUT_JSON)).datasets[0].isoWeek, "2026-W45");
});

test("a missing file, no headline, a bad week or a bad date stops the build", () => {
  const cases = [
    [() => { const r = site(); fs.unlinkSync(path.join(r, "data/au-shelf-price-index.json")); return r; }, /cannot be read/],
    [() => site([]), /no headline row/],
    [() => site([head("W45", "2026-11-09T12:49:02Z")]), /no valid week/],
    [() => site([head("2026-W45", "")]), /no valid publishedAt/],
    [() => site([head("2026-W45", "2026-02-30T00:00:00Z")]), /no valid publishedAt/],
    [() => site([head("2026-W45", "2026-11-09")]), /no valid publishedAt/],
  ];
  for (const [mk, re] of cases) assert.throws(() => build(mk(), "2026-11-11", 21), re);
});

test("a date in the future, or older than the maximum age, stops the build; the limit is the argument", () => {
  const root = site();
  assert.throws(() => build(root, "2026-11-08", 21), /in the future/);
  assert.throws(() => build(root, "2026-12-15", 21), /more than 21/);
  assert.doesNotThrow(() => build(root, "2026-11-30", 21));
  assert.throws(() => build(root, "2026-11-30", 10), /more than 10/);
});

test("--check passes after a build and fails when a file is edited, missing, or the data moves on", () => {
  const root = site(); run(root);
  assert.deepStrictEqual(check(root), []);
  fs.writeFileSync(path.join(root, badgePath("uk-shelf-price-index")), read(root, badgePath("uk-shelf-price-index")).replace("9 Nov", "10 Nov"));
  assert.match(check(root).join("\n"), /uk-shelf-price-index\.svg is not what the data files give/);
  run(root); fs.unlinkSync(path.join(root, OUT_JSON));
  assert.match(check(root).join("\n"), /freshness\.json does not exist/);
  run(root);
  fs.writeFileSync(path.join(root, "data/uk-shelf-price-index-headline.json"), JSON.stringify([head("2026-W46", "2026-11-16T09:00:00Z")]));
  assert.match(check(root).join("\n"), /freshness\.json is not what the data files give/);
});

test("badge text is escaped and the file is a well-formed SVG", () => {
  const s = svg({ label: 'A <b>&"x"', title: "T<" }, { isoWeek: "2026-W45", publishedAt: "2026-11-09" });
  assert.doesNotMatch(s, /<b>|&"x"/); assert.match(s, /&lt;b&gt;&amp;&quot;x&quot;/);
  assert.strictEqual((s.match(/<svg/g) || []).length, 1); assert.ok(s.trim().endsWith("</svg>"));
});

test("the badge never says OK, live or a health word, and uses no green or red", () => {
  const root = site(); run(root);
  for (const ds of DATASETS) assert.doesNotMatch(read(root, badgePath(ds.id)), /\b(ok|live|healthy|stale|real-?time|up to date)\b|#(0f0|f00)|green|red/i);
});

test("the command line: write, check, usage errors, and 'NOTHING WRITTEN' with exit 1", () => {
  const root = site();
  let r = cp.spawnSync(process.execPath, [SCRIPT, "--root", root, "--today", "2026-11-11"], { encoding: "utf8" });
  assert.strictEqual(r.status, 0); assert.match(r.stdout, /wrote data\/freshness\.json/);
  r = cp.spawnSync(process.execPath, [SCRIPT, "--check", "--root", root], { encoding: "utf8" }); assert.strictEqual(r.status, 0);
  r = cp.spawnSync(process.execPath, [SCRIPT, "--root", root, "--today", "2027-06-01"], { encoding: "utf8" }); assert.strictEqual(r.status, 1); assert.match(r.stderr, /NOTHING WRITTEN/);
  assert.strictEqual(cp.spawnSync(process.execPath, [SCRIPT, "--bogus"], { encoding: "utf8" }).status, 2);
  assert.throws(() => parseArgs(["--today", "2026-13-01"]), /real/); assert.throws(() => parseArgs(["--max-age-days", "x"]), /whole number/);
  assert.ok(!fs.readdirSync(path.join(root, "data")).some(f => f.endsWith(".stamp-tmp")));
});

test("the script reads only the two data files: no network, token, eval or child process", () => {
  const src = fs.readFileSync(SCRIPT, "utf8");
  assert.doesNotMatch(src, /require\(["'](https?|net|dgram|dns|tls|child_process|vm|worker_threads)["']\)/);
  assert.doesNotMatch(src, /\beval\s*\(|new Function|fetch\s*\(|process\.env|XMLHttpRequest/);
  assert.deepStrictEqual([...src.matchAll(/require\(["']([^"']+)["']\)/g)].map(m => m[1]).sort(), ["fs", "path"]);
});

test("the committed files agree with the committed data (when the site has them)", () => {
  const top = path.join(__dirname, "..", "..");
  if (!fs.existsSync(path.join(top, OUT_JSON))) return;
  assert.deepStrictEqual(check(top), []);
});
