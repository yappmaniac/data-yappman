// node docs/release/test-workflow-pins.js : every action used by a workflow is pinned to a full commit id with its release in a
// comment, and actions/checkout is on a Node 24 release (v5 or later; v4 and older run on the deprecated Node 20).
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const dir = path.join(__dirname, "..", "..", ".github", "workflows");
let checked = 0;
for (const f of fs.readdirSync(dir).filter(n => /\.ya?ml$/.test(n))) {
  const lines = fs.readFileSync(path.join(dir, f), "utf8").split(/\r?\n/);
  lines.forEach((l, i) => {
    const m = /^\s*-?\s*uses:\s*(\S+)(.*)$/.exec(l);
    if (!m) return;
    const at = `${f}:${i + 1}`;
    const p = /^([\w.-]+\/[\w.\/-]+)@([0-9a-f]{40})\s+#\s*v(\d+)\.(\d+)\.(\d+)\s*$/.exec(m[1] + m[2]);
    assert.ok(p, `${at}: "${l.trim()}" must be pinned to a 40-character commit id with a "# vX.Y.Z" comment`);
    if (p[1] === "actions/checkout") assert.ok(Number(p[3]) >= 5, `${at}: actions/checkout v${p[3]} runs on Node 20; use v5 or later`);
    checked++;
  });
}
assert.ok(checked >= 2, "no workflow action found");
console.log(`workflow pins: ${checked} actions pinned; checkout on Node 24`);
