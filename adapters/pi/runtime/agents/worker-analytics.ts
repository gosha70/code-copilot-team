/**
 * Worker analytics correlation + partial-failure handling (T7.4, FR-011/FR-013).
 *
 * Three deliverables, one cohesive module:
 *   1. runWorkerVerification — execute the FR-016 verify runner INSIDE a
 *      worker's worktree and map the outcome to a VerificationStatus (the field
 *      T7.3 only tracked). Reuses workflow/verify.ts unchanged.
 *   2. buildCorrelation / emitCorrelation — a neutral, REDACTED record linking a
 *      worker to its parent session + outcome, appended as JSONL.
 *   3. summarizeBatch — a pure, FAIL-CLOSED verdict over a set of workers.
 *
 * FR-021 BOUNDARY (must stay honest): T7.4 emits neutral correlation records and
 * executes worker verification. It does NOT translate the full CCT analytics
 * format, ingest into the analytics DB, or surface in Studio — that is FR-021 /
 * FR-026, a separate task with no capability id yet. See
 * specs/pi-harness-adoption/design-t74-worker-analytics.md.
 */

import * as fs from "node:fs";
import * as path from "node:path";

import {
  runVerify,
  verifyGate,
  resolveVerifyRunner,
} from "../workflow/verify.ts";
import { containsSecret } from "../workflow/memory.ts";
import type { VerificationStatus } from "./worktree.ts";
import type { ChildStatus } from "./child-session.ts";

export const WORKER_ANALYTICS_REL = path.join(".cct", "worker-analytics.jsonl");

// ── 1. worker verification execution ─────────────────────────────────────────

export interface WorkerVerificationResult {
  status: VerificationStatus; // passed | failed | pending
  ran: boolean;
  reason: string;
}

/**
 * Run the required verification gates inside a worker's worktree. Honest
 * mapping: the runner executed and the gate passed → "passed"; executed and
 * failed → "failed"; did NOT execute (no runner) → "pending" (never silently
 * "passed"). The caller records the status via worktree.setVerificationStatus.
 */
export function runWorkerVerification(
  worktreePath: string,
  gates: string[],
  timeoutSec: number,
  opts: { runner?: string | null; piAdapterDir?: string | null } = {},
): WorkerVerificationResult {
  const runner =
    opts.runner !== undefined
      ? opts.runner
      : resolveVerifyRunner(opts.piAdapterDir ?? null);
  const outcome = runVerify(worktreePath, runner, gates, timeoutSec);
  if (!outcome.ran) {
    return { status: "pending", ran: false, reason: outcome.reason };
  }
  const gate = verifyGate(worktreePath, gates, "build");
  return {
    status: gate.pass ? "passed" : "failed",
    ran: true,
    reason: gate.reason,
  };
}

// ── 2. worker → parent correlation record ────────────────────────────────────

export interface WorkerCorrelation {
  at: string; // ISO (injected)
  correlationId: string;
  workerId: string;
  branch: string;
  featureId: string | null;
  parentSessionId: string | null;
  childSessionId: string | null;
  depth: number;
  verification: VerificationStatus;
  childStatus: ChildStatus;
  costUsd: number | null;
}

export interface CorrelationInput {
  at: string;
  correlationId: string;
  workerId: string;
  branch: string;
  featureId?: string | null;
  parentSessionId?: string | null;
  childSessionId?: string | null;
  depth: number;
  verification: VerificationStatus;
  childStatus: ChildStatus;
  costUsd?: number | null;
}

/** Mask a field that carries a secret value; leave everything else intact. */
function redactField(value: string | null): string | null {
  if (value === null) return null;
  return containsSecret(value) ? "[REDACTED]" : value;
}

/**
 * Assemble a correlation record with every string field redacted before it can
 * be persisted (FR-021 redaction-before-persist). Pure.
 */
export function buildCorrelation(input: CorrelationInput): WorkerCorrelation {
  return {
    at: input.at,
    correlationId: redactField(input.correlationId) ?? "",
    workerId: redactField(input.workerId) ?? "",
    branch: redactField(input.branch) ?? "",
    featureId: redactField(input.featureId ?? null),
    parentSessionId: redactField(input.parentSessionId ?? null),
    childSessionId: redactField(input.childSessionId ?? null),
    depth: input.depth,
    verification: input.verification,
    childStatus: input.childStatus,
    costUsd: input.costUsd ?? null,
  };
}

/**
 * Append a correlation record as one JSONL line to `.cct/worker-analytics.jsonl`.
 * The record is (re)redacted here too, so a caller cannot bypass redaction.
 * Best-effort: never throws into the caller's control flow.
 */
export function emitCorrelation(
  projectRoot: string,
  record: WorkerCorrelation,
): boolean {
  try {
    const safe = buildCorrelation(record);
    const file = path.join(projectRoot, WORKER_ANALYTICS_REL);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.appendFileSync(file, JSON.stringify(safe) + "\n");
    return true;
  } catch {
    return false;
  }
}

// ── 3. partial-failure aggregation ───────────────────────────────────────────

export interface WorkerOutcome {
  workerId: string;
  verification: VerificationStatus;
  childStatus: ChildStatus;
}

export type BatchVerdict = "all-passed" | "partial" | "all-failed";

export interface BatchSummary {
  total: number;
  passed: number;
  failed: number;
  byChildStatus: Record<ChildStatus, number>;
  byVerification: Record<VerificationStatus, number>;
  failedWorkers: string[];
  verdict: BatchVerdict;
}

const CHILD_STATUSES: ChildStatus[] = [
  "ok",
  "timeout",
  "cancelled",
  "error",
  "cap-exceeded",
  "no-runner",
];
const VERIFICATION_STATUSES: VerificationStatus[] = [
  "pending",
  "passed",
  "failed",
];

/** A worker passes ONLY when verification passed AND the child ran ok. */
export function workerPassed(o: WorkerOutcome): boolean {
  return o.verification === "passed" && o.childStatus === "ok";
}

/**
 * Fail-closed batch summary. A pending/timeout/error/cancelled/cap-exceeded/
 * no-runner worker counts as NOT passed, so the batch is never "all-passed" on
 * an unresolved worker. (An empty batch is vacuously all-passed.)
 */
export function summarizeBatch(outcomes: WorkerOutcome[]): BatchSummary {
  const byChildStatus = Object.fromEntries(
    CHILD_STATUSES.map((s) => [s, 0]),
  ) as Record<ChildStatus, number>;
  const byVerification = Object.fromEntries(
    VERIFICATION_STATUSES.map((s) => [s, 0]),
  ) as Record<VerificationStatus, number>;

  const failedWorkers: string[] = [];
  let passed = 0;
  for (const o of outcomes) {
    byChildStatus[o.childStatus] += 1;
    byVerification[o.verification] += 1;
    if (workerPassed(o)) passed += 1;
    else failedWorkers.push(o.workerId);
  }

  const total = outcomes.length;
  const verdict: BatchVerdict =
    passed === total ? "all-passed" : passed === 0 ? "all-failed" : "partial";

  return {
    total,
    passed,
    failed: total - passed,
    byChildStatus,
    byVerification,
    failedWorkers,
    verdict,
  };
}
