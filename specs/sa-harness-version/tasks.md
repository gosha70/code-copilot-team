# Tasks: harness version + compare (A4 — two PRs)

| # | PR | Task | File(s) | Done |
|---|----|------|---------|------|
| 0 | — | Owner approves the plan (D1–D8 as corrected 2026-09-24; split A4a/A4b) | `plan.md` | [x] |
| 1 | A4a | Hook `harness-stamp.sh` (instructions/providers digests, `harness.json` with full sha, ledger append, guards); registered in `settings.json`; `setup.sh` installs it and writes `~/.cct/harness.json` on install and `--sync`; NOT added to `CC_PLUGIN_HOOKS` (FR-1, FR-7) | `adapters/claude-code/.claude/hooks/harness-stamp.sh`, `.claude/settings.json`, `setup.sh` | [x] |
| 2 | A4a | Six columns, schema 10, `_REQUIRED_COLUMNS`, constants, the ledger path (environment-only), `RawSession.harness` (FR-4) | `001_core.sql`, `relational/db.py`, `constants.py`, `config.py`, `contracts.py` | [x] |
| 3 | A4a | `harness_stamps.read_ledger` (earliest + mixed, sanitised); adapter reads `version`(s) and joins the stamp; `upsert_session` writes the six; `_SESSION_COLS` gains them (FR-2, FR-3, FR-4) | `harness_stamps.py`, `adapters/claude_code.py`, `relational/store.py`, `mcp/tools.py`, fixtures | [x] |
| 4 | A4a | Session header stamp / mixed / unstamped; `harnessView.ts`; states-check (FR-6 part) | `studio/lib/api.ts`, `studio/lib/harnessView.ts`, `studio/components/SessionHeader.tsx`, `studio/scripts/states-check.mjs` | [x] |
| 5 | A4a | Tests: ledger, hook invocation, adapter incl. mixed cases, store, refusal, plugin exclusion; README section; docs hooks row (FR-8) | `tests/test_harness_stamps.py`, `tests/test_adapter_claude_code.py`, `README.md`, `docs/…` | [x] |
| 6 | A4a | Scratch-store verification with a real ledger from this machine on other ports; gates; alignment; `/review-submit`; PR (no close marker); CI | — | [ ] |
| 7 | A4b | `harness_aggregates` + route + MCP tool; closed `harness` filter + facets (FR-5, FR-6) | `api/dashboard.py`, `api/server.py`, `mcp/tools.py`, `mcp/server.py` | [ ] |
| 8 | A4b | `HarnessPanel` on the Dashboard, the filter in the bar, states-check; tests (aggregates, filter, API, MCP); README (FR-5, FR-6, FR-8) | `studio/…`, `tests/…`, `README.md` | [ ] |
| 9 | A4b | Scratch verification; gates; `/review-submit`; PR (no close marker); CI. After merge, on the owner's word: their store recreated + `ingest --full` | — | [ ] |
