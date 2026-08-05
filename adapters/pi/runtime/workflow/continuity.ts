/**
 * Durable continuity report (US3 of unattended-cross-harness-execution, FR-9..
 * FR-13). Composes the project's EXISTING durable state — the SDD `tasks.md`,
 * the Pi session checkpoint (`.cct/pi-session.json`), and the auto-build ledger
 * (`.cct/auto-build/<featureId>/state.json`) — into one honest status a resumed
 * or supervised session can re-read.
 *
 * Honesty discipline (do not soften):
 *   - Each source is reported present / missing / corrupt from what is actually
 *     on disk — never fabricated (FR-13).
 *   - The checkpoint is read through the existing `loadCheckpoint`, which
 *     sanitizes every field (untrusted disk text never reaches a digest); this
 *     report surfaces only those sanitized structured fields, never free text
 *     (FR-11/FR-12).
 *   - Pi native compaction stays DEGRADED: no `PreCompact`/`PostCompact` hook
 *     exists, so `compaction.native` is false and the mechanism is stated as
 *     checkpoint-at-explicit-actions + `session_start` recovery (FR-10). This
 *     module never claims a native compaction hook.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { loadCheckpoint, SESSION_STATE_REL } from "./checkpoint.ts";

export type SourceStatus = "present" | "missing" | "corrupt";

export interface ContinuitySource {
  name: "tasks" | "checkpoint" | "auto-build-ledger";
  /** Repo-relative path that was probed (explicit per FR-13). */
  path: string;
  status: SourceStatus;
  /** Human summary — derived only from validated fields, never raw disk text. */
  detail: string;
}

export interface ContinuityReport {
  featureId: string | null;
  sources: ContinuitySource[];
  compaction: {
    /** Pi exposes no PreCompact/PostCompact hook — always false here (FR-10). */
    native: boolean;
    mechanism: string;
  };
}

const COMPACTION_MECHANISM =
  "degraded: Pi exposes no PreCompact/PostCompact hook; state is checkpointed at " +
  "explicit CCT actions (phase transitions, /cct:checkpoint) and recovered at " +
  "session_start — durable, not a native compaction hook";

/**
 * A feature id is a slug and is used to build filesystem paths under `specs/`
 * and `.cct/auto-build/`. The checkpoint is UNTRUSTED disk state, so an id that
 * is not a single safe path segment (contains a slash/backslash, or is `.`/`..`)
 * is rejected for path use — a tampered checkpoint must not probe outside the
 * project (path traversal). Rejected ⇒ treated as "no active feature id".
 */
const SAFE_FEATURE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
function safeFeatureId(id: string | null | undefined): string | null {
  if (!id || id === "." || id === "..") return null;
  if (id.includes("/") || id.includes("\\")) return null;
  return SAFE_FEATURE_ID.test(id) ? id : null;
}

/**
 * Defense in depth: resolve `segments` under `root` and return the absolute
 * path ONLY if it stays within `root`; otherwise null (never read it). Catches
 * any residual traversal even if a segment slipped past validation.
 */
function resolveWithin(root: string, ...segments: string[]): string | null {
  const rootAbs = path.resolve(root);
  const abs = path.resolve(root, ...segments);
  if (abs !== rootAbs && !abs.startsWith(rootAbs + path.sep)) return null;
  return abs;
}

/**
 * Count SDD task checkboxes in BOTH layouts this repo uses: bullet lists
 * (`- [ ]` / `* [x]`) and markdown table cells (`| [ ] |`). One checkbox per
 * line; header/separator rows have none. Avoids matching stray `[ ]` in prose.
 */
function countTaskCheckboxes(text: string): { total: number; done: number } {
  let total = 0;
  let done = 0;
  for (const line of text.split("\n")) {
    const m =
      line.match(/^\s*[-*]\s+\[([ xX])\]/) ??
      line.match(/\|\s*\[([ xX])\]\s*\|/);
    if (!m) continue;
    total += 1;
    if (m[1] === "x" || m[1] === "X") done += 1;
  }
  return { total, done };
}

function readTasks(
  projectRoot: string,
  featureId: string | null,
): ContinuitySource {
  const candidates = [
    featureId ? path.join("specs", featureId, "tasks.md") : "",
    "specs/tasks.md",
    "tasks.md",
  ].filter(Boolean);

  for (const rel of candidates) {
    const abs = resolveWithin(projectRoot, rel);
    if (!abs || !fs.existsSync(abs)) continue;
    try {
      const text = fs.readFileSync(abs, "utf8");
      const { total, done } = countTaskCheckboxes(text);
      const remaining = total - done;
      return {
        name: "tasks",
        path: rel,
        status: "present",
        detail:
          total === 0
            ? "no task checkboxes found"
            : `${done}/${total} tasks done, ${remaining} remaining`,
      };
    } catch {
      return {
        name: "tasks",
        path: rel,
        status: "corrupt",
        detail: "unreadable tasks.md",
      };
    }
  }
  return {
    name: "tasks",
    path: candidates[0],
    status: "missing",
    detail: "no SDD tasks.md found",
  };
}

/** Distinguish missing vs corrupt vs present (loadCheckpoint collapses the first two). */
function readCheckpoint(projectRoot: string): {
  source: ContinuitySource;
  featureId: string | null;
} {
  const abs = path.join(projectRoot, SESSION_STATE_REL);
  if (!fs.existsSync(abs)) {
    return {
      source: {
        name: "checkpoint",
        path: SESSION_STATE_REL,
        status: "missing",
        detail: "no checkpoint yet",
      },
      featureId: null,
    };
  }
  const cp = loadCheckpoint(projectRoot); // sanitizes every field; null on corrupt
  if (cp === null) {
    return {
      source: {
        name: "checkpoint",
        path: SESSION_STATE_REL,
        status: "corrupt",
        detail: "checkpoint present but unparseable/invalid",
      },
      featureId: null,
    };
  }
  const feat = cp.featureId ?? "<none>";
  const phase = cp.phase ?? "<none>";
  return {
    source: {
      name: "checkpoint",
      path: SESSION_STATE_REL,
      status: "present",
      detail: `feature '${feat}', phase '${phase}', checkpoint #${cp.checkpointCount}${cp.savedAt ? `, saved ${cp.savedAt}` : ""}`,
    },
    featureId: cp.featureId,
  };
}

/** Auto-build ledger status for the active feature (FR-9). */
function readLedger(
  projectRoot: string,
  featureId: string | null,
): ContinuitySource {
  if (!featureId) {
    return {
      name: "auto-build-ledger",
      path: ".cct/auto-build/<feature-id>/state.json",
      status: "missing",
      detail: "no active feature id (from checkpoint) to locate a ledger",
    };
  }
  const rel = path.join(".cct", "auto-build", featureId, "state.json");
  const abs = resolveWithin(projectRoot, rel);
  if (!abs || !fs.existsSync(abs)) {
    return {
      name: "auto-build-ledger",
      path: rel,
      status: "missing",
      detail: "no auto-build run recorded",
    };
  }
  try {
    const parsed = JSON.parse(fs.readFileSync(abs, "utf8"));
    if (typeof parsed !== "object" || parsed === null) {
      return {
        name: "auto-build-ledger",
        path: rel,
        status: "corrupt",
        detail: "ledger is not a JSON object",
      };
    }
    const status =
      typeof parsed.status === "string" ? parsed.status : "<unknown>";
    const phase =
      typeof parsed.current_phase === "number"
        ? parsed.current_phase
        : "<unknown>";
    const updated =
      typeof parsed.updated === "string" ? parsed.updated : "<unknown>";
    return {
      name: "auto-build-ledger",
      path: rel,
      status: "present",
      detail: `status '${status}', phase ${phase}, updated ${updated}`,
    };
  } catch {
    return {
      name: "auto-build-ledger",
      path: rel,
      status: "corrupt",
      detail: "ledger present but unparseable JSON",
    };
  }
}

/**
 * Build the continuity report. `featureId` may be passed explicitly; otherwise
 * it is derived from the checkpoint (the honest link between the checkpoint and
 * the auto-build ledger).
 */
export function continuityReport(
  projectRoot: string,
  featureId?: string | null,
): ContinuityReport {
  const cp = readCheckpoint(projectRoot);
  // The feature id builds file paths; a tampered checkpoint must not escape the
  // project root, so reject anything that is not a safe path segment (P1).
  const activeFeature = safeFeatureId(featureId ?? cp.featureId);
  return {
    featureId: activeFeature,
    sources: [
      readTasks(projectRoot, activeFeature),
      cp.source,
      readLedger(projectRoot, activeFeature),
    ],
    compaction: { native: false, mechanism: COMPACTION_MECHANISM },
  };
}
