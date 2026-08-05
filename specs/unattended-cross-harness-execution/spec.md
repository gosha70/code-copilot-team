# Spec: unattended cross-harness execution

Source: user-provided issue note, 2026-08-04. This spec turns three related
operational gaps into a single reviewable feature: unattended permission
posture, long-run continuity, and usage-limit cooldown resume across the
Claude Code and Pi harnesses.

## User Scenarios

- US1: As a project owner running a large build such as mapatlas, I can select
  an unattended posture that lets routine edit/build/test work proceed without
  repeated permission prompts, while deny rules, protected paths, sandbox gates,
  and security floors still fail closed.
- US2: As a maintainer of multiple copilots, I can generate the Claude Code
  settings posture from the same shared permission profile that Pi imports, so
  Claude and Pi do not drift through hand-maintained allow/deny lists.
- US3: As a long-running-session operator, when context compacts or a session is
  restarted, the harness resumes from durable project truth: the SDD
  `tasks.md`, the relevant automation ledger, and CCT checkpoint state. The
  system reports native memory limitations honestly instead of claiming Pi has a
  compaction hook it does not expose.
- US4: As an unattended-run operator, when a harness exits or blocks because of
  usage or token limits while tasks remain open, a supervisor records the event,
  waits the configured cooldown, and relaunches the same harness against the
  same worktree so work continues from durable state.

## Requirements

### Permission Posture (US1, US2)

- FR-1: The repo MUST provide a named unattended posture for long-running
  builds. It MUST combine:
  - the existing relaxed permission profile as the base allow/deny posture;
  - `headless.ask_resolution = "allow"` for ask-gated operations;
  - existing sandbox enforcement for autonomous/CI operation;
  - existing security floors, denied commands, protected paths, network/package
    policies, and trust gates unchanged.
- FR-2: `headless.ask_resolution = "allow"` MUST resolve only ask decisions. It
  MUST NOT convert deny decisions into allows, bypass protected paths, relax
  `security.fail_closed`, disable review/verify gates, or imply
  `bypassPermissions`.
- FR-3: The unattended posture MUST be opt-in and visibly named in config,
  launcher output, or diagnostics. Existing conservative profiles MUST remain
  available for interactive and CI use.
- FR-4: Pi profile resolution MUST test that the unattended posture imports the
  intended permission profile and resolves ask-gated commands/tools to allow
  only in headless mode.
- FR-5: Claude Code settings MUST be generated from the same shared permission
  profile source that Pi imports. Generated settings MUST be idempotent, must
  preserve unrelated user settings, and must never emit `bypassPermissions`.
- FR-6: Claude Code generated settings MUST include the Claude-side analog of
  Pi's `headless.ask_resolution = "allow"`: an explicit non-interactive
  default such as `permissions.defaultMode = "acceptEdits"` or the
  adapter-supported equivalent. This default MUST resolve residual routine asks
  without `bypassPermissions`, and MUST NOT weaken explicit deny rules,
  protected-path hooks, security floors, review gates, or verification gates.
- FR-7: Claude Code generated settings MUST distinguish managed keys from
  user-owned keys so switching away from the unattended posture removes or
  updates only managed permission-profile content.
- FR-8: A drift guard MUST prove the shared permission profile, the Pi imported
  layer, and the Claude generated settings remain aligned for the managed
  allow/ask/deny posture and for ask-resolution semantics. The guard MUST fail
  if Pi resolves residual asks to allow but Claude would still prompt under its
  generated settings.

### Long-Run Continuity (US3)

- FR-9: The continuity contract MUST use existing durable state as the source of
  truth: SDD `tasks.md`, `.cct/pi-session.json`, and the auto-build ledger under
  `.cct/auto-build/<feature-id>/`.
- FR-10: Pi continuity MUST remain honestly classified as degraded when the
  limitation is native context or compaction visibility. Pi currently observes
  `session_start` and can re-inject a checkpoint digest, but does not expose
  `PreCompact` or `PostCompact`.
- FR-11: Claude Code continuity MAY use native hook surfaces where available,
  but the cross-harness contract MUST still be durable-state-first so the
  supervisor can resume either adapter from the same project artifacts.
- FR-12: Any model-visible recovery digest MUST be sanitized and trust-gated
  using the existing checkpoint discipline. A tampered checkpoint or task file
  MUST NOT become unsanitized instruction text.
- FR-13: Diagnostics MUST make the continuity source explicit: native hook,
  checkpoint recovery, auto-build ledger, and tasks file status. Missing or
  corrupt state MUST be reported as absent/corrupt, never fabricated.

### Cooldown Resume Supervisor (US4)

- FR-14: The feature MUST add a harness-neutral resume supervisor around the
  existing launchers and automation driver, rather than embedding token-limit
  logic in one adapter. It MUST support at least:
  - `scripts/auto-build-loop.sh <feature-id> --resume`;
  - Pi through `pi-code`;
  - Claude Code through the existing `claude-code` wrapper or Claude CLI path.
- FR-15: The supervisor MUST maintain its own durable run ledger under `.cct/`
  with feature id, harness, worktree, attempt count, cooldowns, last exit code,
  last classified reason, and timestamps. Missing/corrupt ledgers MUST fail
  closed with a clear recovery message.
- FR-16: Usage-limit detection MUST be explicit and test-backed. The first
  implementation MAY use configured output matchers, known subprocess exit
  classifications, and `scripts/auto-build-loop.sh`'s existing usage/preflight
  exit signal (`1`), but MUST store the matched evidence. It MUST NOT rely on
  unverified vendor session stores or infer success from silence.
- FR-17: If the harness exits cleanly while `tasks.md` still has unchecked tasks
  in the active feature, the supervisor MUST treat that as incomplete work and
  either relaunch or park according to the configured policy.
- FR-18: A cooldown resume MUST:
  - wait at least the configured cooldown;
  - relaunch in the same project/worktree;
  - pass the selected unattended posture;
  - preserve the automation/checkpoint ledgers;
  - cap retries and total wall-clock time.
- FR-19: Terminal conditions MUST be deterministic:
  - success when the configured task-completion detector reports all target
    tasks complete and verification gates pass;
  - parked when a non-usage breaker occurs;
  - failed when max attempts, max cooldowns, or wall-clock caps are exceeded;
  - failed when state is corrupt and cannot be reconciled.
- FR-20: The supervisor MUST not perform destructive git operations. Commits,
  pushes, merges, cleanup, and branch deletion remain owned by the existing
  auto-build driver or explicit user action.
- FR-21: Notifications, if configured, MUST reuse the existing non-blocking
  notification contract: notify failures are journaled and never convert a
  failed/parked state into success.

### Reporting and Documentation

- FR-22: `doctor`, `features`, or equivalent diagnostics MUST report the new
  unattended posture and cooldown-resume support, including which pieces are
  enabled, degraded, or unavailable by adapter.
- FR-23: Documentation MUST include:
  - when to use unattended mode;
  - why `ask_resolution = "allow"` is not a permission bypass;
  - how to run/resume a supervised build;
  - how to inspect ledgers after a cooldown resume;
  - what Pi cannot remember natively.
- FR-24: The spec MUST include tests for prompt resolution, generated Claude
  settings, checkpoint/trust honesty, cooldown classification, task-completion
  detection, retry caps, and no-destructive-git behavior.

## Constraints

- Bash code MUST remain compatible with macOS bash 3.2.
- No new external dependency may be added without a specific implementation
  need and maintenance justification.
- No feature in this spec may disable protected-path, denied-command, sandbox,
  review, verify, or trust enforcement.
- The implementation MUST treat CLI output, task files, checkpoint files, and
  ledgers as untrusted input.
- The implementation MUST avoid parsing Pi native transcript/session storage
  unless that format is separately verified and test-backed.
- This feature MUST not claim native Pi compaction hooks, native Pi token-limit
  APIs, or native Pi multi-session memory unless those surfaces are verified.

## Out of Scope

- Creating an OS sandbox or container backend.
- Vendor quota management or billing APIs.
- Studio UI for supervised runs.
- Native Pi compaction hooks.
- Changing branch protection, release workflows, or PR merge policy.
- Broad rewrites of `scripts/auto-build-loop.sh`; the supervisor should compose
  it or add narrow extension points.
