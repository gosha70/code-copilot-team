# Origin Alignment Check — redaction-canaries

Date: 2026-11-19 18:00
Trigger: phase-complete gate for the implementation (tasks 1–14 done).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/457.
- `origin/2026-11-19-owner-decisions.md` (scoping rulings and both spec
  reviews) and the approved spec, plan and tasks.

## Origin claim (verbatim)

> Plant canary secrets in test fixtures and assert they never appear in any
> excerpt or judge-bound output. … If a future contributor adds a new
> excerpt path that skips redaction, the canary will surface in the test
> output and fail the build.

## What was built, against the spec

- FR-001: `tests/fixtures/canary/` holds the transcript template, the two
  steering files and `canaries.json` (13 canaries, one per placement,
  including both straddle cases placed inside a fence that crosses the 500-
  and 1,200-character cuts).
- FR-002/003: `tests/canary.py` captures the per-turn judge and session
  analysis (fake judge), every Ask tool plus the store facts, the embedding
  provider (fake embedder) and every MCP tool and resource through the real
  server. Each capture asserts it calls every registered tool, so a new
  Ask or MCP tool without a canary call fails.
- FR-004: four family modules assert the per-mode invariant, each with a
  `none`-mode positive control that the capture sees the corpus.
- FR-005: `OutboundPolicy` in `ingest/redaction.py`; `project_context`
  uses the extracted rule. Applied on the per-turn judge, the transcript
  (analysis and Ask turns), Ask tools and store facts, embeddings, and the
  MCP server's tools and resources.
- FR-006: `test_canary_floor.py`, ingested under `none` and `code`, with and
  without the trace archive, then tightened per project, tightened
  globally, or opted out.
- FR-007: `test_canary_coverage.py`, with its limits in the docstring.
- FR-008: the existing steering and archive canary tests are unchanged.
- Success criterion 3: thirteen mutations, each removing one path's
  redaction, floor or opt-out filter, each failing a canary test that names
  the path and the canary; an unmapped `.complete(` call fails the guard.

## Deviations from the plan, with reasons

- **MCP floor in the MCP layer.** The plan put it in `mcp/tools.py`; those
  functions also serve the Studio API, which the spec keeps out of scope.
  The floor sits in `mcp/server.py`, plus an optional `outbound` argument on
  `resources.recent_errors` and `outbound_filter` on `analyze_patterns`,
  both defaulting to no change for Studio.
- **A policy object, not `session_outbound_mode`.** Multi-session paths
  need the floor for many sessions; `OutboundPolicy.load` computes it in one
  query (or for one session) and every path uses the same object.
- **Error type is floored too.** The corpus showed that under `none` ingest
  stores an error's first line as `error_type`, which reached Ask, MCP
  details, recent errors and the pattern aggregates after tightening. It is
  reduced with the same `safe_error_type` a redacting ingest uses; an
  aggregate that groups across sessions is reduced whenever any session is
  floored.
- **Ask captured through its tools.** The plan said to script the Ask loop;
  the loop sends only `store_facts` and tool results, so the capture calls
  every tool and `store_facts` directly — the same payloads, without a
  scripted model.
- **Thread views and clusters.** A thread that includes an opted-out
  session is refused as a whole (a pruned tree would still identify it); a
  cluster drops opted-out members and recomputes its identity from the
  kept ones, keeping `size` as a total.
- Two existing MCP tests mocked the database with a bare `Mock`; the floor
  now reads the session table first, so their mock answers that query with
  no rows. What they assert is unchanged.

## Verdict

Verdict: aligned
Confidence: high
