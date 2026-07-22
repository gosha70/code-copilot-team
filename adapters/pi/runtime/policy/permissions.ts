/**
 * CCT permission engine (spec FR-009; authored).
 *
 * Normalized allow / ask / deny rules over tools, commands, and paths.
 * Precedence within a decision: deny > ask > allow > default.
 * Headless contract (FR-022): `ask` resolves deterministically to the
 * configured `headless.ask_resolution` ("allow" | "deny" | "fail") —
 * no safety-critical decision may depend on an interactive prompt.
 *
 * Rule sources (from layered config, already floor-protected):
 *   tools.allow / tools.deny            — tool-name lists ("*" wildcard)
 *   permissions.paths.deny / .ask       — path globs (see matchGlob)
 *   security.denied_commands            — command prefixes (normalized)
 *   permissions.commands.ask            — command prefixes
 */

export type Decision = "allow" | "ask" | "deny";

export interface PermissionRuleSet {
  toolsAllow: string[]; // empty = all tools allowed by default
  toolsDeny: string[];
  pathsDeny: string[];
  pathsAsk: string[];
  commandsDeny: string[]; // normalized prefixes, e.g. "git push --force"
  commandsAsk: string[];
  askResolution: "allow" | "deny" | "fail"; // headless resolution
  interactive: boolean;
}

export interface PermissionVerdict {
  decision: Decision;
  effective: "allow" | "deny" | "fail"; // after headless ask resolution
  rule: string | null; // which rule fired (for audit + reason text)
  reason: string;
}

/** Minimal glob: `*` = within segment, `**` = any depth, `?` = one char. */
export function matchGlob(pattern: string, value: string): boolean {
  const esc = (s: string): string => s.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  let re = "";
  let i = 0;
  while (i < pattern.length) {
    if (pattern.startsWith("**/", i)) {
      re += "(?:.*/)?";
      i += 3;
    } else if (pattern.startsWith("**", i)) {
      re += ".*";
      i += 2;
    } else if (pattern[i] === "*") {
      re += "[^/]*";
      i += 1;
    } else if (pattern[i] === "?") {
      re += "[^/]";
      i += 1;
    } else {
      re += esc(pattern[i]);
      i += 1;
    }
  }
  // A bare name pattern (no slash) may match at any depth (protect ".env"
  // anywhere in the tree, matching hook behavior).
  const anchored = pattern.includes("/") ? `^${re}$` : `(^|/)${re}$`;
  return new RegExp(anchored).test(value.replace(/\\/g, "/"));
}

/** Normalize a shell command for prefix comparison (collapse whitespace). */
export function normalizeCommand(cmd: string): string {
  return cmd.trim().replace(/\s+/g, " ");
}

/**
 * Split a compound shell command on top-level separators (;, &&, ||, |, &)
 * so `echo hi && git push --force` cannot smuggle a denied command
 * (security test: chained destructive commands).
 */
export function splitCommands(raw: string): string[] {
  const parts: string[] = [];
  let current = "";
  let quote: string | null = null;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    // POSIX processes backslash escapes inside "..." but never inside '...'.
    // Consume the escaped pair atomically so `'a\'` closes its quote and
    // `"a\\"` does not leave one open — either would hide a separator.
    if (quote === '"' && ch === "\\" && i + 1 < raw.length) {
      current += ch + raw[i + 1];
      i += 1;
      continue;
    }
    if (quote) {
      current += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      current += ch;
      continue;
    }
    if (ch === ";" || ch === "&" || ch === "|" || ch === "\n") {
      if (current.trim()) parts.push(current.trim());
      current = "";
      continue;
    }
    // Subshell / command substitution openers: keep contents for scanning.
    current += ch;
  }
  if (current.trim()) parts.push(current.trim());
  // Also scan inside $(…) and `…` substitutions.
  const nested: string[] = [];
  for (const p of parts) {
    const sub = p.match(/\$\(([^)]*)\)|`([^`]*)`/g);
    if (sub) for (const s of sub) nested.push(s.replace(/^\$\(|\)$|^`|`$/g, ""));
  }
  return [...parts, ...nested.filter((n) => n.trim())];
}

function commandMatches(prefix: string, command: string): boolean {
  const np = normalizeCommand(prefix);
  const nc = normalizeCommand(command);
  if (nc === np) return true;
  if (!nc.startsWith(np)) return false;
  const next = nc[np.length];
  return next === " " || next === undefined;
}

function resolveAsk(rules: PermissionRuleSet, rule: string, what: string): PermissionVerdict {
  if (rules.interactive) {
    return {
      decision: "ask",
      effective: "allow", // interactive: escalate to the user via ctx.ui.confirm
      rule,
      reason: `${what} requires confirmation (rule: ${rule})`,
    };
  }
  const effective = rules.askResolution === "allow" ? "allow" : rules.askResolution;
  return {
    decision: "ask",
    effective,
    rule,
    reason: `${what} is ask-gated; headless ask_resolution=${rules.askResolution} (rule: ${rule})`,
  };
}

export function checkTool(rules: PermissionRuleSet, toolName: string): PermissionVerdict {
  for (const t of rules.toolsDeny) {
    if (t === "*" || t === toolName) {
      return {
        decision: "deny",
        effective: "deny",
        rule: `tools.deny:${t}`,
        reason: `tool '${toolName}' is denied by policy`,
      };
    }
  }
  if (rules.toolsAllow.length > 0 && !rules.toolsAllow.includes(toolName)) {
    return {
      decision: "deny",
      effective: "deny",
      rule: "tools.allow",
      reason: `tool '${toolName}' is not in the active allowlist [${rules.toolsAllow.join(", ")}]`,
    };
  }
  return { decision: "allow", effective: "allow", rule: null, reason: "allowed" };
}

export function checkPath(rules: PermissionRuleSet, filePath: string): PermissionVerdict {
  for (const g of rules.pathsDeny) {
    if (matchGlob(g, filePath)) {
      return {
        decision: "deny",
        effective: "deny",
        rule: `paths.deny:${g}`,
        reason: `path '${filePath}' matches protected pattern '${g}'`,
      };
    }
  }
  for (const g of rules.pathsAsk) {
    if (matchGlob(g, filePath)) return resolveAsk(rules, `paths.ask:${g}`, `path '${filePath}'`);
  }
  return { decision: "allow", effective: "allow", rule: null, reason: "allowed" };
}

export function checkCommand(rules: PermissionRuleSet, rawCommand: string): PermissionVerdict {
  const pieces = splitCommands(rawCommand);
  for (const piece of pieces) {
    for (const prefix of rules.commandsDeny) {
      if (commandMatches(prefix, piece)) {
        return {
          decision: "deny",
          effective: "deny",
          rule: `commands.deny:${prefix}`,
          reason: `command '${piece}' matches denied pattern '${prefix}'`,
        };
      }
    }
  }
  for (const piece of pieces) {
    for (const prefix of rules.commandsAsk) {
      if (commandMatches(prefix, piece))
        return resolveAsk(rules, `commands.ask:${prefix}`, `command '${piece}'`);
    }
  }
  return { decision: "allow", effective: "allow", rule: null, reason: "allowed" };
}

/** Build a rule set from resolved CCT config (loader output). */
export function rulesFromConfig(
  get: (path: string) => unknown,
  interactive: boolean,
): PermissionRuleSet {
  const arr = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);
  const askRes = get("headless.ask_resolution");
  return {
    toolsAllow: arr(get("tools.allow")),
    toolsDeny: arr(get("tools.deny")),
    pathsDeny: arr(get("security.protected_paths")),
    pathsAsk: arr(get("permissions.paths.ask")),
    commandsDeny: arr(get("security.denied_commands")),
    commandsAsk: arr(get("permissions.commands.ask")),
    askResolution:
      askRes === "allow" || askRes === "fail" ? (askRes as "allow" | "fail") : "deny",
    interactive,
  };
}
