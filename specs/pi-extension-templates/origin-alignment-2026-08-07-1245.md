# Origin alignment check — pi-extension-templates

Origin: https://github.com/gosha70/code-copilot-team/issues/179

Origin claim:
> Prompt enforcement alone is insufficient for enterprise environments
> requiring deterministic, programmatic guardrails. Introduce native Pi
> harness extension templates (.pi/extensions/) and programmatic hook
> recipes: mid-generation execution gates intercepting write/edit to spawn
> external validation and feed failures back for self-correction; AST
> parsing wrappers; dynamic event-driven model routing; headless JSON-RPC
> bootstrap recipes. Acceptance: a .pi/extensions/ starter template in
> project presets; docs linking hooks with AGENTS.md/SYSTEM.md
> definitions; a reference validator demonstrating mid-generation
> interception; standard headless launch configurations.

Working claim:
> The spec delivers the issue's four acceptance items on VERIFIED Pi
> surfaces: (1) a .pi/extensions/ starter template scaffolded by `pi-code
> init --extension-template` — a tool_call PRE-write execution gate that
> spawns an external validator and feeds its stderr back as the block
> reason for immediate self-correction (the issue's mid-generation gate,
> delivered pre-write because PostToolUse is unsupported on this Pi build
> — recorded, not overclaimed); (2) a runnable stdlib ast.parse reference
> validator; (3) linkage docs (prompts declare intent, extensions enforce)
> plus an honesty table mapping each unverified issue API (post_tool_call,
> agent_event/setModel, --mode rpc, auto-discovery) to its status and
> working alternative; (4) headless recipes on the verified `--mode json`
> surface with envelope/exit-code semantics and a CI example. No runtime
> change, no new capability, no unverified API shipped as working.

Mismatches:
  - Dynamic mid-turn model routing (agent_event/setModel) is NOT delivered
    as working behavior — no verified Pi surface exists for it; it is
    recorded in the honesty table with the config-policy alternative. This
    is the honesty boundary, not a scope cut: shipping it would fabricate
    an API. The issue's own acceptance list does not require it (its four
    checkboxes are covered above).

Verdict: aligned
Confidence: high

Note: re-check after the phase-1 review redesign. The corrected facts
(tool_result supported, auto-discovery supported/trust-gated, setModel
present, rpc shipped) move the working claim CLOSER to the origin ask:
post-tool interception and result patching are now genuinely delivered,
auto-discovery is the recommended load path, and the previous mismatch
bullet (model routing) softens to exists-but-unwrapped, documented. The
pre-write gate now validates incoming content (the origin mid-generation
gate, honestly). Scope unchanged; alignment strengthened.

Note: re-check after the verification-round fixes (N1-N9): working
primary-source canary with visible skip + version pinning, type-sound
error classification now under a dedicated tsconfig in the typecheck gate,
ctx.cwd-resolved post-gate (no silent fail-open on relative paths),
validator 3-state contract hardened (non-UTF-8 = validator error), warn/
timeout branches tested. Scope unchanged.
