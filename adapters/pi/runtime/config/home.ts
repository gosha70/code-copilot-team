/**
 * The one place in the Pi runtime that knows where CCT keeps a user's files
 * (#411).
 *
 * The home is `${CCT_HOME:-~/.cct}`. Through the 2.1.x line a top-level entry
 * that is absent from the home but present in the legacy home
 * `~/.code-copilot-team` is served from there, reads and writes alike, so a
 * directory is never split between the two; the first 2.2 change removes the
 * fallback. Nothing here moves a file: `cct home migrate` is the only mover.
 *
 * Mirrors scripts/lib/cct-home.sh (bash) and
 * scripts/session_analytics/home.py (Python) rule for rule.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export const ENV_HOME = "CCT_HOME";
export const HOME_DEFAULT_REL = ".cct";
/** Served as a fallback through 2.1.x; removed in 2.2. */
export const HOME_LEGACY_REL = ".code-copilot-team";
/** An entry `cct home migrate` set aside; reported there, never listed here. */
export const MIGRATE_ASIDE_PREFIX = ".cct-migrate-aside.";

/** The home directory; it may not exist yet. */
export function cctHome(env: NodeJS.ProcessEnv = process.env): string {
  const override = env[ENV_HOME];
  return override && override.length > 0 ? override : path.join(os.homedir(), HOME_DEFAULT_REL);
}

/** True if the entry exists, a dangling symlink included (no final-link follow). */
function present(p: string): boolean {
  try {
    fs.lstatSync(p);
    return true;
  } catch {
    return false;
  }
}

export function legacyHome(): string {
  return path.join(os.homedir(), HOME_LEGACY_REL);
}

/**
 * The path to read, write or create `relative` at.
 * CCT_HOME set: that directory, no fallback. Otherwise the TOP-LEVEL entry
 * (the first segment of `relative`) decides: the legacy home when that entry
 * exists only there, else the home. `pi/audit.log` therefore goes wherever
 * `pi/` lives and never splits the directory. Presence does not follow a
 * final symlink: a dangling home entry still selects the home rather than
 * silently reviving a stale legacy copy.
 */
export function cctHomePath(relative: string, env: NodeJS.ProcessEnv = process.env): string {
  const entry = relative.split(/[\\/]/)[0];
  const overridden = Boolean(env[ENV_HOME] && env[ENV_HOME]!.length > 0);
  if (!overridden && !present(path.join(cctHome(env), entry)) && present(path.join(legacyHome(), entry))) {
    return path.join(legacyHome(), relative);
  }
  return path.join(cctHome(env), relative);
}

/** Entries still served from the legacy home (absent from the home). */
export function legacyHits(env: NodeJS.ProcessEnv = process.env): string[] {
  if (env[ENV_HOME] && env[ENV_HOME]!.length > 0) return [];
  const legacy = legacyHome();
  if (!fs.existsSync(legacy) || !fs.statSync(legacy).isDirectory()) return [];
  const home = cctHome(env);
  return fs
    .readdirSync(legacy)
    .filter((name) => !name.startsWith(MIGRATE_ASIDE_PREFIX) && !present(path.join(home, name)))
    .sort();
}
