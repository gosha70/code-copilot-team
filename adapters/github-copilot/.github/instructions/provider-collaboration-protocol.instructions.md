---
applyTo: "**"
---

# Provider Collaboration Protocol

Rules governing cross-provider peer review in dual-copilot sessions.

## Session Flags

Peer review is enabled per-session via launcher flags:

- `--peer-review [provider-name]` — enable peer review; optional provider override.
- `--peer-review-off` — disable peer review.
- `--peer-review-scope code|design|both` — review scope (default: `both`).

Environment variables set by launcher:
- `CCT_PEER_REVIEW_ENABLED` — `true` or `false`.
- `CCT_PEER_PROVIDER` — explicit provider name or empty (use profile default).
- `CCT_PEER_TRIGGER` — `phase-complete` (only supported value).

## Trigger Semantics

Peer review is triggered **only** by the `/phase-complete` command, not by every session stop.

1. Developer runs `/phase-complete` at the end of a phase.
2. Command writes `.cct/review/pending.json` with required fields.
3. Stop hook checks for the marker and invokes the peer-review runner.
4. Runner processes the marker, writes collaboration artifacts, then deletes/archives the marker.

The stop hook is a **consumer** of the marker, not a producer. Without a marker, the hook is a no-op.

## Marker Contract

Path: `.cct/review/pending.json` (project root).

Required fields:
- `feature_id` — matches `specs/<feature-id>/`
- `phase` — `plan` or `build`
- `target_ref` — git ref (branch or commit SHA)
- `subject_provider` — the provider that did the work (e.g., `claude`)
- `peer_provider` — the provider that will review (e.g., `codex`, or empty for profile default)
- `review_scope` — `code`, `design`, or `both`
- `request_id` — unique identifier (UUID or timestamp-based)
- `requested_at` — ISO 8601 timestamp

### Marker Lifecycle

1. **Created** by `/phase-complete` command.
2. **Consumed** by peer-review runner on stop hook.
3. **Deleted or archived** after processing — success or fail.
4. **Stale markers** (where `requested_at` is older than session start, or required keys are missing) are warned and skipped.

## Artifact Schema

Collaboration artifacts live under `specs/<feature-id>/collaboration/`.

Artifact types:
- `plan-consult.md` — peer review of the plan phase.
- `build-review.md` — peer review of the build phase.

### Frontmatter (aligned with SDD conventions)

```yaml
---
feature_id: [feature-id]
date: [YYYY-MM-DD]
status: [draft | final]
phase: [plan | build]
mode: [consult | review]
subject_provider: [provider that did the work]
peer_provider: [provider that reviewed]
peer_profile: [profile name from providers.toml]
runner_fingerprint: [command template hash + provider version]
verdict: [PASS | FAIL | INCONCLUSIVE]
blocking_findings_open: [integer]
target_ref: [git ref]
---
```

## Fail-Closed Runtime Rule

When `CCT_PEER_REVIEW_ENABLED=true` and a valid marker exists:
- The session blocks until the peer-review runner succeeds.
- Runner failure (timeout, auth error, provider crash) blocks the stop event (exit 2).

### Local Escape Hatch

- Set `CCT_PEER_BYPASS=true` or run with `--peer-review-off` to unblock the session.
- Bypass events are logged in artifact metadata (`bypass: true`).
- CI rejects PRs with bypass artifacts — local bypass does not circumvent merge gates.

## CI Verdict Policy

CI validator (`scripts/validate-collaboration.sh`) fails the PR when:

1. Required collaboration artifacts are missing (when `collaboration_mode: dual` in plan.md).
2. `verdict != PASS`.
3. `blocking_findings_open > 0`.
4. `subject_provider == peer_provider` (profile-name level).
5. Bypass artifacts are present.

## Identity Policy

- Provider identity is enforced at the **profile name** level from `providers.toml`.
- `runner_fingerprint` records the command template hash and provider version for audit.
- Wrapper-level spoofing detection is out of scope for v1.

## Provider Profile

Global registry: `~/.code-copilot-team/providers.toml`.

See `shared/templates/provider-profile-template.toml` for schema and seed file.
