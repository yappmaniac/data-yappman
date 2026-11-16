// Offline tests for the affiliate click event in assets/site.js.   node --test docs/release/site-referral-click.test.js
// site.js runs in a stub browser: no DOM, no network, no Umami. The test checks what is sent, when, and that nothing else is.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const AFF = require("./affiliate.js");

const SRC = fs.readFileSync(path.join(__dirname, "..", "..", "assets", "site.js"), "utf8");

function browser({ umami = true, pathname = "/licences/" } = {}) {
  const calls = [], handlers = {};
  const ctx = {
    document: { querySelector: () => null, getElementById: () => null, addEventListener: (t, f) => { (handlers[t] = handlers[t] || []).push(f); } },
    location: { pathname, href: "https://data.yappman.com" + pathname, hash: "", replace() {} },
    URL, sessionStorage: { getItem: () => null, setItem() {} }, setTimeout, clearTimeout,
  };
  ctx.window = ctx;
  if (umami) ctx.umami = { track: (name, data) => calls.push([name, JSON.parse(JSON.stringify(data))]) };   // plain copy: the page's objects live in another realm
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  const link = href => ({ target: { closest: sel => (sel === "a[href]" ? { href } : null) } });
  return { calls, handlers, fire: (type, e) => (handlers[type] || []).forEach(f => f(e)), link };
}
const AFFIL = `https://apify.com/yappman/uk-supermarket-price-scraper?${AFF.PARAM}`;

test("a click on an affiliate link to our Actor sends one event with the page and the Actor page only", () => {
  const b = browser();
  b.fire("click", b.link(AFFIL));
  assert.deepStrictEqual(b.calls, [["apify-referral-click", { path: "/licences/", target: "/yappman/uk-supermarket-price-scraper" }]]);
});

test("utm tags and the parameter together are fine, and the query is never sent", () => {
  const b = browser({ pathname: "/coverage/" });
  b.fire("click", b.link(`https://apify.com/yappman/uk-supermarket-price-scraper?utm_source=data.yappman.com&utm_campaign=coverage&${AFF.PARAM}`));
  assert.strictEqual(b.calls.length, 1);
  assert.deepStrictEqual(Object.keys(b.calls[0][1]).sort(), ["path", "target"]);
  assert.ok(!JSON.stringify(b.calls).includes("fpr") && !JSON.stringify(b.calls).includes("utm"));
});

test("other links send nothing: no parameter, another token, another host, a relative link, the menu without the parameter", () => {
  const b = browser();
  for (const href of ["https://apify.com/yappman/x", "https://apify.com/yappman/x?fpr=other", "https://example.com/x?fpr=wy5pu7", "/licences/", "https://www.apify.com/yappman/x?fpr=wy5pu7", "not a url ::"]) b.fire("click", b.link(href));
  assert.deepStrictEqual(b.calls, []);
});

test("a click that is not on a link, or on an element without closest, sends nothing and does not throw", () => {
  const b = browser();
  b.fire("click", { target: { closest: () => null } });
  b.fire("click", { target: {} });
  b.fire("click", { target: null });
  assert.deepStrictEqual(b.calls, []);
});

test("with Umami blocked or not loaded nothing runs and nothing throws", () => {
  const b = browser({ umami: false });
  assert.doesNotThrow(() => b.fire("click", b.link(AFFIL)));
  assert.deepStrictEqual(b.calls, []);
});

test("a middle click counts, a right click does not", () => {
  const b = browser();
  b.fire("auxclick", Object.assign(b.link(AFFIL), { button: 1 }));
  b.fire("auxclick", Object.assign(b.link(AFFIL), { button: 2 }));
  assert.strictEqual(b.calls.length, 1);
});

test("site.js stays free of cookies, storage writes for tracking, network calls and new scripts", () => {
  assert.doesNotMatch(SRC, /document\.cookie|localStorage|XMLHttpRequest|fetch\s*\(|sendBeacon|createElement\(['"]script/);
  const tracked = SRC.slice(SRC.indexOf("var trackReferral"), SRC.indexOf("Old home-page anchors"));
  assert.doesNotMatch(tracked, /sessionStorage|navigator|userAgent|screen|referrer|cookie/);
});

test("the token in site.js is the token in affiliate.js, and the event name is fixed", () => {
  assert.ok(SRC.includes(`'${AFF.TOKEN}'`), "site.js must use the same token as docs/release/affiliate.js");
  assert.ok(SRC.includes("'apify-referral-click'"));
});
