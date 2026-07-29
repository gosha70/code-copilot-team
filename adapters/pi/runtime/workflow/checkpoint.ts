/**
 * Durable session checkpoint + compaction recovery (T9.1, FR-017).
 *
 * DEGRADED BY CONSTRUCTION. Pi emits no observable compaction event
 * (hooks/events.ts: PreCompact/PostCompact are `unsupported`), so a checkpoint
 * CANNOT be taken automatically at the moment of compaction. Instead:
 *   - a checkpoint is written at explicit CCT actions (`/cct:checkpoint`, and
 *     automatically on phase transitions), capturing the recovery-relevant
 *     session state to `.cct/pi-session.json`;
 *   - recovery runs at `session_start` — a resumed or post-compaction session
 *     loads the checkpoint and re-injects a digest + the compaction-preservation
 *     prompt into context, so the model re-learns where CCT left off.
 * This is best-effort durability, not a compaction hook; the capability
 * `memory.session-state` reports `degraded` for exactly this reason.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { Phase } from "./phases.ts";

export const SESSION_STATE_REL = path.join(".cct", "pi-session.json");
export const CHECKPOINT_VERSION = 1;

export interface SessionCheckpoint {
  version: number;
  savedAt: string; // ISO timestamp
  phase: Phase | null;
  featureId: string | null;
  checkpointCount: number; // increments each write — a restart/compaction proxy
  note: string;
}

/**
 * The CCT compaction-preservation prompt. Pi cannot inject this AT compaction
 * (no hook), so it is surfaced via the recovery digest / always-context as
 * standing guidance: whenever the session compacts, keep these facts.
 */
export const COMPACTION_PROMPT =
  "[CCT compaction guidance] If this session is compacted, PRESERVE: the active " +
  "feature id and workflow phase; any open peer-review round and its findings; " +
  "pending verification gates; and unresolved protected-path or permission " +
  "decisions. These are recoverable from .cct/ but keep them in the summary so " +
  "work continues without re-deriving state.";

export function loadCheckpoint(projectRoot: string): SessionCheckpoint | null {
  const file = path.join(projectRoot, SESSION_STATE_REL);
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    if (typeof parsed !== "object" || parsed === null) return null;
    const phase =
      typeof parsed.phase === "string" ? (parsed.phase as Phase) : null;
    return {
      version:
        typeof parsed.version === "number"
          ? parsed.version
          : CHECKPOINT_VERSION,
      savedAt: typeof parsed.savedAt === "string" ? parsed.savedAt : "",
      phase,
      featureId: typeof parsed.featureId === "string" ? parsed.featureId : null,
      checkpointCount:
        typeof parsed.checkpointCount === "number" ? parsed.checkpointCount : 0,
      note: typeof parsed.note === "string" ? parsed.note : "",
    };
  } catch {
    // Missing or corrupt → no checkpoint (recovery is a no-op, never a crash).
    return null;
  }
}

/**
 * Write a checkpoint, incrementing checkpointCount off any prior checkpoint.
 * `nowIso` is injected (callers pass an ISO string) so the write is testable
 * and deterministic.
 */
export function writeCheckpoint(
  projectRoot: string,
  fields: { phase: Phase | null; featureId: string | null; note?: string },
  nowIso: string,
): SessionCheckpoint {
  const prior = loadCheckpoint(projectRoot);
  const cp: SessionCheckpoint = {
    version: CHECKPOINT_VERSION,
    savedAt: nowIso,
    phase: fields.phase,
    featureId: fields.featureId,
    checkpointCount: (prior?.checkpointCount ?? 0) + 1,
    note: fields.note ?? "",
  };
  const file = path.join(projectRoot, SESSION_STATE_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(cp, null, 2) + "\n");
  return cp;
}

/** Human-readable recovery summary injected into a resumed session's context. */
export function recoveryDigest(cp: SessionCheckpoint): string {
  const feature = cp.featureId
    ? `feature '${cp.featureId}'`
    : "no active feature";
  const phase = cp.phase ? `phase '${cp.phase}'` : "no phase";
  const when = cp.savedAt || "unknown time";
  const head =
    `[CCT session recovery] Resuming ${feature} in ${phase} ` +
    `(checkpoint #${cp.checkpointCount}, saved ${when}). ` +
    "Run /cct:status to confirm state; /cct:checkpoint to save again.";
  return cp.note
    ? `${head}\nNote: ${cp.note}\n${COMPACTION_PROMPT}`
    : `${head}\n${COMPACTION_PROMPT}`;
}
