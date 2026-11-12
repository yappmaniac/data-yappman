// Tests for docs/release/build-coverage-page.js.   node --test docs/release/build-coverage-page.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const { build, check, write, weekOf, weekMonday, weeksBetween, OUT, REF } = require("./build-coverage-page.js");

const SCRIPT = path.join(__dirname, "build-coverage-page.js");
const TPL = '<!DOCTYPE html>\n<html>\n<head>\n<title>x</title>\n<meta name="description" content="x">\n<meta property="og:title" content="x">\n<meta property="og:description" content="x">\n<meta property="og:url" content="x">\n<link rel="canonical" href="x">\n</head>\n<body>\n<a class="nav-top active" aria-current="true">Trust</a>\n<main id="main" tabindex="-1">\nold\n</main>\n<footer>f</footer>\n</body>\n</html>\n';
const meta = (v, base, pub, matched) => ({ vintage: v, publishedAt: pub + "T07:00:00Z", revision: 1, recordType: "meta", base, matchedTotal: matched });
const ret = (v, r) => ({ vintage: v, recordType: "retailer", retailer: r, class: "", level: 100 });
function ukItems() {
  const weeks = [["2026-W39", "2026-W39", "2026-10-05", null], ["2026-W40", "2026-W39", "2026-10-05", 71399], ["2026-W42", "2026-W42", "2026-10-26", null], ["2026-W43", "2026-W42", "2026-10-26", 74503]];
  const out = [];
  for (const [v, b, p, m] of weeks) { out.push(meta(v, b, p, m)); for (const r of ["tesco", "sainsburys", "asda", "aldi"]) out.push(ret(v, r)); }
  return out;
}
function auItems() {
  const out = [];
  for (const [v, p, m] of [["2026-W41", "2026-10-15", null], ["2026-W42", "2026-10-15", 23266], ["2026-W43", "2026-10-26", 23161]]) { out.push(meta(v, "2026-W41", p, m)); for (const r of ["coles", "woolworths", "aldi_au"]) out.push(ret(v, r)); }
  return out;
}
const REFDATA = () => ({
  schema: 1, retrievedOn: "2026-11-12",
  claims: {
    "weekly-start": { confirmed: true, source: "licences" }, "daily-basket-start": { confirmed: true, source: "methodology" },
    "snapshot-rows": { confirmed: true, source: "method" }, "morrisons-from-w44": { confirmed: true, source: "licences" },
    "w41-three-retailers": { confirmed: true, source: "notice" }, "actor-history-sentence": { confirmed: true, source: "README" }, "morrisons-no-price-history": { confirmed: true, source: "UK session code evidence" },
    "aldi-w41": { confirmed: false, source: "" }, "morrisons-w44-w45": { confirmed: false, source: "" },
  },
  uk: {
    weeklyStart: { claim: "weekly-start", week: "2026-W39", date: "2026-09-27" }, dailyBasketStart: { claim: "daily-basket-start", date: "2026-09-24" },
    snapshotRows: { claim: "snapshot-rows", sentence: "Over 75,000 products a week in the weekly snapshots (75,835 in the week 43 snapshot of 25 October 2026)." },
    retailers: [
      { id: "tesco", name: "Tesco", inIndex: true, heldFrom: "2026-W39", notHeld: ["2026-W41"], notHeldClaim: "w41-three-retailers" },
      { id: "sainsburys", name: "Sainsbury's", inIndex: true, heldFrom: "2026-W39", notHeld: ["2026-W41"], notHeldClaim: "w41-three-retailers" },
      { id: "asda", name: "Asda", inIndex: true, heldFrom: "2026-W39", notHeld: ["2026-W41"], notHeldClaim: "w41-three-retailers" },
      { id: "aldi", name: "Aldi", inIndex: true, heldFrom: "2026-W39", notHeld: [], notHeldClaim: "aldi-w41" },
      { id: "morrisons", name: "Morrisons", inIndex: false, heldFrom: "2026-W44", heldFromClaim: "morrisons-from-w44", heldThrough: "2026-W45", heldThroughClaim: "morrisons-w44-w45" },
    ],
  },
  au: { retailers: [{ id: "coles", name: "Coles", inIndex: true, heldFrom: "2026-W41" }, { id: "woolworths", name: "Woolworths", inIndex: true, heldFrom: "2026-W41" }, { id: "aldi_au", name: "Aldi Australia", inIndex: true, heldFrom: "2026-W41" }] },
  notices: { "2026-W41": "/notices/w41-skipped/" },
});
function site(ref = REFDATA(), uk = ukItems(), au = auItems()) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cov-"));
  fs.mkdirSync(path.join(root, "data")); fs.mkdirSync(path.join(root, "notices/w41-skipped"), { recursive: true });
  fs.writeFileSync(path.join(root, "notices/w41-skipped/index.html"), TPL);
  fs.writeFileSync(path.join(root, "data/uk-shelf-price-index.json"), JSON.stringify(uk));
  fs.writeFileSync(path.join(root, "data/au-shelf-price-index.json"), JSON.stringify(au));
  fs.writeFileSync(path.join(root, REF), JSON.stringify(ref));
  return root;
}
const page = root => build(root).get(OUT);

test("ISO week arithmetic needs no clock and handles year ends", () => {
  assert.strictEqual(weekOf(new Date(Date.UTC(2026, 9, 5))), "2026-W41");
  assert.strictEqual(weekOf(new Date(Date.UTC(2026, 11, 28))), "2026-W53");
  assert.strictEqual(weekOf(new Date(Date.UTC(2027, 0, 3))), "2026-W53");
  assert.strictEqual(weekOf(new Date(Date.UTC(2027, 0, 4))), "2027-W01");
  assert.strictEqual(weekMonday("2026-W39").toISOString().slice(0, 10), "2026-09-21");
  assert.deepStrictEqual(weeksBetween("2026-W52", "2027-W02"), ["2026-W52", "2026-W53", "2027-W01", "2027-W02"]);
});

test("weeks and counts are computed from the index files", () => {
  const p = page(site());
  assert.match(p, /<td>Tesco<\/td><td>2026-W39<\/td><td class="num">4<\/td><td class="num">4<\/td><td><a href="\/notices\/w41-skipped\/">2026-W41<\/a><\/td>/);
  assert.match(p, /<td>Coles<\/td><td>2026-W41<\/td><td class="num">3<\/td>/);
  assert.match(p, /latest weekly release is 2026-W43, published 26 October 2026/);
  assert.match(p, /UK Online Shelf-Price Index<\/a><\/td><td>2026-W39<\/td><td>2026-W43<\/td><td class="num">4<\/td><td><a href="\/notices\/w41-skipped\/">2026-W41<\/a><\/td><td>2 series: base 2026-W39 \(2026-W39 to 2026-W40\); base 2026-W42 \(2026-W42 to 2026-W43\)\. Levels in different series cannot be compared\./);
  assert.match(p, /AU Online Shelf-Price Index<\/a><\/td><td>2026-W41<\/td><td>2026-W43<\/td><td class="num">3<\/td><td>none<\/td><td>One series, base 2026-W41 \(2026-W41 to 2026-W43\)\./);
  assert.match(p, /<td>2026-W40<\/td><td class="num">71,399<\/td><td class="num">&mdash;<\/td>/);
  assert.match(p, /<td>2026-W41<\/td><td class="num">&mdash;<\/td><td class="num">base week<\/td>/);
});

test("an unconfirmed claim is never printed: Aldi's week 41 and Morrisons' held weeks are dashes", () => {
  const p = page(site());
  assert.match(p, /<td>Aldi<\/td><td>2026-W39<\/td><td class="num">&mdash;<\/td><td class="num">4<\/td><td>&mdash;<\/td>/);
  assert.match(p, /<td>Morrisons<\/td><td>2026-W44<\/td><td class="num">&mdash;<\/td><td class="num">not in the index yet<\/td><td>&mdash;<\/td>/);
  assert.match(p, /A dash means this page does not state the figure\./);
  assert.match(p, /Morrisons is held from week 44 of 2026 and is not yet in the index\./);
  assert.doesNotMatch(p, /week 45/i);
});

test("once Aldi's week 41 is confirmed the cell is printed", () => {
  const ref = REFDATA(); ref.claims["aldi-w41"] = { confirmed: true, source: "UK session evidence" }; ref.uk.retailers[3].notHeld = [];
  assert.match(page(site(ref)), /<td>Aldi<\/td><td>2026-W39<\/td><td class="num">5<\/td><td class="num">4<\/td><td>none<\/td>/);
  const ref2 = REFDATA(); ref2.claims["aldi-w41"] = { confirmed: true, source: "UK session evidence" }; ref2.uk.retailers[3].notHeld = ["2026-W41"];
  assert.match(page(site(ref2)), /<td>Aldi<\/td>[^\n]*<a href="\/notices\/w41-skipped\/">2026-W41<\/a>/);
});

test("once Morrisons' weeks 44 and 45 are confirmed the held count is printed, with the weeks it covers", () => {
  const ref = REFDATA(); ref.claims["morrisons-w44-w45"] = { confirmed: true, source: "dataset metadata" };
  const p = page(site(ref));
  assert.match(p, /<td>Morrisons<\/td><td>2026-W44<\/td><td class="num">2 \(2026-W44 to 2026-W45\)<\/td><td class="num">not in the index yet<\/td><td>none<\/td>/);
  assert.match(p, /<td>Aldi<\/td>[^\n]*&mdash;<\/td><\/tr>/);                         // Aldi is still a dash while its claim is unconfirmed
  const bad = REFDATA(); bad.claims["morrisons-w44-w45"] = { confirmed: true, source: "dataset metadata" }; bad.uk.retailers[4].heldThrough = "2026-W43";
  assert.throws(() => build(site(bad)), /morrisons has a bad heldThrough/);
});

test("a claim marked confirmed without a source stops the build", () => {
  const ref = REFDATA(); ref.claims["snapshot-rows"].source = " ";
  assert.throws(() => build(site(ref)), /marked confirmed but has no source/);
});

test("a mandatory claim that is not confirmed stops the build", () => {
  for (const id of ["weekly-start", "daily-basket-start", "snapshot-rows", "actor-history-sentence", "morrisons-no-price-history"]) {
    const ref = REFDATA(); ref.claims[id] = { confirmed: false, source: "" };
    assert.throws(() => build(site(ref)), new RegExp(`claim ${id} is used on the page but is not confirmed`));
  }
});

test("Morrisons outside the index needs its claim confirmed", () => {
  const ref = REFDATA(); ref.claims["morrisons-from-w44"].confirmed = false;
  assert.throws(() => build(site(ref)), /morrisons-from-w44 is used on the page but is not confirmed/);
});

test("the reference file must agree with the index", () => {
  const ref = REFDATA(); ref.uk.retailers[0].heldFrom = "2026-W40";
  assert.throws(() => build(site(ref)), /tesco heldFrom 2026-W40 disagrees with the index \(first week 2026-W39\)/);
  const ref2 = REFDATA(); ref2.uk.weeklyStart.week = "2026-W38";
  assert.throws(() => build(site(ref2)), /weeklyStart 2026-W38 is not the first UK index week/);
  const ref3 = REFDATA(); ref3.uk.retailers[4].inIndex = true;
  assert.throws(() => build(site(ref3)), /marked inIndex but the index has no rows/);
});

test("a week missing from a published index must have a notice", () => {
  const ref = REFDATA(); delete ref.notices["2026-W41"];
  assert.throws(() => build(site(ref)), /no notice/);                                   // stops at the first guard that sees the gap
  ref.claims["w41-three-retailers"].confirmed = false; ref.claims["w41-three-retailers"].source = "";
  assert.throws(() => build(site(ref)), /UK index: week 2026-W41 was not published and .* has no notice/);
  const au = auItems().filter(r => r.vintage !== "2026-W42");
  assert.throws(() => build(site(REFDATA(), ukItems(), au)), /AU index: week 2026-W42 was not published/);
});

test("a confirmed not-held week needs a notice link", () => {
  const ref = REFDATA(); ref.uk.retailers[0].notHeld = ["2026-W40"];
  assert.throws(() => build(site(ref)), /tesco is shown as not holding 2026-W40 but there is no notice/);
});

test("the page says nothing earlier exists, makes no forward statement and keeps the rights wording", () => {
  const p = page(site());
  assert.match(p, /Nothing was collected before those dates, so there are no earlier weeks to supply, and we do not estimate or backfill them\./);
  assert.match(p, /27 September 2026 and the daily basket on 24 September 2026 \(it has no run on 25 September\)/);
  assert.doesNotMatch(p, /2027/); assert.doesNotMatch(p, /official|cheapest|complete data/i);
  assert.match(p, /no affiliation, endorsement or partnership is claimed/); assert.match(p, /not CPI and not a measure of prices paid/);
  assert.match(p, /public dataset under CC BY 4\.0, with history from 24 September 2026/);
  assert.match(p, /includePriceHistory option/); assert.match(p, /utm_campaign=coverage/);
});

test("the Actor paragraph keeps the supplied sentence and adds the clarifying clause about Morrisons", () => {
  const p = page(site());
  assert.match(p, /\(week 41 is missing at Tesco, Sainsbury&rsquo;s and Asda; there are none for Morrisons\)\. The Actor builds no weekly report\./);
  assert.match(p, /Price history is not offered for Morrisons yet, so its rows carry an empty price history and are never charged for it; the Morrisons weekly snapshots we hold \(from 2026-W44\) are not yet part of that\./);
  const ref = REFDATA(); ref.uk.retailers[4].heldFrom = "2026-W45";
  assert.match(page(site(ref)), /weekly snapshots we hold \(from 2026-W45\)/);              // follows the reference file
  ref.uk.retailers.pop();
  assert.doesNotMatch(page(site(ref)), /Price history is not offered/);                       // no outside retailer, no clause
});

test("the page uses the site template and drops the active menu state", () => {
  const p = page(site());
  assert.match(p, /<title>How much history we hold — Yappman Data<\/title>/);
  assert.match(p, /<link rel="canonical" href="https:\/\/data\.yappman\.com\/coverage\/">/);
  assert.doesNotMatch(p, /nav-top active/); assert.match(p, /<footer>f<\/footer>/);
});

test("same inputs give a byte-identical page, --check passes after a build and fails after a change", () => {
  const root = site();
  assert.strictEqual(page(root), page(root));
  assert.ok(check(root).length > 0);
  write(root, build(root));
  assert.deepStrictEqual(check(root), []);
  fs.appendFileSync(path.join(root, OUT), "x");
  assert.match(check(root)[0], /is not what the data files give/);
});

test("a new week in the index changes the page with no edit to the reference file", () => {
  const uk = ukItems(); uk.push(meta("2026-W44", "2026-W42", "2026-11-02", 74335)); for (const r of ["tesco", "sainsburys", "asda", "aldi"]) uk.push(ret("2026-W44", r));
  const p = page(site(REFDATA(), uk));
  assert.match(p, /<td>Tesco<\/td><td>2026-W39<\/td><td class="num">5<\/td><td class="num">5<\/td>/); assert.match(p, /latest weekly release is 2026-W44/);
});

test("the command line: write, check, and a clean refusal with nothing written", () => {
  const root = site();
  assert.match(cp.execFileSync("node", [SCRIPT, "--root", root], { encoding: "utf8" }), /wrote coverage\/index\.html/);
  assert.match(cp.execFileSync("node", [SCRIPT, "--check", "--root", root], { encoding: "utf8" }), /agrees with the data files/);
  const ref = REFDATA(); ref.claims["snapshot-rows"].confirmed = false;
  const bad = site(ref);
  const r = cp.spawnSync("node", [SCRIPT, "--root", bad], { encoding: "utf8" });
  assert.strictEqual(r.status, 1); assert.match(r.stderr, /NOTHING WRITTEN/); assert.ok(!fs.existsSync(path.join(bad, OUT)));
});

test("no network is used", () => {
  const src = fs.readFileSync(SCRIPT, "utf8");
  assert.doesNotMatch(src, /require\("(https?|net|dns)"\)|fetch\(|XMLHttpRequest|Date\.now\(|new Date\(\)/);
});
