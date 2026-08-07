/**
 * Environment scrubbing policy (#173, spec pi-sandbox-hardening FR-1/FR-3) —
 * NAME-based credential scrubbing for the CCT-controlled spawn boundaries
 * (subagent child sessions, the `worktree run` worker handoff). Values are
 * never read, logged, or persisted; matching is on variable NAMES only.
 * `containsSecret` (workflow/memory.ts) remains the value-side guard for
 * persistence surfaces — a different concern, untouched.
 *
 * Trust asymmetry (FR-004a): the checked-in project layer may only TIGHTEN
 * the policy. `resolveScrubPolicy` enforces this by provenance — a project-
 * layer value is honored for `security.env_scrub` only when it enables
 * scrubbing, `env_scrub_extra` contributions union across all layers (extra
 * patterns only ever tighten), and `env_scrub_keep` from the project layer is
 * ignored outright (keeps loosen). The floor engine (config/floor.ts) is NOT
 * used here: its RELAXATION_LAYERS excludes the global layer, which would
 * make a default-ON scrub impossible to disable from the user's own global
 * config — the approved contract allows exactly that.
 *
 * Pattern syntax is deliberately tiny: an exact env NAME, `PREFIX_*`, or
 * `*_SUFFIX` (one `*`, at one end). No regex from config — bounded matching,
 * no ReDoS surface. Matching is case-insensitive (a lower-cased `foo_token`
 * must not slip past a conventionally upper-cased pattern).
 */

export interface ScrubPolicy {
  /** Name globs to remove: exact, `PREFIX_*`, or `*_SUFFIX`. */
  patterns: string[];
  /** Names that always survive; exact or `PREFIX_*`. Keep beats pattern. */
  keep: string[];
}

export interface ScrubResult {
  env: Record<string, string>;
  /** Names removed by the policy, sorted. Names only — never values. */
  removed: string[];
}

/** Credential-shaped names removed by default (spec FR-1). */
export const DEFAULT_SCRUB_PATTERNS: readonly string[] = [
  "AWS_*",
  "GITHUB_TOKEN",
  "GH_TOKEN",
  "NPM_TOKEN",
  "*_TOKEN",
  "*_SECRET",
  "*_KEY",
  "*_PASSWORD",
  "*_PASSPHRASE",
  "*_CREDENTIAL",
  "*_CREDENTIALS",
];

/**
 * Names that always survive (spec FR-3, resolved decision 2): OS/session
 * baselines, the whole CCT_* contract, and the LLM provider credentials a
 * child pi needs to run at all — default-ON scrubbing must not brick child
 * sessions.
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
  "OPENAI_API_KEY",
  "PI_API_KEY",
];

/** Exact env-var name, `PREFIX_*`, or `*_SUFFIX` — nothing else. */
const GLOB_RE = /^(?:[A-Za-z_][A-Za-z0-9_]*\*?|\*[A-Za-z0-9_]+)$/;

/** Drop config-supplied entries that are not the tiny supported glob shape. */
export function sanitizeGlobs(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (g): g is string => typeof g === "string" && GLOB_RE.test(g),
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
  env: Record<string, string | undefined>,
  policy: ScrubPolicy,
): ScrubResult {
  const out: Record<string, string> = {};
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
  policy: ScrubPolicy;
}

/** The checked-in trusted-project layer — the one that may only tighten. */
const PROJECT_LAYER = "project";

/** Every (layer, value) that contributed to a key, oldest first. */
function contributions(
  entry: ResolvedEntryLike | undefined,
): { layer: string; value: unknown }[] {
  if (!entry) return [];
  return [...entry.history, { layer: entry.layer, value: entry.value }];
}

/** Latest contribution NOT from the checked-in project layer. */
function lastNonProject(entry: ResolvedEntryLike | undefined): unknown {
  const c = contributions(entry).filter((e) => e.layer !== PROJECT_LAYER);
  return c.length > 0 ? c[c.length - 1].value : undefined;
}

/**
 * Resolve the effective scrub config from loaded configuration, applying the
 * FR-004a trust asymmetry by provenance:
 *   - `security.env_scrub`: the project layer is honored only when it ENABLES
 *     scrubbing (tighten); otherwise the latest non-project value wins.
 *   - `security.env_scrub_extra`: unioned across ALL layers (only tightens).
 *   - `security.env_scrub_keep`: the latest non-project value wins; project-
 *     layer keeps are ignored (keeps loosen).
 * Absent config resolves to default-ON with the built-in policy.
 */
export function resolveScrubPolicy(
  resolved: Map<string, ResolvedEntryLike> | undefined,
): ResolvedScrubConfig {
  const scrub = resolved?.get("security.env_scrub");
  const extra = resolved?.get("security.env_scrub_extra");
  const keep = resolved?.get("security.env_scrub_keep");

  const nonProject = lastNonProject(scrub);
  const projectEnables = contributions(scrub).some(
    (e) => e.layer === PROJECT_LAYER && e.value === true,
  );
  const enabled =
    projectEnables || (typeof nonProject === "boolean" ? nonProject : true);

  const extraPatterns = new Set<string>();
  for (const e of contributions(extra))
    for (const g of sanitizeGlobs(e.value)) extraPatterns.add(g);

  const keepExtra = sanitizeGlobs(lastNonProject(keep));

  return {
    enabled,
    policy: {
      patterns: [...DEFAULT_SCRUB_PATTERNS, ...extraPatterns],
      keep: [...DEFAULT_SCRUB_KEEP, ...keepExtra],
    },
  };
}
