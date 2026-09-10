---
feature_id: auto-build-run-surface
spec_mode: lightweight
status: approved
date: 2026-09-09
issue: "#190 §12 (no child issue by the owner's standing rule)"
origin:
  transcripts:
    - specs/auto-build-run-surface/origin/2026-09-08-owner-ordering.md
  user_messages:
    - "2026-09-08: 'not D. Take option 3, and before building it, run the unattended profile for real at least once … one real run, then option 3 over its data, then D scoped by that data'"
    - "2026-09-09: human review of PR #331 — P1 summary provenance, P2 FR-3 ordering, merge hygiene; then 'is merged'"
  documents:
    - "issue #190 §1 (terminal outcomes), §2 (cost accounting), §12 (monitor and tune)"
---

# Spec: the auto-build run surface and the human verdict

## Why now

Four real unattended runs exist (2026-09-09). Three ended
`terminated_policy` on infrastructure (a broken reviewer CLI, a stale
review workspace, a reasoning model answering with no content) and each
was fixed in the engine (#327, #329, #330); the fourth landed as PR #331
and merged after a human review requested changes. Nobody can see that
sequence without opening four directories and reading JSON. §12 asks for
one page that shows it, and for the one label the ledger cannot write
itself: what the human did with the PR.

## User scenarios

- US1: I open **Runs** in the Studio and see every auto-build attempt
  the driver has recorded on this machine: feature, profile, outcome in
  the driver's own words (`landed`, `terminated_policy`, or none yet),
  why it stopped, how far it got, what it cost against its cap with the
  estimated part distinguished, which requirements had verifiers and
  which went green, and every policy decision the driver took.
- US2: A run is in progress. The page keeps refreshing while it is live
  and stops when it concludes.
- US3: A PR from a run has been reviewed. I set the verdict on the run
  — merged unmodified, merged with fixes, or rejected — with a note, from
  the page or the CLI, and the run carries it from then on, including
  after the ledger directory is archived or pruned.
- US4: I want the same facts in a terminal or a script: `runs list`,
  `runs show`, `runs label`.

## Requirements

- FR-1 **Ledger root.** `auto_build.ledger_root` in `defaults.json`
  (`CCT_SA_AUTO_BUILD_ROOT`), default `.cct` resolved against the
  repository root when relative. The reader lists two fixed
  subdirectories beneath it: `auto-build/` (live ledgers) and
  `auto-build-archive/` (ledgers a person moved aside). Nothing else
  under the root is read. Payloads name the root as configured and
  never carry an absolute path built from it.
- FR-2 **Run record, derived per request from the ledger, stored
  nowhere.** One record per directory that has a readable `state.json`
  with an `attempt_id`; the attempt id is the run key. Fields:
  `feature_id`, `profile`, `branch`, `base_ref`, `status`, `outcome`
  (verbatim from the state: `landed`, `terminated_policy`, or `null`
  — the driver writes no other value today, and the reader invents
  none), `disposition {reason, detail, phase}` (the state plus
  `termination.json` for an unattended termination; for a parked run
  the newest escalation the state lists, read from
  `escalations/esc-N.json`), `concluded` (status is one the driver
  writes nothing after: done, terminated, parked, aborted), `live`
  (not concluded and the state's `updated` within
  `auto_build.active_window_seconds` — freshness only: the driver
  writes its state at status transitions, so a build phase longer than
  the window is stale and still running),
  `started_at`, `updated_at`, `elapsed_sec`, `caps`, `cost {metered_usd,
  estimated_usd, cap_usd}`, `phases[]` with per-phase `rounds` and
  review verdict from the phase's `review/loop-summary.json` (null when
  the phase never reached review), `fix_sessions`, commit count;
  `verifiers {admission_mapped, results {green, total, frs[]}}` from the
  frozen contract and `verification-results.json` (each null when the
  file is absent); `policy_decisions[]` = the ledger events in a fixed
  set (`POLICY_EVENTS`: terminations, parks, review-state resets,
  skipped artifacts, merge decisions, cap changes, waivers, bypasses,
  gates, downgrades); `escalations` count; `pr {number, url}`; `ledger`
  = the directory's path relative to the root; `verdict` (FR-4) or null.
  A directory whose state cannot be read is counted and named under
  `skipped`, never fatal; a second directory carrying an attempt id
  already seen is counted `duplicate` and ignored.
- FR-3 **Outcome is never collapsed.** No field, badge, summary or CLI
  line maps outcomes onto pass/fail. The summary counts runs by the
  outcome value itself and separately counts runs with no outcome yet.
- FR-4 **Verdict store.** Table `auto_build_verdict` (new DDL file, so
  `apply_ddl` creates it on the next command): `run_key` UNIQUE,
  `feature_id`, `verdict` in {`merged_unmodified`, `merged_with_fixes`,
  `rejected`}, `note`, `set_at`. Setting requires the run key to exist
  among the ledgers (404 otherwise); a verdict outlives its ledger and
  is counted `verdicts_without_ledger` in the list payload once the
  directory is gone. Clearing deletes the row. Absence is "no verdict".
- FR-5 **API.** `GET /api/runs` → `{root {path, is_dir}, runs[],
  summary {total, live, by_outcome, by_verdict}, skipped[],
  verdicts_without_ledger}`, sorted newest first by `started_at`.
  `GET /api/runs/{key}` → the record plus every ledger event and the
  triage report text when present. `PUT /api/runs/{key}/verdict` with
  `{verdict, note}` and `DELETE /api/runs/{key}/verdict`; both return
  the updated record. An unknown verdict value is a 400 that names the
  three allowed values.
- FR-6 **CLI.** `runs list [--json]`, `runs show KEY [--json]`, `runs
  label KEY VERDICT [--note TEXT]`, `runs unlabel KEY`. The terminal
  rendering shares one renderer with nothing else; the JSON is the API
  payload.
- FR-7 **Studio page** `/runs` (nav tab after Team): an opening card
  that says what a run is, which root is read and how many runs it
  holds; then one card per run with the FR-2 facts, the cost as a bar
  with the estimated portion visibly distinct from the metered one
  and the cap as the bar's length, the verifier state, the policy
  decisions, the PR link, and a verdict control (three choices, a note,
  clear). States, pure in `lib/runsView.ts` from the payload only:
  `no-root` (root is not a directory: where ledgers come from and how
  the root is set), `empty` (root present, no run), `runs`. Score trend:
  today no ledger writes a score, so the page says "no scores recorded"
  per run instead of drawing an empty chart.
- FR-8 **Polling.** The page polls while any run in the payload has
  not `concluded`, and stops on the first payload where every run has.
  Freshness is not the test: a run whose last state write is older
  than the window is still polled until it concludes, so a long build
  phase is seen to end.
- FR-9 **Verification.** Unit tests build ledgers in a temporary root
  from the four real runs' shapes (one landed with a PR, one terminated
  with `termination.json`, one parked, one unreadable, one duplicate)
  and assert FR-2/3/4/5 including the 404 and 400 paths, the orphaned
  verdict count, a park's disposition from its escalation, and a stale
  unconcluded run; the states script asserts FR-7's three states,
  the verbatim outcome wording, the estimated-versus-metered cost line
  and FR-8; `next build`, `states-check`, `unittest discover` and the
  smoke job green; a real-data walk over the four ledgers with the
  verdict of run 4 set to `merged_with_fixes`.
- FR-10 **Docs.** Cookbook: tab row, env key, a numbered section, the
  CLI one-liners. Session-analytics README: command row and a section.

## Constraints

- Python stdlib only; no new dependency; no change to existing tables.
- The driver's ledger format is not changed by this feature; the reader
  tolerates missing files and the hand-maintained archive convention.
- Nothing here calls GitHub: the verdict is what a person says it is.
- Studio conventions: `useApi`, `Card`, `Loading`/`ErrorNote`; every
  page state asserted by `studio/scripts/states-check.mjs`.
- No new GitHub issue; one PR.

## Out of scope

Increment D (adjudication, builder swap, resume); calibrated presets
from run data (§12's third paragraph — the evaluator has not run yet);
ingesting ledgers into the store; deriving the verdict from GitHub.
