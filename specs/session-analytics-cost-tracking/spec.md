# Spec: session-analytics cost tracking (E5)

Issue #83 (E5, Tier-1 from the #65 prioritization). Base: the #63 pipeline
(P1–P5) shipped in PR #64. Groundwork in place: `copilot_turn` carries
`tokens_input`/`tokens_output` + `cache_read_tokens`/`cache_write_tokens`
(populated by the Claude Code adapter) and a nullable `cost_usd` column (never
populated); `copilot_session.model` records a session-level model; the judge
writes `heuristic_label` rows. No price/cost computation exists yet.

## User Scenarios

- US1: As an operator, I see a top-line **cost (USD)** and **per-session cost**
  computed from token counts, so I can track copilot spend.
- US2: As an analyst, I see cost broken down by dimension — model, session
  `phase`, and judge label — so I can see where spend concentrates
  (cost-per-outcome).
- US3: As a maintainer, updating prices later never makes historical cost
  ambiguous: each rate declares its **currency** and **effective date/version**,
  and the version used to price a turn is recorded, so a stored `cost_usd` is
  always interpretable.

## Requirements

- FR-1: **Price table in config** (no rates in source — repo rule). A `pricing`
  block in `config_data/defaults.json`, layered/overridable like the rest of
  config, keyed by model id, with per-token-type rates (input, output,
  cache_read, cache_write). Each rate entry declares **`currency`** (e.g. `USD`)
  and an **`effective_date`/version**. Rate units are per-1M-tokens (documented).
  A table mixing currencies without normalization is rejected at load.
- FR-2: **Per-turn model attribution**. Add a nullable `copilot_turn.model`
  column (both SQLite + postgres DDL) and capture the model per assistant
  message in the Claude Code adapter (it already reads `msg.get("model")`);
  fall back to `copilot_session.model` when a turn's message has none. This
  handles mid-session model switches (different models → different rates).
- FR-3: **Compute `cost_usd` at ingest** for turns with a known `(model, rate)`:
  `cost_usd = Σ(tokens_type × rate[model][type])`, populating
  `copilot_turn.cost_usd` and recording which price version priced it. A turn
  whose model has no matching price → `cost_usd` stays **NULL** and increments a
  surfaced "unpriced" counter reported at end of ingest — cost is **never
  silently 0**.
- FR-4: **Rollups + KPI**. Session-level `cost_usd` = Σ its turn costs (view or
  materialized column). A **cost-per-outcome** query: cost aggregated by session
  `phase` and by judge `heuristic_label`; the primary KPI is total cost +
  cost-per-session.
- FR-5: **API/query surface**: expose the cost rollups (per-session cost, total,
  by-dimension) through the existing analytics API for the studio.
- FR-6: **Studio**: per-session cost on the sessions list + session detail, and
  a top-line cost KPI on the analysis page.
- FR-7: **Tests**: pricing math (incl. cache tokens), unknown-model → NULL +
  counted path, session rollup correctness, currency/version metadata handling,
  and per-turn model capture with session fallback — across the SQLite unittest
  suite + the postgres smoke path.
- FR-8: **Docs**: config price-table docs (how to update rates, effective-date
  semantics) in the session-analytics README.

## Constraints

- Python; no hardcoded structured rates in source (prices live in config).
- Cost is never silently 0 for an unpriced turn — NULL + surfaced count.
- Historical cost is reproducible: the price version used is recorded per turn;
  a price change does not re-price already-ingested turns (re-pricing existing
  data is out of scope for v1 — see D-repricing).
- Schema change is **additive** (new nullable columns); with no `pricing` block
  configured, `cost_usd` stays NULL and behavior matches today.
- SQLite (unittest) + PostgreSQL (smoke) parity — both DDL dialects updated.
- One issue per PR: this bundle covers exactly #83.
