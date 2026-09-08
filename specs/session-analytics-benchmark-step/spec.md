---
feature_id: session-analytics-benchmark-step
spec_mode: lightweight
status: approved
date: 2026-09-08
issue: none
supersedes: session-analytics-benchmark-ui (FR-3, FR-4, FR-5 and the Studio-only constraint)
origin:
  transcripts:
    - specs/session-analytics-benchmark-step/origin/2026-09-08-owner-directive.md
  user_messages:
    - "2026-09-08: '[P2] The Benchmark section is lacking explanation and actions'"
    - "2026-09-08: 'Graph first … Then Ask, then Benchmark.'"
    - "2026-09-08 (review of PR #321 at a7f01d7): five findings on polling, inferred cause, 'organic', the Claude-Code-only boundary, and this spec"
  documents:
    - doc_internal/plans/studio-graph-search-benchmark-2026-09-08.md (§3)
---

# Spec: Benchmark explains itself; linking runs is a pipeline step

## Why this supersedes the 2026-07-18 Benchmark UI spec

That spec (#96) was a deliberately backend-free first pass: FR-4 forbade
any API/store/constants change, FR-5 required a one-shot fetch with no
auto-refresh, and the constraint was a Studio-only diff. The owner's
2026-09-08 finding — the page lacked explanation and actions, and told a
person to run a CLI command — cannot be met inside that boundary: an
action on the page needs a step behind it, and a step needs a setting
and a payload that says where it reads from. This spec records the new
contract; the old bundle stays as the history of the first pass.

## User scenarios

- US1: I open Benchmark on a fresh store and learn in two sentences what
  a benchmark run is, where results come from, and what to set or press.
- US2: I have run the harness. I set its runs folder once in Settings
  and press **Link benchmark runs** on the Benchmark page (or on
  Analysis, or Run all does it); the page shows the scan moving and then
  the attempts by result.
- US3: My run records carry no session id (older harness runs), or name
  sessions I have not loaded. The page tells me outcomes exist and no
  session is linked, and — when the last scan's counters are known —
  why, without guessing.

## Requirements

- FR-1 **Setting.** `CCT_SA_BENCHMARK_RUNS_ROOT` / `benchmark_runs_root`
  in `defaults.json`, exposed under Settings → Benchmarks with the
  folder picker. Blank by default.
- FR-2 **Pipeline placement.** Step `correlate` ("Link benchmark runs")
  runs right after `ingest` in `RUN_ALL_SEQUENCE`, before `graph`: a
  benchmark-linked session is never noise, so links must exist before
  the graph decides what to leave out.
- FR-3 **Skipped vs failed.** With the setting blank the step ends
  `done` with `skipped: true` and the reason ("no benchmark runs root
  configured"); Run all continues. With a path that is not a directory
  the step fails with that reason.
- FR-4 **One scan seam.** `correlate.run(db, runs_root, stats,
  progress)` is the whole scan: called by the CLI `correlate` command
  and by the step. One commit at the end; a failure persists nothing
  and the partial counters remain on `stats` for the caller. `progress`
  receives the live `CorrelationStats` every `PROGRESS_EVERY` records
  and once at the end; the step publishes them as its job progress.
- FR-5 **Linking boundary (unchanged from #91).** Outcomes are stored
  for every benchmark backend. Session linking applies to Claude Code
  runs whose run record carries a Claude Code session id matching a
  loaded session. The page, the step blurb, the Settings blurb and the
  cookbook say this; nothing implies every backend links.
- FR-6 **Payload.** `/api/dashboard/benchmark` adds `runs_root {path,
  configured, is_dir}` and `link_job` (the step's job state, message,
  seconds, progress).
- FR-7 **Page states**, from the payload only, pure in
  `lib/benchmarkIntro.ts`:
  - `unset` — no folder set: explanation + link to Settings.
  - `not-a-dir` — folder set but not a directory: the path, link to
    Settings.
  - `unlinked` — folder exists, no outcomes, nothing linked: the
    folder and the **Link benchmark runs** button.
  - `outcomes-only` — outcomes exist, no session linked: "N attempts
    have outcomes, but no session is currently linked." The CAUSE is
    stated only from the last scan's counters when present
    (`null_session_id`, `unmatched`, `out_of_scope`), never inferred
    from the counts alone.
  - `linked` — "L of T sessions are linked to A benchmark attempts;
    the other U are not linked to a benchmark attempt." Absence of a
    link is not evidence of organic provenance and is not called that.
- FR-8 **Polling.** The page polls while the server's job state is
  `running`, and from the moment the button is pressed until the first
  response received after that press — a stale `idle` response held by
  `useApi` must not end polling. A page opened while a scan is running
  polls from its first response. When a scan ends, the page refetches
  the outcome row.
- FR-9 **Analysis** finds steps by id, never by index; a skipped step
  shows a badge with the reason; the correlate step shows its live
  counters while running.
- FR-10 **Verification.** Unit tests for FR-2/3/4 and the payload; the
  states script asserts every FR-7 state (including the counterexample
  "outcomes + unmatched > 0 never claims the records lacked session
  ids") and the FR-8 polling transitions; `next build` and
  doc-accuracy green; a real-data walk on the owner's runs folder.

## Constraints

- No new GitHub issue (owner's standing rule); one PR.
- The correlate contract of #91/#92 is unchanged: Claude Code-only exact
  join for session links, outcomes stored for every backend.
- The judge is not involved; nothing here writes outside the scan's
  single commit.
- Studio conventions: `useApi`, `Card`, `Loading`/`ErrorNote`; every
  page state is asserted by `studio/scripts/states-check.mjs`.

## Out of scope

Broadening linking beyond Claude Code; per-record progress rendering
beyond the counters; any change to the harness's run-record format.
