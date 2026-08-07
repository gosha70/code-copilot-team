/**
 * CCT enterprise guardrails — STARTER TEMPLATE (issue #179).
 *
 * Deterministic, programmatic validation for your project, enforced at two
 * points (both verified against the installed pi package — see the README
 * honesty table for sources):
 *
 *   1. PRE-WRITE (`tool_call`, `write` tool): the INCOMING content —
 *      `event.input.content`, not the old file — is validated in a temp
 *      file BEFORE anything touches disk. Bad content never lands.
 *   2. POST-EXECUTION (`tool_result`, `write` + `edit` tools): the file as
 *      it now exists on disk is validated AFTER the tool ran; on failure
 *      the tool result is patched to an error carrying your validator's
 *      report, so the model sees it immediately and self-corrects.
 *      Validating the POST state means an edit that REPAIRS an already-
 *      broken file passes — there is no "legacy file deadlock".
 *
 * `edit` is deliberately not pre-gated: its input is a list of patches,
 * not final content; the post-execution check covers it one step later.
 *
 * KNOWN BOUNDARY: the `bash` tool is NOT gated here — a shell heredoc can
 * write files without triggering these hooks. Pair this template with your
 * harness's bash policy (the CCT runtime gates bash separately) and treat
 * this file as the write/edit guardrail, not a filesystem sandbox.
 *
 * Event/result shapes follow pi's shipped typings
 * (dist/core/extensions/types.d.ts): tool_call events are
 * `{ type, toolCallId, toolName, input }` with `write` input
 * `{ path, content }`; blocking returns `{ block: true, reason }`;
 * tool_result handlers chain like middleware and may return partial
 * patches `{ content, isError }`.
 *
 * LOADING (details + trust caveats in README.md): this file is placed in
 * `.pi/extensions/`, which pi AUTO-DISCOVERS once the project is trusted —
 * the upstream-recommended path (enables `/reload`). An explicit
 * `--extension` flag also works but BYPASSES pi's project-trust gate; see
 * the README security note before putting it in an alias.
 */

import { execFile } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

/** Which file extensions to validate. Empty array = validate every path. */
const VALIDATE_EXTENSIONS: string[] = [".py"];

/**
 * The validator command, argv form (no shell). `--` and the target file
 * are appended. Override per-run with the GUARDRAILS_VALIDATOR_CMD env var
 * (whitespace-split into argv — NO argument may contain spaces; use this
 * constant for anything more complex). Prefer an absolute path when your
 * sessions may start outside the repo root (e.g. worktree workers).
 *
 * Contract: exit 0 = pass; exit 1 = violation (readable report on stderr —
 * the model reads it verbatim); any other exit, spawn failure, timeout, or
 * oversized output = "validator error" (handled per FAIL_CLOSED below,
 * never reported to the model as a code violation).
 */
const VALIDATOR_CMD: string[] = [
  "python3",
  ".pi/extensions/validators/check-python-ast.py",
];

/**
 * Fail-closed: when the validator itself cannot run, block the pre-write
 * (and mark the post-result as an error) with the failure text. Set false
 * for warn-and-allow — which WARNS on the console, never silently.
 */
const FAIL_CLOSED = true;

/** Env overrides (tests + per-run tuning): GUARDRAILS_FAIL_CLOSED=false
 * flips to warn-and-allow; GUARDRAILS_TIMEOUT_MS overrides the cap. */
function failClosed(): boolean {
  const env = process.env.GUARDRAILS_FAIL_CLOSED;
  if (env === "false") return false;
  if (env === "true") return true;
  return FAIL_CLOSED;
}

/** Wall-clock cap and output cap for one validation run. */
const VALIDATOR_TIMEOUT_MS = 15_000;
const VALIDATOR_MAX_BUFFER = 10 * 1024 * 1024;

const GATED_TOOLS = new Set(["write", "edit"]);

function validatorArgv(): string[] {
  const env = process.env.GUARDRAILS_VALIDATOR_CMD;
  if (env && env.trim()) return env.trim().split(/\s+/);
  return [...VALIDATOR_CMD];
}

function shouldValidate(filePath: string): boolean {
  if (VALIDATE_EXTENSIONS.length === 0) return true;
  return VALIDATE_EXTENSIONS.includes(path.extname(filePath).toLowerCase());
}

type Verdict =
  | { kind: "pass" }
  | { kind: "violation"; report: string }
  | { kind: "validator-error"; detail: string };

/** Async (never blocks pi's event loop); `--` guards dash-leading paths. */
function runValidator(target: string): Promise<Verdict> {
  const argv = validatorArgv();
  return new Promise((resolve) => {
    execFile(
      argv[0],
      [...argv.slice(1), "--", target],
      {
        encoding: "utf8",
        timeout: (() => {
          const t = Number(process.env.GUARDRAILS_TIMEOUT_MS);
          return Number.isFinite(t) && t > 0 ? t : VALIDATOR_TIMEOUT_MS;
        })(),
        maxBuffer: VALIDATOR_MAX_BUFFER,
      },
      (error, stdout, stderr) => {
        if (!error) return resolve({ kind: "pass" });
        const code: unknown = (error as { code?: unknown }).code;
        if (code === 1) {
          const report = (stderr || stdout || "").trim() || "(no output)";
          return resolve({ kind: "violation", report });
        }
        // Spawn failure (ENOENT...), timeout, ENOBUFS, or a non-0/1 exit:
        // the VALIDATOR failed, which is never the model's fault.
        return resolve({
          kind: "validator-error",
          detail: String(code ?? error.message),
        });
      },
    );
  });
}

function validatorErrorText(detail: string): string {
  return (
    `[guardrails] validator could not run (${detail}) — ` +
    (failClosed()
      ? "failing closed. Fix the validator setup (see .pi/extensions/README.md) or set FAIL_CLOSED=false."
      : "warn-and-allow posture: proceeding WITHOUT validation.")
  );
}

export default async function (pi: any): Promise<void> {
  pi.on?.("session_start", async () => {
    // Visibility, not enforcement: the active validator is printed once so
    // an ambient GUARDRAILS_VALIDATOR_CMD can never act invisibly.
    console.log(
      `[guardrails] validating ${VALIDATE_EXTENSIONS.join(", ") || "ALL files"} ` +
        `via [${validatorArgv().join(" ")}] ` +
        `(${failClosed() ? "fail-closed" : "warn-and-allow"})`,
    );
  });

  // 1) PRE-WRITE: validate the incoming content before it reaches disk.
  pi.on?.("tool_call", async (event: any) => {
    if (event?.toolName !== "write") return undefined;
    const input: any = event?.input ?? {};
    const rawPath = String(input?.path ?? "");
    const content = input?.content;
    if (!rawPath || !shouldValidate(rawPath)) return undefined;
    if (typeof content !== "string") return undefined;

    // Same extension so extension-sensitive validators behave identically.
    const tmp = path.join(
      fs.mkdtempSync(path.join(os.tmpdir(), "guardrails-")),
      `incoming${path.extname(rawPath)}`,
    );
    try {
      fs.writeFileSync(tmp, content);
      const verdict = await runValidator(tmp);
      if (verdict.kind === "violation") {
        return {
          block: true,
          reason:
            `[guardrails] pre-write validation failed for '${rawPath}':\n` +
            `${verdict.report}\n` +
            "The file was NOT written. Correct the violations and retry.",
        };
      }
      if (verdict.kind === "validator-error") {
        const text = validatorErrorText(verdict.detail);
        if (failClosed()) return { block: true, reason: text };
        console.warn(text);
      }
      return undefined;
    } finally {
      fs.rmSync(path.dirname(tmp), { recursive: true, force: true });
    }
  });

  // 2) POST-EXECUTION: validate what is now on disk; patch the result on
  // failure so the model self-corrects. Repairs of broken files PASS here.
  pi.on?.("tool_result", async (event: any, ctx: any) => {
    if (!GATED_TOOLS.has(String(event?.toolName ?? ""))) return undefined;
    if (event?.isError) return undefined; // the tool already failed
    const rawPath = String(event?.input?.path ?? "");
    if (!rawPath || !shouldValidate(rawPath)) return undefined;
    // pi documents tool paths as relative-or-absolute, resolved against the
    // SESSION cwd (ctx.cwd) — a fail-closed guardrail must not silently
    // no-op on relative paths when the process cwd differs.
    const target = path.resolve(String(ctx?.cwd ?? process.cwd()), rawPath);
    if (!fs.existsSync(target)) {
      console.warn(
        `[guardrails] post-${event.toolName}: '${rawPath}' not found at ` +
          `'${target}' after a successful tool run — validation skipped.`,
      );
      return undefined;
    }

    const verdict = await runValidator(target);
    if (verdict.kind === "violation") {
      return {
        isError: true,
        content: [
          {
            type: "text",
            text:
              `[guardrails] post-${event.toolName} validation failed for ` +
              `'${rawPath}':\n${verdict.report}\n` +
              "The change IS on disk — fix the violations in a follow-up edit.",
          },
        ],
      };
    }
    if (verdict.kind === "validator-error") {
      const text = validatorErrorText(verdict.detail);
      if (failClosed()) {
        return { isError: true, content: [{ type: "text", text }] };
      }
      console.warn(text);
    }
    return undefined;
  });

  pi.registerCommand?.("guardrails:status", {
    description: "Show the guardrails validator configuration",
    handler: async (_args: unknown, ctx: any) => {
      const line =
        `guardrails: validating ${VALIDATE_EXTENSIONS.join(", ") || "ALL"} ` +
        `via [${validatorArgv().join(" ")}] ` +
        `(${failClosed() ? "fail-closed" : "warn-and-allow"})`;
      if (ctx?.ui?.notify) ctx.ui.notify(line);
      else console.log(line);
    },
  });
}
