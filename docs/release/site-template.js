#!/usr/bin/env node
"use strict";
// The site's shared menu and footer: ONE source, written into every page between invisible HTML-comment markers.
//
//   node docs/release/site-template.js --check [--root DIR]     exit 1 and list every page whose menu or footer differs from the source, or lacks its markers
//   node docs/release/site-template.js --write [--root DIR]     rewrite the marked regions of the pages that differ (nothing else in a page is touched)
//   node docs/release/site-template.js --migrate [--root DIR]   ONE-OFF: add the markers to a page that has none, only if its menu and footer already equal the source
//
// Source (not served: the folder starts with an underscore):  _template/nav.tpl (the menu, with no group active) and _template/footer.tpl
// (the footer, with a `<!-- site:notes -->` place for each page's own legal note). In a page:
//     <!-- site:nav active=free -->   ...the <nav> block...   <!-- /site:nav -->        active= is free, actors, institutions, resources or none; "home" marks the brand link
//     <!-- site:footer -->            ...the <footer> block... <!-- /site:footer -->     its <!-- site:notes --> region is the page's own and is never rewritten
// The pages stay plain static HTML in place (IndexNow, the sitemap and the URLs are unchanged). The four page builders call setActive() so the
// pages they write carry the same markers. No network, no clock. A page is changed only inside its two marked regions.
const fs = require("fs");
const path = require("path");

const TEMPLATE_DIR = "_template";
const SKIP_DIRS = new Set([".git", ".claude", "_incoming", "_template", "node_modules", "docs"]);
const NOT_PAGES = new Set(["google428db29621210fc5.html"]);           // a search-console verification file: no menu, no footer
const GROUPS = ["free", "actors", "institutions", "resources"];
const NAV_MARK = /<!-- site:nav((?: [a-z]+(?:=[a-z]+)?)*) -->\n/;
const NAV_END = "<!-- /site:nav -->\n";
const FOOT_MARK = "<!-- site:footer -->\n";
const FOOT_END = "<!-- /site:footer -->\n";
const NOTES_START = "<!-- site:notes -->\n";
const NOTES_END = "<!-- /site:notes -->\n";
const ACTIVE = 'class="nav-top active" aria-current="true"';
const PLAIN = 'class="nav-top"';

const lf = s => s.replace(/\r\n/g, "\n");
const read = p => fs.readFileSync(p, "utf8");

function partials(root) {
  const nav = lf(read(path.join(root, TEMPLATE_DIR, "nav.tpl")));
  const footer = lf(read(path.join(root, TEMPLATE_DIR, "footer.tpl")));
  if (!nav.startsWith('<nav aria-label="Main"') || !nav.endsWith("</nav>\n")) throw new Error(`${TEMPLATE_DIR}/nav.tpl: not a <nav> block`);
  if (nav.includes(ACTIVE)) throw new Error(`${TEMPLATE_DIR}/nav.tpl: no group may be active in the source`);
  if (!footer.startsWith('<footer class="site-footer">') || !footer.endsWith("</footer>\n") || footer.split(NOTES_START).length !== 2 || footer.split(NOTES_END).length !== 2)
    throw new Error(`${TEMPLATE_DIR}/footer.tpl: not a <footer> block with one notes place`);
  return { nav, footer };
}

// The menu for one page: the source with `group` (or none) active, and the brand link marked on the home page.
function navFor(source, group, home) {
  let nav = source;
  if (group && group !== "none") {
    if (!GROUPS.includes(group)) throw new Error(`unknown menu group "${group}"`);
    const at = `${PLAIN} aria-expanded="false" aria-controls="panel-${group}"`;
    if (nav.split(at).length !== 2) throw new Error(`the source menu has no single "${group}" group`);
    nav = nav.replace(at, `${ACTIVE} aria-expanded="false" aria-controls="panel-${group}"`);
  }
  if (home) {
    const brand = '<a class="brand" href="/">';
    if (nav.split(brand).length !== 2) throw new Error("the source menu has no single brand link");
    nav = nav.replace(brand, '<a class="brand" href="/" aria-current="page">');
  }
  return nav;
}
const markerFor = (group, home) => `<!-- site:nav active=${group || "none"}${home ? " home" : ""} -->\n`;

// For the page builders: the template page's menu is the source of truth; they mark their own group active.
function setActive(text, group) {
  const marker = text.match(NAV_MARK);
  if (!marker) throw new Error("the template page has no site:nav marker");
  const home = /(^| )home$/.test(marker[1].trim());
  const open = text.indexOf(marker[0]) + marker[0].length, close = text.indexOf(NAV_END);
  if (close < open) throw new Error("the template page has no closing site:nav marker");
  const nav = text.slice(open, close).replace(ACTIVE, PLAIN);
  const body = nav.replace(`${PLAIN} aria-expanded="false" aria-controls="panel-${group}"`, `${ACTIVE} aria-expanded="false" aria-controls="panel-${group}"`);
  if (body === nav) throw new Error(`the template menu has no "${group}" group`);
  return text.slice(0, text.indexOf(marker[0])) + markerFor(group, home) + body + text.slice(close);
}

function parse(text) {
  const nm = text.match(NAV_MARK);
  if (!nm) return { error: "no site:nav marker" };
  const nStart = text.indexOf(nm[0]), nBody = nStart + nm[0].length, nEnd = text.indexOf(NAV_END, nBody);
  if (nEnd < 0) return { error: "no closing site:nav marker" };
  const attrs = nm[1].trim().split(/\s+/).filter(Boolean);
  const active = (attrs.find(a => a.startsWith("active=")) || "active=none").slice(7), home = attrs.includes("home");
  const fStart = text.indexOf(FOOT_MARK, nEnd);
  if (fStart < 0) return { error: "no site:footer marker" };
  const fBody = fStart + FOOT_MARK.length, fEnd = text.indexOf(FOOT_END, fBody);
  if (fEnd < 0) return { error: "no closing site:footer marker" };
  const footer = text.slice(fBody, fEnd), ns = footer.indexOf(NOTES_START), ne = footer.indexOf(NOTES_END);
  if (ns < 0 || ne < ns) return { error: "the footer has no site:notes region" };
  return { nStart, nBody, nEnd, active, home, fStart, fBody, fEnd, notes: footer.slice(ns + NOTES_START.length, ne) };
}

function render(page, src) {
  const p = parse(page);
  if (p.error) return { error: p.error };
  const nav = navFor(src.nav, p.active, p.home);
  const footer = src.footer.replace(NOTES_START + NOTES_END, NOTES_START + p.notes + NOTES_END);
  return { text: page.slice(0, p.nBody) + nav + page.slice(p.nEnd, p.fBody) + footer + page.slice(p.fEnd), changed: undefined };
}

function pages(root) {
  const out = [];
  (function walk(dir) {
    for (const e of fs.readdirSync(path.join(root, dir), { withFileTypes: true })) {
      const rel = dir ? `${dir}/${e.name}` : e.name;
      if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) walk(rel); }
      else if (e.name.endsWith(".html") && !NOT_PAGES.has(rel)) out.push(rel);
    }
  })("");
  return out.sort();
}

function check(root) {
  const src = partials(root), bad = [];
  for (const f of pages(root)) {
    const page = lf(read(path.join(root, f))), r = render(page, src);
    if (r.error) bad.push(`${f}: ${r.error}`);
    else if (r.text !== page) bad.push(`${f}: its menu or footer differs from ${TEMPLATE_DIR}/; run site-template.js --write`);
  }
  return bad;
}

function writeFile(p, text, crlf) { fs.writeFileSync(p, crlf ? text.replace(/\n/g, "\r\n") : text); }

function write(root) {
  const src = partials(root), done = [];
  for (const f of pages(root)) {
    const p = path.join(root, f), raw = read(p), page = lf(raw), r = render(page, src);
    if (r.error) throw new Error(`${f}: ${r.error}`);
    if (r.text !== page) { writeFile(p, r.text, raw.includes("\r\n")); done.push(f); }
  }
  return done;
}

// One-off: put the markers into a page that has none. Refuses unless the page's menu and footer already equal the source with that page's
// active group and notes, so the migration cannot change what a visitor sees. Returns the pages it migrated.
function migrate(root) {
  const src = partials(root), done = [], plan = [];
  for (const f of pages(root)) {
    const p = path.join(root, f), raw = read(p), page = lf(raw);
    if (page.includes("<!-- site:nav")) continue;
    const nm = page.match(/(^|\n)(<nav aria-label="Main"[\s\S]*?<\/nav>\n)/);
    const fm = page.match(/(^|\n)(<footer class="site-footer">[\s\S]*?<\/footer>\n)/);
    if (!nm || !fm) throw new Error(`${f}: no menu or footer to migrate`);
    const navText = nm[2], footText = fm[2];
    const act = [...navText.matchAll(/class="nav-top active" aria-current="true"[^>]*aria-controls="panel-([a-z]+)"/g)].map(m => m[1]);
    if (act.length > 1) throw new Error(`${f}: more than one active menu group`);
    const group = act[0] || "none", home = navText.includes('<a class="brand" href="/" aria-current="page">');
    if (navFor(src.nav, group, home) !== navText) throw new Error(`${f}: its menu is not the source menu (group ${group}); migration refused`);
    const co = footText.match(/(    <p class="co">[^\n]*<\/p>\n)([\s\S]*?)(    <p><a href="#top">Back to top &uarr;<\/a><\/p>\n)/);
    if (!co) throw new Error(`${f}: the footer has no company line and back-to-top line`);
    const noted = footText.replace(co[0], co[1] + NOTES_START + co[2] + NOTES_END + co[3]);
    const rebuilt = src.footer.replace(NOTES_START + NOTES_END, NOTES_START + co[2] + NOTES_END);
    if (rebuilt !== noted) throw new Error(`${f}: its footer is not the source footer plus its own notes; migration refused`);
    const out = page.replace(navText, markerFor(group, home) + navText + NAV_END).replace(footText, FOOT_MARK + noted + FOOT_END);
    plan.push([p, out, raw.includes("\r\n")]);
    done.push(f);
  }
  for (const [p, out, crlf] of plan) writeFile(p, out, crlf);          // every page is checked first: all migrate, or none does
  return done;
}

module.exports = { check, write, migrate, setActive, pages, partials, navFor, markerFor, parse, render, TEMPLATE_DIR, GROUPS };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", mode = null;
  for (let i = 0; i < args.length; i++) {
    if (["--check", "--write", "--migrate"].includes(args[i])) mode = args[i];
    else if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  if (!mode) { console.error("usage: site-template.js --check | --write | --migrate [--root DIR]"); process.exit(2); }
  try {
    if (mode === "--check") { const bad = check(root); if (bad.length) { console.error(bad.join("\n")); process.exit(1); } console.log(`the menu and footer of ${pages(root).length} pages agree with ${TEMPLATE_DIR}/`); }
    else if (mode === "--write") { const d = write(root); console.log(d.length ? `rewrote the menu or footer of ${d.length} page(s)` : "nothing to rewrite"); }
    else { const d = migrate(root); console.log(`added markers to ${d.length} page(s)`); }
  } catch (e) { console.error("NOTHING CHANGED BEYOND WHAT IS LISTED. " + e.message); process.exit(1); }
}
