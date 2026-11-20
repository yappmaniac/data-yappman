"use strict";
// Tests for docs/release/site-template.js: one menu and footer source, marked regions in the pages, a check that fails on drift.
// Run: node --test docs/release/site-template.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const T = require("./site-template.js");

const SCRIPT = path.join(__dirname, "site-template.js");
const REPO = path.join(__dirname, "..", "..");
const NOTE = '    <p class="legal">Page-specific licence note.</p>\n';

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), "site-template-")); }
function put(root, rel, text) { fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true }); fs.writeFileSync(path.join(root, rel), text); }
function get(root, rel) { return fs.readFileSync(path.join(root, rel), "utf8"); }
function sourceRoot() {
  const root = tmp();
  for (const f of ["nav.part", "footer.part"]) put(root, `${T.TEMPLATE_DIR}/${f}`, fs.readFileSync(path.join(REPO, T.TEMPLATE_DIR, f), "utf8"));
  return root;
}
// A page as the site had it before the markers: the menu for its group, then the footer with its own note.
function plainPage(src, group, home, note) {
  const footer = src.footer.replace("<!-- site:notes -->\n<!-- /site:notes -->\n", note);
  return `<!DOCTYPE html>\n<html>\n<head>\n<title>x</title>\n</head>\n<body>\n${T.navFor(src.nav, group, home)}<main id="main" tabindex="-1">\n<h1>t</h1>\n</main>\n${footer}</body>\n</html>\n`;
}
function plainSite() {
  const root = sourceRoot(), src = T.partials(root);
  put(root, "index.html", plainPage(src, "none", true, ""));
  put(root, "free/index.html", plainPage(src, "free", false, NOTE));
  put(root, "indices/index.html", plainPage(src, "indices", false, "").replace(/\n/g, "\r\n"));      // a CRLF page
  put(root, "google428db29621210fc5.html", "google-site-verification: google428db29621210fc5.html\n");  // not a page
  put(root, "_incoming/skipped/index.html", "<html>not a page of the site</html>\n");
  return { root, src };
}
const stripMarkers = s => s.replace(/^<!-- \/?site:[^>]*-->\r?\n/gm, "");

test("the source menu has no group active and the footer has one notes place", () => {
  const src = T.partials(REPO);
  assert.doesNotMatch(src.nav, /nav-top active/);
  assert.equal(src.footer.split("<!-- site:notes -->").length, 2);
});

test("migrate adds markers only: stripping them gives back every page byte for byte, line endings included", () => {
  const { root } = plainSite();
  const before = Object.fromEntries(T.pages(root).map(f => [f, get(root, f)]));
  assert.deepStrictEqual(T.pages(root), ["free/index.html", "index.html", "indices/index.html"]);
  assert.equal(T.migrate(root).length, 3);
  for (const f of T.pages(root)) {
    const now = get(root, f);
    assert.equal(stripMarkers(now), before[f], f);
    assert.equal(now.includes("\r\n"), before[f].includes("\r\n"), f + " line endings");
  }
  assert.deepStrictEqual(T.check(root), []);
  assert.match(get(root, "free/index.html"), /<!-- site:nav active=free -->/);
  assert.match(get(root, "index.html"), /<!-- site:nav active=none home -->/);
  assert.equal(get(root, "google428db29621210fc5.html").includes("site:"), false);
  assert.equal(T.migrate(root).length, 0, "a second migrate changes nothing");
});

test("check fails when one menu link in one page is edited, and --write puts it back without touching the rest", () => {
  const { root } = plainSite(); T.migrate(root);
  const p = path.join(root, "free/index.html"), good = fs.readFileSync(p, "utf8");
  fs.writeFileSync(p, good.replace("/methodology/", "/methodology-changed/"));
  const bad = T.check(root);
  assert.equal(bad.length, 1); assert.match(bad[0], /^free\/index\.html: its menu or footer differs/);
  const r = spawnSync(process.execPath, [SCRIPT, "--check", "--root", root], { encoding: "utf8" });
  assert.equal(r.status, 1); assert.match(r.stderr, /free\/index\.html/);
  assert.deepStrictEqual(T.write(root), ["free/index.html"]);
  assert.equal(fs.readFileSync(p, "utf8"), good);
  assert.deepStrictEqual(T.check(root), []);
});

test("a footer edit and a menu change in the source reach every page, each keeping its own note, active group and line endings", () => {
  const { root } = plainSite(); T.migrate(root);
  const nav = path.join(root, T.TEMPLATE_DIR, "nav.part");
  fs.writeFileSync(nav, fs.readFileSync(nav, "utf8").replace("/methodology/", "/how-it-works/"));
  assert.equal(T.check(root).length, 3);
  assert.equal(T.write(root).length, 3);
  assert.deepStrictEqual(T.check(root), []);
  const free = get(root, "free/index.html");
  assert.match(free, /\/how-it-works\//); assert.ok(free.includes(NOTE)); assert.match(free, /<!-- site:nav active=free -->/);
  assert.equal((free.match(/nav-top active/g) || []).length, 1);
  assert.ok(get(root, "indices/index.html").includes("\r\n"));
  assert.equal(get(root, "indices/index.html").replace(/\r\n/g, "\n").split("\n").filter(l => /^<!-- site:/.test(l)).length > 0, true);
  assert.match(get(root, "index.html"), /<a class="brand" href="\/" aria-current="page">/);
});

test("a page that lacks its markers is reported, and the check exits 1", () => {
  const { root } = plainSite();
  const bad = T.check(root);
  assert.equal(bad.length, 3); assert.match(bad[0], /no site:nav marker/);
  assert.equal(spawnSync(process.execPath, [SCRIPT, "--check", "--root", root], { encoding: "utf8" }).status, 1);
});

test("migrate refuses, and writes nothing at all, when any page's menu or footer is not the source plus its own note", () => {
  const { root } = plainSite();
  const p = path.join(root, "indices/index.html"), raw = fs.readFileSync(p, "utf8");
  fs.writeFileSync(p, raw.replace("/methodology/", "/elsewhere/"));
  const before = T.pages(root).map(f => get(root, f));
  assert.throws(() => T.migrate(root), /migration refused/);
  assert.deepStrictEqual(T.pages(root).map(f => get(root, f)), before);
  const r = spawnSync(process.execPath, [SCRIPT, "--migrate", "--root", root], { encoding: "utf8" });
  assert.equal(r.status, 1); assert.match(r.stderr, /indices\/index\.html/);
});

test("setActive: the page builders mark their own group, keep the markers, and refuse a template without them", () => {
  const { root } = plainSite(); T.migrate(root);
  const tpl = get(root, "free/index.html").replace(/\n<main[\s\S]*$/, "\n");
  const out = T.setActive(tpl, "trust");
  assert.match(out, /<!-- site:nav active=trust -->/);
  assert.equal((out.match(/nav-top active/g) || []).length, 1);
  assert.match(out, /nav-top active" aria-current="true" aria-expanded="false" aria-controls="panel-trust"/);
  assert.equal(T.setActive(T.setActive(tpl, "indices"), "trust"), out, "re-marking is stable");
  assert.throws(() => T.setActive("<html></html>", "trust"), /no site:nav marker/);
  assert.throws(() => T.setActive(tpl, "nonsense"), /no "nonsense" group/);
});

test("the real site: every page agrees with _template/", () => {
  assert.deepStrictEqual(T.check(REPO), []);
  assert.ok(T.pages(REPO).length > 50);
});

test("the command line: usage errors exit 2; the script uses only fs and path: no network, eval or child process", () => {
  assert.equal(spawnSync(process.execPath, [SCRIPT], { encoding: "utf8" }).status, 2);
  assert.equal(spawnSync(process.execPath, [SCRIPT, "--nonsense"], { encoding: "utf8" }).status, 2);
  const src = fs.readFileSync(SCRIPT, "utf8");
  assert.doesNotMatch(src, /require\(["'](https?|net|dgram|dns|tls|child_process|vm|worker_threads)["']\)/);
  assert.doesNotMatch(src, /\beval\s*\(|new Function|fetch\s*\(|process\.env/);
  assert.deepStrictEqual([...src.matchAll(/require\(["']([^"']+)["']\)/g)].map(m => m[1]).sort(), ["fs", "path"]);
});
