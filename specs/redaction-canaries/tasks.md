---
spec_mode: full
feature_id: redaction-canaries
risk_category: security
status: approved
date: 2026-11-19
---

# Tasks: canary secrets on every off-machine path (#457)

<!-- [P] = can run in parallel within the group. FR# traces to spec.md. -->

## Floor (FR-005)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `outbound_mode`, `session_outbound_mode`, `outbound_text`, with unit tests (stricter wins, `ingest: "off"` gives skip, unknown modes give metadata-only, stricter-than-recorded gives a marker) | `ingest/redaction.py`, `tests/test_redaction.py` | build | [x] |
| 2 | | `project_context` uses the extracted function and reads nothing for an opted-out project; the existing steering tests stay green | `judge/session_analysis.py` | build | [x] |
| 3 | [P] | Apply the floor and skip opted-out sessions on the per-turn judge and the analysis transcript (analysis of an opted-out session returns an error naming the opt-out) | `judge/runner.py`, `judge/session_analysis.py` | build | [x] |
| 4 | [P] | Apply the floor and skip opted-out sessions on Ask tool results | `ask/tools.py` | build | [x] |
| 5 | [P] | Apply the floor and skip opted-out sessions on embedding input | `embedding/composer.py` | build | [x] |
| 6 | [P] | Apply the floor and skip opted-out sessions on MCP tools and resources | `mcp/tools.py`, `mcp/resources.py` | build | [x] |

## Corpus and capture (FR-001 to FR-004, FR-006, FR-008)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 7 | | Canary corpus: transcript, project root with `AGENTS.md`/`CLAUDE.md`, both straddle cases; `CANARIES`, `assert_no_canary`, `COVERED_MODULES` | `tests/fixtures/canary/`, `tests/canary.py` | build | [x] |
| 8 | [P] | Judge canaries: per-turn judge and session analysis, under code (all but prose canaries) and metadata-only (all) | `tests/test_canary_judge.py` | build | [x] |
| 9 | [P] | Ask canaries: prompt and every tool result | `tests/test_canary_ask.py` | build | [x] |
| 10 | [P] | Embedding canaries | `tests/test_canary_embedding.py` | build | [x] |
| 11 | [P] | MCP canaries: every tool and resource | `tests/test_canary_mcp.py` | build | [x] |
| 12 | | Floor canaries: ingest under none and code, tighten per project and globally, then opt the project out; all four families | `tests/test_canary_floor.py` | build | [x] |

## Coverage guard (FR-007) and docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 13 | | AST scan of off-machine transports against `COVERED_MODULES`, with named exemptions and reasons (D3); the docstring states the limits from FR-007 | `tests/test_canary_coverage.py` | build | [x] |
| 14 | [P] | README paragraph on the floor | `scripts/session_analytics/README.md` | build | [x] |

## Final verification

- [x] For each FR-003 path: a temporary patch removing its redaction or floor fails a canary test naming the path and canary (output quoted in the PR; patches not committed).
- [x] A temporary off-machine call in an unmapped module fails `test_canary_coverage.py`.
- [x] Full Session Analytics suite green.
- [x] `bash scripts/validate-spec.sh --feature-id redaction-canaries` passes.
- [x] `bash scripts/check-origin-alignment.sh redaction-canaries` passes.
- [x] Maintainer approval (`status: approved`) before implementation: approved 2026-11-19 with decisions D1–D3 (spec.md, "Decisions").
