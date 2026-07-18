# Spec: session-analytics benchmark comparison UI (E9 Studio slice)

Issue #96, the final E9 slice (tracking #65). Grounding (verified 2026-07-18):
`GET /api/dashboard/benchmark` (shipped #92/#93, endpoint-tested with FastAPI)
already returns `{sessions_total, sessions_linked, sessions_unlinked,
distinct_benchmark_attempts, by_result: [{result, attempts, linked_sessions,
total_cost_usd, avg_duration_seconds}]}`. The Studio (`studio/`) has typed
fetchers in `lib/api.ts`, a `TABS` nav in `app/layout.tsx`, and shared
`Card`/`Stat`/`useApi`/`formatCost` components in `components/ui.tsx`. No
Studio surface shows any benchmark data. Scope = **backend-free first pass**
(2026-07-18 decision): consume the existing payload only.

## User Scenarios

- US1: As an analyst, I open the Studio's Benchmark view and see, per
  benchmark result (pass/fail/error/timeout), how many attempts ran, how many
  distinct sessions linked, what those sessions cost in total, and their
  average duration — the "compare sessions by benchmark outcome" payoff.
- US2: As an operator on a store with no benchmark data (or one where
  `correlate` hasn't run), the view says so plainly and points me at the
  `correlate` command instead of showing an empty broken table.

## Requirements

- FR-1: **Typed fetcher** — `api.benchmark()` in `studio/lib/api.ts` GETs
  `/api/dashboard/benchmark` with a TypeScript type mirroring the payload
  exactly (no client-side re-derivation of server figures).
- FR-2: **Comparison view** — coverage stats (linked sessions, unlinked
  sessions, distinct benchmark attempts) rendered via `Stat`, plus a
  per-result comparison presentation (table or cards — D-presentation) with
  EXACTLY the four per-result figures from the payload: `attempts`,
  `linked_sessions`, `total_cost_usd` (via the existing `formatCost`),
  `avg_duration_seconds` (humanized). Results ordered as served (attempts
  DESC — server contract).
- FR-3: **Empty state** — `by_result` empty ⇒ an explanatory panel (no
  benchmark outcomes ingested; run `session-analytics correlate
  --runs-root <dir>`), not an empty table. Coverage stats still render.
- FR-4: **Backend-free** — zero change to the API, store, schema, or
  constants. If the payload proves insufficient during build, STOP and
  re-scope (circuit-breaker) rather than silently extending the backend.
- FR-5: **Convention fit** — one-shot `useApi` fetch (no auto-refresh in this
  slice), `Loading`/`ErrorNote` for the standard states, existing styling
  idioms; placement per D-placement.
- FR-6: **Validation** — `cd studio && npm run build` green (the studio CI
  job's exact check, run locally while Actions is down). The payload contract
  itself is already covered by `tests/test_api.py::test_dashboard_benchmark`.

## Constraints

- Studio-only diff (`studio/lib/api.ts`, `app/layout.tsx` if a tab is added,
  one page/component file). No Python changes.
- No new npm dependencies.
- One issue per PR: this bundle covers exactly #96.
