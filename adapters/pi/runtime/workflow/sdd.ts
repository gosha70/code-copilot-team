/**
 * SDD classification + gating (spec FR-006/FR-007; authored).
 *
 * Reads specs/<feature-id>/plan.md frontmatter (spec_mode, feature_id,
 * status, justification) and validates artifact completeness per mode —
 * parity with scripts/validate-spec.sh:
 *   full        → plan.md + spec.md + tasks.md, no unresolved markers
 *   lightweight → plan.md + spec.md, no unresolved markers
 *   none        → plan.md with non-empty justification; spec.md must NOT exist
 *
 * gateBuild() is the deterministic decision the Build phase consumes:
 * write/execution tools outside specs/ stay blocked until it passes.
 */

import * as fs from "node:fs";
import * as path from "node:path";

export type SpecMode = "full" | "lightweight" | "none";

export interface PlanFrontmatter {
  spec_mode: SpecMode | null;
  feature_id: string | null;
  status: string | null;
  justification: string | null;
  raw: { [k: string]: string };
}

export interface SddGate {
  pass: boolean;
  featureId: string | null;
  specMode: SpecMode | null;
  reasons: string[]; // empty when pass
}

const CLARIFICATION_MARKER = /\[NEEDS CLARIFICATION\]:|\[NEEDS CLARIFICATION:/;

export function parseFrontmatter(planContent: string): PlanFrontmatter {
  const result: PlanFrontmatter = {
    spec_mode: null,
    feature_id: null,
    status: null,
    justification: null,
    raw: {},
  };
  const lines = planContent.split(/\r?\n/);
  if (lines[0]?.trim() !== "---") return result;
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim() === "---") break;
    const m = line.match(/^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$/);
    if (!m) continue; // nested blocks (origin:) handled by validate-spec.sh
    const key = m[1];
    const value = m[2].replace(/^["']|["']$/g, "").trim();
    result.raw[key] = value;
  }
  const mode = result.raw["spec_mode"];
  if (mode === "full" || mode === "lightweight" || mode === "none") result.spec_mode = mode;
  result.feature_id = result.raw["feature_id"] ?? null;
  result.status = result.raw["status"] ?? null;
  result.justification = result.raw["justification"] ?? null;
  return result;
}

function fileHasMarker(file: string): boolean {
  try {
    return CLARIFICATION_MARKER.test(fs.readFileSync(file, "utf8"));
  } catch {
    return false;
  }
}

/** Validate one spec directory. Mirrors validate-spec.sh mode rules. */
export function validateSpecDir(specDir: string): SddGate {
  const reasons: string[] = [];
  const planFile = path.join(specDir, "plan.md");
  if (!fs.existsSync(planFile)) {
    return {
      pass: false,
      featureId: path.basename(specDir),
      specMode: null,
      reasons: [`plan.md not found in ${specDir}`],
    };
  }
  const fm = parseFrontmatter(fs.readFileSync(planFile, "utf8"));
  if (!fm.spec_mode) reasons.push("spec_mode missing or invalid in plan.md frontmatter");
  if (!fm.feature_id) reasons.push("feature_id missing from plan.md frontmatter");
  if (!fm.status) reasons.push("status missing from plan.md frontmatter");

  const specFile = path.join(specDir, "spec.md");
  const tasksFile = path.join(specDir, "tasks.md");

  if (fm.spec_mode === "full" || fm.spec_mode === "lightweight") {
    if (!fs.existsSync(specFile)) {
      reasons.push(`spec.md required for spec_mode=${fm.spec_mode} but not found`);
    } else if (fileHasMarker(specFile)) {
      reasons.push("spec.md has unresolved [NEEDS CLARIFICATION] markers");
    }
    if (fileHasMarker(planFile)) {
      reasons.push("plan.md has unresolved [NEEDS CLARIFICATION] markers");
    }
    if (fm.spec_mode === "full" && !fs.existsSync(tasksFile)) {
      reasons.push("tasks.md required for spec_mode=full but not found");
    }
  } else if (fm.spec_mode === "none") {
    if (!fm.justification) reasons.push("justification required for spec_mode=none");
    if (fs.existsSync(specFile)) reasons.push("spec.md must NOT exist for spec_mode=none");
  }

  return {
    pass: reasons.length === 0,
    featureId: fm.feature_id ?? path.basename(specDir),
    specMode: fm.spec_mode,
    reasons,
  };
}

/**
 * Build-phase gate for a feature (FR-007). Deterministic in all modes.
 * `featureId` may be null → gate fails with an actionable reason.
 */
export function gateBuild(projectRoot: string, featureId: string | null): SddGate {
  if (!featureId) {
    return {
      pass: false,
      featureId: null,
      specMode: null,
      reasons: [
        "no active feature: set one with /cct:phase build <feature-id> (plan.md under specs/<feature-id>/ required)",
      ],
    };
  }
  return validateSpecDir(path.join(projectRoot, "specs", featureId));
}

/** Paths a blocked Build session may still write (spec US-4): specs tree + CCT state. */
export function isSpecPath(relPath: string): boolean {
  const p = relPath.replace(/\\/g, "/");
  return p.startsWith("specs/") || p.startsWith(".cct/") || p.startsWith(".code-copilot-team/");
}
