# session_analytics.cost — turn-level cost computation (E5 cost tracking).
#
# Pure functions over the config price table (config.PricingConfig) — no DB,
# no I/O, so the pricing math is unit-testable in isolation. Cost is computed
# AT INGEST (D-compute, specs/session-analytics-cost-tracking/plan.md):
#
#   cost_usd = Σ(tokens_type × rate[model][type]) / 1_000_000
#
# with a NULL token field treated as 0 for its component. A turn whose model
# has no matching price entry (or has no model at all) gets cost_usd = NULL
# — NEVER silently 0 — and, when the model IS known but unpriced, is tallied
# in ``UnpricedStats`` so ingest can report it instead of hiding it.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .config import PricingConfig


@dataclass(frozen=True)
class CostResult:
    cost_usd: Optional[float]
    price_version: Optional[str]  # the ModelRate.effective_date that priced it


@dataclass
class UnpricedStats:
    """Distinct unpriced model ids → turn count, surfaced at end of ingest.

    A turn with no model at all (e.g. a user turn) is NOT counted here —
    there is no model to look up, so it is simply not a pricing candidate.
    Only a turn whose (known) model has no matching price entry counts.
    """

    counts: dict[str, int] = field(default_factory=dict)

    def record(self, model: str) -> None:
        self.counts[model] = self.counts.get(model, 0) + 1

    @property
    def total_turns(self) -> int:
        return sum(self.counts.values())

    def as_dict(self) -> dict:
        return {"models": dict(self.counts), "turns": self.total_turns}


def compute_turn_cost(
    pricing: Optional[PricingConfig],
    model: Optional[str],
    *,
    tokens_input: Optional[int],
    tokens_output: Optional[int],
    cache_read_tokens: Optional[int],
    cache_write_tokens: Optional[int],
    unpriced: Optional[UnpricedStats] = None,
) -> CostResult:
    """Cost for one turn, or ``CostResult(None, None)`` when unpriceable.

    No pricing configured at all, or the turn has no model → NULL, not
    counted (nothing to report — this is the no-op/regression-safe path).
    A known model absent from the price table → NULL, counted in
    ``unpriced`` (if given).
    """
    if pricing is None or not model:
        return CostResult(None, None)

    rate = pricing.rate_for(model)
    if rate is None:
        if unpriced is not None:
            unpriced.record(model)
        return CostResult(None, None)

    cost = (
        (tokens_input or 0) * rate.input
        + (tokens_output or 0) * rate.output
        + (cache_read_tokens or 0) * rate.cache_read
        + (cache_write_tokens or 0) * rate.cache_write
    ) / 1_000_000.0
    return CostResult(cost, rate.effective_date)
