/**
 * Claude Code permissions/*.json -> Pi rule-list importer (T5.2, FR-009).
 *
 * Pure converter: maps Claude profile permission entries into Pi's existing
 * allow / ask / deny / protected-path / denied-command rule lists. It changes
 * NO enforcement semantics — it only produces lists the permission engine
 * already understands. Entries with no faithful Pi target are reported as
 * structured warnings/skips, never silently approximated. Path-scoped denies
 * import to protected paths (Pi enforces those on write tools only); a read-only
 * origin (Read/Glob/Grep) additionally records a `notEnforced` note so the
 * read-vs-write gap is explicit. See specs/pi-harness-adoption/design-t52-importer.md.
 *
 * This task delivers the converter + fixtures/tests only. Wiring the imported
 * lists into the layered config is a later task.
 */

export interface ImportedRules {
  toolsAllow: string[];
  toolsDeny: string[];
  pathsDeny: string[];
  pathsAsk: string[];
  commandsDeny: string[];
  commandsAsk: string[];
}

export type PermissionSection = "allow" | "deny" | "ask";

export interface ImportWarning {
  entry: string;
  section: PermissionSection;
  reason: string;
}

/** A rule that imported, but whose original Claude intent Pi cannot fully enforce. */
export interface NotEnforced {
  entry: string;
  target: string; // the Pi rule the entry mapped to
  reason: string;
}

export interface ImportResult {
  rules: ImportedRules;
  warnings: ImportWarning[];
  notEnforced: NotEnforced[];
}

// File tools whose scoped argument is a path. Bash is handled separately (its
// argument is a command pattern).
const FILE_TOOLS = new Set(["read", "edit", "write", "glob", "grep"]);
// Read-oriented tools: Pi path-gates writes only, so a path rule from one of
// these does not enforce the tool's own (read) intent.
const READ_ONLY_TOOLS = new Set(["read", "glob", "grep"]);

interface ParsedEntry {
  tool: string; // lowercased Pi tool name
  arg: string | null; // inside Tool(...), or null for a bare tool
}

function parseEntry(raw: string): ParsedEntry | null {
  const m = /^([A-Za-z][A-Za-z0-9_]*)(?:\((.*)\))?$/.exec(raw.trim());
  if (!m) return null;
  return { tool: m[1].toLowerCase(), arg: m[2] ?? null };
}

/** Strip a leading `./` so a bare name matches at any depth in Pi's glob. */
function normalizePath(arg: string): string {
  const p = arg.trim();
  return p.startsWith("./") ? p.slice(2) : p;
}

interface BashParse {
  prefix: string;
  warning: string | null;
}

/**
 * Convert a Claude `Bash(...)` argument to a Pi command prefix. The common form
 * `<prefix>:*` (any args) maps exactly to Pi's prefix word-boundary match. An
 * argument without `:*` is a Claude exact-match imported as a (broader) prefix;
 * a non-trailing `:` is non-standard — both are imported with a warning.
 */
function parseBashPattern(arg: string): BashParse {
  const a = arg.trim();
  if (a.endsWith(":*")) return { prefix: a.slice(0, -2).trim(), warning: null };
  if (a.includes(":")) {
    return {
      prefix: a,
      warning: `Bash pattern '${a}' has a non-trailing ':'; imported verbatim as a prefix`,
    };
  }
  return {
    prefix: a,
    warning: `Bash('${a}') is a Claude exact-match; imported as a Pi prefix (also matches '${a} <args>')`,
  };
}

export function importClaudePermissions(json: unknown): ImportResult {
  const rules: ImportedRules = {
    toolsAllow: [],
    toolsDeny: [],
    pathsDeny: [],
    pathsAsk: [],
    commandsDeny: [],
    commandsAsk: [],
  };
  const warnings: ImportWarning[] = [];
  const notEnforced: NotEnforced[] = [];

  const root =
    json && typeof json === "object" ? (json as Record<string, unknown>) : {};
  const perms =
    root.permissions && typeof root.permissions === "object"
      ? (root.permissions as Record<string, unknown>)
      : {};

  const pushUnique = (list: string[], v: string): void => {
    if (v && !list.includes(v)) list.push(v);
  };
  const warn = (
    entry: string,
    section: PermissionSection,
    reason: string,
  ): void => {
    warnings.push({ entry, section, reason });
  };

  const sections: PermissionSection[] = ["allow", "deny", "ask"];
  for (const section of sections) {
    const entries = Array.isArray(perms[section]) ? perms[section] : [];
    for (const raw of entries as unknown[]) {
      if (typeof raw !== "string") continue;
      const parsed = parseEntry(raw);
      if (!parsed) {
        warn(raw, section, "unparseable permission entry");
        continue;
      }
      const { tool, arg } = parsed;

      // Bare tool -> tool allow/deny. Pi has no tool-level ask.
      if (arg === null) {
        if (section === "allow") pushUnique(rules.toolsAllow, tool);
        else if (section === "deny") pushUnique(rules.toolsDeny, tool);
        else
          warn(
            raw,
            section,
            "bare tool in 'ask' has no Pi tool-level ask target",
          );
        continue;
      }

      // Scoped Bash(...) -> command prefix. Pi has no command allowlist.
      if (tool === "bash") {
        if (section === "allow") {
          warn(
            raw,
            section,
            "Pi has no command allowlist; scoped Bash allow skipped",
          );
          continue;
        }
        const { prefix, warning } = parseBashPattern(arg);
        if (warning) warn(raw, section, warning);
        if (!prefix) {
          warn(raw, section, "empty Bash pattern skipped");
          continue;
        }
        pushUnique(
          section === "deny" ? rules.commandsDeny : rules.commandsAsk,
          prefix,
        );
        continue;
      }

      // Scoped file tool(...) -> protected path. Pi has no path allowlist.
      if (FILE_TOOLS.has(tool)) {
        const p = normalizePath(arg);
        if (!p) {
          warn(raw, section, "empty path pattern skipped");
          continue;
        }
        if (section === "allow") {
          warn(
            raw,
            section,
            "Pi has no path allowlist; scoped file-tool allow skipped",
          );
          continue;
        }
        pushUnique(section === "deny" ? rules.pathsDeny : rules.pathsAsk, p);
        if (READ_ONLY_TOOLS.has(tool)) {
          notEnforced.push({
            entry: raw,
            target: `${section === "deny" ? "pathsDeny" : "pathsAsk"}:${p}`,
            reason:
              "Pi enforces protected paths on write tools only; the read intent " +
              `of '${raw}' is not enforced`,
          });
        }
        continue;
      }

      // Any other scoped tool (WebFetch, WebSearch, ...) has no Pi rule target.
      warn(raw, section, `scoped '${tool}' has no Pi rule target`);
    }
  }

  return { rules, warnings, notEnforced };
}
