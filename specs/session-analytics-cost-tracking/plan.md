---
spec_mode: full
feature_id: session-analytics-cost-tracking
risk_category: integration
justification: |
  Adds cost computation to the session-analytics pipeline: a config price
  table, an additive per-turn model + cost_usd population at ingest, session
  rollups + a cost-per-outcome KPI, an API surface, and studio UI. Touches the
  ingest path and both DDL dialects (SQLite + postgres), but all changes are
  additive (nullable columns; no pricing block = today's behavior). Coverage
  via the existing unittest suite + the postgres smoke path. Tracking: #65;
  groundwork: #63/PR #64.
status: approved
date: 2026-07-15
issue: 83
origin:
  issue: gosha70/code-copilot-team#83
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/83
  origin_claim: |
    Issue #83 (E5): compute + expose token cost. Price table in config (no
    source rates) keyed by model with per-token-type rates, each carrying
    currency + effective date/version; per-turn cost_usd computed at ingest for
    known models, unknown → NULL + surfaced count (never silently 0); session
    rollup + cost-per-outcome KPI; API + studio surface. Grounded in #63: token
    fields + nullable cost_usd + session-level model + heuristic_label judge
    output already exist. User defaults (2026-07-15): store model id per turn if
    not already present, versioned rates in config, compute cost at ingest for
    known models, unknown NULL with reporting.
---

# Plan: session-analytics cost tracking (E5)

Grounded code facts (verified 2026-07-15):
- `copilot_turn` has token fields + a nullable `cost_usd` (never populated) but
  **no model column**; `copilot_session.model` holds a session-level model.
- The Claude Code adapter (`adapters/claude_code.py`) reads `msg.get("model")`
  per assistant message but keeps only the first (→ session model).
- Judge output is `heuristic_label` (per-turn labels) + a session judge rollup;
  there is no single "outcome" column.
- Config loads `config_data/defaults.json` (layered) — the price-table home.

## Deliverables

1. **Price table** (`config_data/defaults.json` `pricing` block + `config.py`
   loader + validation): per-model, per-token-type rates with currency +
   effective_date/version; per-1M-token units; mixed-currency rejected.
2. **Per-turn model** (migration + adapter): add nullable `copilot_turn.model`
   to both DDL dialects; capture per-message model with session fallback.
3. **Cost at ingest** (ingest pipeline): populate `cost_usd` for known models,
   record the price version, count + report unpriced models; unknown → NULL.
4. **Rollups + KPI** (queries/view): session cost = Σ turn costs;
   cost-per-outcome by `phase` + `heuristic_label`; total + cost-per-session.
5. **API** surface for the rollups; **studio** per-session cost + top-line KPI.
6. **Tests** (unittest + smoke) per FR-7; **docs** per FR-8.

## Design decisions to confirm at approval (your defaults baked in)

- **D-model.** Add per-turn `copilot_turn.model` (migration) + per-message
  capture, falling back to the session model. *(Your default — "store model id
  per turn if not already present"; grounded: session-level exists, per-turn
  does not. Recommended for accuracy across mid-session `/model` switches.
  Alternative: price by the existing session model with no migration — simpler,
  but wrong when a session switches models.)*
- **D-units/versioning.** Rates per-1M-tokens, `currency: USD`,
  `effective_date`/version per entry; the version used is recorded per turn.
  *(Your default — versioned rates in config; adds the currency/date metadata
  you requested on #83.)*
- **D-compute.** Cost computed **at ingest** for known models; unknown → NULL +
  surfaced count. *(Your default.)*
- **D-outcome.** "Cost-per-outcome" = cost grouped by session `phase` and judge
  `heuristic_label` (the available dimensions); primary KPI = total +
  cost-per-session. *(Grounded — no single outcome column; confirm this is the
  intended "outcome".)*
- **D-repricing.** A price change does **not** re-price already-ingested turns
  (their `cost_usd` reflects the version effective at ingest — stable history).
  A bulk `reprice` maintenance pass is **out of scope for v1**. *(Follows from
  compute-at-ingest; flag if you want re-pricing in scope.)*

## Out of scope

- Re-pricing historical data on a price change (v1: version-stamped at ingest).
- Cost budgets/alerts, multi-currency conversion, non-Claude model rate curation
  beyond the config schema.

## Test strategy

Unittest-first (SQLite, zero deps): pricing math incl. cache tokens,
unknown-model NULL+count, per-turn model + fallback, rollup + cost-per-outcome
correctness, currency/version validation. Then the postgres smoke path
(`session-analytics-smoke` fixture ingest) asserts cost columns populate under
the real dialect. Studio: cost renders in the `studio` CI build.
