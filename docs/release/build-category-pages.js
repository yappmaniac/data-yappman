#!/usr/bin/env node
// Builds one static page per category of the UK Online Shelf-Price Index from the free index file the site already publishes:
//   shelf-price-index/categories/index.html and shelf-price-index/categories/<class>/index.html (16 classes)
//
//   node docs/release/build-category-pages.js [--root DIR]        write the pages
//   node docs/release/build-category-pages.js --check [--root DIR]   fail unless they equal a rebuild
//
// Input (read only): data/uk-shelf-price-index.json. Used rows: the category rows (recordType class) and the retailer-in-category rows
// (retailer_class), which the free index already publishes. Nothing else: no product, no retailer image or description, no
// row from any paid file, no network, no clock, no token. The pages are generated from the data only, so a rebuild is byte-identical.
// The page template is the notices page's head, menu and footer, read from the site at build time.
// Honest limits written on every page: history starts 27 Sep 2026; week 41 has no data; the two series (base 2026-W39 and base
// 2026-W42) are not joined; categories are assigned by keyword rules and are approximate; shelf prices only, not CPI.
"use strict";
const fs = require("fs");
const AFF = require("./affiliate.js");
const path = require("path");

const DIR = "shelf-price-index/categories";
const SRC = "data/uk-shelf-price-index.json";
const TEMPLATE = "notices/w41-skipped/index.html";
const SITE = "https://data.yappman.com";
const LABELS = {
  "alcohol": "Alcohol", "baby": "Baby", "bread-cereals": "Bread and cereals", "dairy-eggs": "Dairy and eggs", "fish": "Fish",
  "food-other": "Other food", "fruit": "Fruit", "household": "Household", "meat": "Meat", "oils-fats": "Oils and fats", "other": "Other",
  "personal-care": "Personal care", "pet": "Pet", "soft-drinks": "Soft drinks", "sugar-confectionery": "Sugar and confectionery", "vegetables": "Vegetables",
};
// The phrase used in running text ("the shelf prices of ..."), and a scope line for the catch-all classes.
const PHRASES = {
  "alcohol": "alcohol", "baby": "baby products", "bread-cereals": "bread and cereals", "dairy-eggs": "dairy and eggs", "fish": "fish",
  "food-other": "other food", "fruit": "fruit", "household": "household products", "meat": "meat", "oils-fats": "oils and fats",
  "other": "products in no other category", "personal-care": "personal care products", "pet": "pet products", "soft-drinks": "soft drinks",
  "sugar-confectionery": "sugar and confectionery", "vegetables": "vegetables",
};
const SCOPE = {
  "other": "This category holds the products the keyword rules place in no other category, so it is a mixed group.",
  "food-other": "This category holds food that the keyword rules place in none of the named food categories, so it is a mixed group.",
};
const RETAILERS = { tesco: "Tesco", sainsburys: "Sainsbury&rsquo;s", asda: "Asda", aldi: "Aldi" };
const WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const lvl = v => (typeof v === "number" && isFinite(v) ? v.toFixed(1) : "—");
const pct = v => (typeof v !== "number" || !isFinite(v) ? "—" : (Math.abs(v) < 0.005 ? "0.00" : (v > 0 ? "+" : "-") + Math.abs(v).toFixed(2)) + "%");
const num = v => (typeof v === "number" && isFinite(v) ? v.toLocaleString("en-GB") : "—");
// A cell that is not measured that week is shown as such, never as a level: base week, or a thin cell (carried or insufficient).
const notMeasured = r => (r.status === "carried" || r.status === "insufficient");
const levelCell = r => (notMeasured(r) ? "not updated" : lvl(r.level));
const changeCell = r => (r.status === "base" ? "base" : notMeasured(r) ? "too few products" : pct(r.weekOnWeekPct));
const longDate = d => { const [y, m, dd] = d.split("-").map(Number); return `${dd} ${MONTHS[m - 1]} ${y}`; };

function load(root) {
  let items;
  try { items = JSON.parse(fs.readFileSync(path.join(root, SRC), "utf8")); } catch (e) { throw new Error(`${SRC}: cannot be read as JSON (${e.code || e.message})`); }
  if (!Array.isArray(items)) throw new Error(`${SRC}: not an array`);
  const metas = items.filter(r => r && r.recordType === "meta").sort((a, b) => (a.vintage < b.vintage ? -1 : 1));
  if (!metas.length) throw new Error(`${SRC}: no meta item`);
  const base = {}, published = {};
  for (const m of metas) { if (!WEEK_RE.test(String(m.vintage)) || !WEEK_RE.test(String(m.base))) throw new Error(`${SRC}: a meta item has a bad week or base`); base[m.vintage] = m.base; published[m.vintage] = String(m.publishedAt || "").slice(0, 10); }
  const classes = metas[metas.length - 1].classes;
  if (!Array.isArray(classes) || !classes.length) throw new Error(`${SRC}: the latest meta item lists no classes`);
  for (const c of classes) if (!(c in LABELS) || !(c in PHRASES)) throw new Error(`class "${c}" has no label in this script; add it before building`);
  const cls = {}, rc = {};
  for (const r of items) {
    if (!r || r.recordType === "meta") continue;
    if (!WEEK_RE.test(String(r.vintage)) || !(r.vintage in base)) throw new Error(`${SRC}: a row has a week with no meta item`);
    if (r.recordType === "class" && classes.includes(r.class)) (cls[r.class] = cls[r.class] || []).push(r);
    if (r.recordType === "retailer_class" && classes.includes(r.class) && r.retailer in RETAILERS) (rc[r.class] = rc[r.class] || []).push(r);
  }
  for (const c of classes) { if (!cls[c] || !cls[c].length) throw new Error(`class "${c}" has no rows`); cls[c].sort((a, b) => (a.vintage < b.vintage ? -1 : 1)); }
  const latest = metas[metas.length - 1].vintage;
  return { classes, cls, rc, base, published, latest, weeks: metas.map(m => m.vintage) };
}

function page(tpl, title, desc, url, body) {
  const lines = tpl.head.split("\n");
  const set = (start, v) => { const i = lines.findIndex(l => l.startsWith(start)); if (i < 0) throw new Error("template line missing: " + start); lines[i] = v; };
  set("<title>", `<title>${esc(title)} — Yappman Data</title>`);
  set("<meta name=\"description\"", `<meta name="description" content="${esc(desc)}">`);
  set("<meta property=\"og:title\"", `<meta property="og:title" content="${esc(title)} — Yappman Data">`);
  set("<meta property=\"og:description\"", `<meta property="og:description" content="${esc(desc)}">`);
  set("<meta property=\"og:url\"", `<meta property="og:url" content="${url}">`);
  set("<link rel=\"canonical\"", `<link rel="canonical" href="${url}">`);
  const head = lines.join("\n").replace("class=\"nav-top active\" aria-current=\"true\"", "class=\"nav-top\"");
  return head + "<main id=\"main\" tabindex=\"-1\">\n" + body + "</main>\n" + tpl.foot;
}

function chart(rows, label) {
  const pts = rows.filter(r => typeof r.level === "number" && !notMeasured(r));
  if (pts.length < 2) return "";
  const W = 520, H = 170, pl = 44, pr = 16, pt = 14, pb = 30;
  const xs = pts.map((_, i) => pl + i * (W - pl - pr) / (pts.length - 1));
  const lv = pts.map(r => r.level);
  const lo = Math.floor(Math.min(...lv) - 1), hi = Math.ceil(Math.max(...lv) + 1);
  const y = v => pt + (hi - v) * (H - pt - pb) / (hi - lo);
  const d = pts.map((r, i) => (i ? "L" : "M") + xs[i].toFixed(1) + "," + y(lv[i]).toFixed(1)).join(" ");
  const grid = [lo, (lo + hi) / 2, hi].map(v => `<line class="gridline" x1="${pl}" x2="${W - pr}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/><text class="axis" x="${pl - 6}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${Number.isInteger(v) ? v : v.toFixed(1)}</text>`).join("");
  const dots = pts.map((r, i) => `<g class="pt"><circle class="dot" r="4" cx="${xs[i].toFixed(1)}" cy="${y(lv[i]).toFixed(1)}"/><title>${esc(r.vintage)}: ${lvl(r.level)}</title></g>`).join("");
  const labels = pts.map((r, i) => `<text class="axis" x="${xs[i].toFixed(1)}" y="${H - 10}" text-anchor="${i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}">${esc(r.vintage)}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${grid}<path class="series-line" d="${d}"/>${dots}${labels}</svg>`;
}

function categoryBody(d, c) {
  const name = LABELS[c], rows = d.cls[c], last = rows[rows.length - 1];
  const current = rows.filter(r => d.base[r.vintage] === d.base[d.latest]);
  const closed = rows.filter(r => d.base[r.vintage] !== d.base[d.latest]);
  const tr = r => `<tr><td>${esc(r.vintage)}</td><td>${esc(d.base[r.vintage])}</td><td class="num">${levelCell(r)}</td><td class="num">${changeCell(r)}</td><td class="num">${num(r.matched)}</td></tr>`;
  const retailerRows = (d.rc[c] || []).filter(r => r.vintage === last.vintage).sort((a, b) => (Object.keys(RETAILERS).indexOf(a.retailer) - Object.keys(RETAILERS).indexOf(b.retailer)));
  const moved = last.status === "base" ? `Latest week ${esc(last.vintage)} is the base week: level 100.` : `Latest published week ${esc(last.vintage)}: level ${lvl(last.level)}, ${pct(last.weekOnWeekPct)} on the week before (base 100 at ${esc(d.base[last.vintage])}).`;
  return `<header>
  <h1>UK shelf prices: ${esc(name)}</h1>
  <p class="sub">How the posted online shelf prices of ${esc(PHRASES[c])} moved at Tesco, Sainsbury&rsquo;s, Asda and Aldi, from the free <a href="/shelf-price-index/">UK Online Shelf-Price Index</a>.</p>
</header>
${AFF.DISCLOSURE_HTML}
<p>${moved} Published ${esc(longDate(d.published[last.vintage]))}. Shelf prices only; it is not CPI and not a measure of prices paid.</p>
${SCOPE[c] ? `<p>${esc(SCOPE[c])}</p>\n` : ""}${chart(current, `${name}: index level by week, base 100 at ${d.base[d.latest]}`)}
<p class="meta">The chart shows the current series only. Its vertical axis does not start at zero, so small moves look larger.</p>
<h2>By week</h2>
<div class="table-wrap"><table><thead><tr><th>Week</th><th>Base week</th><th class="num">Index</th><th class="num">Week on week</th><th class="num">Matched products</th></tr></thead><tbody>
${[...closed, ...current].map(tr).join("\n")}
</tbody></table></div>
${retailerRows.length ? `<h2>By retailer, ${esc(last.vintage)}</h2>
<div class="table-wrap"><table><thead><tr><th>Retailer</th><th class="num">Index</th><th class="num">Matched products</th></tr></thead><tbody>
${retailerRows.map(r => `<tr><td>${RETAILERS[r.retailer]}</td><td class="num">${levelCell(r)}</td><td class="num">${num(r.matched)}</td></tr>`).join("\n")}
</tbody></table></div>` : ""}
<h2>What this does and does not show</h2>
<ul>
  <li>The history starts on 27 September 2026. Week 41 has no data (<a href="/notices/w41-skipped/">see the notice</a>), so the series restarted at week 42 with a new base of 100; the earlier weeks are a closed series and are not joined to the new one.</li>
  <li>Categories are assigned by keyword rules on the retailers&rsquo; category names and product names, so they are approximate, and a category can rest on fewer than four retailers (<a href="/shelf-price-index/method/">method</a>).</li>
  <li>Matched products are those priced in both weeks. A retailer cell with fewer than 20 usable products keeps the week before&rsquo;s level and is shown here as &ldquo;not updated&rdquo;. The figures are the free index&rsquo;s own; nothing is added.</li>
</ul>
<p>Released under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. Cite as &ldquo;Yappman Data, UK Online Shelf-Price Index, ${esc(name)}, CC BY 4.0, vintage ${esc(last.vintage)}, ${SITE}/${DIR}/${c}/&rdquo;. The full series is on the <a href="/shelf-price-index/">index page</a>. Product-level shelf prices can be read on demand with <a href="${AFF.withParam("https://apify.com/yappman/uk-supermarket-price-scraper?utm_source=data.yappman.com&amp;utm_medium=referral&amp;utm_campaign=categories")}" rel="${AFF.REL}">UK Supermarket &amp; Grocery Prices</a>, a pay-per-event Actor on the Apify Store.</p>
<p><a href="/${DIR}/">All categories</a></p>
`;
}

function indexBody(d) {
  const rows = d.classes.map(c => { const r = d.cls[c][d.cls[c].length - 1]; return `<tr><td><a href="/${DIR}/${c}/">${esc(LABELS[c])}</a></td><td class="num">${lvl(r.level)}</td><td class="num">${r.status === "base" ? "base" : pct(r.weekOnWeekPct)}</td><td class="num">${num(r.matched)}</td></tr>`; });
  return `<header>
  <h1>UK shelf prices by category</h1>
  <p class="sub">One page for each of the 16 categories of the free <a href="/shelf-price-index/">UK Online Shelf-Price Index</a>: week ${esc(d.latest)}, base 100 at ${esc(d.base[d.latest])}. Shelf prices only; not CPI.</p>
</header>
<div class="table-wrap"><table><thead><tr><th>Category</th><th class="num">Index</th><th class="num">Week on week</th><th class="num">Matched products</th></tr></thead><tbody>
${rows.join("\n")}
</tbody></table></div>
<p>History starts on 27 September 2026; week 41 has no data (<a href="/notices/w41-skipped/">see the notice</a>). Released under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.</p>
`;
}

function build(root) {
  const d = load(root);
  const raw = fs.readFileSync(path.join(root, TEMPLATE), "utf8").replace(/\r\n/g, "\n");
  const [head, rest] = raw.split("<main id=\"main\" tabindex=\"-1\">\n");
  if (!rest || !rest.includes("</main>\n")) throw new Error(`${TEMPLATE}: not the expected page shape`);
  const tpl = { head, foot: rest.split("</main>\n").slice(1).join("</main>\n") };
  const out = new Map();
  out.set(`${DIR}/index.html`, page(tpl, "UK shelf prices by category", "The 16 categories of the free UK Online Shelf-Price Index with the latest week, the change on the week before and the number of matched products. Shelf prices only; not CPI.", `${SITE}/${DIR}/`, indexBody(d)));
  for (const c of d.classes) {
    const name = LABELS[c];
    out.set(`${DIR}/${c}/index.html`, page(tpl, `UK shelf prices: ${name}`, `How the posted online shelf prices of ${PHRASES[c]} moved at Tesco, Sainsbury's, Asda and Aldi, by week, from the free UK Online Shelf-Price Index. Not CPI.`, `${SITE}/${DIR}/${c}/`, categoryBody(d, c)));
  }
  return out;
}

function check(root) {
  const bad = [];
  for (const [f, s] of build(root)) {
    const p = path.join(root, f);
    if (!fs.existsSync(p)) bad.push(`${f} does not exist; run the build`);
    else if (fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n") !== s) bad.push(`${f} is not what the data file gives; run the build`);
  }
  return bad;
}

function write(root, files) {
  const tmp = [];
  try {
    for (const [f, s] of files) { const p = path.join(root, f); fs.mkdirSync(path.dirname(p), { recursive: true }); const t = p + ".stamp-tmp"; tmp.push([p, t]); fs.writeFileSync(t, s); }
    for (const [p, t] of tmp) fs.renameSync(t, p);
  } finally { for (const [, t] of tmp) { try { if (fs.existsSync(t)) fs.unlinkSync(t); } catch { /* shows in git status */ } } }
}

module.exports = { build, check, write, load, LABELS, PHRASES, DIR, SRC };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", doCheck = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--check") doCheck = true;
    else if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  try {
    if (doCheck) { const bad = check(root); if (bad.length) { console.error(bad.join("\n")); process.exit(1); } console.log("category pages agree with the data file"); }
    else { const files = build(root); write(root, files); console.log(`wrote ${files.size} pages`); }
  } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
}
