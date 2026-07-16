# Tasks: session-analytics cost tracking (E5)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: Price table + per-turn model + cost at ingest

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `pricing` block in defaults.json + config.py loader/validation (per-model, per-token-type rates; currency + effective_date/version; per-1M units; mixed-currency rejected) (FR-1) | `scripts/session_analytics/config_data/defaults.json`, `config.py`, `constants.py` | build | [ ] |
| 2 | | Additive `copilot_turn.model` column (both DDL dialects) + adapter per-message model capture with session fallback (FR-2) | `config_data/ddl/postgres/*.sql`, `config_data/ddl/sqlite/*` , `adapters/claude_code.py`, `contracts.py`, `relational/store.py` | build | [ ] |
| 3 | | Cost-at-ingest: compute `cost_usd` for known models, record price version, count + report unpriced; unknown → NULL (FR-3) | `scripts/session_analytics/ingest/pipeline.py`, `relational/store.py` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] No `pricing` block → `cost_usd` NULL, behavior unchanged (regression)
- [ ] Known model → correct `cost_usd` (incl. cache tokens) + version recorded; unknown → NULL + counted

---

## US2: Rollups + KPI + API + studio

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Session cost rollup (Σ turn costs) + cost-per-outcome query (by `phase` + `heuristic_label`); total + cost-per-session KPI (FR-4) | `scripts/session_analytics/` (queries/analytics), DDL view if used | build | [ ] |
| 5 | | API surface for the cost rollups (FR-5) | `scripts/session_analytics/` (api) | build | [ ] |
| 6 | [P] | Studio: per-session cost (list + detail) + top-line cost KPI (analysis) (FR-6) | `studio/app/**`, `studio/lib/api.ts` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] Session cost == Σ turn costs; cost-per-phase / per-label sums reconcile
- [ ] Studio renders cost; `next build` green

---

## US3: Tests + docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 7 | | Unittests: pricing math (cache tokens), unknown→NULL+count, per-turn model + fallback, rollup + cost-per-outcome, currency/version validation (FR-7) | `scripts/session_analytics/tests/**` | build | [ ] |
| 8 | | Postgres smoke path asserts cost columns populate under the real dialect (FR-7) | `.github/workflows/session-analytics-smoke.yml` (if new fixture assertions), `tests/**` | build | [ ] |
| 9 | [P] | Docs: price-table config + effective-date semantics in the session-analytics README (FR-8) | `scripts/session_analytics/README.md` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] Unittest suite + smoke green with cost assertions
- [ ] Docs show how to update rates + the currency/version model

---

## Final Verification

- [ ] Unittest suite + postgres smoke + `studio` build all pass
- [ ] No hardcoded rates in source; no-pricing-block regression holds
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
