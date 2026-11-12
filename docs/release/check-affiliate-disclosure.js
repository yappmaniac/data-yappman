#!/usr/bin/env node
"use strict";
// Fails if the Apify affiliate parameter is used wrongly anywhere on the site.
//
//   node docs/release/check-affiliate-disclosure.js [--root DIR]
//
// For every HTML page outside docs/:
//  - a link carrying fpr= must go to one of our own Actors (https://apify.com/yappman/...), carry our token, and have rel="sponsored";
//  - a page with such a link must carry the disclosure line (id="affiliate-disclosure", exact text) once, and a page without one must not;
//  - fpr= must not appear outside a link's href (structured data, text) and not in the menu (a line holding 8 or more Actor links).
// For every other text file (llms.txt, data/*.txt, xml, json, md): fpr= must not appear. No network, no clock.
const fs = require("fs");
const path = require("path");
const AFF = require("./affiliate.js");

function walk(root, dir = "") {
  const out = [];
  for (const e of fs.readdirSync(path.join(root, dir), { withFileTypes: true })) {
    const rel = dir ? `${dir}/${e.name}` : e.name;
    if (e.isDirectory()) { if (!["docs", "node_modules", ".git", ".github", "assets"].includes(e.name)) out.push(...walk(root, rel)); }
    else if (/\.(html|txt|xml|json|md|csv|svg)$/.test(e.name)) out.push(rel);
  }
  return out;
}

function check(root) {
  const bad = [];
  const ANCHOR = /<a\s[^>]*?href="([^"]*)"[^>]*>/gi;
  for (const f of walk(root)) {
    const t = fs.readFileSync(path.join(root, f), "utf8").replace(/\r\n/g, "\n");
    if (!/\.html$/.test(f)) { if (/[?&]fpr=/.test(t)) bad.push(`${f}: carries fpr= (only in-content links on HTML pages may)`); continue; }
    const lines = t.split("\n");
    let withParamLinks = 0;
    const anchorsFpr = [];
    for (const m of t.matchAll(ANCHOR)) {
      const href = m[1];
      if (!AFF.hasParam(href)) continue;
      withParamLinks++; anchorsFpr.push(m.index);
      const line = t.slice(0, m.index).split("\n").length;
      if (!AFF.OWN_ACTOR.test(href)) bad.push(`${f}:${line}: fpr= on a link that is not one of our own Actor pages (${href.slice(0, 60)})`);
      if (!new RegExp(`[?&](?:amp;)?${AFF.PARAM}(?:&|$)`).test(href)) bad.push(`${f}:${line}: fpr= is not our token`);
      if (!/\brel="[^"]*\bsponsored\b[^"]*"/.test(m[0])) bad.push(`${f}:${line}: an affiliate link without rel="sponsored"`);
      const anchorsOnLine = (lines[line - 1].match(/href="https:\/\/apify\.com\/yappman\//g) || []).length;
      if (anchorsOnLine >= 8) bad.push(`${f}:${line}: an affiliate link in the menu (a line with ${anchorsOnLine} Actor links)`);
    }
    const all = [...t.matchAll(/[?&](?:amp;)?fpr=/g)].length;
    if (all !== withParamLinks) bad.push(`${f}: fpr= appears ${all - withParamLinks} time(s) outside a link's href`);
    const disclosures = [...t.matchAll(new RegExp(`id="${AFF.DISCLOSURE_ID}"`, "g"))].length;
    if (withParamLinks && disclosures !== 1) bad.push(`${f}: has ${withParamLinks} affiliate link(s) and ${disclosures} disclosure line(s); it needs exactly one`);
    if (!withParamLinks && disclosures) bad.push(`${f}: has a disclosure line but no affiliate link`);
    if (disclosures && !t.includes(AFF.DISCLOSURE_HTML)) bad.push(`${f}: the disclosure line is not the standard text`);
    // where the page has its own header inside <main>, the disclosure sits under it, before the first affiliate link
    const mainAt = t.indexOf("<main");
    const pageHeader = mainAt >= 0 && t.indexOf("</header>", mainAt) > 0;
    if (disclosures && withParamLinks && pageHeader && t.indexOf(`id="${AFF.DISCLOSURE_ID}"`) > anchorsFpr[0]) bad.push(`${f}: the disclosure comes after the first affiliate link`);
  }
  return bad;
}

module.exports = { check };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".";
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--root" && args[i + 1] && !args[i + 1].startsWith("--")) root = args[++i];
    else { console.error("usage error: unknown or incomplete argument " + args[i]); process.exit(2); }
  }
  const bad = check(root);
  if (bad.length) { console.error(bad.join("\n")); process.exit(1); }
  console.log("affiliate links and disclosures are consistent");
}
