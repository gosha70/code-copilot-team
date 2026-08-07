/**
 * Local heartbeat emission (Slice B1 of #174, issue #187, spec FR-3).
 *
 * A small, bounded, sanitized `.cct/heartbeat.json` maintained BEST-EFFORT
 * whenever a checkpoint is written, so an in-flight session is locally
 * observable (the analytics incremental/watch ingest polls it). Honest
 * semantics: a heartbeat proves "a CCT action happened at `updatedAt`" —
 * NOT that the session is alive now. Pi has no turn-end/Stop event and B1
 * does not invent one; emission follows the checkpoint cadence exactly
 * (`memory.session-state` stays degraded for the same reason).
 *
 * Sanitization happens ON WRITE (phase-2 review B-1): the inputs are
 * user/attacker-reachable (`/cct:phase <phase> <featureId>` args, the
 * untrusted `.cct/pi-workflow.json` state), so every field goes through
 * the checkpoint's own `sanitizeText` discipline, the phase is validated
 * against `PHASE_ORDER`, and numbers are clamped — the artifact is bounded
 * by construction, not by reader courtesy. The Phase-3 reader still
 * sanitizes on read (FR-4): both directions, per the spec. The write is
 * atomic (temp + rename) because `watch` polls this file while checkpoints
 * rewrite it.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { PHASE_ORDER } from "./phases.ts";
import type { Phase } from "./phases.ts";
import { MAX_FEATURE_ID, MAX_TIMESTAMP, sanitizeText } from "./checkpoint.ts";

export const HEARTBEAT_REL = path.join(".cct", "heartbeat.json");
export const HEARTBEAT_VERSION = 1;

const MAX_SESSION_ID = 128;
const MAX_CHECKPOINT_COUNT = 1_000_000_000;

export interface HeartbeatFields {
  /** Nullable by construction (spec FR-3): Pi exposes no native session id
   * at checkpoint time; carried for the contract, null today. */
  sessionId?: string | null;
  phase: Phase | null;
  featureId: string | null;
  checkpointCount: number;
}

export interface Heartbeat {
  version: number;
  sessionId: string | null;
  phase: Phase | null;
  featureId: string | null;
  checkpointCount: number;
  updatedAt: string; // ISO timestamp of the underlying CCT action
}

/** Clamp to a finite non-negative bounded integer (tamper-tolerant). */
function clampCount(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.min(Math.max(Math.trunc(value), 0), MAX_CHECKPOINT_COUNT);
}

/**
 * Write the heartbeat (sanitized + bounded on write). Throws on I/O
 * failure — call sites that must never fail their primary action use
 * `tryWriteHeartbeat`.
 */
export function writeHeartbeat(
  projectRoot: string,
  fields: HeartbeatFields,
  nowIso: string,
): Heartbeat {
  const hb: Heartbeat = {
    version: HEARTBEAT_VERSION,
    sessionId: sanitizeText(fields.sessionId, MAX_SESSION_ID) || null,
    phase: (PHASE_ORDER as readonly string[]).includes(fields.phase as string)
      ? fields.phase
      : null,
    featureId: sanitizeText(fields.featureId, MAX_FEATURE_ID) || null,
    checkpointCount: clampCount(fields.checkpointCount),
    updatedAt: sanitizeText(nowIso, MAX_TIMESTAMP),
  };
  const file = path.join(projectRoot, HEARTBEAT_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  // Atomic replace: `watch` polls this file while checkpoints rewrite it —
  // a torn read must not be constructible from our side (review B-4). The
  // temp name is pid-unique (two sessions in one root must not race on a
  // shared temp path) and never left behind on a rename failure (R-1).
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(hb, null, 2) + "\n");
  try {
    fs.renameSync(tmp, file);
  } finally {
    if (fs.existsSync(tmp)) fs.rmSync(tmp, { force: true });
  }
  return hb;
}

/** Best-effort variant: null on any failure, never throws into the caller. */
export function tryWriteHeartbeat(
  projectRoot: string,
  fields: HeartbeatFields,
  nowIso: string,
): Heartbeat | null {
  try {
    return writeHeartbeat(projectRoot, fields, nowIso);
  } catch {
    return null;
  }
}
