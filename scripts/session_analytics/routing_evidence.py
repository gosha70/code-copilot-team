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


# ── API payload builders (pure; the FastAPI routes are thin
# wrappers). NOTHING here may serialize a filesystem path: sets are
# addressed by opaque id, invalid sets by directory basename, and
# evidence files by their manifest-relative reference. ──
class EvidenceFileUnavailable(Exception):
    """A referenced evidence file cannot be served. ``code`` is a
    closed sanitized reason; no path ever appears in it."""

    def __init__(self, code: str):
        assert code in ("unknown_reference", "hash_mismatch",
                        "unreadable_artifact")
        self.code = code
        super().__init__(code)


def evidence_index(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
) -> Mapping[str, Any]:
    """The listing payload: valid sets summarized by identity and
    shape, invalid sets carried with their closed sanitized state —
    rendered, never skipped."""
    sets: list[Mapping[str, Any]] = []
    for entry in entries:
        if isinstance(entry, InvalidEvidenceSet):
            sets.append({
                "state": "invalid_evidence",
                "label": entry.label,
                "code": entry.code,
                "artifact": entry.artifact,
                "detail": entry.detail,
            })
            continue
        fp = entry.manifest["fingerprint"]
        report = entry.report
        sets.append({
            "state": "valid",
            "set_id": entry.set_id,
            "registry_digest": fp["registry_digest"],
            "preset_digest": fp["preset_digest"],
            "task_set_revision": fp["task_set_revision"],
            "toolchain_digest": fp["toolchain_digest"],
            "tasks": sorted(
                (report["arms"].get("cct_router") or {}).get("tasks") or {}
            ),
            "arms": sorted(report["arms"]),
            "pareto_status": (report.get("pareto") or {}).get("status"),
            "record_count": len(entry.records),
        })
    return {"sets": sets}


def find_evidence_set(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
    set_id: str,
) -> Optional[LoadedEvidenceSet]:
    for entry in entries:
        if isinstance(entry, LoadedEvidenceSet) and entry.set_id == set_id:
            return entry
    return None


def evidence_detail(loaded: LoadedEvidenceSet) -> Mapping[str, Any]:
    """The E1 report VERBATIM plus the set identity — no figure is
    recomputed, rounded, or re-derived on the way out (the
    figure-provenance gate holds the API to this)."""
    return {
        "set_id": loaded.set_id,
        "report": loaded.report,
        "record_count": len(loaded.records),
    }


def recommendations_payload(loaded: LoadedEvidenceSet) -> Mapping[str, Any]:
    """Derive, then hold every record to the figure-provenance gate
    (decision 9) BEFORE anything is served: one resolver validates all
    source pointers and recomputes every declared delta against the
    canonical report parse."""
    records = derive_recommendations(loaded)
    verify_recommendation_provenance(loaded, records)
    return {
        "set_id": loaded.set_id,
        "recommendations": records,
    }


def serve_evidence_file(
    loaded: LoadedEvidenceSet, ref: str
) -> Mapping[str, Any]:
    """Serve ONE referenced evidence file, hash-verified against the
    manifest before a byte leaves the server: an unknown reference, a
    containment escape, or content that no longer matches its
    manifest hash refuses with a closed code — unverified artifact
    bytes are never served."""
    manifest_files = loaded.manifest.get("evidence_files") or {}
    expected = manifest_files.get(ref)
    if expected is None:
        raise EvidenceFileUnavailable("unknown_reference")
    target = loaded.path / ref
    try:
        resolved = target.resolve()
        resolved.relative_to(loaded.path.resolve())
        content = resolved.read_bytes()
    except (OSError, ValueError):
        raise EvidenceFileUnavailable("unreadable_artifact") from None
    import hashlib as _hashlib

    actual = "sha256:" + _hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise EvidenceFileUnavailable("hash_mismatch")
    return {"ref": ref, "content": content.decode("utf-8", "replace")}


def routing_evidence_settings(config: Any) -> Mapping[str, Any]:
    """The SANITIZED settings shape: whether evidence roots are
    configured and how many — the raw root paths never leave the
    server (routing-shadow decision on #261's no-sensitive-path
    acceptance)."""
    roots = tuple(getattr(config, "routing_evidence_roots", ()) or ())
    return {"configured": bool(roots), "root_count": len(roots)}


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


# ── figure provenance (decision 9) ─────────────────────────────────────
def _json_pointer(*tokens: str) -> str:
    """RFC 6901 pointer from raw tokens (~ and / escaped)."""
    return "".join(
        "/" + token.replace("~", "~0").replace("/", "~1") for token in tokens
    )


def _figure_source(arm: str, task: str, field: str) -> Mapping[str, Any]:
    return {
        "artifact": "report",
        "pointer": _json_pointer("arms", arm, "tasks", task, field),
    }


def _delta_source(arm: str, task: str, field: str) -> Mapping[str, Any]:
    """Router minus candidate — the declared subtraction's two operands."""
    return {
        "operation": "subtract",
        "lhs": _figure_source("cct_router", task, field),
        "rhs": _figure_source(arm, task, field),
    }


def _resolve_pointer(doc: Any, pointer: str) -> Any:
    """Resolve one RFC 6901 pointer against a parsed artifact; raises
    DerivationError on any unresolvable step."""
    if not pointer.startswith("/"):
        raise DerivationError(
            f"figure source pointer {pointer!r} is not a JSON Pointer"
        )
    node = doc
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, Mapping) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            raise DerivationError(
                f"figure source pointer {pointer!r} does not resolve in its "
                f"artifact — a served figure with an unresolvable source "
                f"fails the provenance gate"
            )
    return node


def _resolve_figure(artifacts: Mapping[str, Any], source: Mapping[str, Any],
                    where: str) -> float:
    artifact = artifacts.get(source.get("artifact"))
    if artifact is None:
        raise DerivationError(
            f"{where}: figure source names unknown artifact "
            f"{source.get('artifact')!r}"
        )
    value = _resolve_pointer(artifact, source["pointer"])
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DerivationError(
            f"{where}: figure source {source['pointer']!r} resolves to a "
            f"non-numeric value"
        )
    return value


def _check_direct(artifacts: Mapping[str, Any], figure: Any, source: Any,
                  expected: Mapping[str, Any], where: str) -> None:
    if figure is None:
        if source is not None:
            raise DerivationError(
                f"{where}: a null figure must carry a null source"
            )
        return
    if source is None:
        raise DerivationError(
            f"{where}: served figure carries no source pointer — decision 9 "
            f"refuses unsourced figures"
        )
    if source != expected:
        # identity binding: "exact source" means THIS record's task,
        # arm, and field — a resolvable-but-wrong pointer is refused
        # even when the two artifact values happen to collide
        raise DerivationError(
            f"{where}: source descriptor does not name this figure's exact "
            f"artifact field — the provenance gate refuses the payload"
        )
    resolved = _resolve_figure(artifacts, source, where)
    if float(resolved) != float(figure):
        raise DerivationError(
            f"{where}: served figure differs from its pointed-at artifact "
            f"value — the provenance gate refuses the payload"
        )


def _check_delta(artifacts: Mapping[str, Any], delta: Any, source: Any,
                 expected: Mapping[str, Any], where: str) -> None:
    if delta is None:
        if source is not None:
            raise DerivationError(
                f"{where}: a null delta must carry a null source"
            )
        return
    if source is None:
        raise DerivationError(
            f"{where}: served delta carries no operand pointers — decision 9 "
            f"refuses unsourced figures"
        )
    if source != expected:
        raise DerivationError(
            f"{where}: delta descriptor does not name this delta's exact "
            f"operand fields — the provenance gate refuses the payload"
        )
    lhs = _resolve_figure(artifacts, source["lhs"], where + "/lhs")
    rhs = _resolve_figure(artifacts, source["rhs"], where + "/rhs")
    if float(lhs) - float(rhs) != float(delta):
        raise DerivationError(
            f"{where}: served delta differs from the recomputed subtraction "
            f"of its two operands — the provenance gate refuses the payload"
        )


def verify_recommendation_provenance(
    loaded: LoadedEvidenceSet,
    records: Sequence[Mapping[str, Any]],
) -> None:
    """THE serving resolver (decision 9): every numeric figure a
    recommendation payload serves either points at its exact artifact
    field (resolved against ONE canonical parse, float64 equality) or
    declares the subtraction of two pointed-at fields (recomputed,
    exact equality). No source, an unresolvable pointer, or a value
    differing from its source refuses the whole payload — nothing
    partially provenanced ever leaves the server."""
    artifacts = {"report": loaded.report}
    for rec in records:
        task = rec["task_id"]
        ceiling = rec["oracle_ceiling"]
        for field in ("quality", "cost"):
            _check_direct(
                artifacts, ceiling[field], ceiling["sources"][field],
                _figure_source("oracle", task, field),
                f"{task}/oracle_ceiling/{field}",
            )
        for arm, delta in rec["divergence"].items():
            for field, base in (("quality_delta", "quality"),
                                ("cost_delta", "cost")):
                _check_delta(
                    artifacts, delta[field], delta["sources"][field],
                    _delta_source(arm, task, base),
                    f"{task}/divergence/{arm}/{field}",
                )
        _check_confidence(loaded, rec)


def _check_confidence(loaded: LoadedEvidenceSet,
                      rec: Mapping[str, Any]) -> None:
    """Confidence statistics carry no source pointers (they are
    statistics OF the derivation, not copies of artifact figures), so
    their gate is recomputation — and the recomputation trusts NOTHING
    the payload asserts about itself: the ENTIRE confidence block
    (grade AND every basis field, including ``components_included``
    from the canonical report and ``insufficiency_refs``
    independently reconstructed from the report, the outcome path,
    and the availability evidence) is re-derived and compared whole.
    Any disagreement refuses the payload — a tampered or drifted
    confidence claim never leaves the server."""
    expected = _derive_task(loaded, rec["task_id"])
    if rec["confidence"] != expected["confidence"]:
        raise DerivationError(
            f"{rec['task_id']}/confidence: served confidence block "
            f"disagrees with its independent re-derivation from the "
            f"canonical report and records — the provenance gate refuses "
            f"the payload"
        )


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
    oracle_ceiling = {
        "quality": o_q,
        "cost": o_c,
        "sources": {
            "quality": _figure_source("oracle", task, "quality")
            if o_q is not None else None,
            "cost": _figure_source("oracle", task, "cost")
            if o_c is not None else None,
        },
    }

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
            "sources": {
                "quality_delta": _delta_source(arm, task, "quality")
                if r_q is not None and a_q is not None else None,
                "cost_delta": _delta_source(arm, task, "cost")
                if r_c is not None and a_c is not None else None,
            },
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
