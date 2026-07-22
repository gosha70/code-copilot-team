/**
 * Protected-path resolution defenses (spec Phase 5: canonicalization,
 * symlink defense, traversal; authored).
 *
 * checkPath() in permissions.ts matches patterns against a path string.
 * This module makes sure the STRING being matched is the real target:
 *   - normalizes ../ traversal against the project root
 *   - resolves symlinks (existing prefix realpath) so a link cannot
 *     smuggle a write into a protected target (security test: "writes
 *     through symlinked paths")
 *   - flags escapes outside the project root
 */

import * as fs from "node:fs";
import * as path from "node:path";

export interface ResolvedTarget {
  /** Project-relative canonical path used for pattern matching. */
  relative: string;
  /** Absolute canonical path (symlinks in the existing prefix resolved). */
  absolute: string;
  /** True when the canonical target escapes the project root. */
  outsideProject: boolean;
  /** True when a symlink changed the effective target. */
  viaSymlink: boolean;
}

/**
 * Resolve the deepest existing ancestor of `p` through realpath, then
 * re-attach the non-existing tail. This canonicalizes writes to
 * not-yet-existing files inside symlinked directories too.
 */
function realpathPrefix(abs: string): string {
  let existing = abs;
  const tail: string[] = [];
  for (;;) {
    if (fs.existsSync(existing)) break;
    const parent = path.dirname(existing);
    if (parent === existing) break;
    tail.unshift(path.basename(existing));
    existing = parent;
  }
  let resolved: string;
  try {
    resolved = fs.realpathSync(existing);
  } catch {
    resolved = existing;
  }
  return tail.length ? path.join(resolved, ...tail) : resolved;
}

export function resolveTarget(projectRoot: string, rawPath: string): ResolvedTarget {
  const rootReal = realpathPrefix(path.resolve(projectRoot));
  const abs = path.resolve(projectRoot, rawPath);
  const canonical = realpathPrefix(abs);
  const viaSymlink = canonical !== abs;
  const rel = path.relative(rootReal, canonical);
  const outsideProject = rel.startsWith("..") || path.isAbsolute(rel);
  return {
    relative: outsideProject ? canonical.replace(/\\/g, "/") : rel.replace(/\\/g, "/"),
    absolute: canonical,
    outsideProject,
    viaSymlink,
  };
}

/**
 * Candidate path strings to run against protected patterns: the raw
 * request AND the canonical target — a rule must fire if EITHER form
 * matches (belt and braces: pattern authors think in raw paths, attackers
 * in canonical ones).
 */
export function matchCandidates(projectRoot: string, rawPath: string): {
  candidates: string[];
  resolved: ResolvedTarget;
} {
  const resolved = resolveTarget(projectRoot, rawPath);
  const rawRel = path
    .relative(path.resolve(projectRoot), path.resolve(projectRoot, rawPath))
    .replace(/\\/g, "/");
  const set = new Set<string>([rawRel || rawPath.replace(/\\/g, "/"), resolved.relative]);
  return { candidates: [...set], resolved };
}
