// Stamp the latest PUBLISHED index figures into the static HTML of the UK and AU index pages (and JSON-LD dateModified).
//
//   node docs/release/stamp-latest.js --uk FILE --confirm-uk 2026-W43 [--au FILE --confirm-au 2026-W42] [--date YYYY-MM-DD] [--root DIR]
//   node docs/release/stamp-latest.js --check            (fails unless BOTH pages are stamped)
//
// FILE is the public vintage file the publish tool writes locally ({"meta": {...}, "rows": [...]}), AFTER the dataset
// has been checked to hold that vintage. Because the publish tool also writes these files in a dry run, the file alone does
// not prove publication: the operator must pass --confirm-uk / --confirm-au with the vintage, as an assertion that the public
// dataset holds it (the same idea as --confirm-vintage in the publish tool).
//
// Units: weekOnWeekPct and fourWeekPct are stored already in percent (GroceryPricesActor tools/indices/core.py:913-914,
// "(relative - 1) * 100"), and the page script prints them with toFixed(2) + "%", the level with toFixed(1); this script does the same.
//
// Safety rules (each is tested in docs/release/stamp-latest.test.js):
//  - the vintage must match the confirmation, be a well-formed ISO week (W01-W53), and not be older than the one already stamped;
//  - the file needs a meta item for that vintage (revision 1, licence CC BY 4.0, the right title) and exactly one headline
//    row with status ok or base and a finite level; nothing is imputed, so a skipped, held or insufficient week cannot be stamped;
//  - publishedAt must be a strict ISO date (optionally with a time), a real date, not in the future;
//  - every inserted value is validated as a number, an ISO week or a date and then escaped;
//  - the page needs exactly ONE JSON-LD block whose top level is the Dataset object for that index, and the re-parsed
//    output must carry the new dateModified;
//  - atomic: everything is checked in memory first; the files are then written to temporary names and renamed, with a
//    rollback of the renamed ones if a rename fails; no network, no eval, no child processes (only fs and path);
//  - the wording is "latest published", never "current" or "live".
// Two dates are written: dateModified = the vintage's publishedAt date, and the sitemap lastmod = --date (default today).
const fs = require("fs");
const path = require("path");

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MARK_RE = /<!--static-latest:start-->\n([\s\S]*?)\n<!--static-latest:end-->/;
const WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;
const ISO_RE = /^(\d{4}-\d{2}-\d{2})(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/;
const PAGES = {
  uk: { file: "shelf-price-index/index.html", sitemap: "shelf-price-index/", title: "UK Online Shelf-Price Index" },
  au: { file: "au-shelf-price-index/index.html", sitemap: "au-shelf-price-index/", title: "AU Online Shelf-Price Index" },
};
const KNOWN_FLAGS = new Set(["uk", "au", "confirm-uk", "confirm-au", "date", "root", "check"]);

const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const realDate = d => { const t = new Date(d + "T00:00:00Z"); return /^\d{4}-\d{2}-\d{2}$/.test(d) && !isNaN(t) && t.toISOString().slice(0, 10) === d; };
const longDate = d => { const [y, m, dd] = d.split("-").map(Number); return `${dd} ${MONTHS[m - 1]} ${y}`; };
const num = (v, name) => { if (typeof v !== "number" || !isFinite(v)) throw new Error(`${name} is not a finite number`); return v; };
const signed = (v, digits) => { const t = Math.abs(v).toFixed(digits); return (Number(t) === 0 ? "" : v > 0 ? "+" : "-") + t + "%"; };

function buildBlock(market, data, vintage, today) {
  const spec = PAGES[market];
  if (!WEEK_RE.test(vintage)) throw new Error(`${market}: "${vintage}" is not an ISO week (W01-W53)`);
  if (!data || typeof data !== "object" || !data.meta || !Array.isArray(data.rows)) throw new Error(`${market}: file must be {"meta": {...}, "rows": [...]}`);
  const meta = data.meta;
  if (meta.recordType !== "meta" || meta.vintage !== vintage) throw new Error(`${market}: no meta item for ${vintage}`);
  if (meta.revision !== 1) throw new Error(`${market}: meta revision is not 1`);
  if (meta.license !== "CC BY 4.0") throw new Error(`${market}: meta licence is not CC BY 4.0`);
  if (meta.title !== spec.title) throw new Error(`${market}: meta title is not "${spec.title}"`);
  const heads = data.rows.filter(r => r && r.recordType === "headline" && r.vintage === vintage);
  if (heads.length !== 1) throw new Error(`${market}: expected exactly one headline row for ${vintage}, found ${heads.length}`);
  const h = heads[0];
  if (h.status !== "ok" && h.status !== "base") throw new Error(`${market}: headline status is "${h.status}", only ok or base can be stamped`);
  const level = num(h.level, "level");
  const iso = ISO_RE.exec(String(meta.publishedAt || ""));
  if (!iso || !realDate(iso[1])) throw new Error(`${market}: publishedAt is not a strict ISO date`);
  const published = iso[1];
  if (published > today) throw new Error(`${market}: publishedAt is in the future`);
  const lead = `${spec.title}: latest published week ${vintage}`;
  let text;
  if (h.status === "base") {
    if (level !== 100) throw new Error(`${market}: a base week must have level 100`);
    text = `${lead} (base week: level 100.0, no change). Published ${longDate(published)}.`;
  } else {
    const wow = num(h.weekOnWeekPct, "weekOnWeekPct");
    const w4 = h.fourWeekPct === null || h.fourWeekPct === undefined || h.fourWeekPct === "" ? null : num(h.fourWeekPct, "fourWeekPct");
    text = `${lead}. Headline level ${level.toFixed(1)}, ${signed(wow, 2)} on the week before` + (w4 === null ? "" : `, ${signed(w4, 2)} over four weeks`) + `. Published ${longDate(published)}.`;
  }
  return { html: `<p id="static-latest" class="meta" data-vintage="${vintage}">${esc(text)}</p>`, published };
}

function stampJsonLd(html, spec, published) {
  const blocks = [...html.matchAll(/<script type="application\/ld\+json">\n([\s\S]*?)<\/script>/g)];
  if ((html.match(/application\/ld\+json/g) || []).length !== 1 || blocks.length !== 1) throw new Error(`${spec.file}: expected exactly one JSON-LD block`);
  const j = JSON.parse(blocks[0][1]);
  if (Array.isArray(j) || !j || typeof j !== "object" || j["@type"] !== "Dataset" || j.name !== spec.title) throw new Error(`${spec.file}: the JSON-LD top level is not the ${spec.title} Dataset object`);
  j.dateModified = published;
  const text = JSON.stringify(j, null, 2) + "\n";
  if (JSON.parse(text).dateModified !== published) throw new Error(`${spec.file}: dateModified did not survive serialisation`);
  return html.replace(blocks[0][1], () => text);
}

function stamp(opts) {
  const root = opts.root || ".";
  const today = opts.date;
  if (!realDate(today)) throw new Error("the date must be a real YYYY-MM-DD date");
  const nowDay = new Date().toISOString().slice(0, 10);
  if (Math.abs(new Date(today + "T00:00:00Z") - new Date(nowDay + "T00:00:00Z")) > 86400000) throw new Error("the date must be within one day of today");
  const out = new Map(); // path -> new content (LF; autocrlf restores working-tree line endings)
  const orig = new Map();
  const read = f => { const p = path.join(root, f); if (!out.has(p)) { const s = fs.readFileSync(p, "utf8"); orig.set(p, s); out.set(p, s.replace(/\r\n/g, "\n")); } return p; };
  const changedPages = [];
  for (const market of ["uk", "au"]) {
    const file = opts[market], confirm = opts["confirm-" + market];
    if (!file && !confirm) continue;
    if (!file || !confirm) throw new Error(`--${market} and --confirm-${market} must be given together`);
    if (!WEEK_RE.test(confirm)) throw new Error(`--confirm-${market} must be an ISO week like 2026-W43 (W01-W53)`);
    const data = JSON.parse(fs.readFileSync(file, "utf8"));
    if (!data.meta || data.meta.vintage !== confirm) throw new Error(`${market}: the file's vintage (${data.meta && data.meta.vintage}) does not match --confirm-${market} ${confirm}`);
    const block = buildBlock(market, data, confirm, today);
    const spec = PAGES[market];
    const p = read(spec.file);
    let html = out.get(p);
    const m = html.match(MARK_RE);
    if (!m) throw new Error(`${spec.file}: static-latest markers not found`);
    const cur = (m[1].match(/data-vintage="([^"]*)"/) || [])[1];
    if (cur === undefined) throw new Error(`${spec.file}: marker block has no data-vintage`);
    if (cur && confirm < cur) throw new Error(`${market}: ${confirm} is older than the stamped ${cur}`);
    html = html.replace(MARK_RE, () => `<!--static-latest:start-->\n${block.html}\n<!--static-latest:end-->`);
    html = stampJsonLd(html, spec, block.published);
    out.set(p, html);
    changedPages.push(spec.sitemap);
  }
  if (!changedPages.length) throw new Error("nothing to stamp: give --uk/--confirm-uk and/or --au/--confirm-au");
  const sp = read("sitemap.xml");
  let sm = out.get(sp);
  for (const pg of changedPages) {
    const re = new RegExp(`(<loc>https://data\\.yappman\\.com/${pg.replace(/\//g, "\\/")}</loc>\\n\\s*<lastmod>)[^<]*`);
    if (!re.test(sm)) throw new Error("sitemap entry missing: /" + pg);
    sm = sm.replace(re, (x, a1) => a1 + today);
  }
  out.set(sp, sm);
  return { out, orig, changedPages };
}

// Writes after validation: temporary files first, then renames; rolls back the renamed files if a rename fails.
function commit(out, orig) {
  const tmp = [];
  const cleanup = () => { const left = []; for (const [, t] of tmp) { try { if (fs.existsSync(t)) fs.unlinkSync(t); } catch { left.push(t); } } return left; };
  try {
    for (const [p, s] of out) { const t = p + ".stamp-tmp"; tmp.push([p, t]); fs.writeFileSync(t, s); }
  } catch (e) {
    const left = cleanup();
    throw new Error("could not write temporary files; nothing was changed (" + e.message + ")" + (left.length ? "; could not remove: " + left.join(", ") : "") + "; run git status and delete any *.stamp-tmp file before git add");
  }
  const done = [];
  try {
    for (const [p, t] of tmp) { fs.renameSync(t, p); done.push(p); }
  } catch (e) {
    const notRestored = [];
    for (const p of done) { try { fs.writeFileSync(p, orig.get(p)); } catch { notRestored.push(p); } }
    const left = cleanup();
    throw new Error("could not replace a file (" + e.message + "); " + (done.length ? (notRestored.length ? "COULD NOT RESTORE: " + notRestored.join(", ") + "; the others were restored" : "the " + done.length + " earlier file(s) were restored") : "no file had been replaced")
      + (left.length ? "; could not remove: " + left.join(", ") : "") + "; run git status and delete any *.stamp-tmp file before git add");
  }
}

function check(root) {
  const bad = [];
  for (const spec of Object.values(PAGES)) {
    const html = fs.readFileSync(path.join(root, spec.file), "utf8").replace(/\r\n/g, "\n");
    const m = html.match(MARK_RE);
    if (!m) bad.push(`${spec.file}: markers missing`);
    else if (!/data-vintage="\d{4}-W\d{2}"/.test(m[1])) bad.push(`${spec.file}: still the unstamped placeholder`);
  }
  return bad;
}

function parseArgs(args) {
  const o = {};
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (!a.startsWith("--") || !KNOWN_FLAGS.has(a.slice(2))) throw new Error("unknown argument " + a);
    const k = a.slice(2);
    if (k === "check") { o.check = true; continue; }
    const v = args[i + 1];
    if (v === undefined || v.startsWith("--")) throw new Error(`--${k} needs a value`);
    o[k] = v; i++;
  }
  return o;
}

module.exports = { stamp, commit, check, buildBlock, parseArgs, esc, MARK_RE, PAGES };

if (require.main === module) {
  let o;
  try { o = parseArgs(process.argv.slice(2)); } catch (e) { console.error("usage error: " + e.message); process.exit(2); }
  const root = o.root || ".";
  if (o.check) {
    const bad = check(root);
    if (bad.length) { console.error(bad.join("\n")); process.exit(1); }
    console.log("static-latest blocks are stamped");
  } else {
    let r;
    try { r = stamp({ ...o, root, date: o.date || new Date().toISOString().slice(0, 10) }); } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
    try { commit(r.out, r.orig); } catch (e) { console.error("WRITE PROBLEM. " + e.message); process.exit(1); }
    console.log("stamped", r.changedPages.join(", "));
  }
}
