// Tests for docs/release/build-index-files.js.   node --test docs/release/build-index-files.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const { build, commit, readSite, checkAll, parseArgs, MARKETS, CSV_OUT, JSON_OUT, HEADLINE_OUT, AU_JSON_OUT } = require("./build-index-files.js");

const SCRIPT = path.join(__dirname, "build-index-files.js");
const TODAY = new Date().toISOString().slice(0, 10);
const AT = TODAY + "T07:00:00Z";
const CORE = "vintage,publishedAt,revision,recordType,retailer,class,level,weekOnWeekPct,fourWeekPct,matched,matchedShare,status";
const FLOW = ",entered,left,relinked,missingPackSize";

const meta = (v, over = {}) => ({ vintage: v, publishedAt: AT, revision: 1, recordType: "meta", title: "UK Online Shelf-Price Index", base: "2026-W42", retailers: ["tesco", "aldi"], classes: ["dairy-eggs", "pet"], license: "CC BY 4.0", subtotals: ["food-soft-drinks"], ...over });
const row = (v, recordType, retailer, cls, level, over = {}, flow = true) => ({ vintage: v, publishedAt: AT, revision: 1, recordType, retailer, class: cls, level, weekOnWeekPct: -0.2055, fourWeekPct: null, matched: 4333, matchedShare: 0.9823, status: "ok", ...(flow ? { entered: null, left: null, relinked: null, missingPackSize: null } : {}), ...over });
const rowsFor = (v, flow = true) => [row(v, "headline", "", "", 99.7238, {}, flow), row(v, "retailer", "tesco", "", 100.0653, {}, flow), row(v, "retailer", "aldi", "", 100, {}, flow), row(v, "class", "", "pet", 101.5, {}, flow), row(v, "subtotal", "", "food-soft-drinks", 99.8139, {}, flow)];
const fmt = x => (x === null || x === undefined ? "" : String(x));
const toCsv = (rows, flow = true) => [CORE + (flow ? FLOW : ""), ...rows.map(r => (CORE + (flow ? FLOW : "")).split(",").map(k => fmt(r[k])).join(","))].join("\n") + "\n";

function vintage(root, v, { m = {}, rows, flow = true, csv } = {}) {
  const rs = rows || rowsFor(v, flow);
  const jp = path.join(root, `uk-shelf-price-index-${v}.json`);
  fs.writeFileSync(jp, JSON.stringify({ meta: meta(v, m), rows: rs }));
  fs.writeFileSync(jp.replace(/\.json$/, ".csv"), csv === undefined ? toCsv(rs, flow) : csv);
  return jp;
}
const site = () => fs.mkdtempSync(path.join(os.tmpdir(), "idxfiles-"));
const run = (root, o) => { const r = build({ root, ...o }); commit(r.out, r.orig); return r; };
const read = (root, f) => fs.readFileSync(path.join(root, f), "utf8");

test("first build needs --new and writes both files: 17 columns, base column, meta first in the JSON", () => {
  const root = site(); const f = vintage(root, "2026-W44");
  assert.throws(() => build({ root, uk: [[f, "2026-W44"]] }), /give --new/);
  run(root, { root, uk: [[f, "2026-W44"]], new: true });
  const csv = read(root, CSV_OUT).split("\n");
  assert.strictEqual(csv[0], CORE + FLOW + ",base");
  assert.strictEqual(csv[1], `2026-W44,${AT},1,headline,,,99.7238,-0.2055,,4333,0.9823,ok,,,,,2026-W42`);
  assert.strictEqual(csv.length, 7); // header + 5 rows + final newline
  const items = JSON.parse(read(root, JSON_OUT));
  assert.strictEqual(items[0].recordType, "meta"); assert.strictEqual(items.length, 6);
  assert.strictEqual(readSite(root).last, "2026-W44");
});

test("older vintages without the four flow columns are padded with empty fields", () => {
  const root = site(); const f = vintage(root, "2026-W39", { flow: false, m: { base: "2026-W39" } });
  run(root, { uk: [[f, "2026-W39"]], new: true });
  assert.match(read(root, CSV_OUT).split("\n")[1], /,ok,,,,,2026-W39$/);
});

test("appends a newer vintage; refuses a repeated or older one, and --new once the files exist", () => {
  const root = site();
  run(root, { uk: [[vintage(root, "2026-W43"), "2026-W43"]], new: true });
  const f44 = vintage(root, "2026-W44");
  assert.throws(() => build({ root, uk: [[f44, "2026-W44"]], new: true }), /already exist/);
  run(root, { uk: [[f44, "2026-W44"]] });
  assert.strictEqual(readSite(root).lines.length, 10);
  assert.throws(() => build({ root, uk: [[f44, "2026-W44"]] }), /not newer/);
  assert.throws(() => build({ root, uk: [[vintage(root, "2026-W42"), "2026-W42"]] }), /not newer/);
});

test("the confirmation must match the file, and be a real ISO week", () => {
  const root = site(); const f = vintage(root, "2026-W44");
  assert.throws(() => build({ root, uk: [[f, "2026-W45"]], new: true }), /does not match/);
  assert.throws(() => build({ root, uk: [[f, "2026-W54"]], new: true }), /ISO week/);
});

test("meta checks: revision, licence, title, base, future publishedAt, unknown or wrongly typed keys", () => {
  const cases = [[{ runId: "abc" }, /unknown meta key runId/], [{ notCpi: false }, /notCpi/], [{ matchedTotal: "1" }, /matchedTotal/], [{ coverageWarnings: [1] }, /coverageWarnings/], [{ weighting: 2 }, /weighting/], [{ revision: 2 }, /revision/], [{ license: "MIT" }, /licence/], [{ title: "X" }, /title/], [{ base: "W42" }, /base/], [{ publishedAt: "2999-01-01T00:00:00Z" }, /future/], [{ publishedAt: "2026-02-30" }, /strict ISO/]];
  for (const [m, re] of cases) {
    const root = site(); const f = vintage(root, "2026-W44", { m });
    assert.throws(() => build({ root, uk: [[f, "2026-W44"]], new: true }), re);
  }
});

test("row checks: unknown status, record type, field, retailer or class; non-finite number; two headlines", () => {
  const bad = [
    [r => (r[1].status = "held"), /status/], [r => (r[1].recordType = "brand"), /record type/], [r => (r[1].extra = 1), /unknown field/],
    [r => (r[1].retailer = "lidl"), /retailer lidl/], [r => (r[3].class = "=cmd"), /class/], [r => (r[1].level = "100"), /finite/],
    [r => (r[1].recordType = "headline", r[1].retailer = ""), /one headline/], [r => (r[1].publishedAt = "2026-01-01"), /differs from the meta/],
  ];
  for (const [mut, re] of bad) {
    const root = site(); const rows = rowsFor("2026-W44"); mut(rows);
    const f = vintage(root, "2026-W44", { rows });
    assert.throws(() => build({ root, uk: [[f, "2026-W44"]], new: true }), re);
  }
});

test("the tool's CSV must match the JSON field for field, and must not be quoted or missing", () => {
  const root = site(); const rows = rowsFor("2026-W44");
  const good = toCsv(rows);
  const cases = [[good.replace("99.7238", "99.7239"), /differ in level/], [good.replace("tesco", '"tesco"'), /quoted/], [good.split("\n").slice(0, 3).join("\n") + "\n", /CSV has/], [good.replace("matchedShare", "share"), /unexpected column/]];
  for (const [csv, re] of cases) {
    const f = vintage(root, "2026-W44", { rows, csv });
    assert.throws(() => build({ root, uk: [[f, "2026-W44"]], new: true }), re);
  }
  const f = vintage(root, "2026-W44", { rows }); fs.unlinkSync(f.replace(/\.json$/, ".csv"));
  assert.throws(() => build({ root, uk: [[f, "2026-W44"]], new: true }), /CSV of the same vintage/);
});

test("numbers keep the tool's text (100.0 stays 100.0 when the JSON value is 100)", () => {
  const root = site(); const rows = rowsFor("2026-W44");
  const f = vintage(root, "2026-W44", { rows, csv: toCsv(rows).replace(",aldi,,100,", ",aldi,,100.0,") });
  run(root, { uk: [[f, "2026-W44"]], new: true });
  assert.match(read(root, CSV_OUT), /,aldi,,100\.0,/);
});

test("--check fails when the site files disagree, or only one exists", () => {
  const root = site(); run(root, { uk: [[vintage(root, "2026-W44"), "2026-W44"]], new: true });
  const noPage = cp.spawnSync(process.execPath, [SCRIPT, "--check", "--root", root], { encoding: "utf8" });
  assert.strictEqual(noPage.status, 1); assert.match(noPage.stderr, /shelf-price-index\/index\.html not found/);
  pageWith(root, MARKETS.uk.page, "2026-W44");
  assert.strictEqual(cp.spawnSync(process.execPath, [SCRIPT, "--check", "--root", root], { encoding: "utf8" }).status, 0);
  fs.writeFileSync(path.join(root, CSV_OUT), read(root, CSV_OUT).replace("100.0653", "100.0654"));
  const r = cp.spawnSync(process.execPath, [SCRIPT, "--check", "--root", root], { encoding: "utf8" });
  assert.strictEqual(r.status, 1); assert.match(r.stderr, /differ in level/);
  fs.unlinkSync(path.join(root, JSON_OUT));
  assert.throws(() => readSite(root), /only one of/);
});

test("a failed build writes nothing; arguments pair up", () => {
  const root = site(); run(root, { uk: [[vintage(root, "2026-W43"), "2026-W43"]], new: true });
  const before = read(root, CSV_OUT);
  const rows = rowsFor("2026-W44"); rows[0].status = "held";
  const r = cp.spawnSync(process.execPath, [SCRIPT, "--root", root, "--uk", vintage(root, "2026-W44", { rows }), "--confirm-uk", "2026-W44"], { encoding: "utf8" });
  assert.strictEqual(r.status, 1); assert.match(r.stderr, /NOTHING WRITTEN/);
  assert.strictEqual(read(root, CSV_OUT), before);
  assert.deepStrictEqual(parseArgs(["--uk", "a.json", "--confirm-uk", "2026-W44", "--uk", "b.json", "--confirm-uk", "2026-W45"]).uk, [["a.json", "2026-W44"], ["b.json", "2026-W45"]]);
  assert.throws(() => parseArgs(["--uk", "a.json"]), /without its/);
  assert.throws(() => parseArgs(["--confirm-uk", "2026-W44"]), /without a --uk/);
  assert.throws(() => parseArgs(["--nz", "x"]), /unknown argument/);
  assert.throws(() => parseArgs(["--au", "x"]), /--au without its --confirm-au/);
  assert.throws(() => parseArgs(["--uk", "a.json", "--confirm-au", "2026-W44"]), /--confirm-au without a --au/);
  assert.deepStrictEqual(parseArgs(["--au", "a.json", "--confirm-au", "2026-W44"]).au, [["a.json", "2026-W44"]]);
});

test("an empty coverageWarnings list is left out of the JSON; a non-empty one is kept", () => {
  const root = site();
  run(root, { uk: [[vintage(root, "2026-W43", { m: { coverageWarnings: [] } }), "2026-W43"], [vintage(root, "2026-W44", { m: { coverageWarnings: ["aldi: fewer products"] } }), "2026-W44"]], new: true });
  const metas = JSON.parse(read(root, JSON_OUT)).filter(i => i.recordType === "meta");
  assert.ok(!("coverageWarnings" in metas[0]));
  assert.deepStrictEqual(metas[1].coverageWarnings, ["aldi: fewer products"]);
});

test("a failed rename deletes a new file again instead of leaving it empty, and restores an existing one", () => {
  const root = site();
  const fresh = path.join(root, "new.txt"), old = path.join(root, "old.txt"), blocked = path.join(root, "blocked");
  fs.writeFileSync(old, "before"); fs.mkdirSync(blocked); fs.writeFileSync(path.join(blocked, "x"), "x");
  const out = new Map([[fresh, "a"], [old, "b"], [blocked, "c"]]);
  const orig = new Map([[fresh, null], [old, "before"], [blocked, "?"]]);
  assert.throws(() => commit(out, orig), /could not replace a file/);
  assert.ok(!fs.existsSync(fresh));
  assert.strictEqual(fs.readFileSync(old, "utf8"), "before");
  assert.ok(!fs.readdirSync(root).some(f => f.endsWith(".stamp-tmp")));
});

// ---- the headline file, the AU site JSON and the page check
const AU_META = { title: "AU Online Shelf-Price Index", base: "2026-W41", retailers: ["coles", "aldi_au"], classes: ["dairy-eggs", "pet"], currency: "AUD", headlineDefinition: "like-for-like", headlineClasses: ["dairy-eggs"], colesStatus: "partial", colesProducts: 6844, colesRangeSharePct: 22.4, colesRequests: 170, woolworthsStore: "1101", classRulesVersion: "fa356eec3b57" };
const auRows = v => [row(v, "headline", "", "", 100.1408, {}, false), row(v, "retailer", "coles", "", 99.5, {}, false), row(v, "retailer", "aldi_au", "", 100, {}, false), row(v, "retailer_like_for_like", "coles", "", 99.4, {}, false), row(v, "class", "", "pet", 101.5, {}, false)];
function auVintage(root, v, m = {}, rows) {
  const rs = rows || auRows(v);
  const jp = path.join(root, `au-shelf-price-index-${v}.json`);
  fs.writeFileSync(jp, JSON.stringify({ meta: meta(v, { ...AU_META, ...m }), rows: rs }));
  fs.writeFileSync(jp.replace(/\.json$/, ".csv"), toCsv(rs, false));
  return jp;
}
const pageWith = (root, file, v) => { fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true }); fs.writeFileSync(path.join(root, file), `<!--static-latest:start-->\n<p id="static-latest" data-vintage="${v}">x</p>\n<!--static-latest:end-->\n`); };

test("the headline file holds exactly the headline rows of the JSON, in the same item text, and follows each build", () => {
  const root = site();
  run(root, { uk: [[vintage(root, "2026-W43"), "2026-W43"]], new: true });
  run(root, { uk: [[vintage(root, "2026-W44"), "2026-W44"]] });
  const heads = JSON.parse(read(root, HEADLINE_OUT)), all = JSON.parse(read(root, JSON_OUT));
  assert.deepStrictEqual(heads, all.filter(i => i.recordType === "headline"));
  assert.deepStrictEqual(heads.map(h => h.vintage), ["2026-W43", "2026-W44"]);
  for (const line of read(root, HEADLINE_OUT).split("\n").slice(1, -2)) assert.ok(read(root, JSON_OUT).includes(line.replace(/,$/, "")));
  fs.writeFileSync(path.join(root, HEADLINE_OUT), read(root, HEADLINE_OUT).replace("99.7238", "99.7239"));
  assert.throws(() => readSite(root), /not the headline rows/);
});

test("--derive rewrites only the headline file; --check needs it", () => {
  const root = site(); run(root, { uk: [[vintage(root, "2026-W44"), "2026-W44"]], new: true });
  const json = read(root, JSON_OUT), csv = read(root, CSV_OUT), head = read(root, HEADLINE_OUT);
  fs.unlinkSync(path.join(root, HEADLINE_OUT));
  assert.throws(() => checkAll(root), /run --derive/);
  const r = cp.spawnSync(process.execPath, [SCRIPT, "--derive", "--root", root], { encoding: "utf8" });
  assert.strictEqual(r.status, 0);
  assert.strictEqual(read(root, HEADLINE_OUT), head); assert.strictEqual(read(root, JSON_OUT), json); assert.strictEqual(read(root, CSV_OUT), csv);
  fs.writeFileSync(path.join(root, HEADLINE_OUT), "[]\n"); // a wrong headline file: --derive repairs it
  assert.strictEqual(cp.spawnSync(process.execPath, [SCRIPT, "--derive", "--root", root], { encoding: "utf8" }).status, 0);
  assert.strictEqual(read(root, HEADLINE_OUT), head);
  assert.throws(() => build({ root, derive: true, uk: [[vintage(root, "2026-W45"), "2026-W45"]] }), /do not give it with/);
});

test("AU: a site JSON only (no CSV, no headline file), with its own meta keys and record type; UK rules still refuse them", () => {
  const root = site();
  run(root, { au: [[auVintage(root, "2026-W44"), "2026-W44"]], new: true });
  run(root, { au: [[auVintage(root, "2026-W45", { coverageWarnings: ["coles"] }), "2026-W45"]] });
  const items = JSON.parse(read(root, AU_JSON_OUT));
  assert.strictEqual(items.length, 12); assert.strictEqual(items[0].currency, "AUD"); assert.deepStrictEqual(items[6].coverageWarnings, ["coles"]);
  assert.ok(items.some(i => i.recordType === "retailer_like_for_like" && i.retailer === "coles"));
  assert.deepStrictEqual(fs.readdirSync(path.join(root, "data")), ["au-shelf-price-index.json"]);
  assert.strictEqual(readSite(root, MARKETS.au).last, "2026-W45");
  assert.strictEqual(readSite(root), null); // no UK files were written
  assert.throws(() => build({ root, au: [[auVintage(root, "2026-W46", { colesProducts: "many" }), "2026-W46"]] }), /colesProducts/);
  assert.throws(() => build({ root, au: [[auVintage(root, "2026-W46", { headlineClasses: ["=cmd"] }), "2026-W46"]] }), /headlineClasses/);
  assert.throws(() => build({ root, au: [[auVintage(root, "2026-W46", { headlineClasses: [["pet"]] }), "2026-W46"]] }), /headlineClasses/);
  assert.throws(() => build({ root, au: [[auVintage(root, "2026-W46", { runId: "abc" }), "2026-W46"]] }), /unknown meta key runId/);
  assert.throws(() => build({ root, au: [[auVintage(root, "2026-W46", { title: "UK Online Shelf-Price Index" }), "2026-W46"]] }), /title/);
  const r2 = site(); const rows = rowsFor("2026-W44"); rows[3].recordType = "retailer_like_for_like";
  assert.throws(() => build({ root: r2, uk: [[vintage(r2, "2026-W44", { rows }), "2026-W44"]], new: true }), /record type/);
  assert.throws(() => build({ root: r2, uk: [[vintage(r2, "2026-W44", { m: { currency: "GBP" } }), "2026-W44"]], new: true }), /unknown meta key currency/);
});

test("AU: the tool's CSV is still checked against the JSON, and --new is refused once the file exists", () => {
  const root = site(); const f = auVintage(root, "2026-W44");
  fs.writeFileSync(f.replace(/\.json$/, ".csv"), toCsv(auRows("2026-W44"), false).replace("100.1408", "100.1409"));
  assert.throws(() => build({ root, au: [[f, "2026-W44"]], new: true }), /differ in level/);
  run(root, { au: [[auVintage(root, "2026-W44"), "2026-W44"]], new: true });
  assert.throws(() => build({ root, au: [[auVintage(root, "2026-W45"), "2026-W45"]], new: true }), /already exist/);
});

test("--check: a page's stamped week must be the last week in its data file; the AU file is needed once the AU page exists", () => {
  const root = site();
  run(root, { uk: [[vintage(root, "2026-W44"), "2026-W44"]], new: true });
  pageWith(root, MARKETS.uk.page, "2026-W44");
  assert.strictEqual(checkAll(root).length, 1);
  pageWith(root, MARKETS.uk.page, "2026-W45"); // stamped, but the week was not added to the data file
  assert.throws(() => checkAll(root), /stamped 2026-W45 but the last week in data\/uk-shelf-price-index\.json is 2026-W44/);
  pageWith(root, MARKETS.uk.page, "2026-W44");
  pageWith(root, MARKETS.au.page, "2026-W44");
  assert.throws(() => checkAll(root), /au-shelf-price-index\.json does not exist/);
  run(root, { au: [[auVintage(root, "2026-W44"), "2026-W44"]], new: true });
  assert.strictEqual(checkAll(root).length, 2);
  const r = cp.spawnSync(process.execPath, [SCRIPT, "--check", "--root", root], { encoding: "utf8" });
  assert.strictEqual(r.status, 0); assert.match(r.stdout, /au-shelf-price-index\.json: 5 rows, last vintage 2026-W44/);
});

test("a site JSON whose vintage has no headline row, or two, is refused", () => {
  const root = site(); run(root, { au: [[auVintage(root, "2026-W44"), "2026-W44"]], new: true });
  const items = JSON.parse(read(root, AU_JSON_OUT));
  fs.writeFileSync(path.join(root, AU_JSON_OUT), JSON.stringify(items.filter(i => i.recordType !== "headline")));
  assert.throws(() => readSite(root, MARKETS.au), /exactly one headline row/);
});

test("the pages read the site files and never fetch the dataset", () => {
  const top = path.join(__dirname, "..", "..");
  const want = { "index.html": HEADLINE_OUT, "press/index.html": HEADLINE_OUT, "shelf-price-index/index.html": JSON_OUT, "au-shelf-price-index/index.html": AU_JSON_OUT };
  for (const [page, file] of Object.entries(want)) {
    const html = fs.readFileSync(path.join(top, page), "utf8");
    assert.ok(html.includes(`"/${file}"`), `${page} should read /${file}`);
    assert.doesNotMatch(html, /fetch\([^)]*api\.apify\.com/);
    assert.doesNotMatch(html, /fetch\(`?\$?\{?BASE\}?\?/); // the old call: fetch(`${BASE}?format=json...`)
  }
});

test("the announcement bar on the home page and /notices/ carries a real last-day date, and site.js hides it after that day", () => {
  const top = path.join(__dirname, "..", "..");
  for (const page of ["index.html", "notices/index.html"]) {
    const m = fs.readFileSync(path.join(top, page), "utf8").match(/<div class="strip" id="strip"[^>]*data-until="(\d{4}-\d{2}-\d{2})"/);
    assert.ok(m, `${page}: the bar needs data-until`);
    assert.strictEqual(new Date(m[1] + "T00:00:00Z").toISOString().slice(0, 10), m[1]);
  }
  assert.match(fs.readFileSync(path.join(top, "assets/site.js"), "utf8"), /data-until[\s\S]{0,200}toISOString\(\)\.slice\(0, 10\) > until\) strip\.hidden = true/);
});
