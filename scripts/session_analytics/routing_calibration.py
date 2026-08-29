"""Calibration gates + shadow kNN recommender (routing-calibration,
E3 of #109, issue #266).

T1 scope: the identities everything else binds to. Every report this
increment produces carries TWO identities (plan decision 3):

- ``corpus_id`` — sha256 over the canonical JSON of the sorted ids of
  the consumed (valid) evidence sets. Invalid sets are never part of
  the corpus.
- ``policy_id`` — sha256 over the canonical JSON of the FULL
  evaluation policy: feature-vocabulary version, classifier
  parameters, normalization scheme, tier floor, the canonical digest
  of the operator's current policy source, and the declared
  false-downgrade threshold.

A report whose corpus_id or policy_id does not match the live corpus
and configuration is STALE: it renders with an explicit stale state
and satisfies no calibration gate. An evaluation produced under an old
metric, floor, or policy can therefore never pass G3–G5.

Shadow-only by construction (plan decision 9): nothing the router
executes references this module; it writes only under the
analytics-owned calibration root; every value here is derived from
operator configuration and validated evidence, never the other way
around.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from benchmark_runner.routing_eval.evidence_set import (
    EvidenceSetError,
    derive_profile_policy,
)
from benchmark_runner.routing_eval.routing_quality import (
    ControlSetIncomplete,
)
from benchmark_runner.routing_eval.record_check import load_schema, validate
from benchmark_runner.routing_eval.scenario_config import TASK_CLASSES
from session_analytics import constants as C
from session_analytics.routing_evidence import (
    InvalidEvidenceSet,
    LoadedEvidenceSet,
    derive_recommendations,
)

#: The closed feature vocabulary version (plan decision 4). Bumping it
#: is a policy change: every existing report goes stale.
FEATURE_VOCABULARY_VERSION = "fv1"

#: The five gates, in report order (plan decision 2).
GATE_IDS = (
    "telemetry_complete",
    "labeled_volume",
    "heldout_evaluated",
    "false_downgrade",
    "floors_authoritative",
)

#: The normalization scheme name (plan decision 5): min-max fitted on
#: the training fold, query values clamped into [0, 1].
NORMALIZATION_SCHEME = "minmax_fold_v1"


class CalibrationError(RuntimeError):
    """The calibration machinery itself is broken or misconfigured
    (never a data condition — thin data is insufficient_data)."""


def _canonical_digest(doc: Any) -> str:
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def corpus_id(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
) -> str:
    """The corpus identity: valid set ids only, sorted, canonical.
    Adding, removing, or invalidating a set changes it."""
    ids = sorted(
        e.set_id for e in entries if isinstance(e, LoadedEvidenceSet)
    )
    return _canonical_digest(ids)


@dataclass(frozen=True)
class EvaluationPolicy:
    """The FULL evaluation policy (plan decision 3). Every field
    participates in ``policy_id``; none has a default here — values
    come from the layered configuration, never from code."""

    feature_vocabulary: str
    k: int
    k_min: int
    distance_metric: str
    vote_epsilon: float
    normalization: str
    tier_floor: str
    policy_source_digest: Optional[str]
    max_false_downgrade_rate: float

    def as_document(self) -> Mapping[str, Any]:
        return {
            "feature_vocabulary": self.feature_vocabulary,
            "k": self.k,
            "k_min": self.k_min,
            "distance_metric": self.distance_metric,
            "vote_epsilon": self.vote_epsilon,
            "normalization": self.normalization,
            "tier_floor": self.tier_floor,
            "policy_source_digest": self.policy_source_digest,
            "max_false_downgrade_rate": self.max_false_downgrade_rate,
        }


def policy_source_digest(path: "str | Path | None") -> Optional[str]:
    """Canonical digest of the operator's CURRENT policy source bytes.
    None when no source is configured or the file is absent — an
    absent policy is representable (downstream gates report
    insufficient_data), never fabricated."""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def policy_from_config(config: Any) -> EvaluationPolicy:
    """Assemble the evaluation policy from the layered configuration
    block. A missing key is a configuration error (CalibrationError) —
    the defaults file ships every key, so absence means a broken
    override, and a policy silently completed from code would violate
    plan decision 8."""
    block = getattr(config, C.CFG_ROUTING_CALIBRATION, None) or {}
    # The min_* gate thresholds are deliberately NOT here (decision 3):
    # gates apply them LIVE at evaluation time, so changing one changes
    # the gate result immediately without staling evaluation reports.
    required = ("k", "k_min", "distance_metric", "vote_epsilon",
                "tier_floor", "policy_source", "max_false_downgrade_rate")
    missing = [key for key in required if key not in block]
    if missing:
        raise CalibrationError(
            f"routing_calibration configuration is missing {missing} — "
            f"thresholds and classifier parameters are operator policy "
            f"and are never completed from code"
        )
    return EvaluationPolicy(
        feature_vocabulary=FEATURE_VOCABULARY_VERSION,
        k=int(block["k"]),
        k_min=int(block["k_min"]),
        distance_metric=str(block["distance_metric"]),
        vote_epsilon=float(block["vote_epsilon"]),
        normalization=NORMALIZATION_SCHEME,
        tier_floor=str(block["tier_floor"]),
        policy_source_digest=policy_source_digest(block["policy_source"]),
        max_false_downgrade_rate=float(block["max_false_downgrade_rate"]),
    )


def policy_id(policy: EvaluationPolicy) -> str:
    return _canonical_digest(policy.as_document())


#: The closed route-class vocabulary (the routing-run schema's enum).
ROUTE_CLASSES = (
    "primary_only", "tier1_only", "tier2_fallback", "tier2_preferred",
)

#: The ordered encoded-feature names of feature vocabulary fv1
#: (plan decisions 4-5): one-hot task class, one-hot route class, then
#: the two numeric features. This tuple IS the closed vocabulary — a
#: post-execution figure can only enter by changing it, which is a
#: policy change (new feature_vocabulary) that stales every report.
FEATURE_NAMES = tuple(
    [f"task_class={c}" for c in TASK_CLASSES]
    + [f"route_class={r}" for r in ROUTE_CLASSES]
    + ["file_scope", "trial_count"]
)

#: Tier order for the floor comparison (decision 7/8): tier1 is the
#: HIGHER capability tier.
_TIER_RANK = {"tier1": 1, "tier2": 0}


@dataclass(frozen=True)
class Example:
    """One (evidence set, task): its PRE-ROUTING features and its
    E2-derived label. ``features`` is None (with ``missing`` naming the
    reason) when the set carries no descriptors or the task lacks one;
    ``label`` is None when the E2 outcome is insufficient_data. Only
    examples with BOTH are pool candidates."""

    evidence_set_id: str
    task_id: str
    features: "Mapping[str, Any] | None"
    missing: "str | None"
    label: "Mapping[str, Any] | None"


def extract_examples(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
) -> list[Example]:
    """Deterministic feature/label extraction (decision 4). Features
    come ONLY from the persisted pre-routing descriptors and the trial
    count; labels come ONLY from E2's own derivation — the label's
    ingredients (post-execution figures) never enter a feature."""
    examples: list[Example] = []
    for entry in sorted(
        (e for e in entries if isinstance(e, LoadedEvidenceSet)),
        key=lambda e: e.set_id,
    ):
        descriptors = (entry.task_descriptors or {}).get("descriptors")
        for rec in derive_recommendations(entry):
            task = rec["task_id"]
            label = None
            if rec["outcome"] != "insufficient_data":
                label = {"outcome": rec["outcome"],
                         "suggested": rec["suggested"]}
            descriptor = (descriptors or {}).get(task)
            if descriptor is None:
                reason = ("set carries no task descriptors"
                          if not descriptors
                          else f"no descriptor for task {task!r}")
                examples.append(Example(entry.set_id, task, None,
                                        reason, label))
                continue
            features = {
                "task_class": descriptor["task_class"],
                "route_class": descriptor["route_class"],
                "file_scope": descriptor["file_scope"],
                "trial_count": rec["confidence"]["basis"]["trials"],
            }
            examples.append(Example(entry.set_id, task, features, None,
                                    label))
    return examples


def load_current_policy(config: Any) -> "Mapping[str, Any] | None":
    """The operator's CURRENT per-profile declarations, read from the
    configured policy source through the E1 production parser. None
    when no source is configured, the file is absent, or it does not
    parse — an absent policy is representable (recommendations report
    insufficient_data), never fabricated."""
    block = getattr(config, C.CFG_ROUTING_CALIBRATION, None) or {}
    source = block.get("policy_source")
    if not source or not Path(source).is_file():
        return None
    try:
        return derive_profile_policy(Path(source), "current")
    except (EvidenceSetError, ControlSetIncomplete, OSError):
        # an unparseable source is an ABSENT policy (recommendations
        # report insufficient_data), never a fabricated one
        return None


def _fit_bounds(
    pool: Sequence[Example],
) -> Mapping[str, "tuple[float, float]"]:
    """Min-max bounds fitted on the POOL only (the training fold —
    decision 5/6). A degenerate feature (min == max) normalizes to 0.0
    deterministically."""
    bounds = {}
    for name in ("file_scope", "trial_count"):
        values = [float(e.features[name]) for e in pool]
        bounds[name] = (min(values), max(values))
    return bounds


def _encode(
    features: Mapping[str, Any],
    bounds: Mapping[str, "tuple[float, float]"],
) -> "list[float]":
    """The fv1 encoding: one-hot over the closed vocabularies, min-max
    normalized numerics clamped into [0, 1]."""
    vector = [1.0 if features["task_class"] == c else 0.0
              for c in TASK_CLASSES]
    vector += [1.0 if features["route_class"] == r else 0.0
               for r in ROUTE_CLASSES]
    for name in ("file_scope", "trial_count"):
        lo, hi = bounds[name]
        value = float(features[name])
        if hi == lo:
            vector.append(0.0)
        else:
            vector.append(min(1.0, max(0.0, (value - lo) / (hi - lo))))
    return vector


def _l2(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _eligible_under_policy(
    suggested: "Mapping[str, Any] | None",
    current_policy: Mapping[str, Any],
    tier_floor: str,
) -> bool:
    """The current-policy filter (decisions 5/8): a suggestion naming a
    profile absent from the CURRENT declarations, below the tier
    floor, or without the build role is ineligible. A no_change label
    names no profile and passes."""
    if suggested is None:
        return True
    profile = current_policy["profiles"].get(suggested["profile_id"])
    if profile is None:
        return False
    if _TIER_RANK[profile["capability_tier"]] < _TIER_RANK[tier_floor]:
        return False
    return "build" in (profile.get("roles") or ())


def knn_recommendation(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
    set_id: str,
    task_id: str,
    policy: EvaluationPolicy,
    current_policy: "Mapping[str, Any] | None",
    *,
    _examples: "Sequence[Example] | None" = None,
) -> Mapping[str, Any]:
    """One shadow kNN recommendation (decision 5), schema-validated
    before return. Deterministic: identical corpus + policy yield
    byte-identical output. The neighbor pool excludes EVERY example of
    the queried task (serving parity with the leave-one-task-out
    evaluation — similarity speaks from OTHER tasks' evidence, never
    from the query's own answer)."""
    doc: dict[str, Any] = {
        "schema_version": 1,
        "evidence_set_id": set_id,
        "task_id": task_id,
        "policy_id": policy_id(policy),
        "outcome": "insufficient_data",
        "suggested": None,
        "neighbors": [],
        "k": policy.k,
        "k_min": policy.k_min,
        "distance_metric": policy.distance_metric,
        "insufficient_reason": None,
    }

    def _refuse(reason: str) -> Mapping[str, Any]:
        doc["insufficient_reason"] = reason
        return _validated(doc)

    examples = list(_examples) if _examples is not None         else extract_examples(entries)
    query = next(
        (e for e in examples
         if e.evidence_set_id == set_id and e.task_id == task_id),
        None,
    )
    if query is None:
        return _refuse(f"no example for task {task_id!r} in the set")
    if query.features is None:
        return _refuse(query.missing or "features unavailable")
    if current_policy is None:
        return _refuse("no current policy source is configured")

    # candidate filtering BEFORE ranking (decision 5)
    pool = [
        e for e in examples
        if e.task_id != task_id
        and e.features is not None
        and e.label is not None
        and _eligible_under_policy(e.label["suggested"], current_policy,
                                   policy.tier_floor)
    ]
    if len(pool) < policy.k_min:
        return _refuse(
            f"{len(pool)} eligible labeled neighbors, fewer than "
            f"k_min={policy.k_min}"
        )

    bounds = _fit_bounds(pool)
    encoded_query = _encode(query.features, bounds)
    ranked = sorted(
        pool,
        key=lambda e: (_l2(_encode(e.features, bounds), encoded_query),
                       e.evidence_set_id, e.task_id),
    )
    neighborhood = ranked[: min(policy.k, len(ranked))]

    weights: dict[str, float] = {}
    voters: list[tuple[float, float, Example]] = []
    for e in neighborhood:
        d = _l2(_encode(e.features, bounds), encoded_query)
        w = 1.0 / (d + policy.vote_epsilon)
        weights[e.label["outcome"]] = weights.get(e.label["outcome"], 0.0) + w
        voters.append((w, d, e))
        doc["neighbors"].append({
            "evidence_set_id": e.evidence_set_id,
            "task_id": e.task_id,
            "distance": d,
            "label": {"outcome": e.label["outcome"],
                      "suggested": e.label["suggested"]},
            "evidence_refs": [
                f"report/arms/cct_router/tasks/{e.task_id}",
            ],
        })

    switch_weight = weights.get("switch_profile", 0.0)
    keep_weight = weights.get("no_change_recommended", 0.0)
    if switch_weight > keep_weight:
        # highest-weight switch voter's suggestion; ties by distance,
        # then set id, then task id (the sort already fixed the order)
        winner = min(
            (v for v in voters
             if v[2].label["outcome"] == "switch_profile"),
            key=lambda v: (-v[0], v[1], v[2].evidence_set_id,
                           v[2].task_id),
        )
        suggested = winner[2].label["suggested"]
        if not _eligible_under_policy(suggested, current_policy,
                                      policy.tier_floor):
            return _refuse(
                "the winning suggestion is not eligible under the "
                "current policy"
            )
        doc["outcome"] = "switch_profile"
        doc["suggested"] = dict(suggested)
    else:
        # a TIE resolves conservatively: never a switch on a tie
        doc["outcome"] = "no_change_recommended"
    return _validated(doc)


def _validated(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    errors = validate(doc, load_schema("knn-recommendation"))
    if errors:
        raise CalibrationError(
            f"derived kNN recommendation violates its own schema: "
            f"{errors[:3]}"
        )
    return doc


def report_staleness(
    report: Mapping[str, Any],
    current_corpus_id: str,
    current_policy_id: str,
) -> Mapping[str, Any]:
    """Compare a persisted report's bindings to the live corpus and
    configuration. Either mismatch makes it stale, with the reasons
    named; a stale report satisfies no gate (plan decision 3)."""
    reasons = []
    if report.get("corpus_id") != current_corpus_id:
        reasons.append("corpus_changed")
    if report.get("policy_id") != current_policy_id:
        reasons.append("policy_changed")
    return {"stale": bool(reasons), "reasons": reasons}
