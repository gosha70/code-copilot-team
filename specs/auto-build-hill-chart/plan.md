---
spec_mode: full
feature_id: auto-build-hill-chart
risk_category: integration
justification: |
  Changes the autonomous build driver's phase loop (a policy surface
  with a 1,297-assertion suite), adds a pitch-directory resolution
  rule, writes a file the Shape-Up commands own, and touches three
  command/agent documents with generated copies. FR-1..FR-9 in spec.md.
status: approved
date: 2026-11-11
issue: "#405"
origin:
  issue: "#405"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/405
  transcripts:
    - specs/auto-build-hill-chart/origin/2026-11-11-issue-405-origin.md
  origin_claim: |
    An auto-build run never moves the active pitch's hill-chart scopes,
    so every driver-built cycle reaches /cooldown with all scopes
    uphill. Map each phase to a scope read from the pitch and set the
    scope done when its phase lands.
---

# Plan: auto-build moves the pitch's hill-chart scopes

## Shape

One driver change in three small functions plus the resolution rule;
one new test block; one doc section and three one-sentence notes.

1. `resolve_spec_dir` in `auto-build-loop.sh`: `specs/<id>`, else
   `specs/pitches/<id>` (FR-1); the same resolution in
   `review-round-runner.sh`, and the driver passes
   `CCT_REVIEW_COLLAB_DIR` so review artifacts land in the pitch dir.
2. `hill_*` helpers, defined only in terms of `jq`, `now_iso` and the
   existing `journal`/`driver_commit`: `hill_active`, `hill_map`
   (phase → scope ids from `enumerate_phases` titles), `hill_preflight`
   (FR-4: prints the map, refuses on a gap with exit 2), `hill_set
   <scope> <status> <note>` (atomic write, forward only, idempotent),
   `hill_phase_start <n>`, `hill_phase_landed <n> <sha>` (last-phase
   rule, scoped commit with one retry, FR-5/6), `hill_final` (FR-7).
3. Call sites: `hill_preflight` at the end of preflight;
   `hill_phase_start` in `run_phase` before the build session;
   `hill_phase_landed` right after the ledger's `.phases[p].status =
   "done"` and before `push_branch`; `hill_final` before the automation
   summary commit so the summary line is inside it.
4. Docs: `docs/auto-build.md` § Hill chart; one sentence each in
   `adapters/claude-code/.claude/commands/hill.md` (source of the
   plugin and pi copies), `cooldown.md`, and
   `claude_code/.claude/agents/scope-executor.md` (source of the
   adapter copies); regenerate with `scripts/generate.sh`; CHANGELOG.

## Interfaces

- `hill_map` output: `<n>\t<S-ids space-separated or empty>` per phase,
  computed once at preflight and stored in the ledger as
  `.hill.map` so `--resume` uses the same mapping.
- `hill_set` returns 0 when it wrote, 1 when the scope was already at
  or past the target; an unknown scope cannot reach it because
  preflight refused the mapping.
- `hill_preflight` exit 1 is a configuration refusal, the same code as
  a missing `tasks.md`; it happens before the ledger is written.
- The hill commit message: `docs(<feature-id>): phase <n> hill chart
  [auto-build]`, path-scoped to `$SPEC_DIR/hill.json`.

## Test strategy

In `tests/test-auto-build-loop.sh`, a `setup_pitch` helper beside
`setup_project` that writes `specs/pitches/demo-pitch/` with plan,
spec, tasks (`## US1: One (S1)`, `## US2: Two (S2)`, `## US3: Three
(S2)`), a `pitch.md` with `bet_status: building`, and a `hill.json`
with S1–S3 `uphill`; the driver runs as `demo-pitch`. Cases: full run
ends `S1=done S2=done S3=uphill` with three hill commits; no-token
phase and unknown-scope token each refuse at preflight (exit 2, no
phase run); coverage-gate park then resume; pre-set `done` scope
untouched; hill-commit failure retried once (one-shot failing `git`
stub) and journaled on persistent failure with `hill.json` carried by
the summary commit; existing feature fixtures produce no hill events. Pins: `TEST_AUTO_BUILD_LOOP_EXPECTED_PASS` and
`docs/repo-structure.md` in one commit; `test-generate` for the
regenerated copies.

## Risks

| Risk | Mitigation |
|---|---|
| A scope marked `done` before its verification | `done` only after the coverage gate; park leaves `downhill` |
| The hill write sweeps into the wrong commit | `downhill` rides the build commit by design; `done` is a scoped commit |
| A phase is built with no scope to credit | Preflight refuses the run on a mapping gap (D1) |
| A transient git failure leaves the chart behind the branch | One retry, then journal; the next build or summary commit stages `hill.json` (D4) |
| Resume double-stamps | ledger already skips done phases; `hill_set` is idempotent |
| A resumed run credits a different scope than the phase started against | the mapping is frozen in the ledger; a live map that differs refuses the resume |
| The run finishes over a chart it could not write | a write failure parks as `hill_chart_error`; only a commit failure is retried and journaled |
| Feature runs change | activation needs `hill.json`; suite asserts unchanged journal and commits |

## Delivery gates

`validate-spec.sh --feature-id auto-build-hill-chart`, origin gate,
`tests/test-auto-build-loop.sh`, `tests/test-generate.sh`,
`generate.sh --check`, doc accuracy, `git diff --check`,
`pre-pr-check.sh --closes 405`, peer review, CI green on the final
head read from GitHub.
