---
spec_mode: full
feature_id: auto-build-loop-escalation
risk_category: integration
justification: |
  Extends the merged driver (#69/#73) with the human-facing escalation loop:
  pluggable notification, per-reason --resume resolution detection, and
  escalation-record enrichment. Touches the driver's park/resume core and
  adds reason-specific re-entry logic; all coverage via the existing
  mock-based suite. Series design: specs/auto-build-loop/design.md.
status: approved
date: 2026-07-13
issue: 70
origin:
  issue: gosha70/code-copilot-team#70
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/70
  origin_claim: |
    Issue #70 (increment C): (1) escalation records with full failure
    history (breaker file, findings files, test logs, fix-session count,
    origin exit); (2) pluggable notify.command with {feature_id} {reason}
    {phase} {status} {summary} placeholders, failure never blocks parking;
    (3) --resume resolution detection — /review-decide outputs, fresh
    origin-alignment record or committed origin-divergence.md, milestone
    approved-by sign-off; missing artifact prints exactly what is needed
    and exits non-zero; idempotent re-entry. (4) WIP-push-on-escalation —
    relocated to #71 by user-approved scope amendment (2026-07-13); issues
    #70/#71 and the series design phasing updated accordingly.
    Tests: breaker -> record +
    notify stub; resume approve/reject/retry; refusal on missing artifact;
    no duplicate commits on mid-phase resume.
---

# Plan: auto-build-loop escalation, notification, resume (increment C)

Design reference: `specs/auto-build-loop/design.md` §1.4 (escalation record),
§2 (escalation/notification), decisions 5-6. Base: driver merged in #73.

## Deliverables

1. **Notification** (`scripts/auto-build-loop.sh`): `notify()` renders
   `notify.command` (config; `CCT_AUTOBUILD_NOTIFY_CMD` overrides) with
   placeholders `{feature_id} {reason} {phase} {status} {summary}`, runs it
   via `bash -c`; failure is logged, never blocks. Fired on: park, milestone
   pause, run done.
2. **Escalation record enrichment**: history refs per reason (breaker file,
   findings files, latest test log, fix-session count, origin exit code);
   `resolved`/`resolved_at` lifecycle; `notified` flag.
3. **Parked `--resume` resolution detection** (replaces the increment-B
   refusal), per reason:
   - `review_breaker`: read `/review-decide` outcome — approve (bypass
     loop-summary) accepts the phase review as human-approved bypass (the
     PASS hard gate learns this exception), reject → status `aborted`,
     retry → re-enter in-review with the runner's retry semantics.
   - `origin_gate`: re-run `check-origin-alignment.sh`; exit <= 1 resolves
     (fresh record or committed origin-divergence.md produced by the human).
   - `test_failure` / `build_session_error` / `git_anomaly`: require clean
     worktree, re-run `test.command`; green resolves and re-enters the phase
     flow (existing idempotent build/commit skip logic).
   - `provider_unavailable`: re-run targeted provider health; usable resolves.
   - `cap_exceeded`: re-read caps from `automation.json` (refresh the
     snapshot's caps only); resolves iff the new caps are no longer exceeded.
   - Unresolved: print the exact artifact/action needed per reason, exit 1.
   - On any resolution: mark the escalation `resolved`, journal, notify.
4. **Tests** (`tests/test-auto-build-loop.sh` extensions): notify stub
   (file-appending command) fired on park/milestone/done with rendered
   placeholders; resume paths — review approve → completes, reject → aborted,
   retry → re-reviews; origin resolved via internal-origin restore;
   test_failure resolved by fixing the fixture test; cap raised in config
   resolves; unresolved parked resume still refuses with actionable message.
   Counts registered in `tests/test-counts.env`; README count synced.
5. **Docs**: `shared/skills/auto-build-loop/SKILL.md` — replace the
   "increment C pending" resume note with the per-reason resolution playbook;
   regenerate adapters.

## Out of scope

- WIP-push-on-escalation (relocated to #71 with the pr profile; user-approved amendment).
- New notification transports (the command template IS the transport;
  Telegram/webhook scripts are user config).
- `pr`/`merge` profiles (#71, later).

## Test strategy

Mock-only as before (CCT_CLAUDE_BIN, CCT_PROVIDER_PROFILE, notify stub file).
Every new resume path lands with a same-PR assertion. Linux parity: run the
suite once in an ubuntu container before requesting review (lesson from #73:
macOS bash 3.2 masks Linux bash errexit semantics).
