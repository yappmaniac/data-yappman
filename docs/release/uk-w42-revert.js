// Post-publish wording for the UK W42 restart. Run from the repo root on the publish branch, in the SAME push as the
// dataset check, only when the public dataset uk-shelf-price-index holds W42 AND W43 and the files are verified
// (the trigger is the data, not the date):   node docs/release/uk-w42-revert.js 2026-10-26
// The argument is the publish date (YYYY-MM-DD, a real date within one day of today).
// Atomic: every anchor in every file is checked in memory first; nothing is written unless all of them match.
const fs = require("fs");
const date = process.argv[2] || "";
const dt = new Date(date + "T00:00:00Z");
if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || isNaN(dt) || dt.toISOString().slice(0, 10) !== date) { console.error("usage: node docs/release/uk-w42-revert.js YYYY-MM-DD (a real date)"); process.exit(2); }
if (Math.abs(dt - new Date(new Date().toISOString().slice(0, 10) + "T00:00:00Z")) > 86400000) { console.error("the date must be within one day of today"); process.exit(2); }
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const [y, m, d] = date.split("-").map(Number); const LONG = `${d} ${MONTHS[m - 1]} ${y}`;

const files = new Map(); // path -> content (LF; the repo's autocrlf setting restores line endings on commit/checkout)
const get = f => { if (!files.has(f)) files.set(f, fs.readFileSync(f, "utf8").replace(/\r\n/g, "\n")); return files.get(f); };
function ed(f, a, b, n = 1) { const s = get(f); const c = s.split(a).length - 1; if (c !== n) throw new Error(`${f}: anchor count ${c}, want ${n}: ${a.slice(0, 70)}`); files.set(f, s.split(a).join(b)); }

try {
  const UK = "shelf-price-index/index.html";
  ed(UK, "Latest week 2026-W40; restart at W42 pending.", "Base 100 at 2026-W42 after the skipped week 41.", 2);
  ed(UK, " (not yet published; the latest published week is 2026-W40)", "");
  ed(UK, "The index will restart at week 42 after a skipped week 41", "The index restarted at week 42 after a skipped week 41");
  ed(UK, "and at 2026-W42 for the new series, which has not been published yet. The latest published week is 2026-W40. Intended weekly", "and at 2026-W42 for the new series. Intended weekly");
  ed(UK, "from a new base of 100 at ISO week 2026-W42 (not published yet). Four-week changes", "from a new base of 100 at ISO week 2026-W42. Four-week changes");

  const M = "shelf-price-index/method/index.html";
  ed(M, "the index will restart with a new base of 100 at 2026-W42, which has not been published yet (the latest published week is 2026-W40); the first weekly change", "the index restarted with a new base of 100 at 2026-W42; the first weekly change");
  ed(M, "week 41 skipped; the index will restart with a new base at 2026-W42, not yet published (", "week 41 skipped; the index restarted with a new base at 2026-W42 (");
  ed(M, "  <li><strong>12 October 2026:</strong>", `  <li><strong>${LONG}:</strong> 2026-W42 published as the new base (level 100).</li>\n  <li><strong>12 October 2026:</strong>`);

  ed("methodology/index.html", "100 at 2026-W42 after week 41 was skipped (not published yet)", "100 at 2026-W42 after week 41 was skipped");
  ed("press/index.html", "so the index will restart with a new base at week 42, once it is published", "so the index restarted with a new base at week 42");

  ed("notices/index.html", '<span class="pill">Will restart at week 42</span>', '<span class="pill">Restarted at week 42</span>');
  ed("notices/index.html", "the series will restart at week 42</a></h3>", "the series restarted at week 42</a></h3>");
  ed("notices/w41-skipped/index.html", "the series will restart at week 42", "the series restarted at week 42", 3);
  ed("notices/w41-skipped/index.html", "The UK shelf-price index will restart at week 42 as the new base", "The UK shelf-price index restarted at week 42 as the new base", 2);
  ed("notices/w41-skipped/index.html", "The index will therefore restart:", "The index therefore restarted:");
  ed("notices/w41-skipped/index.html", "UK shelf-price index. Posted 12 October 2026.", `UK shelf-price index. Posted 12 October 2026. Published on ${LONG}.`);

  let sm = get("sitemap.xml");
  for (const p of ["shelf-price-index/", "shelf-price-index/method/", "methodology/", "press/", "notices/", "notices/w41-skipped/"]) {
    const re = new RegExp(`(<loc>https://data\\.yappman\\.com/${p.replace(/\//g, "\\/")}</loc>\\n\\s*<lastmod>)[^<]*`);
    if (!re.test(sm)) throw new Error("sitemap entry " + p);
    sm = sm.replace(re, (x, a1) => a1 + date);
  }
  files.set("sitemap.xml", sm);
} catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }

for (const [f, s] of files) fs.writeFileSync(f, s);
console.log("revert applied for", date, "to", files.size, "files");
