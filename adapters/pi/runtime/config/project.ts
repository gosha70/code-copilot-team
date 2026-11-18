/**
 * Where a project's Pi files live (#460).
 *
 * The committed configuration is `<repo>/.cct.toml`, the personal override
 * `<repo>/.cct.local.toml` (never committed) and the `pi-code init` manifest
 * `<repo>/.cct-init.json`; `<repo>/.cct/` stays runtime state. While the
 * fallback lasts (spec FR-9: through the minor release after the one #460
 * ships in), a file absent at its new path but present in the legacy
 * `<repo>/.code-copilot-team/` is read from there. Each file resolves on its
 * own, and the new file wins when both exist. Nothing here moves a file:
 * `pi-code migrate` is the only mover.
 *
 * Mirrors `project_file` in adapters/pi/bin/pi-code rule for rule.
 */

import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

export type ProjectFileKind = "config" | "local" | "manifest";

/** New path, relative to the project root. */
export const PROJECT_FILES: Record<ProjectFileKind, string> = {
  config: ".cct.toml",
  local: ".cct.local.toml",
  manifest: ".cct-init.json",
};

/** Legacy directory, read only while the fallback lasts (FR-9). */
export const LEGACY_PROJECT_DIR = ".code-copilot-team";

/** Legacy file name inside LEGACY_PROJECT_DIR. */
export const LEGACY_PROJECT_FILES: Record<ProjectFileKind, string> = {
  config: "config.toml",
  local: "config.local.toml",
  manifest: ".cct-init.json",
};

const KINDS: ProjectFileKind[] = ["config", "local", "manifest"];

/** True if the entry exists, a dangling symlink included. */
function present(p: string): boolean {
  try {
    fs.lstatSync(p);
    return true;
  } catch {
    return false;
  }
}

export function newProjectPath(projectDir: string, kind: ProjectFileKind): string {
  return path.join(projectDir, PROJECT_FILES[kind]);
}

export function legacyProjectPath(projectDir: string, kind: ProjectFileKind): string {
  return path.join(projectDir, LEGACY_PROJECT_DIR, LEGACY_PROJECT_FILES[kind]);
}

/**
 * The path to read `kind` from: the new file when it exists, else the legacy
 * file when only it exists (while the fallback lasts), else the new path.
 */
export function projectFile(projectDir: string, kind: ProjectFileKind): string {
  const fresh = newProjectPath(projectDir, kind);
  if (present(fresh)) return fresh;
  const legacy = legacyProjectPath(projectDir, kind);
  if (present(legacy)) return legacy;
  return fresh;
}

export interface ProjectFileState {
  kind: ProjectFileKind;
  /** Where the file is read from. */
  path: string;
  source: "new" | "legacy" | "absent";
  /** The legacy file exists beside a new one (it is ignored). */
  legacyShadowed: boolean;
}

export function projectFileStates(projectDir: string): ProjectFileState[] {
  return KINDS.map((kind) => {
    const fresh = newProjectPath(projectDir, kind);
    const legacy = legacyProjectPath(projectDir, kind);
    const hasNew = present(fresh);
    const hasLegacy = present(legacy);
    return {
      kind,
      path: hasNew || !hasLegacy ? fresh : legacy,
      source: hasNew ? "new" : hasLegacy ? "legacy" : "absent",
      legacyShadowed: hasNew && hasLegacy,
    };
  });
}

/** True when git reports `rel` as ignored in `projectDir`'s work tree. */
function gitIgnored(projectDir: string, rel: string): boolean {
  const r = spawnSync("git", ["-C", projectDir, "check-ignore", "-q", "--", rel], { stdio: "ignore" });
  return r.status === 0;
}

function inGitWorkTree(projectDir: string): boolean {
  const r = spawnSync("git", ["-C", projectDir, "rev-parse", "--is-inside-work-tree"], { encoding: "utf8" });
  return r.status === 0 && r.stdout.trim() === "true";
}

/**
 * `pi-code doctor`'s project findings (spec FR-7): one line per legacy file
 * still present, and the ignore checks in a git work tree.
 */
export function projectWarnings(projectDir: string): string[] {
  const out: string[] = [];
  for (const s of projectFileStates(projectDir)) {
    const legacyRel = path.join(LEGACY_PROJECT_DIR, LEGACY_PROJECT_FILES[s.kind]);
    if (s.source === "legacy") {
      out.push(`${legacyRel} is read from the legacy location — run pi-code migrate to move it to ${PROJECT_FILES[s.kind]}`);
    } else if (s.legacyShadowed) {
      out.push(`${legacyRel} is ignored because ${PROJECT_FILES[s.kind]} exists — compare them and remove the legacy file`);
    }
  }
  if (inGitWorkTree(projectDir)) {
    for (const kind of ["config", "manifest"] as ProjectFileKind[]) {
      const rel = PROJECT_FILES[kind];
      if (present(path.join(projectDir, rel)) && gitIgnored(projectDir, rel)) {
        out.push(`${rel} is ignored by git — the team would not get it on commit (see git check-ignore -v ${rel})`);
      }
    }
    const local = PROJECT_FILES.local;
    if (present(path.join(projectDir, local)) && !gitIgnored(projectDir, local)) {
      out.push(`${local} is not ignored by git — personal settings could be committed`);
    }
  }
  return out;
}
