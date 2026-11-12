#!/usr/bin/env node
"use strict";
// Builds /coverage/ ("How much history we hold"): the weeks of snapshots we hold, by retailer, and what exists before them.
//
//   node docs/release/build-coverage-page.js [--root DIR]         write the page
//   node docs/release/build-coverage-page.js --check [--root DIR]   fail unless the page equals a rebuild
//
// Inputs (read only): data/uk-shelf-price-index.json and data/au-shelf-price-index.json (published weeks, publish dates, bases and
// matched counts) and data/coverage-reference.json (the few facts the index cannot show, each a claim with a source).
// No network, no clock, no Apify read. Everything the page counts is computed from those files, so a normal week needs no edit.
// Rules: a claim used on the page must be confirmed:true with a source or the build stops; an OPTIONAL claim (a retailer's missing
// weeks) that is not confirmed is never printed (its cell shows a dash). A week missing from a published index needs a notice link in
// the reference file, or the build stops: a gap is never left unexplained.
const fs = require("fs");
const AFF = require("./affiliate.js");
const path = require("path");

const OUT = "coverage/index.html";
const REF = "data/coverage-reference.json";
const TEMPLATE = "notices/w41-skipped/index.html";
const SITE = "https://data.yappman.com";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;
const MANDATORY = ["weekly-start", "daily-basket-start", "snapshot-rows", "actor-history-sentence", "morrisons-no-price-history"];
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const num = n => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const longDate = d => { if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) throw new Error(`bad date "${d}"`); const [y, m, dd] = d.split("-").map(Number); return `${dd} ${MONTHS[m - 1]} ${y}`; };
const readJson = (root, f) => { try { return JSON.parse(fs.readFileSync(path.join(root, f), "utf8")); } catch (e) { throw new Error(`${f}: cannot be read as JSON (${e.code || e.message})`); } };

// ISO weeks without a clock: the Monday of a week, and the week of a date
function weekMonday(w) {
  const y = +w.slice(0, 4), wk = +w.slice(6);
  const jan4 = new Date(Date.UTC(y, 0, 4));
  const dow = (jan4.getUTCDay() + 6) % 7;
  return new Date(Date.UTC(y, 0, 4 - dow + (wk - 1) * 7));
}
function weekOf(date) {
  const t = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  t.setUTCDate(t.getUTCDate() + 3 - ((t.getUTCDay() + 6) % 7));
  const y = t.getUTCFullYear();
  const jan4 = new Date(Date.UTC(y, 0, 4));
  const wk = 1 + Math.round(((t - jan4) / 86400000 - 3 + ((jan4.getUTCDay() + 6) % 7)) / 7);
  return `${y}-W${String(wk).padStart(2, "0")}`;
}
function weeksBetween(a, b) {
  const out = [];
  for (let d = weekMonday(a); weekOf(d) <= b && out.length < 600; d = new Date(d.getTime() + 7 * 86400000)) out.push(weekOf(d));
  return out;
}

function market(items, label) {
  if (!Array.isArray(items)) throw new Error(`${label}: not a list`);
  const metas = items.filter(r => r && r.recordType === "meta").sort((a, b) => (a.vintage < b.vintage ? -1 : 1));
  if (!metas.length) throw new Error(`${label}: no meta items`);
  const weeks = metas.map(m => {
    if (!WEEK_RE.test(String(m.vintage)) || !WEEK_RE.test(String(m.base))) throw new Error(`${label}: a meta item has a bad week`);
    const pub = /^(\d{4}-\d{2}-\d{2})T/.exec(String(m.publishedAt || ""));
    if (!pub) throw new Error(`${label}: ${m.vintage} has no publishedAt`);
    return { week: m.vintage, base: m.base, published: pub[1], matched: typeof m.matchedTotal === "number" ? m.matchedTotal : null };
  });
  if (new Set(weeks.map(w => w.week)).size !== weeks.length) throw new Error(`${label}: a week appears twice`);
  const rows = new Map();   // retailer id -> weeks that have a retailer row
  for (const r of items) if (r && r.recordType === "retailer" && r.retailer) { if (!rows.has(r.retailer)) rows.set(r.retailer, new Set()); rows.get(r.retailer).add(r.vintage); }
  return { weeks, rows, first: weeks[0].week, latest: weeks[weeks.length - 1] };
}

function load(root) {
  const uk = market(readJson(root, "data/uk-shelf-price-index.json"), "UK index");
  const au = market(readJson(root, "data/au-shelf-price-index.json"), "AU index");
  const ref = readJson(root, REF);
  if (ref.schema !== 1 || !ref.claims || !ref.uk || !ref.au || !Array.isArray(ref.uk.retailers) || !Array.isArray(ref.au.retailers)) throw new Error(`${REF}: not the expected shape`);
  longDate(ref.retrievedOn);
  for (const [id, c] of Object.entries(ref.claims)) {
    if (typeof c.confirmed !== "boolean") throw new Error(`${REF}: claim ${id} has no confirmed true/false`);
    if (c.confirmed && !(typeof c.source === "string" && c.source.trim())) throw new Error(`${REF}: claim ${id} is marked confirmed but has no source`);
  }
  const confirmed = id => { if (!(id in ref.claims)) throw new Error(`${REF}: claim ${id} does not exist`); return ref.claims[id].confirmed === true; };
  const need = id => { if (!confirmed(id)) throw new Error(`${REF}: claim ${id} is used on the page but is not confirmed with a source`); };
  for (const id of MANDATORY) need(id);
  need(ref.uk.weeklyStart.claim); need(ref.uk.dailyBasketStart.claim); need(ref.uk.snapshotRows.claim);
  longDate(ref.uk.weeklyStart.date); longDate(ref.uk.dailyBasketStart.date);
  if (!WEEK_RE.test(ref.uk.weeklyStart.week) || ref.uk.weeklyStart.week !== uk.first) throw new Error(`${REF}: weeklyStart ${ref.uk.weeklyStart.week} is not the first UK index week ${uk.first}`);
  for (const [mk, m] of [["uk", uk], ["au", au]]) {
    for (const r of ref[mk].retailers) {
      if (!WEEK_RE.test(r.heldFrom)) throw new Error(`${REF}: ${r.id} has a bad heldFrom`);
      if (r.inIndex) {
        const have = [...(m.rows.get(r.id) || [])].sort();
        if (!have.length) throw new Error(`${REF}: ${r.id} is marked inIndex but the index has no rows for it`);
        if (have[0] !== r.heldFrom) throw new Error(`${REF}: ${r.id} heldFrom ${r.heldFrom} disagrees with the index (first week ${have[0]})`);
      } else {
        if (m.rows.has(r.id)) throw new Error(`${REF}: ${r.id} is marked not in the index but the index has rows for it`);
        if (!r.heldFromClaim) throw new Error(`${REF}: ${r.id} is outside the index and needs a heldFromClaim`);
        need(r.heldFromClaim);
      }
      if (r.heldThroughClaim) {
        confirmed(r.heldThroughClaim);
        if (!WEEK_RE.test(String(r.heldThrough)) || r.heldThrough < r.heldFrom) throw new Error(`${REF}: ${r.id} has a bad heldThrough`);
      }
      if (r.notHeldClaim) {
        const ok = confirmed(r.notHeldClaim);
        for (const w of r.notHeld || []) {
          if (!WEEK_RE.test(w)) throw new Error(`${REF}: ${r.id} has a bad notHeld week`);
          if (ok && !(ref.notices && ref.notices[w])) throw new Error(`${REF}: ${r.id} is shown as not holding ${w} but there is no notice for that week`);
        }
      }
    }
    // a week missing between the first and the latest published week must have a notice
    const have = new Set(m.weeks.map(w => w.week));
    for (const w of weeksBetween(m.first, m.latest.week)) if (!have.has(w) && !(ref.notices && ref.notices[w])) throw new Error(`${mk.toUpperCase()} index: week ${w} was not published and ${REF} has no notice for it`);
  }
  return { uk, au, ref, confirmed };
}

function seriesText(m) {
  const groups = [];
  for (const w of m.weeks) { const g = groups[groups.length - 1]; if (g && g.base === w.base) g.to = w.week; else groups.push({ base: w.base, from: w.week, to: w.week }); }
  const parts = groups.map(g => `base ${g.base} (${g.from === g.to ? g.from : `${g.from} to ${g.to}`})`);
  return groups.length === 1 ? `One series, ${parts[0]}.` : `${groups.length} series: ${parts.join("; ")}. Levels in different series cannot be compared.`;
}

function body(d) {
  const { uk, au, ref } = d;
  const notice = w => (ref.notices && ref.notices[w] ? `<a href="${esc(ref.notices[w])}">${esc(w)}</a>` : esc(w));
  const missing = m => { const have = new Set(m.weeks.map(w => w.week)); return weeksBetween(m.first, m.latest.week).filter(w => !have.has(w)); };
  const heldWeeks = (m, r) => [...(m.rows.get(r.id) || [])].filter(w => w >= r.heldFrom && w <= m.latest.week).length;
  let dash = false;
  const ukRow = r => {
    const idx = r.inIndex ? String(heldWeeks(uk, r)) : "not in the index yet";
    let nh = "&mdash;";
    if (r.notHeldClaim && d.confirmed(r.notHeldClaim)) nh = r.notHeld.length ? r.notHeld.map(notice).join(", ") : "none";
    else if (!r.inIndex && r.heldThroughClaim && d.confirmed(r.heldThroughClaim)) nh = "none";
    else dash = true;
    // weekly snapshots held: only from confirmed claims; otherwise a dash
    let held = null;
    if (r.inIndex) {
      if (r.notHeldClaim && d.confirmed(r.notHeldClaim)) held = String(weeksBetween(r.heldFrom, uk.latest.week).filter(w => !new Set(r.notHeld).has(w)).length);
    } else if (r.heldThroughClaim && d.confirmed(r.heldThroughClaim)) {
      held = `${weeksBetween(r.heldFrom, r.heldThrough).length} (${esc(r.heldFrom)} to ${esc(r.heldThrough)})`;
    }
    if (held === null) { held = "&mdash;"; dash = true; }
    return `<tr><td>${esc(r.name)}</td><td>${esc(r.heldFrom)}</td><td class="num">${held}</td><td class="num">${idx}</td><td>${nh}</td></tr>`;
  };
  const auRow = r => `<tr><td>${esc(r.name)}</td><td>${esc(r.heldFrom)}</td><td class="num">${heldWeeks(au, r)}</td></tr>`;
  const ukRows = ref.uk.retailers.map(ukRow).join("\n");
  const auRows = ref.au.retailers.map(auRow).join("\n");
  const idxRow = (label, link, m) => {
    const miss = missing(m);
    return `<tr><td><a href="${link}">${label}</a></td><td>${esc(m.first)}</td><td>${esc(m.latest.week)}</td><td class="num">${m.weeks.length}</td><td>${miss.length ? miss.map(notice).join(", ") : "none"}</td><td>${esc(seriesText(m))}</td></tr>`;
  };
  const allWeeks = [...new Set([...uk.weeks.map(w => w.week), ...au.weeks.map(w => w.week), ...weeksBetween(uk.first, uk.latest.week)])].sort();
  const cell = (m, w) => { const x = m.weeks.find(v => v.week === w); return x ? (x.matched === null ? "base week" : num(x.matched)) : "&mdash;"; };
  const matchRows = allWeeks.map(w => `<tr><td>${esc(w)}</td><td class="num">${cell(uk, w)}</td><td class="num">${cell(au, w)}</td></tr>`).join("\n");
  const start = longDate(ref.uk.weeklyStart.date), daily = longDate(ref.uk.dailyBasketStart.date);
  // sentences that follow the reference file, so they cannot go stale when a fact changes
  const gapWeeks = [...new Set(ref.uk.retailers.filter(r => r.notHeldClaim && d.confirmed(r.notHeldClaim)).flatMap(r => r.notHeld))].sort();
  const gapSentence = gapWeeks.length ? `The ${gapWeeks.length === 1 ? "gap" : "gaps"} in ${gapWeeks.map(notice).join(" and ")} ${gapWeeks.length === 1 ? "is" : "are"} explained in the linked ${gapWeeks.length === 1 ? "notice" : "notices"}. ` : "";
  const outside = ref.uk.retailers.filter(r => !r.inIndex);
  const outsideSentence = outside.map(r => `${esc(r.name)} is held from week ${Number(r.heldFrom.slice(6))} of ${esc(r.heldFrom.slice(0, 4))}${r.inIndex ? "" : " and is not yet in the index"}.`).join(" ");
  const outsideShort = outside.map(r => `${esc(r.name)} is held from week ${Number(r.heldFrom.slice(6))} of ${esc(r.heldFrom.slice(0, 4))}.`).join(" ");
  const actor = `With the includePriceHistory option, the search, category and product rows of our <a href="${AFF.withParam("https://apify.com/yappman/uk-supermarket-price-scraper?utm_source=data.yappman.com&amp;utm_medium=referral&amp;utm_campaign=coverage")}" rel="${AFF.REL}">UK Supermarket &amp; Grocery Prices</a> Actor on the Apify Store carry the product&rsquo;s weekly snapshot prices, newest first, up to 52 weeks, from ISO week 39 of 2026 (week 41 is missing at Tesco, Sainsbury&rsquo;s and Asda; there are none for Morrisons). The Actor builds no weekly report.${outside.length ? ` Price history is not offered for ${outside.map(r => esc(r.name)).join(" and ")} yet, so ${outside.length === 1 ? "its rows carry" : "their rows carry"} an empty price history and are never charged for it; the ${outside.map(r => esc(r.name)).join(" and ")} weekly snapshots we hold (from ${outside.map(r => esc(r.heldFrom)).join(" and ")}) are not yet part of that.` : ""}`;
  return `<header>
  <h1>How much history we hold</h1>
  <p class="sub">The weeks of shelf-price snapshots we hold, by retailer, and what exists before them. Weekly, not real time. These are posted online shelf prices, not prices paid.</p>
</header>
${AFF.DISCLOSURE_HTML}

<h2 id="short">The short answer</h2>
<p>Our weekly UK snapshots start with the collection of ${esc(start)} (ISO week ${esc(ref.uk.weeklyStart.week)}). The latest weekly release is ${esc(uk.latest.week)}, published ${esc(longDate(uk.latest.published))}. The Australian index starts with ${esc(au.first)}. The history is short: one week is added with each weekly release, and the tables below are rebuilt from the published index files, so this page cannot say more than the index does.</p>

<h2 id="uk">UK weekly snapshots, by retailer</h2>
<p><em>Held from</em> is the first weekly snapshot we hold for the retailer. <em>Weekly snapshots held</em> counts the weekly snapshots we hold, up to ${esc(uk.latest.week)}. <em>Weeks in the published index</em> counts the weeks that have figures for the retailer in the free index; a snapshot can be held without being in the index.</p>
<div class="table-wrap"><table><thead><tr><th>Retailer</th><th>Held from</th><th class="num">Weekly snapshots held</th><th class="num">Weeks in the published index</th><th>Weekly snapshot not held</th></tr></thead><tbody>
${ukRows}
</tbody></table></div>
${dash ? "<p class=\"meta\">A dash means this page does not state the figure.</p>\n" : ""}<p>${gapSentence}${outsideSentence}</p>

<h2 id="au">Australian weekly snapshots, by retailer</h2>
<div class="table-wrap"><table><thead><tr><th>Retailer</th><th>Held from</th><th class="num">Weeks in the published index</th></tr></thead><tbody>
${auRows}
</tbody></table></div>

<h2 id="index">Published index weeks</h2>
<div class="table-wrap"><table><thead><tr><th>Index</th><th>First published week</th><th>Latest published week</th><th class="num">Weeks published</th><th>Weeks not published</th><th>Series</th></tr></thead><tbody>
${idxRow("UK Online Shelf-Price Index", "/shelf-price-index/", uk)}
${idxRow("AU Online Shelf-Price Index", "/au-shelf-price-index/", au)}
</tbody></table></div>
<p>The free index and its files are released under <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>; the stable addresses are on the <a href="/data/v1/">index files page</a>, and how the index is built is on the <a href="/shelf-price-index/method/">method page</a>.</p>

<h2 id="products">How many products each week</h2>
<p>${esc(ref.uk.snapshotRows.sentence)} Matched products are those found in both weeks with a price; the table gives the headline count for each published week.</p>
<div class="table-wrap"><table><thead><tr><th>Week</th><th class="num">UK matched products</th><th class="num">AU matched products</th></tr></thead><tbody>
${matchRows}
</tbody></table></div>

<h2 id="before">Why there is nothing earlier</h2>
<p>We began collecting the weekly UK snapshots on ${esc(start)} and the daily basket on ${esc(daily)} (it has no run on 25 September). Nothing was collected before those dates, so there are no earlier weeks to supply, and we do not estimate or backfill them. ${outsideShort}</p>

<h2 id="daily">The daily basket</h2>
<p>The daily 212-item basket is a public dataset under CC BY 4.0, with history from ${esc(daily)}; a monthly snapshot of it is also on Kaggle.</p>

<h2 id="product-level">Product-level weeks</h2>
<p>${actor}</p>

<p>Retailer names are used only to describe the source of public product information; no affiliation, endorsement or partnership is claimed. Shelf prices only; not CPI and not a measure of prices paid. How the snapshots are checked is on the <a href="/data-quality/">data quality</a> page.</p>
`;
}

function build(root) {
  const d = load(root);
  const raw = fs.readFileSync(path.join(root, TEMPLATE), "utf8").replace(/\r\n/g, "\n");
  const [head0, rest] = raw.split("<main id=\"main\" tabindex=\"-1\">\n");
  if (!rest || !rest.includes("</main>\n")) throw new Error(`${TEMPLATE}: not the expected page shape`);
  const foot = rest.split("</main>\n").slice(1).join("</main>\n");
  const title = "How much history we hold", desc = "The weeks of UK and Australian shelf-price snapshots we hold, by retailer, the weeks not held, and why nothing earlier exists. Weekly, not real time.";
  const lines = head0.split("\n");
  const set = (start, v) => { const i = lines.findIndex(l => l.startsWith(start)); if (i < 0) throw new Error("template line missing: " + start); lines[i] = v; };
  set("<title>", `<title>${esc(title)} — Yappman Data</title>`);
  set("<meta name=\"description\"", `<meta name="description" content="${esc(desc)}">`);
  set("<meta property=\"og:title\"", `<meta property="og:title" content="${esc(title)} — Yappman Data">`);
  set("<meta property=\"og:description\"", `<meta property="og:description" content="${esc(desc)}">`);
  set("<meta property=\"og:url\"", `<meta property="og:url" content="${SITE}/coverage/">`);
  set("<link rel=\"canonical\"", `<link rel="canonical" href="${SITE}/coverage/">`);
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

module.exports = { build, check, write, load, weekOf, weekMonday, weeksBetween, OUT, REF };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", doCheck = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--check") doCheck = true;
    else if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  try {
    if (doCheck) { const bad = check(root); if (bad.length) { console.error(bad.join("\n")); process.exit(1); } console.log("the coverage page agrees with the data files"); }
    else { write(root, build(root)); console.log("wrote " + OUT); }
  } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
}
