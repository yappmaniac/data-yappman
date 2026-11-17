#!/usr/bin/env node
"use strict";
// Takes one shop off the basket check page (/basket/). For the day a shop asks us in writing to stop.
//
//   node docs/release/basket-remove-shop.js SHOP [--root DIR]             take the shop off the page
//   node docs/release/basket-remove-shop.js --restore SHOP [--root DIR]   allow the shop back (see below)
//
// SHOP is one of aldi, asda, sainsburys, tesco. Removing a shop changes three public files, and nothing else:
//   1. data/basket-pilot-list.json: "removedShops":["SHOP"], and every product entry of that shop (its product name, id, link and
//      pack size) is taken out. assets/basket.js reads removedShops when the page loads and leaves the shop out of every column,
//      total, note and download.
//   2. data/basket-pilot.json: every cell of that shop is taken out, so the file holds none of its prices.
//   3. basket/index.html: rebuilt, so the title, headings and notes name only the shops still shown.
// After it, the shop's key appears only in removedShops, and its name only in the sentences that say it is not in the comparison.
// It prints what to do next (review the diff, run the gates, commit, push by commit id on Russell's go). It never commits or pushes,
// uses no network and no clock.
//
// --restore only takes the shop out of removedShops and rebuilds the page. The product entries were removed and are NOT put back by
// this script: a person regenerates the list from the pinned list (docs/release/make_basket_pilot_list.py), and the prices return
// with the next daily read. Until then the shop's column shows "No matching product at this shop."
//
// The daily data builder (build-basket-pilot.js) is not changed by this. Stop the daily collection for the shop the same day.
const fs = require("fs");
const path = require("path");
const pilot = require("./build-basket-pilot.js");
const page = require("./build-basket-page.js");

const TOKEN = /"removedShops":\[[^\]]*\]/g;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function plan(root, shop, restore) {
  const listPath = path.join(root, pilot.LIST), dataPath = path.join(root, pilot.OUT);
  const listText = fs.readFileSync(listPath, "utf8");
  const list = JSON.parse(listText);
  if (!Array.isArray(list.shops) || !list.shops.includes(shop)) throw new Error(`"${shop}" is not one of the shops in ${pilot.LIST} (${(list.shops || []).join(", ")})`);
  const tokens = listText.match(TOKEN) || [];
  if (tokens.length !== 1) throw new Error(`${pilot.LIST}: expected exactly one "removedShops":[...] entry, found ${tokens.length}`);
  const before = Array.isArray(list.removedShops) ? list.removedShops : [];
  const after = list.shops.filter(s => restore ? (before.includes(s) && s !== shop) : (before.includes(s) || s === shop));
  if (list.shops.length - after.length < 2) throw new Error("at least two shops must stay on the page; nothing changed");

  // The list is edited as text, so that nothing else in the one-line file changes: the removedShops entry, and (on a removal) each
  // of that shop's product entries, which are flat objects. The result is then checked against the same edit made on the parsed list.
  let newListText = listText.replace(TOKEN, `"removedShops":${JSON.stringify(after)}`), entries = 0;
  const want = JSON.parse(listText); want.removedShops = after;
  if (!restore) {
    const cell = new RegExp(`,"${shop}":\\{[^{}]*\\}|"${shop}":\\{[^{}]*\\},?`, "g");
    newListText = newListText.replace(cell, () => { entries++; return ""; });
    for (const it of want.items) delete it.cells[shop];
  }
  let got;
  try { got = JSON.parse(newListText); } catch (e) { throw new Error(`${pilot.LIST}: the edited list is not valid JSON; nothing changed`); }
  if (!same(got, want)) throw new Error(`${pilot.LIST}: the edited list is not the list less ${shop}; nothing changed`);
  if (!restore && got.items.some(it => it.cells && it.cells[shop])) throw new Error(`${pilot.LIST}: a ${shop} entry is left; nothing changed`);

  const files = new Map([[pilot.LIST, newListText]]);
  let cells = 0;
  if (!restore && fs.existsSync(dataPath)) {
    const d = JSON.parse(fs.readFileSync(dataPath, "utf8"));
    for (const [n, o] of Object.entries(d.cells || {})) {
      if (o[shop]) { delete o[shop]; cells++; }
      if (!Object.keys(o).length) delete d.cells[n];               // as the builder writes it: an item with no cell has no entry
    }
    files.set(pilot.OUT, pilot.dump(d));
  }
  return { files, before, after, entries, cells, changed: newListText !== listText || (files.has(pilot.OUT) && files.get(pilot.OUT) !== fs.readFileSync(dataPath, "utf8").replace(/\r\n/g, "\n")) };
}

function apply(root, shop, restore) {
  const p = plan(root, shop, restore);
  // the page is built from the new list: write the list first, and put it back if the page cannot be built
  const listPath = path.join(root, pilot.LIST), old = fs.readFileSync(listPath, "utf8");
  fs.writeFileSync(listPath, p.files.get(pilot.LIST));
  let pageFiles;
  try { pageFiles = page.build(root); } catch (e) { fs.writeFileSync(listPath, old); throw e; }
  if (p.files.has(pilot.OUT)) fs.writeFileSync(path.join(root, pilot.OUT), p.files.get(pilot.OUT));
  page.write(root, pageFiles);
  return p;
}

module.exports = { plan, apply };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", restore = false, shop = null;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--restore") restore = true;
    else if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else if (!args[i].startsWith("--") && shop === null) shop = args[i].toLowerCase();
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  if (!shop) { console.error("usage: basket-remove-shop.js [--restore] SHOP [--root DIR]"); process.exit(2); }
  try {
    const p = apply(root, shop, restore);
    if (restore) console.log(`${shop} is no longer in removedShops (now [${p.after.join(", ")}]); ${page.OUT} rebuilt. Its product entries are NOT back: regenerate the list from the pinned list with docs/release/make_basket_pilot_list.py; the prices return with the next daily read.`);
    else console.log(`removed ${shop}: removedShops is now [${p.after.join(", ")}]; ${p.entries} product entries taken out of ${pilot.LIST}; ${p.cells} cells taken out of ${pilot.OUT}; ${page.OUT} rebuilt.`);
    if (!p.changed) console.log("(the files already said so; nothing was different)");
    console.log("Next: git diff --stat (expect only data/basket-pilot-list.json, data/basket-pilot.json and basket/index.html), commit, run the gates on a clean checkout of that commit, and push that commit id on Russell's go.");
    if (!restore) console.log("Also stop the daily collection for this shop today.");
  } catch (e) { console.error("NOTHING CHANGED. " + e.message); process.exit(1); }
}
