/**
 * Shell-hook subprocess adapter (T5.1, FR-010).
 *
 * Runs existing Claude Code `.sh` hooks as subprocesses, fed the neutral event
 * serialized to Claude-Code-shaped stdin JSON. Hook logic is NOT ported — the
 * scripts execute unmodified. The exit-code convention matches Claude Code:
 * 0 = allow, 2 = block (stderr is the reason); any other code is a non-blocking
 * error whose disposition follows the per-hook fail mode.
 *
 * Support gate (FR-010): only `supported` events are ever executed. A
 * `degraded` or `unsupported` event is reported and audited, never
 * approximated. Per-hook: timeout, bounded retry, fail-open/fail-closed, and an
 * audit record for every outcome (run, block, skip, error).
 */

import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

import type { CctLifecycleEvent } from "./events.ts";
import { toClaudeStdin } from "./events.ts";

export const DEFAULT_HOOK_TIMEOUT_MS = 5000;
export const DEFAULT_HOOK_RETRIES = 0;

/** Claude Code hook exit-code convention. */
const EXIT_ALLOW = 0;
const EXIT_BLOCK = 2;

export type FailMode = "open" | "closed";
export type HookStatus = "allow" | "block" | "skipped" | "error";

export interface HookScript {
  path: string;
  timeoutMs?: number;
}

export interface HookOpts {
  retries?: number;
  failMode?: FailMode; // disposition when a hook errors or times out
}

export interface HookOutcome {
  script: string | null;
  status: HookStatus;
  exitCode: number | null;
  reason: string;
}

export interface DispatchResult {
  event: string;
  support: string;
  ran: boolean;
  block: boolean;
  reason: string;
  outcomes: HookOutcome[];
}

/** Audit sink shape (a thin subset of AuditRecord, minus ts/mode). */
export type HookAuditFn = (rec: {
  actor: string;
  decision: string;
  rule: string | null;
  subject: string;
  origin: string;
}) => void;

function runOne(
  script: HookScript,
  stdin: string,
  retries: number,
  failMode: FailMode,
): HookOutcome {
  const timeout = script.timeoutMs ?? DEFAULT_HOOK_TIMEOUT_MS;
  let last: HookOutcome = {
    script: script.path,
    status: "error",
    exitCode: null,
    reason: "hook did not run",
  };
  for (let attempt = 0; attempt <= retries; attempt++) {
    const r = spawnSync(script.path, [], {
      input: stdin,
      timeout,
      encoding: "utf8",
    });
    if (r.error) {
      const code = (r.error as NodeJS.ErrnoException).code;
      const timedOut = code === "ETIMEDOUT" || r.signal != null;
      last = {
        script: script.path,
        status: "error",
        exitCode: null,
        reason: timedOut
          ? `hook timed out after ${timeout}ms`
          : `hook failed to run: ${r.error.message}`,
      };
      continue; // retry
    }
    const status = r.status ?? 0;
    const stderr = (r.stderr ?? "").trim();
    if (status === EXIT_BLOCK) {
      return {
        script: script.path,
        status: "block",
        exitCode: status,
        reason: stderr || "blocked by shell hook",
      };
    }
    if (status === EXIT_ALLOW) {
      return {
        script: script.path,
        status: "allow",
        exitCode: status,
        reason: "",
      };
    }
    last = {
      script: script.path,
      status: "error",
      exitCode: status,
      reason: stderr || `hook exited ${status}`,
    };
  }
  // Retries exhausted with no clean allow/block: apply the fail mode.
  if (failMode === "closed") {
    return { ...last, status: "block", reason: `${last.reason} (fail-closed)` };
  }
  return { ...last, status: "allow", reason: `${last.reason} (fail-open)` };
}

/**
 * Dispatch a lifecycle event to its resolved shell hooks. Gates on support,
 * runs each script in order, blocks on the first veto, and audits every
 * outcome. Never throws — enforcement must not crash on a hook fault.
 */
export function dispatchHooks(
  ev: CctLifecycleEvent,
  scripts: HookScript[],
  opts: HookOpts,
  auditFn: HookAuditFn,
): DispatchResult {
  const subject = ev.tool ? `${ev.event}:${ev.tool}` : ev.event;

  if (ev.support !== "supported") {
    auditFn({
      actor: `hook:${ev.event}`,
      decision: `skipped-${ev.support}`,
      rule: "hook.support-gate",
      subject,
      origin: "shell-hook",
    });
    return {
      event: ev.event,
      support: ev.support,
      ran: false,
      block: false,
      reason: `${ev.event} is ${ev.support} — not executed`,
      outcomes: [],
    };
  }

  const retries = opts.retries ?? DEFAULT_HOOK_RETRIES;
  const failMode: FailMode = opts.failMode ?? "open";
  const stdin = toClaudeStdin(ev);
  const outcomes: HookOutcome[] = [];

  for (const script of scripts) {
    const outcome = runOne(script, stdin, retries, failMode);
    outcomes.push(outcome);
    auditFn({
      actor: `hook:${ev.event}`,
      decision: outcome.status,
      rule: script.path,
      subject,
      origin: "shell-hook",
    });
    if (outcome.status === "block") {
      return {
        event: ev.event,
        support: ev.support,
        ran: true,
        block: true,
        reason: outcome.reason,
        outcomes,
      };
    }
  }

  return {
    event: ev.event,
    support: ev.support,
    ran: scripts.length > 0,
    block: false,
    reason: "",
    outcomes,
  };
}

/** Existing Claude Code PreToolUse veto scripts, by Pi tool name (reuse map). */
const PRE_TOOL_SCRIPTS: Record<string, string> = {
  edit: "protect-files.sh",
  write: "protect-files.sh",
  bash: "protect-git.sh",
};

function isExecutableFile(p: string): boolean {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

/**
 * Resolve the shell scripts that reuse existing Claude Code hooks for an event.
 * Only PreToolUse maps to reusable veto scripts today (protect-files.sh /
 * protect-git.sh); every other supported event resolves to none (a reported,
 * audited no-op) until a semantically-matching script exists.
 */
export function resolveHookScripts(
  ev: CctLifecycleEvent,
  scriptsDir: string | null,
): HookScript[] {
  if (!scriptsDir) return [];
  if (ev.event === "PreToolUse" && ev.tool && PRE_TOOL_SCRIPTS[ev.tool]) {
    const p = path.join(scriptsDir, PRE_TOOL_SCRIPTS[ev.tool]);
    if (isExecutableFile(p)) return [{ path: p }];
  }
  return [];
}

/**
 * Locate the directory holding the reusable `.sh` hooks. `CCT_HOOK_SCRIPTS_DIR`
 * wins when set; otherwise fall back to the sibling Claude Code plugin scripts
 * relative to the Pi adapter dir. Returns null when neither exists — the
 * adapter then no-ops cleanly and doctor reports "no scripts configured".
 */
export function resolveHookScriptsDir(
  piAdapterDir: string | null,
): string | null {
  const env = process.env.CCT_HOOK_SCRIPTS_DIR;
  if (env && fs.existsSync(env)) return env;
  if (piAdapterDir) {
    const sibling = path.resolve(
      piAdapterDir,
      "..",
      "claude-code",
      "plugin",
      "scripts",
    );
    if (fs.existsSync(sibling)) return sibling;
  }
  return null;
}
