"""The task x profile x trial outcome matrix and its derived arms (E1 T3).

Plan decision 3: one sweep yields every control, so only ``cct_router``
executes live. That is only *valid* under three constraints, all
enforced here:

- **Trials are a dimension.** Cells are keyed ``(task, profile,
  trial)`` and never averaged before storage.
- **Only independent measures may be derived.** Sequence-dependent
  measures (§Metric contract rows 9-11) have no cell slot at all;
  derived arms report them ``not_applicable`` by construction.
- **Reuse is fingerprint-gated.** A stored matrix is reusable only
  when every one of the five components matches; a mismatch names the
  component and refuses.

Control selectors follow plan.md §Control selectors exactly. A control
is a per-task selection under a fixed rule, never a literal matrix
column, because eligibility varies by task. The oracle chooses per
``(task, trial)`` — the true hindsight bound — and bounds quality, not
cost. ``quality`` is a parameter here: the versioned projection
(§quality_fn v1) is T5's deliverable, and the selectors must not bake
in a competing definition. The declared tie-break sequence, however,
IS implemented here, because it is computable from cell fields and an
unordered tie would make selection an artifact of iteration order.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Optional

MATRIX_SCHEMA_VERSION = 1

#: §Metric contract rows 9-11 — measured only along a stateful run.
SEQUENCE_DEPENDENT_MEASURES = (
    "tier2_accepted_unchanged",
    "reconciliation_rework_ratio",
    "rollbacks",
)
NOT_APPLICABLE = "not_applicable"

#: Capability-tier order, best first — tier1 outranks tier2 (the
#: registry's closed vocabulary; increment A).
_TIER_ORDER = {"tier1": 0, "tier2": 1}


class ReuseRefused(ValueError):
    """A stored matrix's fingerprint does not match; reuse is refused."""


class MatrixIntegrityError(ValueError):
    """The matrix is not the exact declared Cartesian sweep.

    Schema validity is not coverage: a persisted matrix that lost one
    expensive trial cell would let always_cheapest average whatever
    remains and win on incomplete evidence, and a vanished oracle
    candidate silently lowers the hindsight bound. Selectors refuse an
    incomplete matrix rather than deriving biased controls from it."""


class InsufficientEvidence(Exception):
    """A selection that cannot be made honestly. Never a zero."""


@dataclass(frozen=True)
class Fingerprint:
    registry_digest: str
    preset_digest: str
    execution_identity: tuple[Mapping[str, Any], ...]
    task_set_revision: str
    toolchain_digest: str

    COMPONENTS = (
        "registry_digest",
        "preset_digest",
        "execution_identity",
        "task_set_revision",
        "toolchain_digest",
    )


@dataclass(frozen=True)
class Cell:
    task_id: str
    profile_id: str
    trial: int
    #: The trial seed — part of the cell's canonical identity
    #: (task_id, profile_id, trial, seed). Ineligible cells carry the
    #: seed their trial WOULD have used: pairing is declared, not
    #: conditional on execution.
    seed: int
    eligible: bool
    result: Optional[str] = None
    regressions: Mapping[str, Optional[bool]] = field(default_factory=dict)
    scope_violation: Optional[bool] = None
    repeated_repair: Optional[bool] = None
    intervention: Optional[bool] = None
    cost_value: Optional[float] = None
    cost_provenance: str = "unavailable"
    cost_estimator: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    routing_run_ref: Optional[str] = None

    def cost_satisfies(self, cost_basis: str) -> bool:
        """Provenance homogeneity (§Cost and reporting contract): a cell
        may contribute cost only under the comparison's single declared
        basis, with estimated cells pinned to their table version."""
        if self.cost_value is None:
            return False
        if cost_basis == "measured":
            return self.cost_provenance == "measured"
        if cost_basis.startswith("estimated@"):
            wanted = cost_basis.split("@", 1)[1]
            return (
                self.cost_provenance == "estimated"
                and self.cost_estimator == wanted
            )
        return False


@dataclass(frozen=True)
class OutcomeMatrix:
    fingerprint: Fingerprint
    #: The DECLARED task list — what coverage is verified against.
    task_ids: tuple[str, ...]
    trials: int
    trial_seeds: tuple[int, ...]
    cost_basis: str
    cells: tuple[Cell, ...]
    schema_version: int = MATRIX_SCHEMA_VERSION

    def tasks(self) -> list[str]:
        return list(self.task_ids)

    def cells_for(self, task_id: str, profile_id: Optional[str] = None) -> list[Cell]:
        return [
            c
            for c in self.cells
            if c.task_id == task_id
            and (profile_id is None or c.profile_id == profile_id)
        ]

    def eligible_profiles(self, task_id: str) -> list[str]:
        seen: dict[str, None] = {}
        for c in self.cells:
            if c.task_id == task_id and c.eligible:
                seen.setdefault(c.profile_id, None)
        return list(seen)


# ── build (the sweep) ──────────────────────────────────────────────────


def build_matrix(
    fingerprint: Fingerprint,
    tasks: list[str],
    profiles: list[str],
    trial_seeds: list[int],
    cost_basis: str,
    eligible: Callable[[str, str], bool],
    execute: Callable[[str, str, int, int], Cell],
) -> OutcomeMatrix:
    """Sweep every eligible (task, profile, trial); emit the matrix.

    ``execute(task, profile, trial, seed)`` runs one fixed-profile cell
    and returns it — in production that is the benchmark runner; tests
    stub it. Ineligible pairs get an explicit ineligible cell rather
    than silence: eligibility varies by task, and the selectors need to
    see that a profile was *considered and ineligible*, not unrun.
    Iteration order is deterministic (declared task order, profile id
    lexical, trial index) — no time, no randomness here.
    """
    cells: list[Cell] = []
    for task in tasks:
        for profile in sorted(profiles):
            is_eligible = bool(eligible(profile, task))
            for trial, seed in enumerate(trial_seeds):
                if not is_eligible:
                    cells.append(
                        Cell(task_id=task, profile_id=profile, trial=trial,
                             seed=seed, eligible=False)
                    )
                    continue
                cell = execute(task, profile, trial, seed)
                if (cell.task_id, cell.profile_id, cell.trial, cell.seed) != (
                    task, profile, trial, seed
                ):
                    raise ValueError(
                        f"executor returned a cell for {cell.task_id}/{cell.profile_id}"
                        f"/trial-{cell.trial}/seed-{cell.seed}, expected "
                        f"{task}/{profile}/trial-{trial}/seed-{seed}"
                    )
                cells.append(cell)
    matrix = OutcomeMatrix(
        fingerprint=fingerprint,
        task_ids=tuple(tasks),
        trials=len(trial_seeds),
        trial_seeds=tuple(trial_seeds),
        cost_basis=cost_basis,
        cells=tuple(cells),
    )
    verify_matrix(matrix)
    return matrix


# ── persistence (the schema's shape, canonical bytes) ──────────────────


def matrix_to_record(matrix: OutcomeMatrix) -> dict[str, Any]:
    return {
        "schema_version": matrix.schema_version,
        "fingerprint": {
            "registry_digest": matrix.fingerprint.registry_digest,
            "preset_digest": matrix.fingerprint.preset_digest,
            "execution_identity": [dict(e) for e in matrix.fingerprint.execution_identity],
            "task_set_revision": matrix.fingerprint.task_set_revision,
            "toolchain_digest": matrix.fingerprint.toolchain_digest,
        },
        "tasks": list(matrix.task_ids),
        "trials": matrix.trials,
        "trial_seeds": list(matrix.trial_seeds),
        "cost_basis": matrix.cost_basis,
        "cells": [
            {
                "task_id": c.task_id,
                "profile_id": c.profile_id,
                "trial": c.trial,
                "seed": c.seed,
                "eligible": c.eligible,
                "result": c.result,
                "regressions": dict(c.regressions),
                "scope_violation": c.scope_violation,
                "repeated_repair": c.repeated_repair,
                "intervention": c.intervention,
                "cost": {
                    "value": c.cost_value,
                    "provenance": c.cost_provenance,
                    "estimator": c.cost_estimator,
                },
                "elapsed_seconds": c.elapsed_seconds,
                "routing_run_ref": c.routing_run_ref,
            }
            for c in matrix.cells
        ],
    }


def matrix_dumps(matrix: OutcomeMatrix) -> str:
    """Canonical bytes: same matrix, same artifact, byte for byte."""
    return json.dumps(matrix_to_record(matrix), sort_keys=True, separators=(",", ":")) + "\n"


def matrix_from_record(record: Mapping[str, Any]) -> OutcomeMatrix:
    fp = record["fingerprint"]
    return OutcomeMatrix(
        schema_version=record["schema_version"],
        task_ids=tuple(record["tasks"]),
        fingerprint=Fingerprint(
            registry_digest=fp["registry_digest"],
            preset_digest=fp["preset_digest"],
            execution_identity=tuple(fp["execution_identity"]),
            task_set_revision=fp["task_set_revision"],
            toolchain_digest=fp["toolchain_digest"],
        ),
        trials=record["trials"],
        trial_seeds=tuple(record["trial_seeds"]),
        cost_basis=record["cost_basis"],
        cells=tuple(
            Cell(
                task_id=c["task_id"],
                profile_id=c["profile_id"],
                trial=c["trial"],
                seed=c["seed"],
                eligible=c["eligible"],
                result=c.get("result"),
                regressions=c.get("regressions", {}),
                scope_violation=c.get("scope_violation"),
                repeated_repair=c.get("repeated_repair"),
                intervention=c.get("intervention"),
                cost_value=(c.get("cost") or {}).get("value"),
                cost_provenance=(c.get("cost") or {}).get("provenance", "unavailable"),
                cost_estimator=(c.get("cost") or {}).get("estimator"),
                elapsed_seconds=c.get("elapsed_seconds"),
                routing_run_ref=c.get("routing_run_ref"),
            )
            for c in record["cells"]
        ),
    )


# ── matrix integrity: the sweep is an invariant, re-established after
# load. Schema validity alone cannot prove exact Cartesian coverage. ──


def verify_matrix(matrix: OutcomeMatrix) -> None:
    """Prove the exact declared sweep, or refuse (MatrixIntegrityError).

    For each declared task x declared profile (the fingerprint's
    execution identity) x declared (trial, seed): EXACTLY one cell —
    eligibility never removes the cell requirement (ineligible pairs
    have explicit ineligible cells; "missing because ineligible" does
    not exist). No duplicates, no undeclared cells, and every cell's
    seed equals its trial's declared seed.
    """
    violations: list[str] = []
    if len(matrix.trial_seeds) != matrix.trials:
        violations.append(
            f"trial_seeds length {len(matrix.trial_seeds)} != trials {matrix.trials}"
        )
    declared_profiles = tuple(
        e["profile_id"] for e in matrix.fingerprint.execution_identity
    )
    if len(set(declared_profiles)) != len(declared_profiles):
        violations.append("duplicate profile in execution_identity")
    if len(set(matrix.task_ids)) != len(matrix.task_ids):
        violations.append("duplicate task in the declared task list")

    expected = {
        (task, profile, trial)
        for task in matrix.task_ids
        for profile in declared_profiles
        for trial in range(matrix.trials)
    }
    seen: set[tuple[str, str, int]] = set()
    for c in matrix.cells:
        identity = (c.task_id, c.profile_id, c.trial)
        if identity in seen:
            violations.append(f"duplicate cell {identity}")
            continue
        seen.add(identity)
        if identity not in expected:
            violations.append(f"undeclared cell {identity}")
            continue
        declared_seed = matrix.trial_seeds[c.trial]
        if c.seed != declared_seed:
            violations.append(
                f"cell {identity} carries seed {c.seed}, but trial {c.trial} "
                f"declares seed {declared_seed}"
            )
    for missing in sorted(expected - seen):
        violations.append(f"missing cell {missing}")
    if violations:
        raise MatrixIntegrityError(
            "matrix is not the exact declared sweep — refusing to derive "
            "controls from incomplete or corrupt evidence: "
            + "; ".join(violations)
        )


# ── the reuse gate ─────────────────────────────────────────────────────


def check_reuse(stored: Fingerprint, expected: Fingerprint) -> list[str]:
    """The components that differ. Empty list == reusable."""
    mismatched = []
    for component in Fingerprint.COMPONENTS:
        if getattr(stored, component) != getattr(expected, component):
            mismatched.append(component)
    return mismatched


def assert_reusable(stored: OutcomeMatrix, expected: Fingerprint) -> None:
    """Refuse by NAME on any mismatch — stale cells never carry forward."""
    mismatched = check_reuse(stored.fingerprint, expected)
    if mismatched:
        raise ReuseRefused(
            f"stored matrix is not reusable: fingerprint mismatch in {mismatched} — "
            f"a matrix is only evidence for the exact registry, preset, execution "
            f"identity, task set, and toolchain it was swept under"
        )


# ── the declared tie-break (plan.md §quality_fn v1) ────────────────────


def _regression_count(cell: Cell) -> int:
    return sum(1 for v in cell.regressions.values() if v is True)


def tie_break_key(cell: Cell) -> tuple:
    """The declared deterministic sequence: verifier outcome, then
    regressions ascending, then scope violations, then repeated repair,
    then interventions, then cost ascending, then profile id lexical.
    Reconciliation rework is deliberately NOT here — it is
    not_applicable for derived arms and would make arms incomparable.
    Lower tuples win."""
    return (
        0 if cell.result == "pass" else 1,
        _regression_count(cell),
        1 if cell.scope_violation else 0,
        1 if cell.repeated_repair else 0,
        1 if cell.intervention else 0,
        cell.cost_value if cell.cost_value is not None else float("inf"),
        cell.profile_id,
    )


# ── control selectors (plan.md §Control selectors) ─────────────────────


@dataclass(frozen=True)
class ArmSelection:
    """One derived arm: chosen cells plus explicit insufficiency.

    ``sequence_dependent`` is fixed at not_applicable for every derived
    arm — rows 9-11 exist only along a stateful run.
    """

    kind: str
    chosen: tuple[Cell, ...]
    insufficient: Mapping[str, str]  # task_id (or task/trial) -> reason
    sequence_dependent: Mapping[str, str] = field(
        default_factory=lambda: {m: NOT_APPLICABLE for m in SEQUENCE_DEPENDENT_MEASURES}
    )


def select_always_best(
    matrix: OutcomeMatrix, profile_meta: Mapping[str, Mapping[str, Any]]
) -> ArmSelection:
    """Per task: the eligible profile with the highest capability tier;
    ties by priority ascending, then id lexical — the routing
    selector's existing total order, so the baseline is never an
    artifact of registry declaration order."""
    verify_matrix(matrix)
    chosen: list[Cell] = []
    insufficient: dict[str, str] = {}
    for task in matrix.tasks():
        candidates = matrix.eligible_profiles(task)
        if not candidates:
            insufficient[task] = "no eligible profile for this task"
            continue

        def order(pid: str) -> tuple:
            meta = profile_meta.get(pid, {})
            tier = _TIER_ORDER.get(meta.get("tier", ""), len(_TIER_ORDER))
            return (tier, meta.get("priority", float("inf")), pid)

        best = min(candidates, key=order)
        chosen.extend(matrix.cells_for(task, best))
    return ArmSelection("always_best", tuple(chosen), insufficient)


def select_always_cheapest(matrix: OutcomeMatrix) -> ArmSelection:
    """Per task: the eligible profile with the lowest MEAN cost across
    that task's trials, using only cells satisfying the declared
    cost_basis. If ANY eligible profile for the task has no
    basis-satisfying cell, the task is insufficient — never selected on
    mixed provenance. Ties by profile id lexical."""
    verify_matrix(matrix)
    chosen: list[Cell] = []
    insufficient: dict[str, str] = {}
    basis = matrix.cost_basis
    for task in matrix.tasks():
        candidates = matrix.eligible_profiles(task)
        if not candidates:
            insufficient[task] = "no eligible profile for this task"
            continue
        means: dict[str, float] = {}
        blocked: Optional[str] = None
        for pid in candidates:
            priced = [
                c.cost_value
                for c in matrix.cells_for(task, pid)
                if c.cost_satisfies(basis)
            ]
            if not priced:
                blocked = pid
                break
            means[pid] = sum(priced) / len(priced)
        if blocked is not None:
            insufficient[task] = (
                f"eligible profile '{blocked}' has no cell satisfying "
                f"cost_basis '{basis}' — refusing to select on mixed provenance"
            )
            continue
        cheapest = min(means, key=lambda pid: (means[pid], pid))
        chosen.extend(matrix.cells_for(task, cheapest))
    return ArmSelection("always_cheapest", tuple(chosen), insufficient)


def select_oracle(
    matrix: OutcomeMatrix,
    quality: Callable[[Cell], float],
    budget_ceiling_usd: Optional[float] = None,
) -> ArmSelection:
    """Per ``(task, trial)`` — NOT per task after aggregating trials:
    the true hindsight bound. ``quality`` is the versioned projection
    (T5's quality_fn v1); ties resolve by the declared sequence. With a
    ceiling this is ``oracle_budget``: the ceiling is PER-CELL and only
    per-cell — it filters candidate cells, is asserted per selected
    cell, and implies nothing about the arm's summed cost."""
    verify_matrix(matrix)
    kind = "oracle" if budget_ceiling_usd is None else "oracle_budget"
    chosen: list[Cell] = []
    insufficient: dict[str, str] = {}
    for task in matrix.tasks():
        for trial in range(matrix.trials):
            candidates = [
                c
                for c in matrix.cells_for(task)
                if c.trial == trial and c.eligible and c.result is not None
            ]
            if budget_ceiling_usd is not None:
                candidates = [
                    c
                    for c in candidates
                    if c.cost_satisfies(matrix.cost_basis)
                    and c.cost_value <= budget_ceiling_usd
                ]
            key = f"{task}/trial-{trial}"
            if not candidates:
                insufficient[key] = (
                    "no executed eligible cell"
                    if budget_ceiling_usd is None
                    else f"no basis-satisfying cell within the per-cell ceiling "
                    f"{budget_ceiling_usd}"
                )
                continue
            # Highest quality wins; ties resolve by the declared
            # ascending sequence, so sort on (-quality, tie_break).
            best = sorted(candidates, key=lambda c: (-quality(c),) + tie_break_key(c))[0]
            chosen.append(best)
    return ArmSelection(kind, tuple(chosen), insufficient)
