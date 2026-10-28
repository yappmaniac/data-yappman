#!/usr/bin/env node
// Validates the Christmas basket summary record (schema 1) and prints it re-serialised.
// Usage: node docs/release/validate-basket-summary.js <record.json> [<current copy.json>]
// Exits non-zero, printing nothing to stdout, if the record is invalid or older than the current copy.
"use strict";
const fs = require("fs");

const MAX_BYTES = 65536;
const RETAILERS = ["tesco", "sainsburys", "asda", "aldi"];
const ITEMS = new Set([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 28]);
const FLAGS = new Set(["fresh", "frozen", "size-differs", "pack-changed", "optional",
  "gap:no-line", "gap:held", "gap:not-priced", "gap:blocked", "gap:implausible"]);
const REASONS = new Set(["no-line", "held", "not-priced", "blocked", "implausible"]);
// UTC timestamps only, for example 2026-10-28T05:45:41Z or 2026-10-28T05:45:41.123Z.
const ISO_UTC = /^20\d\d-[01]\d-[0-3]\dT[0-2]\d:[0-5]\d:[0-5]\d(\.\d{1,3})?Z$/;
const isoTime = v => typeof v === "string" && v.length <= 24 && ISO_UTC.test(v) && isFinite(Date.parse(v));

function fail(msg) { process.stderr.write("invalid: " + msg + "\n"); process.exit(1); }
const isObj = v => v !== null && typeof v === "object" && !Array.isArray(v);
const keysOnly = (o, allowed, where) => Object.keys(o).forEach(k => { if (!allowed.includes(k)) fail(`${where}: unexpected key ${JSON.stringify(k)}`); });
const money = (v, max, where, nullable) => {
  if (v === null && nullable) return;
  if (typeof v !== "number" || !isFinite(v) || v < 0 || v > max || Math.round(v * 100) !== v * 100 && Math.abs(Math.round(v * 100) - v * 100) > 1e-6) fail(`${where}: bad amount ${v}`);
};
const count = (v, where) => { if (!Number.isInteger(v) || v < 0 || v > 27) fail(`${where}: bad count ${v}`); };

const raw = fs.readFileSync(process.argv[2]);
if (raw.length > MAX_BYTES) fail(`record is ${raw.length} bytes, over ${MAX_BYTES}`);
let rec;
try { rec = JSON.parse(raw.toString("utf8")); } catch (e) { fail("not JSON"); }
if (!isObj(rec)) fail("not an object");
keysOnly(rec, ["schema", "updated", "weeks", "gaps"], "record");
if (rec.schema !== 1) fail("schema is not 1");
if (!isoTime(rec.updated)) fail("updated is not a UTC timestamp");
const updated = Date.parse(rec.updated);
if (updated > Date.now() + 3600e3) fail("updated is in the future");
if (!Array.isArray(rec.weeks) || rec.weeks.length < 1 || rec.weeks.length > 9) fail("weeks must hold 1 to 9 entries");
const seen = new Set();
rec.weeks.forEach((w, i) => {
  const at = `weeks[${i}]`;
  if (!isObj(w)) fail(at + " not an object");
  keysOnly(w, ["week", "asOf", "appliedAt", "commonItems", "commonTotal", "byRetailer", "items"], at);
  if (typeof w.week !== "string" || !/^20\d\d-W\d\d$/.test(w.week) || seen.has(w.week)) fail(at + ": bad or repeated week");
  seen.add(w.week);
  if (typeof w.asOf !== "string" || !/^20\d\d-\d\d-\d\d$/.test(w.asOf)) fail(at + ": bad asOf");
  if (w.appliedAt !== undefined && !isoTime(w.appliedAt)) fail(at + ": bad appliedAt");
  count(w.commonItems, at + ".commonItems");
  if (!isObj(w.commonTotal)) fail(at + ".commonTotal missing");
  keysOnly(w.commonTotal, RETAILERS, at + ".commonTotal");
  RETAILERS.forEach(r => money(w.commonTotal[r], 10000, `${at}.commonTotal.${r}`, false));
  if (!isObj(w.byRetailer)) fail(at + ".byRetailer missing");
  keysOnly(w.byRetailer, RETAILERS, at + ".byRetailer");
  RETAILERS.forEach(r => {
    const b = w.byRetailer[r];
    if (!isObj(b)) fail(`${at}.byRetailer.${r} missing`);
    keysOnly(b, ["total", "itemsPriced"], `${at}.byRetailer.${r}`);
    money(b.total, 10000, `${at}.byRetailer.${r}.total`, false);
    count(b.itemsPriced, `${at}.byRetailer.${r}.itemsPriced`);
  });
  if (!Array.isArray(w.items) || w.items.length > 27) fail(at + ".items must be a list of at most 27");
  const ns = new Set();
  w.items.forEach((it, j) => {
    const a = `${at}.items[${j}]`;
    if (!isObj(it)) fail(a + " not an object");
    keysOnly(it, ["n", ...RETAILERS, "flags"], a);
    if (!ITEMS.has(it.n) || ns.has(it.n)) fail(a + ": bad or repeated item number");
    ns.add(it.n);
    RETAILERS.forEach(r => money(it[r] === undefined ? null : it[r], 1000, `${a}.${r}`, true));
    if (it.flags !== undefined) {
      if (!isObj(it.flags)) fail(a + ".flags not an object");
      keysOnly(it.flags, RETAILERS, a + ".flags");
      Object.entries(it.flags).forEach(([r, list]) => {
        if (!Array.isArray(list) || list.some(f => !FLAGS.has(f))) fail(`${a}.flags.${r}: unknown flag`);
      });
    }
  });
});
if (rec.gaps !== undefined) {
  if (!Array.isArray(rec.gaps) || rec.gaps.length > 108) fail("gaps must be a list of at most 108");
  rec.gaps.forEach((g, i) => {
    if (!isObj(g)) fail(`gaps[${i}] not an object`);
    keysOnly(g, ["n", "retailer", "reason"], `gaps[${i}]`);
    if (!ITEMS.has(g.n) || !RETAILERS.includes(g.retailer) || !REASONS.has(g.reason)) fail(`gaps[${i}]: bad entry`);
  });
}
// Never replace a newer copy with an older record.
if (process.argv[3] && fs.existsSync(process.argv[3])) {
  try {
    const cur = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
    const curUpdated = Date.parse(cur.updated);
    if (isFinite(curUpdated) && updated < curUpdated) fail("record is older than the current copy");
    if (Array.isArray(cur.weeks) && rec.weeks.length < cur.weeks.length) fail("record has fewer weeks than the current copy");
  } catch (e) { if (e && e.code) throw e; }
}
process.stdout.write(JSON.stringify(rec) + "\n");
