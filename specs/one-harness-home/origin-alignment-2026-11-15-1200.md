# Origin alignment check — one-harness-home (planning bundle)

Date: 2026-11-15 12:00 EST

Origin: issue #411 (body as of 2026-11-15, no comments) and the
repository at `56c2e5d`, recorded in
`origin/2026-11-15-issue-411-origin.md`.

| Issue | Bundle |
|---|---|
| Two homes; decide once, migrate as one change | spec.md § Why; D1, D4 |
| Option A: `~/.cct/` wins; one helper per language; fallback read for one minor release; doctor notice | FR-1, FR-2, FR-3, FR-6, FR-11 |
| Option B | rejected in D1 with the reason (the project-level `.cct/` would still differ) |
| Rejected: move only `providers.toml`; symlink | Constraints: no symlink; FR-5 no silent move |
| Risks: missed reader hides the move; Pi manifest records path and hash | FR-9 guard; D5 keeps the per-project config and its manifest where they are |
| Compatibility: fallback for one minor release, doctor notice, CHANGELOG | FR-3, FR-6, FR-10, FR-11 |
| Timing: decide at 2.1 | the Unreleased line is 2.1; FR-11 names 2.2 for the removal |

## Deviations and narrowings, each stated

- **Per-project convention (D5).** Option A includes moving
  `.code-copilot-team/config.toml` to `.cct/config.toml`. The bundle
  recommends keeping it, because `.cct/` is the untracked runtime-state
  directory and committed configuration inside it needs a gitignore
  exception in every project. This is a narrowing of Option A awaiting
  the owner's ruling; if ruled the other way it becomes its own issue
  (D4).
- **`cct home migrate`** is an addition the issue does not name; the
  issue forbids silent moves by implication (its symlink objection) and
  asks for a doctor notice, so the explicit mover is the only path from
  the notice to a migrated home.

## Open decisions

D1–D6 are proposed with recommendations and marked
`[NEEDS CLARIFICATION]` in spec.md. Build does not start until ruled.

Verdict: aligned
Confidence: high
