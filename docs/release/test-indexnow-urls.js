const assert = require("assert");
const { urlFor } = require("./indexnow-urls.js");
const H = "https://data.yappman.com";
assert.strictEqual(urlFor("index.html"), H + "/");
assert.strictEqual(urlFor("shelf-price-index/index.html"), H + "/shelf-price-index/");
assert.strictEqual(urlFor("notices/w41-skipped/index.html"), H + "/notices/w41-skipped/");
assert.strictEqual(urlFor(["shelf-price-index","method","index.html"].join(String.fromCharCode(92))), H + "/shelf-price-index/method/");
for (const f of ["_held/x/index.html", "docs/a/index.html", "404.html", "google428db29621210fc5.html", "sitemap.xml", "robots.txt", "assets/site.css", "README.md", "a/page.html"]) assert.strictEqual(urlFor(f), null, f);
console.log("indexnow-urls: all checks passed");
