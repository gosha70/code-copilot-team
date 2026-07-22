/**
 * Monotonic user security floor (spec P7 / FR-009a §8.2; authored).
 *
 * Protected settings follow a separate precedence chain in which trusted
 * PROJECT configuration may STRENGTHEN but never WEAKEN the floor
 * established by built-in minimums + user (global) configuration.
 * Explicit relaxation is allowed only from user-controlled layers
 * (project-local override file or session/CLI) and is always recorded.
 */

export type FloorCombinator =
  | "array-union" // stricter = superset (protected paths, denied commands)
  | "bool-or" // stricter = true (deny_network, sandbox_required, fail_closed, mandatory review)
  | "bool-and"; // stricter = false (allow_package_install, allow_secret_paths)

/** Dotted config path → how strictness composes. */
export const SECURITY_FLOOR: { [path: string]: FloorCombinator } = {
  "security.protected_paths": "array-union",
  "security.denied_commands": "array-union",
  "security.deny_network": "bool-or",
  "security.sandbox_required": "bool-or",
  "security.fail_closed": "bool-or",
  "review.mandatory": "bool-or",
  "security.allow_package_install": "bool-and",
  "security.allow_secret_paths": "bool-and",
};

/** Layers allowed to relax the floor (user-controlled; spec §8.2). */
export const RELAXATION_LAYERS = new Set(["project-local", "cli", "env", "session"]);

export interface FloorDecision {
  path: string;
  layer: string;
  attempted: unknown;
  kept: unknown;
  action: "strengthened" | "blocked-weakening" | "relaxed-by-override" | "unchanged";
}

export function isFloorPath(path: string): boolean {
  return Object.prototype.hasOwnProperty.call(SECURITY_FLOOR, path);
}

function isStrictening(comb: FloorCombinator, current: unknown, incoming: unknown): boolean {
  switch (comb) {
    case "bool-or":
      return incoming === true || current === incoming;
    case "bool-and":
      return incoming === false || current === incoming;
    case "array-union": {
      const cur = Array.isArray(current) ? current : [];
      const inc = Array.isArray(incoming) ? incoming : [];
      // Superset (or equal) of current = strengthening.
      return cur.every((v) => inc.some((w) => JSON.stringify(w) === JSON.stringify(v)));
    }
  }
}

function strengthen(comb: FloorCombinator, current: unknown, incoming: unknown): unknown {
  switch (comb) {
    case "bool-or":
      return current === true || incoming === true;
    case "bool-and":
      return current === false || incoming === false ? false : true;
    case "array-union": {
      const cur = Array.isArray(current) ? current : [];
      const inc = Array.isArray(incoming) ? incoming : [];
      const out = [...cur];
      for (const v of inc) {
        if (!out.some((w) => JSON.stringify(w) === JSON.stringify(v))) out.push(v);
      }
      return out;
    }
  }
}

/**
 * Apply an incoming protected value from `layer` against the current floor
 * value. Returns the value to keep plus an auditable decision record.
 */
export function applyFloorValue(
  path: string,
  layer: string,
  current: unknown,
  incoming: unknown,
): { kept: unknown; decision: FloorDecision } {
  const comb = SECURITY_FLOOR[path];
  if (current === undefined) {
    return {
      kept: incoming,
      decision: { path, layer, attempted: incoming, kept: incoming, action: "unchanged" },
    };
  }
  if (JSON.stringify(current) === JSON.stringify(incoming)) {
    return {
      kept: current,
      decision: { path, layer, attempted: incoming, kept: current, action: "unchanged" },
    };
  }
  if (isStrictening(comb, current, incoming)) {
    const kept = strengthen(comb, current, incoming);
    return {
      kept,
      decision: { path, layer, attempted: incoming, kept, action: "strengthened" },
    };
  }
  // Weakening attempt.
  if (RELAXATION_LAYERS.has(layer)) {
    return {
      kept: incoming,
      decision: { path, layer, attempted: incoming, kept: incoming, action: "relaxed-by-override" },
    };
  }
  return {
    kept: current,
    decision: { path, layer, attempted: incoming, kept: current, action: "blocked-weakening" },
  };
}
