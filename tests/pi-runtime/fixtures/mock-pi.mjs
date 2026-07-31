#!/usr/bin/env node
// mock-pi.mjs — a stand-in for the `pi` binary, for T7.2 child-session runner
// tests. Deterministic, no LLM. Behaviour is driven by env vars:
//
//   MOCK_PI_ARGV_OUT   write JSON of argv (the flags the runner passed) here
//   MOCK_PI_SLEEP_MS   sleep this long before emitting (timeout/cancel tests)
//   MOCK_PI_EXIT       process exit code (default 0)
//   MOCK_PI_NO_ENVELOPE  emit no result envelope (error-path test)
//
// On the happy path it prints one `--mode json` result-envelope line carrying
// the T10.3 contract fields (subtype / total_cost_usd / session_id).

import fs from "node:fs";

const argv = process.argv.slice(2);
if (process.env.MOCK_PI_ARGV_OUT) {
  fs.writeFileSync(process.env.MOCK_PI_ARGV_OUT, JSON.stringify(argv));
}

function emitAndExit() {
  if (!process.env.MOCK_PI_NO_ENVELOPE) {
    process.stdout.write(
      JSON.stringify({
        type: "result",
        subtype: "success",
        total_cost_usd: 0.01,
        session_id: "sess-mock",
      }) + "\n",
    );
  }
  process.exit(Number(process.env.MOCK_PI_EXIT || "0"));
}

const sleep = Number(process.env.MOCK_PI_SLEEP_MS || "0");
if (sleep > 0) {
  // Stay alive so the runner's timeout/cancel path can kill us. SIGTERM ends
  // the process with a non-zero signal (default Node behaviour).
  setTimeout(emitAndExit, sleep);
} else {
  emitAndExit();
}
