---
spec_mode: full
feature_id: unattended-cross-harness-execution
risk_category: security
justification: |
  Adds an opt-in unattended posture that changes how ask-gated permission
  prompts are resolved, and adds a cooldown/resume supervisor for long-running
  autonomous builds. This touches safety-sensitive boundaries: permission
  decisions, checkpoint recovery, task completion detection, subprocess
  classification, and retry loops. The design is deliberately split so prompt
  resolution is reviewed before the broader orchestration work.
status: draft
date: 2026-08-04
origin:
  attachment: /Users/gosha/.codex/attachments/51c05dc8-3615-47a4-b54b-1c8478d5f4ba/pasted-text.txt
  origin_claim: |
    Generic permission profiles already solve most permission prompts, but Pi's
    autonomous profile inherits headless ask denial and Claude settings are not
    generated from the shared profiles. Long-run coherence is mostly handled by
    checkpoint + tasks.md truth. Token-limit cooldown/resume is a new
    harness-neutral orchestration feature.
---

# Plan: unattended cross-harness execution

## Existing Facts

- Pi profile resolution already supports `Profile.importPermissions?: string[]`
  and imports Claude permission profiles through
  `adapters/pi/runtime/policy/permission-profiles.ts`.
- Pi's built-in `autonomous` profile imports `relaxed` but does not currently
  set `headless.ask_resolution = "allow"`; it inherits the default `deny`.
- Pi's permission engine already has the required three-way headless policy:
  `allow`, `deny`, and `fail`. The permission engine distinguishes ask from
  deny, so ask-resolution can be loosened without weakening deny rules.
- Claude Code has shared permission profile JSON files under
  `adapters/claude-code/permissions/`, but project `.claude/settings.json`
  remains a Claude-launcher-owned generated artifact rather than a common
  profile output shared with Pi.
- Pi checkpoint recovery exists in
  `adapters/pi/runtime/workflow/checkpoint.ts`. It is intentionally degraded:
  Pi has `session_start`, but no verified `PreCompact` or `PostCompact` event.
- `scripts/auto-build-loop.sh` already owns the build-loop ledger, parking,
  resume, notifications, cost/wall-clock caps, and backend dispatch to Claude
  or Pi. The cooldown supervisor should build around this surface.

## Design

### D1: Opt-In Unattended Posture

Create a named posture instead of silently changing all interactive behavior.
The posture should resolve to the existing relaxed allow/deny set plus
`headless.ask_resolution = "allow"` and autonomous sandbox requirements.

Implementation may choose either:
- a new profile such as `unattended`, inheriting `autonomous`; or
- a narrowly documented change to `autonomous` if review decides the name
  already means "unattended".

The preferred implementation is a new explicit `unattended` profile. It avoids
surprising existing users of `autonomous` while giving mapatlas-style runs a
clear, auditable opt-in.

### D2: Shared Permission Output for Claude

Keep the shared permission profile JSON as the source. Add a generator or
launcher subcommand that produces Claude Code `settings.json` managed
permission keys from that source. The generator must:

- emit no `bypassPermissions`;
- set the Claude-side non-interactive default that is semantically equivalent
  to Pi's `headless.ask_resolution = "allow"` for residual routine asks, for
  example `permissions.defaultMode = "acceptEdits"` when that remains the
  adapter-supported setting;
- preserve unrelated user settings;
- mark or track the managed section so it can be updated idempotently;
- support drift checks over both allow/deny lists and ask-resolution semantics;
- share tests with Pi profile import expectations where possible.

This converts "Claude has hand-maintained settings" into "Claude consumes the
same shared posture through its adapter-specific settings shape."

### D3: Durable-State-First Continuity

Do not try to make Pi remember through config. The portable contract is:

1. `tasks.md` is the project truth for remaining work.
2. `.cct/pi-session.json` is the Pi checkpoint truth for active feature/phase.
3. `.cct/auto-build/<feature-id>/state.json` is the automation truth for the
   build loop.

Diagnostics should report which of those are present and usable. A future
native hook can improve the status, but it cannot replace the durable contract.

### D4: Cooldown Resume Supervisor

Add a thin supervisor around the existing build loop and launchers. The
supervisor owns:

- usage-limit classification;
- cooldown timers;
- retry caps;
- relaunching the selected harness;
- durable run journaling;
- incomplete-task detection after a clean exit.

The supervisor does not own:

- commits;
- PRs;
- merges;
- worktree cleanup;
- verification semantics;
- review decisions.

Those remain in `auto-build-loop.sh`, the worktree manager, or explicit user
commands.

### D5: Classification Honesty

Usage/token-limit detection starts as explicit pattern/exit classification over
captured subprocess output, plus the existing `auto-build-loop.sh` usage/preflight
exit signal (`1`), because there is no verified generic quota API. The ledger
must include the matched evidence and classifier version. Unknown nonzero exits
park or fail; they do not become cooldown resumes by default.

### D6: Safety Defaults

The unattended posture should reduce prompts, not reduce enforcement. The
expected safety stack for unattended long runs is:

- trusted project required for project config and recovery injection;
- sandbox required for autonomous/unattended work;
- unrestricted-host rejection preserved;
- deny rules and security floors preserved;
- review/verify gates unchanged unless explicitly overridden through their
  existing audited override paths.

## Deliverables

1. **Unattended Pi posture**: profile/config update and tests proving relaxed
   permission import plus headless ask allow, with deny invariants unchanged.
2. **Claude settings generation**: adapter-specific generated settings from the
   shared permission profiles, with idempotency and no-bypass tests.
3. **Cross-harness drift guard**: assertions proving Pi import and Claude
   generated settings agree on managed permission posture.
4. **Continuity diagnostics**: a small report over tasks/checkpoint/automation
   state, with corrupted/missing state handled honestly.
5. **Cooldown resume supervisor**: ledgered wrapper around the existing
   launchers/build-loop with explicit usage classification and retry caps.
6. **Docs**: user-facing guide for unattended runs and recovery inspection.

## Sequencing

1. Permission posture first. This is the smallest change needed for mapatlas
   unattended execution and the highest safety-review value.
2. Claude generation second. It closes cross-harness drift without touching the
   long-running supervisor.
3. Continuity diagnostics third. It documents what already works and prevents
   overclaims.
4. Cooldown supervisor last. It is the largest orchestration change and should
   land after the permission posture is trusted.

## Test Strategy

- Pi runtime tests for profile resolution and headless ask resolution.
- Permission-engine regression tests showing ask becomes allow only under the
  unattended headless posture; deny/protected/sandbox decisions remain deny.
- Claude launcher/setup tests for generated settings, idempotency, preserved
  unrelated keys, and no `bypassPermissions`.
- Drift tests over shared profile -> Pi imported config -> Claude settings.
- Checkpoint/continuity tests for missing, corrupt, untrusted, and trusted
  checkpoint states.
- Supervisor tests with mock harnesses for:
  - usage-limit output classification;
  - clean exit with tasks still unchecked;
  - cooldown wait using a test clock or injectable sleep;
  - retry cap;
  - unknown error parking;
  - no destructive git command execution.

## Open Implementation Notes

- The preferred profile name is `unattended`. If review decides
  `autonomous` should be the unattended posture, the implementation should
  document the behavior change explicitly and keep `ci` fail-fast.
- The supervisor can start as a script under `scripts/` if it composes
  `auto-build-loop.sh`. If the first implementation needs typed parsing of
  task/checkpoint state, a small helper module is acceptable, but broad driver
  rewrites are out of scope.
