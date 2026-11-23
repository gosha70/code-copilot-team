# Origin Alignment Check — archive-floor-row-mode

Date: 2026-11-23 15:47
Trigger: the owner's decisions of 2026-11-23 (a public issue, now #514;
D3 moved to its own issue, #515), which update `plan.md`.

## Origin sources read

- The owner's request in `origin/2026-11-23-owner-request.md`.
- Issue #514, filed from it, with the `archive --full` workaround first.
- The owner's decisions: file #514 publicly, then commit, review with
  DeepSeek and open this fix's PR; D3 as option (a) in its own issue and
  PR (#515), not holding this fix.

## Acceptance criteria — status

- Archived text is decided by the trace row's own `redaction_mode` against
  the project's current mode, in the shared policy — **met**
  (`OutboundPolicy.archived_text`, `archive_floors`).
- In every reader of `trace_document` that applies the floor — **met**:
  session analysis and Ask `session_turns` through `build_transcript`, MCP
  `get_session_details`, and Ask `search_text`. Export follows in #513 once
  this merges. The on-machine readers apply no floor, per #457's ruling.
- The `test_canary_floor` case "ingest and archive under none, tighten,
  ingest --full, archive not re-run" — **met**. It fails on master and on
  v2.1.0, with the four paths leaking 5, 3, 5 and 5 canaries of 13, and
  passes with the fix, tightened by the project and globally.
- Stored session-analysis outputs checked — **met**. The gap is
  confirmed and moved to #515, as the owner decided.

## Mismatches

None.

## Verdict

Verdict: aligned
Confidence: high
