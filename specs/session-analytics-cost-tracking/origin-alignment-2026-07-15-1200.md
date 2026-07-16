# Origin alignment check — session-analytics-cost-tracking

Origin: https://github.com/gosha70/code-copilot-team/issues/83

Origin claim:
> Issue #83 (E5, from the #65 prioritization): compute + expose token cost. A
> price table in config (no source rates), keyed by model with per-token-type
> rates, each declaring currency + effective date/version; per-turn cost_usd
> computed at ingest for known models, unknown → NULL + surfaced count (never
> silently 0); session rollup + a cost-per-outcome KPI; API + studio surface.
> Grounded in #63: token fields + a nullable cost_usd + a session-level model +
> the heuristic_label judge output already exist.

Working claim:
> specs/session-analytics-cost-tracking/{spec.md,plan.md,tasks.md} bind exactly
> that scope (FR-1..FR-8), with decisions confirmed by the user at plan approval
> (2026-07-15): D-model = add a per-turn copilot_turn.model column + per-message
> capture with session fallback (accurate across mid-session /model switches;
> session-level model already exists, per-turn does not); D-units/versioning =
> per-1M-token rates with currency + effective_date, version recorded per turn;
> D-compute = cost at ingest for known models, unknown NULL + reported;
> D-outcome = cost-per-outcome grouped by session phase + judge heuristic_label
> (the dimensions that exist); D-repricing = version-stamped at ingest, bulk
> reprice out of scope for v1. No implementation exists yet on branch
> feat/session-analytics-cost-tracking-83.

Verdict: aligned
Confidence: high

Checked 2026-07-15 by re-reading issue #83, the #65 prioritization, and the
#63 groundwork (copilot_turn token fields + nullable cost_usd, session-level
copilot_session.model, the claude_code adapter's per-message model read, the
heuristic_label judge output, and the config_data/defaults.json layered
config). Plan flipped to status: approved with explicit user approval; D-model
(per-turn) and the other decisions confirmed.
