# Tasks: feedback (A3)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 0 | Owner approves the plan (D1–D8; corrected 2026-09-23 per the owner's review) | `plan.md` | [x] |
| 1 | Table keyed by `(sequence_num, tool_sequence_num)`, `UNIQUE (supersedes)`, schema version 9 in place, constants incl. the typed vocabulary (FR-1, FR-5) | `config_data/ddl/postgres/010_feedback.sql`, `relational/db.py`, `constants.py` | [x] |
| 2 | Store functions: add (typing per name, bool before int, target exists, supersession invariants), list, current in one query (FR-2, FR-5) | `scripts/session_analytics/feedback.py` | [x] |
| 3 | Routes: POST/GET feedback, `source_id` from `derive_developer_id` at request time; detail payload folds one feedback query onto session/turns/tool calls; export table (FR-3, FR-4, FR-7) | `api/server.py`, `mcp/tools.py`, `export.py` | [x] |
| 4 | Tests: store incl. supersession refusals, re-ingest survival at all three levels, schema-8 store stamped 9 in place; API incl. spoofed source ignored; payload additivity + single query; export (FR-8) | `tests/test_feedback.py`, `tests/test_api.py` | [x] |
| 5 | Studio: types, `feedbackView`, `FeedbackControl` on turn cards and the header; JudgeQuality note (FR-6) | `studio/lib/api.ts`, `studio/lib/feedbackView.ts`, `studio/components/FeedbackControl.tsx`, `studio/app/sessions/[id]/page.tsx`, `studio/components/JudgeQuality.tsx` | [x] |
| 6 | `states-check` states; README section (FR-8) | `studio/scripts/states-check.mjs`, `scripts/session_analytics/README.md` | [x] |
| 7 | Scratch-store verification on other ports incl. a re-ingest with feedback attached; the owner's instance untouched, their store not rebuilt | — | [x] |
| 8 | Gates, alignment re-check, `/review-submit`, PR (no close marker), CI green | — | [ ] |
