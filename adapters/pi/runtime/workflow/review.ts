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

// Grace added to the runner's own timeout budget for the belt-and-braces
// spawn timeout, so a hung reviewer process cannot block the Pi session.
const RUNNER_GRACE_SEC = 30;

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
  const r = spawnSync(runnerPath, [projectRoot], {
    env,
    encoding: "utf8",
    timeout: (limits.timeoutSec + RUNNER_GRACE_SEC) * 1000,
  });
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

/** Remove resolved-loop artifacts so a fresh loop's gate reflects only itself. */
function clearReviewArtifacts(projectRoot: string): void {
  const dir = reviewDir(projectRoot);
  for (const f of [
    "loop-summary.json",
    "breaker-tripped.json",
    "decision.json",
  ]) {
    try {
      fs.rmSync(path.join(dir, f));
    } catch {
      /* absent — nothing to clear */
    }
  }
}

/**
 * Decide init-vs-continue for a submit. Re-initializing resets the runner's
 * breaker inputs (current_round, loop_start, findings), so we CONTINUE an
 * unresolved loop on the same feature/phase — the runner's max-rounds/timeout/
 * stale breakers must keep accumulating across re-submits (decision D; the
 * Claude /review-submit skill likewise "initializes OR continues"). We start a
 * fresh loop only when there is no loop, the prior loop is resolved
 * (PASS/bypass), or the feature/phase changed — clearing stale artifacts so the
 * gate does not read a prior loop's PASS.
 */
export function prepareReviewLoop(
  projectRoot: string,
  p: ReviewSubmitParams,
): "init" | "continue" {
  const st = loadReviewState(projectRoot);
  const sameTarget =
    !!st && st.feature_id === p.featureId && st.phase === p.phase;
  if (sameTarget && !reviewPasses(projectRoot)) return "continue";
  clearReviewArtifacts(projectRoot);
  initReviewState(projectRoot, p);
  return "init";
}

export interface SubmitOutcome extends ReviewRoundOutcome {
  mode: "init" | "continue";
}

/**
 * Full submit: prepare the loop (init or continue) then run one round. Extracted
 * here rather than inlined in the index.ts handler so the init-vs-continue
 * decision is reachable by the suite — the handler layer was the untested seam.
 */
export function submitReviewRound(
  projectRoot: string,
  p: ReviewSubmitParams,
  runnerPath: string | null,
  limits: ReviewLimits,
  providerProfile?: string,
): SubmitOutcome {
  const mode = prepareReviewLoop(projectRoot, p);
  const outcome = runReviewRound(
    projectRoot,
    runnerPath,
    limits,
    providerProfile,
  );
  return { ...outcome, mode };
}

/**
 * Resolve the review target ref. An explicit arg wins; else the merge-base with
 * the default branch (so a MULTI-commit feature is reviewed whole, not just its
 * last commit); else HEAD~1.
 */
export function resolveTargetRef(projectRoot: string, arg?: string): string {
  if (arg) return arg;
  try {
    const r = spawnSync(
      "git",
      ["-C", projectRoot, "merge-base", "master", "HEAD"],
      { encoding: "utf8" },
    );
    const base = (r.stdout ?? "").trim();
    if (r.status === 0 && base) return base;
  } catch {
    /* git unavailable — fall back */
  }
  return "HEAD~1";
}

/**
 * Peer-review session contract (T6.3, FR-000a). These read the launcher-set
 * `CCT_PEER_*` env as SESSION INTENT only — they never mutate persisted config,
 * and the precedence is always explicit-arg > env > profile default.
 */
export function sessionPeerProvider(arg: string): string {
  return arg || process.env.CCT_PEER_PROVIDER || "";
}

export function sessionReviewScope(): string {
  const s = process.env.CCT_PEER_REVIEW_SCOPE;
  return s === "code" || s === "design" || s === "both" ? s : "both";
}

/**
 * Audited peer-review override (decision B): `--peer-review-off`
 * (`CCT_PEER_REVIEW_ENABLED=false`) or `CCT_PEER_BYPASS=true`. This NEVER
 * downgrades `review.mandatory` (config-authoritative policy is untouched) — it
 * only signals that the mandatory-review gate should be waived for THIS session,
 * and every use is audited by the caller. Peer-review only; no reach into
 * verify/permissions/SDD gates.
 */
export function peerReviewDisabled(): boolean {
  return (
    process.env.CCT_PEER_REVIEW_ENABLED === "false" ||
    process.env.CCT_PEER_BYPASS === "true"
  );
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

/**
 * #233: the deterministic breaker-context resolution shared with
 * scripts/review-decide.sh. With breaker-tripped.json missing, the context
 * is RECONSTRUCTED — bound to THIS feature via state.json's feature_id,
 * never a scan of other features' ledgers — and the provenance is returned
 * so the driver can validate it against the escalation it resolves.
 * Throws with a precise, human-relayable message on every refusal.
 */
function resolveBreakerContext(projectRoot: string): {
  breakerType: string;
  reconstructedFrom?: string;
} {
  const btf = path.join(reviewDir(projectRoot), "breaker-tripped.json");
  const breaker = readJson(btf);
  if (breaker) {
    const bt =
      (breaker.breaker_type as string | undefined) ??
      (breaker.breaker as string | undefined) ??
      "unknown";
    return { breakerType: bt };
  }
  const st = loadReviewState(projectRoot);
  const fid = st?.feature_id;
  if (typeof fid !== "string" || fid.length === 0) {
    throw new Error(
      "no .cct/review/breaker-tripped.json and state.json carries no feature_id — " +
        "cannot bind a reconstruction to a feature. Nothing to decide.",
    );
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(fid)) {
    throw new Error(
      `state.json feature_id '${fid}' is not a safe path segment — refusing.`,
    );
  }
  const escDir = path.join(
    projectRoot,
    ".cct",
    "auto-build",
    fid,
    "escalations",
  );
  let newest: string | undefined;
  let newestDetail = "";
  let i = 1;
  for (;;) {
    const esc = path.join(escDir, `esc-${i}.json`);
    if (!fs.existsSync(esc)) break;
    const rec = readJson(esc);
    if (!rec || typeof rec.resolved !== "boolean") {
      throw new Error(
        `escalation record ${esc} is unreadable — refusing to reconstruct from corrupt state.`,
      );
    }
    if (rec.reason === "review_breaker" && rec.resolved === false) {
      newest = esc;
      newestDetail = typeof rec.detail === "string" ? rec.detail : "";
    }
    i += 1;
  }
  // A gap (esc-2 missing while esc-3 exists) hides everything above it
  // from the sequential scan — an unresolved later record must never read
  // as "nothing to decide". Same fail-closed rule as the driver.
  const top = i - 1;
  if (fs.existsSync(escDir)) {
    for (const f of fs.readdirSync(escDir)) {
      const m = /^esc-(\d+)\.json$/.exec(f);
      if (m && Number(m[1]) > top) {
        throw new Error(
          `escalation records are gapped (esc-${top + 1} missing while ${f} exists) — ` +
            "the sequence cannot be trusted; refusing to reconstruct.",
        );
      }
    }
  }
  if (!newest) {
    throw new Error(
      "No active circuit breaker: .cct/review/breaker-tripped.json does not exist and " +
        `no unresolved review_breaker escalation was found under .cct/auto-build/${fid}/escalations/. ` +
        "Nothing to decide.",
    );
  }
  const breakerType = /review runner exited \d+/.test(newestDetail)
    ? "runner_crash_legacy"
    : "reconstructed";
  return { breakerType, reconstructedFrom: newest };
}

/**
 * Record a decision; on approve, write the `bypass:true` loop-summary.
 * Same deterministic contract as scripts/review-decide.sh (#233): the
 * breaker context is resolved (or feature-bound reconstructed, with
 * provenance) BEFORE anything is written, retry state is made durable
 * BEFORE the decision is published, and every failure throws leaving NO
 * consumable decision.
 */
export function writeDecision(
  projectRoot: string,
  decision: ReviewDecision,
  detail: string,
  now: string,
): void {
  const dir = reviewDir(projectRoot);
  fs.mkdirSync(dir, { recursive: true });
  const ctx = resolveBreakerContext(projectRoot);
  if (decision === "retry") {
    // #233 second-order trap: retry semantics (attempt bump + loop_start
    // reset) are mandatory and must be DURABLE before the decision marker
    // exists — the driver consumes the decision expecting them applied.
    const st = loadReviewState(projectRoot);
    if (!st) {
      throw new Error(
        "retry needs .cct/review/state.json (attempt bump + loop_start reset) " +
          "and it is missing or unreadable — no decision was recorded.",
      );
    }
    const attempt = typeof st.attempt === "number" ? st.attempt : 1;
    st.attempt = attempt + 1;
    st.loop_start = Math.floor(Date.now() / 1000);
    fs.writeFileSync(
      path.join(dir, "state.json"),
      JSON.stringify(st, null, 2) + "\n",
    );
  }
  fs.writeFileSync(
    path.join(dir, "decision.json"),
    JSON.stringify(
      {
        decision,
        detail,
        at: now,
        breaker_type: ctx.breakerType,
        ...(ctx.reconstructedFrom
          ? { reconstructed_from: ctx.reconstructedFrom }
          : {}),
      },
      null,
      2,
    ) + "\n",
  );
  fs.rmSync(path.join(dir, "breaker-tripped.json"), { force: true });
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
