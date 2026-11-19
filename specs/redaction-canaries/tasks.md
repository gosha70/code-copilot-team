---
spec_mode: full
feature_id: redaction-canaries
risk_category: security
status: draft
date: 2026-11-19
---

# Tasks: canary secrets on every off-machine path (#457)

<!-- [P] = can run in parallel within the group. FR# traces to spec.md. -->

## Floor (FR-005)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `outbound_mode`, `session_outbound_mode`, `outbound_text`, with unit tests (stricter wins, `ingest: "off"` gives metadata-only, unknown modes give metadata-only, stricter-than-recorded gives a marker) | `ingest/redaction.py`, `tests/test_redaction.py` | build | [ ] |
| 2 | | `project_context` uses the extracted function; the existing steering tests stay green | `judge/session_analysis.py` | build | [ ] |
| 3 | [P] | Apply the floor on the per-turn judge and the analysis transcript | `judge/runner.py`, `judge/session_analysis.py` | build | [ ] |
| 4 | [P] | Apply the floor on Ask tool results | `ask/tools.py` | build | [ ] |
| 5 | [P] | Apply the floor on embedding input | `embedding/composer.py` | build | [ ] |
| 6 | [P] | Apply the floor on MCP tools and resources | `mcp/tools.py`, `mcp/resources.py` | build | [ ] |

## Corpus and capture (FR-001 to FR-004, FR-006, FR-008)

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 7 | | Canary corpus: transcript, project root with `AGENTS.md`/`CLAUDE.md`, both straddle cases; `CANARIES`, `assert_no_canary`, `COVERED_MODULES` | `tests/fixtures/canary/`, `tests/canary.py` | build | [ ] |
| 8 | [P] | Judge canaries: per-turn judge and session analysis, under code and metadata-only | `tests/test_canary_judge.py` | build | [ ] |
| 9 | [P] | Ask canaries: prompt and every tool result | `tests/test_canary_ask.py` | build | [ ] |
| 10 | [P] | Embedding canaries | `tests/test_canary_embedding.py` | build | [ ] |
| 11 | [P] | MCP canaries: every tool and resource | `tests/test_canary_mcp.py` | build | [ ] |
| 12 | | Floor canaries: ingest under none and code, tighten per project and globally, all four families | `tests/test_canary_floor.py` | build | [ ] |

## Coverage guard (FR-007) and docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 13 | | AST scan of off-machine transports against `COVERED_MODULES`, with named exemptions | `tests/test_canary_coverage.py` | build | [ ] |
| 14 | [P] | README paragraph on the floor | `scripts/session_analytics/README.md` | build | [ ] |

## Final verification

- [ ] For each FR-003 path: a temporary patch removing its redaction or floor fails a canary test naming the path and canary (output quoted in the PR; patches not committed).
- [ ] A temporary off-machine call in an unmapped module fails `test_canary_coverage.py`.
- [ ] Full Session Analytics suite green.
- [ ] `bash scripts/validate-spec.sh --feature-id redaction-canaries` passes.
- [ ] `bash scripts/check-origin-alignment.sh redaction-canaries` passes.
- [ ] Maintainer approval (`status: approved`) before implementation.
