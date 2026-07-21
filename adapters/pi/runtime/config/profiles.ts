/**
 * Built-in CCT profiles (spec §8.4 / FR-004; authored).
 *
 * A profile is a partial configuration applied between built-in defaults
 * and the global configuration file. Profiles may inherit; circular
 * inheritance is rejected (spec: "circular inheritance must be rejected").
 */

import type { TomlTable } from "./toml.ts";

export interface Profile {
  name: string;
  description: string;
  inherits?: string;
  config: TomlTable;
}

export const BUILTIN_PROFILES: { [name: string]: Profile } = {
  minimal: {
    name: "minimal",
    description: "Skills, prompts, discovery, and limited enforcement",
    config: {
      workflow: { sdd: { enabled: false } },
      security: { fail_closed: false },
      review: { mandatory: false },
    },
  },
  disciplined: {
    name: "disciplined",
    description: "Default SDD, safety hooks, review, and verification",
    config: {
      workflow: { sdd: { enabled: true, mode: "enforced" } },
      security: { fail_closed: true },
      review: { mandatory: false, after_phase: true },
      verification: { on_stop: true },
    },
  },
  "review-heavy": {
    name: "review-heavy",
    description: "Mandatory peer review and stronger quality gates",
    inherits: "disciplined",
    config: {
      review: { mandatory: true, before_commit: true },
    },
  },
  autonomous: {
    name: "autonomous",
    description: "Autonomous build loop with required isolation",
    inherits: "disciplined",
    config: {
      security: { sandbox_required: true },
      autonomy: {
        enabled: true,
        max_concurrency: 4,
        max_recursion: 2,
        reject_unrestricted_host: true,
      },
    },
  },
  "local-first": {
    name: "local-first",
    description: "Prefer Ollama, vLLM, LM Studio, or local providers",
    inherits: "disciplined",
    config: {
      providers: { prefer: ["ollama", "vllm", "lmstudio"] },
    },
  },
  "air-gapped": {
    name: "air-gapped",
    description: "No network integrations; local models and tools only",
    inherits: "local-first",
    config: {
      security: { deny_network: true },
      providers: { require_local: true },
    },
  },
  ci: {
    name: "ci",
    description: "Deterministic non-interactive execution and exit codes",
    inherits: "disciplined",
    config: {
      headless: { ask_resolution: "fail" },
      security: { sandbox_required: true },
      ui: { interactive: false },
    },
  },
  "peer-reviewer": {
    name: "peer-reviewer",
    description:
      "Non-recursive read-only reviewer (FR-015a): no SDD, no teams, no subagents, no writes, ephemeral session",
    config: {
      workflow: { sdd: { enabled: false } },
      review: { mandatory: false, allow_recursive: false },
      agents: { teams_enabled: false, subagents_enabled: false },
      tools: { allow: ["read", "grep", "find", "ls"] },
      security: { fail_closed: true, allow_package_install: false },
      session: { ephemeral: true },
      headless: { ask_resolution: "deny" },
      limits: { timeout_sec: 300, max_tokens: 200000 },
    },
  },
};

export class ProfileError extends Error {}

/**
 * Resolve a profile into its flattened config chain (base-most first).
 * Rejects unknown names and circular inheritance.
 */
export function resolveProfileChain(
  name: string,
  registry: { [name: string]: Profile } = BUILTIN_PROFILES,
): Profile[] {
  const chain: Profile[] = [];
  const seen = new Set<string>();
  let cursor: string | undefined = name;
  while (cursor !== undefined) {
    if (seen.has(cursor)) {
      throw new ProfileError(
        `circular profile inheritance detected: ${[...seen, cursor].join(" -> ")}`,
      );
    }
    const profile = registry[cursor];
    if (!profile) {
      throw new ProfileError(
        `unknown profile '${cursor}' (available: ${Object.keys(registry).sort().join(", ")})`,
      );
    }
    seen.add(cursor);
    chain.unshift(profile);
    cursor = profile.inherits;
  }
  return chain;
}
