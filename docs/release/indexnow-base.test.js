// Tests for docs/release/indexnow-base.js.   node --test docs/release/indexnow-base.test.js
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const { chooseBase, parseArgs, EMPTY_TREE } = require("./indexnow-base.js");
const { urlFor } = require("./indexnow-urls.js");

const SCRIPT = path.join(__dirname, "indexnow-base.js");
const g = (cwd, ...a) => cp.execFileSync("git", ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", ...a], { cwd, encoding: "utf8" }).trim();

// A scratch repository: each call adds one commit that writes the given files.
function repo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "inbase-"));
  g(dir, "init", "-q", "-b", "main");
  const commit = (files, msg = "c") => {
    for (const [f, s] of Object.entries(files)) { fs.mkdirSync(path.dirname(path.join(dir, f)), { recursive: true }); fs.writeFileSync(path.join(dir, f), s); }
    g(dir, "add", "-A"); g(dir, "commit", "-q", "-m", msg);
    return g(dir, "rev-parse", "HEAD");
  };
  return { dir, commit };
}
const inRepo = (dir, fn) => { const old = process.cwd(); process.chdir(dir); try { return fn(); } finally { process.chdir(old); } };
const base = (dir, o) => inRepo(dir, () => chooseBase(o));
const pages = (dir, b, h) => g(dir, "diff", "--name-only", b, h, "--", "*.html").split("\n").filter(Boolean).map(urlFor).filter(Boolean).sort();

test("a normal push after a pinged commit: the base is the last pinged commit, so every commit of a multi-commit push is covered", () => {
  const r = repo();
  const a = r.commit({ "index.html": "1" });
  r.commit({ "licences/index.html": "2" });
  r.commit({ "privacy/index.html": "3", "data/x.json": "[]" });
  const h = r.commit({ "notices/index.html": "4" });
  const x = base(r.dir, { head: h, previous: [a] });
  assert.strictEqual(x.base, a);
  assert.deepStrictEqual(pages(r.dir, x.base, x.head), ["https://data.yappman.com/licences/", "https://data.yappman.com/notices/", "https://data.yappman.com/privacy/"]);
});

test("the case of 11 Nov 2026: the deployment reported the previous release; the last PINGED commit still gives every changed page", () => {
  const r = repo();
  r.commit({ "index.html": "0" });
  const prevRelease = r.commit({ "licences/index.html": "1" });
  const lastPinged = prevRelease; // the run after that release pinged it
  r.commit({ "privacy/index.html": "2" });
  const h = r.commit({ "actors/index.html": "3" });
  // the old workflow used the commit the deployment reported (prevRelease) minus one; the new one uses the last pinged commit
  const x = base(r.dir, { head: h, previous: [lastPinged] });
  assert.deepStrictEqual(pages(r.dir, x.base, x.head), ["https://data.yappman.com/actors/", "https://data.yappman.com/privacy/"]);
});

test("the head itself, unknown ids and duplicates in --previous are skipped; the newest usable one wins", () => {
  const r = repo();
  const a = r.commit({ "index.html": "1" });
  const b = r.commit({ "licences/index.html": "2" });
  const h = r.commit({ "privacy/index.html": "3" });
  assert.strictEqual(base(r.dir, { head: h, previous: [h, "deadbeefdeadbeef", b, b, a] }).base, b);
  assert.strictEqual(base(r.dir, { head: h, previous: ["not a sha; rm -rf", b] }).base, b);
});

test("a force push or rebase: a previous commit that is no longer an ancestor falls back to the merge base", () => {
  const r = repo();
  const root = r.commit({ "index.html": "1" });
  const old = r.commit({ "licences/index.html": "2" });
  g(r.dir, "reset", "-q", "--hard", root);
  const h = r.commit({ "privacy/index.html": "3" });
  const x = base(r.dir, { head: h, previous: [old] });
  assert.strictEqual(x.base, root); assert.match(x.why, /history was rewritten/);
  assert.deepStrictEqual(pages(r.dir, x.base, x.head), ["https://data.yappman.com/privacy/"]);
});

test("no previous run: the commit before HEAD; the first commit of a repository: the empty tree (every page)", () => {
  const r = repo();
  const only = r.commit({ "index.html": "1", "licences/index.html": "2" });
  const first = base(r.dir, { head: only, previous: [] });
  assert.strictEqual(first.base, EMPTY_TREE);
  assert.deepStrictEqual(pages(r.dir, first.base, first.head), ["https://data.yappman.com/", "https://data.yappman.com/licences/"]);
  const h = r.commit({ "privacy/index.html": "3" });
  assert.strictEqual(base(r.dir, { head: h, previous: [] }).base, only);
  assert.strictEqual(base(r.dir, { head: h, previous: ["0000000000000000000000000000000000000000"] }).base, only);
});

test("the same head again (a re-run): the base is the commit before it only if no earlier run is known; with an earlier run it is that run's commit", () => {
  const r = repo();
  const a = r.commit({ "index.html": "1" });
  const h = r.commit({ "privacy/index.html": "2" });
  assert.strictEqual(base(r.dir, { head: h, previous: [h, a] }).base, a);
  assert.strictEqual(base(r.dir, { head: h, previous: [h] }).base, a); // only the head known: HEAD~1
});

test("a manual --input is used as given, and must be a commit; an option-like value is refused", () => {
  const r = repo();
  const a = r.commit({ "index.html": "1" });
  const h = r.commit({ "privacy/index.html": "2" });
  assert.strictEqual(base(r.dir, { head: h, input: a, previous: [h] }).base, a);
  assert.strictEqual(base(r.dir, { head: h, input: "main~1" }).base, a);
  assert.throws(() => base(r.dir, { head: h, input: "--output=x" }), /not a commit id or a plain ref/);
  assert.throws(() => base(r.dir, { head: h, input: "nosuchref" }), /not a commit/);
  assert.throws(() => base(r.dir, { head: "nosuchhead" }), /not a commit/);
});

test("the command line: prints only the SHA on stdout, explains on stderr, argument errors exit 1", () => {
  const r = repo();
  const a = r.commit({ "index.html": "1" });
  const h = r.commit({ "privacy/index.html": "2" });
  const ok = cp.spawnSync(process.execPath, [SCRIPT, "--head", h, "--previous", `${h} ${a}`], { cwd: r.dir, encoding: "utf8" });
  assert.strictEqual(ok.status, 0); assert.strictEqual(ok.stdout.trim(), a); assert.match(ok.stderr, /last pinged commit/);
  for (const args of [[], ["--head"], ["--head", h, "--bogus", "x"], ["--head", "nosuch"]]) assert.strictEqual(cp.spawnSync(process.execPath, [SCRIPT, ...args], { cwd: r.dir, encoding: "utf8" }).status, 1);
  assert.deepStrictEqual(parseArgs(["--head", "abc", "--previous", "a b  c"]).previous, ["a", "b", "c"]);
});

test("the real case, when this repository has the commits: 7eec60a..9e7821c pings exactly the 13 pages changed by the push", () => {
  const top = path.join(__dirname, "..", "..");
  const has = s => { try { cp.execFileSync("git", ["cat-file", "-e", s + "^{commit}"], { cwd: top, stdio: "ignore" }); return true; } catch { return false; } };
  if (!has("7eec60abf9142f17c38acbd6d9fbe25bc023d1cd") || !has("9e7821c3b8e21cf49bd3affdc0890d358aef4f4d")) return;
  const x = base(top, { head: "9e7821c3b8e21cf49bd3affdc0890d358aef4f4d", previous: ["7eec60abf9142f17c38acbd6d9fbe25bc023d1cd"] });
  const got = pages(top, x.base, x.head);
  assert.strictEqual(got.length, 13);
  for (const p of ["/", "/actors/", "/au-shelf-price-index/", "/data-quality/", "/demos/", "/licences/", "/methodology/", "/notices/", "/notices/default-retailers/", "/notices/matchkey/", "/press/", "/privacy/", "/shelf-price-index/"]) assert.ok(got.includes("https://data.yappman.com" + p), p);
});

test("the script uses only child_process (git with fixed arguments): no network, eval or shell", () => {
  const src = fs.readFileSync(SCRIPT, "utf8");
  assert.doesNotMatch(src, /require\(["'](https?|net|dgram|dns|tls|vm|worker_threads)["']\)/);
  assert.doesNotMatch(src, /\beval\s*\(|new Function|fetch\s*\(|\bexec\s*\(|execSync|shell:\s*true/);
  assert.deepStrictEqual([...src.matchAll(/require\(["']([^"']+)["']\)/g)].map(m => m[1]), ["child_process"]);
});
