/**
 * Memory promotion/deletion + wiki-first retrieval + sensitive-memory controls
 * (T9.2, FR-017). Complements the session checkpoint (T9.1): checkpoints are
 * transient per-session state; memories are durable, explicitly-promoted facts
 * with provenance.
 *
 * CCT-NATIVE STORE is the active backend: `.cct/memory.json`. The MemKernel
 * adapter is DETECTION + a self-guarding contract only — MemKernel is an MCP
 * server (memkernel.mcp.server), so real delegation requires the Pi MCP provider
 * (integrations.mcp, T10.2), which is not yet available. Until then the adapter
 * reports pending-MCP and the built-in store is authoritative. Either way the
 * sensitive-memory control is fail-closed: a fact carrying a secret is REFUSED,
 * never stored and never handed to an external server.
 */

import * as fs from "node:fs";
import * as path from "node:path";

export const MEMORY_REL = path.join(".cct", "memory.json");

export type MemoryType = "user" | "feedback" | "project" | "reference";
const MEMORY_TYPES: MemoryType[] = ["user", "feedback", "project", "reference"];

export interface MemoryProvenance {
  phase: string | null;
  featureId: string | null;
  at: string; // ISO
}

export interface MemoryRecord {
  id: string;
  type: MemoryType;
  fact: string;
  provenance: MemoryProvenance;
}

export interface PromoteResult {
  ok: boolean;
  record?: MemoryRecord;
  refused?: boolean; // true when a sensitive-control refusal
  reason: string;
}

// Strong secret-VALUE signatures — refuse a memory that carries any of these.
// (Key WORDS like "password" alone are fine; actual secret VALUES are not.)
const SECRET_PATTERNS: RegExp[] = [
  /\bsk-[A-Za-z0-9]{16,}\b/, // OpenAI-style
  /\bAKIA[0-9A-Z]{16}\b/, // AWS access key id
  /\bgh[pousr]_[A-Za-z0-9]{20,}\b/, // GitHub tokens
  /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/, // JWT
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/, // PEM private key
  /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/, // Slack tokens
  /(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{8,}/i, // key=value secret
];

export function containsSecret(text: string): boolean {
  return SECRET_PATTERNS.some((re) => re.test(text));
}

function loadRaw(projectRoot: string): MemoryRecord[] {
  try {
    const parsed = JSON.parse(
      fs.readFileSync(path.join(projectRoot, MEMORY_REL), "utf8"),
    );
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (r): r is MemoryRecord =>
        r &&
        typeof r.id === "string" &&
        typeof r.fact === "string" &&
        MEMORY_TYPES.includes(r.type),
    );
  } catch {
    return []; // missing or corrupt -> empty (never throws)
  }
}

function saveRaw(projectRoot: string, records: MemoryRecord[]): void {
  const file = path.join(projectRoot, MEMORY_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(records, null, 2) + "\n");
}

export function listMemories(projectRoot: string): MemoryRecord[] {
  return loadRaw(projectRoot);
}

/** Deterministic id from the fact + count (no Math.random / Date.now needed). */
function memoryId(fact: string, ordinal: number): string {
  const slug = fact
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
  return `${slug || "mem"}-${ordinal}`;
}

export function promoteMemory(
  projectRoot: string,
  fields: { type: MemoryType; fact: string; provenance: MemoryProvenance },
): PromoteResult {
  const fact = fields.fact.trim();
  if (!fact) return { ok: false, reason: "empty fact — nothing to remember" };
  // Sensitive-memory control (fail-closed): never persist a secret.
  if (containsSecret(fact)) {
    return {
      ok: false,
      refused: true,
      reason:
        "refused: the fact appears to contain a secret value — memories must not store credentials",
    };
  }
  const records = loadRaw(projectRoot);
  const record: MemoryRecord = {
    id: memoryId(fact, records.length + 1),
    type: fields.type,
    fact,
    provenance: fields.provenance,
  };
  records.push(record);
  saveRaw(projectRoot, records);
  return { ok: true, record, reason: `remembered as ${record.id}` };
}

export function deleteMemory(projectRoot: string, id: string): boolean {
  const records = loadRaw(projectRoot);
  const next = records.filter((r) => r.id !== id);
  if (next.length === records.length) return false;
  saveRaw(projectRoot, next);
  return true;
}

export interface RecallHit {
  source: "wiki" | "memory";
  ref: string; // wiki page path, or memory id
  text: string;
}

/**
 * Wiki-first retrieval (the wiki-first-query convention): consult
 * `<project>/knowledge/wiki/index.md` first, THEN the promoted memories. Wiki
 * hits are returned before memory hits so the canonical project layer wins.
 * Case-insensitive substring match — deterministic, no embeddings (that's the
 * MemKernel/MCP path, pending T10.2).
 */
export function recall(projectRoot: string, query: string): RecallHit[] {
  const q = query.trim().toLowerCase();
  const hits: RecallHit[] = [];
  if (!q) return hits;

  const wikiIndex = path.join(projectRoot, "knowledge", "wiki", "index.md");
  try {
    const text = fs.readFileSync(wikiIndex, "utf8");
    for (const line of text.split("\n")) {
      if (line.toLowerCase().includes(q)) {
        hits.push({
          source: "wiki",
          ref: "knowledge/wiki/index.md",
          text: line.trim(),
        });
      }
    }
  } catch {
    /* no wiki -> memory only */
  }

  for (const r of loadRaw(projectRoot)) {
    if (r.fact.toLowerCase().includes(q)) {
      hits.push({ source: "memory", ref: r.id, text: r.fact });
    }
  }
  return hits;
}

export interface MemKernelStatus {
  available: boolean;
  transport: "mcp";
  reason: string;
}

/**
 * MemKernel adapter (self-guarding). MemKernel is exclusively an MCP server, so
 * delegation needs the Pi MCP provider (T10.2). This reports availability
 * honestly; the built-in store stays authoritative until MCP lands. Callers must
 * still pass facts through `containsSecret` — the self-guard is transport-
 * independent: a secret is never handed to an external memory server.
 */
export function memkernelStatus(
  env: Record<string, string | undefined> = process.env,
): MemKernelStatus {
  const declaredEndpoint = env.MEMKERNEL_ENDPOINT || env.MEMKERNEL_PROJECT_ID;
  return {
    available: false,
    transport: "mcp",
    reason: declaredEndpoint
      ? "MemKernel declared, but delegation requires the Pi MCP provider (integrations.mcp, T10.2) — using the built-in store"
      : "MemKernel is an MCP server; the Pi MCP provider (T10.2) is not yet available — using the built-in store",
  };
}
