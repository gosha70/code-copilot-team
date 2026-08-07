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

Working claim (rewritten this round — supersedes earlier records' claim
blocks, which carried pre-review statements the phase-1 review disproved):
> The feature delivers all four acceptance items on pi-0.83.0-verified
> surfaces (primary sources cited throughout): (1) a .pi/extensions/
> guardrails starter scaffolded by `pi-code init --extension-template`
> with TWO gates — pre-write validation of the incoming `write` content
> (blocked before disk) and `tool_result` post-execution validation of the
> on-disk write/edit result with the report patched into the tool result —
> the issue's mid-generation interception, delivered on pi's shipped
> events; (2) a runnable 3-state reference validator; (3) linkage docs
> (prompts declare, extensions enforce) plus a primary-sourced honesty
> table: tool_result supported (used), setModel exists (documented,
> unwrapped — the routing ask is partially available), --mode rpc shipped
> but harness-unexercised, auto-discovery supported/trust-gated and the
> recommended load path with the explicit-flag trust-bypass caveat; (4)
> headless recipes on the harness-verified `--mode json` surface with a
> CI job example. No runtime change; a version-pinned canary keeps the
> table honest against the installed pi.

Mismatches:
  - Dynamic model ROUTING is documented as partially available
    (`setModel` exists; no `agent_event`) rather than templated — a
    deliberate scope boundary, not an availability falsehood. The issue's
    four acceptance checkboxes are all delivered.

Verdict: aligned
Confidence: high
