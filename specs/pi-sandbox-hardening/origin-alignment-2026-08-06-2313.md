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

Note: re-check after resolving the pre-commit review finding on launcher
scrub-off trust semantics. The spec now encodes the FR-004a asymmetry:
untrusted project config may only TIGHTEN scrub policy (env_scrub_extra);
loosening (env_scrub=false, env_scrub_keep) requires a trusted scope
(global/user config, or project config in a positively-trusted session), and
the out-of-session CLI never honors a project-local opt-out. This narrows
HOW the origin ask is enforced; the origin scope itself is unchanged.

Note: re-check after recording build-phase-1 deltas (plan D0): provenance-
based asymmetry instead of the floor engine, runner-contract scrub (no live
runSubagent caller), launcher boundary global/env/cli-scope only with the
handoff audit at worker session_start. Implementation-level HOW changes; the
origin scope (strip host credentials before exposing the shell to the
subagent) is unchanged and now partially delivered (subagent boundary).
