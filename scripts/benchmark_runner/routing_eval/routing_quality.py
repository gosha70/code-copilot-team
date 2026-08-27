"""The routing-quality report (E1 T5).

plan.md §Metric contract + §Cost and reporting contract, implemented
exactly. The report emits, per arm: the FULL metric vector (every
implemented row of the contract — a metric not in the table is not
emitted), `Q` under the declared quality_fn version, and cost under the
comparison's single declared cost_basis. The comparison view is `Q`,
cost, and the Pareto frontier — NO AIQ scalar (a single operating
point traces no curve).

The control-set gate is a HARD ERROR, not a warning: a `cct_router`
figure without `always_best`, `always_cheapest`, and `oracle` — for
the same preset digest, and none of them insufficient — is the exact
uncontrolled number this increment exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from .outcome_matrix import (
    NOT_APPLICABLE,
    SEQUENCE_DEPENDENT_MEASURES,
    ArmSelection,
    Cell,
    OutcomeMatrix,
)
from .quality_fn import (
    QUALITY_FN_VERSION,
    QualityInsufficient,
    arm_quality,
    component_aggregates,
    compute_mask,
)

INSUFFICIENT = "insufficient_evidence"

#: The three controls a cct_router figure must never appear without.
REQUIRED_CONTROLS = ("always_best", "always_cheapest", "oracle")


class ControlSetIncomplete(Exception):
    """The reporter refuses to emit a cct_router figure uncontrolled."""


def router_cells_from_records(
    records: Sequence[Mapping[str, Any]],
) -> list[Cell]:
    """Reduce routing-run records to per-(task, trial) measure cells.

    The same reduction shape the matrix sweep stores for control arms,
    from the router's own durable evidence: the verifier outcome is
    pass only when the record carries verifier executions and every
    one exited 0 (no verifiers -> None: absence of evidence is never a
    pass); regressions come from the recorded baselines and quality
    gates; cost carries its provenance through.
    """
    cells = []
    for r in records:
        verifiers = r.get("verifiers") or []
        if verifiers:
            result = "pass" if all(v.get("exit_status") == 0 for v in verifiers) else "fail"
        else:
            result = None
        baseline = r.get("baseline") or {}
        gates = r.get("quality_gates") or {}
        coverage = gates.get("coverage") or {}
        security = (gates.get("security") or {}).get("findings_by_severity") or {}

        def _regressed(before, after):
            if before is None or after is None:
                return None
            return after < before

        def _security_regressed(before, after):
            if before is None or after is None:
                return None
            return any(
                (after.get(k) or 0) > (before.get(k) or 0)
                for k in set(before) | set(after)
            )

        def _baseline_regressed(kind: str):
            before = baseline.get(f"{kind}_passed")
            # post-run signal: a failing verifier of that kind would be
            # its own row; the harvested record carries no separate
            # post-run lint/type signal, so absence stays None.
            return None if before is None else False

        repair = r.get("repair_cycles") or []
        signatures = [c.get("signature") for c in repair]
        cost = r.get("cost") or {}
        cells.append(
            Cell(
                task_id=r["task_id"],
                profile_id=r.get("profile_id") or "cct_router",
                trial=r["trial"],
                seed=r.get("trial_seed", 0),
                eligible=True,
                result=result,
                regressions={
                    "lint": _baseline_regressed("lint"),
                    "typecheck": _baseline_regressed("typecheck"),
                    "coverage": _regressed(coverage.get("before"), coverage.get("after")),
                    "security": _security_regressed(security.get("before"), security.get("after")),
                },
                scope_violation=bool(r.get("scope_violations"))
                if r.get("scope_violations") is not None
                else None,
                repeated_repair=len(signatures) != len(set(signatures)),
                intervention=bool(r.get("interventions")),
                cost_value=cost.get("value"),
                cost_provenance=cost.get("provenance", "unavailable"),
                cost_estimator=cost.get("estimator"),
            )
        )
    return cells


def _arm_cost(cells: Sequence[Cell], cost_basis: str):
    """Row 12's aggregation: mean over trials, SUM over tasks — under
    the single declared basis, or insufficiency (never zero)."""
    by_task: dict[str, list[Cell]] = {}
    for c in cells:
        by_task.setdefault(c.task_id, []).append(c)
    total = 0.0
    for task, task_cells in by_task.items():
        priced = [c.cost_value for c in task_cells if c.cost_satisfies(cost_basis)]
        if len(priced) != len(task_cells):
            return {
                "value": None,
                "status": INSUFFICIENT,
                "reason": f"task '{task}' has cells not satisfying cost_basis "
                f"'{cost_basis}' — a partial or mixed-provenance sum is "
                f"incomplete evidence",
            }
        total += sum(priced) / len(priced)
    return {"value": total, "status": "ok", "reason": None}


def _sequence_dependent_from_records(records: Sequence[Mapping[str, Any]]):
    """Rows 9-11, measured ONLY along the router's stateful run.

    The unit is the CELL, not the record: a delegated (task, trial)
    usually spans two invocation records — the delegate leg carries the
    builder's delegated_lines, the reconcile leg carries the pair — and
    summing records raw would double-count the denominator. Per cell,
    the durable values must agree; a delegated cell missing either
    count makes rows 9-10 ``insufficient_evidence`` (with the reason
    under ``insufficient_reason``) — rework is never assumed zero.
    Ratios aggregate as sum-of-numerators over sum-of-denominators; a
    zero denominator is not_applicable, never zero.
    """
    rollbacks = sum(len(r.get("rollbacks") or []) for r in records)
    cells: dict[tuple, dict] = {}
    insufficient_reason = None
    for r in records:
        tier2 = r.get("tier2") or {}
        if not tier2.get("delegated"):
            continue
        cell = cells.setdefault(
            (r["task_id"], r["trial"]),
            {"delegated_lines": None, "reconciliation_diff_lines": None},
        )
        for field in ("delegated_lines", "reconciliation_diff_lines"):
            value = tier2.get(field)
            if value is None:
                continue
            if cell[field] is not None and cell[field] != value:
                insufficient_reason = (
                    f"cell {(r['task_id'], r['trial'])} carries conflicting "
                    f"{field} evidence ({cell[field]} vs {value}) — "
                    f"contradictory durable evidence is insufficiency, "
                    f"never a pick"
                )
            cell[field] = value
    if not cells:
        return {
            "tier2_accepted_unchanged": NOT_APPLICABLE,
            "reconciliation_rework_ratio": NOT_APPLICABLE,
            "rollbacks": rollbacks,
        }
    if insufficient_reason is None:
        missing = sorted(
            key for key, c in cells.items()
            if c["delegated_lines"] is None
            or c["reconciliation_diff_lines"] is None
        )
        if missing:
            insufficient_reason = (
                f"delegated cell(s) {missing} lack complete line-count "
                f"evidence — unreconciled or unmeasured delegation is "
                f"never rendered as zero rework"
            )
    if insufficient_reason is not None:
        return {
            "tier2_accepted_unchanged": INSUFFICIENT,
            "reconciliation_rework_ratio": INSUFFICIENT,
            "rollbacks": rollbacks,
            "insufficient_reason": insufficient_reason,
        }
    num = sum(c["reconciliation_diff_lines"] for c in cells.values())
    den = sum(c["delegated_lines"] for c in cells.values())
    accepted_unchanged = sum(
        1 for c in cells.values() if c["reconciliation_diff_lines"] == 0
    ) / len(cells)
    return {
        "tier2_accepted_unchanged": accepted_unchanged,
        "reconciliation_rework_ratio": (num / den) if den else NOT_APPLICABLE,
        "rollbacks": rollbacks,
    }


@dataclass(frozen=True)
class ArmReport:
    kind: str
    quality: Optional[float]
    metrics: Mapping[str, Any]
    cost: Mapping[str, Any]
    insufficient: Mapping[str, str]


def build_report(
    matrix: OutcomeMatrix,
    control_selections: Mapping[str, ArmSelection],
    router_records: Sequence[Mapping[str, Any]],
    *,
    expected_preset_digest: str,
) -> Mapping[str, Any]:
    """The comparison report: Q + full vector + cost per arm, and the
    Pareto frontier — refusing an uncontrolled router figure.

    Order matters and is fixed: the global component mask comes from
    the COMPLETE matrix before anything else; the control-set gate runs
    before any router figure is computed; insufficiency propagates and
    is never rendered as zero.
    """
    # ── ONE comparison identity, reusing T3's frozen fingerprint
    # semantics: the router evidence and the control matrix must agree
    # on EVERY fingerprint component durably represented on both sides
    # — preset alone is too weak (same preset, different registry means
    # the arms did not run in the same routing universe, which
    # invalidates the plane more fundamentally than a missing control).
    # The explicit boundary: execution_identity is the one component
    # routing-run records do not carry (the router fixes no single
    # profile; its per-attempt selections live in routing_decisions),
    # so it is matrix-only by construction — everything carried is
    # compared, nothing is silently assumed equal, and a component that
    # cannot be proven (a null toolchain) REFUSES.
    if matrix.fingerprint.preset_digest != expected_preset_digest:
        raise ControlSetIncomplete(
            f"the matrix carries preset digest "
            f"{matrix.fingerprint.preset_digest!r}, expected "
            f"{expected_preset_digest!r} — controls from another preset "
            f"control nothing"
        )
    comparable = (
        ("preset_digest", matrix.fingerprint.preset_digest),
        ("registry_digest", matrix.fingerprint.registry_digest),
        ("task_set_revision", matrix.fingerprint.task_set_revision),
        ("toolchain_digest", matrix.fingerprint.toolchain_digest),
    )
    for i, r in enumerate(router_records):
        for component, matrix_value in comparable:
            record_value = r.get(component)
            if record_value is None:
                raise ControlSetIncomplete(
                    f"router record {i} cannot prove its {component} — "
                    f"comparability is never silently assumed"
                )
            if record_value != matrix_value:
                raise ControlSetIncomplete(
                    f"router record {i} carries {component} "
                    f"{record_value!r} but the control matrix carries "
                    f"{matrix_value!r} — the router and its controls did not "
                    f"run in the same routing universe, so no comparative "
                    f"figure exists"
                )

    # ── the ONE global mask, before any selection is consulted ──
    mask = compute_mask(matrix)

    # ── the control-set gate: hard error, never a warning ──
    for control in REQUIRED_CONTROLS:
        selection = control_selections.get(control)
        if selection is None:
            raise ControlSetIncomplete(
                f"control arm '{control}' is missing — a cct_router figure "
                f"without its complete control set is the uncontrolled number "
                f"this increment exists to prevent"
            )
        if selection.insufficient:
            raise ControlSetIncomplete(
                f"control arm '{control}' is insufficient_evidence "
                f"({dict(selection.insufficient)}) — an insufficient control "
                f"never satisfies the gate"
            )

    arms: dict[str, ArmReport] = {}

    def _report_arm(kind: str, cells: Sequence[Cell],
                    sequence_dependent: Mapping[str, Any],
                    selection_insufficient: "Mapping[str, str] | None" = None,
                    ) -> ArmReport:
        insufficient: dict[str, str] = {}
        sequence_dependent = dict(sequence_dependent)
        sequence_reason = sequence_dependent.pop("insufficient_reason", None)
        if sequence_reason is not None:
            insufficient["sequence_dependent"] = sequence_reason
        try:
            # Decision 9: an arm whose SELECTION is itself insufficient
            # is carried through as insufficiency — a Q over partial
            # coverage would misrepresent the arm, and insufficiency is
            # never rendered as a number.
            if selection_insufficient:
                for key, reason in sorted(selection_insufficient.items()):
                    insufficient[f"selection:{key}"] = reason
                raise QualityInsufficient(
                    f"arm '{kind}' has an insufficient selection — Q is "
                    f"withheld rather than computed over partial coverage"
                )
            quality = arm_quality(cells, mask)
            vector = dict(component_aggregates(cells, mask))
        except QualityInsufficient as exc:
            quality, vector = None, {}
            insufficient["quality"] = str(exc)
        cost = _arm_cost(cells, matrix.cost_basis)
        if cost["status"] == INSUFFICIENT:
            insufficient["cost"] = cost["reason"]
        return ArmReport(
            kind=kind,
            quality=quality,
            metrics={**vector, **sequence_dependent},
            cost=cost,
            insufficient=insufficient,
        )

    na = {m: NOT_APPLICABLE for m in SEQUENCE_DEPENDENT_MEASURES}
    for control in REQUIRED_CONTROLS:
        selection = control_selections[control]
        arms[control] = _report_arm(control, selection.chosen, na)
    if "oracle_budget" in control_selections:
        selection = control_selections["oracle_budget"]
        arms["oracle_budget"] = _report_arm(
            "oracle_budget", selection.chosen, na,
            selection_insufficient=selection.insufficient,
        )

    router_cells = router_cells_from_records(router_records)
    arms["cct_router"] = _report_arm(
        "cct_router", router_cells,
        _sequence_dependent_from_records(router_records),
    )

    # ── the plane: Q + cost + Pareto. The cost axis requires EVERY arm
    # priced under the one basis; otherwise the frontier is withheld as
    # insufficiency — never partially drawn. Q stays reported. ──
    pareto: Any
    if any(a.quality is None for a in arms.values()):
        pareto = {"status": INSUFFICIENT,
                  "reason": "an arm's Q is withheld — no comparable plane"}
    elif any(a.cost["status"] == INSUFFICIENT for a in arms.values()):
        pareto = {"status": INSUFFICIENT,
                  "reason": "an arm's cost does not satisfy the declared "
                            "cost_basis — the frontier is withheld, not "
                            "partially drawn"}
    else:
        points = sorted(
            ((k, a.quality, a.cost["value"]) for k, a in arms.items()),
            key=lambda p: (p[2], -p[1], p[0]),
        )
        frontier, best_q = [], None
        for kind, q, cost_value in points:
            if best_q is None or q > best_q:
                frontier.append({"arm": kind, "quality": q, "cost": cost_value})
                best_q = q
        pareto = {"status": "ok", "frontier": frontier}

    return {
        "quality_fn": QUALITY_FN_VERSION,
        "components_included": list(mask),
        "cost_basis": matrix.cost_basis,
        "preset_digest": expected_preset_digest,
        "arms": {
            kind: {
                "quality": a.quality,
                "metrics": dict(a.metrics),
                "cost": dict(a.cost),
                "insufficient": dict(a.insufficient),
            }
            for kind, a in arms.items()
        },
        "pareto": pareto,
    }
