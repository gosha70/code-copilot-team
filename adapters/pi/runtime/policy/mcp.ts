/**
 * MCP provider interface + first audited backend (T10.2, FR-018).
 *
 * MCP servers are OPTIONAL, AUDITED backends — never silent (spec P6). This
 * module DECLARES backends, PROBES connectivity, and REPORTS the full FR-018
 * surface (provenance, trust, permissions, tools, connectivity, version,
 * security) so `pi-code`/`/cct:mcp` can render an honest picture and every
 * enablement is auditable.
 *
 * TRANSPORT BOUNDARY (honest): the runtime does NOT own the MCP JSON-RPC
 * transport — live tool invocation (retain/recall/…) flows through Pi's own MCP
 * client when the host provides one. This module is the declaration + audited
 * reporting + trust/connectivity gate; it never itself speaks the wire protocol.
 * Connectivity is probed by PATH presence, NOT by spawning the server (spawning
 * an MCP server with no --version contract would start it, not check it).
 * Hence the capability reports `degraded`, not `enabled`.
 */

import * as fs from "node:fs";
import * as path from "node:path";

// FR-018 modes.
export type McpMode =
  "disabled" | "external-package" | "first-party-bridge" | "remote-gateway";

export interface McpBackend {
  name: string;
  mode: McpMode;
  command: string | null; // external-package / first-party-bridge
  args: string[];
  endpoint: string | null; // remote-gateway
  tools: string[];
  source: string; // provenance: "built-in" | a config path
  permissions: string; // what the backend is allowed to do
}

export interface McpProbe {
  reachable: boolean;
  version: string | null;
  reason: string;
}

export interface McpReport {
  name: string;
  mode: McpMode;
  provenance: string;
  trust: "trusted" | "untrusted" | "n/a";
  permissions: string;
  tools: string[];
  connectivity: string;
  version: string | null;
  security: string;
}

/** The first audited backend: MemKernel, an external-package MCP server. */
export const MEMKERNEL_BACKEND: McpBackend = {
  name: "memkernel",
  mode: "external-package",
  command: "memkernel",
  args: [],
  endpoint: null,
  tools: ["retain", "recall", "get", "forget"],
  source: "built-in",
  permissions:
    "memory tools only (retain/recall/get/forget); no shell, file, or network access granted by CCT",
};

function whichOnPath(
  cmd: string,
  env: Record<string, string | undefined>,
): string | null {
  const raw = env.PATH ?? "";
  for (const dir of raw.split(path.delimiter)) {
    if (!dir) continue;
    const p = path.join(dir, cmd);
    try {
      fs.accessSync(p, fs.constants.X_OK);
      return p;
    } catch {
      /* not here */
    }
  }
  return null;
}

/** Connectivity probe by PATH presence — never spawns the server. */
export function probeBackend(
  backend: McpBackend,
  env: Record<string, string | undefined> = process.env,
): McpProbe {
  if (backend.mode === "disabled") {
    return { reachable: false, version: null, reason: "backend is disabled" };
  }
  if (backend.mode === "remote-gateway") {
    return backend.endpoint
      ? {
          reachable: false,
          version: null,
          reason: `remote gateway ${backend.endpoint} — declared; not probed in-process`,
        }
      : {
          reachable: false,
          version: null,
          reason: "remote gateway with no endpoint declared",
        };
  }
  if (!backend.command) {
    return { reachable: false, version: null, reason: "no command declared" };
  }
  const found = whichOnPath(backend.command, env);
  if (!found) {
    return {
      reachable: false,
      version: null,
      reason: `${backend.command} not on PATH`,
    };
  }
  // Version is intentionally NOT read (would risk starting the server).
  return {
    reachable: true,
    version: null,
    reason: `${backend.command} present on PATH`,
  };
}

/** Build the FR-018 report for a backend, gated by project trust. */
export function mcpReport(
  backend: McpBackend,
  probe: McpProbe,
  trust: "trusted" | "untrusted" | "unknown",
): McpReport {
  const trustField =
    trust === "trusted"
      ? "trusted"
      : trust === "untrusted"
        ? "untrusted"
        : "n/a";
  let security: string;
  if (trust !== "trusted") {
    security =
      "withheld — an MCP backend is enabled only for a positively-trusted project (FR-004a)";
  } else if (probe.reachable) {
    security =
      "audited backend; live invocation flows through Pi's MCP transport (version not read to avoid starting the server)";
  } else {
    security = "declared but not reachable — nothing is invoked";
  }
  return {
    name: backend.name,
    mode: backend.mode,
    provenance: backend.source,
    trust: trustField,
    permissions: backend.permissions,
    tools: backend.tools,
    connectivity: probe.reachable
      ? `reachable — ${probe.reason}`
      : `unreachable — ${probe.reason}`,
    version: probe.version,
    security,
  };
}

/**
 * Resolve the declared MCP backends. The MCP provider is off unless the config
 * opts in (`integrations.mcp.enabled === true`); when on, the built-in MemKernel
 * backend is declared. (Config-declared custom backends are a later addition.)
 */
export function resolveMcpBackends(
  cfg: (path: string) => unknown,
): McpBackend[] {
  if (cfg("integrations.mcp.enabled") !== true) return [];
  return [MEMKERNEL_BACKEND];
}
