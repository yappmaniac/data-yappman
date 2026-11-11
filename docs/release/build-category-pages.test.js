// Tests for docs/release/build-category-pages.js.   node --test docs/release/build-category-pages.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const { build, check, write, load, LABELS, DIR, SRC } = require("./build-category-pages.js");

const SCRIPT = path.join(__dirname, "build-category-pages.js");
const TPL = '<!DOCTYPE html>\n<html lang="en-GB">\n<head>\n<title>x</title>\n<meta name="description" content="x">\n<meta property="og:title" content="x">\n<meta property="og:description" content="x">\n<meta property="og:url" content="x">\n<link rel="canonical" href="x">\n</head>\n<body>\n<nav><button class="nav-top active" aria-current="true">Trust</button></nav>\n<main id="main" tabindex="-1">\n<h1>t</h1>\n</main>\n<footer>f</footer>\n</body></html>\n';
const CLASSES = Object.keys(LABELS);
const meta = (v, base, classes = CLASSES) => ({ vintage: v, publishedAt: v === "2026-W45" ? "2026-11-09T12:00:00Z" : "2026-11-02T12:00:00Z", revision: 1, recordType: "meta", base, classes });
const crow = (v, c, level, status = "ok") => ({ vintage: v, recordType: "class", retailer: "", class: c, level, weekOnWeekPct: 0.05, matched: 1234, status });
const rrow = (v, c, ret, level) => ({ vintage: v, recordType: "retailer_class", retailer: ret, class: c, level, matched: 321, status: "ok" });
function site(over = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cats-"));
  fs.mkdirSync(path.join(root, "data")); fs.mkdirSync(path.join(root, "notices/w41-skipped"), { recursive: true });
  fs.writeFileSync(path.join(root, "notices/w41-skipped/index.html"), TPL);
  const items = [meta("2026-W44", "2026-W42"), meta("2026-W45", "2026-W42", over.classes)];
  for (const c of over.classes || CLASSES) { items.push(crow("2026-W44", c, 100, "base"), crow("2026-W45", c, c === "pet" ? 100.5 : 100.2)); for (const r of ["tesco", "aldi"]) items.push(rrow("2026-W45", c, r, 100.1)); }
  fs.writeFileSync(path.join(root, SRC), JSON.stringify(items));
  return root;
}
const rd = (root, f) => fs.readFileSync(path.join(root, f), "utf8");

test("one page per class plus an index, each with the chart, tables, history note, licence and citation", () => {
  const root = site(); const files = build(root);
  assert.strictEqual(files.size, 17);
  const pet = files.get(`${DIR}/pet/index.html`);
  assert.match(pet, /<h1>UK shelf prices: Pet<\/h1>/); assert.match(pet, /<svg viewBox/); assert.match(pet, /level 100\.5, \+0\.05% on the week before/);
  assert.match(pet, /history starts on 27 September 2026/); assert.match(pet, /Week 41 has no data/); assert.match(pet, /CC BY 4\.0/);
  assert.match(pet, /canonical" href="https:\/\/data\.yappman\.com\/shelf-price-index\/categories\/pet\/"/);
  assert.doesNotMatch(pet, /nav-top active/);
  assert.match(files.get(`${DIR}/index.html`), /href="\/shelf-price-index\/categories\/dairy-eggs\/"/);
});

test("only the free index's own figures: no product, image, description or script", () => {
  for (const s of build(site()).values()) assert.doesNotMatch(s, /<img|\bEAN\b|image|retailerProductId|productName|<script/i);
});

test("deterministic: a rebuild is byte-identical; --check passes, and fails when a page is edited, missing, or the data moves", () => {
  const root = site(); write(root, build(root));
  const first = rd(root, `${DIR}/meat/index.html`);
  write(root, build(root)); assert.strictEqual(rd(root, `${DIR}/meat/index.html`), first);
  assert.deepStrictEqual(check(root), []);
  fs.writeFileSync(path.join(root, `${DIR}/meat/index.html`), first.replace("Meat", "Beef"));
  assert.match(check(root).join("\n"), /meat\/index\.html is not what the data file gives/);
  fs.unlinkSync(path.join(root, `${DIR}/fish/index.html`)); assert.match(check(root).join("\n"), /fish\/index\.html does not exist/);
  write(root, build(root));
  const items = JSON.parse(rd(root, SRC)); items.push(crow("2026-W46", "pet", 100.9)); items.push(meta("2026-W46", "2026-W42"));
  fs.writeFileSync(path.join(root, SRC), JSON.stringify(items));
  assert.match(check(root).join("\n"), /pet\/index\.html is not what the data file gives/);
});

test("a class with no label, no rows or a bad week stops the build; text from the data is escaped", () => {
  assert.throws(() => build(site({ classes: [...CLASSES, "mystery"] })), /no label/);
  const r2 = site(); const items = JSON.parse(rd(r2, SRC)).filter(r => !(r.recordType === "class" && r.class === "pet")); fs.writeFileSync(path.join(r2, SRC), JSON.stringify(items));
  assert.throws(() => build(r2), /class "pet" has no rows/);
  const r3 = site(); const i3 = JSON.parse(rd(r3, SRC)); i3[3].vintage = "W45"; fs.writeFileSync(path.join(r3, SRC), JSON.stringify(i3));
  assert.throws(() => build(r3), /week/);
  const r4 = site(); const i4 = JSON.parse(rd(r4, SRC)); i4.find(r => r.recordType === "class").vintage = "2026-W44"; i4.find(r => r.recordType === "meta").vintage = "2026-W44";
  assert.doesNotMatch([...build(r4).values()].join(""), /<b>/);
});

test("the two series are kept apart: the chart uses only the current base, the table shows both with their base week", () => {
  const p = build(site()).get(`${DIR}/meat/index.html`);
  assert.strictEqual((p.match(/<circle class="dot"/g) || []).length, 1 + 1);
  assert.match(p, /<td>2026-W44<\/td><td>2026-W42<\/td>/);
});

test("a thin retailer cell (carried or insufficient) is shown as not updated, never as a level, and is left out of the chart", () => {
  const root = site(); const items = JSON.parse(rd(root, SRC));
  items.push({ vintage: "2026-W45", recordType: "retailer_class", retailer: "asda", class: "oils-fats", level: 100, matched: 1, status: "carried" });
  fs.writeFileSync(path.join(root, SRC), JSON.stringify(items));
  const p = build(root).get(`${DIR}/oils-fats/index.html`);
  assert.match(p, /<td>Asda<\/td><td class="num">not updated<\/td><td class="num">1<\/td>/);
  assert.doesNotMatch(p, /<td>Asda<\/td><td class="num">100\.0/);
});

test("running text uses a noun phrase for every class, and the catch-all classes say what they hold", () => {
  const files = build(site());
  assert.match(files.get(`${DIR}/pet/index.html`), /shelf prices of pet products moved/);
  assert.match(files.get(`${DIR}/other/index.html`), /shelf prices of products in no other category moved/);
  assert.match(files.get(`${DIR}/other/index.html`), /a mixed group/);
  assert.match(files.get(`${DIR}/meat/index.html`), /does not start at zero/);
});

test("the command line: write, check, usage error, and 'NOTHING WRITTEN' when the data file is missing", () => {
  const root = site();
  let r = cp.spawnSync(process.execPath, [SCRIPT, "--root", root], { encoding: "utf8" }); assert.strictEqual(r.status, 0); assert.match(r.stdout, /wrote 17 pages/);
  r = cp.spawnSync(process.execPath, [SCRIPT, "--check", "--root", root], { encoding: "utf8" }); assert.strictEqual(r.status, 0);
  assert.strictEqual(cp.spawnSync(process.execPath, [SCRIPT, "--bogus"], { encoding: "utf8" }).status, 2);
  fs.unlinkSync(path.join(root, SRC)); r = cp.spawnSync(process.execPath, [SCRIPT, "--root", root], { encoding: "utf8" }); assert.strictEqual(r.status, 1); assert.match(r.stderr, /NOTHING WRITTEN/);
});

test("the committed pages agree with the committed data (when the site has them)", () => {
  const top = path.join(__dirname, "..", "..");
  if (!fs.existsSync(path.join(top, DIR, "index.html"))) return;
  assert.deepStrictEqual(check(top), []);
  for (const c of load(top).classes) assert.ok(fs.existsSync(path.join(top, DIR, c, "index.html")), c);
});

test("the script uses only fs and path: no network, eval or child process", () => {
  const src = fs.readFileSync(SCRIPT, "utf8");
  assert.doesNotMatch(src, /require\(["'](https?|net|dgram|dns|tls|child_process|vm|worker_threads)["']\)/);
  assert.doesNotMatch(src, /\beval\s*\(|new Function|fetch\s*\(|process\.env/);
  assert.deepStrictEqual([...src.matchAll(/require\(["']([^"']+)["']\)/g)].map(m => m[1]).sort(), ["fs", "path"]);
});
