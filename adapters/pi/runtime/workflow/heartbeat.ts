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
 * The file carries ONLY fields already present in the checkpoint, passed
 * through the same sanitization discipline — no free text beyond the
 * bounded ids, no env values, no secrets surface. A heartbeat write
 * failure must never break the checkpoint path (fail-safe by contract).
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { Phase } from "./phases.ts";

export const HEARTBEAT_REL = path.join(".cct", "heartbeat.json");
export const HEARTBEAT_VERSION = 1;

export interface Heartbeat {
  version: number;
  /**
   * Nullable by construction (spec FR-3): Pi exposes no native session id
   * at checkpoint time, so this is carried for the contract (and future
   * runtimes that know one) and is null today — honest, never fabricated.
   */
  sessionId: string | null;
  phase: Phase | null;
  featureId: string | null;
  checkpointCount: number;
  updatedAt: string; // ISO timestamp of the underlying CCT action
}

/**
 * Write the heartbeat. Throws on I/O failure — call sites that must never
 * fail their primary action use `tryWriteHeartbeat`.
 */
export function writeHeartbeat(
  projectRoot: string,
  fields: {
    sessionId?: string | null;
    phase: Phase | null;
    featureId: string | null;
    checkpointCount: number;
  },
  nowIso: string,
): Heartbeat {
  const hb: Heartbeat = {
    version: HEARTBEAT_VERSION,
    sessionId: fields.sessionId ?? null,
    phase: fields.phase,
    featureId: fields.featureId,
    checkpointCount: fields.checkpointCount,
    updatedAt: nowIso,
  };
  const file = path.join(projectRoot, HEARTBEAT_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(hb, null, 2) + "\n");
  return hb;
}

/** Best-effort variant: null on any failure, never throws into the caller. */
export function tryWriteHeartbeat(
  projectRoot: string,
  fields: {
    sessionId?: string | null;
    phase: Phase | null;
    featureId: string | null;
    checkpointCount: number;
  },
  nowIso: string,
): Heartbeat | null {
  try {
    return writeHeartbeat(projectRoot, fields, nowIso);
  } catch {
    return null;
  }
}
