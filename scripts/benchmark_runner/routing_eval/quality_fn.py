"""quality_fn v1 — the declared reporting projection (E1 T5).

plan.md §quality_fn v1, implemented exactly. This function exists for
two purposes only — ranking arms and the oracle's per-cell choice — and
its scalar is always reported BESIDE the full metric vector, never in
place of it.

- Components are §Metric contract rows 1-8 only: the measures
  applicable to every arm. Sequence-dependent rows 9-11 are
  ``not_applicable`` for derived arms and would make arms incomparable;
  cost (row 12) is the other axis of the plane.
- Each component normalizes to [0, 1], higher better: the pass rate is
  used directly; the seven adverse rates contribute ``1 - r``.
- The weights are FIXED at v1 and sum to 1.0.
- The component mask is computed ONCE over the complete report matrix
  before any control selection and used identically for every cell and
  every arm — per-cell mask derivation would let different cells score
  under different weightings.
- A component unevaluable somewhere is DROPPED everywhere with the
  remaining weights renormalized (arms stay comparable by
  construction); a missing PRIMARY outcome (row 1) withholds Q for the
  whole comparison — Q is never "best effort".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

QUALITY_FN_VERSION = "v1"


class QualityInsufficient(Exception):
    """Q cannot be computed honestly for this comparison.

    Raised when the verifier outcome (the 0.50-weight primary
    component) is missing for an executed cell: every other component
    can be masked and renormalized, but a comparison whose primary
    outcome is unknown has no quality axis at all.
    """


#: The v1 components, in §Metric contract row order, with their FIXED
#: weights. `value` extracts the per-cell raw signal: row 1 yields the
#: pass indicator; rows 2-8 yield the adverse indicator (True/False) or
#: None when unevaluable.
def _pass_indicator(cell) -> Optional[float]:
    if cell.result is None:
        return None
    return 1.0 if cell.result == "pass" else 0.0


def _regression(kind: str) -> Callable[[Any], Optional[float]]:
    def read(cell) -> Optional[float]:
        value = (cell.regressions or {}).get(kind)
        return None if value is None else (1.0 if value else 0.0)

    return read


def _flag(attr: str) -> Callable[[Any], Optional[float]]:
    def read(cell) -> Optional[float]:
        value = getattr(cell, attr)
        return None if value is None else (1.0 if value else 0.0)

    return read


@dataclass(frozen=True)
class Component:
    name: str
    weight: float
    #: True for row 1 (higher raw value is better); False for the
    #: adverse rows, which contribute 1 - r.
    positive: bool
    value: Callable[[Any], Optional[float]]


COMPONENTS: tuple[Component, ...] = (
    Component("verifier_pass_rate", 0.50, True, _pass_indicator),
    Component("lint_regression", 0.075, False, _regression("lint")),
    Component("typecheck_regression", 0.075, False, _regression("typecheck")),
    Component("coverage_regression", 0.075, False, _regression("coverage")),
    Component("security_regression", 0.075, False, _regression("security")),
    Component("scope_violation", 0.10, False, _flag("scope_violation")),
    Component("repeated_repair", 0.05, False, _flag("repeated_repair")),
    Component("intervention", 0.05, False, _flag("intervention")),
)

assert abs(sum(c.weight for c in COMPONENTS) - 1.0) < 1e-12


def compute_mask(matrix) -> tuple[str, ...]:
    """The GLOBAL component mask, from the complete report matrix.

    Deterministic and selection-independent: a component is included
    only when it is evaluable in EVERY executed eligible cell of the
    matrix. One unevaluable cell anywhere drops the component for every
    arm (with renormalization); a missing primary outcome instead
    raises QualityInsufficient — the comparison has no quality axis.
    """
    executed = [c for c in matrix.cells if c.eligible]
    included = []
    for component in COMPONENTS:
        values = [component.value(c) for c in executed]
        if any(v is None for v in values):
            if component.name == "verifier_pass_rate":
                raise QualityInsufficient(
                    "an executed cell carries no verifier outcome — the "
                    "primary component cannot be masked away, so Q is "
                    "withheld for the whole comparison"
                )
            continue
        included.append(component.name)
    return tuple(included)


def _active(mask: Sequence[str]) -> list[tuple[Component, float]]:
    """The masked-in components with their RENORMALIZED weights."""
    active = [c for c in COMPONENTS if c.name in set(mask)]
    if "verifier_pass_rate" not in {c.name for c in active}:
        raise QualityInsufficient(
            "the mask excludes the primary verifier component — Q is undefined"
        )
    total = sum(c.weight for c in active)
    return [(c, c.weight / total) for c in active]


def cell_quality(cell, mask: Sequence[str]) -> float:
    """Q for ONE cell under the global mask — the oracle's choice key."""
    q = 0.0
    for component, weight in _active(mask):
        raw = component.value(cell)
        if raw is None:
            raise QualityInsufficient(
                f"cell {cell.task_id}/{cell.profile_id}/trial-{cell.trial} is "
                f"unevaluable for masked-in component '{component.name}' — the "
                f"mask must be computed over the same matrix the cells come from"
            )
        q += weight * (raw if component.positive else 1.0 - raw)
    return q


def component_aggregates(
    cells: Sequence[Any], mask: Sequence[str]
) -> Mapping[str, float]:
    """Per-component ARM aggregates: per-cell values, mean over trials
    to a per-task value, then mean over tasks with equal task weight —
    §Metric contract's default aggregation, applied per component
    BEFORE weighting (Q is a projection of aggregates, not a mean of
    cell scalars)."""
    by_task: dict[str, list[Any]] = {}
    for cell in cells:
        by_task.setdefault(cell.task_id, []).append(cell)
    aggregates: dict[str, float] = {}
    for component, _w in _active(mask):
        task_means = []
        for task_cells in by_task.values():
            values = [component.value(c) for c in task_cells]
            if any(v is None for v in values):
                raise QualityInsufficient(
                    f"unevaluable value for masked-in component "
                    f"'{component.name}' — mask and cells disagree"
                )
            task_means.append(sum(values) / len(values))
        aggregates[component.name] = sum(task_means) / len(task_means)
    return aggregates


def arm_quality(cells: Sequence[Any], mask: Sequence[str]) -> float:
    """The arm's Q: renormalized weighted sum over its component
    aggregates. Deterministic under any input permutation."""
    if not cells:
        raise QualityInsufficient("an arm with no cells has no quality")
    aggregates = component_aggregates(cells, mask)
    q = 0.0
    for component, weight in _active(mask):
        raw = aggregates[component.name]
        q += weight * (raw if component.positive else 1.0 - raw)
    return q
