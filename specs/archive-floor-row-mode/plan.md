---
spec_mode: none
feature_id: archive-floor-row-mode
risk_category: bug
justification: |
  Privacy bug fix. After a tightened project is re-ingested, archived
  trace text leaves the machine as stored, because the outbound floor
  (#457) judges it by the session's recorded mode, which `ingest --full`
  has just updated. The fix judges archived text by the trace row's own
  recorded mode, inside OutboundPolicy and the paths that apply it. There
  is no new configuration; the precedent is the spec_mode none path for a
  privacy bug (#473, #477).
status: approved
date: 2026-11-23
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/514
  transcripts:
    - specs/archive-floor-row-mode/origin/2026-11-23-owner-request.md
  origin_claim: |
    The owner, 2026-11-23: "Fix it in the shared policy in its own PR:
    decide archived text by the trace row's own redaction_mode against the
    project's current mode, in every reader of trace_document. Add to
    test_canary_floor the case "ingest and archive under none, tighten,
    ingest --full, archive not re-run", which must fail on master. Also
    check stored session-analysis outputs."
---

# Plan: archived text is judged by its own recorded mode

## The gap

`OutboundPolicy` floors a session when the project's current mode is
stricter than the mode the session was recorded under. `ingest --full`
re-records a tightened project's sessions under the current mode, so that
comparison then finds nothing to do. Archived trace rows keep the mode
they were written under until `archive --full` rewrites them; a plain
`archive` skips turns already archived. Four off-machine paths read those
rows and sent their text as stored.

The new canary case reproduces it on v2.1.0 (`86b8384`) and on master
(`6a876ba`): ingest and archive under `none`, tighten, `ingest --full`,
archive not re-run. Session analysis then carries 5 of 13 canaries, Ask
`session_turns` 3, Ask `search_text` 5, and MCP `get_session_details` 5.

## The fix

- **D1. In the policy** (`ingest/redaction.py`). `load` keeps each kept
  session's current and recorded mode. `archived_text(session, text,
  row_mode)` and `archive_floors(session, row_mode)` decide an archived
  row by its own mode against the project's current one, so a row written
  under a looser mode leaves as the metadata-only marker. A row with no,
  an empty, or an unknown recorded mode fails closed: it counts as
  `none`, never as the session's mode, which a re-ingest may have made
  stricter than the row (since `6de5f3e`). The session-level methods are
  unchanged.
- **D2. In every path that applies the floor and reads `trace_document`:**
  - `build_transcript`, which serves session analysis and Ask
    `session_turns`;
  - MCP `get_session_details`, which now checks archived rows even when
    the session itself is not floored;
  - Ask `search_text`, which skips a hit on such a row, as it skips a
    tightened session's.

  Export gets the same check in #513. The on-machine readers (the Studio
  API, the `search` CLI, `correlate_labels`) apply no floor, per #457's
  coverage ruling, and are unchanged.

## Tests

- `test_canary_floor`: the new case, tightened by the project and
  globally. It asserts the state it is about (the session re-recorded
  under `metadata-only`, its archive still under `none`), then that no
  path carries a canary. It fails on master and on v2.1.0.
- `test_redaction`: the row-level methods, a row with no recorded mode,
  and a session the policy does not know.

## Stored session analyses (checked; #515)

A session analysis survives `ingest --full` (re-ingest deletes a
session's labels and kpis, not its analyses) and records no mode. One
stored while the project was looser, whose result quotes a canary, is
returned by Ask `session_analyses` as stored after the tightening and
re-ingest, with or without an archive. That was checked with the canary
corpus on master. The row-level check cannot cover it, since there is no
row mode to judge by.

**D3 (the owner, 2026-11-23):** option (a), in its own issue and PR
(#515), without holding this fix. Each analysis records the loosest mode
of the text the judge was sent; rows stored before that count as `none`;
`error_text` is covered as well as `result_json`; and that plan
inventories every stored text column derived from session content.

## Not changed

The session-level floor and what each mode removes. No store is
rewritten.
