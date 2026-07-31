/**
 * Neutral agent-manifest schema (T7.1, FR-011).
 *
 * A manifest is a named agent described by the SAME leaf set the phase policy
 * already uses (config/loader.ts `phases.<name>`): model / thinking / tools /
 * skills / context / permissions. A phase is a built-in agent with a fixed
 * name; a manifest is a user/imported agent with a chosen name.
 *
 * Per FR-011 as scoped for T7.1, every field here is RESOLVED AND REPORTED, not
 * enforced — the same boundary loader.ts already documents for phase policy.
 * Enforcement (applying model/thinking/permissions to a live child session)
 * lands with the Phase 7 child-session runner (T7.2), which itself is gated on
 * verifying Pi's SDK child-session surface. This module is pure data + pure
 * validation: no filesystem, no spawn, no config mutation.
 *
 * Defaults for fields a source cannot express are NEUTRAL SENTINELS ("inherit"
 * / empty), never fabricated intent, and are always recorded in
 * `declaredNotSourced`. See specs/pi-harness-adoption/design-t71-agent-manifest.md.
 */

/** Thinking effort. "inherit" = no override (the not-sourced sentinel). */
export type ThinkingLevel = "inherit" | "none" | "low" | "medium" | "high";

export const THINKING_LEVELS: readonly ThinkingLevel[] = [
  "inherit",
  "none",
  "low",
  "medium",
  "high",
];

/** Where a manifest came from — never fabricated, always recorded. */
export type AgentSource = "claude-import" | "authored" | "generated";

export const AGENT_SOURCES: readonly AgentSource[] = [
  "claude-import",
  "authored",
  "generated",
];

export interface AgentManifest {
  /** Invocation key: unique, kebab-case. */
  name: string;
  /** One-line human description. */
  description: string;
  /** "inherit" (no override) or a declared model tier/id carried verbatim. */
  model: string;
  thinking: ThinkingLevel;
  /** Pi tool names, lowercased. */
  tools: string[];
  /** CCT skill names; [] when the source did not express any. */
  skills: string[];
  /** Always-context selectors; [] when the source did not express any. */
  context: string[];
  /** Named posture ("inherit" | a profile/posture name). Reported, not enforced. */
  permissions: string;
  source: AgentSource;
  /** Fields set to a neutral default because the source lacked them. */
  declaredNotSourced: string[];
}

/** Neutral not-sourced defaults. Sentinels asserting no intent — always flagged. */
export const MANIFEST_SENTINELS = {
  model: "inherit",
  thinking: "inherit" as ThinkingLevel,
  permissions: "inherit",
} as const;

/** Fields a source may omit; each defaults to a sentinel and is flagged. */
export const OPTIONAL_FIELDS = [
  "model",
  "thinking",
  "skills",
  "context",
  "permissions",
] as const;

const NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const MAX_NAME = 64;

export interface ManifestValidation {
  valid: boolean;
  errors: string[];
}

/**
 * Validate one manifest. `existingNames`, when provided, enforces uniqueness of
 * `name` across a set (the importer passes the names seen so far).
 */
export function validateManifest(
  m: AgentManifest,
  existingNames?: Set<string>,
): ManifestValidation {
  const errors: string[] = [];

  if (!m.name || typeof m.name !== "string") {
    errors.push("name is required");
  } else {
    if (m.name.length > MAX_NAME)
      errors.push(`name exceeds ${MAX_NAME} characters`);
    if (!NAME_RE.test(m.name))
      errors.push(`name '${m.name}' is not kebab-case ([a-z0-9] with hyphens)`);
    if (existingNames?.has(m.name))
      errors.push(`duplicate agent name '${m.name}'`);
  }

  if (!m.description || typeof m.description !== "string")
    errors.push("description is required");

  if (!THINKING_LEVELS.includes(m.thinking))
    errors.push(
      `thinking '${m.thinking}' is not one of ${THINKING_LEVELS.join("/")}`,
    );

  for (const field of ["tools", "skills", "context"] as const) {
    const v = m[field];
    if (!isStringArray(v)) errors.push(`${field} must be an array of strings`);
  }

  if (!m.permissions || typeof m.permissions !== "string")
    errors.push("permissions posture is required (use 'inherit' for none)");

  if (!AGENT_SOURCES.includes(m.source))
    errors.push(
      `source '${m.source}' is not one of ${AGENT_SOURCES.join("/")}`,
    );

  if (!isStringArray(m.declaredNotSourced))
    errors.push("declaredNotSourced must be an array of strings");

  return { valid: errors.length === 0, errors };
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === "string");
}
