/**
 * Configuration linting: obsolete and unrecognized keys (spec FR-004, T1.7).
 *
 * Migration (migrate.ts) rewrites keys it knows how to move. Linting reports
 * what migration deliberately will not touch:
 *
 *   - **obsolete** — a key that named a real setting which no longer exists.
 *     Silently ignoring it is the dangerous case: someone writes
 *     `security.allow_all = true`, sees no complaint, and believes it took
 *     effect. Reported as an error.
 *   - **legacy** — a key an available migration handles. Informational: the
 *     value is preserved, but the file should be updated at some point.
 *   - **unknown** — a key nothing reads. Usually a typo (`security.fail_close`
 *     for `fail_closed`). Reported as a warning, not an error, because
 *     forward-compatible files may carry keys a newer runtime will read.
 *
 * The severity split matters: an unknown key must not break a session, but a
 * key that looks like it disables a protection and does nothing must be loud.
 */

import type { TomlTable, TomlValue } from "./toml.ts";

export type FindingKind = "obsolete" | "legacy" | "unknown";

export interface LintFinding {
  kind: FindingKind;
  key: string;
  message: string;
}

/** Keys that once existed and no longer do. Value is the guidance to print. */
const OBSOLETE_KEYS: { [dotted: string]: string } = {
  "security.allow_all":
    "removed — it never disabled the security floor; use a profile or explicit permissions",
  "security.disable_gates":
    "removed — use `workflow.sdd.enabled = false` if SDD gating is not wanted",
  "permissions.bypass":
    "removed — bypassing permissions is not a supported configuration",
  "review.auto_approve":
    "removed — approvals are recorded per review, not configured globally",
  "session.trust_project":
    "removed — trust is resolved by Pi's project_trust lifecycle, never by config",
};

/** Keys a migration still understands; carried forward automatically. */
const LEGACY_KEYS: { [dotted: string]: string } = {
  "headless.deny_asks":
    "superseded by `headless.ask_resolution` (migrated automatically)",
  "security.ask_paths":
    "moved to `permissions.paths.ask` (migrated automatically)",
  "security.ask_commands":
    "moved to `permissions.commands.ask` (migrated automatically)",
};

/**
 * Exact leaf keys the runtime reads, for CLOSED sections. Listing leaves (not
 * just the section prefix) is what lets a typo like `security.fail_close` be
 * caught — a prefix match would wave it through under `security.`, and a
 * misspelled security key that silently does nothing is the worst case.
 */
const KNOWN_KEYS = new Set([
  "config_version",
  "headless.ask_resolution",
  "limits.timeout_sec",
  "limits.max_review_rounds",
  "review.mandatory",
  "review.after_phase",
  "review.allow_recursive",
  "security.fail_closed",
  "security.deny_network",
  "security.sandbox_required",
  "security.allow_package_install",
  "security.allow_secret_paths",
  "security.protected_paths",
  "security.denied_commands",
  "session.ephemeral",
  "verification.on_stop",
  "workflow.sdd.enabled",
  "workflow.sdd.mode",
  "tools.allow",
  "tools.deny",
  "permissions.paths.ask",
  "permissions.paths.deny",
  "permissions.commands.ask",
  // Per-phase policy leaves (T4.3), generated below so a typo in a phase name
  // or leaf is still caught rather than waved through under a `phases.` prefix.
  ...["research", "plan", "build", "review"].flatMap((phase) =>
    ["model", "thinking", "tools", "skills", "context", "permissions"].map(
      (leaf) => `phases.${phase}.${leaf}`,
    ),
  ),
]);

/**
 * OPEN sections whose leaf keys are user-defined, so any key beneath them is
 * recognized: profile names, provider names/fields. A typo here cannot be
 * distinguished from an intentional new name, so these are not linted for
 * unknown leaves.
 */
const OPEN_PREFIXES = ["profiles.", "providers."];

function isTable(v: TomlValue | undefined): v is TomlTable {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Flatten to dotted leaf paths (arrays are leaves, not tables). */
export function flattenKeys(table: TomlTable, prefix = ""): string[] {
  const out: string[] = [];
  for (const key of Object.keys(table)) {
    const dotted = prefix ? `${prefix}.${key}` : key;
    const value = table[key];
    if (isTable(value)) out.push(...flattenKeys(value, dotted));
    else out.push(dotted);
  }
  return out;
}

function isKnown(dotted: string): boolean {
  if (OPEN_PREFIXES.some((p) => dotted.startsWith(p))) return true;
  return KNOWN_KEYS.has(dotted);
}

/**
 * Lint a parsed configuration table. Operates on the file as written, so it
 * must run BEFORE migration — afterwards the legacy keys are already gone.
 */
export function lintConfig(table: TomlTable): LintFinding[] {
  const findings: LintFinding[] = [];
  for (const key of flattenKeys(table)) {
    if (OBSOLETE_KEYS[key] !== undefined) {
      findings.push({ kind: "obsolete", key, message: OBSOLETE_KEYS[key] });
      continue;
    }
    if (LEGACY_KEYS[key] !== undefined) {
      findings.push({ kind: "legacy", key, message: LEGACY_KEYS[key] });
      continue;
    }
    if (!isKnown(key)) {
      findings.push({
        kind: "unknown",
        key,
        message: "not read by this runtime — check for a typo",
      });
    }
  }
  return findings;
}

/** Findings that should fail a validation run. */
export function hasErrors(findings: LintFinding[]): boolean {
  return findings.some((f) => f.kind === "obsolete");
}
