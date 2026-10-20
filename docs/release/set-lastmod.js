// Push-time sitemap step:   node docs/release/set-lastmod.js YYYY-MM-DD page1/ page2/ ...
// Sets the sitemap lastmod to the date ONLY for the pages named (use the word home for the home page: Git Bash rewrites a bare "/" into a Windows path and PowerShell can drop an empty argument).
// Get the list of changed pages with:   git diff --name-only main..HEAD -- '*.html'   (x/index.html -> x/ ; root index.html -> home)
// It does not check that the list is complete: afterwards check `git diff sitemap.xml` shows only those lastmod lines.
// The date must be a real date within one day of today. Atomic: nothing is written unless every entry is found.
const fs = require("fs");
const [date, ...pages] = process.argv.slice(2);
const dt = new Date((date || "") + "T00:00:00Z");
if (!/^\d{4}-\d{2}-\d{2}$/.test(date || "") || isNaN(dt) || dt.toISOString().slice(0, 10) !== date || !pages.length) { console.error("usage: node docs/release/set-lastmod.js YYYY-MM-DD page/ [page/ ...]"); process.exit(2); }
if (Math.abs(dt - new Date(new Date().toISOString().slice(0, 10) + "T00:00:00Z")) > 86400000) { console.error("the date must be within one day of today"); process.exit(2); }
const esc = s => s.replace(/[.*+?^${}()|[\]\\\/]/g, "\\$&");
let sm = fs.readFileSync("sitemap.xml", "utf8").replace(/\r\n/g, "\n");
for (const raw of pages) {
  const p = raw === "home" || raw === "/" || raw === "" ? "" : raw;
  const re = new RegExp(`(<loc>https://data\\.yappman\\.com/${esc(p)}</loc>\\n\\s*<lastmod>)[^<]*`);
  if (!re.test(sm)) { console.error("NOTHING WRITTEN. sitemap entry missing: /" + p); process.exit(1); }
  sm = sm.replace(re, (x, a1) => a1 + date);
}
fs.writeFileSync("sitemap.xml", sm);
console.log("lastmod set to", date, "for", pages.length, "pages");
