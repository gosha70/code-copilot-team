// agent-caps.test.mjs — T7.2 concurrency + recursion caps (FR-011). Run via
// tests/test-pi-runtime.sh. Pure logic: no spawn.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_MAX_CONCURRENCY,
  DEFAULT_MAX_RECURSION,
  Semaphore,
  recursionExceeded,
  resolveCaps,
} from "../../adapters/pi/runtime/agents/caps.ts";

test("resolveCaps reads autonomy leaves, falls back to defaults", () => {
  assert.deepEqual(resolveCaps(undefined), {
    maxConcurrency: DEFAULT_MAX_CONCURRENCY,
    maxRecursion: DEFAULT_MAX_RECURSION,
  });
  assert.deepEqual(
    resolveCaps({ autonomy: { max_concurrency: 8, max_recursion: 3 } }),
    { maxConcurrency: 8, maxRecursion: 3 },
  );
});

test("resolveCaps rejects non-positive / non-integer overrides", () => {
  const c = resolveCaps({ autonomy: { max_concurrency: 0, max_recursion: -1 } });
  assert.deepEqual(c, {
    maxConcurrency: DEFAULT_MAX_CONCURRENCY,
    maxRecursion: DEFAULT_MAX_RECURSION,
  });
  assert.equal(
    resolveCaps({ autonomy: { max_concurrency: 2.5 } }).maxConcurrency,
    DEFAULT_MAX_CONCURRENCY,
  );
});

test("recursionExceeded: depth+1 must not exceed maxRecursion", () => {
  // maxRecursion 2 -> legal child depths are 1 and 2; depth 2 may not spawn.
  assert.equal(recursionExceeded(0, 2), false); // root spawns depth 1
  assert.equal(recursionExceeded(1, 2), false); // depth 1 spawns depth 2
  assert.equal(recursionExceeded(2, 2), true); // depth 2 may not spawn
});

test("Semaphore bounds concurrency to max in-flight", async () => {
  const sem = new Semaphore(2);
  let inFlight = 0;
  let peak = 0;
  const task = async () => {
    const release = await sem.acquire();
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    await new Promise((r) => setTimeout(r, 10));
    inFlight -= 1;
    release();
  };
  await Promise.all(Array.from({ length: 6 }, task));
  assert.equal(peak, 2, `peak concurrency ${peak} must not exceed 2`);
  assert.equal(inFlight, 0);
});

test("Semaphore releases are idempotent (double-release is a no-op)", async () => {
  const sem = new Semaphore(1);
  const r1 = await sem.acquire();
  r1();
  r1(); // must not add a phantom slot
  const r2 = await sem.acquire();
  let got3 = false;
  sem.acquire().then(() => (got3 = true));
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(got3, false, "only one slot may be held at a time");
  r2();
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(got3, true);
});
