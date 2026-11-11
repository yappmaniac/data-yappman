#!/usr/bin/env node
// Builds the Atom feed of the weekly largest category moves in the UK Online Shelf-Price Index: shelf-price-index/moves.xml
//
//   node docs/release/build-moves-feed.js [--root DIR]         write the feed
//   node docs/release/build-moves-feed.js --check [--root DIR]   fail unless it equals a rebuild
//
// Input (read only): data/uk-shelf-price-index.json, the free index file. One entry per published week with a week-on-week change
// (base weeks have none), newest first, at most MAX_ENTRIES. Each entry: the headline level and change, and the largest rises and falls
// among the categories, chosen exactly as /this-week/ chooses them: category rows with status ok and at least MIN_MATCHED matched
// products, the TOP_MOVES largest each way plus any tied with the last. Dates are the weeks' own publication times, so a rebuild is
// byte-identical. No network, no clock.
"use strict";
const fs = require("fs");
const path = require("path");

const OUT = "shelf-price-index/moves.xml";
const SRC = "data/uk-shelf-price-index.json";
const SITE = "https://data.yappman.com";
const MIN_MATCHED = 100, TOP_MOVES = 3, MAX_ENTRIES = 26;
const WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;
const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
const CLASS_RE = /^[a-z][a-z0-9-]{0,40}$/;
const xml = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const pct = v => (Math.abs(v) < 0.005 ? "0.00" : (v > 0 ? "+" : "-") + Math.abs(v).toFixed(2)) + "%";
const isNum = v => typeof v === "number" && isFinite(v);

function top(ordered) {
  if (ordered.length <= TOP_MOVES) return ordered;
  const cut = ordered[TOP_MOVES - 1].weekOnWeekPct;
  return ordered.slice(0, TOP_MOVES).concat(ordered.slice(TOP_MOVES).filter(r => r.weekOnWeekPct === cut));
}

function weeks(items) {
  if (!Array.isArray(items)) throw new Error(`${SRC}: not an array`);
  const out = [];
  // Each week's base week (the two series are not joined), and the current category list: a row of any other class, such as the
  // "food and soft drinks" row weeks 39 and 40 carried before it became a subtotal, is left out.
  const metas = items.filter(r => r && r.recordType === "meta" && WEEK_RE.test(String(r.vintage))).sort((a, b) => (a.vintage < b.vintage ? -1 : 1));
  if (!metas.length) throw new Error(`${SRC}: no meta item`);
  const base = {};
  for (const m of metas) { if (!WEEK_RE.test(String(m.base))) throw new Error(`${SRC}: the meta item of ${m.vintage} has no valid base`); base[m.vintage] = m.base; }
  const current = metas[metas.length - 1].classes;
  if (!Array.isArray(current) || !current.length) throw new Error(`${SRC}: the latest meta item lists no classes`);
  const heads = items.filter(r => r && r.recordType === "headline" && r.status === "ok");
  for (const h of heads) {
    if (!WEEK_RE.test(String(h.vintage)) || !ISO_RE.test(String(h.publishedAt)) || !isNum(h.level) || !isNum(h.weekOnWeekPct)) throw new Error(`${SRC}: a headline row is malformed`);
    if (!(h.vintage in base)) throw new Error(`${SRC}: ${h.vintage} has no meta item`);
    const classes = items.filter(r => r && r.recordType === "class" && r.vintage === h.vintage && r.status === "ok" && current.includes(r.class));
    for (const r of classes) if (!CLASS_RE.test(String(r.class)) || !isNum(r.weekOnWeekPct) || !Number.isInteger(r.matched)) throw new Error(`${SRC}: a category row of ${h.vintage} is malformed`);
    const big = classes.filter(r => r.matched >= MIN_MATCHED);
    const up = top(big.filter(r => r.weekOnWeekPct > 0).sort((a, b) => b.weekOnWeekPct - a.weekOnWeekPct || (a.class < b.class ? -1 : 1)));
    const down = top(big.filter(r => r.weekOnWeekPct < 0).sort((a, b) => a.weekOnWeekPct - b.weekOnWeekPct || (a.class < b.class ? -1 : 1)));
    out.push({ week: h.vintage, base: base[h.vintage], published: h.publishedAt, level: h.level, wow: h.weekOnWeekPct, up, down });
  }
  if (new Set(out.map(w => w.week)).size !== out.length) throw new Error(`${SRC}: a week has more than one headline row`);
  return out.sort((a, b) => (a.week < b.week ? 1 : -1)).slice(0, MAX_ENTRIES);
}

function entry(w) {
  const list = rows => (rows.length ? rows.map(r => `${r.class.replace(/-/g, " ")} ${pct(r.weekOnWeekPct)} (${r.matched.toLocaleString("en-GB")} matched products)`).join("; ") : "none this week");
  const html = `<p>UK Online Shelf-Price Index, week ${w.week}: headline level ${w.level.toFixed(1)} (base 100 at ${w.base}), ${pct(w.wow)} on the week before.</p>`
    + `<p>Largest category rises (categories with at least ${MIN_MATCHED} matched products): ${list(w.up)}.</p>`
    + `<p>Largest category falls: ${list(w.down)}.</p>`
    + `<p>Levels from different base weeks are not comparable: the series restarted at week 42, and earlier entries use an earlier base. Shelf prices only; not CPI and not a measure of prices paid. Source: Yappman Data, UK Online Shelf-Price Index, CC BY 4.0, vintage ${w.week}, ${SITE}/shelf-price-index/</p>`;
  return `  <entry>
    <id>tag:data.yappman.com,2026:uk-shelf-price-index/${w.week}</id>
    <title>UK shelf prices, ${w.week}: headline ${pct(w.wow)} on the week</title>
    <link rel="alternate" type="text/html" href="${SITE}/shelf-price-index/"/>
    <published>${w.published}</published>
    <updated>${w.published}</updated>
    <content type="html">${xml(html)}</content>
  </entry>
`;
}

function build(root) {
  let items;
  try { items = JSON.parse(fs.readFileSync(path.join(root, SRC), "utf8")); } catch (e) { throw new Error(`${SRC}: cannot be read as JSON (${e.code || e.message})`); }
  const ws = weeks(items);
  if (!ws.length) throw new Error(`${SRC}: no published week with a change`);
  const feed = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>tag:data.yappman.com,2026:uk-shelf-price-index-moves</id>
  <title>UK Online Shelf-Price Index: weekly largest category moves</title>
  <subtitle>The headline change and the largest category rises and falls each published week. Shelf prices only; not CPI.</subtitle>
  <link rel="self" type="application/atom+xml" href="${SITE}/${OUT}"/>
  <link rel="alternate" type="text/html" href="${SITE}/shelf-price-index/"/>
  <updated>${ws[0].published}</updated>
  <author><name>Yappman Data</name><uri>${SITE}/</uri></author>
  <rights>CC BY 4.0, https://creativecommons.org/licenses/by/4.0/. Cite as Yappman Data, UK Online Shelf-Price Index.</rights>
${ws.map(entry).join("")}</feed>
`;
  return new Map([[OUT, feed]]);
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
  for (const [f, s] of files) { const p = path.join(root, f); const t = p + ".stamp-tmp"; fs.writeFileSync(t, s); fs.renameSync(t, p); }
}

module.exports = { build, check, write, weeks, OUT, SRC, MIN_MATCHED, TOP_MOVES };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", doCheck = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--check") doCheck = true;
    else if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  try {
    if (doCheck) { const bad = check(root); if (bad.length) { console.error(bad.join("\n")); process.exit(1); } console.log("the moves feed agrees with the data file"); }
    else { write(root, build(root)); console.log("wrote " + OUT); }
  } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
}
