"""Shadow-mode routing evidence consumption (routing-shadow T2).

The session-analytics side of E2: discovers E1 evidence sets under
operator-configured roots, validates them with E1's OWN loader checks
(`routing_eval.evidence_set.validate_evidence_set` — schemas, manifest
hash bindings over the same bytes parsed, pairwise fingerprint
agreement, containment), and derives shadow-mode recommendations as a
DETERMINISTIC PROJECTION of the report's served figures.

Nothing here recomputes a metric: suggested profiles are the report's
own selection provenance, divergence is the declared float64
subtraction of served figures, and confidence is graded from the
report's per-trial tables. The dependency direction is one-way —
this module imports `benchmark_runner.routing_eval` read-only; nothing
the router executes can read anything produced here.

The three load-bearing rules (plan decision 5):

- **positive two-axis dominance, never identity difference** — a
  switch is recommended only when an EXECUTABLE candidate arm's
  per-task quality strictly beats the router's at no greater cost
  under the declared basis (or ties quality at strictly lower cost),
  under the declared 1e-9 tolerance; a router that outperforms every
  control is `no_change_recommended`;
- **the availability guard** — fixed-profile sweeps are
  availability-neutral, the router ran under the scenario's injected
  outages: a dominating candidate whose profile never appears
  admissible (verdict `selected` or `eligible`) in the router's own
  durable candidate evidence for the task yields
  `insufficient_data` with the availability evidence referenced,
  never an inactionable switch;
- **insufficiency never collapses** — any consumed figure that is
  absent or insufficient in a VALID set yields `insufficient_data`
  with the specific references; invalid sets produce NO records at
  all (they are a set-level `invalid_evidence` state).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from benchmark_runner.routing_eval.evidence_set import (
    EvidenceSetInvalid,
    discover_evidence_sets,
    validate_evidence_set,
)
from benchmark_runner.routing_eval.quality_fn import COMPONENTS
from benchmark_runner.routing_eval.record_check import load_schema, validate

#: E2's declared comparison tolerance (plan decision 5) — E2-owned,
#: not borrowed from E1's internal comparisons.
TOLERANCE = 1e-9

#: The executable candidate arms. The oracle is a hindsight bound,
#: named as the ceiling, never suggested.
EXECUTABLE_CANDIDATES = ("always_best", "always_cheapest")


#: Confidence grade rule v2 (plan decision 5): declared, deterministic.
_GRADE_HIGH_TRIALS = 5
_GRADE_HIGH_AGREEMENT = 0.8
_GRADE_MODERATE_TRIALS = 2
_GRADE_MODERATE_AGREEMENT = 0.6


class DerivationError(RuntimeError):
    """The derivation itself is broken (never a data condition)."""


@dataclass(frozen=True)
class LoadedEvidenceSet:
    """One VALID evidence set. ``path`` is server-side only — the API
    layer must never serialize it; ``set_id`` is the public identity."""

    set_id: str
    path: Path
    manifest: Mapping[str, Any]
    report: Mapping[str, Any]
    matrix: Mapping[str, Any]
    records: Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class InvalidEvidenceSet:
    """A SET-level invalid_evidence state: rendered, never skipped,
    and never a source of recommendation records. ``label`` is the
    directory's basename (a single path segment), never a path."""

    label: str
    code: str
    artifact: str
    detail: str
    state: str = field(default="invalid_evidence")


def load_evidence_sets(
    roots: Sequence["Path | str"],
) -> list["LoadedEvidenceSet | InvalidEvidenceSet"]:
    """Discover and validate every evidence set under the configured
    roots. Valid sets load; invalid sets surface with their sanitized
    closed failure code. Hidden (staging) entries never appear."""
    out: list[LoadedEvidenceSet | InvalidEvidenceSet] = []
    for root in roots:
        for entry in discover_evidence_sets(Path(root)):
            try:
                validated = validate_evidence_set(entry)
            except EvidenceSetInvalid as exc:
                out.append(InvalidEvidenceSet(
                    label=entry.name,
                    code=exc.code,
                    artifact=exc.artifact,
                    detail=exc.detail,
                ))
                continue
            out.append(LoadedEvidenceSet(
                set_id=validated["set_id"],
                path=entry,
                manifest=validated["manifest"],
                report=validated["report"],
                matrix=validated["matrix"],
                records=validated["records"],
            ))
    return out


# ── derivation ─────────────────────────────────────────────────────────
def derive_recommendations(
    loaded: LoadedEvidenceSet,
) -> list[Mapping[str, Any]]:
    """Every task's recommendation record for one VALID set, in
    deterministic task order, each validated against
    recommendation.schema.json before it is returned. Identical
    artifact bytes yield byte-identical records."""
    report = loaded.report
    router_tasks = report["arms"]["cct_router"]["tasks"]
    schema = load_schema("recommendation")
    records = []
    for task in sorted(router_tasks):
        record = _derive_task(loaded, task)
        errors = validate(record, schema)
        if errors:
            raise DerivationError(
                f"derived recommendation for task {task!r} violates its own "
                f"schema: {errors[:3]}"
            )
        records.append(record)
    return records


def _figures(report: Mapping[str, Any], arm: str, task: str):
    table = (report["arms"].get(arm) or {}).get("tasks") or {}
    entry = table.get(task)
    if entry is None:
        return None, None, None
    return entry.get("quality"), entry.get("cost"), entry.get("per_trial")


def _dominates(q_c, c_c, q_r, c_r) -> bool:
    """The tolerance-aware two-axis dominance predicate."""
    if None in (q_c, c_c, q_r, c_r):
        return False
    quality_wins = q_c > q_r + TOLERANCE
    quality_ties = abs(q_c - q_r) <= TOLERANCE
    cost_not_worse = c_c <= c_r + TOLERANCE
    cost_wins = c_c < c_r - TOLERANCE
    return (quality_wins and cost_not_worse) or (quality_ties and cost_wins)


def _admissibility(
    records: Sequence[Mapping[str, Any]], task: str, profile: str, set_id: str
) -> tuple[bool, list[Mapping[str, Any]]]:
    """The availability guard's evidence: was ``profile`` ever
    admissible (verdict selected or eligible) in the router's durable
    candidate evidence for ``task``? Returns the admissibility and the
    addressable references that prove it (or its absence)."""
    refs: list[Mapping[str, Any]] = []
    admissible = False
    for i, record in enumerate(records):
        if record.get("task_id") != task:
            continue
        for j, decision in enumerate(record.get("routing_decisions") or []):
            for candidate in decision.get("considered") or []:
                if candidate.get("id") != profile:
                    continue
                refs.append({
                    "evidence_set_id": set_id,
                    "artifact": "routing_runs",
                    "locator": {"record": i, "decision": j},
                })
                if candidate.get("verdict") in ("selected", "eligible"):
                    admissible = True
    if not refs:
        # the profile never appeared at all — reference the task's
        # records as the (absence of) availability evidence
        refs = [
            {"evidence_set_id": set_id, "artifact": "routing_runs",
             "locator": {"record": i}}
            for i, record in enumerate(records)
            if record.get("task_id") == task
        ]
    return admissible, refs


def _actual_from_records(
    records: Sequence[Mapping[str, Any]], task: str, set_id: str
) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    by_trial: dict[int, list[tuple[int, Mapping[str, Any]]]] = {}
    for i, record in enumerate(records):
        if record.get("task_id") != task:
            continue
        by_trial.setdefault(record["trial"], []).append((i, record))
    per_trial = []
    refs = []
    for trial in sorted(by_trial):
        chain = []
        delegated = False
        reconciled = False
        for i, record in by_trial[trial]:
            refs.append({"evidence_set_id": set_id,
                         "artifact": "routing_runs",
                         "locator": {"record": i}})
            for decision in record.get("routing_decisions") or []:
                selected = decision.get("selected")
                if selected:
                    chain.append(selected)
            if (record.get("tier2") or {}).get("delegated"):
                delegated = True
            reconciliation = record.get("reconciliation")
            if reconciliation and reconciliation.get("outcome") == "reconciled":
                reconciled = True
        per_trial.append({"trial": trial, "chain": chain,
                          "delegated": delegated, "reconciled": reconciled})
    return {"per_trial": per_trial}, refs


def _agreement(
    report: Mapping[str, Any],
    task: str,
    arms: Sequence[str],
    mode: str,
) -> tuple[Optional[float], list[int]]:
    """Trial agreement under the SAME two-axis dominance predicate the
    recommendation uses. ``mode`` is 'switch' (the suggested arm — the
    single element of ``arms`` — dominates per trial) or 'no_change'
    (NO candidate dominates per trial). Returns (agreement fraction or
    None, the trials that could not evaluate the predicate)."""
    _q, _c, router_rows = _figures(report, "cct_router", task)
    if not router_rows:
        return None, []
    by_arm = {}
    for arm in arms:
        _aq, _ac, rows = _figures(report, arm, task)
        by_arm[arm] = {row["trial"]: row for row in rows or []}
    router_by_trial = {row["trial"]: row for row in router_rows}
    agree = 0
    evaluated = 0
    unevaluated: list[int] = []
    for trial in sorted(router_by_trial):
        r = router_by_trial[trial]
        arm_rows = [by_arm[a].get(trial) for a in arms]
        values = [r.get("quality"), r.get("cost")] + [
            v for row in arm_rows
            for v in ((row.get("quality"), row.get("cost"))
                      if row else (None, None))
        ]
        if any(v is None for v in values):
            unevaluated.append(trial)
            continue
        evaluated += 1
        dominance = [
            _dominates(row["quality"], row["cost"], r["quality"], r["cost"])
            for row in arm_rows
        ]
        if mode == "switch":
            if dominance[0]:
                agree += 1
        else:
            if not any(dominance):
                agree += 1
    if evaluated == 0:
        return None, unevaluated
    return agree / evaluated, unevaluated


def _grade(
    trials: int,
    agreement: Optional[float],
    components_included: Sequence[str],
    unevaluated: Sequence[int],
    insufficiency_refs: Sequence[str],
) -> str:
    """Grade rule v2: declared, deterministic. Any insufficiency, any
    unevaluated trial, or missing agreement caps the grade at low."""
    if insufficiency_refs or unevaluated or agreement is None:
        return "low"
    # the FULL v1 mask is an exact-set identity, not a count: a
    # schema-valid list of the right length with a duplicate and an
    # omission must never qualify
    full_mask = (
        set(components_included) == {c.name for c in COMPONENTS}
        and len(components_included) == len(COMPONENTS)
    )
    if trials >= _GRADE_HIGH_TRIALS and full_mask and (
        agreement >= _GRADE_HIGH_AGREEMENT
    ):
        return "high"
    if trials >= _GRADE_MODERATE_TRIALS and full_mask and (
        agreement >= _GRADE_MODERATE_AGREEMENT
    ):
        return "moderate"
    return "low"


def _derive_task(loaded: LoadedEvidenceSet, task: str) -> Mapping[str, Any]:
    report = loaded.report
    set_id = loaded.set_id
    cost_basis = report["cost_basis"]
    components = list(report["components_included"])

    actual, actual_refs = _actual_from_records(loaded.records, task, set_id)
    trials = max(len(actual["per_trial"]), 1)

    r_q, r_c, _router_rows = _figures(report, "cct_router", task)
    o_q, o_c, _ = _figures(report, "oracle", task)
    oracle_ceiling = {"quality": o_q, "cost": o_c}

    evidence_refs: list[Mapping[str, Any]] = list(actual_refs)
    for arm in ("cct_router", "oracle") + EXECUTABLE_CANDIDATES:
        if task in ((report["arms"].get(arm) or {}).get("tasks") or {}):
            evidence_refs.append({
                "evidence_set_id": set_id, "artifact": "report",
                "locator": {"arm": arm, "task": task},
            })

    # consumed-figure sufficiency: the DECLARED insufficiency states
    # govern first — an arm carrying an insufficiency entry (e.g. the
    # router's sequence_dependent rows) or a withheld Pareto frontier
    # makes the comparison plane incomplete even when per-task numbers
    # exist — then the router's and EVERY executable candidate's
    # per-task figures must be present.
    insufficiency_refs: list[str] = []
    for arm in ("cct_router",) + EXECUTABLE_CANDIDATES:
        declared = (report["arms"].get(arm) or {}).get("insufficient") or {}
        for key in sorted(declared):
            insufficiency_refs.append(
                f"{arm}/insufficient/{key}: {declared[key]}"
            )
    pareto_status = (report.get("pareto") or {}).get("status")
    if pareto_status == "insufficient_evidence":
        reason = (report.get("pareto") or {}).get("reason") or "frontier withheld"
        insufficiency_refs.append(f"pareto: {reason}")
    divergence: dict[str, Any] = {}
    for arm in EXECUTABLE_CANDIDATES:
        a_q, a_c, _rows = _figures(report, arm, task)
        if a_q is None or a_c is None:
            insufficiency_refs.append(f"{arm}/{task}: per-task figures "
                                      f"insufficient or absent")
        divergence[arm] = {
            "quality_delta": (r_q - a_q)
            if r_q is not None and a_q is not None else None,
            "cost_delta": (r_c - a_c)
            if r_c is not None and a_c is not None else None,
            "cost_basis": cost_basis,
        }
    if r_q is None or r_c is None:
        insufficiency_refs.insert(
            0, f"cct_router/{task}: per-task figures insufficient or absent"
        )

    def _record(outcome, suggested, agreement, unevaluated,
                extra_insufficiency=()):
        refs = insufficiency_refs + list(extra_insufficiency)
        return {
            "schema_version": 1,
            "evidence_set_id": set_id,
            "task_id": task,
            "actual": actual,
            "suggested": suggested,
            "oracle_ceiling": oracle_ceiling,
            "divergence": divergence,
            "outcome": outcome,
            "confidence": {
                "grade": _grade(trials, agreement, components,
                                unevaluated, refs),
                "basis": {
                    "trials": trials,
                    "agreement": agreement,
                    "components_included": components,
                    "insufficiency_refs": refs,
                    **({"unevaluated_trials": list(unevaluated)}
                       if unevaluated else {}),
                },
            },
            "evidence_refs": evidence_refs,
        }

    if insufficiency_refs:
        return _record("insufficient_data", None, None, [])

    dominating = [
        arm for arm in EXECUTABLE_CANDIDATES
        if _dominates(*_figures(report, arm, task)[:2], r_q, r_c)
    ]
    if not dominating:
        agreement, unevaluated = _agreement(
            report, task, list(EXECUTABLE_CANDIDATES), "no_change"
        )
        return _record("no_change_recommended", None, agreement, unevaluated)

    # suggested = the dominating arm with the higher quality — under
    # the SAME declared tolerance the dominance predicate uses; ties
    # by lower cost (tolerance-aware), then arm name. Harmless
    # rounding can never change WHICH profile is recommended.
    def _beats(a: str, b: str) -> bool:
        a_q, a_c, _ = _figures(report, a, task)
        b_q, b_c, _ = _figures(report, b, task)
        if a_q > b_q + TOLERANCE:
            return True
        if b_q > a_q + TOLERANCE:
            return False
        if a_c < b_c - TOLERANCE:
            return True
        if b_c < a_c - TOLERANCE:
            return False
        return a < b

    suggested_arm = dominating[0]
    for arm in dominating[1:]:
        if _beats(arm, suggested_arm):
            suggested_arm = arm
    profile = (report["arms"][suggested_arm].get("selections") or {}).get(task)
    if not profile:
        return _record(
            "insufficient_data", None, None, [],
            extra_insufficiency=[
                f"{suggested_arm}/{task}: no selection provenance"
            ],
        )

    admissible, availability_refs = _admissibility(
        loaded.records, task, profile, set_id
    )
    evidence_refs.extend(
        ref for ref in availability_refs if ref not in evidence_refs
    )
    if not admissible:
        # THE AVAILABILITY GUARD: the candidate dominates numerically,
        # but the router's own durable evidence never shows the
        # profile admissible for this task — recommending it would be
        # an inactionable switch, so the outcome is insufficient_data
        # with the availability evidence referenced.
        return _record(
            "insufficient_data", None, None, [],
            extra_insufficiency=[
                f"availability/{task}: profile '{profile}' never appears "
                f"admissible in the router's candidate evidence"
            ],
        )

    agreement, unevaluated = _agreement(report, task, [suggested_arm],
                                        "switch")
    return _record(
        "switch_profile",
        {"arm": suggested_arm, "profile_id": profile},
        agreement,
        unevaluated,
    )
