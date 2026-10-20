// Tests for docs/release/stamp-latest.js.   node --test docs/release/stamp-latest.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { stamp, check, buildBlock } = require("./stamp-latest.js");

const TODAY = new Date().toISOString().slice(0, 10);
const page = (vintage, title) => `<html><head><script type="application/ld+json">\n{\n  "@type": "Dataset",\n  "name": "${title}"\n}\n</script></head><body>\n<p id="status">Loading the latest week…</p>\n<!--static-latest:start-->\n<p id="static-latest" class="meta" data-vintage="${vintage}">placeholder</p>\n<!--static-latest:end-->\n</body></html>\n`;
const SM = `<?xml version="1.0"?>\n<urlset>\n  <url>\n    <loc>https://data.yappman.com/shelf-price-index/</loc>\n    <lastmod>2026-10-01</lastmod>\n  </url>\n  <url>\n    <loc>https://data.yappman.com/au-shelf-price-index/</loc>\n    <lastmod>2026-10-01</lastmod>\n  </url>\n  <url>\n    <loc>https://data.yappman.com/press/</loc>\n    <lastmod>2026-10-01</lastmod>\n  </url>\n</urlset>\n`;

function setup(ukVintage = "", auVintage = "") {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "stamp-"));
  fs.mkdirSync(path.join(root, "shelf-price-index"));
  fs.mkdirSync(path.join(root, "au-shelf-price-index"));
  fs.writeFileSync(path.join(root, "shelf-price-index/index.html"), page(ukVintage, "UK Online Shelf-Price Index"));
  fs.writeFileSync(path.join(root, "au-shelf-price-index/index.html"), page(auVintage, "AU Online Shelf-Price Index"));
  fs.writeFileSync(path.join(root, "sitemap.xml"), SM);
  return root;
}
const meta = (vintage, title, over = {}) => ({ recordType: "meta", vintage, publishedAt: TODAY + "T07:00:00Z", revision: 1, title, license: "CC BY 4.0", ...over });
const head = (vintage, over = {}) => ({ vintage, recordType: "headline", retailer: "", class: "", level: 100.1, weekOnWeekPct: 0.1, fourWeekPct: null, matched: 70000, status: "ok", ...over });
function file(root, name, data) { const p = path.join(root, name); fs.writeFileSync(p, JSON.stringify(data)); return p; }
const ukData = (v, over = {}, hOver = {}) => ({ meta: meta(v, "UK Online Shelf-Price Index", over), rows: [head(v, hOver)] });
const run = (root, o) => stamp({ root, date: TODAY, ...o });

test("stamps a normal week: text, data-vintage, JSON-LD dateModified, sitemap for exactly that page", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W43", {}, { level: 100.4, weekOnWeekPct: 0.35, fourWeekPct: -0.2 }));
  const { out, changedPages } = run(root, { uk: f, "confirm-uk": "2026-W43" });
  const html = out.get(path.join(root, "shelf-price-index/index.html"));
  assert.match(html, /data-vintage="2026-W43"/);
  assert.match(html, /Latest published week: 2026-W43\. Headline level 100\.4, \+0\.35% on the week before, -0\.20% over four weeks\./);
  assert.match(html, new RegExp(`"dateModified": "${TODAY}"`));
  assert.deepStrictEqual(changedPages, ["shelf-price-index/"]);
  const sm = out.get(path.join(root, "sitemap.xml"));
  assert.match(sm, new RegExp(`shelf-price-index/</loc>\\n\\s*<lastmod>${TODAY}`));
  assert.match(sm, /au-shelf-price-index\/<\/loc>\n\s*<lastmod>2026-10-01/);
  assert.match(sm, /press\/<\/loc>\n\s*<lastmod>2026-10-01/);
  assert.doesNotMatch(html, /\b(current|live|real-time)\b/i);
});

test("a base week says base, level 100, no change", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W42", {}, { level: 100, weekOnWeekPct: null, status: "base" }));
  const html = run(root, { uk: f, "confirm-uk": "2026-W42" }).out.get(path.join(root, "shelf-price-index/index.html"));
  assert.match(html, /\(base week: level 100\.0, no change\)/);
});

test("a base week must have level 100", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W42", {}, { level: 99, status: "base" }));
  assert.throws(() => run(root, { uk: f, "confirm-uk": "2026-W42" }), /level 100/);
});

test("refuses without the confirmation, or when it does not match the file", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W43"));
  assert.throws(() => run(root, { uk: f }), /together/);
  assert.throws(() => run(root, { uk: f, "confirm-uk": "2026-W42" }), /does not match/);
  assert.throws(() => run(root, { uk: f, "confirm-uk": "W43" }), /ISO week/);
});

test("refuses a week older than the one already stamped; allows the same week again", () => {
  const root = setup("2026-W43"); const old = file(root, "old.json", ukData("2026-W42", {}, { level: 100, status: "base", weekOnWeekPct: null }));
  assert.throws(() => run(root, { uk: old, "confirm-uk": "2026-W42" }), /older than the stamped/);
  const same = file(root, "same.json", ukData("2026-W43"));
  assert.doesNotThrow(() => run(root, { uk: same, "confirm-uk": "2026-W43" }));
});

test("refuses held, skipped or unusable weeks: no meta, no headline, bad status, wrong licence/title/revision", () => {
  const root = setup();
  const cases = [
    [{ meta: null, rows: [head("2026-W43")] }, /does not match|file must be/],
    [{ meta: meta("2026-W44", "UK Online Shelf-Price Index"), rows: [head("2026-W43")] }, /exactly one headline/],
    [{ meta: meta("2026-W43", "UK Online Shelf-Price Index"), rows: [] }, /exactly one headline/],
    [ukData("2026-W43", {}, { status: "carried" }), /only ok or base/],
    [ukData("2026-W43", {}, { status: "insufficient" }), /only ok or base/],
    [ukData("2026-W43", { license: "CC0" }), /licence/],
    [ukData("2026-W43", { title: "AU Online Shelf-Price Index" }), /title/],
    [ukData("2026-W43", { revision: 2 }), /revision/],
    [ukData("2026-W43", { publishedAt: "2999-01-01T00:00:00Z" }), /future/],
    [ukData("2026-W43", { publishedAt: "not a date" }), /publishedAt/],
  ];
  for (const [data, re] of cases) { const f = file(root, "x.json", data); assert.throws(() => run(root, { uk: f, "confirm-uk": data.meta && data.meta.vintage ? data.meta.vintage : "2026-W43" }), re); }
});

test("non-numeric or hostile values are rejected, and text values are escaped", () => {
  const root = setup();
  const f = file(root, "x.json", ukData("2026-W43", {}, { level: "<script>alert(1)</script>" }));
  assert.throws(() => run(root, { uk: f, "confirm-uk": "2026-W43" }), /not a finite number/);
  const g = file(root, "y.json", ukData("2026-W43", {}, { weekOnWeekPct: "1e999" }));
  assert.throws(() => run(root, { uk: g, "confirm-uk": "2026-W43" }), /not a finite number/);
  const { html } = buildBlock("uk", ukData("2026-W43"), "2026-W43", TODAY);
  assert.doesNotMatch(html, /<script/i);
});

test("atomic: if the second market fails, nothing is written for the first", () => {
  const root = setup(); const uk = file(root, "uk.json", ukData("2026-W43"));
  const au = file(root, "au.json", { meta: meta("2026-W42", "AU Online Shelf-Price Index"), rows: [] });
  const before = fs.readFileSync(path.join(root, "shelf-price-index/index.html"), "utf8");
  assert.throws(() => run(root, { uk, "confirm-uk": "2026-W43", au, "confirm-au": "2026-W42" }), /headline/);
  assert.strictEqual(fs.readFileSync(path.join(root, "shelf-price-index/index.html"), "utf8"), before);
  assert.strictEqual(fs.readFileSync(path.join(root, "sitemap.xml"), "utf8"), SM);
});

test("a missing marker or sitemap entry fails closed", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W43"));
  fs.writeFileSync(path.join(root, "shelf-price-index/index.html"), "<html></html>");
  assert.throws(() => run(root, { uk: f, "confirm-uk": "2026-W43" }), /markers not found/);
  const r2 = setup(); fs.writeFileSync(path.join(r2, "sitemap.xml"), "<urlset></urlset>");
  assert.throws(() => run(r2, { uk: file(r2, "u.json", ukData("2026-W43")), "confirm-uk": "2026-W43" }), /sitemap entry missing/);
});

test("the date must be real and within one day of today", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W43"));
  assert.throws(() => stamp({ root, date: "2026-13-45", uk: f, "confirm-uk": "2026-W43" }), /real/);
  assert.throws(() => stamp({ root, date: "2020-01-01", uk: f, "confirm-uk": "2026-W43" }), /within one day/);
});

test("--check fails on the placeholder and passes once stamped", () => {
  const root = setup(); assert.ok(check(root).length === 2);
  const { out } = run(root, { uk: file(root, "uk.json", ukData("2026-W43")), "confirm-uk": "2026-W43", au: file(root, "au.json", { meta: meta("2026-W42", "AU Online Shelf-Price Index"), rows: [head("2026-W42")] }), "confirm-au": "2026-W42" });
  for (const [p, s] of out) fs.writeFileSync(p, s);
  assert.deepStrictEqual(check(root), []);
});

test("the script uses only fs and path: no network, eval or child processes", () => {
  const src = fs.readFileSync(path.join(__dirname, "stamp-latest.js"), "utf8");
  assert.doesNotMatch(src, /require\(["'](https?|net|dgram|dns|tls|child_process|vm|worker_threads)["']\)/);
  assert.doesNotMatch(src, /\beval\s*\(|new Function|fetch\s*\(|XMLHttpRequest|process\.binding/);
  const reqs = [...src.matchAll(/require\(["']([^"']+)["']\)/g)].map(m => m[1]).sort();
  assert.deepStrictEqual(reqs, ["fs", "path"]);
});
