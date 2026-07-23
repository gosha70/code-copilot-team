/**
 * Always-on context loading (spec FR-003 / C-4, T2.3; authored).
 *
 * generate.sh emits `resources/context/always-context.md` — the ALWAYS_SKILLS
 * bodies (coding-standards, copilot-conventions, copyright-headers,
 * origin-confirmation, safety, wiki-first-query) concatenated. The runtime
 * loads it at session start and hands it to Pi as always-on context, so the
 * agent sees CCT's non-negotiable policy before executing any task.
 *
 * Size limits (C-4). The 32 KiB `AGENTS.md` cap is a Codex-adapter constraint
 * and does NOT apply to Pi: Pi injects context into the model's context
 * window, so the real bound is the window itself, not a fixed file cap.
 * There is therefore no hard limit to fail on. What matters is keeping the
 * always-on bundle from crowding out the task, so this module carries an
 * *advisory* soft limit and warns past it rather than truncating or failing.
 *
 * The soft limit is measured, not guessed: at the time of writing the bundle
 * is ~26 KiB, and the limit is set to 48 KiB — comfortably above today's
 * bundle while still flagging if it roughly doubles, which would be a signal
 * that ALWAYS_SKILLS has grown beyond what belongs in every single session.
 */

import * as fs from "node:fs";
import * as path from "node:path";

/** Advisory soft limit for the always-on bundle (see header). */
export const ALWAYS_CONTEXT_SOFT_LIMIT_BYTES = 48 * 1024;

export interface AlwaysContext {
  /** Bundle text, or null when no bundle is installed. */
  text: string | null;
  /** Absolute path the bundle was read from, or null. */
  source: string | null;
  /** Byte length of the bundle (0 when absent). */
  bytes: number;
  /** True when the bundle exceeds the advisory soft limit. */
  overSoftLimit: boolean;
  /** Human-readable warning when over the soft limit, else null. */
  warning: string | null;
}

const EMPTY: AlwaysContext = {
  text: null,
  source: null,
  bytes: 0,
  overSoftLimit: false,
  warning: null,
};

/**
 * Resolve and read the always-context bundle. Checks the managed install
 * first, then a repo checkout, mirroring how the launcher resolves the
 * runtime. Returns EMPTY (not an error) when no bundle is installed —
 * advisory context is not required for the runtime to function.
 */
export function loadAlwaysContext(candidateDirs: string[]): AlwaysContext {
  for (const dir of candidateDirs) {
    if (!dir) continue;
    const file = path.join(dir, "resources", "context", "always-context.md");
    if (!fs.existsSync(file)) continue;
    let text: string;
    try {
      text = fs.readFileSync(file, "utf8");
    } catch {
      continue;
    }
    const bytes = Buffer.byteLength(text, "utf8");
    const overSoftLimit = bytes > ALWAYS_CONTEXT_SOFT_LIMIT_BYTES;
    return {
      text,
      source: file,
      bytes,
      overSoftLimit,
      warning: overSoftLimit
        ? `always-on context bundle is ${(bytes / 1024).toFixed(1)} KiB, over the ` +
          `${(ALWAYS_CONTEXT_SOFT_LIMIT_BYTES / 1024).toFixed(0)} KiB advisory limit — ` +
          `it is injected into every session and may crowd out task context`
        : null,
    };
  }
  return EMPTY;
}
