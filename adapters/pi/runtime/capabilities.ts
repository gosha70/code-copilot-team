/**
 * Capability seed for the Pi adapter (spec FR-029; authored).
 *
 * Its own module so the runtime and the diagnostic CLI report identical
 * capability state. The neutral definitions live in
 * shared/capabilities/catalog.yaml, and this seed is pinned to
 * shared/capabilities/pi.yaml by tests/test-pi-adapter.sh — edit both or
 * the drift guard fails.
 */

export interface CapabilityRecord {
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

/** Capability seed. Statuses flip only via acceptance gates (FR-028). */
export function seedCapabilities(): CapabilityRecord[] {
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
      runtime_status: "enabled",
      reason:
        "The read-only reviewer execution contract (T3.1-T3.4) passes its acceptance suite (scripts/pi-provider-acceptance.sh) — the single source of truth. Enablement is bound to that suite by tests/test-pi-provider-gate.sh; PATH presence never implies enabled. Runtime availability of the pi binary is gated separately by the pi-code doctor health probe.",
    },
    {
      id: "review.enforcement",
      implementation_kind: "cct-first-party",
      runtime_status: "degraded",
      reason:
        "Mandatory review is gated at /cct:phase-complete and the review->next transition (Pi emits no Stop/turn-end event); weaker than Claude's Stop-hook gate.",
    },
    {
      id: "verification.enforcement",
      implementation_kind: "cct-first-party",
      runtime_status: "degraded",
      reason:
        "Verification gates block at /cct:phase-complete + review->next (Pi has no Stop event); type-check runs tsc --noEmit over the runtime when typescript is installed (else unsupported); lint/dependency-audit still report unsupported, never a fake pass.",
    },
    {
      id: "integrations.mcp",
      implementation_kind: "optional-bridge",
      runtime_status: "degraded",
      reason:
        "MCP provider interface present (FR-018 modes: disabled/external-package/first-party-bridge/remote-gateway) with MemKernel as the first audited backend — declared, connectivity-probed (PATH, never spawned), trust-gated, and reported via /cct:mcp; no backend is silent (P6). DEGRADED because live JSON-RPC tool invocation flows through Pi's own MCP transport, which the extension does not own; opt in with integrations.mcp.enabled.",
    },
    {
      id: "integrations.hosted-platform",
      implementation_kind: "external-platform",
      runtime_status: "unavailable",
      reason: "Anthropic-hosted services are external platforms; never claimed as Pi parity.",
    },
    {
      id: "memory.session-state",
      implementation_kind: "cct-first-party",
      runtime_status: "degraded",
      reason:
        "Session state persists to .cct/pi-session.json and recovers into context at session_start; checkpoints are taken at explicit CCT actions (phase transitions, /cct:checkpoint) because Pi emits no observable compaction event — not a pre-compaction hook, hence degraded.",
    },
    {
      id: "security.sandbox",
      implementation_kind: "cct-first-party",
      runtime_status: "degraded",
      reason:
        "Enforces the autonomous/ci no-unrestricted-host rule — rejects tool execution (fail-closed) when a sandbox is required but the environment is host-unrestricted and no override is set. Detection is best-effort (Docker via cgroup/.dockerenv; micro-vm/remote via operator CCT_SANDBOX declaration); the runtime cannot itself create a sandbox.",
    },
    {
      id: "memory.promotion",
      implementation_kind: "cct-first-party",
      runtime_status: "degraded",
      reason:
        "Built-in store (.cct/memory.json) is authoritative: promote/delete/list, wiki-first recall, provenance, and a fail-closed sensitive-memory control (a secret-bearing fact is refused). MemKernel is an MCP server, so code-aware delegation waits on the Pi MCP provider (integrations.mcp, T10.2); until then it reports pending-MCP.",
    },
  ];
}
