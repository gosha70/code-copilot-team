# T7.4 Design Read — Worker analytics correlation + partial-failure handling (FR-011/FR-013)

Status: **design read — approval needed on scope, the correlation sink, and the
verdict policy before implementing.** T7.4 is P1. It closes the two pieces T7.2
and T7.3 deferred: it **executes verification inside a worker worktree** (setting
the `verificationStatus` T7.3 only tracked), **correlates** each worker back to
its parent session, and **aggregates partial failures** across a worker set.

## FR context

- **FR-011** subagents clause: "…analytics correlation."
- **FR-013** worktree state: `verification` status — T7.3 tracked it; T7.4 sets it.
- **FR-021** (full analytics format: Pi events → the neutral CCT analytics
  format, Studio/DB ingestion, redaction) is a **separate, broader task** — it
  has **no capability id yet** and is not T7.4. T7.4 emits **worker-correlation
  records** in a neutral, redacted shape; wiring them into the analytics DB /
  Studio is FR-021 / FR-026 later. This boundary keeps T7.4 honest.

## What exists today (reuse, not rebuild)

- **The FR-016 verify runner** (`workflow/verify.ts`): `runVerify(projectRoot,
  runner, gates, timeoutSec)` spawns `bash <runner> <projectRoot>` and writes
  `.cct/verify/result.json`; `verifyGate(projectRoot, gates, phase)` → `{pass,
  reason}`. Pass `projectRoot = a worker's worktreePath` and verification runs
  **in that worktree** — the execution is real and reusable. Tested today via a
  stub runner + `CCT_VERIFY_RUNNER` (reuse that pattern).
- **T7.2 correlation wiring**: `child-session.ts` already injects
  `CCT_AGENT_CORRELATION_ID` + `CCT_AGENT_DEPTH` into each child, and
  `ChildResult` carries `sessionId` / `subtype` / `costUsd`. The linkage
  material already exists per worker.
- **T7.3 ledger**: `setVerificationStatus(ledger, workerId, status)` +
  `WorkerRecord` (workerId/branch/featureId/worktreePath). T7.4 fills the status.
- **Redaction**: `workflow/memory.ts` exports `containsSecret(text)` over
  `SECRET_PATTERNS` (sk-/AKIA/gh_/JWT/PEM/Slack/key=value). Reuse it at field
  granularity — no new pattern list (a hardcoded second copy would drift).

## Scope of T7.4 (the three deliverables)

1. **Worker verification execution.** `runWorkerVerification(worktreePath, gates,
   timeoutSec, runner?)`: reuse `runVerify` + `verifyGate` at the worktree →
   map to a `VerificationStatus`. Honest mapping: `ran && pass → "passed"`;
   `ran && !pass → "failed"`; `!ran → "pending"` (runner absent — verification
   did not execute; NOT silently "passed"). Caller records it via T7.3's
   `setVerificationStatus`.
2. **Worker→parent correlation record.** A neutral, **redacted** record linking a
   worker to its session and outcome, appended as JSONL to
   `.cct/worker-analytics.jsonl`.
3. **Partial-failure handling.** A pure aggregator over a set of worker outcomes
   → a batch summary + a **fail-closed verdict**.

## Correlation record (proposed)

```ts
export interface WorkerCorrelation {
  at: string;                 // ISO (injected, like checkpoint.ts)
  correlationId: string;      // from CCT_AGENT_CORRELATION_ID (T7.2)
  workerId: string;           // T7.3 ledger
  branch: string;
  featureId: string | null;
  parentSessionId: string | null; // the CCT session that spawned the worker
  childSessionId: string | null;   // ChildResult.sessionId (the pi child)
  depth: number;
  verification: VerificationStatus; // passed | failed | pending
  childStatus: ChildStatus;         // ok | timeout | cancelled | error | cap-exceeded | no-runner
  costUsd: number | null;           // ChildResult.costUsd
}
```
Every string field is passed through a redactor before persistence: a field that
`containsSecret` is written as `"[REDACTED]"`. (Fields are structured/validated,
so this is belt-and-suspenders, but FR-021 requires redaction-before-persist.)

## Partial-failure aggregation (proposed)

```ts
export interface WorkerOutcome {
  workerId: string;
  verification: VerificationStatus;
  childStatus: ChildStatus;
}
export type BatchVerdict = "all-passed" | "partial" | "all-failed";
export interface BatchSummary {
  total: number;
  passed: number;               // verification "passed" AND childStatus "ok"
  failed: number;
  byChildStatus: Record<ChildStatus, number>;
  byVerification: Record<VerificationStatus, number>;
  verdict: BatchVerdict;
  failedWorkers: string[];
}
```
**Fail-closed verdict:** a worker counts as *passed* only when `verification ===
"passed"` AND `childStatus === "ok"`. `all-passed` iff every worker passed;
`all-failed` iff none passed; otherwise `partial`. A `pending` verification, a
timeout, an error, or a cap-exceeded all count as **not passed** — the batch is
never reported clean on an unresolved worker.

## Enforceable vs declared (T7.4)

| element | status | how |
|---|---|---|
| run verification in a worker worktree, set `verificationStatus` | **enforced** | reuse FR-016 `runVerify`/`verifyGate` at `worktreePath` |
| worker→parent correlation record (id/session/feature/outcome/cost) | **enforced** | append redacted JSONL to `.cct/worker-analytics.jsonl` |
| redaction before persistence | **enforced** | `containsSecret` per field → `[REDACTED]` |
| partial-failure aggregation + fail-closed verdict | **enforced** | pure `summarizeBatch` |
| full FR-021 analytics-format translation + Studio/DB ingestion | **deferred** | separate task (no capability id yet); T7.4 emits neutral records only |
| emit at a lifecycle Stop event | **degraded** | Pi has no Stop event — records are emitted at explicit worker-finish/cleanup, not a hook (consistent with the events boundary) |

## Module shape

One cohesive module `adapters/pi/runtime/agents/worker-analytics.ts`:
`runWorkerVerification` (impure: spawn verify at the worktree → status),
`buildCorrelation` (pure: assemble + redact), `emitCorrelation` (append JSONL),
`summarizeBatch` (pure). Mirrors `worktree.ts`'s pure-core + thin-exec split;
imports `runVerify`/`verifyGate` (verify.ts), `containsSecret` (memory.ts),
`VerificationStatus` (worktree.ts), `ChildStatus` (child-session.ts).

## Capability

No new id. **Update the `agents.worktrees` reason** across all four files:
verification is now **executed** for workers (was "tracked") and worker
correlation records are emitted (redacted). Merge execution stays T8; full
FR-021 analytics stays separate. Status remains **`degraded`** (merge not
executed; full analytics not translated). No status/kind drift.

## Scope (in / out)

**In:** `agents/worker-analytics.ts` (verification-execution → status,
correlation build+emit+redact, batch aggregation + verdict); `agents.worktrees`
reason refresh; tests (stub verify runner for execution over a temp worktree +
pure aggregation/redaction/mapping); design doc.

**Out (→ later):** the full FR-021 analytics format + Studio/DB ingestion; merge
execution (T8); teams (T8); live `/cct:` wiring; a Stop-event emit (no Pi hook).

## Open questions for approval

1. **Correlation sink** — `.cct/worker-analytics.jsonl` (append, redacted) as the
   interim neutral sink, pending FR-021 ingestion. Confirm this is the right
   place (vs `.cct/verify/` or the analytics dir).
2. **Verdict policy** — **fail-closed**: a worker passes only on `verification
   "passed"` AND `childStatus "ok"`; `pending`/timeout/error/cap-exceeded ⇒ not
   passed ⇒ batch never "all-passed". Confirm.
3. **`!ran` mapping** — a missing/failed verify runner maps to **`"pending"`**
   (did-not-execute), not `"failed"`, but still counts as not-passed in the
   verdict. Confirm this honest split (vs collapsing to `failed`).
4. **Module** — one `worker-analytics.ts` (execution + correlation + aggregation)
   vs splitting execution into `worker-verify.ts`. Lean: one cohesive module.
