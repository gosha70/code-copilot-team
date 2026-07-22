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
