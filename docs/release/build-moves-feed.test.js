// Tests for docs/release/build-moves-feed.js.   node --test docs/release/build-moves-feed.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const { build, check, write, weeks, OUT, SRC } = require("./build-moves-feed.js");

const SCRIPT = path.join(__dirname, "build-moves-feed.js");
const head = (v, at, level, wow, status = "ok") => ({ vintage: v, publishedAt: at, recordType: "headline", retailer: "", class: "", level, weekOnWeekPct: wow, status });
const meta = (v, base = "2026-W42", classes = ["meat", "pet", "bread-cereals", "fish", "dairy-eggs", "vegetables", "fruit", "baby", "oils-fats", "tiny"]) => ({ vintage: v, publishedAt: "2026-11-09T12:00:00Z", recordType: "meta", base, classes });
const cls = (v, c, wow, matched = 500, status = "ok") => ({ vintage: v, recordType: "class", retailer: "", class: c, level: 100, weekOnWeekPct: wow, matched, status });
function site(items) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-"));
  fs.mkdirSync(path.join(root, "data")); fs.mkdirSync(path.join(root, "shelf-price-index"));
  fs.writeFileSync(path.join(root, SRC), JSON.stringify(items || [
    meta("2026-W42"), meta("2026-W44"), meta("2026-W45"), meta("2026-W39", "2026-W39"),
    head("2026-W42", "2026-10-26T09:58:29Z", 100, null, "base"), cls("2026-W45", "food-soft-drinks", 0.9),
    head("2026-W44", "2026-11-02T08:20:48Z", 99.72, -0.24), cls("2026-W44", "meat", 0.3), cls("2026-W44", "pet", -0.5),
    head("2026-W45", "2026-11-09T12:49:02Z", 99.73, 0.01), cls("2026-W45", "bread-cereals", 0.22), cls("2026-W45", "fish", 0.18), cls("2026-W45", "dairy-eggs", 0.07),
    cls("2026-W45", "vegetables", 0.07), cls("2026-W45", "fruit", 0.05), cls("2026-W45", "baby", -0.2), cls("2026-W45", "oils-fats", -0.21, 316), cls("2026-W45", "tiny", -9, 20),
  ]));
  return root;
}
const rd = root => fs.readFileSync(path.join(root, OUT), "utf8");

test("one entry per week with a change, newest first; base weeks have none", () => {
  const root = site(); write(root, build(root)); const s = rd(root);
  assert.deepStrictEqual([...s.matchAll(/<id>tag:data\.yappman\.com,2026:uk-shelf-price-index\/(2026-W\d\d)<\/id>/g)].map(m => m[1]), ["2026-W45", "2026-W44"]);
  assert.match(s, /<updated>2026-11-09T12:49:02Z<\/updated>/);
});

test("the same move rule as /this-week/: at least 100 matched, top 3 each way plus ties at the cut", () => {
  const w = weeks(JSON.parse(fs.readFileSync(path.join(site(), SRC), "utf8")))[0];
  assert.deepStrictEqual(w.up.map(r => r.class), ["bread-cereals", "fish", "dairy-eggs", "vegetables"]);
  assert.deepStrictEqual(w.down.map(r => r.class), ["oils-fats", "baby"]);
});

test("the content is escaped HTML inside well-formed XML, with the source and licence line", () => {
  const root = site(); write(root, build(root)); const s = rd(root);
  assert.match(s, /^<\?xml version="1\.0" encoding="utf-8"\?>\n<feed xmlns="http:\/\/www\.w3\.org\/2005\/Atom">/);
  assert.match(s, /<content type="html">&lt;p&gt;UK Online Shelf-Price Index, week 2026-W45/);
  assert.doesNotMatch(s.replace(/<content type="html">[^<]*<\/content>/g, ""), /&lt;|<p>/);
  assert.match(s, /CC BY 4\.0, vintage 2026-W45/); assert.match(s, /not CPI/);
  assert.strictEqual((s.match(/<entry>/g) || []).length, (s.match(/<\/entry>/g) || []).length);
});

test("deterministic; --check passes after a build and fails when the feed is edited or the data moves", () => {
  const root = site(); write(root, build(root)); const first = rd(root); write(root, build(root));
  assert.strictEqual(rd(root), first); assert.deepStrictEqual(check(root), []);
  fs.writeFileSync(path.join(root, OUT), first.replace("2026-W45", "2026-W46"));
  assert.match(check(root).join("\n"), /is not what the data file gives/);
});

test("each entry states its base week and warns that levels of different bases are not comparable; a retired class row is left out", () => {
  const root = site(); write(root, build(root)); const s = rd(root);
  assert.match(s, /week 2026-W45: headline level 99\.7 \(base 100 at 2026-W42\)/); assert.match(s, /not comparable: the series restarted at week 42, and earlier entries use an earlier base/);
  assert.doesNotMatch(s, /food soft drinks/);
});

test("malformed input stops the build; no published change stops it too", () => {
  assert.throws(() => build(site([meta("2026-W45"), head("W45", "2026-11-09T12:49:02Z", 99, 0.1)])), /malformed/);
  assert.throws(() => build(site([meta("2026-W45"), head("2026-W45", "2026-11-09", 99, 0.1)])), /malformed/);
  assert.throws(() => build(site([meta("2026-W45", "2026-W42", ["<b>"]), head("2026-W45", "2026-11-09T12:49:02Z", 99, 0.1), cls("2026-W45", "<b>", 0.1)])), /malformed/);
  assert.throws(() => build(site([meta("2026-W42"), head("2026-W42", "2026-10-26T09:58:29Z", 100, null, "base")])), /no published week/);
  assert.throws(() => build(site([head("2026-W45", "2026-11-09T12:49:02Z", 99, 0.1)])), /no meta item/);
  const r = cp.spawnSync(process.execPath, [SCRIPT, "--bogus"], { encoding: "utf8" }); assert.strictEqual(r.status, 2);
});

test("the committed feed agrees with the committed data (when the site has it)", () => {
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
