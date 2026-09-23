# Tasks: search (A2)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 0 | Owner approves the plan (D1–D7; D5 = the label MVP); approved 2026-09-22 after one review round | `plan.md` | [x] |
| 1 | Query layer: developer, model, tool, priced min/max cost, label filters; inclusive `date_to`; `count_noise_sessions` takes them all; facets over the list's population (FR-1a, FR-1b, FR-2, FR-4) | `scripts/session_analytics/mcp/tools.py` | [x] |
| 2 | Routes: `/api/sessions` passes every filter, returns facets, 400 on an unknown tag or label; `/api/search` applies noise and returns archive coverage (FR-1, FR-5) | `scripts/session_analytics/api/server.py`, `scripts/session_analytics/archive.py` | [x] |
| 3 | API tests: each filter, combinations, unknown tag/label, the `date_to` boundary day, unpriced session under a cost filter, excluded count, facets, search coverage and noise (FR-6) | `scripts/session_analytics/tests/test_api.py` | [x] |
| 4 | Studio: filter bar with URL state; search page with turn links; nav entry (FR-3, FR-5) | `studio/components/SessionFilters.tsx`, `studio/app/sessions/page.tsx`, `studio/app/search/page.tsx`, `studio/lib/searchView.ts`, `studio/lib/api.ts`, `studio/app/layout.tsx` | [x] |
| 5 | `states-check` states; README paragraph incl. Search vs Ask and the #307 note (FR-5a, FR-6) | `studio/scripts/states-check.mjs`, `scripts/session_analytics/README.md` | [x] |
| 6 | Scratch-store verification on other ports; facet timing on the largest store | — | [x] |
| 7 | Gates, alignment re-check, `/review-submit` (DeepSeek PASS ×2), PR (no close marker), CI green | — | [ ] |
