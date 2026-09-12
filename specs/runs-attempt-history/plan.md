---
spec_mode: lightweight
feature_id: runs-attempt-history
risk_category: ui
justification: |
  Three derived fields on an existing per-request reader, three pure
  view helpers and their rendering, tests on both sides. FR-1..FR-6 in
  spec.md state the behaviour. Small on purpose: the feature for the
  sixth real unattended run.
status: approved
date: 2026-09-12
issue: none
origin:
  transcripts:
    - specs/runs-attempt-history/origin/2026-09-12-owner-directive.md
  user_messages:
    - "2026-09-12: 'the real unattended run first, using the next feature you actually want shipped'"
  origin_claim: |
    Show on the Runs tab what the ledger records since D1/D2: the probe's
    answer, a round-time fallback, and earlier terminations after a
    resume, so a resumed run that landed is not read as a plain landing.
---

# Plan: the Runs tab shows a run's probe, fallback and earlier terminations

## Deliverables

1. `scripts/session_analytics/api/auto_build.py`: `_probe(ledger)`,
   `_earlier_terminations(ledger)`, `_fallbacks(state, ledger)`; the
   three fields in `read_run`; `render_run` / `render_list` lines
   (FR-1..FR-4). Constants for the file patterns in `constants.py`.
2. `studio/lib/api.ts` (types), `studio/lib/runsView.ts` (`probeLine`,
   `earlierTerminationsLine`, `fallbackLines`), `studio/app/runs/page.tsx`
   (render), `studio/scripts/states-check.mjs` (assertions) (FR-5).
3. `scripts/session_analytics/tests/test_auto_build_runs.py` (FR-6);
   `docs/session-analytics-cookbook.md` §8.6 sentence.

## Test strategy

Deterministic only: Python unit tests over temporary ledgers (the
existing `_write_ledger` helper accepts extra files), and the Studio
states script for the helpers. The suite command is the session-
analytics pytest run with the host-`.env` cases deselected, plus the
states script.
