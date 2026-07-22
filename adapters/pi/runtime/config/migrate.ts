/**
 * CCT configuration versioning and migration (spec FR-004; authored).
 *
 * Every configuration file declares `config_version`. Files written before
 * versioning existed carry none and are treated as version 1.
 *
 * Migrations run in order, each moving a table from one version to the next,
 * and report what they changed so the loader can surface it rather than
 * silently rewriting a user's configuration in memory.
 *
 * A file declaring a version NEWER than this runtime supports is an error,
 * not a warning: the file may rely on semantics this build does not implement,
 * and security-relevant settings must fail closed (C-3).
 */

import type { TomlTable, TomlValue } from "./toml.ts";

/** Version this runtime reads and writes. */
export const CONFIG_SCHEMA_VERSION = 2;

/** Key every configuration file may declare. */
export const CONFIG_VERSION_KEY = "config_version";

export interface MigrationNote {
  from: number;
  to: number;
  change: string;
}

export interface MigrationResult {
  table: TomlTable;
  /** Version declared by the file (1 when absent). */
  declared: number;
  notes: MigrationNote[];
  /** Set when the file cannot be used at all. */
  error: string | null;
}

interface Migration {
  from: number;
  to: number;
  apply: (table: TomlTable) => string[];
}

function isTable(v: TomlValue | undefined): v is TomlTable {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function getPath(table: TomlTable, dotted: string): TomlValue | undefined {
  let cur: TomlValue | undefined = table;
  for (const part of dotted.split(".")) {
    if (!isTable(cur)) return undefined;
    cur = cur[part];
  }
  return cur;
}

function setPath(table: TomlTable, dotted: string, value: TomlValue): void {
  const parts = dotted.split(".");
  const last = parts.pop() as string;
  let cur = table;
  for (const part of parts) {
    if (!isTable(cur[part])) cur[part] = {};
    cur = cur[part] as TomlTable;
  }
  cur[last] = value;
}

function deletePath(table: TomlTable, dotted: string): void {
  const parts = dotted.split(".");
  const last = parts.pop() as string;
  let cur: TomlValue | undefined = table;
  for (const part of parts) {
    if (!isTable(cur)) return;
    cur = cur[part];
  }
  if (isTable(cur)) delete cur[last];
}

/**
 * Rename a key, preserving the existing value. If the new key is already set
 * the old one is dropped without overwriting — an explicit new-form setting
 * always wins over a stale old-form one.
 */
function rename(
  table: TomlTable,
  from: string,
  to: string,
  notes: string[],
): void {
  const oldValue = getPath(table, from);
  if (oldValue === undefined) return;
  if (getPath(table, to) === undefined) {
    setPath(table, to, oldValue);
    notes.push(`renamed '${from}' to '${to}'`);
  } else {
    notes.push(
      `dropped '${from}'; '${to}' is already set and takes precedence`,
    );
  }
  deletePath(table, from);
}

/**
 * Ordered migrations. Each entry moves a table from `from` to `to`; adding a
 * new one means bumping CONFIG_SCHEMA_VERSION to match its `to`.
 */
const MIGRATIONS: Migration[] = [
  {
    from: 1,
    to: 2,
    apply: (table) => {
      const notes: string[] = [];
      // v1 spelled the headless contract as a bare boolean; v2 uses the
      // three-valued resolution so "fail" is expressible (FR-022).
      const legacy = getPath(table, "headless.deny_asks");
      if (typeof legacy === "boolean") {
        if (getPath(table, "headless.ask_resolution") === undefined) {
          setPath(table, "headless.ask_resolution", legacy ? "deny" : "allow");
          notes.push(
            `converted 'headless.deny_asks = ${legacy}' to ` +
              `'headless.ask_resolution = "${legacy ? "deny" : "allow"}"'`,
          );
        } else {
          notes.push(
            "dropped 'headless.deny_asks'; 'headless.ask_resolution' is already set",
          );
        }
        deletePath(table, "headless.deny_asks");
      }
      // v1 grouped both under `security`; paths moved to `permissions`.
      rename(table, "security.ask_paths", "permissions.paths.ask", notes);
      rename(table, "security.ask_commands", "permissions.commands.ask", notes);
      return notes;
    },
  },
];

/** Read a file's declared config version. Absent means 1 (pre-versioning). */
export function declaredVersion(table: TomlTable): number | null {
  const raw = table[CONFIG_VERSION_KEY];
  if (raw === undefined) return 1;
  if (typeof raw === "number" && Number.isInteger(raw) && raw >= 1) return raw;
  return null; // present but not a positive integer
}

/**
 * Bring a parsed configuration table up to CONFIG_SCHEMA_VERSION.
 *
 * The input table is not mutated. `error` is set (and the table returned
 * unchanged) when the file declares a version this runtime cannot read.
 */
export function migrateTable(table: TomlTable): MigrationResult {
  const declared = declaredVersion(table);
  if (declared === null) {
    return {
      table,
      declared: 0,
      notes: [],
      error: `${CONFIG_VERSION_KEY} must be a positive integer`,
    };
  }
  if (declared > CONFIG_SCHEMA_VERSION) {
    return {
      table,
      declared,
      notes: [],
      error:
        `${CONFIG_VERSION_KEY} ${declared} is newer than this runtime supports ` +
        `(${CONFIG_SCHEMA_VERSION}); upgrade Code Copilot Team or pin the older config`,
    };
  }

  const working = JSON.parse(JSON.stringify(table)) as TomlTable;
  const notes: MigrationNote[] = [];
  let version = declared;
  for (const m of MIGRATIONS) {
    if (m.from < version) continue;
    if (m.from !== version) break; // gap in the chain; stop rather than guess
    for (const change of m.apply(working)) {
      notes.push({ from: m.from, to: m.to, change });
    }
    version = m.to;
  }
  working[CONFIG_VERSION_KEY] = CONFIG_SCHEMA_VERSION;

  return { table: working, declared, notes, error: null };
}
