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
  checkExecPolicy,
  checkPath,
  checkTool,
  rulesFromConfig,
} from "./policy/permissions.ts";
import type { PermissionRuleSet, PermissionVerdict } from "./policy/permissions.ts";
import { matchCandidates } from "./policy/protected.ts";
import { audit, resolveAuditMode } from "./policy/audit.ts";
import { hookMappingReport, translateToolCall } from "./hooks/events.ts";
import { dispatchHooks, resolveHookScripts, resolveHookScriptsDir } from "./hooks/adapter.ts";
import { defaultProjectTrustFinding, trustDrift } from "./config/trust.ts";
import { seedCapabilities } from "./capabilities.ts";
import { loadAlwaysContext } from "./context.ts";
import type { AlwaysContext } from "./context.ts";
import type { CapabilityRecord } from "./capabilities.ts";
import {
  buildWriteGate,
  isValidPhase,
  loadState,
  resolvePhasePolicy,
  transition,
} from "./workflow/phases.ts";
import type { WorkflowState } from "./workflow/phases.ts";
import {
  loadCheckpoint,
  recoveryDigest,
  tryWriteCheckpoint,
} from "./workflow/checkpoint.ts";
import {
  promoteMemory,
  deleteMemory,
  listMemories,
  recall,
  memkernelStatus,
} from "./workflow/memory.ts";
import type { MemoryType } from "./workflow/memory.ts";
import { detectSandbox, sandboxGate } from "./policy/sandbox.ts";
import type {
  SandboxDetection,
  SandboxGateResult,
} from "./policy/sandbox.ts";
import {
  midReviewWarning,
  peerReviewDisabled,
  resolveReviewRunner,
  resolveTargetRef,
  reviewGate,
  sessionPeerProvider,
  sessionReviewScope,
  submitReviewRound,
  writeDecision,
} from "./workflow/review.ts";
import {
  resolveVerifyRunner,
  runVerify,
  verifyGate,
  verifyWarning,
} from "./workflow/verify.ts";
import { isSpecPath, validateSpecDir } from "./workflow/sdd.ts";
import {
  RISK_CATEGORIES,
  loadClassification,
  overrideClassification,
  resolveClassification,
} from "./workflow/classify.ts";
import type { RiskCategory } from "./workflow/classify.ts";
import type { SpecMode } from "./workflow/sdd.ts";

type TrustState = "trusted" | "untrusted" | "unknown";

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
  /** Always-on context bundle, loaded at session start (T2.3). */
  context: AlwaysContext | null;
  /** Whether the bundle was actually handed to Pi (API available). */
  contextInjected: boolean;
  sandbox: { gate: SandboxGateResult; detection: SandboxDetection } | null;
  /** Directory of reusable shell hooks, or null when none (T5.1/FR-010). */
  hookScriptsDir: string | null;
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
    audit({ mode: resolveAuditMode(state.interactive), actor: "session_start", ...finding.audit });
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
    mode: resolveAuditMode(state.interactive),
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
  if (state.context && state.context.text) {
    lines.push(
      `always-on context: ${(state.context.bytes / 1024).toFixed(1)} KiB from ` +
        `${state.context.source} (${state.contextInjected ? "injected" : "NOT injected"})`,
    );
  } else {
    lines.push("always-on context: <no bundle installed>");
  }
  if (state.config) {
    const resolved = state.config;
    const policy = resolvePhasePolicy(
      (k) => resolved.resolved.get(k)?.value,
      state.workflow.phase,
    );
    lines.push(
      `phase policy [${policy.phase}]: model=${policy.model} thinking=${policy.thinking} ` +
        `permissions=${policy.permissions} (resolved, reported only — not enforced)`,
    );
    lines.push(`  tools: ${policy.tools.join(", ") || "<inherit>"}`);
    const denyNet = resolved.resolved.get("security.deny_network")?.value === true;
    const allowPkg =
      resolved.resolved.get("security.allow_package_install")?.value !== false;
    const failClosed =
      resolved.resolved.get("security.fail_closed")?.value !== false;
    lines.push(
      `exec policy: package_install=${allowPkg ? "allowed" : "DENIED"} ` +
        `network=${denyNet ? "DENIED (command-name denylist, not a sandbox)" : "allowed"} ` +
        `fail_closed=${failClosed}`,
    );
    if (state.sandbox) {
      const g = state.sandbox.gate;
      const verdict = !g.required
        ? "not required"
        : g.allowed
          ? g.overridden
            ? "REQUIRED — host-unrestricted, OVERRIDDEN"
            : "required — satisfied"
          : "REQUIRED — host-unrestricted: BLOCKED";
      lines.push(
        `sandbox: ${g.state} (${state.sandbox.detection.provider}) — ${verdict}`,
      );
    }
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
  lines.push("lifecycle-hook mapping (FR-010):");
  for (const l of hookMappingReport()) lines.push(l);
  lines.push(`  shell-hook scripts dir: ${state.hookScriptsDir ?? "<none configured>"}`);
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
    context: null,
    contextInjected: false,
    sandbox: null,
    hookScriptsDir: null,
  };

  const cfg = (dotted: string): unknown => state.config?.resolved.get(dotted)?.value;

  const requiredGates = (): string[] => {
    const v = cfg("verification.required");
    return Array.isArray(v) ? v.map(String) : [];
  };

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

  // Resource dirs to search for the always-context bundle: the managed
  // install and a repo checkout, mirroring how the launcher finds the runtime.
  const resourceDirs = (): string[] => {
    const home = process.env.CCT_HOME ?? path.join(os.homedir(), ".code-copilot-team");
    const dirs = [path.join(home, "pi")];
    try {
      const here = path.dirname(new URL(import.meta.url).pathname);
      dirs.push(path.dirname(here)); // <adapter>/runtime -> <adapter>
    } catch {
      /* import.meta unavailable — managed dir is enough */
    }
    return dirs;
  };

  // The Pi adapter dir (<adapter>/runtime -> <adapter>), used to locate the
  // sibling Claude Code plugin scripts the shell-hook adapter reuses (T5.1).
  const piAdapterDir = (): string | null => {
    try {
      const here = path.dirname(new URL(import.meta.url).pathname);
      return path.dirname(here);
    } catch {
      return null;
    }
  };

  /**
   * Load the always-on policy bundle and hand it to Pi. Injection uses Pi's
   * context API when present; `contextInjected` records whether it actually
   * ran, so doctor reports the truth instead of assuming the model saw it.
   */
  function injectAlwaysContext(s: CctRuntimeState, ctx: any): void {
    s.context = loadAlwaysContext(resourceDirs());
    if (s.context.warning) s.warnings.push(s.context.warning);
    if (!s.context.text) return;
    const api = ctx?.addContext ?? ctx?.appendSystemContext ?? pi?.registerContext;
    if (typeof api === "function") {
      try {
        api.call(ctx ?? pi, s.context.text);
        s.contextInjected = true;
      } catch {
        s.contextInjected = false;
      }
    } else {
      s.warnings.push(
        "always-on context bundle loaded but Pi exposed no context-injection " +
          "API in this version — policy is not in the session prompt",
      );
    }
  }

  pi.on?.("session_start", async (_event: unknown, ctx: any) => {
    try {
      state.trust = ctx?.isProjectTrusted?.() ? "trusted" : "untrusted";
    } catch {
      state.trust = "unknown"; // fail closed: unknown ⇒ untrusted behavior
    }
    state.cwd = ctx?.cwd ?? process.cwd();
    state.interactive = ctx?.hasUI === true && ctx?.mode === "tui";
    state.hookScriptsDir = resolveHookScriptsDir(piAdapterDir());
    loadConfigForState(state, state.cwd);
    state.workflow = loadState(state.cwd);
    // T9.1 (FR-017): post-compaction / restart recovery. Pi emits no compaction
    // event, so recovery runs here — re-inject a digest + the compaction prompt
    // so the model re-learns where CCT left off. Audited, best-effort.
    const recovered = loadCheckpoint(state.cwd);
    if (recovered) {
      state.warnings.push(
        `session recovery: resumed from checkpoint #${recovered.checkpointCount} ` +
          `(${recovered.phase ?? "no phase"}/${recovered.featureId ?? "no feature"})`,
      );
      // Trust-gate the CONTEXT injection: .cct/pi-session.json is untrusted
      // project-local input (may be tampered), so its recovery digest is
      // injected into model context ONLY for a positively-trusted project
      // (FR-004a) — same discipline as project config. Fields are also
      // sanitized on load (defense-in-depth).
      if (state.trust === "trusted") {
        const rApi =
          ctx?.addContext ?? ctx?.appendSystemContext ?? pi?.registerContext;
        if (typeof rApi === "function") {
          try {
            rApi.call(ctx ?? pi, recoveryDigest(recovered));
          } catch {
            /* best-effort: recovery context is advisory */
          }
        }
      } else {
        state.warnings.push(
          "session recovery: context injection withheld — project not positively trusted",
        );
      }
      audit({
        mode: resolveAuditMode(state.interactive),
        actor: "session_start",
        decision: "recovered",
        rule: "session.checkpoint",
        subject: `#${recovered.checkpointCount}:${recovered.featureId ?? "<none>"}`,
        origin: "session",
      });
    }
    const midReview = midReviewWarning(state.cwd);
    if (midReview) {
      state.warnings.push(midReview);
      audit({
        mode: resolveAuditMode(state.interactive),
        actor: "session_start",
        decision: "warn",
        rule: "review.unresolved",
        subject: midReview.slice(0, 200),
        origin: "review-gate",
      });
    }
    const verifyWarn = verifyWarning(state.cwd, requiredGates());
    if (verifyWarn) {
      state.warnings.push(verifyWarn);
      audit({
        mode: resolveAuditMode(state.interactive),
        actor: "session_start",
        decision: "warn",
        rule: "verification.unresolved",
        subject: verifyWarn.slice(0, 200),
        origin: "verify-gate",
      });
    }
    refreshRules();
    // T10.1 (FR-019): detect the sandbox and evaluate the autonomous/ci
    // no-unrestricted-host gate. Reported + audited here; enforced at tool_call.
    {
      const detection = detectSandbox(process.env);
      const gate = sandboxGate(detection, {
        sandboxRequired: cfg("security.sandbox_required") === true,
        rejectUnrestrictedHost: cfg("autonomy.reject_unrestricted_host") === true,
        override: process.env.CCT_SANDBOX_OVERRIDE === "1",
      });
      state.sandbox = { gate, detection };
      if (!gate.allowed) {
        state.warnings.push(`SANDBOX BLOCK: ${gate.reason}`);
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "session_start",
          decision: "deny",
          rule: "security.sandbox_required",
          subject: gate.state,
          origin: "sandbox",
        });
      } else if (gate.overridden) {
        state.warnings.push(`sandbox override accepted: ${gate.reason}`);
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "session_start",
          decision: "override",
          rule: "security.sandbox_required",
          subject: gate.state,
          origin: "sandbox",
        });
      } else if (gate.required && detection.provider === "env") {
        // A required sandbox satisfied purely by an env DECLARATION (not
        // host-detected) is allowed, but must not be invisible — a bare host
        // could declare itself sandboxed via CCT_SANDBOX. Recorded.
        state.warnings.push(
          `sandbox declared via env: ${detection.state} (CCT_SANDBOX) — accepted, recorded`,
        );
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "session_start",
          decision: "declared",
          rule: "security.sandbox_required",
          subject: `CCT_SANDBOX=${detection.state}`,
          origin: "sandbox",
        });
      }
    }
    injectAlwaysContext(state, ctx);
    if (!(state.profile in BUILTIN_PROFILES)) {
      state.warnings.push(`unknown profile '${state.profile}' — using defaults chain only`);
    }
    updateStatus(ctx);
  });

  // FR-020: the active phase's model/thinking, resolved from config. Shown
  // in the status line; applying the switch to the session is Phase 7.
  const phasePolicyLabel = (): string => {
    const pol = resolvePhasePolicy(cfg, state.workflow.phase);
    return `model:${pol.model} think:${pol.thinking}`;
  };

  const updateStatus = (ctx: any): void => {
    ctx?.ui?.setStatus?.(
      "cct",
      `CCT ${state.profile} · ${state.workflow.phase}` +
        (state.workflow.featureId ? `:${state.workflow.featureId}` : "") +
        ` · ${phasePolicyLabel()}` +
        ` · trust:${state.trust} · sdd:${cfg("workflow.sdd.enabled") === true ? "on" : "off"}`,
    );
  };

  // ── Enforcement: tool_call interception (FR-007/FR-009, Phase 4–5 core) ──
  const WRITE_TOOLS = new Set(["edit", "write"]);
  const EXEC_TOOLS = new Set(["bash"]);

  const block = (origin: string, actor: string, v: PermissionVerdict, subject: string) => {
    audit({
      mode: resolveAuditMode(state.interactive),
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

    // T10.1 (FR-019): reject unrestricted-host EXECUTION. When the posture
    // requires a sandbox and none is present (no override), no tool runs.
    if (state.sandbox && !state.sandbox.gate.allowed) {
      return block(
        "sandbox",
        `tool_call:${String(event?.toolName ?? event?.name ?? "")}`,
        {
          decision: "deny",
          effective: "deny",
          rule: "security.sandbox_required",
          reason: state.sandbox.gate.reason,
        },
        state.sandbox.gate.state,
      );
    }
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
        // Package-install / network policy (T5.3, FR-009).
        const execV = checkExecPolicy(state.rules, command);
        if (execV.effective === "deny") {
          const origin =
            execV.rule === "security.deny_network" ? "network-policy" : "package-policy";
          return block(origin, `tool_call:${toolName}`, execV, command);
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

    // 5) FR-010: reuse existing Claude Code PreToolUse veto hooks where the
    // semantics match, as a defense-in-depth layer behind the in-runtime
    // checks. Support-gated, audited, fail-closed (a veto hook that errors
    // blocks rather than silently allows). No-op when no script resolves.
    const preEvent = translateToolCall(toolName, args, state.cwd, {
      interactive: state.interactive,
      mode: resolveAuditMode(state.interactive),
    });
    const preScripts = resolveHookScripts(preEvent, state.hookScriptsDir);
    if (preScripts.length > 0) {
      const res = dispatchHooks(
        preEvent,
        preScripts,
        { failMode: "closed" },
        (rec) => audit({ mode: resolveAuditMode(state.interactive), ...rec }),
      );
      if (res.block) return { block: true, reason: `[cct] ${res.reason}` };
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

  pi.registerCommand?.("cct:hooks", {
    description: "Show the Pi->CCT lifecycle-hook mapping and support levels (FR-010)",
    handler: async (ctx: any) => {
      const lines = [
        "lifecycle-hook mapping (FR-010):",
        ...hookMappingReport(),
        `shell-hook scripts dir: ${state.hookScriptsDir ?? "<none configured>"}`,
      ];
      emit(ctx, lines.join("\n"));
    },
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
      // Mandatory-review gate on LEAVING review (decision A): cannot advance
      // out of an unresolved mandatory review without a PASS/bypass summary.
      if (state.workflow.phase === "review" && target !== "review" && cfg("review.mandatory") === true) {
        const rg = reviewGate(state.cwd, true, "review");
        if (!rg.pass && peerReviewDisabled()) {
          audit({
            mode: resolveAuditMode(state.interactive),
            actor: "cct:phase",
            decision: "override",
            rule: "peer-review-off",
            subject: `review->${target}:${state.workflow.featureId ?? "<none>"}`,
            origin: "review-gate",
          });
        } else if (!rg.pass) {
          audit({
            mode: resolveAuditMode(state.interactive),
            actor: "cct:phase",
            decision: "deny",
            rule: "review.mandatory",
            subject: `review->${target}:${state.workflow.featureId ?? "<none>"}`,
            origin: "review-gate",
          });
          return emit(ctx, `phase transition 'review -> ${target}' BLOCKED:\n  - ${rg.reason}`);
        }
      }
      if (state.workflow.phase === "review" && target !== "review" && requiredGates().length > 0) {
        const vg = verifyGate(state.cwd, requiredGates(), "review");
        if (!vg.pass) {
          audit({
            mode: resolveAuditMode(state.interactive),
            actor: "cct:phase",
            decision: "deny",
            rule: "verification.required",
            subject: `review->${target}:${state.workflow.featureId ?? "<none>"}`,
            origin: "verify-gate",
          });
          return emit(ctx, `phase transition 'review -> ${target}' BLOCKED:\n  - ${vg.reason}`);
        }
      }
      const result = transition(
        state.cwd,
        state.workflow,
        target,
        featureId,
        new Date().toISOString(),
      );
      if (!result.ok) {
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "cct:phase",
          decision: "deny",
          rule: "sdd.entry-gate",
          subject: `${target}:${featureId ?? state.workflow.featureId ?? "<none>"}`,
          origin: "sdd-gate",
        });
        return emit(ctx, `phase transition to '${target}' BLOCKED:\n  - ${result.reasons.join("\n  - ")}`);
      }
      state.workflow = result.state;
      // T9.1: checkpoint on every phase transition (an explicit CCT action —
      // the durable substitute for a missing pre-compaction hook).
      if (
        !tryWriteCheckpoint(
          state.cwd,
          {
            phase: state.workflow.phase,
            featureId: state.workflow.featureId,
            note: `entered ${state.workflow.phase}`,
          },
          new Date().toISOString(),
        )
      ) {
        state.warnings.push(
          "checkpoint write failed (durability is best-effort; the phase transition itself is unaffected)",
        );
      }
      updateStatus(ctx);
      const pol = resolvePhasePolicy(cfg, state.workflow.phase);
      emit(
        ctx,
        `phase: ${state.workflow.phase}` +
          (state.workflow.featureId ? ` (feature: ${state.workflow.featureId})` : "") +
          (result.gate ? ` — SDD gate: PASS (${result.gate.specMode})` : "") +
          `\n  policy (resolved, not enforced): model=${pol.model} thinking=${pol.thinking} ` +
          `permissions=${pol.permissions}\n  tools: ${pol.tools.join(", ") || "<inherit>"}`,
      );
    },
  });

  pi.registerCommand?.("cct:checkpoint", {
    description: "Save a durable session checkpoint (recovered at next session start)",
    handler: async (ctx: any) => {
      const cp = tryWriteCheckpoint(
        state.cwd,
        {
          phase: state.workflow.phase,
          featureId: state.workflow.featureId,
          note: `manual checkpoint in ${state.workflow.phase}`,
        },
        new Date().toISOString(),
      );
      if (!cp) {
        return emit(
          ctx,
          "checkpoint write failed — check .cct/ path and permissions (no workflow state was lost)",
        );
      }
      emit(
        ctx,
        `checkpoint #${cp.checkpointCount} saved ` +
          `(${cp.phase ?? "no phase"}/${cp.featureId ?? "no feature"}) — ` +
          "recovered automatically at the next session start",
      );
    },
  });

  pi.registerCommand?.("cct:remember", {
    description:
      "Promote a durable memory: /cct:remember <user|feedback|project|reference> <fact>",
    handler: async (ctx: any, args?: string) => {
      const raw = (typeof args === "string" ? args : "").trim();
      const m = /^(user|feedback|project|reference)\s+([\s\S]+)$/.exec(raw);
      if (!m) {
        return emit(
          ctx,
          "usage: /cct:remember <user|feedback|project|reference> <fact>",
        );
      }
      const res = promoteMemory(state.cwd, {
        type: m[1] as MemoryType,
        fact: m[2],
        provenance: {
          phase: state.workflow.phase,
          featureId: state.workflow.featureId,
          at: new Date().toISOString(),
        },
      });
      if (!res.ok) {
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "cct:remember",
          decision: res.refused ? "refused" : "deny",
          rule: "memory.sensitive",
          subject: res.reason.slice(0, 120),
          origin: "memory",
        });
        return emit(ctx, `not remembered: ${res.reason}`);
      }
      emit(ctx, res.reason);
    },
  });

  pi.registerCommand?.("cct:memory", {
    description: "List promoted memories",
    handler: async (ctx: any) => {
      const all = listMemories(state.cwd);
      if (all.length === 0) {
        return emit(ctx, "no memories yet — /cct:remember <type> <fact>");
      }
      emit(ctx, all.map((r) => `${r.id} [${r.type}] ${r.fact}`).join("\n"));
    },
  });

  pi.registerCommand?.("cct:memory-forget", {
    description: "Delete a memory by id: /cct:memory-forget <id>",
    handler: async (ctx: any, args?: string) => {
      const id = (typeof args === "string" ? args : "").trim();
      if (!id) return emit(ctx, "usage: /cct:memory-forget <id>");
      emit(
        ctx,
        deleteMemory(state.cwd, id) ? `forgot ${id}` : `no memory with id '${id}'`,
      );
    },
  });

  pi.registerCommand?.("cct:recall", {
    description: "Wiki-first recall across the wiki + promoted memories: /cct:recall <query>",
    handler: async (ctx: any, args?: string) => {
      const q = (typeof args === "string" ? args : "").trim();
      if (!q) return emit(ctx, "usage: /cct:recall <query>");
      const hits = recall(state.cwd, q);
      if (hits.length === 0) return emit(ctx, `no matches for '${q}'`);
      emit(
        ctx,
        hits.map((h) => `[${h.source}] ${h.text}`).join("\n") +
          `\n  (${memkernelStatus().reason})`,
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

  // SDD risk classifier (T4.1). Show / set / override the spec_mode for the
  // active feature. Persisted and user-correctable: `--set` records a manual
  // override that survives re-classification.
  pi.registerCommand?.("cct:classify", {
    description:
      "Classify SDD risk for the active feature: /cct:classify [<category> [files]] | --set <mode> <reason>",
    handler: async (ctx: any, args?: string) => {
      const feature = state.workflow.featureId;
      if (!feature) {
        return emit(ctx, "no active feature — set one with /cct:phase <phase> <feature-id>");
      }
      const parts = (typeof args === "string" ? args : "").trim().split(/\s+/).filter(Boolean);

      if (parts[0] === "--set") {
        const mode = parts[1] as SpecMode;
        if (mode !== "full" && mode !== "lightweight" && mode !== "none") {
          return emit(ctx, "usage: /cct:classify --set <full|lightweight|none> <reason>");
        }
        const reason = parts.slice(2).join(" ") || "(no reason given)";
        const c = overrideClassification(state.cwd, feature, mode, reason);
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "cct:classify",
          decision: "override",
          rule: "sdd.classification",
          subject: `${feature}:${c.mode}`,
          origin: "sdd-gate",
        });
        return emit(ctx, `classification for ${feature}: ${c.mode} (user override) — ${c.justification}`);
      }

      if (parts.length === 0) {
        const c = loadClassification(state.cwd, feature);
        return emit(
          ctx,
          c
            ? `classification for ${feature}: ${c.mode} (${c.source}) — ${c.justification}`
            : `no classification for ${feature} yet — /cct:classify <${RISK_CATEGORIES.join("|")}> [files]`,
        );
      }

      const category = parts[0] as RiskCategory;
      if (!RISK_CATEGORIES.includes(category)) {
        return emit(ctx, `unknown category '${parts[0]}' (${RISK_CATEGORIES.join("|")})`);
      }
      const filesTouched = parts[1] ? Number(parts[1]) : undefined;
      const c = resolveClassification(state.cwd, feature, { category, filesTouched });
      emit(
        ctx,
        c
          ? `classification for ${feature}: ${c.mode} (${c.source}) — ${c.justification}`
          : `could not classify ${feature}`,
      );
    },
  });

  // ── Stateful commands (T2.4) ──────────────────────────────────────
  // The generator excludes these from prompt-template conversion because
  // they mutate workflow state, start agents, or drive review loops. They
  // are registered here as /cct:* commands so a session recognizes them
  // rather than dropping them. Commands whose backing machinery lands in a
  // later phase report that honestly instead of no-oping or faking success.
  const DEFERRED_STATEFUL: { name: string; description: string; lands: string }[] = [
    {
      name: "cct:cycle-start",
      description: "Start a Shape-Up cycle for a bet pitch",
      lands: "the Shape-Up capability is not part of the enforced Pi runtime yet",
    },
    {
      name: "cct:ralph-start",
      description: "Start a Ralph autonomous-iteration loop",
      lands: "autonomous loops land with the agent runner in Phase 7+",
    },
    {
      name: "cct:auto-build",
      description: "Start the autonomous build driver for an approved SDD feature",
      lands: "the auto-build driver lands with the agent runner in Phase 7+",
    },
  ];
  for (const c of DEFERRED_STATEFUL) {
    pi.registerCommand?.(c.name, {
      description: c.description,
      handler: async (ctx: any) =>
        emit(
          ctx,
          `${c.name} is recognized but not yet active in pi-code: ${c.lands}. ` +
            `Run 'pi-code features' to see capability status.`,
        ),
    });
  }

  // phase-complete has real backing now: the phase machine and the SDD gate
  // both exist, so it validates the active feature's gate and reports whether
  // the phase can complete rather than deferring.
  pi.registerCommand?.("cct:phase-complete", {
    description: "Validate the SDD gate and report whether the phase can complete",
    handler: async (ctx: any) => {
      if (!state.workflow.featureId) {
        emit(ctx, "no active feature — set one with /cct:phase <phase> <feature-id>");
        return;
      }
      const gate = validateSpecDir(path.join(state.cwd, "specs", state.workflow.featureId));
      const mandatory = cfg("review.mandatory") === true;
      const rgate = reviewGate(state.cwd, mandatory, state.workflow.phase);
      const reviewOverride = mandatory && !rgate.pass && peerReviewDisabled();
      const vgate = verifyGate(state.cwd, requiredGates(), state.workflow.phase);
      const lines = [
        `feature: ${state.workflow.featureId}`,
        `phase: ${state.workflow.phase}`,
        `sdd gate: ${gate.pass ? "PASS" : "FAIL"} (spec_mode=${gate.specMode ?? "?"})`,
      ];
      for (const r of gate.reasons) lines.push(`  - ${r}`);
      lines.push(
        `review gate: ${rgate.pass ? "PASS" : reviewOverride ? "OVERRIDDEN (--peer-review-off)" : "BLOCKED"}` +
          (mandatory ? "" : " (review not mandatory)"),
      );
      if (reviewOverride) {
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "cct:phase-complete",
          decision: "override",
          rule: "peer-review-off",
          subject: `${state.workflow.featureId}:${state.workflow.phase}`,
          origin: "review-gate",
        });
      } else if (!rgate.pass) {
        lines.push(`  - ${rgate.reason}`);
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "cct:phase-complete",
          decision: "deny",
          rule: "review.mandatory",
          subject: `${state.workflow.featureId}:${state.workflow.phase}`,
          origin: "review-gate",
        });
      }
      lines.push(
        `verify gate: ${vgate.pass ? "PASS" : "BLOCKED"}` +
          (requiredGates().length ? "" : " (no gates required)"),
      );
      if (!vgate.pass) {
        for (const l of vgate.reason.split("\n")) lines.push(`  ${l}`);
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "cct:phase-complete",
          decision: "deny",
          rule: "verification.required",
          subject: `${state.workflow.featureId}:${state.workflow.phase}`,
          origin: "verify-gate",
        });
      }
      const canComplete = gate.pass && (rgate.pass || reviewOverride) && vgate.pass;
      lines.push(
        canComplete
          ? "phase may complete; advance with /cct:phase <next> " + state.workflow.featureId
          : "phase is BLOCKED",
      );
      emit(ctx, lines.join("\n"));
    },
  });

  pi.registerCommand?.("cct:verify", {
    description:
      "Run the verification gates (verification.required) and report per-gate status",
    handler: async (ctx: any) => {
      const gates = requiredGates();
      if (gates.length === 0) {
        return emit(ctx, "no verification gates required (set verification.required)");
      }
      const out = runVerify(
        state.cwd,
        resolveVerifyRunner(piAdapterDir()),
        gates,
        Number(cfg("limits.timeout_sec") ?? 900),
      );
      const vg = verifyGate(state.cwd, gates, state.workflow.phase);
      audit({
        mode: resolveAuditMode(state.interactive),
        actor: "cct:verify",
        decision: vg.pass ? "pass" : "deny",
        rule: "verification.required",
        subject: `${state.workflow.featureId ?? "<none>"}:${gates.join(",")}`,
        origin: "verify-gate",
      });
      const lines = [
        `verify: ${out.ran ? `ran (exit ${out.exitCode})` : "did not run"}`,
        `  ${out.reason}`,
        `verify gate: ${vg.pass ? "PASS" : "BLOCKED"}`,
      ];
      if (!vg.pass) for (const l of vg.reason.split("\n")) lines.push(`  ${l}`);
      emit(ctx, lines.join("\n"));
    },
  });

  pi.registerCommand?.("cct:review-submit", {
    description: "Submit work for cross-provider peer review (one round)",
    handler: async (ctx: any, args?: string) => {
      if (!state.workflow.featureId) {
        return emit(ctx, "no active feature — set one with /cct:phase <phase> <feature-id>");
      }
      // T3.4 (FR-015a): the peer-reviewer is a non-recursive read-only reviewer —
      // a reviewer session must NOT start reviews. The active profile is the
      // discriminator (review.allow_recursive is false by default for everyone,
      // so it cannot be the signal). Blocked and audited, never a silent skip.
      if (state.config?.profileChain.includes("peer-reviewer")) {
        audit({
          mode: resolveAuditMode(state.interactive),
          actor: "cct:review-submit",
          decision: "block",
          rule: "review.allow_recursive",
          subject: state.workflow.featureId,
          origin: "review-gate",
        });
        return emit(
          ctx,
          "review blocked: the peer-reviewer is non-recursive (FR-015a) — a reviewer session cannot start reviews (rule: review.allow_recursive)",
        );
      }
      const parts = (typeof args === "string" ? args : "").trim().split(/\s+/).filter(Boolean);
      const peerProvider = sessionPeerProvider(parts[0] ?? "");
      const runnerPhase = state.workflow.phase === "plan" ? "plan" : "build";
      const limits = {
        maxRounds: Number(cfg("limits.max_review_rounds") ?? 5),
        timeoutSec: Number(cfg("limits.timeout_sec") ?? 900),
      };
      // Init-or-continue (NOT unconditional init): re-submitting must preserve
      // the runner's breaker state (current_round/loop_start/findings).
      const outcome = submitReviewRound(
        state.cwd,
        {
          featureId: state.workflow.featureId,
          phase: runnerPhase,
          subjectProvider: "pi",
          peerProvider,
          reviewScope: sessionReviewScope(),
          targetRef: resolveTargetRef(state.cwd, parts[1]),
          loopStart: Math.floor(Date.now() / 1000),
        },
        resolveReviewRunner(piAdapterDir()),
        limits,
      );
      audit({
        mode: resolveAuditMode(state.interactive),
        actor: "cct:review-submit",
        decision: outcome.status,
        rule: "review.round",
        subject: `${state.workflow.featureId}:${runnerPhase}`,
        origin: "review-gate",
      });
      const tail =
        outcome.status === "pass" ? "\n  phase may complete"
        : outcome.status === "breaker" ? "\n  breaker tripped — /cct:review-decide approve|reject|retry"
        : outcome.status === "no-runner" || outcome.status === "error" ? ""
        : "\n  address findings and re-run /cct:review-submit";
      emit(
        ctx,
        `review round: ${outcome.status}` +
          (outcome.verdict ? ` (verdict ${outcome.verdict})` : "") +
          `\n  ${outcome.reason}` +
          tail,
      );
    },
  });

  pi.registerCommand?.("cct:review-decide", {
    description: "Resolve a review-loop breaker: /cct:review-decide <approve|reject|retry> [detail]",
    handler: async (ctx: any, args?: string) => {
      if (!state.workflow.featureId) return emit(ctx, "no active feature");
      const parts = (typeof args === "string" ? args : "").trim().split(/\s+/).filter(Boolean);
      const decision = parts[0];
      if (decision !== "approve" && decision !== "reject" && decision !== "retry") {
        return emit(ctx, "usage: /cct:review-decide <approve|reject|retry> [detail]");
      }
      const detail = parts.slice(1).join(" ") || "(no detail)";
      writeDecision(state.cwd, decision, detail, new Date().toISOString());
      audit({
        mode: resolveAuditMode(state.interactive),
        actor: "cct:review-decide",
        decision,
        rule: "review.decision",
        subject: `${state.workflow.featureId}:${detail}`.slice(0, 200),
        origin: "review-gate",
      });
      emit(
        ctx,
        decision === "approve" ? "review bypassed by audited human override; phase may complete"
        : decision === "reject" ? "review rejected; work does not proceed"
        : "breaker reset; continue with /cct:review-submit",
      );
    },
  });
}
