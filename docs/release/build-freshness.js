#!/usr/bin/env node
// Builds the freshness file and badges for the two free weekly indices, from files already on this site:
//   data/freshness.json, badges/uk-shelf-price-index.svg, badges/au-shelf-price-index.svg
//
//   node docs/release/build-freshness.js [--root DIR] [--today YYYY-MM-DD] [--max-age-days N]    write the three files
//   node docs/release/build-freshness.js --check [--root DIR]                                      fail unless they equal a rebuild
//
// Inputs (read only): data/uk-shelf-price-index-headline.json and data/au-shelf-price-index.json, the same files the index pages read.
// For each, the newest headline row: its week (vintage) and the date it was published (publishedAt). Nothing else is read or written:
// no level, no counts, no register data, no run, store, task or user ids; no network, no token, no clock in the output.
// The output depends only on the inputs, so a rerun gives byte-identical files. The date is the day the week's figures were published
// (weekly resolution, not real time); a published week can rest on incomplete retailer data, as the notices say, so the badge states a
// date, never "OK" or "live", and its colour never means healthy or stale.
// Build rules: a missing or malformed week or date stops the build; a date in the future, or older than --max-age-days (default 21)
// compared with --today (default: today, UTC), stops it too. --check does not look at the clock: it only compares files.
// Run it in the same commit as the weekly stamp (docs/release/index-publish-checklist.md).
"use strict";
const fs = require("fs");
const path = require("path");

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;
const ISO_RE = /^(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;
const DATASETS = [
  { id: "uk-shelf-price-index", title: "UK Online Shelf-Price Index", label: "UK shelf prices", source: "data/uk-shelf-price-index-headline.json", page: "https://data.yappman.com/shelf-price-index/", files: ["https://data.yappman.com/data/uk-shelf-price-index.csv", "https://data.yappman.com/data/uk-shelf-price-index.json"] },
  { id: "au-shelf-price-index", title: "AU Online Shelf-Price Index", label: "AU shelf prices", source: "data/au-shelf-price-index.json", page: "https://data.yappman.com/au-shelf-price-index/", files: ["https://data.yappman.com/data/au-shelf-price-index.json"] },
];
const OUT_JSON = "data/freshness.json";
const badgePath = id => `badges/${id}.svg`;

const realDate = d => { const t = new Date(d + "T00:00:00Z"); return /^\d{4}-\d{2}-\d{2}$/.test(d) && !isNaN(t) && t.toISOString().slice(0, 10) === d; };
const dayNumber = d => Math.round(new Date(d + "T00:00:00Z").getTime() / 86400000);
const longDate = d => { const [y, m, dd] = d.split("-").map(Number); return `${dd} ${MONTHS[m - 1]} ${y}`; };
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

// -> { id, title, isoWeek, publishedAt (yyyy-mm-dd), ... } for one dataset, validated.
function latest(root, ds, today, maxAge) {
  let rows;
  try { rows = JSON.parse(fs.readFileSync(path.join(root, ds.source), "utf8")); } catch (e) { throw new Error(`${ds.source}: cannot be read as JSON (${e.code || e.message})`); }
  if (!Array.isArray(rows)) throw new Error(`${ds.source}: not an array`);
  const heads = rows.filter(r => r && r.recordType === "headline");
  if (!heads.length) throw new Error(`${ds.source}: no headline row`);
  for (const h of heads) if (typeof h.vintage !== "string" || !WEEK_RE.test(h.vintage)) throw new Error(`${ds.source}: a headline row has no valid week`);
  heads.sort((a, b) => (a.vintage < b.vintage ? -1 : a.vintage > b.vintage ? 1 : 0));
  const h = heads[heads.length - 1];
  const m = ISO_RE.exec(String(h.publishedAt || ""));
  if (!m || !realDate(m[1])) throw new Error(`${ds.source}: ${h.vintage} has no valid publishedAt`);
  const date = m[1];
  if (today !== null) {
    if (date > today) throw new Error(`${ds.source}: ${h.vintage} is published on ${date}, in the future`);
    if (dayNumber(today) - dayNumber(date) > maxAge) throw new Error(`${ds.source}: the latest week ${h.vintage} was published ${dayNumber(today) - dayNumber(date)} days ago, more than ${maxAge}`);
  }
  return { dataset: ds.id, title: ds.title, isoWeek: h.vintage, publishedAt: date, page: ds.page, files: ds.files };
}

function svg(ds, d) {
  const value = `${d.isoWeek} · ${longDate(d.publishedAt)}`;
  const lw = Math.round(ds.label.length * 7.2 + 16), vw = Math.round(value.length * 7.2 + 16), w = lw + vw; // generous: Verdana digits are about 7px at 11px
  const title = `${ds.title}: latest published week ${d.isoWeek}, published ${longDate(d.publishedAt)}`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="20" role="img" aria-label="${esc(title)}">\n`
    + `<title>${esc(title)}</title>\n`
    + `<rect width="${lw}" height="20" fill="#3c4a5a"/><rect x="${lw}" width="${vw}" height="20" fill="#5a6c80"/>\n`
    + `<g fill="#ffffff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">`
    + `<text x="${Math.round(lw / 2)}" y="14">${esc(ds.label)}</text><text x="${lw + Math.round(vw / 2)}" y="14">${esc(value)}</text></g>\n</svg>\n`;
}

function build(root, today, maxAge) {
  const items = DATASETS.map(ds => ({ ds, d: latest(root, ds, today, maxAge) }));
  const newest = items.map(i => i.d.publishedAt).sort().pop();
  const json = JSON.stringify({
    schema: 1,
    note: "The date is the day each weekly index published its latest week. Weekly series, not real time. A published week can rest on incomplete retailer data; see https://data.yappman.com/notices/.",
    latestPublishedAt: newest,
    datasets: items.map(i => i.d),
  }, null, 2) + "\n";
  const files = new Map([[OUT_JSON, json]]);
  for (const i of items) files.set(badgePath(i.ds.id), svg(i.ds, i.d));
  return files;
}

function check(root) {
  const want = build(root, null, 0);
  const bad = [];
  for (const [f, s] of want) {
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
  } finally { for (const [, t] of tmp) { try { if (fs.existsSync(t)) fs.unlinkSync(t); } catch { /* left for the caller to see in git status */ } } }
}

function parseArgs(args) {
  const o = {};
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "--check") { o.check = true; continue; }
    if (!["--root", "--today", "--max-age-days"].includes(a)) throw new Error("unknown argument " + a);
    if (args[i + 1] === undefined || args[i + 1].startsWith("--")) throw new Error(`${a} needs a value`);
    o[a.slice(2)] = args[++i];
  }
  if (o.today !== undefined && !realDate(o.today)) throw new Error("--today must be a real YYYY-MM-DD date");
  if (o["max-age-days"] !== undefined && !/^\d{1,3}$/.test(o["max-age-days"])) throw new Error("--max-age-days must be a whole number");
  return o;
}

module.exports = { build, check, write, parseArgs, latest, svg, DATASETS, OUT_JSON, badgePath };

if (require.main === module) {
  let o;
  try { o = parseArgs(process.argv.slice(2)); } catch (e) { console.error("usage error: " + e.message); process.exit(2); }
  const root = o.root || ".";
  try {
    if (o.check) {
      const bad = check(root);
      if (bad.length) { console.error(bad.join("\n")); process.exit(1); }
      console.log("freshness files agree with the data files");
    } else {
      const files = build(root, o.today || new Date().toISOString().slice(0, 10), Number(o["max-age-days"] ?? 21));
      write(root, files);
      console.log("wrote " + [...files.keys()].join(", "));
    }
  } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
}
