---
feature_id: auto-build-hill-chart
spec_mode: full
status: approved
date: 2026-11-11
issue: "#405"
origin:
  issue: "#405"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/405
  transcripts:
    - specs/auto-build-hill-chart/origin/2026-11-11-issue-405-origin.md
---

# Spec: auto-build moves the pitch's hill-chart scopes as phases land

## Why

A Shape-Up cycle driven by the auto-build driver ends with every scope
of its pitch still `uphill`, because nothing in the driver touches
`hill.json`. `/cooldown` then suggests `shelved` for a cycle that
shipped, and the operator sets the scopes `done` by hand after the
fact, which is what happened on wiki-studio cycles 03 and 04. The hill
chart is the cycle's only progress record, so it must move with the
phases that actually land.

The driver already knows when a phase lands: after the review rounds,
the phase gate's origin re-check and artifact commit, and the coverage
gate. The pitch already names the scope each phase serves in its task
headings. This feature connects the two and nothing more.

## User Scenarios

1. **Driver-built cycle.** A pitch is `building` with `hill.json` from
   `/cycle-start`. Its `tasks.md` has `## US1: Templates (S1)`,
   `## US2: Agents (S2)` and `## US3: Docs (S2)`. The operator runs
   `claude-code build <pitch-id>`. When phase 1 starts, S1 moves to
   `downhill`; when phase 1 lands, S1 moves to `done` and `hill.json`
   is committed with a note naming the phase and its landed commit.
   Phase 2 moves S2 to `downhill`; S2 reaches `done` only when phase 3,
   the last phase mapped to it, lands. `/cooldown` then suggests
   `shipped` with a true hill summary.
2. **Ordinary feature, unchanged.** `claude-code build <feature-id>`
   on `specs/<feature-id>/` with no `hill.json` behaves exactly as
   today: no file created, no journal line, no commit.
3. **Phase without a scope.** A pitch phase heading carries no `(S<n>)`
   token, or names `S9` which `hill.json` does not have. Preflight
   prints the mapping with the gap named and exits before the first
   phase: the dependency between a phase and its scope is a planning
   fact the SDD must state, so the planner or developer fixes
   `tasks.md` and reruns. A scope that no phase names is allowed; it
   stays where it is and the run summary shows it so `/cooldown`'s
   partial-shipped question sees it.
4. **Parked before landing.** Phase 2 moves S2 to `downhill`, then the
   coverage gate parks the run. `hill.json` says `downhill`, which is
   true. On `--resume` the phase lands and S2 moves to `done` once.
5. **Hand-moved scope.** The operator ran `/hill S1 done` before the
   driver landed phase 1. The driver leaves `done` alone and adds no
   note; it never moves a scope backwards.

## Requirements

- **FR-1 Pitch resolution.** The driver resolves `<feature-id>` as
  `specs/<id>` and, when that directory is absent and
  `specs/pitches/<id>` exists, as the pitch directory, the same rule
  `validate-spec.sh` and `check-origin-alignment.sh` apply. `FEATURE_ID`
  stays the bare id in the ledger, branch, commit messages and
  notifications. The review-round runner resolves the same way for its
  spec listing and collaboration artifacts, and the driver passes the
  resolved collaboration directory to it, so a pitch run never creates
  a stray `specs/<id>/` beside the pitch.
- **FR-2 Activation.** Hill-chart automation is active when
  `$SPEC_DIR/hill.json` exists. With no `hill.json` the driver writes
  no hill event, file, commit or summary line, and the pre-existing
  suite fixtures pass unchanged at their pins; a stronger byte-for-byte
  comparison against the previous driver is not claimed.
- **FR-3 Mapping.** A phase maps to every scope id named by `(S<n>)`
  tokens in its title, as `enumerate_phases` already produces it from
  `## US<n>:` headings or the `phases.phases` override; several tokens,
  `(S1)(S2)` or `(S1, S2)`, map the phase to each. A scope may be named
  by several phases. No `automation.json` key is added; the mapping is
  read from the pitch, the issue's second form. The mapping is a
  planning fact: every phase of a pitch run must name at least one
  scope that exists in `hill.json`, and the driver never infers one.
- **FR-4 Preflight gate.** With automation active, preflight journals
  and prints one line per phase, `hill: phase <n> -> S1 S2`, and then
  refuses the run before the first phase, with exit 1 (the driver's
  configuration-refusal code, the same as a missing `tasks.md`) and
  the list of gaps, when any phase has no token (`hill: phase <n> -> (no scope)`)
  or names a scope id absent from `hill.json` (`hill: phase <n> ->
  S9 not in hill.json`). The message names `tasks.md` as the file to
  fix. A scope that no phase names is not a gap. The mapping is frozen
  in the ledger (`hill-map.tsv`) by the attempt that starts the run; a
  `--resume` whose live mapping differs from the frozen one refuses
  with exit 1 naming each changed phase, so a phase started against one
  scope can never credit another.
- **FR-5 Transitions.** When a phase's build session is about to start,
  each mapped scope at `uphill` moves to `downhill` with
  `note = "auto-build: phase <n> started"`. When a phase lands, which
  is the point where the ledger marks the phase `done` after the
  coverage gate, each mapped scope moves to `done` with
  `note = "auto-build: phase <n> landed <sha>"`, unless another phase
  not yet landed also maps to it, in which case it stays `downhill`.
  The driver never moves a scope backwards and never touches a scope
  already at the target status. Each write updates the scope's
  `last_updated` and the root `updated_at`, is atomic (temp file in
  the same directory, then rename), and preserves every other field.
  A chart the driver cannot write (unparseable JSON, no temp file)
  parks the run with reason `hill_chart_error`: unlike a failed
  commit (FR-6), a failed write leaves nothing a later commit could
  heal, and a run must not finish over a stale chart. A write is
  exactly one matching scope in a known status, a rewrite that parses
  and holds the scope at the target, a checked mode and a checked
  rename; the chart is written before the ledger marks the phase done,
  so the park leaves the phase at its coverage gate and a repair commit
  plus `--resume` re-enters there, reviews the repair, and lands the
  remaining scopes once.
- **FR-6 Commit.** The `downhill` change rides in the phase's own build
  commit, since `driver_commit` without paths stages everything. The
  `done` change is committed on its own, scoped to `hill.json`, with
  the message `docs(<feature-id>): phase <n> hill chart [auto-build]`,
  after the ledger marks the phase done and before the push; a no-diff
  result is silent. A git failure is retried once after a short pause
  (`CCT_HILL_COMMIT_RETRY_SEC`, default 2, to clear a transient index
  lock); a second failure is journaled as `artifact_skipped` without
  parking, since the dirty `hill.json` is swept into the next build
  commit or the final automation-summary commit, both of which stage
  it. The landed `sha` in the note is the phase's `last_reviewed_ref`.
- **FR-7 Completion.** The run summary gains one line, `Hill chart:
  S1=done S2=done S3=uphill`, and the journal an event `hill_final`
  with the same text. Scopes no phase mapped are left untouched; the
  driver never sets every scope `done` at close. `/cooldown`'s existing
  partial-shipped question covers the rest.
- **FR-8 Resume.** Transitions are idempotent under `--resume`: a phase
  the ledger already marks done is skipped as today, so its scopes are
  not re-stamped; a phase re-entered at the coverage gate lands once.
- **FR-9 Docs.** `docs/auto-build.md` gains a "Hill chart" section;
  the `/hill` command, `/cooldown` and the `scope-executor` agent each
  gain one sentence stating that the driver moves scopes at phase start
  and landing after its own gates, so a driver-built cycle reaches
  `/cooldown` with a true chart; generated copies regenerate;
  CHANGELOG entry under Unreleased → Added.

## Constraints / What NOT to Build

- No `automation.json` key, no schema change, no new config surface.
- No change to `/hill`'s transition table, `/cycle-start`, or the
  `scope-executor` agent's own behaviour.
- No forced completion of unmapped scopes at run end.
- No bet-log entry written by the driver; `/cooldown` owns the bet log.
- No change to `enumerate_phases`'s heading grammar.
- No new reviewer, gate, or escalation.

## Key Entities

| Entity | Where | Role |
|---|---|---|
| hill chart | `specs/pitches/<id>/hill.json` | per-scope status the driver moves |
| phase → scopes map | derived at preflight from phase titles | which scopes a landing phase completes |
| hill commit | `docs(<id>): phase <n> hill chart [auto-build]` | the `done` transition's own commit |
| `hill_final` | journal event and summary line | final chart state for `/cooldown` |

## Decisions (ruled by the owner on 2026-11-11)

- **D1 Mapping source.** `(S<n>)` tokens in phase titles, no config
  key. **Ruled 2026-11-11 by the owner:** the phase-to-scope
  dependency is a planning fact the SDD artifact must state
  explicitly, and a gap is confirmed with the developer, never
  inferred by the driver; for an unattended run that means preflight
  refuses before the first phase (FR-4).
- **D2 Unmapped scopes.** Left untouched and reported, never forced
  `done` at close. **Ruled 2026-11-11 by the owner: as recommended.**
- **D3 Landing point.** `done` after the coverage gate, where the ledger
  marks the phase done, not at the phase gate's artifact commit.
  **Ruled 2026-11-11 by the owner: as recommended.**
- **D4 Hill commit failure.** **Ruled 2026-11-11 by the owner: retry
  once, then journal** (FR-6). Parking was rejected because an
  unattended run should not halt on a progress-display file; a plain
  journal was rejected in favour of one retry for the transient
  index-lock case.
- **D5 Driver marks `done`.** The driver's gates (review rounds,
  verifier and coverage gates) stand in for the human verification the
  `scope-executor` text reserves to `/hill`. **Ruled 2026-11-11 by the
  owner: as recommended**, with the one-sentence doc updates in FR-9.

## Success Criteria

| Criterion | Proof |
|---|---|
| A driver-built cycle reaches `/cooldown` with its scopes moved | suite: two-phase pitch fixture ends `S1=done S2=done`, hill commit present per phase |
| Features without a hill chart are unchanged | suite: a feature fixture produces no hill event, file, commit or summary line, and every pre-existing fixture passes unchanged at its pin |
| A phase without a scope, or naming an unknown scope, stops the run before it builds | suite: preflight exit 1 with the gap named, no phase run, no commit; a scope named by no phase is allowed |
| A failed hill commit retries once, then is journaled and self-heals | suite: a one-shot failing git stub makes the retry succeed; a persistent failure journals `artifact_skipped`, the run completes, and the final summary commit carries `hill.json` |
| Parked before landing leaves `downhill`; resume lands once | suite: coverage-gate park fixture, then `--resume` |
| Shared scope completes on its last phase | suite: `(S2)` on phases 2 and 3 |
| Never backwards, never re-stamped | suite: pre-set `done` scope keeps its note |
| Pins move together | `tests/test-counts.env` and `docs/repo-structure.md` in the same commit |

## Out of scope

Scope automation for session-driven (non-driver) cycles; a `/hill`
history; bet-log automation; the `## US1 + US7` heading form of the
dogfood pitch.
