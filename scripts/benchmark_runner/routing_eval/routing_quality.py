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

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .outcome_matrix import (
    NOT_APPLICABLE,
    SEQUENCE_DEPENDENT_MEASURES,
    ArmSelection,
    Cell,
    OutcomeMatrix,
    select_always_best,
    select_always_cheapest,
    select_oracle,
)
from .quality_fn import (
    QUALITY_FN_VERSION,
    QualityInsufficient,
    arm_quality,
    cell_quality,
    component_aggregates,
    compute_mask,
)

INSUFFICIENT = "insufficient_evidence"

#: The three controls a cct_router figure must never appear without.
REQUIRED_CONTROLS = ("always_best", "always_cheapest", "oracle")


class ControlSetIncomplete(Exception):
    """The reporter refuses to emit a cct_router figure uncontrolled."""


@dataclass(frozen=True)
class SelectorContext:
    """The AUTHORITATIVE inputs for control-selector recomputation.

    Selector recomputation is only as strong as its inputs, so this
    context is DERIVED, never accepted: ``build_report`` builds it
    internally via :func:`selector_context_from_registry` from the
    registry file and validated scenario config it is given — profile
    tiers/priorities/roles from the production-validated registry, the
    eligibility predicate from the registry's route-class semantics
    plus the production selector's role requirement, the ceiling from
    the config. The derived digests are then verified against the
    matrix fingerprint, so a registry or config other than the one the
    matrix was swept under authorizes nothing.
    """

    registry_digest: str
    preset_digest: str
    profile_meta: Mapping[str, Mapping[str, Any]]
    eligible: Any  # Callable[[str, str], bool] — required, never None
    oracle_budget_ceiling_usd: Optional[float] = None


#: rc_parse's record separators (routing-config.sh RC_US / RC_RS).
_RC_US = "\x1f"
_RC_RS = "\x1e"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _rc_records(registry_path: Path) -> list[tuple[str, str, str, str]]:
    """Validate and tokenize the registry through THE production path
    — ``rc_validate`` in routing-config.sh, exactly what the
    supervisor runs before selecting anything — never a reimplemented
    subset and never grammar-only. A grammar OR semantic violation
    (missing required profile fields, duplicate ids, invalid roles)
    refuses by name; the accepted shape and rules are owned in exactly
    one place.

    The record stream is split on NEWLINES ONLY: ``str.splitlines``
    would treat the array element separator RC_RS (0x1e) as a line
    boundary and truncate every multi-element ``tier_order``/``roles``
    value to its first element."""
    # rc_validate prints violations on stdout and leaves RC_PARSED in
    # the CURRENT shell — so it must not run in a command-substitution
    # subshell, or the parsed records die with it. Violations go to
    # stderr; the record stream is the only stdout.
    script = (
        'source "$1/scripts/lib/routing-config.sh"\n'
        'if ! rc_validate "$2" 1>&2; then exit 1; fi\n'
        'printf "%s" "$RC_PARSED"\n'
    )
    proc = subprocess.run(
        ["bash", "-c", script, "rc", str(_REPO_ROOT), str(registry_path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise ControlSetIncomplete(
            f"registry {registry_path} is rejected by the production "
            f"validator — a selector context is never built from an invalid "
            f"registry: {proc.stderr.strip()[:300]}"
        )
    records = []
    for line in proc.stdout.split("\n"):
        parts = line.split(_RC_US)
        if len(parts) == 4:
            records.append((parts[0], parts[1], parts[2], parts[3]))
    return records


def selector_context_from_registry(
    registry_path: "Path | str",
    config: Any,
) -> SelectorContext:
    """The production way to build a SelectorContext, derived ENTIRELY
    from the digested registry and the validated scenario config:

    - profile tiers/priorities from the registry's own
      ``capability_tier``/``priority`` declarations, parsed by the
      production grammar (``rc_parse``), never a lookalike subset;
    - the eligibility predicate from the registry's route-class
      semantics under the increments' frozen task classes — ordinary
      work routes ``tier1_only``, the config's declared
      ``delegate_tasks`` route ``tier2_preferred`` — so a profile is
      eligible exactly when its declared tier appears in the class's
      ``tier_order``. Nothing is caller-supplied, so a matching
      registry digest can never accompany fabricated eligibility;
    - the registry digest from the same file, the preset digest and
      ``budget_ceiling_usd`` from the validated config."""
    from .injection import preset_digest
    from .supervisor_runner import registry_digest_of

    by_ctx: dict[str, dict[str, tuple[str, str]]] = {}
    for ctx, key, typ, value in _rc_records(Path(registry_path)):
        by_ctx.setdefault(ctx, {})[key] = (typ, value)

    meta: dict[str, dict[str, Any]] = {}
    route_classes: dict[str, tuple[str, ...]] = {}
    for ctx, keys in by_ctx.items():
        if ctx.startswith("profiles."):
            profile_id = keys.get("id", ("", ""))[1]
            if not profile_id:
                continue
            entry: dict[str, Any] = {}
            if "capability_tier" in keys:
                entry["tier"] = keys["capability_tier"][1]
            if "priority" in keys:
                entry["priority"] = int(keys["priority"][1])
            if "roles" in keys:
                entry["roles"] = tuple(
                    r for r in keys["roles"][1].split(_RC_RS) if r
                )
            meta[profile_id] = entry
        elif ctx.startswith("route_classes."):
            name = ctx.split(".", 1)[1]
            _typ, value = keys.get("tier_order", ("", ""))
            route_classes[name] = tuple(t for t in value.split(_RC_RS) if t)

    delegate_tasks = frozenset(getattr(config, "delegate_tasks", ()) or ())

    def eligible(profile_id: str, task_id: str) -> bool:
        # The PRODUCTION selector's predicate, both halves: the
        # execution ROLE (rt_select rejects any candidate that "does
        # not hold role '<role>'" — ordinary builds select with role
        # `build`, packet delegation with `bounded-build`) AND the
        # route class's TIER semantics. The class tier semantics are
        # BUILT INTO rt_select's closed vocabulary — tier1_only admits
        # tier1 only ("increment B routes tier1 only"), tier2_preferred
        # admits tier2 then tier1 — and are NOT read from the
        # registry's [route_classes.*] tables at selection time (those
        # govern task-metadata validation). Mirroring the tables here
        # instead of the selector would wrongly rule every profile
        # ineligible under a registry that declares no such table.
        profile = meta.get(profile_id) or {}
        if task_id in delegate_tasks:
            required_role = "bounded-build"
            admitted_tiers = ("tier2", "tier1")
        else:
            required_role = "build"
            admitted_tiers = ("tier1",)
        return (
            required_role in (profile.get("roles") or ())
            and profile.get("tier") in admitted_tiers
        )

    return SelectorContext(
        registry_digest=registry_digest_of(Path(registry_path)),
        preset_digest=preset_digest(config),
        profile_meta=meta,
        eligible=eligible,
        oracle_budget_ceiling_usd=config.budget_ceiling_usd,
    )


class LifecycleInvalid(ValueError):
    """The router records do not describe exact, well-formed
    lifecycles — partial coverage is refused, never averaged over."""


def _verify_lifecycle_shape(
    key: tuple[str, int], legs: Sequence[Mapping[str, Any]]
) -> None:
    """One (task, trial) lifecycle is either ONE ordinary record, or a
    provisional leg followed by its reconciliation — same seed, same
    packet identity. Anything else refuses (the deleted-provisional
    laundering mutation dies here: a reconciliation record alone can
    never score)."""
    seeds = {r.get("trial_seed") for r in legs}
    if len(seeds) != 1:
        raise LifecycleInvalid(
            f"lifecycle {key} mixes trial seeds {sorted(map(repr, seeds))} — "
            f"its legs do not describe one trial"
        )
    recon_legs = [r for r in legs if r.get("reconciliation")]
    delegated_legs = [
        r for r in legs
        if (r.get("tier2") or {}).get("delegated") and not r.get("reconciliation")
    ]
    if len(recon_legs) > 1:
        raise LifecycleInvalid(
            f"lifecycle {key} carries {len(recon_legs)} reconciliation "
            f"records — duplicate final legs refuse, never average"
        )
    if not recon_legs and not delegated_legs:
        if len(legs) != 1:
            raise LifecycleInvalid(
                f"lifecycle {key} carries {len(legs)} ordinary records — "
                f"exactly one, or the trial is double-counted"
            )
        return
    if not recon_legs:
        raise LifecycleInvalid(
            f"lifecycle {key} delegated but was never reconciled — an "
            f"unreconciled delegation is not router evidence"
        )
    if not delegated_legs:
        raise LifecycleInvalid(
            f"lifecycle {key} carries a reconciliation without its "
            f"provisional leg — the provisional evidence (cost, "
            f"interventions, repair signatures) cannot be allowed to vanish"
        )
    if len(legs) != 2 or legs[-1] is not recon_legs[0]:
        raise LifecycleInvalid(
            f"lifecycle {key} is not provisional-then-reconciliation — "
            f"{len(legs)} legs in an order that describes no lifecycle"
        )
    provisional_t2 = delegated_legs[0].get("tier2") or {}
    recon = recon_legs[0]["reconciliation"]
    if (provisional_t2.get("packet_id"), provisional_t2.get("packet_digest")) != (
        recon.get("packet_id"), recon.get("packet_digest")
    ):
        raise LifecycleInvalid(
            f"lifecycle {key}: the provisional and reconciliation legs name "
            f"different packets — a join on task order is not a join"
        )


def router_cells_from_records(
    records: Sequence[Mapping[str, Any]],
    *,
    matrix: "OutcomeMatrix | None" = None,
) -> list[Cell]:
    """Reduce routing-run records to EXACTLY ONE cell per
    (task, trial) — the NORMATIVE LIFECYCLE FOLD.

    The labeled E1 correction (routing-shadow plan decision 3): a
    delegated task's lifecycle spans a provisional record and a later
    reconciliation record; converting every record to a cell
    double-weighted the task and let a clean reconciliation launder
    the provisional leg's process evidence out of Q. The fold's
    per-component contract:

    - verifier outcome and the state regressions (rows 1-5): the
      FINAL lifecycle leg — final-state evidence. A reconciliation
      record without explicit verifiers scores ``pass`` exactly when
      its outcome is ``reconciled`` (increment C promotes only after
      re-running the packet verifiers green; a verdict the verifiers
      contradict never promotes);
    - scope violation and intervention (rows 6, 8): UNION across all
      lifecycle legs — process evidence never launders;
    - repeated repair (row 7): computed over the CONCATENATED repair
      signature stream of all legs — the same signature once per leg
      IS a lifecycle repeat;
    - cost (row 12) and elapsed (row 13): SUM across legs under
      provenance homogeneity — any unpriced or foreign-provenance leg
      makes the trial's cost unavailable, never partial;
    - the fold refuses duplicate final legs for one (task, trial).

    Records that share a (task, trial) are one lifecycle, in record
    order. Single-record lifecycles reduce exactly as before.
    """
    lifecycles: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    order: list[tuple[str, int]] = []
    for r in records:
        key = (r["task_id"], r["trial"])
        if key not in lifecycles:
            lifecycles[key] = []
            order.append(key)
        lifecycles[key].append(r)
    for key in order:
        _verify_lifecycle_shape(key, lifecycles[key])
    cells = [_fold_lifecycle(key, lifecycles[key]) for key in order]
    if matrix is not None:
        # EXACT task x trial coverage against the declared matrix
        # (rev-5: duplicate or missing folded entries REFUSE the
        # report) with the declared seed pairing.
        expected = {
            (task, trial)
            for task in matrix.task_ids
            for trial in range(matrix.trials)
        }
        got = {(c.task_id, c.trial) for c in cells}
        missing = sorted(expected - got)
        extra = sorted(got - expected)
        if missing or extra:
            raise LifecycleInvalid(
                f"router coverage is not the declared task x trial set — "
                f"missing {missing}, extra {extra}; a report over partial "
                f"coverage is refused, never computed"
            )
        for cell in cells:
            declared_seed = matrix.trial_seeds[cell.trial]
            if cell.seed != declared_seed:
                raise LifecycleInvalid(
                    f"lifecycle ({cell.task_id}, {cell.trial}) carries seed "
                    f"{cell.seed}, the matrix declares {declared_seed} — "
                    f"the trials are not the same trials"
                )
    return cells


def _fold_lifecycle(
    key: tuple[str, int], legs: Sequence[Mapping[str, Any]]
) -> Cell:
    """One (task, trial) lifecycle -> one metric cell, per the
    normative per-component contract above."""
    final = legs[-1]
    reconciled = [r for r in legs if r.get("reconciliation")]
    if len(reconciled) > 1:
        raise ValueError(
            f"lifecycle {key} carries {len(reconciled)} reconciliation "
            f"records — duplicate final legs refuse, never average"
        )
    if reconciled and reconciled[0] is not legs[-1]:
        raise ValueError(
            f"lifecycle {key} has records after its reconciliation — "
            f"the record order does not describe one lifecycle"
        )

    # rows 1-5: final-state evidence from the FINAL leg
    result = _final_result(final)
    regressions = _state_regressions(final)

    # rows 6, 8: union across legs (True > None > False)
    scope = _union_flag(
        bool(r.get("scope_violations")) if r.get("scope_violations") is not None
        else None
        for r in legs
    )
    intervention = _union_flag(
        bool(r.get("interventions")) if r.get("interventions") is not None
        else None
        for r in legs
    )

    # row 7: the concatenated signature stream
    signatures = [
        c.get("signature")
        for r in legs
        for c in (r.get("repair_cycles") or [])
    ]
    repeated = len(signatures) != len(set(signatures))

    # rows 12-13: sums under homogeneity
    cost_value, provenance, estimator = _sum_cost(legs)
    elapsed = _sum_elapsed(legs)

    return Cell(
        task_id=key[0],
        profile_id=final.get("profile_id") or "cct_router",
        trial=key[1],
        seed=final.get("trial_seed", 0),
        eligible=True,
        result=result,
        regressions=regressions,
        scope_violation=scope,
        repeated_repair=repeated,
        intervention=intervention,
        cost_value=cost_value,
        cost_provenance=provenance,
        cost_estimator=estimator,
        elapsed_seconds=elapsed,
    )


def _final_result(final: Mapping[str, Any]) -> Optional[str]:
    verifiers = final.get("verifiers") or []
    if verifiers:
        return (
            "pass"
            if all(v.get("exit_status") == 0 for v in verifiers)
            else "fail"
        )
    reconciliation = final.get("reconciliation")
    if reconciliation is not None:
        return "pass" if reconciliation.get("outcome") == "reconciled" else "fail"
    return None


def _state_regressions(final: Mapping[str, Any]) -> Mapping[str, Optional[bool]]:
    baseline = final.get("baseline") or {}
    gates = final.get("quality_gates") or {}
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
        return None if before is None else False

    return {
        "lint": _baseline_regressed("lint"),
        "typecheck": _baseline_regressed("typecheck"),
        "coverage": _regressed(coverage.get("before"), coverage.get("after")),
        "security": _security_regressed(
            security.get("before"), security.get("after")
        ),
    }


def _union_flag(values) -> Optional[bool]:
    saw_none = False
    for v in values:
        if v is True:
            return True
        if v is None:
            saw_none = True
    return None if saw_none else False


def _sum_cost(legs: Sequence[Mapping[str, Any]]):
    costs = [r.get("cost") or {} for r in legs]
    provenances = {c.get("provenance", "unavailable") for c in costs}
    if len(provenances) != 1:
        return None, "unavailable", None
    provenance = provenances.pop()
    if provenance == "unavailable" or any(c.get("value") is None for c in costs):
        return None, "unavailable", None
    estimators = {c.get("estimator") for c in costs}
    if len(estimators) != 1:
        return None, "unavailable", None
    return sum(c["value"] for c in costs), provenance, estimators.pop()


def _sum_elapsed(legs: Sequence[Mapping[str, Any]]) -> Optional[float]:
    values = [r.get("elapsed_seconds") for r in legs]
    if any(v is None for v in values):
        return None
    return float(sum(values))


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
    registry_path: "Path | str",
    config: Any,
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

    # ── selector authority is DERIVED here, never accepted ──
    # The context is built inside the reporting boundary from the
    # registry file and the validated scenario config — a caller has
    # nothing to hand us but the paths to the declarations themselves,
    # so copied digests can never accompany fabricated metadata or a
    # fabricated predicate. The derived digests must then match the
    # matrix fingerprint: a registry file or config other than the one
    # the matrix was swept under authorizes nothing, and a matrix
    # profile the registry does not declare refuses (no lexical
    # fallback).
    selector_context = selector_context_from_registry(registry_path, config)
    if selector_context.registry_digest != matrix.fingerprint.registry_digest:
        raise ControlSetIncomplete(
            f"the selector context carries registry digest "
            f"{selector_context.registry_digest!r} but the matrix carries "
            f"{matrix.fingerprint.registry_digest!r} — a context from another "
            f"registry authorizes nothing"
        )
    if selector_context.preset_digest != matrix.fingerprint.preset_digest:
        raise ControlSetIncomplete(
            f"the selector context carries preset digest "
            f"{selector_context.preset_digest!r} but the matrix carries "
            f"{matrix.fingerprint.preset_digest!r} — a context from another "
            f"preset authorizes nothing"
        )
    from .outcome_matrix import _TIER_ORDER

    for profile in sorted({c.profile_id for c in matrix.cells}):
        tier = (selector_context.profile_meta.get(profile) or {}).get("tier")
        if tier not in _TIER_ORDER:
            raise ControlSetIncomplete(
                f"matrix profile {profile!r} has no declared capability tier "
                f"in the selector context ({tier!r}) — lexical fallback "
                f"ordering is never an authority for always_best"
            )

    # ── control cells must BE the declared matrix's cells ──
    # "Computed from the same outcome matrix" is proven, not assumed:
    # every selected control cell must be identical — coordinates AND
    # measures — to an eligible cell of this matrix. A foreign cell, a
    # re-measured cell, or an ineligible cell controls nothing.
    by_key = {
        (c.task_id, c.profile_id, c.trial, c.seed): c for c in matrix.cells
    }
    for kind, selection in control_selections.items():
        for cell in selection.chosen:
            key = (cell.task_id, cell.profile_id, cell.trial, cell.seed)
            canonical = by_key.get(key)
            if canonical is None:
                raise ControlSetIncomplete(
                    f"control arm '{kind}' selected cell {key} which is not "
                    f"in the declared outcome matrix — a control from outside "
                    f"the matrix controls nothing"
                )
            if canonical != cell:
                raise ControlSetIncomplete(
                    f"control arm '{kind}' carries cell {key} whose measures "
                    f"differ from the declared matrix's cell — controls are "
                    f"SELECTED from the matrix, never re-measured or edited"
                )
            if not canonical.eligible:
                raise ControlSetIncomplete(
                    f"control arm '{kind}' selected ineligible cell {key} — "
                    f"an unexecuted cell is never a control"
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

    # ── declared selectors are RECOMPUTED, and supplied selections
    # must equal their output exactly. Matrix membership is necessary
    # but not sufficient: genuine eligible cells can still omit tasks
    # or trials, name the wrong eligible profile for
    # always_best/always_cheapest, or hand the oracle a non-optimal
    # cell. A selection that is not its own selector's result over
    # this matrix controls nothing. ──
    def _expect_selector(kind: str, recomputed: ArmSelection) -> None:
        supplied = control_selections[kind]
        if (
            tuple(supplied.chosen) != tuple(recomputed.chosen)
            or dict(supplied.insufficient) != dict(recomputed.insufficient)
        ):
            raise ControlSetIncomplete(
                f"control arm '{kind}' does not equal the declared selector's "
                f"output over this matrix — partial, mis-profiled, or "
                f"non-optimal selections of genuine cells are refused, not "
                f"reported"
            )

    eligible = selector_context.eligible
    ceiling = selector_context.oracle_budget_ceiling_usd
    _expect_selector(
        "always_best",
        select_always_best(
            matrix, selector_context.profile_meta, eligible=eligible
        ),
    )
    _expect_selector(
        "always_cheapest", select_always_cheapest(matrix, eligible=eligible)
    )
    _expect_selector(
        "oracle",
        select_oracle(matrix, lambda c: cell_quality(c, mask), eligible=eligible),
    )
    if "oracle_budget" in control_selections:
        if ceiling is None:
            raise ControlSetIncomplete(
                "an oracle_budget selection was supplied but the validated "
                "config declares no budget ceiling — the reporting boundary "
                "cannot verify a selector it cannot recompute"
            )
        _expect_selector(
            "oracle_budget",
            select_oracle(
                matrix,
                lambda c: cell_quality(c, mask),
                ceiling,
                eligible=eligible,
            ),
        )
    elif ceiling is not None:
        raise ControlSetIncomplete(
            f"the validated config declares budget ceiling {ceiling} (an "
            f"oracle_budget arm) but no oracle_budget selection was supplied "
            f"— a declared arm is never silently dropped"
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

    router_cells = router_cells_from_records(router_records, matrix=matrix)
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

    # ── report v1 (routing-shadow decision 3): selection provenance
    # and the per-task/per-trial figure tables — the intermediate
    # values of THIS pipeline's own aggregation, emitted so a consumer
    # never recomputes anything. ──
    def _selections_of(kind: str) -> Mapping[str, Any]:
        selection = control_selections.get(kind)
        if selection is None:
            return {}
        if kind.startswith("oracle"):
            nested: dict[str, dict[str, str]] = {}
            for cell in selection.chosen:
                nested.setdefault(cell.task_id, {})[str(cell.trial)] = (
                    cell.profile_id
                )
            return nested
        return {c.task_id: c.profile_id for c in selection.chosen}

    def _task_table(cells: Sequence[Cell]) -> Mapping[str, Any]:
        by_task: dict[str, list[Cell]] = {}
        for cell in cells:
            by_task.setdefault(cell.task_id, []).append(cell)
        table: dict[str, Any] = {}
        for task, task_cells in sorted(by_task.items()):
            per_trial = []
            for cell in sorted(task_cells, key=lambda c: c.trial):
                try:
                    q = cell_quality(cell, mask)
                except QualityInsufficient:
                    q = None
                cost_v = (
                    cell.cost_value
                    if cell.cost_satisfies(matrix.cost_basis)
                    else None
                )
                per_trial.append(
                    {"trial": cell.trial, "quality": q, "cost": cost_v}
                )
            qualities = [t["quality"] for t in per_trial]
            costs = [t["cost"] for t in per_trial]
            table[task] = {
                "quality": (
                    sum(qualities) / len(qualities)
                    if qualities and all(v is not None for v in qualities)
                    else None
                ),
                "cost": (
                    sum(costs) / len(costs)
                    if costs and all(v is not None for v in costs)
                    else None
                ),
                "per_trial": per_trial,
            }
        return table

    arm_cells: dict[str, Sequence[Cell]] = {
        kind: control_selections[kind].chosen
        for kind in arms
        if kind in control_selections
    }
    arm_cells["cct_router"] = router_cells

    fp = matrix.fingerprint
    return {
        "schema_version": 1,
        "quality_fn": QUALITY_FN_VERSION,
        "components_included": list(mask),
        "cost_basis": matrix.cost_basis,
        "preset_digest": expected_preset_digest,
        "fingerprint": {
            "registry_digest": fp.registry_digest,
            "preset_digest": fp.preset_digest,
            "execution_identity": [dict(e) for e in fp.execution_identity],
            "task_set_revision": fp.task_set_revision,
            "toolchain_digest": fp.toolchain_digest,
        },
        "arms": {
            kind: {
                "quality": a.quality,
                "metrics": dict(a.metrics),
                "cost": dict(a.cost),
                "insufficient": dict(a.insufficient),
                "selections": _selections_of(kind),
                "tasks": _task_table(arm_cells.get(kind, ())),
            }
            for kind, a in arms.items()
        },
        "pareto": pareto,
    }


class ReportInvalid(ValueError):
    """The persisted report would violate its own contract."""


def write_report(
    report: Mapping[str, Any],
    path: "Path | str",
    *,
    source_artifacts: Mapping[str, str],
) -> Path:
    """Persist the comparison report as `report.json` — the E1 side of
    the routing-shadow evidence contract.

    ``source_artifacts`` carries the sha256 bindings of the published
    `routing-runs.jsonl` and `outcome-matrix.json` bytes (computed by
    the publisher from the SAME bytes it wrote). The completed report
    is validated against report.schema.json BEFORE any byte lands
    (fail-closed — an unvalidatable report is never persisted), then
    written canonically and atomically; a pre-existing path refuses —
    the same discipline as every other E1 artifact writer.
    """
    import json as _json
    import os as _os

    from .record_check import load_schema, validate

    out = Path(path)
    if out.exists():
        raise ReportInvalid(
            f"report artifact {out} already exists — refusing to overwrite "
            f"a persisted result artifact"
        )
    completed = dict(report)
    completed["source_artifacts"] = dict(source_artifacts)
    errors = validate(completed, load_schema("report"))
    if errors:
        raise ReportInvalid(
            f"the report does not satisfy report.schema.json: {errors[:5]}"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(
        _json.dumps(completed, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    _os.replace(tmp, out)
    return out
