#!/usr/bin/env node
"use strict";
// Builds /basket/: the basket check page (static HTML; assets/basket.js fills in the list and totals from two same-site JSON files).
//
//   node docs/release/build-basket-page.js [--root DIR]         write the page
//   node docs/release/build-basket-page.js --check [--root DIR]   fail unless the page equals a rebuild
//
// Inputs (read only): data/basket-pilot-list.json (for the item count and the date a person checked the matches) and the site template
// page. The page text is the wording set in drafts/fable-basket-terms-exposure-16-nov.md section 2.3; the banned words of that
// document are checked here and in the tests. The page itself holds NO prices: they come from data/basket-pilot.json at view time, so
// the daily refresh changes no HTML. No network, no clock.
const fs = require("fs");
const path = require("path");

const OUT = "basket/index.html";
const LIST = "data/basket-pilot-list.json";
const TEMPLATE = "notices/w41-skipped/index.html";
const SITE = "https://data.yappman.com";
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const longDate = d => { if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) throw new Error(`bad date "${d}"`); const [y, m, dd] = d.split("-").map(Number); return `${dd} ${MONTHS[m - 1]} ${y}`; };
// Words the page, its script and its styles must never contain (the terms review, section 2.3).
const BANNED = [/cheapest/i, /\bbest\b/i, /\bsav(e|es|ing|ings)\b/i, /\blive\b/i, /real-time/i, /\bofficial\b/i, /\baccurate\b/i, /guarantee/i, /public data/i, /publicly available/i,
  /\bpermitted\b/i, /\ballowed\b/i, /\bcompliant\b/i, /\blicensed\b/i, /with permission/i, /robots/i, /\bpartner/i, /coming soon/i, /\bcoming\b/i, /CC BY/i, /creative commons/i];

function body(list) {
  const n = list.items.length, checked = longDate(list.checkedOn);
  return `<header>
  <h1>Basket check: everyday items at Aldi, Asda, Sainsbury&rsquo;s and Tesco</h1>
  <p class="sub">A pilot. Pick items and see each shop&rsquo;s total for your list.</p>
</header>

<div id="bk-root">
<p id="bk-status" role="status">Loading prices&hellip;</p>
<noscript><p>This page needs JavaScript to show the list and the totals. Nothing is sent anywhere and no cookies are set.</p></noscript>
<p id="bk-head"></p>
<div class="box notice" id="bk-stale" hidden></div>
<p>Aldi, Asda, Sainsbury&rsquo;s and Tesco are listed in alphabetical order; the order is not a ranking. <a href="#how-this-works">How this works</a> explains how we compare and shows every product and size. Morrisons is not in this comparison.</p>
<p class="meta" id="bk-share-note" hidden></p>

<h2 id="your-list">Your list</h2>
<label for="bk-search"><strong>Search the list</strong> (item, group or brand)</label><br>
<input id="bk-search" type="search" autocomplete="off">
<div id="bk-opts"></div>
<p><label><input type="checkbox" id="bk-remember"> Remember my list and settings on this device (kept in your browser only; nothing is sent anywhere)</label></p>
<div id="bk-result" aria-live="polite"></div>
<div id="bk-tools"></div>
<pre id="bk-printsheet"></pre>

<h2 id="items">The list, item by item</h2>
<div id="bk-list"></div>
</div>

<h2 id="how-this-works">How this works</h2>
<p><strong>What this is.</strong> A like-for-like check of ${n} everyday items that we chose, at four shops. It is not a survey of every product and it does not show which shop is lowest overall.</p>
<p id="matching"><strong>How items were chosen.</strong> We wrote the list by hand: common staples at common sizes. Premium, organic, free-from and flavoured lines are left out. Products were never chosen by price. Each item is either the same branded product at each shop (&ldquo;same product&rdquo;) or each shop&rsquo;s own standard product of the same kind and size (&ldquo;comparable own-label&rdquo;). Comparable own-label is our judgement about the kind of product, not its quality or recipe. A person checked every match on ${esc(checked)}. The full list, with each product&rsquo;s name and pack size at each shop, is above.</p>
<p><strong>Prices.</strong> Each price is for one item without a loyalty card, as read without signing in. A temporary price cut is already included. Multi-buy offers, vouchers and personal offers are never applied. Loyalty-card prices are left out unless you switch them on on this page. An Aldi price may be a cut that is not marked. Where an offer is listed for an item, the cell says so. Totals are for goods only: no delivery, collection or bag charges and no minimum spend. Unit prices are worked out by us from the price and the pack size shown.</p>
${list.statements && list.statements.storeSetting ? `<p><strong>Where.</strong> Tesco and Sainsbury&rsquo;s: prices are read with no store chosen. Asda and Aldi: prices are read for one fixed store or service area, so they may differ from the price at your local store. Prices in smaller-format stores or for your address can differ. Aldi stock is not shown in our data.</p>
` : ""}
<p><strong>When.</strong> ${list.statements && list.statements.dailyRead ? "Prices are read once a day, early morning UK time. Every price shows the date it was read. " : ""}Shops change prices during the day. The shop&rsquo;s own price at the till or checkout is the one that counts.</p>
<p><strong>Sizes.</strong> Same-product packs are within 3% in size. Comparable own-label packs are the same stated size; where a size differs the cell says so and is left out of totals unless you choose to include it.</p>
<p><strong>Changes.</strong> If a product disappears we show &ldquo;no matching product&rdquo; until a person picks a replacement; replacements and corrections are listed with dates below. Corrections so far: none.</p>
<p><strong>Who we are and how this is paid for.</strong> We are Yappman Data; the company name, number and registered office are in the footer of every page, and our email address is info@yappman.com. The page is free. No shop pays us or supplies us, and there are no shop affiliate links here. We sell data tools and data licences, described on the <a href="/licences/">licences page</a>.</p>
<p>Not advice, not a government statistic, not a measure of what people paid.</p>

<p class="meta">Aldi, Asda, Sainsbury&rsquo;s and Tesco are named only to say where each price was read. Morrisons is named only to say it is not included. We are not affiliated with, endorsed by or supplied by any of them, and we do not have their permission. Clubcard Prices and Nectar Prices are the shops&rsquo; own scheme names. Product and brand names belong to their owners.</p>
<p class="meta">To correct a price or match, write to <a href="mailto:info@yappman.com">info@yappman.com</a>; we normally reply within one working day. If a shop asks us in writing to stop, we stop collecting and showing its prices the day we read the message.</p>
`;
}

function build(root) {
  const list = JSON.parse(fs.readFileSync(path.join(root, LIST), "utf8"));
  if (list.schema !== 1 || !Array.isArray(list.items) || !list.items.length) throw new Error(`${LIST}: not the expected shape`);
  const html = body(list);
  const text = html.replace(/<[^>]*>/g, " ");                     // what a visitor reads, not attribute names such as aria-live
  for (const re of BANNED) { const m = re.exec(text); if (m) throw new Error(`the page text contains a banned word ${re}, near: ${text.slice(Math.max(0, m.index - 40), m.index + 40).replace(/\n/g, " ")}`); }
  const raw = fs.readFileSync(path.join(root, TEMPLATE), "utf8").replace(/\r\n/g, "\n");
  const [head0, rest] = raw.split("<main id=\"main\" tabindex=\"-1\">\n");
  if (!rest || !rest.includes("</main>\n")) throw new Error(`${TEMPLATE}: not the expected page shape`);
  const foot = rest.split("</main>\n").slice(1).join("</main>\n");
  const title = "Basket check: everyday items at Aldi, Asda, Sainsbury's and Tesco";
  const desc = `A pilot: pick items from a list of ${list.items.length} and see each shop's total at Aldi, Asda, Sainsbury's and Tesco, with the date the prices were read and how the items were matched.`;
  const lines = head0.split("\n");
  const set = (start, v) => { const i = lines.findIndex(l => l.startsWith(start)); if (i < 0) throw new Error("template line missing: " + start); lines[i] = v; };
  set("<title>", `<title>${esc(title)} — Yappman Data</title>`);
  set("<meta name=\"description\"", `<meta name="description" content="${esc(desc)}">`);
  set("<meta property=\"og:title\"", `<meta property="og:title" content="${esc(title)} — Yappman Data">`);
  set("<meta property=\"og:description\"", `<meta property="og:description" content="${esc(desc)}">`);
  set("<meta property=\"og:url\"", `<meta property="og:url" content="${SITE}/basket/">`);
  set("<link rel=\"canonical\"", `<link rel="canonical" href="${SITE}/basket/">`);
  const ci = lines.findIndex(l => l.startsWith("<link rel=\"stylesheet\""));
  if (ci < 0) throw new Error("template stylesheet line missing");
  lines.splice(ci + 1, 0, "<link rel=\"stylesheet\" href=\"/assets/basket.css\">");
  const head = lines.join("\n").replace("class=\"nav-top active\" aria-current=\"true\"", "class=\"nav-top\"");
  const tail = foot.replace("</body>", "<script src=\"/assets/basket.js\" defer></script>\n</body>");
  if (tail === foot) throw new Error("template has no </body>");
  return new Map([[OUT, head + "<main id=\"main\" tabindex=\"-1\">\n" + html + "</main>\n" + tail]]);
}

function check(root) {
  const bad = [];
  for (const [f, s] of build(root)) {
    const p = path.join(root, f);
    if (!fs.existsSync(p)) bad.push(`${f} does not exist; run the build`);
    else if (fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n") !== s) bad.push(`${f} is not what the list gives; run the build`);
  }
  return bad;
}

function write(root, files) {
  const tmp = [];
  try {
    for (const [f, s] of files) { const p = path.join(root, f); fs.mkdirSync(path.dirname(p), { recursive: true }); const t = p + ".tmp"; tmp.push([p, t]); fs.writeFileSync(t, s); }
    for (const [p, t] of tmp) fs.renameSync(t, p);
  } finally { for (const [, t] of tmp) { try { if (fs.existsSync(t)) fs.unlinkSync(t); } catch { /* shows in git status */ } } }
}

module.exports = { build, check, write, BANNED, OUT };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", doCheck = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--check") doCheck = true;
    else if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  try {
    if (doCheck) { const bad = check(root); if (bad.length) { console.error(bad.join("\n")); process.exit(1); } console.log("the basket page agrees with the list"); }
    else { write(root, build(root)); console.log("wrote " + OUT); }
  } catch (e) { console.error("NOTHING WRITTEN. " + e.message); process.exit(1); }
}
