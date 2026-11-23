# Origin Alignment Check — archive-floor-row-mode

Date: 2026-11-23 14:32
Trigger: first alignment record for this fix (gate exit 4), written with
the fix and its tests, before review.

## Origin sources read

- The owner's request of 2026-11-23, in
  `origin/2026-11-23-owner-request.md`: the gap found in PR #513's review;
  the four off-machine paths that leak on v2.1.0; the fix to make; the
  canary case to add; and the stored session-analysis outputs to check.

## Acceptance criteria — status

- Archived text is decided by the trace row's own `redaction_mode` against
  the project's current mode, in the shared policy — **met**:
  `OutboundPolicy.archived_text` and `archive_floors`.
- In every reader of `trace_document` that applies the floor — **met** for
  session analysis and Ask `session_turns` (through `build_transcript`),
  MCP `get_session_details` and Ask `search_text`. Export follows in #513.
  The on-machine readers apply no floor, per #457's ruling, and are named
  in the plan.
- `test_canary_floor` gains "ingest and archive under none, tighten,
  ingest --full, archive not re-run", which must fail on master — **met**.
  It fails on master and on v2.1.0, with all four paths leaking (5, 3, 5
  and 5 canaries of 13), and passes with the fix, tightened by the project
  and globally.
- Stored session-analysis outputs checked — **met, with a finding**. They
  survive the re-ingest, record no mode, and are returned as stored after
  the tightening, with or without an archive. The fix is an open decision
  (D3 in the plan) for the owner.

## Mismatches

None. D3 is open, not a deviation.

## Verdict

Verdict: aligned
Confidence: medium
