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
    tier_floor = str(block["tier_floor"])
    if tier_floor not in _TIER_RANK:
        raise CalibrationError(
            f"routing_calibration tier_floor {tier_floor!r} is outside the "
            f"closed vocabulary {sorted(_TIER_RANK)} — a mistyped floor "
            f"would silently change which profiles are eligible"
        )
    return EvaluationPolicy(
        feature_vocabulary=FEATURE_VOCABULARY_VERSION,
        k=int(block["k"]),
        k_min=int(block["k_min"]),
        distance_metric=str(block["distance_metric"]),
        vote_epsilon=float(block["vote_epsilon"]),
        normalization=NORMALIZATION_SCHEME,
        tier_floor=tier_floor,
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
    #: The E2 record's OWN evidence references (the closed E2 shape) —
    #: carried verbatim so the kNN surface and the E2 surface resolve
    #: neighbor provenance through ONE resolver.
    evidence_refs: "Sequence[Mapping[str, Any]]" = ()


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
        artifact = entry.task_descriptors or {}
        descriptors = artifact.get("descriptors")
        # THE pre-routing trial count: the scenario's DECLARED trials,
        # persisted in the descriptors artifact. The observed per-trial
        # record count is an execution observation and never a feature.
        declared_trials = artifact.get("trials")
        for rec in derive_recommendations(entry):
            task = rec["task_id"]
            label = None
            if rec["outcome"] != "insufficient_data":
                label = {"outcome": rec["outcome"],
                         "suggested": rec["suggested"]}
            refs = tuple(rec.get("evidence_refs") or ())
            descriptor = (descriptors or {}).get(task)
            if descriptor is None or declared_trials is None:
                if not descriptors:
                    reason = "set carries no task descriptors"
                elif descriptor is None:
                    reason = f"no descriptor for task {task!r}"
                else:
                    reason = "descriptors artifact declares no trial count"
                examples.append(Example(entry.set_id, task, None,
                                        reason, label, refs))
                continue
            features = {
                "task_class": descriptor["task_class"],
                "route_class": descriptor["route_class"],
                "file_scope": descriptor["file_scope"],
                "trial_count": declared_trials,
            }
            examples.append(Example(entry.set_id, task, features, None,
                                    label, refs))
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
            "evidence_refs": [dict(r) for r in e.evidence_refs],
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


# ── held-out evaluation (decisions 6-7) ────────────────────────────────
def _tier_of(
    profile_id: "str | None", profile_policy: "Mapping[str, Any] | None"
) -> "str | None":
    """The capability tier of a profile, resolved ONLY from the set's
    persisted policy declarations (decision 11). None when the set
    carries no policy or the profile is not declared — unresolvable is
    representable, never guessed."""
    if profile_id is None or not profile_policy:
        return None
    entry = (profile_policy.get("profiles") or {}).get(profile_id)
    return entry["capability_tier"] if entry else None


def _actual_profiles(actual: Mapping[str, Any]) -> "list[str]":
    """Every profile the router actually selected for the task, across
    trials, in first-seen order."""
    seen: list[str] = []
    for trial in actual.get("per_trial") or ():
        for profile in trial.get("chain") or ():
            if profile not in seen:
                seen.append(profile)
    return seen


def baseline_tier(
    truth: Mapping[str, Any],
    actual: Mapping[str, Any],
    profile_policy: "Mapping[str, Any] | None",
) -> "str | None":
    """The safety baseline a prediction is judged against (decision 7):

    - truth is switch_profile -> the tier of the TRUTH's suggested
      profile (so predicting Tier 2 while truth switches WITHIN Tier 1
      is a downgrade);
    - truth is no_change_recommended -> the tier the router actually
      operated at. A chain can name several profiles, so the baseline
      is the LOWEST tier the router actually used — recommending a
      tier the router already ran at is not a downgrade. (The plan
      says "the tier of the router's actual selection", singular; this
      is the conservative reading for multi-leg chains, recorded for
      review.)

    None when no tier resolves — the task is then unevaluable for the
    downgrade metric rather than silently counted either way.
    """
    if truth["outcome"] == "switch_profile":
        return _tier_of((truth["suggested"] or {}).get("profile_id"),
                        profile_policy)
    tiers = [
        t for t in (_tier_of(p, profile_policy)
                    for p in _actual_profiles(actual))
        if t is not None
    ]
    if not tiers:
        return None
    return min(tiers, key=lambda t: _TIER_RANK[t])


def is_false_downgrade(
    predicted: Mapping[str, Any],
    baseline: "str | None",
    profile_policy: "Mapping[str, Any] | None",
) -> bool:
    """A prediction is a false downgrade iff it recommends switching to
    a profile of a LOWER capability tier than the safety baseline."""
    if predicted["outcome"] != "switch_profile" or baseline is None:
        return False
    predicted_tier = _tier_of((predicted["suggested"] or {}).get(
        "profile_id"), profile_policy)
    if predicted_tier is None:
        return False
    return _TIER_RANK[predicted_tier] < _TIER_RANK[baseline]


def evaluate_heldout(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
    policy: EvaluationPolicy,
    current_policy: "Mapping[str, Any] | None",
) -> Mapping[str, Any]:
    """Leave-one-task-out evaluation (decision 6). For every labeled
    (set, task): EVERY example of that task is removed from the
    neighbor pool across every set, normalization is fitted on the
    remaining pool, the prediction is compared to the E2 truth, and the
    decision-7 downgrade arithmetic is accumulated.

    Normalization parity with serving: `knn_recommendation` fits bounds
    on the eligibility-FILTERED pool, and this evaluation drives the
    same function, so the folds normalize exactly as serving does —
    otherwise the measured rate would not describe serving behaviour.
    """
    examples = extract_examples(entries)
    policies = {
        e.set_id: e.profile_policy
        for e in entries if isinstance(e, LoadedEvidenceSet)
    }
    actuals: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, LoadedEvidenceSet):
            continue
        for rec in derive_recommendations(entry):
            actuals[(entry.set_id, rec["task_id"])] = rec["actual"]

    results: list[Mapping[str, Any]] = []
    false_downgrades = 0
    evaluated = 0
    unevaluable = 0
    agreements = 0
    floor_violations = 0

    for example in examples:
        if example.label is None or example.features is None:
            unevaluable += 1
            continue
        # THE fold: every example of this task leaves the pool.
        # knn_recommendation already excludes the queried task, so the
        # fold is the corpus itself — the exclusion is one rule, not
        # two implementations that can drift.
        predicted = knn_recommendation(
            entries, example.evidence_set_id, example.task_id, policy,
            current_policy, _examples=examples,
        )
        truth = example.label
        profile_policy = policies.get(example.evidence_set_id)
        base = baseline_tier(
            truth, actuals.get((example.evidence_set_id,
                                example.task_id)) or {"per_trial": []},
            profile_policy,
        )
        downgrade = is_false_downgrade(predicted, base, profile_policy)
        if downgrade:
            false_downgrades += 1
        if predicted["outcome"] == truth["outcome"]:
            agreements += 1
        if predicted["outcome"] == "switch_profile" and current_policy:
            if not _eligible_under_policy(predicted["suggested"],
                                          current_policy,
                                          policy.tier_floor):
                # decision 2/G5: a violation reaching the report is a
                # SURFACED bug, never dropped
                floor_violations += 1
        evaluated += 1
        results.append({
            "evidence_set_id": example.evidence_set_id,
            "task_id": example.task_id,
            "predicted": {"outcome": predicted["outcome"],
                          "suggested": predicted["suggested"]},
            "truth": {"outcome": truth["outcome"],
                      "suggested": truth["suggested"]},
            "downgrade_flag": downgrade,
        })

    report = {
        "schema_version": 1,
        "corpus_id": corpus_id(entries),
        "policy_id": policy_id(policy),
        "policy": dict(policy.as_document()),
        "split": "leave_one_task_out",
        "results": results,
        "agreement": (agreements / evaluated) if evaluated else None,
        "false_downgrades": false_downgrades,
        "evaluated": evaluated,
        "unevaluable": unevaluable,
        "false_downgrade_rate": (
            false_downgrades / evaluated if evaluated else None
        ),
        "floor_violations": floor_violations,
    }
    errors = validate(report, load_schema("evaluation-report"))
    if errors:
        raise CalibrationError(
            f"derived evaluation report violates its own schema: "
            f"{errors[:3]}"
        )
    return report


EVALUATION_REPORT_NAME = "evaluation-report.json"


def write_evaluation_report(
    report: Mapping[str, Any], root: "str | Path"
) -> Path:
    """Persist atomically into the ANALYTICS-owned calibration root
    (never an E1 evidence root): schema-validated before the rename, so
    a partially written or invalid report is never discoverable."""
    errors = validate(report, load_schema("evaluation-report"))
    if errors:
        raise CalibrationError(
            f"refusing to persist an invalid evaluation report: "
            f"{errors[:3]}"
        )
    out = Path(root)
    out.mkdir(parents=True, exist_ok=True)
    target = out / EVALUATION_REPORT_NAME
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)
    return target


def load_evaluation_report(
    root: "str | Path | None",
) -> "Mapping[str, Any] | None":
    """The persisted report, or None when absent/unreadable/invalid —
    an unusable report is ABSENT (gates report insufficient_data),
    never partially trusted."""
    if not root:
        return None
    target = Path(root) / EVALUATION_REPORT_NAME
    if not target.is_file():
        return None
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if validate(doc, load_schema("evaluation-report")):
        return None
    return doc


# ── the five calibration gates (decision 2) ────────────────────────────
def _gate(gate_id, status, measured, threshold, reason, refs=()):
    return {"id": gate_id, "status": status, "measured": measured,
            "threshold": threshold, "reason": reason,
            "evidence_refs": list(refs)}


def _record_is_complete(record: Mapping[str, Any]) -> bool:
    """G1's per-record predicate: a non-insufficient cost AND a
    VERIFIED effective-model identity on every routing decision (null
    means unverified — never assumed equal to the requested model)."""
    if (record.get("cost") or {}).get("value") is None:
        return False
    decisions = record.get("routing_decisions") or []
    if not decisions:
        return False
    return all(d.get("effective_model") is not None for d in decisions)


def compute_gates(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
    config: Any,
    policy: EvaluationPolicy,
    current_policy: "Mapping[str, Any] | None",
    evaluation_report: "Mapping[str, Any] | None",
) -> Mapping[str, Any]:
    """The five #109 §12 conditions as executable results (decision 2).
    A gate whose inputs do not exist is insufficient_data, never pass;
    the overall verdict is calibrated only when EVERY gate passes.
    Nothing here acts on a result."""
    block = getattr(config, C.CFG_ROUTING_CALIBRATION, None) or {}
    for key in ("min_sufficiency", "min_tasks", "min_trials", "min_sets",
                "min_coverage"):
        if key not in block:
            raise CalibrationError(
                f"routing_calibration configuration is missing {key!r} — "
                f"gate thresholds are operator policy and are never "
                f"completed from code"
            )

    valid = [e for e in entries if isinstance(e, LoadedEvidenceSet)]
    invalid_count = sum(
        1 for e in entries if isinstance(e, InvalidEvidenceSet)
    )
    current_corpus = corpus_id(entries)
    current_policy_id = policy_id(policy)
    examples = extract_examples(entries)
    labeled = [e for e in examples
               if e.label is not None and e.features is not None]
    labeled_tasks = sorted({e.task_id for e in labeled})

    gates = []

    # ── G1: telemetry complete and accurate ──
    records = [r for e in valid for r in e.records]
    if not records:
        gates.append(_gate("telemetry_complete", "insufficient_data", None,
                           block["min_sufficiency"],
                           "the corpus contains no router records"))
    else:
        complete = sum(1 for r in records if _record_is_complete(r))
        fraction = complete / len(records)
        status = ("pass" if fraction >= float(block["min_sufficiency"])
                  else "fail")
        gates.append(_gate(
            "telemetry_complete", status, fraction,
            block["min_sufficiency"],
            f"{complete}/{len(records)} records carry measured cost and "
            f"a verified effective-model identity"
            + (f"; {invalid_count} invalid set(s) excluded from the corpus"
               if invalid_count else ""),
            [e.set_id for e in valid],
        ))

    # ── G2: enough repeated LABELED runs ──
    # Trials are counted OBSERVED here (a volume gate measures runs that
    # actually happened) and WITHIN a single set (cross-set aggregation
    # would mix fingerprints). This is the mirror image of the feature
    # rule, where only the DECLARED count may be read.
    observed_trials: dict[tuple[str, str], int] = {}
    for entry in valid:
        for rec in derive_recommendations(entry):
            observed_trials[(entry.set_id, rec["task_id"])] = len(
                rec["actual"]["per_trial"])
    min_trials = int(block["min_trials"])
    qualifying_tasks = sorted({
        e.task_id for e in labeled
        if observed_trials.get((e.evidence_set_id, e.task_id), 0)
        >= min_trials
    })
    contributing_sets = sorted({
        e.evidence_set_id for e in labeled
        if observed_trials.get((e.evidence_set_id, e.task_id), 0)
        >= min_trials
    })
    if not labeled:
        gates.append(_gate("labeled_volume", "insufficient_data", 0,
                           block["min_tasks"],
                           "no (set, task) pair carries a defined label"))
    else:
        enough = (
            len(qualifying_tasks) >= int(block["min_tasks"])
            and len(contributing_sets) >= int(block["min_sets"])
        )
        gates.append(_gate(
            "labeled_volume", "pass" if enough else "fail",
            len(qualifying_tasks), block["min_tasks"],
            f"{len(qualifying_tasks)} labeled task(s) reached "
            f"{min_trials} trials within a single set across "
            f"{len(contributing_sets)} set(s) "
            f"(min_sets={block['min_sets']})",
            qualifying_tasks,
        ))

    # ── G3: evaluated against held-out tasks ──
    staleness = (report_staleness(evaluation_report, current_corpus,
                                  current_policy_id)
                 if evaluation_report else None)
    if evaluation_report is None:
        gates.append(_gate("heldout_evaluated", "insufficient_data", None,
                           block["min_coverage"],
                           "no evaluation report exists"))
    elif staleness["stale"]:
        gates.append(_gate(
            "heldout_evaluated", "insufficient_data", None,
            block["min_coverage"],
            "the evaluation report is stale: "
            + ", ".join(staleness["reasons"]),
        ))
    else:
        covered = {r["task_id"] for r in evaluation_report["results"]}
        coverage = (len(covered & set(labeled_tasks)) / len(labeled_tasks)
                    if labeled_tasks else 0.0)
        status = ("pass" if labeled_tasks
                  and coverage >= float(block["min_coverage"]) else "fail")
        gates.append(_gate(
            "heldout_evaluated", status, coverage, block["min_coverage"],
            f"{len(covered & set(labeled_tasks))}/{len(labeled_tasks)} "
            f"labeled task(s) evaluated held-out",
            sorted(covered),
        ))

    # ── G4: false downgrades below the declared threshold ──
    if evaluation_report is None or staleness["stale"]:
        gates.append(_gate(
            "false_downgrade", "insufficient_data", None,
            policy.max_false_downgrade_rate,
            "no current evaluation report to measure",
        ))
    elif evaluation_report["false_downgrade_rate"] is None:
        gates.append(_gate(
            "false_downgrade", "insufficient_data", None,
            policy.max_false_downgrade_rate,
            "the evaluation report evaluated no task",
        ))
    else:
        rate = evaluation_report["false_downgrade_rate"]
        status = ("pass" if rate < policy.max_false_downgrade_rate
                  else "fail")
        gates.append(_gate(
            "false_downgrade", status, rate,
            policy.max_false_downgrade_rate,
            f"{evaluation_report['false_downgrades']}/"
            f"{evaluation_report['evaluated']} evaluated task(s) were "
            f"false downgrades "
            f"({evaluation_report['unevaluable']} unevaluable)",
        ))

    # ── G5: operator floors remain authoritative (three conjuncts) ──
    if current_policy is None:
        gates.append(_gate(
            "floors_authoritative", "insufficient_data", None,
            policy.tier_floor,
            "no current policy source is configured or parseable",
        ))
    elif evaluation_report is None or staleness["stale"]:
        gates.append(_gate(
            "floors_authoritative", "insufficient_data", None,
            policy.tier_floor,
            "no current evaluation report to check for violations",
        ))
    else:
        violations = evaluation_report["floor_violations"]
        digest_bound = (
            evaluation_report["policy"].get("policy_source_digest")
            == policy.policy_source_digest
            and policy.policy_source_digest is not None
        )
        conjuncts = {
            "floor_declared": policy.tier_floor in _TIER_RANK,
            "zero_violations": violations == 0,
            "policy_digest_bound": digest_bound,
        }
        failed = sorted(k for k, ok in conjuncts.items() if not ok)
        gates.append(_gate(
            "floors_authoritative", "pass" if not failed else "fail",
            violations, policy.tier_floor,
            "all three conjuncts hold" if not failed
            else f"unsatisfied conjunct(s): {failed}",
        ))

    report = {
        "schema_version": 1,
        "corpus_id": current_corpus,
        "policy_id": current_policy_id,
        "corpus": {
            "sets": len(valid),
            "invalid_sets": invalid_count,
            "labeled_tasks": len(labeled_tasks),
        },
        "gates": gates,
        "calibrated": all(g["status"] == "pass" for g in gates),
    }
    errors = validate(report, load_schema("calibration-report"))
    if errors:
        raise CalibrationError(
            f"derived calibration report violates its own schema: "
            f"{errors[:3]}"
        )
    return report


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
