/**
 * Peer-review runner integration + review-loop gate (T6.1, FR-015).
 *
 * THIN DRIVER over the provider-neutral `review-round-runner.sh`: the runner
 * owns the rounds, circuit breakers, read-only sandbox, tamper detection, and
 * `.cct/review/state.json`. This module only inits the loop, invokes one round,
 * reads the runner's artifacts, and exposes the mandatory-review gate — it does
 * NOT re-implement the loop (decision D). The runner resolves the peer provider
 * from providers.toml, so this integration is provider-agnostic; the Pi reviewer
 * provider (providers.pi) is Slice B and stays `disabled`.
 *
 * Confirmed design: specs/pi-harness-adoption/design-t61-review-runner.md.
 */

import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

export const REVIEW_DIR_REL = path.join(".cct", "review");

export interface ReviewLimits {
  maxRounds: number; // limits.max_review_rounds
  timeoutSec: number; // limits.timeout_sec
}

export interface ReviewSubmitParams {
  featureId: string;
  phase: string; // "plan" | "build" (runner vocabulary)
  subjectProvider: string; // "pi"
  peerProvider: string;
  reviewScope: string; // "code" | "design" | "both"
  targetRef: string;
  loopStart: number; // unix seconds
}

export function reviewDir(projectRoot: string): string {
  return path.join(projectRoot, REVIEW_DIR_REL);
}

function readJson(file: string): Record<string, unknown> | null {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

export function loadLoopSummary(
  projectRoot: string,
): Record<string, unknown> | null {
  return readJson(path.join(reviewDir(projectRoot), "loop-summary.json"));
}

export function loadReviewState(
  projectRoot: string,
): Record<string, unknown> | null {
  return readJson(path.join(reviewDir(projectRoot), "state.json"));
}

/** Initialize `.cct/review/state.json` for a new loop; the runner then owns it. */
export function initReviewState(
  projectRoot: string,
  p: ReviewSubmitParams,
): void {
  const dir = reviewDir(projectRoot);
  fs.mkdirSync(dir, { recursive: true });
  const state = {
    current_round: 0,
    attempt: 1,
    loop_start: p.loopStart,
    feature_id: p.featureId,
    phase: p.phase,
    subject_provider: p.subjectProvider,
    peer_provider: p.peerProvider,
    review_scope: p.reviewScope,
    target_ref: p.targetRef,
    last_verdict: null,
    findings: {},
  };
  fs.writeFileSync(
    path.join(dir, "state.json"),
    JSON.stringify(state, null, 2) + "\n",
  );
}

/**
 * Locate `review-round-runner.sh`: `CCT_REVIEW_RUNNER` wins; else the sibling
 * repo `scripts/` relative to the Pi adapter dir; else null (reported no-op,
 * never a crash — mirrors T5.1's `resolveHookScriptsDir`).
 */
export function resolveReviewRunner(
  piAdapterDir: string | null,
): string | null {
  const env = process.env.CCT_REVIEW_RUNNER;
  if (env && fs.existsSync(env)) return env;
  if (piAdapterDir) {
    const guess = path.resolve(
      piAdapterDir,
      "..",
      "..",
      "scripts",
      "review-round-runner.sh",
    );
    if (fs.existsSync(guess)) return guess;
  }
  return null;
}

export type RoundStatus = "pass" | "fail" | "breaker" | "error" | "no-runner";

export interface ReviewRoundOutcome {
  ran: boolean;
  exitCode: number | null; // 0 PASS, 1 FAIL/INVALID, 2 BREAKER
  status: RoundStatus;
  verdict: string | null;
  reason: string;
}

/**
 * Invoke ONE review round through the runner. The runtime's RESOLVED config
 * sets `CCT_REVIEW_*` unconditionally, overriding any ambient shell values: the
 * env layer's sanctioned path into config is `CCT_CONFIG__*`, so honoring
 * ambient `CCT_REVIEW_*` too would open a second, unaudited override channel
 * (decision C).
 */
export function runReviewRound(
  projectRoot: string,
  runnerPath: string | null,
  limits: ReviewLimits,
  providerProfile?: string,
): ReviewRoundOutcome {
  if (!runnerPath) {
    return {
      ran: false,
      exitCode: null,
      status: "no-runner",
      verdict: null,
      reason:
        "review runner not found (set CCT_REVIEW_RUNNER or install scripts/review-round-runner.sh)",
    };
  }
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    CCT_REVIEW_MAX_ROUNDS: String(limits.maxRounds),
    CCT_REVIEW_TIMEOUT_SEC: String(limits.timeoutSec),
  };
  if (providerProfile) env.CCT_PROVIDER_PROFILE = providerProfile;
  const r = spawnSync(runnerPath, [projectRoot], { env, encoding: "utf8" });
  if (r.error) {
    return {
      ran: false,
      exitCode: null,
      status: "error",
      verdict: null,
      reason: `review runner failed to run: ${r.error.message}`,
    };
  }
  const code = r.status ?? 0;
  const verdict =
    (loadLoopSummary(projectRoot)?.verdict as string | undefined) ?? null;
  const status: RoundStatus =
    code === 0 ? "pass" : code === 2 ? "breaker" : "fail";
  return {
    ran: true,
    exitCode: code,
    status,
    verdict,
    reason: (r.stderr ?? "").trim() || `round exit ${code}`,
  };
}

/** Does the current loop-summary satisfy a mandatory-review gate? */
export function reviewPasses(projectRoot: string): boolean {
  const s = loadLoopSummary(projectRoot);
  return !!s && (s.verdict === "PASS" || s.bypass === true);
}

export interface ReviewGate {
  pass: boolean;
  reason: string;
}

/**
 * Mandatory-review gate — the Stop-hook replacement (decision A). When review is
 * mandatory, a build/review phase may not complete without a PASS or bypass
 * loop-summary. INVALID / FAIL / breaker / missing all fail the gate.
 */
export function reviewGate(
  projectRoot: string,
  mandatory: boolean,
  phase: string,
): ReviewGate {
  if (!mandatory) return { pass: true, reason: "review not mandatory" };
  if (phase !== "build" && phase !== "review") {
    return { pass: true, reason: "review gate applies to build/review only" };
  }
  if (reviewPasses(projectRoot)) {
    return { pass: true, reason: "review PASS/bypass on record" };
  }
  const v =
    (loadLoopSummary(projectRoot)?.verdict as string | undefined) ?? "<none>";
  return {
    pass: false,
    reason:
      `mandatory review not satisfied (loop-summary verdict: ${v}); ` +
      "run /cct:review-submit until PASS, or /cct:review-decide approve",
  };
}

/**
 * Session-start mitigation (decision A): if a loop is in progress or FAILed with
 * no PASS/bypass summary, the reviewer walked away mid-review. Returns a warning
 * to surface + audit — Pi has no Stop event to catch this at session end.
 */
export function midReviewWarning(projectRoot: string): string | null {
  const st = loadReviewState(projectRoot);
  if (!st || reviewPasses(projectRoot)) return null;
  const v = (st.last_verdict as string | undefined) ?? "in-progress";
  return (
    `an unresolved peer-review loop for '${st.feature_id ?? "<feature>"}' ` +
    `(last verdict: ${v}) — complete it with /cct:review-submit or /cct:review-decide`
  );
}

export type ReviewDecision = "approve" | "reject" | "retry";

/** Record a decision; on approve, write the `bypass:true` loop-summary. */
export function writeDecision(
  projectRoot: string,
  decision: ReviewDecision,
  detail: string,
  now: string,
): void {
  const dir = reviewDir(projectRoot);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, "decision.json"),
    JSON.stringify({ decision, detail, at: now }, null, 2) + "\n",
  );
  if (decision !== "approve") return;
  const st = loadReviewState(projectRoot) ?? {};
  const summary = {
    feature_id: st.feature_id ?? null,
    date: now.slice(0, 10),
    phase: st.phase ?? null,
    verdict: (st.last_verdict as string | undefined) ?? "FAIL",
    rounds_completed: st.current_round ?? 0,
    attempt_count: st.attempt ?? 1,
    subject_provider: st.subject_provider ?? null,
    peer_provider: st.peer_provider ?? null,
    bypass: true,
    target_ref: st.target_ref ?? null,
    findings: st.findings ?? {},
  };
  fs.writeFileSync(
    path.join(dir, "loop-summary.json"),
    JSON.stringify(summary, null, 2) + "\n",
  );
}
