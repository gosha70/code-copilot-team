---
spec_mode: full
feature_id: redaction-canaries
risk_category: security
justification: |
  Adds canary-secret fixtures and payload-capturing tests over every path
  that sends Session Analytics text off the machine (per-turn judge, session
  analysis, Ask, embeddings, MCP), a coverage guard so a new outbound path
  fails the build until it is covered, and a current-mode redaction floor on
  every one of those paths. Security-relevant code across six modules:
  spec_mode full.
status: draft
date: 2026-11-19
issue: "#457"
origin:
  issue: "#457"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/457
    - https://medium.com/@gosha_70/tracing-coding-agents-without-lying-to-yourself-f8d35a008885
  transcripts:
    - specs/redaction-canaries/origin/2026-11-19-owner-decisions.md
  origin_claim: |
    Plant canary secrets in test fixtures and assert they never appear in
    any excerpt or judge-bound output: "For every excerpt-building path, run
    the pipeline and assert that the canary secret does not appear in the
    excerpt output [and] does not appear in anything sent to the judge
    (including the judge's grounding files and harness stamp). If a future
    contributor adds a new excerpt path that skips redaction, the canary will
    surface in the test output and fail the build." The owner's rulings
    widen the paths to everything off-machine and bring the current-mode
    floor into scope.
---

# Plan: canary secrets on every off-machine path (#457)

## Shape

Three pieces, in this order.

1. **The floor (FR-005).** It changes what the paths send, so the canary tests are written against the final behaviour.
2. **The corpus and capture (FR-001 to FR-004, FR-006, FR-008).** Fixtures plus a test module per path family.
3. **The coverage guard (FR-007).**

### The floor

Extract the mode computation in `project_context` (`judge/session_analysis.py:337-346`) into `ingest/redaction.py`:

- `outbound_mode(recorded, current, ingest_off) -> str` is the pure rule: stricter of the two, and `ingest: "off"` gives `metadata-only`.
- `session_outbound_mode(db, session_id, cfg) -> (recorded, outbound)` reads the stored mode and the project path, and resolves the current override through `ProjectKeyResolver` and `cfg.project_override`.
- `outbound_text(text, recorded, outbound) -> str` returns `text` when the modes match, and `redact_text(text, metadata-only)` when `outbound` is stricter.

`project_context` uses the extracted function, so the steering path keeps its behaviour. Each outbound path applies `outbound_text` to every session-derived text field it sends:

| Path | Where the text is read | Fields |
|---|---|---|
| per-turn judge | `judge/runner.py` `_select_turns` | turn preview, previous-turn preview |
| session analysis | `judge/session_analysis.py` `build_transcript` | previews or archived content per turn |
| Ask | `ask/tools.py` `session_turns`, `search_text`, `session_summary` | turn text, snippets, error messages |
| embeddings | `embedding/composer.py` | preview input |
| MCP | `mcp/tools.py` session details, thread, trace attach; `mcp/resources.py` recent errors | previews, archived content, input previews, error messages |

A path that reads many sessions resolves the mode once per session, not once per turn.

### Corpus and capture

- **`tests/fixtures/canary/`:** a Claude Code transcript (JSONL, the existing fixture format) whose cwd is the corpus project root, plus `AGENTS.md` and `CLAUDE.md` in that root. Canary strings and their placements live in one module (`tests/canary.py`): `CANARIES = {placement: string}`, with the helpers `fenced()` and `assert_no_canary(payload, allowed=...)`.
- **Capture:**
  - The fake judge (registered under a test family) records `rate_turn` contexts and `complete` prompts.
  - The fake embedder is injected where `embedding/runner.py` builds its provider.
  - Ask runs `ask/loop.py` with the fake judge scripted to call each tool once.
  - MCP calls each tool and resource function that `build_server` registers.
- **Test modules:**
  - `test_canary_judge.py`: the per-turn judge, and session analysis (transcript, steering, facts, stamp).
  - `test_canary_ask.py`
  - `test_canary_embedding.py`
  - `test_canary_mcp.py`
  - `test_canary_floor.py`: FR-006, running all four families after the configuration is tightened.

### Coverage guard

`test_canary_coverage.py` parses the package with `ast`. It collects every module that calls `.rate_turn(`, `.complete(` or the embedding provider's `embed(`, or registers MCP tools or resources (`@server.tool`, `@server.resource`), or defines the Ask tool table. It compares that set with `COVERED_MODULES` in `tests/canary.py`. A module missing from the map fails with its name and the line of the call.

The backend implementations (`judge/ollama_judge.py`, `judge/openai_judge.py`, `judge/session_judge.py`, `embedding/ollama_embed.py`) are the transport itself, and they call `self.complete`/`self.embed` internally. The scan excludes them by name.

## Files

- `ingest/redaction.py`: `outbound_mode`, `session_outbound_mode`, `outbound_text`.
- `judge/session_analysis.py`: `project_context` uses them, and `build_transcript` applies the floor.
- `judge/runner.py`, `ask/tools.py`, `embedding/composer.py`, `mcp/tools.py`, `mcp/resources.py`: apply the floor.
- `tests/fixtures/canary/`, `tests/canary.py`, and six new test modules.
- `scripts/session_analytics/README.md`: one paragraph on the floor ("tightening a project's mode applies to what leaves the machine at once; re-ingest to rewrite the store").

## Risks

- **A wrong field list.** A path can send a field the table misses. Mitigation: the canary assertions run on the whole captured payload, not on named fields. A missed field leaks a canary and fails the build.
- **Cost of the floor.** Resolving the mode reads the config and one session row. Paths that read many sessions resolve once per session, and `load_config` is already called per request on these paths.
- **The coverage guard's false positives.** A helper module that calls `complete(` for a non-session purpose (e.g. the backend connection test, which sends fixed strings) goes in the map with a reason, so the exemption is visible in review.

## Test strategy

- Each path family has a canary module running under `code` and under `metadata-only` (FR-004).
- `test_canary_floor.py` covers ingest-then-tighten (FR-006).
- Success criterion 3 is shown in the implementation PR: for each path, a temporary patch that removes its redaction or floor, with the failing test output quoted. The patches are not committed.
- The full Session Analytics suite runs green. The existing steering and archive canary tests are unchanged.

## Slicing

One implementation PR closes #457. The floor and the canary tests prove each other, so they ship together.
