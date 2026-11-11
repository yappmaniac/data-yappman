// Build the site copies of the UK Online Shelf-Price Index: data/uk-shelf-price-index.csv and data/uk-shelf-price-index.json,
// every published vintage in one file each, served at https://data.yappman.com/data/uk-shelf-price-index.csv (and .json).
//
//   node docs/release/build-index-files.js --uk FILE --confirm-uk 2026-W45 [--uk FILE --confirm-uk 2026-W46 ...] [--new] [--root DIR]
//   node docs/release/build-index-files.js --au FILE --confirm-au 2026-W45 [...] [--new] [--root DIR]
//   node docs/release/build-index-files.js --derive [--root DIR]     (rewrites only the derived headline file from the site JSON)
//   node docs/release/build-index-files.js --check [--root DIR]
//
// The index pages read these files, not the dataset: /shelf-price-index/ reads data/uk-shelf-price-index.json,
// /au-shelf-price-index/ reads data/au-shelf-price-index.json (the AU index has a site JSON only, no site CSV), and the home
// page and /press/ read data/uk-shelf-price-index-headline.json, the headline rows of the UK JSON and nothing else. So a
// weekly release MUST add the week here in the same commit as the stamp (docs/release/index-publish-checklist.md);
// --check fails if a page's stamped week is not the last week in its data file.
//
// FILE is the public vintage file the publish tool writes locally ({"meta": {...}, "rows": [...]}); the tool's CSV of the same
// vintage must sit beside it under the same name with .csv. As for stamp-latest.js, the file alone does not prove publication:
// --confirm-uk is the operator's assertion that the public dataset holds that vintage. Pairs are applied in the order given.
// --new is needed only for the first build, when neither site file exists yet.
//
// What the two files hold:
//  - JSON: a flat array of the dataset's items, grouped by vintage, the meta item first, as in the vintage files; nothing is
//    added; an empty meta coverageWarnings list is left out, as the dataset does not return it (seen for 2026-W43 and 2026-W44).
//    Only known meta keys are accepted, so nothing unexpected in a local file reaches the public copy.
//  - CSV: the rows only (no meta), with the tool's 16 columns in its order plus one last column, base, copied from the vintage's
//    meta (2026-W39 for the closed series, 2026-W42 after the restart), so a chart can tell the two series apart. Vintages from
//    before the four flow columns existed (entered, left, relinked, missingPackSize) leave them empty, as the tool's own CSV does.
//    Field text is taken from the tool's CSV, after checking each field against the JSON row, so numbers keep the tool's format.
//
// Safety rules (each is tested in docs/release/build-index-files.test.js):
//  - each vintage must match its confirmation, be a well-formed ISO week, and be newer than the last vintage in the site files;
//  - the meta item: revision 1, licence CC BY 4.0, the right title, a well-formed base week, publishedAt a strict ISO date not in
//    the future; every row: the same vintage, publishedAt and revision, a known record type and status, retailer and class empty
//    or named in the meta, only known columns, every number finite or null; exactly one headline row, one row per retailer;
//  - the tool's CSV must have the same rows as the JSON, field for field; a quoted field or an unknown column stops the build;
//  - --check re-reads the site files and fails unless they agree with each other row for row, the headline file is exactly
//    the headline rows of the JSON, and each index page's stamped week (data-vintage) is the last week in its data file;
//  - atomic writes with rollback (as in stamp-latest.js; a file that did not exist before is deleted again, not left empty);
//    no network, no eval, no child processes (only fs and path).
const fs = require("fs");
const path = require("path");

const TITLE = "UK Online Shelf-Price Index";
const CSV_OUT = "data/uk-shelf-price-index.csv";
const JSON_OUT = "data/uk-shelf-price-index.json";
const HEADLINE_OUT = "data/uk-shelf-price-index-headline.json";
const AU_JSON_OUT = "data/au-shelf-price-index.json";
// One entry per index. csv: null means no site CSV is written (the tool's CSV is still checked against the JSON).
// headline: a small file holding only the headline rows, for the pages that show just the latest level and the chart.
// metaText, metaNum, metaLists and recordTypes are that index's own meta keys and record types, beyond the common ones.
const MARKETS = {
  uk: { key: "uk", title: TITLE, csv: CSV_OUT, json: JSON_OUT, headline: HEADLINE_OUT, page: "shelf-price-index/index.html", metaText: [], metaNum: [], metaLists: [], recordTypes: [] },
  au: { key: "au", title: "AU Online Shelf-Price Index", csv: null, json: AU_JSON_OUT, headline: null, page: "au-shelf-price-index/index.html",
    metaText: ["currency", "headlineDefinition", "colesStatus", "woolworthsStore", "classRulesVersion"], metaNum: ["colesProducts", "colesRangeSharePct", "colesRequests"],
    metaLists: ["headlineClasses"], recordTypes: ["retailer_like_for_like"] },
};
const CORE = ["vintage", "publishedAt", "revision", "recordType", "retailer", "class", "level", "weekOnWeekPct", "fourWeekPct", "matched", "matchedShare", "status"];
const COLUMNS = [...CORE, "entered", "left", "relinked", "missingPackSize"];
const OUT_COLUMNS = [...COLUMNS, "base"];
const NUMBERS = new Set(["level", "weekOnWeekPct", "fourWeekPct", "matched", "matchedShare", "entered", "left", "relinked", "missingPackSize"]);
const RECORD_TYPES = new Set(["headline", "retailer", "class", "retailer_class", "subtotal", "retailer_subtotal"]);
const STATUSES = new Set(["ok", "carried", "insufficient", "base"]);
const WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;
const ISO_RE = /^(\d{4}-\d{2}-\d{2})(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/;
const META_KEYS = new Set(["vintage", "publishedAt", "revision", "recordType", "title", "base", "weighting", "retailers", "classes", "matchedTotal", "coverageWarnings", "headlineRetailers", "methodologyUrl", "notCpi", "measures", "license", "subtotals"]);
const NUM_RE = /^-?\d+(\.\d+)?([eE][-+]?\d+)?$/;
const SLUG_RE = /^[a-z][a-z0-9_-]{0,40}$/;
const KNOWN_FLAGS = new Set(["uk", "confirm-uk", "au", "confirm-au", "new", "derive", "root", "check"]);

const realDate = d => { const t = new Date(d + "T00:00:00Z"); return /^\d{4}-\d{2}-\d{2}$/.test(d) && !isNaN(t) && t.toISOString().slice(0, 10) === d; };
const isNum = v => typeof v === "number" && isFinite(v);

function checkMeta(meta, vintage, today, spec = MARKETS.uk) {
  if (!meta || meta.recordType !== "meta" || meta.vintage !== vintage) throw new Error(`no meta item for ${vintage}`);
  const own = new Set([...spec.metaText, ...spec.metaNum, ...spec.metaLists]);
  for (const k of Object.keys(meta)) if (!META_KEYS.has(k) && !own.has(k)) throw new Error(`${vintage}: unknown meta key ${k}`);
  for (const k of ["weighting", "methodologyUrl", "measures", ...spec.metaText]) if (k in meta && typeof meta[k] !== "string") throw new Error(`${vintage}: meta ${k} is not text`);
  for (const k of ["matchedTotal", "headlineRetailers", ...spec.metaNum]) if (k in meta && meta[k] !== null && !isNum(meta[k])) throw new Error(`${vintage}: meta ${k} is not a finite number or null`);
  for (const k of spec.metaLists) if (k in meta && meta[k] !== null && (!Array.isArray(meta[k]) || !meta[k].every(x => typeof x === "string" && SLUG_RE.test(x)))) throw new Error(`${vintage}: meta ${k} is not a list of names or null`);
  if ("notCpi" in meta && meta.notCpi !== true) throw new Error(`${vintage}: meta notCpi is not true`);
  if ("coverageWarnings" in meta && (!Array.isArray(meta.coverageWarnings) || !meta.coverageWarnings.every(w => typeof w === "string"))) throw new Error(`${vintage}: meta coverageWarnings is not a list of text`);
  if (meta.revision !== 1) throw new Error(`${vintage}: meta revision is not 1`);
  if (meta.license !== "CC BY 4.0") throw new Error(`${vintage}: meta licence is not CC BY 4.0`);
  if (meta.title !== spec.title) throw new Error(`${vintage}: meta title is not "${spec.title}"`);
  if (!WEEK_RE.test(String(meta.base))) throw new Error(`${vintage}: meta base is not an ISO week`);
  const iso = ISO_RE.exec(String(meta.publishedAt || ""));
  if (!iso || !realDate(iso[1])) throw new Error(`${vintage}: publishedAt is not a strict ISO date`);
  if (iso[1] > today) throw new Error(`${vintage}: publishedAt is in the future`);
  for (const k of ["retailers", "classes"]) {
    if (!Array.isArray(meta[k]) || !meta[k].length || !meta[k].every(s => SLUG_RE.test(s))) throw new Error(`${vintage}: meta ${k} is not a list of names`);
  }
  if (meta.subtotals !== undefined && (!Array.isArray(meta.subtotals) || !meta.subtotals.every(s => SLUG_RE.test(s)))) throw new Error(`${vintage}: meta subtotals is not a list of names`);
}

function checkRow(r, meta, i, spec = MARKETS.uk) {
  const at = `${meta.vintage} row ${i + 1}`;
  if (!r || typeof r !== "object" || Array.isArray(r)) throw new Error(`${at}: not an object`);
  for (const k of Object.keys(r)) if (!COLUMNS.includes(k)) throw new Error(`${at}: unknown field ${k}`);
  for (const k of CORE) if (!(k in r)) throw new Error(`${at}: missing field ${k}`);
  if (r.vintage !== meta.vintage || r.publishedAt !== meta.publishedAt || r.revision !== 1) throw new Error(`${at}: vintage, publishedAt or revision differs from the meta item`);
  if (!RECORD_TYPES.has(r.recordType) && !spec.recordTypes.includes(r.recordType)) throw new Error(`${at}: unknown record type ${r.recordType}`);
  if (!STATUSES.has(r.status)) throw new Error(`${at}: unknown status ${r.status}`);
  if (r.retailer !== "" && !meta.retailers.includes(r.retailer)) throw new Error(`${at}: retailer ${r.retailer} is not in the meta`);
  if (r.class !== "" && !meta.classes.includes(r.class) && !(meta.subtotals || []).includes(r.class)) throw new Error(`${at}: class ${r.class} is not in the meta`);
  for (const k of NUMBERS) if (k in r && r[k] !== null && !isNum(r[k])) throw new Error(`${at}: ${k} is not a finite number or null`);
}

// The tool's CSV: plain comma-separated values, never quoted (every value is a name, a number, a week or a date).
function parseCsv(text, what) {
  const lines = text.replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n");
  if (text.includes('"')) throw new Error(`${what}: a quoted field; this tool reads only the plain CSV the publish tool writes`);
  const header = lines[0].split(",");
  if (!(header.length === CORE.length || header.length === COLUMNS.length || header.length === OUT_COLUMNS.length)) throw new Error(`${what}: unexpected header`);
  header.forEach((h, i) => { if (h !== OUT_COLUMNS[i]) throw new Error(`${what}: unexpected column ${h}`); });
  return lines.slice(1).map((l, i) => {
    const f = l.split(",");
    if (f.length !== header.length) throw new Error(`${what} line ${i + 2}: ${f.length} fields, expected ${header.length}`);
    return Object.fromEntries(header.map((h, j) => [h, f[j]]));
  });
}

function sameField(k, text, v) {
  if (v === null || v === undefined) return text === "";
  if (NUMBERS.has(k) || k === "revision") return NUM_RE.test(text) && Number(text) === v;
  return text === String(v);
}

function csvLine(fields, row, meta, at) {
  for (const k of COLUMNS) if (!sameField(k, fields[k] === undefined ? "" : fields[k], row[k])) throw new Error(`${at}: the CSV and JSON differ in ${k}`);
  return OUT_COLUMNS.map(k => (k === "base" ? meta.base : fields[k] === undefined ? "" : fields[k])).join(",");
}

// One vintage file pair -> { items, lines }.
function readVintage(file, vintage, today, spec = MARKETS.uk) {
  if (!WEEK_RE.test(vintage)) throw new Error(`--confirm-${spec.key} must be an ISO week like 2026-W45 (W01-W53), not "${vintage}"`);
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!data || !data.meta || !Array.isArray(data.rows)) throw new Error(`${file}: must be {"meta": {...}, "rows": [...]}`);
  if (data.meta.vintage !== vintage) throw new Error(`the file's vintage (${data.meta.vintage}) does not match --confirm-${spec.key} ${vintage}`);
  checkMeta(data.meta, vintage, today, spec);
  data.rows.forEach((r, i) => checkRow(r, data.meta, i, spec));
  if (data.rows.filter(r => r.recordType === "headline").length !== 1) throw new Error(`${vintage}: expected exactly one headline row`);
  const rets = data.rows.filter(r => r.recordType === "retailer").map(r => r.retailer);
  if (rets.length !== data.meta.retailers.length || new Set(rets).size !== rets.length) throw new Error(`${vintage}: expected one retailer row per retailer in the meta`);
  const csvFile = file.replace(/\.json$/, ".csv");
  if (csvFile === file || !fs.existsSync(csvFile)) throw new Error(`${file}: the tool's CSV of the same vintage (.csv beside it) is missing`);
  const fields = parseCsv(fs.readFileSync(csvFile, "utf8"), csvFile);
  if (fields.length !== data.rows.length) throw new Error(`${vintage}: the CSV has ${fields.length} rows, the JSON ${data.rows.length}`);
  const lines = data.rows.map((r, i) => csvLine(fields[i], r, data.meta, `${vintage} row ${i + 1}`));
  const meta = { ...data.meta };
  if (Array.isArray(meta.coverageWarnings) && !meta.coverageWarnings.length) delete meta.coverageWarnings;
  return { items: [meta, ...data.rows], lines };
}

// The headline file: the headline rows of the site JSON, one per vintage, in the same item text.
const headlineText = items => "[\n" + items.filter(it => it && it.recordType === "headline").map(it => JSON.stringify(it)).join(",\n") + "\n]\n";

// The current site files of one index -> { items, lines, last, rows } after checking that they agree.
function readSite(root, spec = MARKETS.uk, derived = true) {
  const jp = path.join(root, spec.json), cp = spec.csv ? path.join(root, spec.csv) : null;
  const haveJ = fs.existsSync(jp), haveC = cp ? fs.existsSync(cp) : haveJ;
  if (!haveC && !haveJ) return null;
  if (haveC !== haveJ) throw new Error(`only one of ${spec.csv} and ${spec.json} exists`);
  const items = JSON.parse(fs.readFileSync(jp, "utf8"));
  if (!Array.isArray(items) || !items.length) throw new Error(`${spec.json}: not a non-empty array`);
  const fields = cp ? parseCsv(fs.readFileSync(cp, "utf8"), spec.csv) : null;
  if (cp && !fs.readFileSync(cp, "utf8").replace(/\r\n/g, "\n").startsWith(OUT_COLUMNS.join(",") + "\n")) throw new Error(`${spec.csv}: the header is not the 17 site columns`);
  let meta = null, last = "", n = 0, heads = 0;
  const lines = [];
  for (const it of items) {
    if (it && it.recordType === "meta") {
      if (!WEEK_RE.test(String(it.vintage)) || it.vintage <= last) throw new Error(`${spec.json}: vintages are not in increasing order at ${it.vintage}`);
      if (meta && heads !== 1) throw new Error(`${spec.json}: ${meta.vintage} does not have exactly one headline row`);
      checkMeta(it, it.vintage, "9999-12-31", spec);
      meta = it; last = it.vintage; heads = 0; continue;
    }
    if (!meta) throw new Error(`${spec.json}: a row before the first meta item`);
    checkRow(it, meta, n, spec);
    if (it.recordType === "headline") heads++;
    if (fields) {
      const f = fields[n];
      if (!f) throw new Error(`${spec.csv}: fewer rows than ${spec.json}`);
      if (f.base !== meta.base) throw new Error(`${spec.csv} line ${n + 2}: base differs from the meta item`);
      lines.push(csvLine(f, it, meta, `${spec.csv} line ${n + 2}`));
    }
    n++;
  }
  if (heads !== 1) throw new Error(`${spec.json}: ${last} does not have exactly one headline row`);
  if (fields && fields.length !== n) throw new Error(`${spec.csv}: ${fields.length} rows, ${spec.json} ${n}`);
  if (derived && spec.headline && fs.existsSync(path.join(root, spec.headline)) && fs.readFileSync(path.join(root, spec.headline), "utf8").replace(/\r\n/g, "\n") !== headlineText(items)) {
    throw new Error(`${spec.headline}: not the headline rows of ${spec.json}`);
  }
  return { items, lines, last, rows: n };
}

// --check: every index's site files agree; the headline file exists; a page's stamped week is the last week in its file.
// The UK files and the UK page must exist (run it from the site root); another index's file must exist once its page is in the root.
function checkAll(root) {
  const said = [];
  for (const spec of Object.values(MARKETS)) {
    const pagePath = path.join(root, spec.page), havePage = fs.existsSync(pagePath);
    const s = readSite(root, spec);
    if (!s) { if (spec.key === "uk" || havePage) throw new Error(spec.key === "uk" ? "the site files do not exist" : `${spec.json} does not exist`); continue; }
    if (spec.headline && !fs.existsSync(path.join(root, spec.headline))) throw new Error(`${spec.headline} does not exist; run --derive`);
    if (!havePage) throw new Error(`${spec.page} not found under the root, so its stamped week cannot be checked`);
    const m = fs.readFileSync(pagePath, "utf8").match(/<!--static-latest:start-->[\s\S]*?data-vintage="([^"]*)"[\s\S]*?<!--static-latest:end-->/);
    if (!m) throw new Error(`${spec.page}: no stamped week (data-vintage) found`);
    if (m[1] !== s.last) throw new Error(`${spec.page} is stamped ${m[1] || "(nothing)"} but the last week in ${spec.json} is ${s.last}`);
    said.push(spec.key === "uk" ? `site index files agree: ${s.lines.length} rows, last vintage ${s.last}` : `${spec.json}: ${s.rows} rows, last vintage ${s.last}`);
  }
  return said;
}

function build(opts) {
  const root = opts.root || ".";
  const today = new Date().toISOString().slice(0, 10);
  const given = Object.values(MARKETS).filter(spec => (opts[spec.key] || []).length);
  if (!given.length && !opts.derive) throw new Error("nothing to add: give --uk FILE --confirm-uk WEEK (or --au FILE --confirm-au WEEK)");
  if (given.length && opts.derive) throw new Error("--derive rewrites the derived files only; do not give it with --uk or --au");
  const out = new Map(), orig = new Map(); // orig: null for a file that does not exist yet
  const put = (f, s) => { const p = path.join(root, f); orig.set(p, fs.existsSync(p) ? fs.readFileSync(p, "utf8") : null); out.set(p, s); };
  fs.mkdirSync(path.join(root, "data"), { recursive: true });
  const wrote = [];
  let fresh = 0, last = "", rows = 0;
  for (const spec of (opts.derive ? Object.values(MARKETS).filter(m => m.headline) : given)) {
    const site = readSite(root, spec, !opts.derive); // --derive rewrites the headline file, so a wrong one must not stop it
    const names = spec.csv ? `${spec.csv} and ${spec.json}` : spec.json;
    if (opts.derive) {
      if (!site) throw new Error(`${names} do not exist; nothing to derive`);
      put(spec.headline, headlineText(site.items)); wrote.push(spec.headline); last = site.last; rows = site.rows;
      continue;
    }
    if (!site && !opts.new) throw new Error(`${names} do not exist; give --new for the first build`);
    if (!site) fresh++;
    const items = site ? site.items.slice() : [], lines = site ? site.lines.slice() : [];
    last = site ? site.last : "";
    for (const [file, vintage] of opts[spec.key]) {
      if (vintage <= last) throw new Error(`${vintage} is not newer than ${last}, the last vintage in the site files`);
      const v = readVintage(file, vintage, today, spec);
      items.push(...v.items); lines.push(...v.lines); last = vintage;
    }
    if (spec.csv) { put(spec.csv, [OUT_COLUMNS.join(","), ...lines].join("\n") + "\n"); wrote.push(spec.csv); }
    put(spec.json, "[\n" + items.map(it => JSON.stringify(it)).join(",\n") + "\n]\n"); wrote.push(spec.json);
    if (spec.headline) { put(spec.headline, headlineText(items)); wrote.push(spec.headline); }
    rows = items.filter(it => it.recordType !== "meta").length;
  }
  if (opts.new && !fresh) throw new Error("--new given but the site files already exist");
  return { out, orig, last, rows, wrote };
}

// Writes after validation: temporary files first, then renames; if a rename fails, the files already replaced are put back
// (or deleted, if they are new). The temporary suffix is the one .gitignore already covers.
function commit(out, orig) {
  const tmp = [];
  const cleanup = () => { const left = []; for (const [, t] of tmp) { try { if (fs.existsSync(t)) fs.unlinkSync(t); } catch { left.push(t); } } return left; };
  try {
    for (const [p, s] of out) { const t = p + ".stamp-tmp"; tmp.push([p, t]); fs.writeFileSync(t, s); }
  } catch (e) {
    const left = cleanup();
    throw new Error("could not write temporary files; nothing was changed (" + e.message + ")" + (left.length ? "; could not remove: " + left.join(", ") : ""));
  }
  const done = [];
  try {
    for (const [p, t] of tmp) { fs.renameSync(t, p); done.push(p); }
  } catch (e) {
    const notRestored = [];
    for (const p of done) { try { if (orig.get(p) === null) fs.unlinkSync(p); else fs.writeFileSync(p, orig.get(p)); } catch { notRestored.push(p); } }
    const left = cleanup();
    throw new Error("could not replace a file (" + e.message + "); " + (notRestored.length ? "COULD NOT RESTORE: " + notRestored.join(", ") : "nothing was left changed")
      + (left.length ? "; could not remove: " + left.join(", ") : "") + "; run git status before git add");
  }
}

function parseArgs(args) {
  const o = { uk: [], au: [] };
  let file = null, market = null;
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (!a.startsWith("--") || !KNOWN_FLAGS.has(a.slice(2))) throw new Error("unknown argument " + a);
    const k = a.slice(2);
    if (k === "check" || k === "new" || k === "derive") { o[k] = true; continue; }
    const v = args[i + 1];
    if (v === undefined || v.startsWith("--")) throw new Error(`--${k} needs a value`);
    i++;
    if (k === "uk" || k === "au") { if (file !== null) throw new Error(`--${market} without its --confirm-${market}`); file = v; market = k; }
    else if (k === "confirm-uk" || k === "confirm-au") {
      const m = k.slice(8);
      if (file === null || market !== m) throw new Error(`--${k} without a --${m} before it`);
      o[m].push([file, v]); file = null;
    }
    else o[k] = v;
  }
  if (file !== null) throw new Error(`--${market} without its --confirm-${market}`);
  return o;
}

module.exports = { build, commit, readSite, readVintage, checkAll, headlineText, parseArgs, MARKETS, CSV_OUT, JSON_OUT, HEADLINE_OUT, AU_JSON_OUT, OUT_COLUMNS };

if (require.main === module) {
  let o;
  try { o = parseArgs(process.argv.slice(2)); } catch (e) { console.error("usage error: " + e.message); process.exit(2); }
  const root = o.root || ".";
  if (o.check) {
    let said;
    try { said = checkAll(root); } catch (e) { console.error(e.message); process.exit(1); }
    console.log(said.join("\n"));
  } else {
    let r;
    try { r = build({ ...o, root }); } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
    try { commit(r.out, r.orig); } catch (e) { console.error("WRITE PROBLEM. " + e.message); process.exit(1); }
    console.log(`wrote ${r.wrote.join(", ")}: last vintage ${r.last}`);
  }
}
