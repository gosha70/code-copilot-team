/**
 * CCT enterprise guardrails — STARTER TEMPLATE (issue #179).
 *
 * A deterministic, programmatic PRE-WRITE gate for your project: every
 * `write`/`edit` the agent attempts is validated by a command YOU control
 * (AST checker, linter, policy script) BEFORE the file is touched. On
 * failure, the validator's stderr is returned as the block reason — the
 * model sees it immediately and self-corrects. This is enforcement, not
 * prompt discipline.
 *
 * VERIFIED SURFACES ONLY. This template uses exactly the Pi APIs the CCT
 * runtime itself is built on: `session_start`, the `tool_call` gate
 * (return `{ block: true, reason }` to stop a tool), and
 * `registerCommand`. Interception happens PRE-write because that is what
 * this Pi build supports (PostToolUse-style hooks are `unsupported` — see
 * the README's honesty table; pre-write blocking is also strictly
 * stronger: bad content never reaches disk).
 *
 * LOADING (see README.md): launch with an explicit extension flag —
 *   pi-code -- --extension .pi/extensions/cct-guardrails.ts
 * Auto-discovery of `.pi/extensions/` is NOT a verified behavior of this
 * Pi build; the explicit flag is exactly how the CCT runtime loads.
 *
 * CUSTOMIZE the three constants below. Keep your validator's contract:
 * exit 0 = pass; any other exit = block, with a human-readable report on
 * stderr (that text is what the model reads to fix its output).
 */

import { spawnSync } from "node:child_process";
import * as path from "node:path";

/** Which file extensions to validate. Empty array = validate every path. */
const VALIDATE_EXTENSIONS: string[] = [".py"];

/**
 * The validator command. Argv form (no shell). The file under validation
 * is appended as the last argument. Override per-run with the
 * CCT_VALIDATOR_CMD env var (whitespace-split into argv — use the
 * constant instead if your paths contain spaces).
 */
const VALIDATOR_CMD: string[] = [
  "python3",
  ".pi/extensions/validators/check-python-ast.py",
];

/**
 * Fail-closed: when the validator itself cannot run (missing interpreter,
 * crash, timeout), block the write with the failure text. Set to false to
 * warn-and-allow instead — weaker, but never bricks a session on a
 * misconfigured validator. The CCT posture is fail-closed.
 */
const FAIL_CLOSED = true;

/** Wall-clock cap for one validation run. */
const VALIDATOR_TIMEOUT_MS = 15_000;

const WRITE_TOOLS = new Set(["write", "edit"]);

function validatorArgv(): string[] {
  const env = process.env.CCT_VALIDATOR_CMD;
  if (env && env.trim()) return env.trim().split(/\s+/);
  return [...VALIDATOR_CMD];
}

function shouldValidate(filePath: string): boolean {
  if (VALIDATE_EXTENSIONS.length === 0) return true;
  return VALIDATE_EXTENSIONS.includes(path.extname(filePath).toLowerCase());
}

export default async function (pi: any): Promise<void> {
  pi.on?.("session_start", async (_event: unknown, _ctx: unknown) => {
    // A good place for one-time setup. Keep it fast and side-effect free —
    // this runs on every session start.
  });

  pi.on?.("tool_call", async (event: any, _ctx: unknown) => {
    // The same access patterns the CCT runtime uses (verified shapes).
    const toolName = String(event?.toolName ?? event?.name ?? "");
    if (!WRITE_TOOLS.has(toolName)) return undefined; // only gate writes
    const args: any = event?.input ?? event?.args ?? {};
    const rawPath = String(
      args?.path ?? args?.file_path ?? args?.filePath ?? "",
    );
    if (!rawPath || !shouldValidate(rawPath)) return undefined;

    const argv = validatorArgv();
    const proc = spawnSync(argv[0], [...argv.slice(1), rawPath], {
      encoding: "utf8",
      timeout: VALIDATOR_TIMEOUT_MS,
    });

    if (proc.error || proc.status === null) {
      // The validator itself failed to run (not a validation verdict).
      const detail = proc.error ? String(proc.error) : "validator timed out";
      if (FAIL_CLOSED) {
        return {
          block: true,
          reason:
            `[guardrails] validator could not run (${detail}) — ` +
            "failing closed. Fix the validator setup or set FAIL_CLOSED=false.",
        };
      }
      return undefined; // warn-and-allow posture
    }

    if (proc.status !== 0) {
      const report = (proc.stderr || proc.stdout || "").trim() || "(no output)";
      return {
        block: true,
        reason:
          `[guardrails] validation failed for '${rawPath}':\n${report}\n` +
          "Correct the violations above, then retry the write.",
      };
    }
    return undefined; // clean — the write proceeds
  });

  pi.registerCommand?.("guardrails:status", {
    description: "Show the guardrails validator configuration",
    handler: async (_args: unknown, ctx: any) => {
      const line =
        `guardrails: validating ${VALIDATE_EXTENSIONS.join(", ") || "ALL"} ` +
        `via [${validatorArgv().join(" ")}] ` +
        `(${FAIL_CLOSED ? "fail-closed" : "warn-and-allow"})`;
      if (ctx?.ui?.notify) ctx.ui.notify(line);
      else console.log(line);
    },
  });
}
