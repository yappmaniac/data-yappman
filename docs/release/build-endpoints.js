#!/usr/bin/env node
// Builds the stable, versioned copies of the free index files under data/v1/, and their manifest.
//
//   node docs/release/build-endpoints.js [--root DIR]      write data/v1/*
//   node docs/release/build-endpoints.js --check [--root DIR]   fail unless data/v1/* equals a rebuild
//
// Inputs (read only), the files the index pages and build-index-files.js already keep:
//   data/uk-shelf-price-index.csv, data/uk-shelf-price-index.json, data/au-shelf-price-index.json
// Outputs (the v1 contract; the older paths under data/ stay as they are):
//   data/v1/uk-shelf-price-index.csv and .json   byte copies of the inputs
//   data/v1/au-shelf-price-index.json            a byte copy of the input
//   data/v1/au-shelf-price-index.csv             derived from the AU JSON: the rows only (no meta items), the 12 core columns in the UK
//                                                column order plus a last column, base, from the vintage's meta item; empty for null;
//                                                numbers as JSON prints them (1 stays 1); no field is ever quoted, so a text field that
//                                                is not a plain name stops the build
//   data/v1/manifest.json                        schema, version, per dataset the latest week, its publication date, the row count, and
//                                                for each file its path, size and SHA-256. No clock: a rerun is byte-identical.
// Run it in the same commit as each weekly release, after build-index-files.js (docs/release/index-publish-checklist.md).
// Only fs, path and crypto; no network, no token, no child process.
"use strict";
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const V1 = "data/v1";
const SRC = { ukCsv: "data/uk-shelf-price-index.csv", ukJson: "data/uk-shelf-price-index.json", auJson: "data/au-shelf-price-index.json" };
const AU_COLUMNS = ["vintage", "publishedAt", "revision", "recordType", "retailer", "class", "level", "weekOnWeekPct", "fourWeekPct", "matched", "matchedShare", "status", "base"];
const NAME_RE = /^[a-z][a-z0-9_-]{0,40}$/;
const WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;
const sha = buf => crypto.createHash("sha256").update(buf).digest("hex");
// Line endings: a Windows checkout can hold CRLF while the committed (and served) file is LF, so every file is read as LF.
const lf = buf => Buffer.from(buf.toString("utf8").replace(/\r\n/g, "\n"), "utf8");
const read = (root, f) => { try { return lf(fs.readFileSync(path.join(root, f))); } catch (e) { throw new Error(`${f}: cannot be read (${e.code || e.message})`); } };

function auCsv(items) {
  const lines = [AU_COLUMNS.join(",")];
  let base = null, n = 0;
  for (const it of items) {
    if (!it || typeof it !== "object") throw new Error("data/au-shelf-price-index.json: an item is not an object");
    if (it.recordType === "meta") { if (!WEEK_RE.test(String(it.base))) throw new Error(`the AU meta item for ${it.vintage} has no valid base week`); base = it.base; continue; }
    if (base === null) throw new Error("data/au-shelf-price-index.json: a row before the first meta item");
    const f = AU_COLUMNS.map(k => {
      const v = k === "base" ? base : it[k];
      if (v === null || v === undefined) return "";
      if (typeof v === "number") { if (!isFinite(v)) throw new Error(`row ${n + 1}: ${k} is not finite`); return String(v); }
      if (typeof v !== "string") throw new Error(`row ${n + 1}: ${k} is not text or a number`);
      if (v !== "" && !NAME_RE.test(v) && !/^\d{4}-W\d{2}$/.test(v) && !/^\d{4}-\d{2}-\d{2}T[0-9:.]+(Z|[+-]\d{2}:\d{2})$/.test(v) && !WEEK_RE.test(v)) throw new Error(`row ${n + 1}: ${k} "${v.slice(0, 20)}" is not a plain name, week or date`);
      return v;
    });
    lines.push(f.join(",")); n++;
  }
  if (!n) throw new Error("data/au-shelf-price-index.json: no rows");
  return { text: lines.join("\n") + "\n", rows: n };
}

function summary(id, items, files) {
  const heads = items.filter(r => r && r.recordType === "headline" && WEEK_RE.test(String(r.vintage))).sort((a, b) => (a.vintage < b.vintage ? -1 : 1));
  if (!heads.length) throw new Error(`${id}: no headline row`);
  const h = heads[heads.length - 1];
  const m = /^(\d{4}-\d{2}-\d{2})T/.exec(String(h.publishedAt || ""));
  if (!m) throw new Error(`${id}: ${h.vintage} has no publishedAt`);
  return { id, latestVintage: h.vintage, publishedAt: m[1], vintages: new Set(items.filter(r => r && r.recordType === "meta").map(r => r.vintage)).size, rows: items.filter(r => r && r.recordType !== "meta").length, files };
}

function build(root) {
  const ukCsv = read(root, SRC.ukCsv), ukJson = read(root, SRC.ukJson), auJson = read(root, SRC.auJson);
  const parse = (b, f) => { try { const j = JSON.parse(b.toString("utf8")); if (!Array.isArray(j)) throw new Error("not an array"); return j; } catch (e) { throw new Error(`${f}: ${e.message}`); } };
  const uk = parse(ukJson, SRC.ukJson), au = parse(auJson, SRC.auJson);
  const { text: auCsvText, rows: auRows } = auCsv(au);
  const out = new Map([
    [`${V1}/uk-shelf-price-index.csv`, ukCsv], [`${V1}/uk-shelf-price-index.json`, ukJson],
    [`${V1}/au-shelf-price-index.csv`, Buffer.from(auCsvText, "utf8")], [`${V1}/au-shelf-price-index.json`, auJson],
  ]);
  const fileInfo = ids => ids.map(f => ({ path: "/" + f, bytes: out.get(f).length, sha256: sha(out.get(f)) }));
  const ukRows = uk.filter(r => r.recordType !== "meta").length;
  const manifest = {
    schema: 1, version: "v1",
    note: "Free index files, CC BY 4.0. Rows keep their meaning and column order within v1; new columns are added at the end. A change that would break a reader is announced on https://data.yappman.com/notices/ before it ships and will normally use a new path. Weekly series, not real time.",
    datasets: [
      { ...summary("uk-shelf-price-index", uk, fileInfo([`${V1}/uk-shelf-price-index.csv`, `${V1}/uk-shelf-price-index.json`])), page: "https://data.yappman.com/shelf-price-index/" },
      { ...summary("au-shelf-price-index", au, fileInfo([`${V1}/au-shelf-price-index.csv`, `${V1}/au-shelf-price-index.json`])), page: "https://data.yappman.com/au-shelf-price-index/" },
    ],
  };
  if (manifest.datasets[0].rows !== ukRows || manifest.datasets[1].rows !== auRows) throw new Error("row counts disagree");
  out.set(`${V1}/manifest.json`, Buffer.from(JSON.stringify(manifest, null, 2) + "\n", "utf8"));
  return out;
}

function check(root) {
  const bad = [];
  for (const [f, buf] of build(root)) {
    const p = path.join(root, f);
    if (!fs.existsSync(p)) bad.push(`${f} does not exist; run the build`);
    else {
      const same = Buffer.compare(lf(fs.readFileSync(p)), buf) === 0;
      if (!same) bad.push(`${f} is not what the data files give; run the build`);
    }
  }
  return bad;
}

function write(root, files) {
  const tmp = [];
  try {
    for (const [f, b] of files) { const p = path.join(root, f); fs.mkdirSync(path.dirname(p), { recursive: true }); const t = p + ".stamp-tmp"; tmp.push([p, t]); fs.writeFileSync(t, b); }
    for (const [p, t] of tmp) fs.renameSync(t, p);
  } finally { for (const [, t] of tmp) { try { if (fs.existsSync(t)) fs.unlinkSync(t); } catch { /* shows in git status */ } } }
}

module.exports = { build, check, write, auCsv, V1, SRC, AU_COLUMNS };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", doCheck = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--check") doCheck = true;
    else if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  try {
    if (doCheck) { const bad = check(root); if (bad.length) { console.error(bad.join("\n")); process.exit(1); } console.log("data/v1 agrees with the data files"); }
    else { const files = build(root); write(root, files); console.log("wrote " + [...files.keys()].join(", ")); }
  } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
}
