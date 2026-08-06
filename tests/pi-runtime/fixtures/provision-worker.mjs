// Fixture for the CONCURRENCY test (worktree-lifecycle.test.mjs). Spawned as a
// real child process: it blocks on a barrier file, then calls the real
// provisionWorktree() so multiple OS processes contend on the ledger lock
// simultaneously. Exits 0 on ok, 3 on refusal, 1 on error; prints one JSON line.
//
//   argv: <repoRoot> <workerId> <branch> <areasCsv> <barrierFile>
// The parent creates <barrierFile> to release all children at once.

import fs from "node:fs";
import { provisionWorktree } from "../../../adapters/pi/runtime/agents/worktree-lifecycle.ts";

const [repoRoot, workerId, branch, areasCsv, barrierFile] = process.argv.slice(2);
const areas = (areasCsv ?? "").split(",").map((s) => s.trim()).filter(Boolean);

// Busy-wait on the barrier so all children fire provisioning together. The lock
// is synchronous, so this genuinely exercises cross-process contention.
const deadline = Date.now() + 10_000;
while (!fs.existsSync(barrierFile)) {
  if (Date.now() > deadline) {
    process.stdout.write(JSON.stringify({ workerId, error: "barrier timeout" }) + "\n");
    process.exit(1);
  }
  // tight spin — the window we care about is tiny and this is a test child.
}

try {
  const res = provisionWorktree(
    repoRoot,
    { workerId, branch, areas },
    { mode: "print", now: new Date().toISOString() },
  );
  process.stdout.write(JSON.stringify({ workerId, ok: res.ok, path: res.path, errors: res.errors, reason: res.reason }) + "\n");
  process.exit(res.ok ? 0 : 3);
} catch (e) {
  process.stdout.write(JSON.stringify({ workerId, error: String(e?.message ?? e) }) + "\n");
  process.exit(1);
}
