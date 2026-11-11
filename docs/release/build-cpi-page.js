#!/usr/bin/env node
"use strict";
// Builds /shelf-price-index/vs-cpi/: our UK and AU shelf-price indices next to the latest official CPI figures, and why they differ.
//
//   node docs/release/build-cpi-page.js [--root DIR]         write the page
//   node docs/release/build-cpi-page.js --check [--root DIR]   fail unless the page equals a rebuild
//
// Inputs (read only): data/uk-shelf-price-index.json and data/au-shelf-price-index.json (our own latest headline rows and the UK
// "food and soft drinks" subtotal), and data/cpi-reference.json (figures copied by hand from the ONS and ABS release pages, with
// source links and dates). No network, no clock: the page says which month each figure is for. The page makes no accuracy claim and
// draws no conclusion: the two kinds of figure measure different things over different periods, and it says so.
// Update data/cpi-reference.json when ONS or ABS publish (the checklist line), then rebuild.
// The "different periods" sentence is written for the CPI month PERIOD_MONTH. When a series in the reference file is for another month,
// the build stops, so the sentence is rewritten by hand (with the overlap stated for that month) instead of going stale silently.
const PERIOD_MONTH = "2026-09";
const fs = require("fs");
const path = require("path");

const OUT = "shelf-price-index/vs-cpi/index.html";
const CPI = "data/cpi-reference.json";
const TEMPLATE = "notices/w41-skipped/index.html";
const SITE = "https://data.yappman.com";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const longDate = d => { if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) throw new Error(`bad date "${d}"`); const [y, m, dd] = d.split("-").map(Number); return `${dd} ${MONTHS[m - 1]} ${y}`; };
const signed = (v, p) => { const t = Math.abs(v).toFixed(p); return (Number(t) === 0 ? "" : v > 0 ? "+" : "-") + t; };
const readJson = (root, f) => { try { return JSON.parse(fs.readFileSync(path.join(root, f), "utf8")); } catch (e) { throw new Error(`${f}: cannot be read as JSON (${e.code || e.message})`); } };

function ours(items, label, pickSubtotal) {
  const metas = items.filter(r => r && r.recordType === "meta").sort((a, b) => (a.vintage < b.vintage ? -1 : 1));
  const m = metas[metas.length - 1];
  if (!m || !WEEK_RE.test(String(m.vintage)) || !WEEK_RE.test(String(m.base))) throw new Error(`${label}: no valid latest meta item`);
  const pub = /^(\d{4}-\d{2}-\d{2})T/.exec(String(m.publishedAt || ""));
  if (!pub) throw new Error(`${label}: the latest week has no publishedAt`);
  const rows = items.filter(r => r && r.vintage === m.vintage);
  const one = (rt, cls) => { const f = rows.filter(r => r.recordType === rt && (cls === undefined || r.class === cls) && r.retailer === ""); if (f.length !== 1) throw new Error(`${label}: expected one ${rt}${cls ? " " + cls : ""} row for ${m.vintage}, found ${f.length}`); return f[0]; };
  const num = (r, k) => { if (typeof r[k] !== "number" || !isFinite(r[k])) throw new Error(`${label}: ${r.recordType} ${k} is not a number`); return r[k]; };
  const h = one("headline");
  const out = { week: m.vintage, base: m.base, published: pub[1], headline: { level: num(h, "level"), wow: h.status === "base" ? null : num(h, "weekOnWeekPct") } };
  if (pickSubtotal) { const s = one("subtotal", pickSubtotal); out.subtotal = { level: num(s, "level"), wow: s.status === "base" ? null : num(s, "weekOnWeekPct") }; }
  return out;
}

function load(root) {
  const uk = ours(readJson(root, "data/uk-shelf-price-index.json"), "UK index", "food-soft-drinks");
  const au = ours(readJson(root, "data/au-shelf-price-index.json"), "AU index", null);
  const ref = readJson(root, CPI);
  if (ref.schema !== 1 || !Array.isArray(ref.series) || !ref.series.length) throw new Error(`${CPI}: not the expected shape`);
  longDate(ref.retrievedOn);
  for (const s of ref.series) {
    if (!["uk", "au"].includes(s.market) || typeof s.value !== "number" || !isFinite(s.value)) throw new Error(`${CPI}: a series has a bad market or value`);
    for (const k of ["publisher", "name", "period", "unit", "url"]) if (typeof s[k] !== "string" || !s[k]) throw new Error(`${CPI}: a series has no ${k}`);
    if (!/^https:\/\/(www\.ons\.gov\.uk|www\.abs\.gov\.au)\//.test(s.url)) throw new Error(`${CPI}: ${s.name} has a source link outside ons.gov.uk and abs.gov.au`);
    longDate(s.publishedOn); if (s.nextRelease) longDate(s.nextRelease);
    if (s.month !== PERIOD_MONTH) throw new Error(`${CPI}: ${s.name} is for ${s.month}; the page's period sentence is written for ${PERIOD_MONTH}: rewrite it in build-cpi-page.js for the new month, then set PERIOD_MONTH`);
  }
  return { uk, au, ref };
}

function body(d) {
  const cpiRows = m => d.ref.series.filter(s => s.market === m).map(s => `<tr><td>${esc(s.publisher)}</td><td>${esc(s.name)}${s.seriesId ? ` (series ${esc(s.seriesId)})` : ""}</td><td>${esc(s.period)}</td><td class="num">${signed(s.value, 1)}</td><td>${esc(s.unit)}</td><td>${esc(longDate(s.publishedOn))}</td><td><a href="${esc(s.url)}">source</a></td></tr>`).join("\n");
  const wow = v => (v === null ? "base week" : `${signed(v, 2)}% on the week before`);
  const ukNext = d.ref.series.find(s => s.market === "uk" && s.nextRelease);
  return `<header>
  <h1>Our shelf-price indices and the ONS and ABS consumer price indices</h1>
  <p class="sub">The latest figures of each kind, side by side, and why they are not the same thing. The figures are only for the months and weeks shown. This page draws no conclusion from them.</p>
</header>

<h2 id="ours">Our indices (weekly, posted online shelf prices)</h2>
<div class="table-wrap"><table><thead><tr><th>Index</th><th>Week</th><th class="num">Level</th><th>Change</th><th>Base 100 at</th><th>Published</th></tr></thead><tbody>
<tr><td><a href="/shelf-price-index/">UK, all four retailers, all categories</a></td><td>${esc(d.uk.week)}</td><td class="num">${d.uk.headline.level.toFixed(1)}</td><td>${wow(d.uk.headline.wow)}</td><td>${esc(d.uk.base)}</td><td>${esc(longDate(d.uk.published))}</td></tr>
<tr><td>UK, food and soft drinks subtotal</td><td>${esc(d.uk.week)}</td><td class="num">${d.uk.subtotal.level.toFixed(1)}</td><td>${wow(d.uk.subtotal.wow)}</td><td>${esc(d.uk.base)}</td><td>${esc(longDate(d.uk.published))}</td></tr>
<tr><td><a href="/au-shelf-price-index/">AU, like-for-like headline</a></td><td>${esc(d.au.week)}</td><td class="num">${d.au.headline.level.toFixed(1)}</td><td>${wow(d.au.headline.wow)}</td><td>${esc(d.au.base)}</td><td>${esc(longDate(d.au.published))}</td></tr>
</tbody></table></div>

<h2 id="cpi">ONS and ABS CPI, food and non-alcoholic beverages (monthly)</h2>
<p>Copied by hand on ${esc(longDate(d.ref.retrievedOn))} from the release pages linked in the table. They are the publishers&rsquo; figures, not ours, and are replaced when a newer release is published${ukNext ? ` (the next ONS release is ${esc(longDate(ukNext.nextRelease))})` : ""}.</p>
<div class="table-wrap"><table><thead><tr><th>Publisher</th><th>Series</th><th>Month</th><th class="num">Value</th><th>Unit</th><th>Published</th><th>Link</th></tr></thead><tbody>
${cpiRows("uk")}
${cpiRows("au")}
</tbody></table></div>

<h2 id="differ">Why they are not comparable</h2>
<ul>
  <li><strong>Different periods.</strong> The latest CPI figures are for September 2026. Of our UK index, only week 39 of the closed series (data from 27 September 2026) falls in September; the later weeks are in October and November, and the current series starts at week 42 (base 100). The AU index starts in October 2026 (week 41, base 100). A CPI annual rate compares a month with the same month a year earlier; our indices have no year-on-year figure until a year exists.</li>
  <li><strong>Different things measured.</strong> Our indices follow the posted online shelf prices of the same products at Tesco, Sainsbury&rsquo;s, Asda and Aldi (UK) and Coles, Woolworths and Aldi Australia (AU): shelf price only, with loyalty-card prices and multibuy promotions left out, no quantities and no transactions. The CPI is a measure of consumer price inflation built by each statistics office from its own sources and weights (<a href="/shelf-price-index/#method">how our index is built</a>).</li>
  <li><strong>Different weighting.</strong> Our indices give equal weight to each product within a retailer-category cell and to each retailer, with no spending weights.</li>
  <li><strong>Different scope.</strong> Our UK headline covers all categories at four retailers; the food and soft drinks subtotal is the nearest to the CPI food group, but it is not defined the same way. Our AU headline covers the categories in its like-for-like set, not food alone, and Coles is a partial slice of its range.</li>
</ul>
<p>Our indices are shelf prices only, not CPI and not a measure of prices paid; they are released under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. ONS figures: contains public sector information licensed under the <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">Open Government Licence v3.0</a>. ABS figures: source, Australian Bureau of Statistics, <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>. Not affiliated with the Office for National Statistics or the Australian Bureau of Statistics.</p>
`;
}

function build(root) {
  const d = load(root);
  const raw = fs.readFileSync(path.join(root, TEMPLATE), "utf8").replace(/\r\n/g, "\n");
  const [head0, rest] = raw.split("<main id=\"main\" tabindex=\"-1\">\n");
  if (!rest || !rest.includes("</main>\n")) throw new Error(`${TEMPLATE}: not the expected page shape`);
  const foot = rest.split("</main>\n").slice(1).join("</main>\n");
  const title = "Our shelf-price indices and the ONS and ABS consumer price indices", desc = "The latest UK and AU shelf-price index figures next to the latest ONS and ABS food CPI figures, and why they measure different things. No conclusion is drawn.";
  const lines = head0.split("\n");
  const set = (start, v) => { const i = lines.findIndex(l => l.startsWith(start)); if (i < 0) throw new Error("template line missing: " + start); lines[i] = v; };
  set("<title>", `<title>${esc(title)} — Yappman Data</title>`);
  set("<meta name=\"description\"", `<meta name="description" content="${esc(desc)}">`);
  set("<meta property=\"og:title\"", `<meta property="og:title" content="${esc(title)} — Yappman Data">`);
  set("<meta property=\"og:description\"", `<meta property="og:description" content="${esc(desc)}">`);
  set("<meta property=\"og:url\"", `<meta property="og:url" content="${SITE}/shelf-price-index/vs-cpi/">`);
  set("<link rel=\"canonical\"", `<link rel="canonical" href="${SITE}/shelf-price-index/vs-cpi/">`);
  const head = lines.join("\n").replace("class=\"nav-top active\" aria-current=\"true\"", "class=\"nav-top\"");
  return new Map([[OUT, head + "<main id=\"main\" tabindex=\"-1\">\n" + body(d) + "</main>\n" + foot]]);
}

function check(root) {
  const bad = [];
  for (const [f, s] of build(root)) {
    const p = path.join(root, f);
    if (!fs.existsSync(p)) bad.push(`${f} does not exist; run the build`);
    else if (fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n") !== s) bad.push(`${f} is not what the data files give; run the build`);
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

module.exports = { build, check, write, load, OUT, CPI };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", doCheck = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--check") doCheck = true;
    else if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  try {
    if (doCheck) { const bad = check(root); if (bad.length) { console.error(bad.join("\n")); process.exit(1); } console.log("the CPI page agrees with the data files"); }
    else { write(root, build(root)); console.log("wrote " + OUT); }
  } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
}
