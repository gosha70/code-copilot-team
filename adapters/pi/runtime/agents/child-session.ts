/**
 * Out-of-process subagent child-session runner (T7.2, FR-011).
 *
 * Mechanism (approved): spawn `pi --mode json -p <prompt>` as an isolated child
 * process — the SAME verified path T10.3's run_pi_session and the peer reviewer
 * already use. Pi exposes NO subagent primitive, result contract, timeout, or
 * recursion/concurrency API, so the orchestration here is CCT-first-party. The
 * manifest knobs pi's CLI CAN apply are genuinely enforced on the child:
 *
 *   model    -> --model            (tier carried verbatim from T7.1)
 *   thinking -> --thinking         (vocab-mapped; see mapThinking)
 *   tools    -> --tools <list>     (allowlist across built-in/extension/custom)
 *   isolation-> --no-session       (a fresh, ephemeral session = separate context)
 *
 * `permissions`, `skills`, and `context` (beyond isolation) have NO pi surface;
 * they are reported in `notEnforced`, never silently dropped or approximated.
 * See specs/pi-harness-adoption/design-t72-child-session-runner.md.
 */

import { spawn } from "node:child_process";

import type { AgentManifest, ThinkingLevel } from "./manifest.ts";
import { recursionExceeded } from "./caps.ts";
import { AGENT_DEPTH_ENV } from "./caps.ts";

/** Env var carrying an analytics correlation id into the child (full corr: T7.4). */
export const AGENT_CORRELATION_ENV = "CCT_AGENT_CORRELATION_ID";

/** SIGTERM grace before SIGKILL when killing a timed-out/cancelled child. */
const KILL_GRACE_MS = 2000;

export interface ChildRunOptions {
  manifest: AgentManifest;
  prompt: string;
  cwd: string;
  correlationId: string;
  timeoutSec: number;
  depth: number;
  maxRecursion: number;
}

export type ChildStatus =
  "ok" | "timeout" | "cancelled" | "error" | "cap-exceeded" | "no-runner";

export interface ChildResult {
  ran: boolean;
  status: ChildStatus;
  exitCode: number | null;
  sessionId: string | null;
  subtype: string | null;
  costUsd: number | null;
  /** Manifest fields with no pi surface, reported not enforced (never dropped). */
  notEnforced: string[];
  reason?: string;
}

/**
 * Map the neutral manifest thinking level to pi's `--thinking` value.
 * `inherit` -> omit the flag (no override); `none` -> `off`; low/medium/high
 * pass through. The manifest deliberately cannot express pi's minimal/xhigh/max
 * (T7.1 scope) — those are simply unreachable, never approximated.
 */
export function mapThinking(level: ThinkingLevel): string | null {
  switch (level) {
    case "inherit":
      return null;
    case "none":
      return "off";
    case "low":
    case "medium":
    case "high":
      return level;
    default:
      return null;
  }
}

export interface BuiltArgv {
  args: string[];
  env: Record<string, string>;
  notEnforced: string[];
}

/**
 * Pure translator: an AgentManifest + run options -> pi argv + child env, plus
 * the list of manifest fields that carry a request pi cannot enforce. No spawn.
 */
export function buildChildArgv(o: ChildRunOptions): BuiltArgv {
  const m = o.manifest;
  const args = ["--mode", "json", "-p", o.prompt, "--no-session"];

  if (m.model && m.model !== "inherit") args.push("--model", m.model);

  const thinking = mapThinking(m.thinking);
  if (thinking) args.push("--thinking", thinking);

  if (m.tools.length > 0) args.push("--tools", m.tools.join(","));

  // Fields with a request but no pi surface -> reported, not applied.
  const notEnforced: string[] = [];
  if (m.permissions && m.permissions !== "inherit")
    notEnforced.push("permissions");
  if (m.skills.length > 0) notEnforced.push("skills");
  if (m.context.length > 0) notEnforced.push("context");

  const env: Record<string, string> = {
    [AGENT_CORRELATION_ENV]: o.correlationId,
    [AGENT_DEPTH_ENV]: String(o.depth + 1),
  };

  return { args, env, notEnforced };
}

/** Scan pi's --mode json lines for the last result envelope (T10.3 contract). */
function parseEnvelope(stdout: string): {
  sessionId: string | null;
  subtype: string | null;
  costUsd: number | null;
} {
  let sessionId: string | null = null;
  let subtype: string | null = null;
  let costUsd: number | null = null;
  for (const line of stdout.split("\n")) {
    const t = line.trim();
    if (!t.startsWith("{")) continue;
    let obj: Record<string, unknown>;
    try {
      obj = JSON.parse(t);
    } catch {
      continue;
    }
    if ("session_id" in obj && typeof obj.session_id === "string")
      sessionId = obj.session_id;
    if ("subtype" in obj && typeof obj.subtype === "string")
      subtype = obj.subtype;
    if ("total_cost_usd" in obj && typeof obj.total_cost_usd === "number")
      costUsd = obj.total_cost_usd;
  }
  return { sessionId, subtype, costUsd };
}

/**
 * Spawn a subagent child session and resolve a typed ChildResult. Enforces the
 * recursion cap (depth), a wall-clock timeout (kill), and cooperative
 * cancellation via `signal`. Concurrency is bounded by the caller's Semaphore
 * (a single call cannot bound its peers). `runnerPath` overrides the pi binary
 * (tests point it at a mock).
 */
export function runChildSession(
  o: ChildRunOptions,
  opts: { runnerPath?: string; signal?: AbortSignal } = {},
): Promise<ChildResult> {
  const built = buildChildArgv(o);
  const base: Omit<ChildResult, "status" | "ran"> = {
    exitCode: null,
    sessionId: null,
    subtype: null,
    costUsd: null,
    notEnforced: built.notEnforced,
  };

  if (recursionExceeded(o.depth, o.maxRecursion)) {
    return Promise.resolve({
      ...base,
      ran: false,
      status: "cap-exceeded",
      reason: `recursion cap: depth ${o.depth} may not spawn a child past max_recursion=${o.maxRecursion}`,
    });
  }

  const runner = opts.runnerPath || process.env.CCT_PI_BIN || "pi";

  return new Promise<ChildResult>((resolve) => {
    let settled = false;
    let timedOut = false;
    let cancelled = false;
    let stdout = "";
    let stderr = "";

    const child = spawn(runner, built.args, {
      cwd: o.cwd,
      env: { ...process.env, ...built.env },
    });

    const done = (r: ChildResult): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      clearTimeout(killTimer);
      if (opts.signal) opts.signal.removeEventListener("abort", onAbort);
      resolve(r);
    };

    const hardKill = (): void => {
      child.kill("SIGKILL");
    };
    const softKill = (): void => {
      child.kill("SIGTERM");
      killTimer = setTimeout(hardKill, KILL_GRACE_MS);
    };
    let killTimer: ReturnType<typeof setTimeout> = setTimeout(() => {}, 0);
    clearTimeout(killTimer);

    const onAbort = (): void => {
      cancelled = true;
      softKill();
    };
    if (opts.signal) {
      if (opts.signal.aborted) {
        cancelled = true;
      }
      opts.signal.addEventListener("abort", onAbort, { once: true });
    }

    const timer =
      o.timeoutSec > 0
        ? setTimeout(() => {
            timedOut = true;
            softKill();
          }, o.timeoutSec * 1000)
        : setTimeout(() => {}, 0);
    if (o.timeoutSec <= 0) clearTimeout(timer);

    child.stdout?.on("data", (d) => (stdout += d.toString()));
    child.stderr?.on("data", (d) => (stderr += d.toString()));

    child.on("error", (err) => {
      const noRunner = (err as NodeJS.ErrnoException).code === "ENOENT";
      done({
        ...base,
        ran: false,
        status: noRunner ? "no-runner" : "error",
        reason: noRunner
          ? `pi runner not found ('${runner}'); set CCT_PI_BIN`
          : `child failed to start: ${err.message}`,
      });
    });

    child.on("close", (code) => {
      const env = parseEnvelope(stdout);
      const result: ChildResult = {
        ...base,
        ran: true,
        exitCode: code,
        sessionId: env.sessionId,
        subtype: env.subtype,
        costUsd: env.costUsd,
        status: "ok",
      };
      if (cancelled) {
        result.status = "cancelled";
        result.reason = "child cancelled via AbortSignal";
      } else if (timedOut) {
        result.status = "timeout";
        result.reason = `child exceeded ${o.timeoutSec}s wall-clock; killed`;
      } else if (code !== 0 && env.subtype === null && env.sessionId === null) {
        result.status = "error";
        result.reason = `pi exited ${code} with no result envelope${
          stderr ? `: ${stderr.trim().slice(0, 200)}` : ""
        }`;
      }
      done(result);
    });

    if (cancelled) softKill();
  });
}
