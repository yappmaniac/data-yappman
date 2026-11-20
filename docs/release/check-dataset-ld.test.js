// Tests for docs/release/check-dataset-ld.js.   node --test docs/release/check-dataset-ld.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const C = require("./check-dataset-ld.js");
const SCRIPT = path.join(__dirname, "check-dataset-ld.js");
const ROOT = path.join(__dirname, "..", "..");

const good = (slug, extra) => Object.assign({
  "@context": "https://schema.org", "@type": "Dataset", name: "A free dataset", description: "A description that is long enough to mean something about the data.",
  url: `https://data.yappman.com/${slug}/`, license: "https://creativecommons.org/licenses/by/4.0/", isAccessibleForFree: true,
  creator: { "@type": "Organization", name: "Yappman Data" }, temporalCoverage: "2026-01-01/..", dateModified: "2026-11-19",
  distribution: [{ "@type": "DataDownload", encodingFormat: "text/csv", contentUrl: `https://data.yappman.com/${slug}/f.csv` }],
}, extra || {});
function site(mutate) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ld-"));
  for (const rel of C.REQUIRED) {
    const slug = rel.replace(/\/index\.html$/, "");
    let doc = good(slug);
    if (rel === "eu-air-sea-traffic-sample/index.html") doc.license = { "@type": "CreativeWork", name: "reuse authorised provided the source is acknowledged", url: "https://ec.europa.eu/eurostat/web/main/help/copyright-notice" };
    if (mutate) doc = mutate(rel, doc) || doc;
    fs.mkdirSync(path.join(root, slug), { recursive: true });
    fs.writeFileSync(path.join(root, slug, "f.csv"), "a\n");
    fs.writeFileSync(path.join(root, rel), `<head>\n<link rel="canonical" href="https://data.yappman.com/${slug}/">\n<script type="application/ld+json">\n${JSON.stringify(doc, null, 2)}\n</script>\n</head>\n`);
  }
  return root;
}
const first = root => C.check(root).join("\n");

test("a complete set of good pages passes", () => assert.deepStrictEqual(C.check(site()), []));

test("each rule fails the page that breaks it", () => {
  const one = (rel, fn) => first(site((r, d) => { if (r === rel) fn(d); }));
  const R = "council-tax/index.html";
  assert.match(one(R, d => { d.url = "https://data.yappman.com/other/"; }), /not the canonical link/);
  assert.match(one(R, d => { d.license = "https://example.com/l"; }), /licence URLs/);
  assert.match(one(R, d => { delete d.license; }), /licence URLs/);
  assert.match(one(R, d => { d.isAccessibleForFree = false; }), /isAccessibleForFree/);
  assert.match(one(R, d => { d.creator.name = "Someone"; }), /creator/);
  assert.match(one(R, d => { d.temporalCoverage = "1995/.."; }), /ISO interval/);
  assert.match(one(R, d => { d.dateModified = "19 Nov 2026"; }), /dateModified/);
  assert.match(one(R, d => { d.distribution[0].contentUrl = "https://data.yappman.com/council-tax/missing.csv"; }), /does not exist/);
  assert.match(one(R, d => { d.distribution[0].contentUrl = "https://elsewhere.example/f.csv"; }), /outside this site/);
  assert.match(one(R, d => { d.sameAs = ["https://apify.com/yappman/x?fpr=abc"]; }), /affiliate/);
  assert.match(one(R, d => { d.offers = { price: 1 }; }), /unexpected field offers/);
  assert.match(one(R, d => { d.description = "short"; }), /real description/);
  assert.match(one(R, d => { d.license = ["https://creativecommons.org/licenses/by/4.0/", "https://example.com/x"]; }), /licence URLs/);
});

test("a required page without a Dataset block, or with invalid JSON, is reported; the EU page carries exactly the approved Eurostat line", () => {
  const root = site();
  fs.writeFileSync(path.join(root, "rental-yield/index.html"), "<head></head>\n");
  fs.writeFileSync(path.join(root, "basket-x.html"), '<script type="application/ld+json">\n{bad\n</script>\n');
  const out = first(root);
  assert.match(out, /rental-yield\/index\.html: expected exactly one Dataset block, found 0/); assert.match(out, /not valid JSON/);
  assert.doesNotMatch(first(site()), /eu-air/);
  assert.match(first(site((r, d) => { if (r.startsWith("eu-air")) delete d.license; })), /approved Eurostat reuse line/);
  assert.match(first(site((r, d) => { if (r.startsWith("eu-air")) d.license.name = "free to use"; })), /approved Eurostat reuse line/);
  assert.match(first(site((r, d) => { if (r === "recalls-sample/index.html") delete d.license; })), /recalls-sample.*licence/);
});

test("command line: exit 1 with problems, 0 clean, 2 on a usage error; the real site passes", () => {
  assert.equal(spawnSync(process.execPath, [SCRIPT, "--root", site()], { encoding: "utf8" }).status, 0);
  assert.equal(spawnSync(process.execPath, [SCRIPT, "--root", site(r => (r.startsWith("council") ? { "@type": "Dataset" } : null))], { encoding: "utf8" }).status, 1);
  assert.equal(spawnSync(process.execPath, [SCRIPT, "--nonsense"], { encoding: "utf8" }).status, 2);
  assert.deepStrictEqual(C.check(ROOT), []);
  assert.ok(C.count(ROOT) >= 30);
});

test("the catalogue, when present, must carry a DataCatalog whose pages and files exist and whose licences are the stated ones", () => {
  const withCat = (cat) => { const root = site(); fs.mkdirSync(path.join(root, "free-data")); fs.writeFileSync(path.join(root, "free-data/index.html"), cat === null ? "<head></head>\n" : `<script type="application/ld+json">\n${JSON.stringify(cat)}\n</script>\n`); return root; };
  const ok = { "@context": "https://schema.org", "@type": "DataCatalog", dataset: [{ "@type": "Dataset", name: "x", url: "https://data.yappman.com/council-tax/", license: "https://creativecommons.org/licenses/by/4.0/", distribution: [{ contentUrl: "https://data.yappman.com/council-tax/f.csv" }] }] };
  assert.deepStrictEqual(C.check(withCat(ok)), []);
  assert.match(first(withCat(null)), /expected a DataCatalog block/);
  const bad = JSON.parse(JSON.stringify(ok)); bad.dataset[0].distribution[0].contentUrl = "https://data.yappman.com/council-tax/none.csv";
  assert.match(first(withCat(bad)), /file does not exist/);
  const page = JSON.parse(JSON.stringify(ok)); page.dataset[0].url = "https://data.yappman.com/nowhere/";
  assert.match(first(withCat(page)), /dataset page does not exist/);
  const lic = JSON.parse(JSON.stringify(ok)); lic.dataset[0].license = "https://example.com/";
  assert.match(first(withCat(lic)), /licence URLs/);
});
