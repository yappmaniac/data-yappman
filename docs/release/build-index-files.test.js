// Tests for docs/release/build-index-files.js.   node --test docs/release/build-index-files.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const { build, readSite, parseArgs, CSV_OUT, JSON_OUT } = require("./build-index-files.js");
const { commit } = require("./stamp-latest.js");

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

test("meta checks: revision, licence, title, base, future publishedAt", () => {
  const cases = [[{ revision: 2 }, /revision/], [{ license: "MIT" }, /licence/], [{ title: "X" }, /title/], [{ base: "W42" }, /base/], [{ publishedAt: "2999-01-01T00:00:00Z" }, /future/], [{ publishedAt: "2026-02-30" }, /strict ISO/]];
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
  assert.throws(() => parseArgs(["--au", "x"]), /unknown argument/);
});
