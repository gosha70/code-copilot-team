# Spec: auto-build-loop escalation, notification, resume (increment C)

Increment C (#70). Base: driver merged in #73. Design:
specs/auto-build-loop/design.md §1.4, §2.

## User Scenarios

- US1: As a project owner away from my desk, when the loop parks or pauses I
  receive a notification through a command I configured (e.g. a Telegram
  script), telling me the feature, reason, phase, and what to do — and a
  notification failure never loses the escalation (the ledger is durable).
- US2: As a project owner resolving a breaker, I take the normal human action
  (/review-decide, fix the origin record, fix the code, raise a cap) and run
  a single `--resume`; the driver detects my resolution, marks the
  escalation resolved, and continues exactly where it left off — or tells me
  precisely what is still missing.

## Requirements

Notification (US1):
- FR-1: The driver MUST render `notify.command` (config) with placeholders
  `{feature_id}`, `{reason}`, `{phase}`, `{status}`, `{summary}` and execute
  the configured command via the repo's existing shell-execution convention
  on: every park, every milestone pause, and run completion. The command is
  user-configured but this is still a shell boundary: placeholder values MUST
  be substituted safely (no word-splitting/injection surprises from values
  containing spaces or quotes), and quoting behavior MUST be covered by
  tests. `CCT_AUTOBUILD_NOTIFY_CMD` overrides the config value.
  Empty/missing command = no-op.
- FR-2: Notification failure MUST NOT block or alter parking/pausing; it is
  journaled as `notify_failed`. The escalation record carries a `notified`
  boolean.
- FR-3: Escalation records MUST carry reason-specific history refs: breaker
  file and findings files (review_breaker), latest test log and fix-session
  count (test_failure), origin exit code (origin_gate), results dir
  (build_session_error) — plus `resolved: false` and, once resolved,
  `resolved: true` with `resolved_at`.

Parked resume (US2):
- FR-4: `--resume` on a parked run MUST dispatch on the newest unresolved
  escalation's reason and re-derive resolution from artifacts, never from
  flags:
  - `review_breaker`: /review-decide approve (bypass loop-summary present) →
    the phase's review gate accepts the human-approved bypass and the run
    continues; reject → terminal status `aborted` (exit 0 with a clear
    message); retry → re-enter the review loop honoring the runner's
    attempt/round-numbering semantics.
  - `review_breaker` parking MUST preserve the active `.cct/review/` state
    in place (breaker-tripped.json, state.json, findings) — /review-decide
    operates on that live state; the driver archives review state only on
    PASS, and resume MUST NOT re-initialize `.cct/review/state.json` when
    resuming a parked review (a retry decision relies on the existing
    attempt counter and monotonic round numbering).
  - `origin_gate`: re-run check-origin-alignment.sh; exit <= 1 resolves.
  - `test_failure`/`build_session_error`/`git_anomaly`: clean worktree
    required; re-run test.command; exit 0 resolves and re-enters the phase.
  - `provider_unavailable`: re-run providers-health --provider; exit 0
    resolves.
  - `cap_exceeded`: re-read `caps` from automation.json into the snapshot;
    resolves iff no cap is currently exceeded.
- FR-5: The PASS hard gate MUST accept `bypass: true` ONLY when the ledger
  records a human-approved bypass for the SPECIFIC parked phase and
  escalation (set during review_breaker approve-resume); any other bypass —
  including one recorded for a different phase — still parks. Approval is
  single-use, not a standing exemption.
- FR-6: Unresolved parked resume MUST print the exact needed action for the
  reason (e.g. "run /review-decide approve|reject|retry", "produce a fresh
  origin-alignment record or commit origin-divergence.md") and exit 1
  without side effects.
- FR-7: On resolution: mark the escalation resolved, journal `resumed`,
  notify (`reason=resumed`), and continue with the existing idempotent
  re-entry (no duplicate commits, no re-run of archived reviews).
- FR-8: Milestone sign-off resume behavior from increment B is unchanged and
  also notifies on pause.

Tests + docs:
- FR-9: New assertions with a file-appending notify stub: rendered
  placeholders on park/milestone/done; notify failure does not change exit
  codes; resume paths approve/reject/retry, origin-restore, test-fix,
  cap-raise; unresolved refusal message names the needed action; counts
  updated in tests/test-counts.env and README.
- FR-10: auto-build-loop skill resume playbook updated (per-reason table);
  adapters regenerated with zero drift.

## Constraints

- Bash 3.2 compatible; jq for JSON; no new dependencies.
- No push/gh/PR code in this increment (WIP-push relocated to #71).
- Resolution detection is artifact-based only — no `--force-resume`-style
  bypass flags; origin semantics unchanged (driver never authors origin
  artifacts).
- Advisory profile remains the only profile; fail-closed parking preserved
  (no proceed-anyway path).
- One issue per PR: this bundle covers exactly #70 (as amended).
- Linux parity verified in a container before review (bash >= 4 errexit
  semantics differ from macOS bash 3.2).
