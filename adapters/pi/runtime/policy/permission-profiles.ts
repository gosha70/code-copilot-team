/**
 * Live-wiring for the Claude permissions importer (T5.2, FR-009).
 *
 * Resolves a Pi profile's `importPermissions[]` into a computed config layer:
 * reads the reused `permissions/<name>.json` (managed install first, then a repo
 * checkout), runs the pure `importClaudePermissions()` converter, unions the
 * results, and returns a `TomlTable` keyed for the layered config plus flattened
 * warnings for `LoadResult.warnings`. It changes NO enforcement semantics — the
 * permission engine consumes the now-populated config unchanged. The converter's
 * `warnings`/`notEnforced` are surfaced, never dropped (the read-vs-write gap
 * stays visible live). See specs/pi-harness-adoption/design-t52-live-wiring.md.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { TomlTable, TomlValue } from "../config/toml.ts";
import { importClaudePermissions } from "./import-permissions.ts";
import type { ImportedRules } from "./import-permissions.ts";

export interface ImportedLayer {
  table: TomlTable;
  warnings: string[];
  sources: string[]; // resolved JSON paths, for provenance
}

/**
 * Base floor arrays (from the built-in defaults). The monotonic floor treats an
 * array that is not a superset of the current value as a REMOVAL attempt and
 * blocks it (its removal-detection mechanism). An additive imported layer must
 * therefore present `base ∪ imported` for the floor keys so it composes as
 * strengthening rather than being read as "remove the defaults".
 */
export interface FloorBase {
  protectedPaths: string[];
  deniedCommands: string[];
}

// Where the reused permission profiles live: the managed install (bundled by
// setup.sh) first, then a repo checkout (adapters/claude-code/permissions).
function candidateDirs(globalDir: string): string[] {
  const dirs = [path.join(globalDir, "pi", "permissions")];
  try {
    const here = path.dirname(new URL(import.meta.url).pathname);
    // <adapter>/runtime/policy -> <adapter> -> ../claude-code/permissions
    dirs.push(path.join(here, "..", "..", "..", "claude-code", "permissions"));
  } catch {
    /* import.meta unavailable — the managed dir is enough */
  }
  return dirs;
}

function setPath(table: TomlTable, dotted: string, value: TomlValue): void {
  const parts = dotted.split(".");
  let node = table;
  for (const part of parts.slice(0, -1)) {
    const next = node[part];
    if (typeof next !== "object" || next === null || Array.isArray(next)) {
      node[part] = {};
    }
    node = node[part] as TomlTable;
  }
  node[parts[parts.length - 1]] = value;
}

const FIELDS: (keyof ImportedRules)[] = [
  "toolsAllow",
  "toolsDeny",
  "pathsDeny",
  "pathsAsk",
  "commandsDeny",
  "commandsAsk",
];

function unionArr(a: string[], b: string[]): string[] {
  const out = [...a];
  for (const v of b) if (!out.includes(v)) out.push(v);
  return out;
}

/**
 * Build the computed `imported` layer for the named permission profiles. Unknown
 * or malformed profiles are reported as warnings and skipped — never fatal.
 * `base` supplies the built-in floor arrays so imported denies compose as
 * strengthening (see FloorBase).
 */
export function buildImportedLayer(
  names: string[],
  globalDir: string,
  base?: FloorBase,
): ImportedLayer {
  const dirs = candidateDirs(globalDir);
  const merged: ImportedRules = {
    toolsAllow: [],
    toolsDeny: [],
    pathsDeny: [],
    pathsAsk: [],
    commandsDeny: [],
    commandsAsk: [],
  };
  const warnings: string[] = [];
  const sources: string[] = [];
  const seen = new Set<string>();

  for (const name of names) {
    if (seen.has(name)) continue;
    seen.add(name);

    let file: string | null = null;
    for (const d of dirs) {
      const f = path.join(d, `${name}.json`);
      if (fs.existsSync(f)) {
        file = f;
        break;
      }
    }
    if (file === null) {
      warnings.push(
        `permissions import '${name}': profile not found (searched ${dirs.join(", ")})`,
      );
      continue;
    }

    let json: unknown;
    try {
      json = JSON.parse(fs.readFileSync(file, "utf8"));
    } catch (e) {
      warnings.push(
        `permissions import '${name}': ${file} is not valid JSON — skipped (${(e as Error).message})`,
      );
      continue;
    }
    sources.push(file);

    const res = importClaudePermissions(json);
    for (const field of FIELDS) {
      for (const v of res.rules[field]) {
        if (!merged[field].includes(v)) merged[field].push(v);
      }
    }
    for (const w of res.warnings) {
      warnings.push(
        `permissions import '${name}': [${w.section}] ${w.entry} — ${w.reason}`,
      );
    }
    for (const n of res.notEnforced) {
      warnings.push(
        `permissions import '${name}': notEnforced ${n.entry} -> ${n.target} — ${n.reason}`,
      );
    }
  }

  const table: TomlTable = {};
  const put = (dotted: string, arr: string[]): void => {
    if (arr.length > 0) setPath(table, dotted, [...arr]);
  };
  // Non-floor lists: pure imported (base posture; profile/user layers may replace).
  put("tools.allow", merged.toolsAllow);
  put("tools.deny", merged.toolsDeny);
  put("permissions.paths.ask", merged.pathsAsk);
  put("permissions.commands.ask", merged.commandsAsk);
  // Floor lists: base ∪ imported, so the monotonic floor accepts them as
  // strengthening (a partial array would read as a removal attempt and block).
  put(
    "security.protected_paths",
    unionArr(base?.protectedPaths ?? [], merged.pathsDeny),
  );
  put(
    "security.denied_commands",
    unionArr(base?.deniedCommands ?? [], merged.commandsDeny),
  );
  return { table, warnings, sources };
}
