// Tests for docs/release/check-site-size.js.   node --test docs/release/check-site-size.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const S = require("./check-site-size.js");
const SCRIPT = path.join(__dirname, "check-site-size.js");

function site() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "size-"));
  const put = (rel, n) => { fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true }); fs.writeFileSync(path.join(root, rel), Buffer.alloc(n, 97)); };
  put("index.html", 1000); put("data/a/big.csv", 3000); put("data/b.json", 500); put("_incoming/huge.bin", 100000); put(".git/obj", 100000);
  put("_template/nav.tpl", 5000); put("node_modules/x/y.js", 5000); put(".claude/w/z", 5000);
  return root;
}
const run = (root, ...a) => spawnSync(process.execPath, [SCRIPT, "--root", root, ...a], { encoding: "utf8" });

test("only served files count: dot, underscore and node_modules names are skipped", () => {
  const files = S.walk(site());
  assert.deepStrictEqual(files.map(f => f[0]).sort(), ["data/a/big.csv", "data/b.json", "index.html"]);
  assert.equal(S.measure(files).total, 4500);
});

test("verdict: ok under the warn size, warn from it, fail from the fail size", () => {
  assert.equal(S.verdict(599e6, 600, 900), "ok"); assert.equal(S.verdict(600e6, 600, 900), "warn");
  assert.equal(S.verdict(899e6, 600, 900), "warn"); assert.equal(S.verdict(900e6, 600, 900), "fail");
});

test("command line: exit 0 with ok, 0 with WARN, 1 with FAIL, 2 on a usage error", () => {
  const root = site();
  assert.equal(run(root).status, 0); assert.match(run(root).stdout, /^ok: served tree 0\.0 MB in 3 files/);
  const w = run(root, "--warn-mb", "0.001", "--fail-mb", "1"); assert.equal(w.status, 0); assert.match(w.stdout, /^WARN:/);
  const f = run(root, "--warn-mb", "0.001", "--fail-mb", "0.004"); assert.equal(f.status, 1); assert.match(f.stderr, /^FAIL:.*1 GB/);
  assert.equal(run(root, "--warn-mb", "900", "--fail-mb", "600").status, 2);
  assert.equal(run(root, "--nonsense").status, 2);
  assert.equal(run(path.join(root, "missing")).status, 2);
});

test("--git counts only tracked files", () => {
  const root = site();
  const g = (...a) => spawnSync("git", ["-C", root, ...a], { encoding: "utf8" });
  g("init", "-q"); g("add", "index.html", "data/b.json"); g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x");
  assert.equal(S.measure(S.tracked(root)).total, 1500);
  assert.equal(S.measure(S.walk(root)).total, 4500);
});

test("the real site is under the warn size", () => {
  const root = path.join(__dirname, "..", "..");
  assert.equal(S.verdict(S.measure(S.walk(root)).total, 600, 900), "ok");
});
