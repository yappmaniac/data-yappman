// Tests for docs/release/affiliate.js and check-affiliate-disclosure.js.   node --test docs/release/check-affiliate-disclosure.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const AFF = require("./affiliate.js");
const { check } = require("./check-affiliate-disclosure.js");

const SCRIPT = path.join(__dirname, "check-affiliate-disclosure.js");
const OK_LINK = `<a href="https://apify.com/yappman/uk-supermarket-price-scraper?${AFF.PARAM}" rel="sponsored">UK</a>`;
const page = (body, { header = true } = {}) => `<!DOCTYPE html>\n<html><body>\n<header class="site">x</header>\n<main id="main">\n${header ? "<header>\n<h1>T</h1>\n</header>\n" : ""}${body}\n</main>\n</body></html>\n`;
function site(files) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "aff-"));
  for (const [f, t] of Object.entries(files)) { fs.mkdirSync(path.dirname(path.join(root, f)), { recursive: true }); fs.writeFileSync(path.join(root, f), t); }
  return root;
}
const good = () => ({ "a/index.html": page(`${AFF.DISCLOSURE_HTML}\n<p>${OK_LINK}</p>`), "b/index.html": page("<p>no apify here</p>") });

test("withParam keeps an existing utm query and adds the parameter after it, once", () => {
  assert.strictEqual(AFF.withParam("https://apify.com/yappman/x"), "https://apify.com/yappman/x?fpr=wy5pu7");
  assert.strictEqual(AFF.withParam("https://apify.com/yappman/x?utm_source=a&amp;utm_campaign=b"), "https://apify.com/yappman/x?utm_source=a&amp;utm_campaign=b&amp;fpr=wy5pu7");
  const once = AFF.withParam("https://apify.com/yappman/x?utm_source=a");
  assert.strictEqual(AFF.withParam(once), once);
});

test("a consistent site passes", () => { assert.deepStrictEqual(check(site(good())), []); });

test("an affiliate link without the disclosure fails", () => {
  const f = good(); f["a/index.html"] = page(`<p>${OK_LINK}</p>`);
  assert.match(check(site(f)).join("\n"), /a\/index\.html: has 1 affiliate link\(s\) and 0 disclosure line\(s\)/);
});

test("a disclosure on a page with no affiliate link fails (a stale disclosure)", () => {
  const f = good(); f["b/index.html"] = page(`${AFF.DISCLOSURE_HTML}\n<p>nothing</p>`);
  assert.match(check(site(f)).join("\n"), /b\/index\.html: has a disclosure line but no affiliate link/);
});

test("two disclosures, or a changed disclosure text, fail", () => {
  const f = good(); f["a/index.html"] = page(`${AFF.DISCLOSURE_HTML}\n${AFF.DISCLOSURE_HTML}\n<p>${OK_LINK}</p>`);
  assert.match(check(site(f)).join("\n"), /needs exactly one/);
  const g = good(); g["a/index.html"] = page(`<p class="meta" id="affiliate-disclosure">We may earn something.</p>\n<p>${OK_LINK}</p>`);
  assert.match(check(site(g)).join("\n"), /not the standard text/);
});

test("an affiliate link without rel=sponsored fails", () => {
  const f = good(); f["a/index.html"] = page(`${AFF.DISCLOSURE_HTML}\n<p><a href="https://apify.com/yappman/x?${AFF.PARAM}">x</a></p>`);
  assert.match(check(site(f)).join("\n"), /an affiliate link without rel="sponsored"/);
});

test("the parameter on any other host, on Apify-owned pages or with another token fails", () => {
  for (const href of ["https://example.com/x?fpr=wy5pu7", "https://apify.com/store?fpr=wy5pu7", "https://apify.com/apify/web-scraper?fpr=wy5pu7"]) {
    const f = good(); f["a/index.html"] = page(`${AFF.DISCLOSURE_HTML}\n<p><a href="${href}" rel="sponsored">x</a></p>`);
    assert.match(check(site(f)).join("\n"), /not one of our own Actor pages/, href);
  }
  const g = good(); g["a/index.html"] = page(`${AFF.DISCLOSURE_HTML}\n<p><a href="https://apify.com/yappman/x?fpr=other" rel="sponsored">x</a></p>`);
  assert.match(check(site(g)).join("\n"), /fpr= is not our token/);
});

test("the parameter in the menu, in plain-text files or outside a link fails", () => {
  const menu = Array.from({ length: 8 }, (_, i) => `<a href="https://apify.com/yappman/a${i}?${AFF.PARAM}" rel="sponsored">a</a>`).join("");
  const f = good(); f["a/index.html"] = page(`${AFF.DISCLOSURE_HTML}\n${menu}`);
  assert.match(check(site(f)).join("\n"), /an affiliate link in the menu/);
  const g = good(); g["llms.txt"] = "https://apify.com/yappman/x?fpr=wy5pu7\n";
  assert.match(check(site(g)).join("\n"), /llms\.txt: carries fpr=/);
  const h = good(); h["b/index.html"] = page(`<script type="application/ld+json">{"url":"https://apify.com/yappman/x?fpr=wy5pu7"}</script>`);
  assert.match(check(site(h)).join("\n"), /appears 1 time\(s\) outside a link's href/);
});

test("where the page has its own header, the disclosure must come before the first affiliate link", () => {
  const f = good(); f["a/index.html"] = page(`<p>${OK_LINK}</p>\n${AFF.DISCLOSURE_HTML}`);
  assert.match(check(site(f)).join("\n"), /the disclosure comes after the first affiliate link/);
  const home = good(); home["a/index.html"] = page(`<p>${OK_LINK}</p>\n${AFF.DISCLOSURE_HTML}`, { header: false });
  assert.deepStrictEqual(check(site(home)), []);                                           // no page header: it may close the main text
});

test("links without the parameter are not the checker's business", () => {
  const f = good(); f["b/index.html"] = page(`<p><a href="https://apify.com/yappman/x?utm_source=a">x</a> <a href="https://apify.com/store">s</a></p>`);
  assert.deepStrictEqual(check(site(f)), []);
});

test("the command line passes a good site and fails a bad one", () => {
  assert.match(cp.execFileSync("node", [SCRIPT, "--root", site(good())], { encoding: "utf8" }), /consistent/);
  const f = good(); f["a/index.html"] = page(`<p>${OK_LINK}</p>`);
  const r = cp.spawnSync("node", [SCRIPT, "--root", site(f)], { encoding: "utf8" });
  assert.strictEqual(r.status, 1); assert.match(r.stderr, /needs exactly one/);
});

test("the live site passes the checker", () => {
  const root = path.join(__dirname, "..", "..");
  assert.deepStrictEqual(check(root), []);
});
