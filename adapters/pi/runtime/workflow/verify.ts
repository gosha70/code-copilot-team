/**
 * Verification-gate integration (T6.2, FR-016).
 *
 * THIN DRIVER over a provider-neutral `verify-runner.sh` (mirror of review.ts /
 * review-round-runner.sh): the runner runs the configured gates and writes
 * `.cct/verify/result.json`; this module reads that artifact and exposes the
 * gate that blocks phase completion. It does NOT re-implement gate detection.
 *
 * Honesty model (mirror T5.1): each gate is supported | degraded | unsupported;
 * a PASS means the gate actually ran. A REQUIRED gate that is unsupported (no
 * substrate) is a HARD CONFIG ERROR, never a silent pass (decision D).
 *
 * Confirmed design: specs/pi-harness-adoption/design-t62-verify.md.
 */

import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

export const VERIFY_DIR_REL = path.join(".cct", "verify");
const RUNNER_GRACE_SEC = 30;

export type GateStatus = "supported" | "degraded" | "unsupported";

export interface GateResult {
  status: GateStatus;
  pass: boolean;
  detail?: string;
}

/** `.cct/verify/result.json` shape: gate name -> result. */
export type VerifyResult = Record<string, GateResult>;

export function verifyDir(projectRoot: string): string {
  return path.join(projectRoot, VERIFY_DIR_REL);
}

export function loadVerifyResult(projectRoot: string): VerifyResult | null {
  try {
    const raw = JSON.parse(
      fs.readFileSync(path.join(verifyDir(projectRoot), "result.json"), "utf8"),
    );
    return raw && typeof raw === "object" ? (raw as VerifyResult) : null;
  } catch {
    return null;
  }
}

/**
 * Locate `verify-runner.sh`: `CCT_VERIFY_RUNNER` env wins; else the sibling repo
 * `scripts/` relative to the Pi adapter dir; else null (mirror
 * `resolveReviewRunner`). Null does NOT mean "pass" — see `verifyGate`.
 */
export function resolveVerifyRunner(
  piAdapterDir: string | null,
): string | null {
  const env = process.env.CCT_VERIFY_RUNNER;
  if (env && fs.existsSync(env)) return env;
  if (piAdapterDir) {
    const guess = path.resolve(
      piAdapterDir,
      "..",
      "..",
      "scripts",
      "verify-runner.sh",
    );
    if (fs.existsSync(guess)) return guess;
  }
  return null;
}

export interface VerifyRunOutcome {
  ran: boolean;
  exitCode: number | null;
  reason: string;
}

/**
 * Invoke the verify runner over the required gates. The runtime's resolved
 * config sets the gate list; the runner writes `.cct/verify/result.json`.
 */
export function runVerify(
  projectRoot: string,
  runnerPath: string | null,
  gates: string[],
  timeoutSec: number,
): VerifyRunOutcome {
  if (!runnerPath) {
    return {
      ran: false,
      exitCode: null,
      reason:
        "verify runner not found (set CCT_VERIFY_RUNNER or install scripts/verify-runner.sh)",
    };
  }
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    CCT_VERIFY_GATES: gates.join(","),
  };
  // Invoke via `bash <script>` so the runner needs no executable bit.
  const r = spawnSync("bash", [runnerPath, projectRoot], {
    env,
    encoding: "utf8",
    timeout: (timeoutSec + RUNNER_GRACE_SEC) * 1000,
  });
  if (r.error) {
    return {
      ran: false,
      exitCode: null,
      reason: `verify runner failed: ${r.error.message}`,
    };
  }
  const code = r.status ?? 0;
  return {
    ran: true,
    exitCode: code,
    reason: (r.stderr ?? "").trim() || `verify exit ${code}`,
  };
}

export interface VerifyGate {
  pass: boolean;
  reason: string;
}

/**
 * The verification gate — a phase-complete conjunct alongside the SDD + review
 * gates. Blocks only on the REQUIRED gates (decision C/D). A required gate is
 * satisfied ONLY by a real PASS in `result.json`. Failure modes, all fail-CLOSED
 * for a non-empty required list (the absent-runner condition, decision D):
 *   - required list empty            -> pass (nothing to enforce)
 *   - no result.json present         -> FAIL (never ran; runner may be absent)
 *   - a required gate is `unsupported` -> FAIL (hard config error — no substrate)
 *   - a required gate did not pass     -> FAIL
 */
export function verifyGate(
  projectRoot: string,
  requiredGates: string[],
  phase: string,
): VerifyGate {
  if (requiredGates.length === 0) {
    return { pass: true, reason: "no verification gates required" };
  }
  if (phase !== "build" && phase !== "review") {
    return {
      pass: true,
      reason: "verification gate applies to build/review only",
    };
  }
  const result = loadVerifyResult(projectRoot);
  if (!result) {
    return {
      pass: false,
      reason:
        `required verification has not run (no .cct/verify/result.json) for gates: ${requiredGates.join(", ")}; ` +
        "run /cct:verify",
    };
  }
  const problems: string[] = [];
  for (const gate of requiredGates) {
    const g = result[gate];
    if (!g) {
      problems.push(`${gate}: did not run`);
    } else if (g.status === "unsupported") {
      problems.push(
        `${gate}: REQUIRED but unsupported (no substrate) — a config error, not a pass`,
      );
    } else if (!g.pass) {
      problems.push(`${gate}: FAIL${g.detail ? ` (${g.detail})` : ""}`);
    }
  }
  if (problems.length === 0) {
    return { pass: true, reason: "all required verification gates passed" };
  }
  return {
    pass: false,
    reason: `required verification not satisfied:\n  - ${problems.join("\n  - ")}`,
  };
}

/**
 * Session-start mitigation (mirror midReviewWarning): if the last verify result
 * has a required gate failing/unsupported and no session cleared it, warn.
 * Returns a warning string to surface + audit, or null.
 */
export function verifyWarning(
  projectRoot: string,
  requiredGates: string[],
): string | null {
  if (requiredGates.length === 0) return null;
  const gate = verifyGate(projectRoot, requiredGates, "build");
  if (gate.pass) return null;
  return `unresolved verification for required gate(s) ${requiredGates.join(", ")} — run /cct:verify`;
}
