---
spec_mode: full
feature_id: session-analytics-benchmark-ui
risk_category: ui
justification: |
  Studio-only comparison view over the already-shipped, already-tested
  /api/dashboard/benchmark payload. Backend-free by decision (FR-4 makes any
  backend need a stop-and-rescope, not a silent extension). No new deps; the
  studio next build is the validation gate. Smallest slice in the E9 series.
status: approved
date: 2026-07-18
issue: 96
origin:
  issue: gosha70/code-copilot-team#96
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/96
  origin_claim: |
    Issue #96 (E9 Studio slice, backend-free first pass): a Benchmark
    comparison view over the EXISTING GET /api/dashboard/benchmark payload —
    typed api.benchmark() fetcher; coverage stats (linked/unlinked sessions,
    distinct attempts); per-result table/cards with exactly attempts,
    linked_sessions, total_cost_usd, avg_duration_seconds; honest empty state
    pointing at correlate; no API/schema/store change unless the payload
    proves insufficient (then stop and re-scope). Reuses Card/Stat/useApi/
    formatCost; one-shot fetch; next build is the gate.
---

# Plan: session-analytics benchmark comparison UI (E9 Studio slice)

Grounded (verified 2026-07-18): payload shape served + endpoint-tested;
api.ts fetcher pattern (`get<T>` + typed entries in `export const api`);
TABS nav in layout.tsx; Card/Stat/Loading/ErrorNote/useApi/formatCost in
components/ui.tsx; dashboard/sessions pages show the composition idiom.

## Deliverables

1. `studio/lib/api.ts`: `BenchmarkSummary` type + `api.benchmark()` fetcher.
2. Comparison view (per D-placement) rendering coverage `Stat`s + the
   per-result comparison + empty state.
3. `app/layout.tsx`: nav entry (only if D-placement = new page).
4. Validation: `npm run build`; manual render sanity against a seeded local
   store (linked + unlinked + empty cases).

## Design decisions to confirm at approval

- **D-placement** — a NEW `/benchmark` page + "Benchmark" nav tab.
  *(Recommend — the dashboard page is already dense; the comparison gets room
  to grow into per-task drill-down later; the alternative — a Card on the
  dashboard — saves one file but crowds the page and buries the empty state.)*
- **D-presentation** — a comparison TABLE (one row per result, columns =
  result badge / attempts / linked sessions / total linked cost / avg
  duration), with the coverage numbers as a `Stat` row above it. *(Recommend
  — 4 metrics × up to 5 result classes reads better as a table than as up to
  20 cards; matches the sessions-list idiom.)*
- **D-duration-format** — humanize `avg_duration_seconds` as `Xm Ys` (or
  `Xs` under a minute); 0 renders as `—` for unlinked-only rows. *(Recommend.)*
- **D-refresh** — one-shot fetch, NO auto-refresh in this slice (benchmark
  data changes only when `correlate` runs, unlike live session ingest).
  *(Recommend.)*

## Out of scope

- Any backend/API/schema change (FR-4 stop-and-rescope applies).
- Per-task or per-attempt drill-down; charts; auto-refresh.
- Fuzzy fallback / schema_version / run_dir-key items (tracked elsewhere).

## Test strategy

`next build` (type-check + lint + compile — the studio CI job's exact gate,
run locally while Actions is down). Payload contract already pinned by
`test_api.py::test_dashboard_benchmark`. Manual sanity: seed a local sqlite
store three ways (linked+unlinked outcomes via `correlate`; outcomes with no
links; empty store) and confirm the table, the `—` cases, and the empty
state render. No JS test runner exists in the studio (established).
