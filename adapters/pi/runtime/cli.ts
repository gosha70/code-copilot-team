/**
 * Diagnostic CLI for pi-code (spec FR-004/FR-029, T1.6; authored).
 *
 * Backs `pi-code doctor | config | config explain <key> | features`, each with
 * `--json`. It runs OUTSIDE a Pi session, which has one consequence worth
 * stating plainly: Pi's `isProjectTrusted()` is unavailable here, so project
 * configuration is resolved as untrusted (C-3 fail closed). Reported output
 * therefore shows the global/profile view; a live session may resolve
 * additional project layers once trust is positively established. Every
 * surface says so rather than letting the reader assume otherwise.
 *
 * Values are always redacted through the loader's redaction path — this
 * output is pasted into issues.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import {
  explainKey,
  loadLayeredConfig,
  redactedConfig,
} from "./config/loader.ts";
import { CONFIG_SCHEMA_VERSION } from "./config/migrate.ts";
import { seedCapabilities } from "./capabilities.ts";

export interface CliResult {
  out: string;
  code: number;
}

export interface CliOptions {
  argv: string[];
  cwd: string;
  globalDir: string;
  runtimeEntry?: string | null;
  /** Trust is unknowable outside a session; kept injectable for tests. */
  trusted?: boolean;
}

const TRUST_NOTE =
  "project config resolved as UNTRUSTED: pi-code diagnostics run outside a Pi " +
  "session, where isProjectTrusted() is unavailable (fail-closed, C-3)";

function load(opts: CliOptions) {
  return loadLayeredConfig({
    globalDir: opts.globalDir,
    projectDir: opts.cwd,
    trusted: opts.trusted === true,
    profile: process.env.CCT_PROFILE ?? "disciplined",
    noProjectConfig: process.env.CCT_NO_PROJECT_CONFIG === "1",
  });
}

function jsonOut(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function doctor(opts: CliOptions, json: boolean): CliResult {
  const cfg = load(opts);
  const caps = seedCapabilities();
  const runtimeOk = Boolean(
    opts.runtimeEntry && fs.existsSync(opts.runtimeEntry),
  );
  const checks = [
    {
      name: "enforcement runtime",
      ok: runtimeOk,
      detail: opts.runtimeEntry ?? "<not installed>",
    },
    {
      name: "configuration",
      ok: cfg.errors.length === 0,
      detail: `${cfg.loadedFiles.length} file(s) loaded`,
    },
    { name: "config schema", ok: true, detail: `v${CONFIG_SCHEMA_VERSION}` },
    {
      name: "capabilities",
      ok: true,
      detail: `${caps.filter((c) => c.runtime_status === "enabled").length}/${caps.length} enabled`,
    },
  ];
  const code = checks.every((c) => c.ok) && cfg.errors.length === 0 ? 0 : 1;

  if (json) {
    return {
      out: jsonOut({
        checks,
        profileChain: cfg.profileChain,
        loadedFiles: cfg.loadedFiles,
        ignoredFiles: cfg.ignoredFiles,
        migrations: cfg.migrations,
        warnings: cfg.warnings,
        errors: cfg.errors,
        trustNote: TRUST_NOTE,
      }),
      code,
    };
  }

  const lines = ["=== pi-code doctor ==="];
  for (const c of checks)
    lines.push(`[${c.ok ? "ok" : "fail"}]   ${c.name}: ${c.detail}`);
  lines.push(`profile chain: ${cfg.profileChain.join(" -> ") || "<none>"}`);
  for (const f of cfg.ignoredFiles) lines.push(`[skip] ${f.file}: ${f.reason}`);
  for (const m of cfg.migrations) {
    for (const n of m.notes)
      lines.push(`[migrated] ${m.file}: v${n.from}->v${n.to}: ${n.change}`);
  }
  for (const w of cfg.warnings) lines.push(`warning: ${w}`);
  for (const e of cfg.errors) lines.push(`error: ${e}`);
  lines.push(`note: ${TRUST_NOTE}`);
  return { out: lines.join("\n"), code };
}

function config(opts: CliOptions, json: boolean): CliResult {
  const cfg = load(opts);
  const redacted = redactedConfig(cfg);
  if (json) {
    return {
      out: jsonOut({
        configVersion: cfg.configVersion,
        profileChain: cfg.profileChain,
        config: redacted,
        loadedFiles: cfg.loadedFiles,
        trustNote: TRUST_NOTE,
      }),
      code: 0,
    };
  }
  const lines = [`# resolved configuration (v${cfg.configVersion}, redacted)`];
  lines.push(`# profile chain: ${cfg.profileChain.join(" -> ") || "<none>"}`);
  lines.push(`# ${TRUST_NOTE}`);
  const walk = (obj: { [k: string]: unknown }, prefix: string): void => {
    for (const key of Object.keys(obj).sort()) {
      const v = obj[key];
      const dotted = prefix ? `${prefix}.${key}` : key;
      if (v && typeof v === "object" && !Array.isArray(v))
        walk(v as { [k: string]: unknown }, dotted);
      else lines.push(`${dotted} = ${JSON.stringify(v)}`);
    }
  };
  walk(redacted, "");
  return { out: lines.join("\n"), code: 0 };
}

function explain(
  opts: CliOptions,
  key: string | undefined,
  json: boolean,
): CliResult {
  if (!key) {
    return {
      out: "usage: pi-code config explain <key>   (e.g. security.fail_closed)",
      code: 64,
    };
  }
  const cfg = load(opts);
  const resolved = cfg.resolved.get(key);
  if (!resolved) {
    const known = [...cfg.resolved.keys()].sort().slice(0, 15).join(", ");
    return {
      out: json
        ? jsonOut({ key, found: false, knownKeysSample: known.split(", ") })
        : `key '${key}' is not set by any layer.\nknown keys (sample): ${known}`,
      code: 1,
    };
  }
  if (json) {
    return {
      out: jsonOut({
        key,
        found: true,
        value: resolved.value,
        history: resolved.history,
        trustNote: TRUST_NOTE,
      }),
      code: 0,
    };
  }
  return { out: explainKey(cfg, key), code: 0 };
}

function features(json: boolean): CliResult {
  const caps = seedCapabilities();
  if (json) return { out: jsonOut({ capabilities: caps }), code: 0 };
  const lines = ["=== capabilities ==="];
  const width = Math.max(...caps.map((c) => c.id.length));
  for (const c of caps) {
    lines.push(
      `${c.id.padEnd(width)}  ${c.runtime_status.padEnd(13)} ${c.implementation_kind}` +
        (c.reason ? `\n${" ".repeat(width + 2)}  reason: ${c.reason}` : ""),
    );
  }
  return { out: lines.join("\n"), code: 0 };
}

export function runCli(opts: CliOptions): CliResult {
  const args = [...opts.argv];
  const json = args.includes("--json");
  const positional = args.filter((a) => !a.startsWith("--"));
  const command = positional[0] ?? "doctor";

  switch (command) {
    case "doctor":
      return doctor(opts, json);
    case "config":
      return positional[1] === "explain"
        ? explain(opts, positional[2], json)
        : config(opts, json);
    case "features":
      return features(json);
    default:
      return {
        out: `unknown command '${command}' (expected: doctor | config | config explain <key> | features)`,
        code: 64,
      };
  }
}

/** Entry point used by the launcher. */
export function main(argv: string[]): CliResult {
  return runCli({
    argv,
    cwd: process.env.CCT_CLI_CWD ?? process.cwd(),
    globalDir:
      process.env.CCT_HOME ?? path.join(os.homedir(), ".code-copilot-team"),
    runtimeEntry: process.env.CCT_RUNTIME_ENTRY ?? null,
  });
}

// Executed directly by `pi-code` (node --experimental-strip-types cli.ts ...).
if (process.argv[1] && process.argv[1].endsWith("cli.ts")) {
  const result = main(process.argv.slice(2));
  process.stdout.write(result.out + "\n");
  process.exit(result.code);
}
