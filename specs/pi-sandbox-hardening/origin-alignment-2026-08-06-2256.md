# Origin alignment check — pi-sandbox-hardening

Origin: https://github.com/gosha70/code-copilot-team/issues/173

Origin claim:
> Implement `design-t115-security-battery.md` and evaluate robust sandbox
> backends to force agent runtime tools into an isolated environment.
> (1) Backend integration: evaluate and choose an isolation wrapper layer.
> (2) Environment variable scrubbing: intercept host process parameters to
> strip out AWS, GitHub, or internal API tokens before exposing the shell to
> the subagent. (3) Execution battery: a baseline automated security test
> suite that executes cleanly in CI. Acceptance: a destructive command inside
> a Pi sub-session is contained and cannot modify the host OS; file system
> access is restricted to the repository boundary; the battery validates
> rules in CI.

Working claim:
> The spec closes #173 by (a) mapping asks 1 and 3 to work already merged on
> master — T10.1 `SandboxProvider`/`detectSandbox`/`sandboxGate` wired at
> `session_start` + `tool_call` plus the T10.4 backend evaluation
> (explicit-declaration recommendation), and T11.5's
> `security-battery.test.mjs` + cross-adapter contract running in
> `pi-tests.yml` — and (b) building the one missing piece, ask 2: name-based
> environment scrubbing at both CCT-controlled spawn boundaries (subagent
> `runSubagent` spawn and the `pi-code worktree run` worker handoff),
> config-gated default-ON, fail-closed, audited, with a new
> `security.env-scrub` capability and a battery invariant. Containment (AC-1)
> follows the already-approved T10.1/T10.4 posture: the operator's sandbox
> contains; Pi detects, gates fail-closed, and never fabricates a sandbox —
> recorded as the honest degraded boundary rather than claimed as enforced.
> File-system restriction (AC-2) maps to the shipped protected-path +
> worktree-isolation enforcement indexed by the battery.

Mismatches:
  - none

Verdict: aligned
Confidence: high

Note: re-check after recording the four user-settled decisions (default-ON,
keep-list, degraded capability, CLI-computed handoff list) in plan.md — all
four were the recommended options already reflected in the working claim;
alignment unchanged.
