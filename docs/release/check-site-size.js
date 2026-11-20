#!/usr/bin/env node
"use strict";
// Pre-push size check: the tree GitHub Pages will serve must stay well under its 1 GB limit.
//
//   node docs/release/check-site-size.js [--root DIR] [--git] [--warn-mb 600] [--fail-mb 900]
//
// Counts every file Pages would serve: all files except those under a folder or with a name that starts with "." or "_" (Jekyll skips them:
// .git, .claude, _incoming, _template) and node_modules. With --git it counts only the files git tracks (what a push would carry), which is
// the right measure in a working folder that holds untracked downloads. Exit 0 under the warn size, 0 with a warning from the warn size up
// to the fail size, 1 at or above the fail size. No network, no clock; it reads file sizes only.
const fs = require("fs");
const path = require("path");

const MB = 1e6;
const skipName = n => n.startsWith(".") || n.startsWith("_") || n === "node_modules";

function walk(root) {
  const out = [];
  (function go(dir) {
    for (const e of fs.readdirSync(path.join(root, dir), { withFileTypes: true })) {
      if (skipName(e.name)) continue;
      const rel = dir ? `${dir}/${e.name}` : e.name;
      if (e.isDirectory()) go(rel);
      else if (e.isFile()) out.push([rel, fs.statSync(path.join(root, rel)).size]);
    }
  })("");
  return out;
}

function tracked(root) {
  const r = require("child_process").spawnSync("git", ["-C", root, "ls-files", "-z"], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  if (r.status !== 0) throw new Error("git ls-files failed: " + (r.stderr || "").trim());
  return r.stdout.split("\0").filter(Boolean).filter(f => !f.split("/").some(skipName))
    .filter(f => { try { return fs.statSync(path.join(root, f)).isFile(); } catch (e) { return false; } })
    .map(f => [f, fs.statSync(path.join(root, f)).size]);
}

function measure(files) {
  const total = files.reduce((a, [, n]) => a + n, 0), byDir = {};
  for (const [f, n] of files) { const k = f.split("/").slice(0, f.includes("/") ? Math.min(2, f.split("/").length - 1) : 0).join("/") || "(top level)"; byDir[k] = (byDir[k] || 0) + n; }
  const top = Object.entries(byDir).sort((a, b) => b[1] - a[1]).slice(0, 3);
  return { total, files: files.length, top };
}

function verdict(total, warnMb, failMb) { return total >= failMb * MB ? "fail" : total >= warnMb * MB ? "warn" : "ok"; }

module.exports = { walk, tracked, measure, verdict, skipName };

if (require.main === module) {
  const args = process.argv.slice(2);
  let root = ".", git = false, warn = 600, fail = 900;
  for (let i = 0; i < args.length; i++) {
    const a = args[i], v = args[i + 1];
    if (a === "--git") git = true;
    else if (a === "--root" && v && !v.startsWith("--")) { root = v; i++; }
    else if ((a === "--warn-mb" || a === "--fail-mb") && v && /^[0-9]+(\.[0-9]+)?$/.test(v)) { if (a === "--warn-mb") warn = Number(v); else fail = Number(v); i++; }
    else { console.error("usage: check-site-size.js [--root DIR] [--git] [--warn-mb N] [--fail-mb N]"); process.exit(2); }
  }
  if (!(warn > 0 && fail > warn)) { console.error("usage error: the fail size must be above the warn size"); process.exit(2); }
  let m;
  try { m = measure(git ? tracked(root) : walk(root)); } catch (e) { console.error("size check could not run: " + e.message); process.exit(2); }
  const state = verdict(m.total, warn, fail), where = m.top.map(([d, n]) => `${d} ${(n / MB).toFixed(1)} MB`).join("; ");
  const line = `served tree ${(m.total / MB).toFixed(1)} MB in ${m.files} files (largest: ${where}); warn at ${warn} MB, fail at ${fail} MB`;
  if (state === "fail") { console.error("FAIL: " + line + ". GitHub Pages allows 1 GB: move older vintages out of the tree before pushing."); process.exit(1); }
  console.log((state === "warn" ? "WARN: " : "ok: ") + line);
}
