// Stamp the latest PUBLISHED index figures into the static HTML of the UK and AU index pages (and JSON-LD dateModified).
//
//   node docs/release/stamp-latest.js --uk FILE --confirm-uk 2026-W43 [--au FILE --confirm-au 2026-W42] [--date YYYY-MM-DD] [--root DIR]
//   node docs/release/stamp-latest.js --check            (fails if either page still has the unstamped placeholder)
//
// FILE is the public vintage file the publish tool writes locally ({"meta": {...}, "rows": [...]}), AFTER the dataset
// has been checked to hold that vintage. Because the publish tool also writes these files in a dry run, the file alone does
// not prove publication: the operator must pass --confirm-uk / --confirm-au with the vintage, as an assertion that the public
// dataset holds it (the same idea as --confirm-vintage in the publish tool).
//
// Safety rules (each is tested in docs/release/stamp-latest.test.js):
//  - the vintage must match the confirmation, be a well-formed ISO week, and not be older than the one already stamped;
//  - the file needs a meta item for that vintage (revision 1, licence CC BY 4.0, the right title) and a headline row with
//    status ok or base and a finite level; nothing is imputed, so a skipped, held or insufficient week cannot be stamped;
//  - publishedAt must be a real date, not in the future;
//  - every inserted value is validated as a number, an ISO week or a date and then escaped;
//  - atomic: everything is checked in memory first and nothing is written unless all pages stamp; no network, no eval,
//    no child processes (only fs);
//  - the wording is "latest published", never "current" or "live".
const fs = require("fs");
const path = require("path");

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MARK_RE = /<!--static-latest:start-->\n([\s\S]*?)\n<!--static-latest:end-->/;
const PAGES = {
  uk: { file: "shelf-price-index/index.html", sitemap: "shelf-price-index/", title: "UK Online Shelf-Price Index" },
  au: { file: "au-shelf-price-index/index.html", sitemap: "au-shelf-price-index/", title: "AU Online Shelf-Price Index" },
};

const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const realDate = d => { const t = new Date(d + "T00:00:00Z"); return /^\d{4}-\d{2}-\d{2}$/.test(d) && !isNaN(t) && t.toISOString().slice(0, 10) === d; };
const longDate = d => { const [y, m, dd] = d.split("-").map(Number); return `${dd} ${MONTHS[m - 1]} ${y}`; };
const num = (v, name) => { if (typeof v !== "number" || !isFinite(v)) throw new Error(`${name} is not a finite number`); return v; };
const signed = (v, digits) => (v > 0 ? "+" : v < 0 ? "-" : "") + Math.abs(v).toFixed(digits) + "%";

function buildBlock(market, data, vintage, today) {
  const spec = PAGES[market];
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
  const published = String(meta.publishedAt || "").slice(0, 10);
  if (!realDate(published)) throw new Error(`${market}: publishedAt is not a date`);
  if (published > today) throw new Error(`${market}: publishedAt is in the future`);
  let text;
  if (h.status === "base") {
    if (level !== 100) throw new Error(`${market}: a base week must have level 100`);
    text = `Latest published week: ${vintage} (base week: level 100.0, no change). Published ${longDate(published)}.`;
  } else {
    const wow = num(h.weekOnWeekPct, "weekOnWeekPct");
    const w4 = h.fourWeekPct === null || h.fourWeekPct === undefined || h.fourWeekPct === "" ? null : num(h.fourWeekPct, "fourWeekPct");
    text = `Latest published week: ${vintage}. Headline level ${level.toFixed(1)}, ${signed(wow, 2)} on the week before` + (w4 === null ? "" : `, ${signed(w4, 2)} over four weeks`) + `. Published ${longDate(published)}.`;
  }
  return { html: `<p id="static-latest" class="meta" data-vintage="${vintage}">${esc(text)}</p>`, published };
}

function stamp(opts) {
  const root = opts.root || ".";
  const today = opts.date;
  if (!realDate(today)) throw new Error("the date must be a real YYYY-MM-DD date");
  const nowDay = new Date().toISOString().slice(0, 10);
  if (Math.abs(new Date(today + "T00:00:00Z") - new Date(nowDay + "T00:00:00Z")) > 86400000) throw new Error("the date must be within one day of today");
  const out = new Map();
  const read = f => { const p = path.join(root, f); if (!out.has(p)) out.set(p, fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n")); return p; };
  let any = false;
  const changedPages = [];
  for (const market of ["uk", "au"]) {
    const file = opts[market], confirm = opts["confirm-" + market];
    if (!file && !confirm) continue;
    if (!file || !confirm) throw new Error(`--${market} and --confirm-${market} must be given together`);
    if (!/^\d{4}-W\d{2}$/.test(confirm)) throw new Error(`--confirm-${market} must be an ISO week like 2026-W43`);
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
    // JSON-LD dateModified
    const ld = html.match(/<script type="application\/ld\+json">\n([\s\S]*?)<\/script>/);
    if (!ld) throw new Error(`${spec.file}: no JSON-LD block`);
    const j = JSON.parse(ld[1]);
    j.dateModified = block.published;
    html = html.replace(ld[1], () => JSON.stringify(j, null, 2) + "\n");
    out.set(p, html);
    any = true;
    changedPages.push(spec.sitemap);
  }
  if (!any) throw new Error("nothing to stamp: give --uk/--confirm-uk and/or --au/--confirm-au");
  // sitemap lastmod for exactly the stamped pages
  const sp = read("sitemap.xml");
  let sm = out.get(sp);
  for (const pg of changedPages) {
    const re = new RegExp(`(<loc>https://data\\.yappman\\.com/${pg.replace(/\//g, "\\/")}</loc>\\n\\s*<lastmod>)[^<]*`);
    if (!re.test(sm)) throw new Error("sitemap entry missing: /" + pg);
    sm = sm.replace(re, (x, a1) => a1 + today);
  }
  out.set(sp, sm);
  return { out, changedPages };
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

module.exports = { stamp, check, buildBlock, MARK_RE, PAGES };

if (require.main === module) {
  const args = process.argv.slice(2);
  const o = {};
  for (let i = 0; i < args.length; i++) { const a = args[i]; if (a === "--check") o.check = true; else if (a.startsWith("--")) o[a.slice(2)] = args[++i]; else { console.error("unknown argument " + a); process.exit(2); } }
  const root = o.root || ".";
  try {
    if (o.check) {
      const bad = check(root);
      if (bad.length) { console.error(bad.join("\n")); process.exit(1); }
      console.log("static-latest blocks are stamped");
    } else {
      const { out, changedPages } = stamp({ ...o, root, date: o.date || new Date().toISOString().slice(0, 10) });
      for (const [p, s] of out) fs.writeFileSync(p, s);
      console.log("stamped", changedPages.join(", "));
    }
  } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
}
