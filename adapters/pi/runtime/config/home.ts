/**
 * The one place in the Pi runtime that knows where CCT keeps a user's files
 * (#411).
 *
 * The home is `${CCT_HOME:-~/.cct}`. Through the 2.1.x line an entry that is
 * absent from the home but present in the legacy home `~/.code-copilot-team`
 * is read from there (a read-only fallback); the first 2.2 change removes the
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
/** Read-only fallback through 2.1.x; removed in 2.2. */
export const HOME_LEGACY_REL = ".code-copilot-team";

/** The home directory; it may not exist yet. */
export function cctHome(env: NodeJS.ProcessEnv = process.env): string {
  const override = env[ENV_HOME];
  return override && override.length > 0 ? override : path.join(os.homedir(), HOME_DEFAULT_REL);
}

export function legacyHome(): string {
  return path.join(os.homedir(), HOME_LEGACY_REL);
}

/**
 * The path to read `relative` from, or to create it at under the home.
 * CCT_HOME set: that directory, no fallback. Otherwise the home when the
 * entry exists there, the legacy home when it exists only there, and the
 * home as the place to create it.
 */
export function cctHomePath(relative: string, env: NodeJS.ProcessEnv = process.env): string {
  const fresh = path.join(cctHome(env), relative);
  if (env[ENV_HOME] && env[ENV_HOME]!.length > 0) return fresh;
  if (fs.existsSync(fresh)) return fresh;
  const legacy = path.join(legacyHome(), relative);
  if (fs.existsSync(legacy)) return legacy;
  return fresh;
}

/** Entries still served from the legacy home (absent from the home). */
export function legacyHits(env: NodeJS.ProcessEnv = process.env): string[] {
  if (env[ENV_HOME] && env[ENV_HOME]!.length > 0) return [];
  const legacy = legacyHome();
  if (!fs.existsSync(legacy) || !fs.statSync(legacy).isDirectory()) return [];
  const home = cctHome(env);
  return fs
    .readdirSync(legacy)
    .filter((name) => !fs.existsSync(path.join(home, name)))
    .sort();
}
