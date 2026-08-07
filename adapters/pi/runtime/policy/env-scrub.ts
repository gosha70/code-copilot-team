/**
 * Environment scrubbing policy (#173, spec pi-sandbox-hardening FR-1/FR-3) —
 * NAME-based credential scrubbing for the CCT-controlled spawn boundaries
 * (subagent child sessions, the `worktree run` worker handoff). Values are
 * never read, logged, or persisted; matching is on variable NAMES only.
 * `containsSecret` (workflow/memory.ts) remains the value-side guard for
 * persistence surfaces — a different concern, untouched.
 *
 * Trust asymmetry (FR-004a): BOTH in-repo layers — `project`
 * (.code-copilot-team/config.toml) AND `project-local` (config.local.toml) —
 * may only TIGHTEN the scrub policy. This deliberately diverges from
 * floor.ts's RELAXATION_LAYERS (which treats project-local as user-controlled):
 * config.local.toml is only gitignored by convention, so a hostile repo can
 * commit one — and a silently-honored credential-scrub opt-out is exactly the
 * exfiltration vector this module exists to close. Relaxation comes only from
 * genuinely user-controlled scopes: global config, `CCT_CONFIG__*` env, and
 * `pi-code --set` (cli). Precedence is ORDERED: a later trusted layer's
 * explicit boolean always wins (a repo's `env_scrub = true` cannot latch over
 * the user's later cli/env opt-out).
 *
 * Boundary notes, stated deliberately:
 *   - `CCT_*` is kept wholesale (the runtime's own contract vars) and keep
 *     beats pattern — never namespace a real credential under `CCT_`.
 *   - `KUBECONFIG` (and similar path-POINTER vars) are not scrubbed: they are
 *     file paths, not secrets; restricting file access is the protected-path
 *     / sandbox concern, not this one.
 *
 * Pattern syntax is deliberately tiny: an exact env NAME, `PREFIX_*`, or
 * `*_SUFFIX` (one `*`, at one end). Keep globs are narrower still — exact or
 * `PREFIX_*` only (keeps loosen; the surface stays small). No regex from
 * config — bounded matching, no ReDoS surface. Matching is case-insensitive
 * (a lower-cased `foo_token` must not slip past an upper-cased pattern).
 */

export interface ScrubPolicy {
  /** Name globs to remove: exact, `PREFIX_*`, or `*_SUFFIX`. */
  patterns: string[];
  /** Names that always survive; exact or `PREFIX_*` only. Keep beats pattern. */
  keep: string[];
}

export interface ScrubResult {
  env: NodeJS.ProcessEnv;
  /** Names removed by the policy, sorted. Names only — never values. */
  removed: string[];
}

/** Credential-shaped names removed by default (spec FR-1, review F5). */
export const DEFAULT_SCRUB_PATTERNS: readonly string[] = [
  "AWS_*",
  "GITHUB_TOKEN",
  "GH_TOKEN",
  "NPM_TOKEN",
  "PGPASSWORD",
  "SSH_AUTH_SOCK",
  "DOCKER_AUTH_CONFIG",
  "*_TOKEN",
  "*_SECRET",
  "*_KEY",
  "*_PAT",
  "*_PASSWORD",
  "*_PASSPHRASE",
  "*_CREDENTIAL",
  "*_CREDENTIALS",
];

/**
 * Names that always survive (spec FR-3, resolved decision 2): OS/session
 * baselines, the whole CCT_* contract, the LLM provider credentials a child
 * pi needs to run at all (incl. `ANTHROPIC_AUTH_TOKEN`, which the gateway /
 * local-LLM provider fragments emit — review F3), and the non-secret AWS
 * region/profile selectors a Bedrock-backed child needs. A custom
 * `providers.*.api_key_env` name must be added via `security.env_scrub_keep`
 * from a trusted scope.
 */
export const DEFAULT_SCRUB_KEEP: readonly string[] = [
  "PATH",
  "HOME",
  "PWD",
  "SHELL",
  "TERM",
  "USER",
  "LOGNAME",
  "LANG",
  "LC_*",
  "TMPDIR",
  "CCT_*",
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_AUTH_TOKEN",
  "OPENAI_API_KEY",
  "PI_API_KEY",
  "AWS_REGION",
  "AWS_DEFAULT_REGION",
  "AWS_PROFILE",
];

/** Exact env-var name, `PREFIX_*`, or `*_SUFFIX` — nothing else. */
const PATTERN_GLOB_RE = /^(?:[A-Za-z_][A-Za-z0-9_]*\*?|\*[A-Za-z0-9_]+)$/;
/** Keep globs are narrower: exact or `PREFIX_*` (no `*_SUFFIX`). */
const KEEP_GLOB_RE = /^[A-Za-z_][A-Za-z0-9_]*\*?$/;

/** Drop config-supplied pattern entries that are not the supported shape. */
export function sanitizeGlobs(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (g): g is string => typeof g === "string" && PATTERN_GLOB_RE.test(g),
  );
}

/** Keep entries: exact or `PREFIX_*` only (review F8 — keeps loosen). */
export function sanitizeKeepGlobs(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (g): g is string => typeof g === "string" && KEEP_GLOB_RE.test(g),
  );
}

function matchesGlob(name: string, glob: string): boolean {
  const n = name.toUpperCase();
  const g = glob.toUpperCase();
  if (g.endsWith("*")) return n.startsWith(g.slice(0, -1));
  if (g.startsWith("*")) return n.endsWith(g.slice(1));
  return n === g;
}

function matchesAny(name: string, globs: readonly string[]): boolean {
  return globs.some((g) => matchesGlob(name, g));
}

export function defaultScrubPolicy(): ScrubPolicy {
  return {
    patterns: [...DEFAULT_SCRUB_PATTERNS],
    keep: [...DEFAULT_SCRUB_KEEP],
  };
}

/**
 * Pure scrub: returns a NEW env with pattern-matched names removed (keep wins)
 * plus the sorted removed names. The input is never mutated; `undefined`
 * values are dropped (they are not part of a spawnable env either way).
 */
export function scrubEnv(
  env: NodeJS.ProcessEnv,
  policy: ScrubPolicy,
): ScrubResult {
  const out: NodeJS.ProcessEnv = {};
  const removed: string[] = [];
  for (const [name, value] of Object.entries(env)) {
    if (typeof value !== "string") continue;
    if (!matchesAny(name, policy.keep) && matchesAny(name, policy.patterns)) {
      removed.push(name);
      continue;
    }
    out[name] = value;
  }
  removed.sort();
  return { env: out, removed };
}

/**
 * Minimal structural view of the config loader's resolved entries — kept
 * structural so this policy module does not depend on the loader.
 */
export interface ResolvedEntryLike {
  value: unknown;
  layer: string;
  history: { layer: string; value: unknown }[];
}

export interface ResolvedScrubConfig {
  /** Effective on/off after the trust asymmetry is applied. */
  enabled: boolean;
  /** When disabled: the layer whose explicit false won (audit honesty). */
  disabledBy: string | null;
  policy: ScrubPolicy;
}

/** In-repo layers that may only tighten (review F1: BOTH project layers). */
const REPO_LAYERS = new Set(["project", "project-local"]);

/** Every (layer, value) that contributed to a key, oldest first. */
function contributions(
  entry: ResolvedEntryLike | undefined,
): { layer: string; value: unknown }[] {
  if (!entry) return [];
  return [...entry.history, { layer: entry.layer, value: entry.value }];
}

/** Latest contribution NOT from an in-repo layer. */
function lastTrusted(entry: ResolvedEntryLike | undefined): unknown {
  const c = contributions(entry).filter((e) => !REPO_LAYERS.has(e.layer));
  return c.length > 0 ? c[c.length - 1].value : undefined;
}

/**
 * Resolve the effective scrub config from loaded configuration, applying the
 * FR-004a trust asymmetry by provenance, in LAYER ORDER (review F2):
 *   - `security.env_scrub`: walk contributions oldest→newest; a trusted
 *     layer's explicit boolean applies as-is, an in-repo layer's applies only
 *     when it ENABLES scrubbing. A later trusted opt-out therefore always
 *     wins over an earlier repo enable.
 *   - `security.env_scrub_extra`: unioned across ALL layers (only tightens).
 *   - `security.env_scrub_keep`: the latest trusted value wins; in-repo
 *     keeps are ignored entirely (keeps loosen).
 * Absent config resolves to default-ON with the built-in policy.
 */
export function resolveScrubPolicy(
  resolved: Map<string, ResolvedEntryLike> | undefined,
): ResolvedScrubConfig {
  const scrub = resolved?.get("security.env_scrub");
  const extra = resolved?.get("security.env_scrub_extra");
  const keep = resolved?.get("security.env_scrub_keep");

  let enabled = true; // built-in default (spec FR-3, resolved decision 1)
  let disabledBy: string | null = null;
  for (const c of contributions(scrub)) {
    if (typeof c.value !== "boolean") continue;
    if (REPO_LAYERS.has(c.layer)) {
      if (c.value === true) {
        enabled = true; // tighten-only
        disabledBy = null;
      }
    } else {
      enabled = c.value;
      disabledBy = c.value === false ? c.layer : null;
    }
  }

  const extraPatterns = new Set<string>();
  for (const e of contributions(extra))
    for (const g of sanitizeGlobs(e.value)) extraPatterns.add(g);

  const keepExtra = sanitizeKeepGlobs(lastTrusted(keep));

  return {
    enabled,
    disabledBy: enabled ? null : disabledBy,
    policy: {
      patterns: [...DEFAULT_SCRUB_PATTERNS, ...extraPatterns],
      keep: [...DEFAULT_SCRUB_KEEP, ...keepExtra],
    },
  };
}
