/**
 * Code Copilot Team — Pi enforcement runtime (Phase 1: registry + config).
 *
 * Loaded EXPLICITLY by the pi-code launcher via `pi --extension …`.
 * This file must never be referenced from the package manifest's
 * `pi.extensions` and must never live in an auto-discovered
 * `extensions/` directory (spec FR-002 / ADR-1): bare `pi` must not
 * execute any CCT enforcement initialization.
 *
 * Activation contract:
 *   - CCT_RUNTIME=1 must be set by the launcher (defense-in-depth
 *     activation marker — not a security authorization boundary).
 *   - Without the marker the factory logs a notice and registers
 *     nothing, unless CCT_TEST_BOOTSTRAP=1 (supported test/SDK path).
 *
 * Trust contract (spec FR-004a / P9 / P10):
 *   - This runtime OBSERVES Pi's project_trust lifecycle; it defers
 *     decision ownership (returns no decision) so user trust extensions
 *     keep working. Project CCT configuration loads only after
 *     ctx.isProjectTrusted() reports positive trust; unknown or deferred
 *     trust is treated as untrusted (fail closed).
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  explainKey,
  loadLayeredConfig,
  redactedConfig,
} from "./config/loader.ts";
import type { LoadResult } from "./config/loader.ts";
import { BUILTIN_PROFILES } from "./config/profiles.ts";

type TrustState = "trusted" | "untrusted" | "unknown";

interface CapabilityRecord {
  id: string;
  implementation_kind:
    | "native"
    | "cct-first-party"
    | "optional-bridge"
    | "external-platform";
  runtime_status:
    | "enabled"
    | "disabled"
    | "unavailable"
    | "degraded"
    | "misconfigured"
    | "unsupported";
  reason?: string;
}

interface CctRuntimeState {
  profile: string;
  trust: TrustState;
  trustOwner: string | null;
  config: LoadResult | null;
  capabilities: CapabilityRecord[];
  warnings: string[];
}

/** Capability seed. Statuses flip only via acceptance gates (FR-028). */
function seedCapabilities(): CapabilityRecord[] {
  return [
    { id: "skills.shared", implementation_kind: "native", runtime_status: "enabled" },
    { id: "prompts.commands", implementation_kind: "native", runtime_status: "enabled" },
    { id: "config.layered", implementation_kind: "cct-first-party", runtime_status: "enabled" },
    {
      id: "config.trust-gating",
      implementation_kind: "cct-first-party",
      runtime_status: "enabled",
    },
    {
      id: "workflow.sdd",
      implementation_kind: "cct-first-party",
      runtime_status: "disabled",
      reason: "Phase 4 not yet implemented.",
    },
    {
      id: "permissions.engine",
      implementation_kind: "cct-first-party",
      runtime_status: "disabled",
      reason: "Phase 5 not yet implemented.",
    },
    {
      id: "providers.pi",
      implementation_kind: "cct-first-party",
      runtime_status: "disabled",
      reason:
        "Provider plumbing is installed, but the dedicated read-only reviewer execution contract has not passed its acceptance gates.",
    },
    {
      id: "integrations.mcp",
      implementation_kind: "optional-bridge",
      runtime_status: "disabled",
      reason: "Optional; Phase 10.",
    },
    {
      id: "integrations.hosted-platform",
      implementation_kind: "external-platform",
      runtime_status: "unavailable",
      reason: "Anthropic-hosted services are external platforms; never claimed as Pi parity.",
    },
  ];
}

/** Read Pi's own defaultProjectTrust setting for the V2 doctor warning. */
function readDefaultProjectTrust(): string | null {
  try {
    const settingsPath = path.join(os.homedir(), ".pi", "agent", "settings.json");
    if (!fs.existsSync(settingsPath)) return null;
    const settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
    return typeof settings.defaultProjectTrust === "string"
      ? settings.defaultProjectTrust
      : null;
  } catch {
    return null;
  }
}

function loadConfigForState(state: CctRuntimeState, cwd: string): void {
  state.config = loadLayeredConfig({
    globalDir: process.env.CCT_HOME ?? path.join(os.homedir(), ".code-copilot-team"),
    projectDir: cwd,
    trusted: state.trust === "trusted",
    profile: state.profile,
    noProjectConfig: process.env.CCT_NO_PROJECT_CONFIG === "1",
  });
  state.warnings = [...state.config.warnings];

  const dpt = readDefaultProjectTrust();
  if (dpt === "always") {
    state.warnings.push(
      "Pi defaultProjectTrust is 'always': non-interactive sessions trust projects without a saved decision. " +
        "Project CCT configuration may load headlessly (audit origin: defaultProjectTrust).",
    );
  }
}

function doctorReport(state: CctRuntimeState): string {
  const lines: string[] = [];
  lines.push(`pi-code runtime: active (profile=${state.profile})`);
  lines.push(
    `project trust: ${state.trust}` +
      (state.trust !== "trusted" ? " (project CCT config will NOT load)" : "") +
      (state.trustOwner ? ` — decision owned by: ${state.trustOwner}` : ""),
  );
  if (state.config) {
    lines.push(`profile chain: ${state.config.profileChain.join(" -> ") || "<none>"}`);
    lines.push("configuration files:");
    for (const f of state.config.loadedFiles) lines.push(`  loaded:  ${f}`);
    for (const ig of state.config.ignoredFiles) lines.push(`  ignored: ${ig.file} — ${ig.reason}`);
    if (state.config.loadedFiles.length === 0 && state.config.ignoredFiles.length === 0)
      lines.push("  (defaults + profile only)");
    for (const d of state.config.floorDecisions) {
      if (d.action !== "unchanged")
        lines.push(`security floor: ${d.path} [${d.action}] via ${d.layer}`);
    }
    for (const e of state.config.errors) lines.push(`error: ${e}`);
  }
  for (const w of state.warnings) lines.push(`warning: ${w}`);
  lines.push("capabilities:");
  for (const c of state.capabilities) {
    lines.push(
      `  ${c.id}: ${c.implementation_kind}/${c.runtime_status}` + (c.reason ? ` — ${c.reason}` : ""),
    );
  }
  return lines.join("\n");
}

// Factory signature matches Pi's ExtensionAPI contract; typed loosely so
// the runtime carries no build-time dependency (jiti + Node built-ins only).
export default async function (pi: any): Promise<void> {
  const marker = process.env.CCT_RUNTIME === "1";
  const testBootstrap = process.env.CCT_TEST_BOOTSTRAP === "1";

  if (!marker && !testBootstrap) {
    // eslint-disable-next-line no-console
    console.error(
      "[cct] CCT_RUNTIME marker absent — enforcement runtime will not initialize. " +
        "Launch through pi-code for the enforced Code Copilot Team harness.",
    );
    return;
  }

  const state: CctRuntimeState = {
    profile: process.env.CCT_PROFILE ?? "disciplined",
    trust: "unknown",
    trustOwner: null,
    config: null,
    capabilities: seedCapabilities(),
    warnings: [],
  };

  // ── Trust observation (defer ownership: return no decision) ────────
  pi.on?.("project_trust", async (_event: unknown, _ctx: any) => {
    // Deliberately return undefined: the first extension that answers
    // owns the decision (Pi semantics); CCT observes only (P10/V1).
    return undefined;
  });

  pi.on?.("session_start", async (_event: unknown, ctx: any) => {
    try {
      state.trust = ctx?.isProjectTrusted?.() ? "trusted" : "untrusted";
    } catch {
      state.trust = "unknown"; // fail closed: unknown ⇒ untrusted behavior
    }
    loadConfigForState(state, ctx?.cwd ?? process.cwd());
    if (!(state.profile in BUILTIN_PROFILES)) {
      state.warnings.push(`unknown profile '${state.profile}' — using defaults chain only`);
    }
    ctx?.ui?.setStatus?.(
      "cct",
      `CCT ${state.profile} · trust:${state.trust} · sdd:${
        state.config?.resolved.get("workflow.sdd.enabled")?.value === true ? "on" : "off"
      }`,
    );
  });

  const emit = (ctx: any, text: string): void => {
    if (ctx?.hasUI && ctx?.ui?.notify) ctx.ui.notify(text);
    // eslint-disable-next-line no-console
    else console.log(text);
  };

  pi.registerCommand?.("cct:doctor", {
    description: "Code Copilot Team diagnostics (config, trust, capabilities)",
    handler: async (ctx: any) => emit(ctx, doctorReport(state)),
  });

  pi.registerCommand?.("cct:config", {
    description: "Show resolved CCT configuration (redacted)",
    handler: async (ctx: any) => {
      if (!state.config) return emit(ctx, "configuration not loaded yet");
      emit(ctx, JSON.stringify(redactedConfig(state.config), null, 2));
    },
  });

  pi.registerCommand?.("cct:explain", {
    description: "Explain a resolved CCT configuration key: /cct:explain <dotted.key>",
    handler: async (ctx: any, args?: string) => {
      if (!state.config) return emit(ctx, "configuration not loaded yet");
      const key = (typeof args === "string" ? args : "").trim();
      if (!key) return emit(ctx, "usage: /cct:explain <dotted.key>");
      emit(ctx, explainKey(state.config, key));
    },
  });

  pi.registerCommand?.("cct:features", {
    description: "List CCT capability records (JSON)",
    handler: async (ctx: any) => emit(ctx, JSON.stringify(state.capabilities, null, 2)),
  });
}
