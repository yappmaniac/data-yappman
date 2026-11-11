// node docs/release/indexnow-base.js --head SHA [--input REF] [--previous "SHA SHA ..."]   (run inside the repository)
//
// Prints the commit the IndexNow workflow compares with HEAD: every page changed from that commit to HEAD is pinged, so a
// push of several commits, or one that follows a missed run, still pings everything that changed since the last ping.
//
// Why not HEAD~1: the workflow runs after the Pages deployment, and the commit that deployment reports can be the one BEFORE the push
// (11 Nov 2026: a push of 9e7821c was reported as 7eec60a, so only that earlier release's pages were pinged). The push's own
// "before" commit is not in a workflow_run event either, so the workflow asks for the head commits of its own previous successful runs
// (--previous, newest first); the newest one that is still in the history is the last commit that was pinged.
//
// Order of choice:
//  1. --input REF (a manual run): used as given; it must resolve to a commit, or the script fails.
//  2. the first --previous commit that is an ancestor of HEAD;
//  3. if one exists but is not an ancestor (a force push or rebase): the merge base of it and HEAD;
//  4. no usable previous run (the first run, or only unknown commits): HEAD~1;
//  5. HEAD is the first commit: the empty tree, so every page is pinged.
// The commit equal to HEAD is skipped in 2 and 3 (an earlier run of the same HEAD). If the chosen base is HEAD itself, nothing changed
// and the workflow pings nothing.
// Only git is used, through execFileSync with fixed arguments; every SHA or ref is checked against /^[0-9a-fA-F]{7,40}$/ or a safe
// ref pattern before it reaches git, so a value from the workflow cannot add an option.
const { execFileSync } = require("child_process");

const EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const SHA_RE = /^[0-9a-fA-F]{7,40}$/;
const REF_RE = /^[A-Za-z0-9][A-Za-z0-9._\/~^-]{0,100}$/;

function git(args) {
  return execFileSync("git", args, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
}
function tryGit(args) { try { return git(args); } catch { return null; } }
const commitOf = ref => tryGit(["rev-parse", "--verify", "--quiet", ref + "^{commit}"]);
const isAncestor = (a, b) => { try { execFileSync("git", ["merge-base", "--is-ancestor", a, b], { stdio: "ignore" }); return true; } catch { return false; } };

function chooseBase({ head, input, previous }) {
  const headSha = commitOf(head);
  if (!headSha) throw new Error(`--head ${head} is not a commit in this repository`);
  if (input) {
    if (!SHA_RE.test(input) && !REF_RE.test(input)) throw new Error(`--input "${input}" is not a commit id or a plain ref name`);
    const b = commitOf(input);
    if (!b) throw new Error(`--input ${input} is not a commit in this repository`);
    return { base: b, head: headSha, why: "input" };
  }
  const prev = [...new Set((previous || []).filter(s => SHA_RE.test(s)).map(commitOf).filter(Boolean))].filter(s => s !== headSha);
  for (const p of prev) if (isAncestor(p, headSha)) return { base: p, head: headSha, why: "last pinged commit" };
  for (const p of prev) {
    const mb = tryGit(["merge-base", p, headSha]);
    if (mb) return { base: mb, head: headSha, why: "merge base with the last pinged commit (history was rewritten)" };
  }
  const parent = commitOf(headSha + "~1");
  if (parent) return { base: parent, head: headSha, why: prev.length ? "no previous run in this history; the commit before HEAD" : "no previous run; the commit before HEAD" };
  return { base: EMPTY_TREE, head: headSha, why: "first commit; every page" };
}

function parseArgs(args) {
  const o = {};
  for (let i = 0; i < args.length; i += 2) {
    const k = args[i];
    if (!["--head", "--input", "--previous"].includes(k)) throw new Error("unknown argument " + k);
    if (args[i + 1] === undefined) throw new Error(`${k} needs a value`);
    o[k.slice(2)] = args[i + 1];
  }
  if (!o.head) throw new Error("--head is required");
  o.previous = o.previous ? o.previous.split(/\s+/).filter(Boolean) : [];
  return o;
}

module.exports = { chooseBase, parseArgs, EMPTY_TREE };

if (require.main === module) {
  try {
    const r = chooseBase(parseArgs(process.argv.slice(2)));
    console.error(`indexnow base ${r.base} (${r.why}), head ${r.head}`);
    console.log(r.base);
  } catch (e) { console.error("indexnow-base: " + e.message); process.exit(1); }
}
