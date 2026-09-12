---
feature_id: runs-attempt-history
spec_mode: lightweight
status: approved
date: 2026-09-12
issue: "none (Runs tab follow-up to #339/#340; no child issue by the owner's standing rule)"
origin:
  transcripts:
    - specs/runs-attempt-history/origin/2026-09-12-owner-directive.md
  user_messages:
    - "2026-09-12: 'the real unattended run first, using the next feature you actually want shipped—not a feature invented to exercise the harness'"
  origin_claim: |
    The Runs tab must show what the ledger now records: the reviewer
    probe's answer, a round-time reviewer fallback, and a run's earlier
    terminations after a resume — so a resumed run that landed is not
    read as a plain landing. Chosen as the feature for the sixth real
    unattended run (2026-09-12).
---

# Spec: the Runs tab shows a run's probe, fallback and earlier terminations

## Problem

`api/auto_build.py` derives a run record from `state.json`,
`events.jsonl`, `termination.json`, `verification-results.json` and
each phase's review summary. Since #334, #339 and #340 a ledger also
holds `reviewer-probe.json`, `fallback` in a round's findings file, and
`termination-<epoch>.json` files kept when a run is resumed or
terminates a second time. The record ignores all three, so the page and
`runs show` cannot say that a run was probed, fell back, or was resumed
after a termination.

## User scenarios

- US1: I open a run that terminated, was resumed and landed. The card
  says it landed after one earlier termination, and names that
  termination's reason.
- US2: I open a run whose reviewer answered the probe and failed the
  round. The card shows the probe's provider, verdict, seconds and cost,
  and the disposition beside it.
- US3: I open a run whose round fell back to another reviewer. The card
  names the reviewer that failed and the one that gated the round.
- US4: `runs show KEY` prints the same three facts.

## Requirements

- FR-1: The run record gains `probe`: from `reviewer-probe.json`,
  `{provider, requested_provider, verdict, parseable, duration_sec,
  invocation_cost_usd, error}`; `null` when the file is absent or
  unreadable.
- FR-2: The run record gains `earlier_terminations`: one entry per
  `termination-<epoch>.json` in the ledger directory — `{reason, detail,
  phase, created, file}` — sorted by `created` ascending; an empty list
  when there are none. The current `disposition` is unchanged (it still
  comes from `termination.json` or the newest escalation).
- FR-3: The run record gains `fallbacks`: one entry per phase whose
  newest round's findings file carries `fallback` — `{phase, round,
  from, error, to}` where `to` is that round's `reviewer_provider`;
  the findings file is `phase-N/review/findings-round-<round>.json` for
  the highest round present. An empty list when none.
- FR-4: `render_run` prints a probe line ("probe: <provider> answered
  <verdict> in <n>s, <cost or unmetered>" or "probe: none recorded"),
  one line per earlier termination, and one line per fallback;
  `render_list` appends "resumed after N termination(s)" to a run's line
  when `earlier_terminations` is non-empty.
- FR-5: `studio/lib/runsView.ts` gains pure `probeLine(run)`,
  `earlierTerminationsLine(run)` ("landed after 1 earlier termination
  (provider_unavailable)" / "" when none) and `fallbackLines(run)`;
  `app/runs/page.tsx` renders them on the card; `studio/lib/api.ts`
  declares the three fields; `studio/scripts/states-check.mjs` asserts
  the three helpers on a run with and without each fact.
- FR-6: Tests: `tests/test_auto_build_runs.py` builds ledgers with and
  without each artifact and asserts FR-1..FR-4, including an unreadable
  probe file and a findings file without `fallback`; every test
  function's name carries `hist_fr<N>` for the requirement it verifies.
  FR-5's states-script assertions are verified by the PR's CI `studio`
  job (admission and the verifier gate run in a throwaway worktree
  without `studio/node_modules`, so `npm run states-check` cannot be a
  verifier on this host); its deterministic verifier is a Python test
  that the three field names the helpers read are present on the
  record. The cookbook's Runs section names the three facts.

## Constraints

- Derived per request, nothing stored; the ledger format is not
  changed; no new config key.
- Studio conventions: pure helpers in `lib/runsView.ts`, asserted by
  the states script; no new page state.

## Out of scope

Rendering the full events list of an earlier termination; linking a
fallback to provider pricing; any change to the driver.
