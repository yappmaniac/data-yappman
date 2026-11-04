// Build the site copies of the UK Online Shelf-Price Index: data/uk-shelf-price-index.csv and data/uk-shelf-price-index.json,
// every published vintage in one file each, served at https://data.yappman.com/data/uk-shelf-price-index.csv (and .json).
//
//   node docs/release/build-index-files.js --uk FILE --confirm-uk 2026-W45 [--uk FILE --confirm-uk 2026-W46 ...] [--new] [--root DIR]
//   node docs/release/build-index-files.js --check [--root DIR]
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
//  - --check re-reads both site files and fails unless they agree with each other row for row;
//  - atomic writes with rollback (as in stamp-latest.js; a file that did not exist before is deleted again, not left empty);
//    no network, no eval, no child processes (only fs and path).
const fs = require("fs");
const path = require("path");

const TITLE = "UK Online Shelf-Price Index";
const CSV_OUT = "data/uk-shelf-price-index.csv";
const JSON_OUT = "data/uk-shelf-price-index.json";
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
const SLUG_RE = /^[a-z][a-z0-9-]{0,40}$/;
const KNOWN_FLAGS = new Set(["uk", "confirm-uk", "new", "root", "check"]);

const realDate = d => { const t = new Date(d + "T00:00:00Z"); return /^\d{4}-\d{2}-\d{2}$/.test(d) && !isNaN(t) && t.toISOString().slice(0, 10) === d; };
const isNum = v => typeof v === "number" && isFinite(v);

function checkMeta(meta, vintage, today) {
  if (!meta || meta.recordType !== "meta" || meta.vintage !== vintage) throw new Error(`no meta item for ${vintage}`);
  for (const k of Object.keys(meta)) if (!META_KEYS.has(k)) throw new Error(`${vintage}: unknown meta key ${k}`);
  for (const k of ["weighting", "methodologyUrl", "measures"]) if (k in meta && typeof meta[k] !== "string") throw new Error(`${vintage}: meta ${k} is not text`);
  for (const k of ["matchedTotal", "headlineRetailers"]) if (k in meta && meta[k] !== null && !isNum(meta[k])) throw new Error(`${vintage}: meta ${k} is not a finite number or null`);
  if ("notCpi" in meta && meta.notCpi !== true) throw new Error(`${vintage}: meta notCpi is not true`);
  if ("coverageWarnings" in meta && (!Array.isArray(meta.coverageWarnings) || !meta.coverageWarnings.every(w => typeof w === "string"))) throw new Error(`${vintage}: meta coverageWarnings is not a list of text`);
  if (meta.revision !== 1) throw new Error(`${vintage}: meta revision is not 1`);
  if (meta.license !== "CC BY 4.0") throw new Error(`${vintage}: meta licence is not CC BY 4.0`);
  if (meta.title !== TITLE) throw new Error(`${vintage}: meta title is not "${TITLE}"`);
  if (!WEEK_RE.test(String(meta.base))) throw new Error(`${vintage}: meta base is not an ISO week`);
  const iso = ISO_RE.exec(String(meta.publishedAt || ""));
  if (!iso || !realDate(iso[1])) throw new Error(`${vintage}: publishedAt is not a strict ISO date`);
  if (iso[1] > today) throw new Error(`${vintage}: publishedAt is in the future`);
  for (const k of ["retailers", "classes"]) {
    if (!Array.isArray(meta[k]) || !meta[k].length || !meta[k].every(s => SLUG_RE.test(s))) throw new Error(`${vintage}: meta ${k} is not a list of names`);
  }
  if (meta.subtotals !== undefined && (!Array.isArray(meta.subtotals) || !meta.subtotals.every(s => SLUG_RE.test(s)))) throw new Error(`${vintage}: meta subtotals is not a list of names`);
}

function checkRow(r, meta, i) {
  const at = `${meta.vintage} row ${i + 1}`;
  if (!r || typeof r !== "object" || Array.isArray(r)) throw new Error(`${at}: not an object`);
  for (const k of Object.keys(r)) if (!COLUMNS.includes(k)) throw new Error(`${at}: unknown field ${k}`);
  for (const k of CORE) if (!(k in r)) throw new Error(`${at}: missing field ${k}`);
  if (r.vintage !== meta.vintage || r.publishedAt !== meta.publishedAt || r.revision !== 1) throw new Error(`${at}: vintage, publishedAt or revision differs from the meta item`);
  if (!RECORD_TYPES.has(r.recordType)) throw new Error(`${at}: unknown record type ${r.recordType}`);
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
function readVintage(file, vintage, today) {
  if (!WEEK_RE.test(vintage)) throw new Error(`--confirm-uk must be an ISO week like 2026-W45 (W01-W53), not "${vintage}"`);
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!data || !data.meta || !Array.isArray(data.rows)) throw new Error(`${file}: must be {"meta": {...}, "rows": [...]}`);
  if (data.meta.vintage !== vintage) throw new Error(`the file's vintage (${data.meta.vintage}) does not match --confirm-uk ${vintage}`);
  checkMeta(data.meta, vintage, today);
  data.rows.forEach((r, i) => checkRow(r, data.meta, i));
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

// The current site files -> { items, lines, last } after checking that they agree.
function readSite(root) {
  const cp = path.join(root, CSV_OUT), jp = path.join(root, JSON_OUT);
  const haveC = fs.existsSync(cp), haveJ = fs.existsSync(jp);
  if (!haveC && !haveJ) return null;
  if (haveC !== haveJ) throw new Error(`only one of ${CSV_OUT} and ${JSON_OUT} exists`);
  const items = JSON.parse(fs.readFileSync(jp, "utf8"));
  if (!Array.isArray(items) || !items.length) throw new Error(`${JSON_OUT}: not a non-empty array`);
  const fields = parseCsv(fs.readFileSync(cp, "utf8"), CSV_OUT);
  const text = fs.readFileSync(cp, "utf8").replace(/\r\n/g, "\n");
  if (!text.startsWith(OUT_COLUMNS.join(",") + "\n")) throw new Error(`${CSV_OUT}: the header is not the 17 site columns`);
  let meta = null, last = "", n = 0;
  const lines = [];
  for (const it of items) {
    if (it && it.recordType === "meta") {
      if (!WEEK_RE.test(String(it.vintage)) || it.vintage <= last) throw new Error(`${JSON_OUT}: vintages are not in increasing order at ${it.vintage}`);
      checkMeta(it, it.vintage, "9999-12-31");
      meta = it; last = it.vintage; continue;
    }
    if (!meta) throw new Error(`${JSON_OUT}: a row before the first meta item`);
    checkRow(it, meta, n);
    const f = fields[n];
    if (!f) throw new Error(`${CSV_OUT}: fewer rows than ${JSON_OUT}`);
    if (f.base !== meta.base) throw new Error(`${CSV_OUT} line ${n + 2}: base differs from the meta item`);
    lines.push(csvLine(f, it, meta, `${CSV_OUT} line ${n + 2}`));
    n++;
  }
  if (fields.length !== n) throw new Error(`${CSV_OUT}: ${fields.length} rows, ${JSON_OUT} ${n}`);
  return { items, lines, last };
}

function build(opts) {
  const root = opts.root || ".";
  const today = new Date().toISOString().slice(0, 10);
  const pairs = opts.uk || [];
  if (!pairs.length) throw new Error("nothing to add: give --uk FILE --confirm-uk WEEK");
  const site = readSite(root);
  if (!site && !opts.new) throw new Error(`${CSV_OUT} and ${JSON_OUT} do not exist; give --new for the first build`);
  if (site && opts.new) throw new Error("--new given but the site files already exist");
  const items = site ? site.items.slice() : [], lines = site ? site.lines.slice() : [];
  let last = site ? site.last : "";
  for (const [file, vintage] of pairs) {
    if (vintage <= last) throw new Error(`${vintage} is not newer than ${last}, the last vintage in the site files`);
    const v = readVintage(file, vintage, today);
    items.push(...v.items); lines.push(...v.lines); last = vintage;
  }
  const out = new Map(), orig = new Map(); // orig: null for a file that does not exist yet
  const put = (f, s) => { const p = path.join(root, f); orig.set(p, fs.existsSync(p) ? fs.readFileSync(p, "utf8") : null); out.set(p, s); };
  fs.mkdirSync(path.join(root, "data"), { recursive: true });
  put(CSV_OUT, [OUT_COLUMNS.join(","), ...lines].join("\n") + "\n");
  put(JSON_OUT, "[\n" + items.map(it => JSON.stringify(it)).join(",\n") + "\n]\n");
  return { out, orig, last, rows: lines.length };
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
  const o = { uk: [] };
  let file = null;
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (!a.startsWith("--") || !KNOWN_FLAGS.has(a.slice(2))) throw new Error("unknown argument " + a);
    const k = a.slice(2);
    if (k === "check" || k === "new") { o[k] = true; continue; }
    const v = args[i + 1];
    if (v === undefined || v.startsWith("--")) throw new Error(`--${k} needs a value`);
    i++;
    if (k === "uk") { if (file !== null) throw new Error("--uk without its --confirm-uk"); file = v; }
    else if (k === "confirm-uk") { if (file === null) throw new Error("--confirm-uk without a --uk before it"); o.uk.push([file, v]); file = null; }
    else o[k] = v;
  }
  if (file !== null) throw new Error("--uk without its --confirm-uk");
  return o;
}

module.exports = { build, commit, readSite, readVintage, parseArgs, CSV_OUT, JSON_OUT, OUT_COLUMNS };

if (require.main === module) {
  let o;
  try { o = parseArgs(process.argv.slice(2)); } catch (e) { console.error("usage error: " + e.message); process.exit(2); }
  const root = o.root || ".";
  if (o.check) {
    let s;
    try { s = readSite(root); } catch (e) { console.error(e.message); process.exit(1); }
    if (!s) { console.error("the site files do not exist"); process.exit(1); }
    console.log(`site index files agree: ${s.lines.length} rows, last vintage ${s.last}`);
  } else {
    let r;
    try { r = build({ ...o, root }); } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
    try { commit(r.out, r.orig); } catch (e) { console.error("WRITE PROBLEM. " + e.message); process.exit(1); }
    console.log(`wrote ${CSV_OUT} and ${JSON_OUT}: ${r.rows} rows, last vintage ${r.last}`);
  }
}
