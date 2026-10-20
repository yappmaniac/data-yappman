// Tests for docs/release/stamp-latest.js.   node --test docs/release/stamp-latest.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const { stamp, commit, check, buildBlock, parseArgs, esc } = require("./stamp-latest.js");

const SCRIPT = path.join(__dirname, "stamp-latest.js");
const TODAY = new Date().toISOString().slice(0, 10);
const ld = (title, extra = "") => `<script type="application/ld+json">\n{\n  "@type": "Dataset",\n  "name": "${title}"${extra}\n}\n</script>`;
const page = (vintage, title, ldBlock) => `<html><head>${ldBlock === undefined ? ld(title) : ldBlock}</head><body>\n<p id="status">Loading the latest week…</p>\n<!--static-latest:start-->\n<p id="static-latest" class="meta" data-vintage="${vintage}">placeholder</p>\n<!--static-latest:end-->\n</body></html>\n`;
const SM = `<?xml version="1.0"?>\n<urlset>\n  <url>\n    <loc>https://data.yappman.com/shelf-price-index/</loc>\n    <lastmod>2026-10-01</lastmod>\n  </url>\n  <url>\n    <loc>https://data.yappman.com/au-shelf-price-index/</loc>\n    <lastmod>2026-10-01</lastmod>\n  </url>\n  <url>\n    <loc>https://data.yappman.com/press/</loc>\n    <lastmod>2026-10-01</lastmod>\n  </url>\n</urlset>\n`;
const UK = "UK Online Shelf-Price Index", AU = "AU Online Shelf-Price Index";

function setup(ukVintage = "", auVintage = "", ukLd, auLd) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "stamp-"));
  fs.mkdirSync(path.join(root, "shelf-price-index"));
  fs.mkdirSync(path.join(root, "au-shelf-price-index"));
  fs.writeFileSync(path.join(root, "shelf-price-index/index.html"), page(ukVintage, UK, ukLd));
  fs.writeFileSync(path.join(root, "au-shelf-price-index/index.html"), page(auVintage, AU, auLd));
  fs.writeFileSync(path.join(root, "sitemap.xml"), SM);
  return root;
}
const meta = (vintage, title, over = {}) => ({ recordType: "meta", vintage, publishedAt: TODAY + "T07:00:00Z", revision: 1, title, license: "CC BY 4.0", ...over });
const head = (vintage, over = {}) => ({ vintage, recordType: "headline", retailer: "", class: "", level: 100.1, weekOnWeekPct: 0.1, fourWeekPct: null, matched: 70000, status: "ok", ...over });
function file(root, name, data) { const p = path.join(root, name); fs.writeFileSync(p, JSON.stringify(data)); return p; }
const ukData = (v, over = {}, hOver = {}) => ({ meta: meta(v, UK, over), rows: [head(v, hOver)] });
const auData = (v, over = {}, hOver = {}) => ({ meta: meta(v, AU, over), rows: [head(v, hOver)] });
const run = (root, o) => stamp({ root, date: TODAY, ...o });
const read = (root, f) => fs.readFileSync(path.join(root, f), "utf8");
const cli = (root, args) => cp.spawnSync(process.execPath, [SCRIPT, "--root", root, ...args], { encoding: "utf8" });

test("stamps a normal week: sentence with the index name, data-vintage, dateModified, sitemap for exactly that page", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W43", {}, { level: 100.4, weekOnWeekPct: 0.35, fourWeekPct: -0.2 }));
  const { out, changedPages } = run(root, { uk: f, "confirm-uk": "2026-W43" });
  const html = out.get(path.join(root, "shelf-price-index/index.html"));
  assert.match(html, /data-vintage="2026-W43"/);
  assert.match(html, /UK Online Shelf-Price Index: latest published week 2026-W43\. Headline level 100\.4, \+0\.35% on the week before, -0\.20% over four weeks\./);
  assert.match(html, new RegExp(`"dateModified": "${TODAY}"`));
  assert.deepStrictEqual(changedPages, ["shelf-price-index/"]);
  const sm = out.get(path.join(root, "sitemap.xml"));
  assert.match(sm, new RegExp(`shelf-price-index/</loc>\\n\\s*<lastmod>${TODAY}`));
  assert.match(sm, /au-shelf-price-index\/<\/loc>\n\s*<lastmod>2026-10-01/);
  assert.match(sm, /press\/<\/loc>\n\s*<lastmod>2026-10-01/);
  assert.doesNotMatch(html, /\b(current|live|real-time)\b/i);
});

test("units: percent fields are printed as stored (already in percent), a zero has no sign", () => {
  const { html } = buildBlock("uk", ukData("2026-W43", {}, { level: 100.4, weekOnWeekPct: 0.0035, fourWeekPct: 0 }), "2026-W43", TODAY);
  assert.match(html, /Headline level 100\.4, 0\.00% on the week before, 0\.00% over four weeks/);
  const b = buildBlock("uk", ukData("2026-W43", {}, { weekOnWeekPct: -1.256 }), "2026-W43", TODAY).html;
  assert.match(b, /-1\.26% on the week before/);
});

test("a base week says base, level 100, no change; a base week must have level 100", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W42", {}, { level: 100, weekOnWeekPct: null, status: "base" }));
  const html = run(root, { uk: f, "confirm-uk": "2026-W42" }).out.get(path.join(root, "shelf-price-index/index.html"));
  assert.match(html, /\(base week: level 100\.0, no change\)/);
  const bad = file(root, "b.json", ukData("2026-W42", {}, { level: 99, status: "base" }));
  assert.throws(() => run(root, { uk: bad, "confirm-uk": "2026-W42" }), /level 100/);
});

test("AU can be stamped alone and leaves the UK page and sitemap entry alone", () => {
  const root = setup(); const f = file(root, "au.json", auData("2026-W43", {}, { level: 101.2, weekOnWeekPct: 0.3 }));
  const { out, changedPages } = run(root, { au: f, "confirm-au": "2026-W43" });
  assert.deepStrictEqual(changedPages, ["au-shelf-price-index/"]);
  assert.match(out.get(path.join(root, "au-shelf-price-index/index.html")), /AU Online Shelf-Price Index: latest published week 2026-W43/);
  assert.strictEqual(out.has(path.join(root, "shelf-price-index/index.html")), false);
  assert.match(out.get(path.join(root, "sitemap.xml")), /shelf-price-index\/<\/loc>\n\s*<lastmod>2026-10-01/);
});

test("refuses without the confirmation, when it does not match the file, or when it is not an ISO week", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W43"));
  assert.throws(() => run(root, { uk: f }), /together/);
  assert.throws(() => run(root, { uk: f, "confirm-uk": "2026-W42" }), /does not match/);
  assert.throws(() => run(root, { uk: f, "confirm-uk": "W43" }), /ISO week/);
  assert.throws(() => run(root, { uk: f, "confirm-uk": "2026-W54" }), /ISO week/);
  assert.throws(() => run(root, { uk: f, "confirm-uk": "2026-W00" }), /ISO week/);
});

test("ordering: older refused, same allowed, W53 to next year allowed, next year back to W53 refused", () => {
  const root = setup("2026-W43"); const old = file(root, "old.json", ukData("2026-W42", {}, { level: 100, status: "base", weekOnWeekPct: null }));
  assert.throws(() => run(root, { uk: old, "confirm-uk": "2026-W42" }), /older than the stamped/);
  assert.doesNotThrow(() => run(root, { uk: file(root, "same.json", ukData("2026-W43")), "confirm-uk": "2026-W43" }));
  const r2 = setup("2026-W53"); assert.doesNotThrow(() => run(r2, { uk: file(r2, "n.json", ukData("2027-W01")), "confirm-uk": "2027-W01" }));
  const r3 = setup("2027-W01"); assert.throws(() => run(r3, { uk: file(r3, "o.json", ukData("2026-W53")), "confirm-uk": "2026-W53" }), /older than the stamped/);
});

test("refuses held, skipped or unusable weeks", () => {
  const root = setup();
  const cases = [
    [{ meta: null, rows: [head("2026-W43")] }, "2026-W43", /does not match|file must be/],
    [{ meta: meta("2026-W44", UK), rows: [head("2026-W43")] }, "2026-W44", /exactly one headline/],
    [{ meta: meta("2026-W43", UK), rows: [] }, "2026-W43", /exactly one headline/],
    [{ meta: meta("2026-W43", UK), rows: [head("2026-W43"), head("2026-W43", { level: 101 })] }, "2026-W43", /found 2/],
    [ukData("2026-W43", {}, { status: "carried" }), "2026-W43", /only ok or base/],
    [ukData("2026-W43", {}, { status: "insufficient" }), "2026-W43", /only ok or base/],
    [ukData("2026-W43", {}, { weekOnWeekPct: null }), "2026-W43", /weekOnWeekPct is not a finite number/],
    [ukData("2026-W43", { license: "CC0" }), "2026-W43", /licence/],
    [ukData("2026-W43", { title: AU }), "2026-W43", /title/],
    [ukData("2026-W43", { revision: 2 }), "2026-W43", /revision/],
    [ukData("2026-W43", { publishedAt: "2999-01-01T00:00:00Z" }), "2026-W43", /future/],
    [ukData("2026-W43", { publishedAt: "not a date" }), "2026-W43", /strict ISO/],
    [ukData("2026-W43", { publishedAt: TODAY + "garbage" }), "2026-W43", /strict ISO/],
    [ukData("2026-W43", { publishedAt: "2026-13-45T00:00:00Z" }), "2026-W43", /strict ISO/],
    [{ meta: meta("2026-W99", UK), rows: [head("2026-W99")] }, "2026-W99", /ISO week/],
  ];
  for (const [data, v, re] of cases) { const f = file(root, "x.json", data); assert.throws(() => run(root, { uk: f, "confirm-uk": v }), re, JSON.stringify(data).slice(0, 80)); }
});

test("non-numeric, string, null and real Infinity values are rejected; hostile text is escaped", () => {
  const root = setup();
  assert.throws(() => run(root, { uk: file(root, "x.json", ukData("2026-W43", {}, { level: "<script>alert(1)</script>" })), "confirm-uk": "2026-W43" }), /not a finite number/);
  assert.throws(() => run(root, { uk: file(root, "y.json", ukData("2026-W43", {}, { weekOnWeekPct: "1e999" })), "confirm-uk": "2026-W43" }), /not a finite number/);
  assert.throws(() => buildBlock("uk", ukData("2026-W43", {}, { level: Infinity }), "2026-W43", TODAY), /not a finite number/);
  assert.throws(() => buildBlock("uk", ukData("2026-W43", {}, { fourWeekPct: NaN }), "2026-W43", TODAY), /not a finite number/);
  assert.strictEqual(esc(`<img src=x onerror="a&b">`), "&lt;img src=x onerror=&quot;a&amp;b&quot;&gt;");
  assert.doesNotMatch(buildBlock("uk", ukData("2026-W43"), "2026-W43", TODAY).html, /<script/i);
});

test("JSON-LD guard: array, several blocks, none, or a non-Dataset top level all fail with nothing written", () => {
  const arr = `<script type="application/ld+json">\n[{"@type": "Dataset", "name": "${UK}"}]\n</script>`;
  const two = ld(UK) + ld(UK);
  const wrong = `<script type="application/ld+json">\n{"@type": "BreadcrumbList", "name": "${UK}"}\n</script>`;
  const otherName = ld("Something else");
  for (const [block, re] of [[arr, /top level is not/], [two, /exactly one JSON-LD/], ["", /exactly one JSON-LD/], [wrong, /top level is not/], [otherName, /top level is not/]]) {
    const root = setup("", "", block);
    const before = read(root, "shelf-price-index/index.html");
    assert.throws(() => run(root, { uk: file(root, "uk.json", ukData("2026-W43")), "confirm-uk": "2026-W43" }), re);
    assert.strictEqual(read(root, "shelf-price-index/index.html"), before);
  }
});

test("atomic: if the second market fails, nothing is written for the first", () => {
  const root = setup(); const uk = file(root, "uk.json", ukData("2026-W43"));
  const au = file(root, "au.json", { meta: meta("2026-W42", AU), rows: [] });
  const before = read(root, "shelf-price-index/index.html");
  assert.throws(() => run(root, { uk, "confirm-uk": "2026-W43", au, "confirm-au": "2026-W42" }), /headline/);
  assert.strictEqual(read(root, "shelf-price-index/index.html"), before);
  assert.strictEqual(read(root, "sitemap.xml"), SM);
});

function renameFailsOn(failOn, mutateRestore) {
  const root = setup(); const uk = file(root, "uk.json", ukData("2026-W43")); const au = file(root, "au.json", auData("2026-W42"));
  const r = run(root, { uk, "confirm-uk": "2026-W43", au, "confirm-au": "2026-W42" });
  const files = [...r.out.keys()];
  const before = files.map(p => fs.readFileSync(p, "utf8"));
  const real = fs.renameSync, realWrite = fs.writeFileSync; let n = 0, err;
  fs.renameSync = (a, b) => { if (++n === failOn) throw new Error("simulated rename failure"); return real(a, b); };
  if (mutateRestore) fs.writeFileSync = (p, ...rest) => { if (String(p).endsWith(mutateRestore) && !String(p).endsWith(".stamp-tmp")) throw new Error("simulated restore failure"); return realWrite(p, ...rest); };
  try { commit(r.out, r.orig); } catch (e) { err = e; } finally { fs.renameSync = real; fs.writeFileSync = realWrite; }
  const leftovers = files.map(p => p + ".stamp-tmp").filter(t => fs.existsSync(t));
  return { err, files, before, after: files.map(p => fs.readFileSync(p, "utf8")), leftovers };
}

test("a failing rename on the FIRST file changes nothing and leaves no temporary file", () => {
  const x = renameFailsOn(1);
  assert.match(x.err.message, /no file had been replaced/);
  assert.match(x.err.message, /git status/);
  assert.deepStrictEqual(x.after, x.before); assert.deepStrictEqual(x.leftovers, []);
});

test("a failing rename on a LATER file restores the earlier ones and leaves no temporary file", () => {
  const x = renameFailsOn(2);
  assert.match(x.err.message, /earlier file.s. were restored/);
  assert.deepStrictEqual(x.after, x.before); assert.deepStrictEqual(x.leftovers, []);
});

test("a restore that fails is named, not hidden", () => {
  const x = renameFailsOn(3, "shelf-price-index" + path.sep + "index.html");
  assert.match(x.err.message, /COULD NOT RESTORE: .*shelf-price-index/);
});

test("a temporary-write failure removes the partial temporary file and says to check git status", () => {
  const root = setup(); const r = run(root, { uk: file(root, "uk.json", ukData("2026-W43")), "confirm-uk": "2026-W43" });
  const files = [...r.out.keys()]; const realWrite = fs.writeFileSync; let n = 0; let err;
  fs.writeFileSync = (p, ...rest) => { if (String(p).endsWith(".stamp-tmp")) { realWrite(p, "partial"); if (++n === 2) throw new Error("simulated disk error"); return; } return realWrite(p, ...rest); };
  try { commit(r.out, r.orig); } catch (e) { err = e; } finally { fs.writeFileSync = realWrite; }
  assert.match(err.message, /nothing was changed/); assert.match(err.message, /git status/);
  assert.deepStrictEqual(files.map(p => p + ".stamp-tmp").filter(t => fs.existsSync(t)), []);
});

test("CRLF input is accepted and a stamped file is written with LF", () => {
  const root = setup();
  for (const f of ["shelf-price-index/index.html", "sitemap.xml"]) fs.writeFileSync(path.join(root, f), read(root, f).replace(/\n/g, "\r\n"));
  const r = run(root, { uk: file(root, "uk.json", ukData("2026-W43")), "confirm-uk": "2026-W43" });
  commit(r.out, r.orig);
  assert.doesNotMatch(read(root, "shelf-price-index/index.html"), /\r/);
  assert.match(read(root, "shelf-price-index/index.html"), /latest published week 2026-W43/);
});

test("missing marker or sitemap entry, and bad dates, fail closed", () => {
  const root = setup(); const f = file(root, "uk.json", ukData("2026-W43"));
  fs.writeFileSync(path.join(root, "shelf-price-index/index.html"), "<html></html>");
  assert.throws(() => run(root, { uk: f, "confirm-uk": "2026-W43" }), /markers not found/);
  const r2 = setup(); fs.writeFileSync(path.join(r2, "sitemap.xml"), "<urlset></urlset>");
  assert.throws(() => run(r2, { uk: file(r2, "u.json", ukData("2026-W43")), "confirm-uk": "2026-W43" }), /sitemap entry missing/);
  const r3 = setup(); const g = file(r3, "uk.json", ukData("2026-W43"));
  assert.throws(() => stamp({ root: r3, date: "2026-13-45", uk: g, "confirm-uk": "2026-W43" }), /real/);
  assert.throws(() => stamp({ root: r3, date: "2020-01-01", uk: g, "confirm-uk": "2026-W43" }), /within one day/);
});

test("--check fails on the placeholder (either page) and passes once both are stamped", () => {
  const root = setup(); assert.strictEqual(check(root).length, 2);
  const uk = file(root, "uk.json", ukData("2026-W43"));
  const r1 = run(root, { uk, "confirm-uk": "2026-W43" }); commit(r1.out, r1.orig);
  assert.strictEqual(check(root).length, 1); // AU still unstamped
  const au = file(root, "au.json", auData("2026-W42"));
  const r2 = run(root, { au, "confirm-au": "2026-W42" }); commit(r2.out, r2.orig);
  assert.deepStrictEqual(check(root), []);
});

test("argument parsing rejects unknown flags and a flag swallowed as another flag's value", () => {
  assert.throws(() => parseArgs(["--ukk", "x"]), /unknown argument/);
  assert.throws(() => parseArgs(["positional"]), /unknown argument/);
  assert.throws(() => parseArgs(["--uk", "--confirm-uk", "2026-W43"]), /needs a value/);
  assert.throws(() => parseArgs(["--uk"]), /needs a value/);
  assert.deepStrictEqual(parseArgs(["--uk", "a.json", "--confirm-uk", "2026-W43"]), { uk: "a.json", "confirm-uk": "2026-W43" });
  assert.deepStrictEqual(parseArgs(["--check"]), { check: true });
});

test("CLI: success, 'NOTHING WRITTEN' with exit 1, usage errors with exit 2, --check exit codes", () => {
  const root = setup();
  const good = file(root, "uk.json", ukData("2026-W43"));
  let r = cli(root, ["--check"]); assert.strictEqual(r.status, 1); assert.match(r.stderr, /unstamped placeholder/);
  r = cli(root, ["--uk", good, "--confirm-uk", "2026-W42"]); assert.strictEqual(r.status, 1); assert.match(r.stderr, /NOTHING WRITTEN/);
  assert.match(read(root, "shelf-price-index/index.html"), /data-vintage=""/);
  r = cli(root, ["--bogus"]); assert.strictEqual(r.status, 2);
  r = cli(root, ["--uk", "--confirm-uk", "2026-W43"]); assert.strictEqual(r.status, 2);
  r = cli(root, ["--uk", good, "--confirm-uk", "2026-W43"]); assert.strictEqual(r.status, 0); assert.match(r.stdout, /stamped shelf-price-index\//);
  assert.match(read(root, "shelf-price-index/index.html"), /data-vintage="2026-W43"/);
  r = cli(root, ["--check"]); assert.strictEqual(r.status, 1); // AU still unstamped
  const au = file(root, "au.json", auData("2026-W42"));
  r = cli(root, ["--au", au, "--confirm-au", "2026-W42"]); assert.strictEqual(r.status, 0);
  r = cli(root, ["--check"]); assert.strictEqual(r.status, 0);
});

test("the script uses only fs and path: no network, eval or child processes", () => {
  const src = fs.readFileSync(SCRIPT, "utf8");
  assert.doesNotMatch(src, /require\(["'](https?|net|dgram|dns|tls|child_process|vm|worker_threads)["']\)/);
  assert.doesNotMatch(src, /\beval\s*\(|new Function|fetch\s*\(|XMLHttpRequest|process\.binding/);
  const reqs = [...src.matchAll(/require\(["']([^"']+)["']\)/g)].map(m => m[1]).sort();
  assert.deepStrictEqual(reqs, ["fs", "path"]);
});
