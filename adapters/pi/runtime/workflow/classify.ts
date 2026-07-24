/**
 * SDD risk classifier (spec FR-006; authored).
 *
 * Maps the characteristics of a change to a spec_mode — full / lightweight /
 * none — using the same rules the Plan agent follows
 * (shared/skills/spec-workflow/SKILL.md):
 *
 *   full        security, schema, or integration work; or a feature touching
 *               more than 2 files
 *   lightweight a feature touching 1–2 files, non-critical
 *   none        a non-security bug fix, docs-only, or trivial change
 *
 * "When in doubt, escalate": a security-relevant change is `full` regardless
 * of its category, because under-speccing a risky change costs more than
 * over-speccing a safe one.
 *
 * The result is PERSISTED per feature and USER-CORRECTABLE: a manual override
 * is recorded with its reason and wins over auto-classification, so re-running
 * the classifier never silently discards a human decision (FR-006).
 */

import * as fs from "node:fs";
import * as path from "node:path";

import type { SpecMode } from "./sdd.ts";

export type RiskCategory =
  "security" | "schema" | "integration" | "feature" | "bug" | "docs";

export const RISK_CATEGORIES: RiskCategory[] = [
  "security",
  "schema",
  "integration",
  "feature",
  "bug",
  "docs",
];

export interface ClassifierInput {
  category: RiskCategory;
  /** Number of files the change touches (used to split feature full/light). */
  filesTouched?: number;
  /** Any security-relevant surface (auth, secrets, permissions, network). */
  securityRelevant?: boolean;
}

export interface Classification {
  mode: SpecMode;
  category: RiskCategory;
  justification: string;
  /** "auto" = classifier; "user" = manual override (authoritative). */
  source: "auto" | "user";
}

/** Categories that always require the full spec, irrespective of size. */
const ALWAYS_FULL: RiskCategory[] = ["security", "schema", "integration"];

/**
 * Classify a change. Pure — no I/O. Returns an `auto` classification; a caller
 * persists it and may later replace it with a `user` override.
 */
export function classifyRisk(input: ClassifierInput): Classification {
  const files = input.filesTouched ?? 0;

  // Escalation: a security-relevant change is full regardless of category.
  if (input.securityRelevant) {
    return {
      mode: "full",
      category: input.category,
      justification:
        "security-relevant change — escalated to full (under-speccing a risky change costs more)",
      source: "auto",
    };
  }

  if (ALWAYS_FULL.includes(input.category)) {
    return {
      mode: "full",
      category: input.category,
      justification: `${input.category} work requires the full spec`,
      source: "auto",
    };
  }

  if (input.category === "feature") {
    if (files > 2) {
      return {
        mode: "full",
        category: "feature",
        justification: `feature touching ${files} files (> 2) requires the full spec`,
        source: "auto",
      };
    }
    return {
      mode: "lightweight",
      category: "feature",
      justification: `feature touching ${files || "1–2"} file(s), non-critical`,
      source: "auto",
    };
  }

  // bug (non-security) and docs → none.
  return {
    mode: "none",
    category: input.category,
    justification:
      input.category === "docs"
        ? "docs-only change"
        : "non-security bug fix — no spec required",
    source: "auto",
  };
}

// ── Persistence ─────────────────────────────────────────────
// Stored alongside the phase state, keyed by feature id, so a project can
// hold classifications for several features.

const STATE_REL = path.join(".cct", "pi-classification.json");

type Store = { [featureId: string]: Classification };

function readStore(projectRoot: string): Store {
  try {
    const parsed = JSON.parse(
      fs.readFileSync(path.join(projectRoot, STATE_REL), "utf8"),
    );
    return parsed && typeof parsed === "object" ? (parsed as Store) : {};
  } catch {
    return {}; // missing or corrupt → empty (matches phase-state recovery)
  }
}

function writeStore(projectRoot: string, store: Store): void {
  const file = path.join(projectRoot, STATE_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(store, null, 2) + "\n");
}

/** The persisted classification for a feature, or null if none. */
export function loadClassification(
  projectRoot: string,
  featureId: string,
): Classification | null {
  const c = readStore(projectRoot)[featureId];
  if (
    !c ||
    (c.mode !== "full" && c.mode !== "lightweight" && c.mode !== "none")
  )
    return null;
  return c;
}

/**
 * Resolve the classification for a feature. A persisted USER override always
 * wins — re-running with fresh input must not discard a human decision. When
 * there is no user override, classify from `input` (if given) and persist it;
 * otherwise return whatever auto-classification was stored, or null.
 */
export function resolveClassification(
  projectRoot: string,
  featureId: string,
  input?: ClassifierInput,
): Classification | null {
  const existing = loadClassification(projectRoot, featureId);
  if (existing?.source === "user") return existing;
  if (input) {
    const c = classifyRisk(input);
    const store = readStore(projectRoot);
    store[featureId] = c;
    writeStore(projectRoot, store);
    return c;
  }
  return existing;
}

/**
 * Record a manual override. The user picks the mode and gives a reason; it is
 * persisted with source "user" and thereafter wins over auto-classification.
 */
export function overrideClassification(
  projectRoot: string,
  featureId: string,
  mode: SpecMode,
  reason: string,
): Classification {
  const c: Classification = {
    mode,
    category: loadClassification(projectRoot, featureId)?.category ?? "feature",
    justification: `user override: ${reason}`,
    source: "user",
  };
  const store = readStore(projectRoot);
  store[featureId] = c;
  writeStore(projectRoot, store);
  return c;
}
