/**
 * Code Copilot Team — Pi enforcement runtime (Phase 0 skeleton).
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
 *     keep working. Project CCT configuration loads (in Phase 1+) only
 *     after ctx.isProjectTrusted() reports positive trust; unknown or
 *     deferred trust is treated as untrusted (fail closed).
 */

type TrustState = "trusted" | "untrusted" | "unknown";

interface CctRuntimeState {
  profile: string;
  trust: TrustState;
  trustOwner: string | null;
  capabilities: CapabilityRecord[];
}

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

/** Phase 0 capability seed. Statuses flip only via acceptance gates (FR-028). */
function seedCapabilities(): CapabilityRecord[] {
  return [
    { id: "skills.shared", implementation_kind: "native", runtime_status: "enabled" },
    { id: "prompts.commands", implementation_kind: "native", runtime_status: "enabled" },
    {
      id: "config.layered",
      implementation_kind: "cct-first-party",
      runtime_status: "disabled",
      reason: "Phase 1 (registry, TOML config, trust gating) not yet implemented.",
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

// The factory signature matches Pi's ExtensionAPI contract. Typed loosely
// here so Phase 0 carries no build-time dependency; Phase 1 adopts the
// published types from @earendil-works/pi-coding-agent (dev-only).
export default async function (pi: any): Promise<void> {
  const marker = process.env.CCT_RUNTIME === "1";
  const testBootstrap = process.env.CCT_TEST_BOOTSTRAP === "1";

  if (!marker && !testBootstrap) {
    // Loaded outside pi-code (e.g. someone pointed --extension at us
    // manually). Refuse enforcement initialization; register nothing.
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
    capabilities: seedCapabilities(),
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
    ctx?.ui?.setStatus?.(
      "cct",
      `CCT ${state.profile} · trust:${state.trust} · phase0`,
    );
  });

  // ── Diagnostics: /cct:doctor (Phase 0 subset) ──────────────────────
  pi.registerCommand?.("cct:doctor", {
    description: "Code Copilot Team diagnostics (Phase 0 subset)",
    handler: async (ctx: any) => {
      const lines = [
        `pi-code runtime: active (profile=${state.profile})`,
        `project trust: ${state.trust}${state.trust !== "trusted" ? " (project CCT config will NOT load)" : ""}`,
        "capabilities:",
        ...state.capabilities.map(
          (c) =>
            `  ${c.id}: ${c.implementation_kind}/${c.runtime_status}` +
            (c.reason ? ` — ${c.reason}` : ""),
        ),
      ];
      const text = lines.join("\n");
      if (ctx?.hasUI && ctx?.ui?.notify) ctx.ui.notify(text);
      // eslint-disable-next-line no-console
      else console.log(text);
    },
  });

  // ── Discoverability: /cct:features (machine-readable) ──────────────
  pi.registerCommand?.("cct:features", {
    description: "List CCT capability records (JSON)",
    handler: async (_ctx: any) => {
      // eslint-disable-next-line no-console
      console.log(JSON.stringify(state.capabilities, null, 2));
    },
  });
}
