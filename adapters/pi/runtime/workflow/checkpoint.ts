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
import { PHASE_ORDER } from "./phases.ts";
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

const MAX_FEATURE_ID = 128;
const MAX_TIMESTAMP = 40;

/**
 * Persisted strings become MODEL-VISIBLE input at recovery, so they get the
 * same discipline as any untrusted project-local surface: single line, no
 * control characters, bounded length. Prevents a tampered checkpoint from
 * smuggling directives (e.g. an embedded "SYSTEM: ...") into the recovery
 * digest.
 */
function sanitizeText(value: unknown, max: number): string {
  if (typeof value !== "string") return "";
  return value
    .replace(/[\r\n\t]+/g, " ")
    // eslint-disable-next-line no-control-regex
    .replace(/[\x00-\x1f\x7f]/g, "")
    .slice(0, max)
    .trim();
}

export function loadCheckpoint(projectRoot: string): SessionCheckpoint | null {
  const file = path.join(projectRoot, SESSION_STATE_REL);
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    if (typeof parsed !== "object" || parsed === null) return null;
    // Validate/sanitize every field: the file is untrusted (may be tampered).
    const phase = (PHASE_ORDER as string[]).includes(parsed.phase)
      ? (parsed.phase as Phase)
      : null;
    const featureId = sanitizeText(parsed.featureId, MAX_FEATURE_ID) || null;
    return {
      version:
        typeof parsed.version === "number"
          ? parsed.version
          : CHECKPOINT_VERSION,
      savedAt: sanitizeText(parsed.savedAt, MAX_TIMESTAMP),
      phase,
      featureId,
      checkpointCount:
        typeof parsed.checkpointCount === "number" &&
        Number.isFinite(parsed.checkpointCount)
          ? parsed.checkpointCount
          : 0,
      note: sanitizeText(parsed.note, MAX_FEATURE_ID),
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

/**
 * Best-effort checkpoint write for call sites where durability must NEVER break
 * the primary action (a phase transition, a command). Returns the checkpoint on
 * success, or null on any I/O failure — the caller warns/audits and continues.
 */
export function tryWriteCheckpoint(
  projectRoot: string,
  fields: { phase: Phase | null; featureId: string | null; note?: string },
  nowIso: string,
): SessionCheckpoint | null {
  try {
    return writeCheckpoint(projectRoot, fields, nowIso);
  } catch {
    return null;
  }
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
  // The persisted `note` is NOT injected — free-form disk text must not reach
  // model context. Only validated/sanitized fields + our own constant prompt.
  return `${head}\n${COMPACTION_PROMPT}`;
}
