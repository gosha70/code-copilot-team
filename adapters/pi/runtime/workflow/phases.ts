/**
 * Phase state machine: Research → Plan → Build → Review (spec FR-008).
 *
 * State persists in .cct/pi-workflow.json (same project-state directory
 * the peer-review loop already uses) so workflow position survives
 * session restarts and compaction (FR-008 "persist workflow state").
 *
 * Entry gates (Phase 4 scope):
 *   build  → SDD gate must pass for the active feature (FR-007)
 *   review → build must have been entered
 * Full per-phase model/tool/skill routing lands with cct-agents (Phase 7);
 * here we expose the state machine + per-phase policy from config.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { gateBuild } from "./sdd.ts";
import type { SddGate } from "./sdd.ts";

export type Phase = "research" | "plan" | "build" | "review";

export const PHASE_ORDER: Phase[] = ["research", "plan", "build", "review"];

export interface WorkflowState {
  phase: Phase;
  featureId: string | null;
  enteredAt: string | null; // ISO timestamp (informational)
  history: { phase: Phase; featureId: string | null; at: string }[];
}

export interface TransitionResult {
  ok: boolean;
  state: WorkflowState;
  gate: SddGate | null;
  reasons: string[];
}

const STATE_REL = path.join(".cct", "pi-workflow.json");

export function defaultState(): WorkflowState {
  return { phase: "research", featureId: null, enteredAt: null, history: [] };
}

export function loadState(projectRoot: string): WorkflowState {
  const file = path.join(projectRoot, STATE_REL);
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    if (PHASE_ORDER.includes(parsed.phase)) {
      return {
        phase: parsed.phase,
        featureId: typeof parsed.featureId === "string" ? parsed.featureId : null,
        enteredAt: typeof parsed.enteredAt === "string" ? parsed.enteredAt : null,
        history: Array.isArray(parsed.history) ? parsed.history : [],
      };
    }
  } catch {
    /* missing or corrupt → fresh state (corrupt-state property test) */
  }
  return defaultState();
}

export function saveState(projectRoot: string, state: WorkflowState): void {
  const file = path.join(projectRoot, STATE_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(state, null, 2) + "\n");
}

export function isValidPhase(value: string): value is Phase {
  return (PHASE_ORDER as string[]).includes(value);
}

/**
 * Attempt a transition. Free movement between research/plan; build gates
 * on SDD artifacts; review requires having been in build for the feature.
 */
export function transition(
  projectRoot: string,
  state: WorkflowState,
  target: Phase,
  featureId: string | null,
  now: string,
): TransitionResult {
  const effectiveFeature = featureId ?? state.featureId;
  const reasons: string[] = [];
  let gate: SddGate | null = null;

  if (target === "build") {
    gate = gateBuild(projectRoot, effectiveFeature ?? null);
    if (!gate.pass) {
      return { ok: false, state, gate, reasons: gate.reasons };
    }
  }

  if (target === "review") {
    const beenInBuild =
      state.phase === "build" ||
      state.history.some((h) => h.phase === "build" && h.featureId === effectiveFeature);
    if (!beenInBuild) {
      reasons.push(
        `review requires a prior build phase for feature '${effectiveFeature ?? "<none>"}'`,
      );
      return { ok: false, state, gate: null, reasons };
    }
  }

  const next: WorkflowState = {
    phase: target,
    featureId: effectiveFeature ?? null,
    enteredAt: now,
    history: [
      ...state.history,
      { phase: state.phase, featureId: state.featureId, at: state.enteredAt ?? now },
    ].slice(-50),
  };
  saveState(projectRoot, next);
  return { ok: true, state: next, gate, reasons: [] };
}

/**
 * Should a write/execute tool call be blocked in the current phase?
 * Phase 4 contract (FR-007): in build, SDD gate must hold; outside build,
 * research/plan phases are read-oriented but writes to specs/ are the
 * planning deliverable, so only build enforces the artifact gate.
 */
export function buildWriteGate(
  projectRoot: string,
  state: WorkflowState,
  sddEnabled: boolean,
): SddGate | null {
  if (!sddEnabled) return null;
  if (state.phase !== "build") return null;
  const gate = gateBuild(projectRoot, state.featureId);
  return gate.pass ? null : gate;
}
