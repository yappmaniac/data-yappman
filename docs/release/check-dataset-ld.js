#!/usr/bin/env node
"use strict";
// Dataset structured data (schema.org JSON-LD) must be true and complete enough, on every data page.
//
//   node docs/release/check-dataset-ld.js [--root DIR]     exit 1 and list every problem
//
// A page that carries a Dataset block must: parse as JSON; have a name, a description, a url equal to its own canonical link, a license
// URL (OGL v3.0 or CC BY 4.0, the two licences the pages state) unless it is on the short list that names no licence URL, creator Yappman Data,
// isAccessibleForFree true; list in `distribution` only files that exist in the site (a contentUrl on data.yappman.com that points at a file
// here); carry no affiliate or tracking parameter, no Apify Store link and no field outside the list below; and have a valid ISO
// temporalCoverage and dateModified where it has them. REQUIRED pages must carry a Dataset block. No network, no clock.
const fs = require("fs");
const path = require("path");

const SITE = "https://data.yappman.com";
const LICENCES = new Set(["https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/", "https://creativecommons.org/licenses/by/4.0/",
  "https://creativecommons.org/publicdomain/zero/1.0/"]);   // CC0: the GLEIF LEI data
// Eurostat publishes a reuse notice, not a licence: the EU sample page carries exactly the line Russell approved (20 Nov 2026) and that notice.
const EUROSTAT = { page: "eu-air-sea-traffic-sample/index.html", name: "reuse authorised provided the source is acknowledged", url: "https://ec.europa.eu/eurostat/web/main/help/copyright-notice" };
const REQUIRED = ["shelf-price-index/index.html", "au-shelf-price-index/index.html", "shelf-price-index/categories/index.html", "data/v1/index.html",
  "sold-prices/index.html", "sold-prices/history/index.html", "rental-yield/index.html", "council-tax/index.html", "christmas-basket/index.html",
  "gender-pay-gap/index.html", "recalls-sample/index.html", "contracts-sample/index.html", "lei-sample/index.html", "fsa-sample/index.html", "eu-air-sea-traffic-sample/index.html", "360giving-grants-sample/index.html"];
const CATALOGUE = "free-data/index.html";     // when it exists, it must carry a DataCatalog whose datasets and files are real
const ALLOWED = new Set(["@context", "@type", "name", "description", "url", "license", "isAccessibleForFree", "dateModified", "creator", "keywords", "spatialCoverage",
  "temporalCoverage", "distribution", "variableMeasured", "measurementTechnique", "creditText", "sameAs", "isBasedOn", "citation"]);
const BLOCK = /<script type="application\/ld\+json">\n([\s\S]*?)\n<\/script>/g;
const SKIP = new Set([".git", ".claude", "_incoming", "_template", "node_modules", "docs"]);

function pages(root) {
  const out = [];
  (function go(dir) {
    for (const e of fs.readdirSync(path.join(root, dir), { withFileTypes: true })) {
      const rel = dir ? `${dir}/${e.name}` : e.name;
      if (e.isDirectory()) { if (!SKIP.has(e.name)) go(rel); } else if (e.name.endsWith(".html")) out.push(rel);
    }
  })("");
  return out.sort();
}

const isoDate = s => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(s));
const isoInterval = s => typeof s === "string" && /^\d{4}-\d{2}-\d{2}\/(\d{4}-\d{2}-\d{2}|\.\.)$/.test(s);

function check(root) {
  const problems = [], seen = new Set();
  for (const rel of pages(root)) {
    const text = fs.readFileSync(path.join(root, rel), "utf8").replace(/\r\n/g, "\n");
    const docs = [];
    for (const m of text.matchAll(BLOCK)) { try { docs.push(JSON.parse(m[1])); } catch (e) { problems.push(`${rel}: a JSON-LD block is not valid JSON`); } }
    for (const cat of docs.filter(d => d && d["@type"] === "DataCatalog")) {        // the catalogue: every listed dataset points at a real page and real files
      const say = msg => problems.push(`${rel}: catalogue: ${msg}`);
      if (!Array.isArray(cat.dataset) || !cat.dataset.length) { say("no datasets"); continue; }
      for (const d of cat.dataset) {
        const u = d.url || "";
        if (!u.startsWith(SITE + "/") || !fs.existsSync(path.join(root, u.slice(SITE.length + 1), "index.html"))) say(`dataset page does not exist: ${u}`);
        const lic = d.license === undefined ? [] : Array.isArray(d.license) ? d.license : [d.license];
        if (!lic.every(l => LICENCES.has(l))) say(`${d.name}: license is not made of the licence URLs the pages state`);
        for (const dist of d.distribution || []) if (!(dist.contentUrl || "").startsWith(SITE + "/") || !fs.existsSync(path.join(root, dist.contentUrl.slice(SITE.length + 1)))) say(`file does not exist: ${dist.contentUrl}`);
      }
      if (/fpr=|utm_|ref=|https:\/\/apify\.com\//.test(JSON.stringify(cat))) say("an affiliate parameter or a Store link is in the structured data");
    }
    if (rel === CATALOGUE) { seen.add(rel); if (!docs.some(d => d && d["@type"] === "DataCatalog")) problems.push(`${rel}: expected a DataCatalog block`); }
    const sets = docs.filter(d => d && d["@type"] === "Dataset");
    if (REQUIRED.includes(rel)) { seen.add(rel); if (sets.length !== 1) { problems.push(`${rel}: expected exactly one Dataset block, found ${sets.length}`); continue; } }
    if (!sets.length) continue;
    if (sets.length > 1) { problems.push(`${rel}: more than one Dataset block`); continue; }
    const d = sets[0], canonical = (text.match(/<link rel="canonical" href="([^"]*)">/) || [])[1];
    const say = msg => problems.push(`${rel}: ${msg}`);
    for (const k of Object.keys(d)) if (!ALLOWED.has(k)) say(`unexpected field ${k}`);
    if (d["@context"] !== "https://schema.org") say("@context is not https://schema.org");
    if (typeof d.name !== "string" || !d.name.trim()) say("no name");
    if (typeof d.description !== "string" || d.description.length < 50) say("no real description");
    if (!canonical || d.url !== canonical) say(`url ${d.url} is not the canonical link ${canonical}`);
    if (rel === EUROSTAT.page) {
      const l = d.license || {};
      if (l["@type"] !== "CreativeWork" || l.name !== EUROSTAT.name || l.url !== EUROSTAT.url || Object.keys(l).length !== 3) say("license is not the approved Eurostat reuse line");
    } else {
      const lic = Array.isArray(d.license) ? d.license : [d.license];
      if (!(lic.length && lic.every(l => LICENCES.has(l)))) say(`license is not made of the licence URLs the pages state (${lic.join(", ")})`);
    }
    if (d.isAccessibleForFree !== true) say("isAccessibleForFree is not true");
    if (!d.creator || d.creator.name !== "Yappman Data") say("creator is not Yappman Data");
    if (d.dateModified !== undefined && !isoDate(d.dateModified)) say("dateModified is not an ISO date");
    if (d.temporalCoverage !== undefined && !isoInterval(d.temporalCoverage)) say(`temporalCoverage is not an ISO interval (${d.temporalCoverage})`);
    for (const dist of d.distribution || []) {
      const u = dist.contentUrl || "";
      if (u.startsWith(SITE + "/")) { if (!fs.existsSync(path.join(root, u.slice(SITE.length + 1)))) say(`distribution file does not exist: ${u}`); }
      else if (!/^https:\/\/api\.apify\.com\/v2\/datasets\//.test(u)) say(`distribution outside this site and the published Apify datasets: ${u}`);
    }
    const flat = JSON.stringify(d);
    if (/fpr=|utm_|ref=/.test(flat)) say("an affiliate or tracking parameter is in the structured data");
    if (/https:\/\/apify\.com\//.test(flat)) say("an Apify Store link is in the structured data");
  }
  for (const rel of REQUIRED) if (!seen.has(rel)) problems.push(`${rel}: required page is missing`);
  if (fs.existsSync(path.join(root, CATALOGUE)) && !seen.has(CATALOGUE)) problems.push(`${CATALOGUE}: not checked`);
  return problems;
}

function count(root) {
  let n = 0;
  for (const rel of pages(root)) if (/<script type="application\/ld\+json">/.test(fs.readFileSync(path.join(root, rel), "utf8"))) n++;
  return n;
}

module.exports = { check, count, pages, REQUIRED };

if (require.main === module) {
  const a = process.argv.slice(2);
  let root = ".";
  if (a.length === 2 && a[0] === "--root") root = a[1]; else if (a.length) { console.error("usage: check-dataset-ld.js [--root DIR]"); process.exit(2); }
  const bad = check(root);
  if (bad.length) { console.error(bad.join("\n")); process.exit(1); }
  const files = pages(root).filter(rel => fs.readFileSync(path.join(root, rel), "utf8").includes('"@type": "Dataset"')).length;
  console.log(`dataset structured data: ${files} pages carry a valid Dataset block (${count(root)} pages carry JSON-LD of any type)`);
}
