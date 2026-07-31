/**
 * Claude `.claude/agents/*.md` frontmatter -> neutral AgentManifest importer
 * (T7.1, FR-011). Pure converter, same discipline as the T5.2 permissions
 * importer (policy/import-permissions.ts):
 *
 *   - Input is already-read frontmatter text; NO filesystem, NO spawn.
 *   - Claude frontmatter carries only name/description/tools/model. The four
 *     FR-011 fields it cannot express (thinking/permissions/skills/context) are
 *     defaulted to neutral sentinels and reported in `notSourced` — never
 *     fabricated.
 *   - Nothing with no faithful target is silently dropped: the Claude `Agent`
 *     tool (delegation) has no Pi tool equivalent and is reported as a warning,
 *     not imported as a Pi tool.
 *   - The model tier ("sonnet"/"opus") is a CLAUDE tier; it is carried VERBATIM
 *     and never remapped to a Pi model (there is no verified runner surface to
 *     apply it — T7.2). See specs/pi-harness-adoption/design-t71-agent-manifest.md.
 *
 * Reading the .md files off disk and wiring manifests into the runtime is a
 * later task (T7.2); this module delivers the converter + fixtures/tests only.
 */

import { MANIFEST_SENTINELS, validateManifest } from "./manifest.ts";
import type { AgentManifest, ThinkingLevel } from "./manifest.ts";

/** One Claude agent source: its filename stem + its raw frontmatter text. */
export interface ClaudeAgentSource {
  /** Fallback name (filename stem) if frontmatter omits `name`. */
  file: string;
  /** The YAML frontmatter body (with or without the surrounding `---`). */
  frontmatter: string;
}

export interface AgentImportWarning {
  agent: string;
  field: string;
  reason: string;
}

/** Per-manifest record of which fields were defaulted because Claude lacks them. */
export interface AgentNotSourced {
  agent: string;
  fields: string[];
}

export interface AgentImportResult {
  manifests: AgentManifest[];
  warnings: AgentImportWarning[];
  notSourced: AgentNotSourced[];
}

/** The Claude tool that means "may delegate"; it has no Pi tool equivalent. */
const CLAUDE_DELEGATION_TOOL = "agent";

/** Extract the frontmatter body, tolerating input with or without `---` fences. */
function stripFences(raw: string): string {
  const t = raw.replace(/\r\n/g, "\n").trim();
  const fenced = /^---\n([\s\S]*?)\n---\s*$/.exec(t);
  if (fenced) return fenced[1];
  // Or a leading fence with trailing document body after the closing fence.
  const leading = /^---\n([\s\S]*?)\n---\n?/.exec(t);
  if (leading) return leading[1];
  return t;
}

/**
 * Minimal flat-scalar YAML read for the four Claude frontmatter keys. Splits on
 * the FIRST colon of a column-0 line; only recognizes known keys, so a colon
 * inside a description value does not confuse parsing.
 */
function readFrontmatter(body: string): Record<string, string> {
  const out: Record<string, string> = {};
  const KNOWN = new Set(["name", "description", "tools", "model"]);
  for (const line of body.split("\n")) {
    if (!line || /^\s/.test(line)) continue; // skip blanks + nested/continuation
    const idx = line.indexOf(":");
    if (idx < 0) continue;
    const key = line.slice(0, idx).trim().toLowerCase();
    if (!KNOWN.has(key)) continue;
    let value = line.slice(idx + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

function importOne(
  src: ClaudeAgentSource,
  warnings: AgentImportWarning[],
): { manifest: AgentManifest; notSourcedFields: string[] } {
  const fm = readFrontmatter(stripFences(src.frontmatter));
  const name = (fm.name || src.file || "").trim();
  const notSourcedFields: string[] = [];

  // tools: comma-separated; lowercase + trim. The Claude `Agent` delegation
  // tool has no Pi equivalent -> flagged, not imported as a Pi tool.
  const tools: string[] = [];
  for (const rawTool of (fm.tools || "").split(",")) {
    const tool = rawTool.trim().toLowerCase();
    if (!tool) continue;
    if (tool === CLAUDE_DELEGATION_TOOL) {
      warnings.push({
        agent: name,
        field: "tools",
        reason:
          "declares the Claude 'Agent' delegation tool; no Pi tool equivalent — recorded, not imported as a Pi tool",
      });
      continue;
    }
    if (!tools.includes(tool)) tools.push(tool);
  }

  // model: carried verbatim (a Claude tier), never remapped. Absent -> sentinel.
  let model = (fm.model || "").trim();
  if (!model) {
    model = MANIFEST_SENTINELS.model;
    notSourcedFields.push("model");
  }

  // Fields Claude frontmatter cannot express -> neutral sentinels + flagged.
  for (const f of ["thinking", "permissions", "skills", "context"]) {
    notSourcedFields.push(f);
  }

  const manifest: AgentManifest = {
    name,
    description: (fm.description || "").trim(),
    model,
    thinking: MANIFEST_SENTINELS.thinking as ThinkingLevel,
    tools,
    skills: [],
    context: [],
    permissions: MANIFEST_SENTINELS.permissions,
    source: "claude-import",
    declaredNotSourced: notSourcedFields,
  };

  return { manifest, notSourcedFields };
}

/**
 * Convert a set of Claude agent frontmatter sources into neutral manifests.
 * Validation failures (missing/duplicate name, bad shape) are reported as
 * warnings and the manifest is skipped — nothing is silently approximated.
 */
export function importClaudeAgents(
  sources: ClaudeAgentSource[],
): AgentImportResult {
  const manifests: AgentManifest[] = [];
  const warnings: AgentImportWarning[] = [];
  const notSourced: AgentNotSourced[] = [];
  const seen = new Set<string>();

  for (const src of sources) {
    const { manifest, notSourcedFields } = importOne(src, warnings);
    const { valid, errors } = validateManifest(manifest, seen);
    if (!valid) {
      for (const e of errors)
        warnings.push({
          agent: manifest.name || src.file,
          field: "manifest",
          reason: e,
        });
      continue;
    }
    seen.add(manifest.name);
    manifests.push(manifest);
    notSourced.push({ agent: manifest.name, fields: notSourcedFields });
  }

  return { manifests, warnings, notSourced };
}
