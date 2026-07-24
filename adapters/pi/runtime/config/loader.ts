/**
 * Layered CCT configuration loader with provenance (spec FR-004/FR-004a).
 *
 * Ordinary precedence (lowest → highest):
 *   defaults < profile chain < global < trusted project
 *   < trusted project-local < env < cli < session
 *
 * Protected security settings route through the monotonic floor engine
 * (floor.ts): trusted project layers may only strengthen; relaxation is
 * accepted only from user-controlled layers and always recorded.
 *
 * Trust contract: project layers are read ONLY when `trusted === true`
 * (in-process Pi trust resolution — FR-004a). Unknown/deferred trust is
 * untrusted. Ignored files are reported, never silently dropped.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { parseToml, TomlError } from "./toml.ts";
import type { TomlTable, TomlValue } from "./toml.ts";
import { BUILTIN_PROFILES, resolveProfileChain } from "./profiles.ts";
import type { Profile } from "./profiles.ts";
import { applyFloorValue, isFloorPath } from "./floor.ts";
import { CONFIG_SCHEMA_VERSION, CONFIG_VERSION_KEY, migrateTable } from "./migrate.ts";
import type { MigrationNote } from "./migrate.ts";
import type { FloorDecision } from "./floor.ts";

export interface ProvenanceEntry {
  layer: string;
  source: string;
  value: TomlValue;
}

export interface ResolvedKey {
  path: string;
  value: TomlValue;
  layer: string;
  source: string;
  history: ProvenanceEntry[]; // overridden priors, oldest first
  sensitive: boolean;
  floor: boolean;
}

export interface LoadResult {
  config: TomlTable;
  resolved: Map<string, ResolvedKey>;
  profileChain: string[];
  loadedFiles: string[];
  ignoredFiles: { file: string; reason: string }[];
  floorDecisions: FloorDecision[];
  warnings: string[];
  errors: string[];
  /** Schema version this runtime resolved the configuration at. */
  configVersion: number;
  /** Migrations applied while reading files, per file. */
  migrations: { file: string; notes: MigrationNote[] }[];
}

export interface LoadOptions {
  globalDir: string; // ~/.code-copilot-team
  projectDir: string; // project root
  trusted: boolean; // in-process Pi trust resolution result
  profile: string;
  profiles?: { [name: string]: Profile };
  env?: { [k: string]: string | undefined };
  cliSets?: string[]; // ["a.b=v", ...] from pi-code --set
  noProjectConfig?: boolean; // pi-code --no-project-config / --global
}

const SENSITIVE_KEY = /(token|secret|password|api[_-]?key|credential|private[_-]?key)/i;

export const BUILTIN_DEFAULTS: TomlTable = {
  workflow: { sdd: { enabled: true, mode: "enforced" } },
  security: {
    fail_closed: true,
    deny_network: false,
    sandbox_required: false,
    allow_package_install: true,
    allow_secret_paths: false,
    protected_paths: [".env", ".git/config", "**/*.pem", "**/id_rsa*"],
    denied_commands: ["git push --force", "git reset --hard", "rm -rf /"],
  },
  review: { mandatory: false, after_phase: true, allow_recursive: false },
  headless: { ask_resolution: "deny" },
  limits: { timeout_sec: 900, max_review_rounds: 5 },
  session: { ephemeral: false },
  // Per-phase policy (FR-008, T4.3). RESOLVED AND REPORTED, not enforced:
  // `model` "inherit" means no override — actual per-phase model/thinking
  // routing re-spawns the session and lands with cct-agents (Phase 7); live
  // per-phase permission switching lands with Phase 5. `permissions` here is a
  // named posture reported by status/doctor, not fed to the permission engine.
  phases: {
    research: { model: "inherit", thinking: "high", tools: ["read", "grep", "find", "ls"], skills: [], context: ["always"], permissions: "read-only" },
    plan: { model: "inherit", thinking: "high", tools: ["read", "grep", "find", "ls", "write"], skills: [], context: ["always"], permissions: "plan" },
    build: { model: "inherit", thinking: "medium", tools: ["read", "grep", "find", "ls", "write", "edit", "bash"], skills: [], context: ["always"], permissions: "build" },
    review: { model: "inherit", thinking: "high", tools: ["read", "grep", "find", "ls"], skills: [], context: ["always"], permissions: "read-only" },
  },
};

export function isSensitivePath(dotted: string): boolean {
  return SENSITIVE_KEY.test(dotted);
}

function isTable(v: TomlValue | undefined): v is TomlTable {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function* leaves(table: TomlTable, prefix = ""): Generator<[string, TomlValue]> {
  for (const key of Object.keys(table)) {
    const dotted = prefix ? `${prefix}.${key}` : key;
    const value = table[key];
    if (isTable(value)) yield* leaves(value, dotted);
    else yield [dotted, value];
  }
}

function setPath(table: TomlTable, dotted: string, value: TomlValue): void {
  const parts = dotted.split(".");
  let node = table;
  for (const part of parts.slice(0, -1)) {
    if (!isTable(node[part])) node[part] = {};
    node = node[part] as TomlTable;
  }
  node[parts[parts.length - 1]] = value;
}

function coerceScalar(raw: string): TomlValue {
  if (raw === "true") return true;
  if (raw === "false") return false;
  if (/^[+-]?\d+$/.test(raw)) return parseInt(raw, 10);
  if (/^[+-]?\d+\.\d+$/.test(raw)) return parseFloat(raw);
  if (raw.startsWith("[") || raw.startsWith("{")) {
    try {
      return JSON.parse(raw) as TomlValue;
    } catch {
      /* fall through to string */
    }
  }
  return raw;
}

interface Layer {
  name: string;
  source: string;
  table: TomlTable;
}

export function loadLayeredConfig(opts: LoadOptions): LoadResult {
  const env = opts.env ?? process.env;
  const result: LoadResult = {
    config: {},
    resolved: new Map(),
    profileChain: [],
    loadedFiles: [],
    ignoredFiles: [],
    floorDecisions: [],
    warnings: [],
    errors: [],
    configVersion: CONFIG_SCHEMA_VERSION,
    migrations: [],
  };

  const layers: Layer[] = [
    { name: "defaults", source: "<built-in>", table: BUILTIN_DEFAULTS },
  ];

  // Profile chain (base-most first).
  try {
    const chain = resolveProfileChain(opts.profile, opts.profiles ?? BUILTIN_PROFILES);
    result.profileChain = chain.map((p) => p.name);
    for (const p of chain) {
      layers.push({ name: "profile", source: `<profile:${p.name}>`, table: p.config });
    }
  } catch (e) {
    result.errors.push((e as Error).message);
  }

  // File layers.
  const fileLayer = (name: string, file: string, gate?: () => string | null): void => {
    if (!fs.existsSync(file)) return;
    if (gate) {
      const reason = gate();
      if (reason !== null) {
        result.ignoredFiles.push({ file, reason });
        return;
      }
    }
    try {
      const parsed = parseToml(fs.readFileSync(file, "utf8"));
      // Version and migrate before merging: an unreadable version must keep
      // the file out of the merge entirely rather than half-apply it (C-3).
      const migrated = migrateTable(parsed);
      if (migrated.error !== null) {
        result.errors.push(`${file}: ${migrated.error}`);
        result.ignoredFiles.push({ file, reason: migrated.error });
        return;
      }
      if (migrated.notes.length > 0) {
        result.migrations.push({ file, notes: migrated.notes });
        for (const n of migrated.notes) {
          result.warnings.push(`${file}: migrated v${n.from}->v${n.to}: ${n.change}`);
        }
      }
      const table = migrated.table;
      // File metadata, not configuration — keep it out of the resolved keys.
      delete table[CONFIG_VERSION_KEY];
      layers.push({ name, source: file, table });
      result.loadedFiles.push(file);
    } catch (e) {
      if (e instanceof TomlError) result.errors.push(`${file}: ${e.message}`);
      else result.errors.push(`${file}: ${(e as Error).message}`);
    }
  };

  fileLayer("global", path.join(opts.globalDir, "config.toml"));

  const projectGate = (): string | null => {
    if (opts.noProjectConfig) return "--no-project-config / --global set";
    if (!opts.trusted)
      return "project is not positively trusted (Pi project_trust unresolved or denied) — FR-004a fail-closed";
    return null;
  };
  fileLayer("project", path.join(opts.projectDir, ".code-copilot-team", "config.toml"), projectGate);
  fileLayer(
    "project-local",
    path.join(opts.projectDir, ".code-copilot-team", "config.local.toml"),
    projectGate,
  );

  // Env layer: CCT_CONFIG__a__b=value → a.b = value
  const envTable: TomlTable = {};
  let envAny = false;
  for (const key of Object.keys(env).sort()) {
    if (!key.startsWith("CCT_CONFIG__")) continue;
    const dotted = key.slice("CCT_CONFIG__".length).split("__").join(".").toLowerCase();
    setPath(envTable, dotted, coerceScalar(env[key] as string));
    envAny = true;
  }
  if (envAny) layers.push({ name: "env", source: "<env:CCT_CONFIG__*>", table: envTable });

  // CLI layer: pi-code --set a.b=v (newline-joined in CCT_CLI_SETS or opts).
  const sets = opts.cliSets ?? (env.CCT_CLI_SETS ? env.CCT_CLI_SETS.split("\n") : []);
  const cliTable: TomlTable = {};
  let cliAny = false;
  for (const entry of sets) {
    const eq = entry.indexOf("=");
    if (eq <= 0) {
      result.warnings.push(`ignoring malformed --set entry: '${entry}'`);
      continue;
    }
    setPath(cliTable, entry.slice(0, eq).trim(), coerceScalar(entry.slice(eq + 1).trim()));
    cliAny = true;
  }
  if (cliAny) layers.push({ name: "cli", source: "<cli:--set>", table: cliTable });

  // Merge with provenance; protected keys route through the floor engine.
  for (const layer of layers) {
    for (const [dotted, value] of leaves(layer.table)) {
      const prior = result.resolved.get(dotted);
      const floor = isFloorPath(dotted);
      let kept: TomlValue = value;

      if (floor) {
        const { kept: k, decision } = applyFloorValue(
          dotted,
          layer.name,
          prior?.value,
          value,
        );
        kept = k as TomlValue;
        if (decision.action !== "unchanged") result.floorDecisions.push(decision);
        if (decision.action === "blocked-weakening") {
          result.warnings.push(
            `security floor: '${dotted}' from ${layer.source} would weaken protected policy — kept ${JSON.stringify(decision.kept)} (record: blocked-weakening)`,
          );
          continue; // provenance stays with the stronger prior
        }
      }

      const history = prior
        ? [...prior.history, { layer: prior.layer, source: prior.source, value: prior.value }]
        : [];
      result.resolved.set(dotted, {
        path: dotted,
        value: kept,
        layer: layer.name,
        source: layer.source,
        history,
        sensitive: isSensitivePath(dotted),
        floor,
      });
    }
  }

  for (const [dotted, entry] of result.resolved) setPath(result.config, dotted, entry.value);
  return result;
}

/** Explain one resolved key (FR-004 "explain why each final value was selected"). */
export function explainKey(result: LoadResult, dotted: string): string {
  const entry = result.resolved.get(dotted);
  if (!entry) {
    const near = [...result.resolved.keys()].filter((k) => k.includes(dotted)).slice(0, 8);
    return `key '${dotted}' is not set.${near.length ? ` Did you mean: ${near.join(", ")}` : ""}`;
  }
  const value = entry.sensitive ? "<redacted>" : JSON.stringify(entry.value);
  const lines = [
    `${dotted} = ${value}`,
    `  set by:  ${entry.layer} (${entry.source})`,
    entry.floor ? "  protected: security-floor key (monotonic)" : "",
    entry.sensitive ? "  sensitivity: redacted in exports and telemetry" : "",
  ];
  for (const h of [...entry.history].reverse()) {
    lines.push(
      `  overrode: ${entry.sensitive ? "<redacted>" : JSON.stringify(h.value)} from ${h.layer} (${h.source})`,
    );
  }
  return lines.filter(Boolean).join("\n");
}

/** Redacted resolved dump for /cct:config and pi-code export (NFR-003). */
export function redactedConfig(result: LoadResult): { [k: string]: unknown } {
  const out: { [k: string]: unknown } = {};
  for (const [dotted, entry] of [...result.resolved].sort(([a], [b]) => a.localeCompare(b))) {
    out[dotted] = entry.sensitive ? "<redacted>" : entry.value;
  }
  return out;
}
