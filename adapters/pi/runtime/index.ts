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
import {
  checkCommand,
  checkPath,
  checkTool,
  rulesFromConfig,
} from "./policy/permissions.ts";
import type { PermissionRuleSet, PermissionVerdict } from "./policy/permissions.ts";
import { matchCandidates } from "./policy/protected.ts";
import { audit } from "./policy/audit.ts";
import { defaultProjectTrustFinding, trustDrift } from "./config/trust.ts";
import {
  buildWriteGate,
  isValidPhase,
  loadState,
  transition,
} from "./workflow/phases.ts";
import type { WorkflowState } from "./workflow/phases.ts";
import { isSpecPath, validateSpecDir } from "./workflow/sdd.ts";

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
  cwd: string;
  workflow: WorkflowState;
  rules: PermissionRuleSet | null;
  interactive: boolean;
  /** Trust value the current config was resolved with (FR-004a). */
  trustLoadedWith: TrustState | null;
  /** Set when trust changed after config load; requires a restart. */
  restartRequired: boolean;
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
      runtime_status: "enabled",
    },
    {
      id: "workflow.phases",
      implementation_kind: "cct-first-party",
      runtime_status: "enabled",
    },
    {
      id: "permissions.engine",
      implementation_kind: "cct-first-party",
      runtime_status: "enabled",
    },
    {
      id: "permissions.protected-paths",
      implementation_kind: "cct-first-party",
      runtime_status: "enabled",
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
  state.trustLoadedWith = state.trust;

  const finding = defaultProjectTrustFinding(readDefaultProjectTrust());
  if (finding) {
    state.warnings.push(finding.warning);
    // Warning alone is not enough: a headless session that was trusted
    // without a saved decision must leave a durable record (V2).
    audit({ mode: state.interactive ? "tui" : "headless", actor: "session_start", ...finding.audit });
  }
}

/**
 * Compare live trust against what the config was loaded with. Config is never
 * re-resolved mid-session: permissions and gates already made decisions using
 * the old value, so the honest response is to report and require a restart.
 */
function noteTrustDrift(state: CctRuntimeState, current: TrustState): void {
  // Falsy check, not `=== null`: every TrustState is a non-empty string, so
  // this also covers an uninitialized field rather than reporting drift from it.
  if (state.restartRequired || !state.trustLoadedWith) return;
  const drift = trustDrift(state.trustLoadedWith, current);
  if (!drift) return;
  state.restartRequired = true;
  state.trust = current;
  state.warnings.push(drift.message);
  audit({
    mode: state.interactive ? "tui" : "headless",
    actor: "project_trust",
    decision: "restart-required",
    rule: "trust.changed-mid-session",
    subject: `${drift.from}->${drift.to}`,
    origin: "trust",
  });
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
    cwd: process.cwd(),
    workflow: { phase: "research", featureId: null, enteredAt: null, history: [] },
    rules: null,
    interactive: false,
    trustLoadedWith: null,
    restartRequired: false,
  };

  const cfg = (dotted: string): unknown => state.config?.resolved.get(dotted)?.value;

  const refreshRules = (): void => {
    state.rules = state.config ? rulesFromConfig(cfg, state.interactive) : null;
  };

  // ── Trust observation (defer ownership: return no decision) ────────
  pi.on?.("project_trust", async (_event: unknown, ctx: any) => {
    // Deliberately return undefined: the first extension that answers
    // owns the decision (Pi semantics); CCT observes only (P10/V1).
    try {
      const current: TrustState = ctx?.isProjectTrusted?.() ? "trusted" : "untrusted";
      noteTrustDrift(state, current);
      updateStatus(ctx);
    } catch {
      /* observation only — never block the trust decision */
    }
    return undefined;
  });

  pi.on?.("session_start", async (_event: unknown, ctx: any) => {
    try {
      state.trust = ctx?.isProjectTrusted?.() ? "trusted" : "untrusted";
    } catch {
      state.trust = "unknown"; // fail closed: unknown ⇒ untrusted behavior
    }
    state.cwd = ctx?.cwd ?? process.cwd();
    state.interactive = ctx?.hasUI === true && ctx?.mode === "tui";
    loadConfigForState(state, state.cwd);
    state.workflow = loadState(state.cwd);
    refreshRules();
    if (!(state.profile in BUILTIN_PROFILES)) {
      state.warnings.push(`unknown profile '${state.profile}' — using defaults chain only`);
    }
    updateStatus(ctx);
  });

  const updateStatus = (ctx: any): void => {
    ctx?.ui?.setStatus?.(
      "cct",
      `CCT ${state.profile} · ${state.workflow.phase}` +
        (state.workflow.featureId ? `:${state.workflow.featureId}` : "") +
        ` · trust:${state.trust} · sdd:${cfg("workflow.sdd.enabled") === true ? "on" : "off"}`,
    );
  };

  // ── Enforcement: tool_call interception (FR-007/FR-009, Phase 4–5 core) ──
  const WRITE_TOOLS = new Set(["edit", "write"]);
  const EXEC_TOOLS = new Set(["bash"]);

  const block = (origin: string, actor: string, v: PermissionVerdict, subject: string) => {
    audit({
      mode: state.interactive ? "tui" : "headless",
      actor,
      decision: v.decision === "ask" ? `ask->${v.effective}` : v.effective,
      rule: v.rule,
      subject,
      origin,
    });
    return { block: true, reason: `[cct] ${v.reason}` };
  };

  pi.on?.("tool_call", async (event: any, ctx: any) => {
    if (!state.rules) return undefined; // config not loaded → Phase 0 behavior
    const toolName: string = String(event?.toolName ?? event?.name ?? "");
    const args: any = event?.input ?? event?.args ?? {};

    // 1) Tool allow/deny (profile allowlists, e.g. peer-reviewer read-only).
    const toolVerdict = checkTool(state.rules, toolName);
    if (toolVerdict.effective !== "allow") {
      return block("permissions", `tool_call:${toolName}`, toolVerdict, toolName);
    }

    // 2) Path rules for write tools (protected paths, canonicalized).
    if (WRITE_TOOLS.has(toolName)) {
      const rawPath: string = String(args?.path ?? args?.file_path ?? args?.filePath ?? "");
      if (rawPath) {
        const { candidates } = matchCandidates(state.cwd, rawPath);
        for (const candidate of candidates) {
          const v = checkPath(state.rules, candidate);
          if (v.effective === "deny" || v.effective === "fail") {
            return block("protected-path", `tool_call:${toolName}`, v, rawPath);
          }
          if (v.decision === "ask" && state.interactive && ctx?.ui?.confirm) {
            const ok = await ctx.ui.confirm(`[cct] Allow ${toolName} on '${rawPath}'?`, {
              detail: v.reason,
            });
            if (!ok) return block("protected-path", `tool_call:${toolName}`, v, rawPath);
          }
        }

        // 3) SDD Build gate: writes outside specs/ blocked until artifacts hold.
        const gate = buildWriteGate(state.cwd, state.workflow, cfg("workflow.sdd.enabled") === true);
        if (gate && !isSpecPath(rawPath)) {
          const v: PermissionVerdict = {
            decision: "deny",
            effective: "deny",
            rule: "sdd.build-gate",
            reason:
              `Build is gated for feature '${gate.featureId ?? "<none>"}' — ` +
              gate.reasons.join("; ") +
              ". Complete the spec artifacts (or /cct:phase plan) to proceed.",
          };
          return block("sdd-gate", `tool_call:${toolName}`, v, rawPath);
        }
      }
    }

    // 4) Command rules for execution tools (chained-command aware).
    if (EXEC_TOOLS.has(toolName)) {
      const command: string = String(args?.command ?? args?.cmd ?? "");
      if (command) {
        const v = checkCommand(state.rules, command);
        if (v.effective === "deny" || v.effective === "fail") {
          return block("permissions", `tool_call:${toolName}`, v, command);
        }
        if (v.decision === "ask" && state.interactive && ctx?.ui?.confirm) {
          const ok = await ctx.ui.confirm(`[cct] Allow command?`, { detail: command });
          if (!ok) return block("permissions", `tool_call:${toolName}`, v, command);
        }
        const gate = buildWriteGate(state.cwd, state.workflow, cfg("workflow.sdd.enabled") === true);
        if (gate) {
          const v2: PermissionVerdict = {
            decision: "deny",
            effective: "deny",
            rule: "sdd.build-gate",
            reason:
              `Build is gated for feature '${gate.featureId ?? "<none>"}' — ` +
              gate.reasons.join("; "),
          };
          return block("sdd-gate", `tool_call:${toolName}`, v2, command);
        }
      }
    }

    return undefined; // allow
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

  pi.registerCommand?.("cct:phase", {
    description: "Show or change workflow phase: /cct:phase [research|plan|build|review] [feature-id]",
    handler: async (ctx: any, args?: string) => {
      const parts = (typeof args === "string" ? args : "").trim().split(/\s+/).filter(Boolean);
      if (parts.length === 0) {
        return emit(
          ctx,
          `phase: ${state.workflow.phase}` +
            (state.workflow.featureId ? ` (feature: ${state.workflow.featureId})` : ""),
        );
      }
      const target = parts[0].toLowerCase();
      if (!isValidPhase(target)) {
        return emit(ctx, `unknown phase '${parts[0]}' (research|plan|build|review)`);
      }
      const featureId = parts[1] ?? null;
      const result = transition(
        state.cwd,
        state.workflow,
        target,
        featureId,
        new Date().toISOString(),
      );
      if (!result.ok) {
        audit({
          mode: state.interactive ? "tui" : "headless",
          actor: "cct:phase",
          decision: "deny",
          rule: "sdd.entry-gate",
          subject: `${target}:${featureId ?? state.workflow.featureId ?? "<none>"}`,
          origin: "sdd-gate",
        });
        return emit(ctx, `phase transition to '${target}' BLOCKED:\n  - ${result.reasons.join("\n  - ")}`);
      }
      state.workflow = result.state;
      updateStatus(ctx);
      emit(
        ctx,
        `phase: ${state.workflow.phase}` +
          (state.workflow.featureId ? ` (feature: ${state.workflow.featureId})` : "") +
          (result.gate ? ` — SDD gate: PASS (${result.gate.specMode})` : ""),
      );
    },
  });

  pi.registerCommand?.("cct:status", {
    description: "CCT workflow + gate status for the active feature",
    handler: async (ctx: any) => {
      const lines = [
        `phase: ${state.workflow.phase}`,
        `feature: ${state.workflow.featureId ?? "<none>"}`,
        `profile: ${state.profile}`,
        `trust: ${state.trust}`,
        `sdd: ${cfg("workflow.sdd.enabled") === true ? "enabled" : "disabled"}`,
      ];
      if (state.workflow.featureId) {
        const gate = validateSpecDir(path.join(state.cwd, "specs", state.workflow.featureId));
        lines.push(`sdd gate: ${gate.pass ? "PASS" : "FAIL"} (spec_mode=${gate.specMode ?? "?"})`);
        for (const r of gate.reasons) lines.push(`  - ${r}`);
      }
      emit(ctx, lines.join("\n"));
    },
  });
}
