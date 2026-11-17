#!/usr/bin/env node
"use strict";
// Takes one shop off the basket check page (/basket/), or puts it back. For the day a shop asks us in writing to stop.
//
//   node docs/release/basket-remove-shop.js SHOP [--root DIR]             take the shop off the page
//   node docs/release/basket-remove-shop.js --restore SHOP [--root DIR]   put it back
//
// SHOP is one of aldi, asda, sainsburys, tesco. Removing a shop changes three files, and nothing else:
//   1. data/basket-pilot-list.json: the one line that matters, "removedShops":["SHOP"]. assets/basket.js reads it when the page
//      loads and leaves the shop out of every column, total, note and download.
//   2. data/basket-pilot.json: every cell of that shop becomes {"s":"x"} (not read), so the public file holds none of its prices.
//   3. basket/index.html: rebuilt, so the title, headings and notes name only the shops still shown.
// It then prints what to do next (review the diff, commit, push on Russell's go). It never commits or pushes, uses no network and no
// clock. Restoring only reverses 1 and 3: the shop's prices come back with the next daily read.
// The daily data builder (build-basket-pilot.js) is not changed by this: if the daily read still returns rows for a removed shop, its
// prices re-enter the public JSON file (the page still hides them). Stop the collection for that shop the same day.
const fs = require("fs");
const path = require("path");
const pilot = require("./build-basket-pilot.js");
const page = require("./build-basket-page.js");

const TOKEN = /"removedShops":\[[^\]]*\]/g;

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
  const newListText = listText.replace(TOKEN, `"removedShops":${JSON.stringify(after)}`);
  const files = new Map([[pilot.LIST, newListText]]);
  let cells = 0;
  if (!restore && fs.existsSync(dataPath)) {
    const d = JSON.parse(fs.readFileSync(dataPath, "utf8"));
    for (const o of Object.values(d.cells || {})) if (o[shop]) { o[shop] = { s: "x" }; cells++; }
    files.set(pilot.OUT, pilot.dump(d));
  }
  return { files, before, after, cells, changed: before.join() !== after.join() };
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
    console.log(`${restore ? "restored" : "removed"} ${shop}: removedShops is now [${p.after.join(", ")}]${restore ? "" : `; ${p.cells} price cells cleared in ${pilot.OUT}`}; ${page.OUT} rebuilt.`);
    if (!p.changed) console.log("(the list already said so; the files were rewritten to the same state)");
    console.log("Next: git diff --stat (expect only data/basket-pilot-list.json, data/basket-pilot.json and basket/index.html), run the checks, commit, and push on Russell's go.");
    if (!restore) console.log("Also stop the daily collection for this shop today, or its prices re-enter the public data file at the next daily read.");
  } catch (e) { console.error("NOTHING CHANGED. " + e.message); process.exit(1); }
}
