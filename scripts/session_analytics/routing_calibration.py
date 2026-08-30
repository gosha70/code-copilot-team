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
    derive_selector_policy,
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
    #: Digest of the repository's restriction-only routing config. None
    #: when no source is configured, which is a DIFFERENT policy from
    #: one that declares no restriction — hence its own identity
    #: dimension, so binding a repo source stales every prior report.
    repo_policy_digest: Optional[str]
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
            "repo_policy_digest": self.repo_policy_digest,
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
                "tier_floor", "policy_source", "repo_policy_source",
                "max_false_downgrade_rate")
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
        repo_policy_digest=policy_source_digest(
            block["repo_policy_source"]),
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


def _repo_restrictions(source: "str | None") -> "Mapping[str, Any] | None":
    """The repository's RESTRICTION-ONLY routing block, read from the
    configured automation config. None when no source is configured or
    it does not parse — never guessed, because "no configured source"
    and "a source that declares no restriction" are different facts
    and only the second one licenses a tier-2 suggestion."""
    if not source or not Path(source).is_file():
        return None
    try:
        doc = json.loads(Path(source).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    block = doc.get("routing")
    return block if isinstance(block, dict) else {}


def load_current_policy(config: Any) -> "Mapping[str, Any] | None":
    """The operator's CURRENT EFFECTIVE routing policy — composed the
    way ``rc_effective`` composes it for the production selector, so
    eligibility here is answered from the same authority production
    selects from rather than from a parallel rulebook.

    Composition (``scripts/lib/routing-config.sh``): ``enabled`` is
    the AND of the user registry's ``[policy].enabled`` and the repo's
    ``routing.enabled`` (each defaulting true when absent); the
    candidate set is the registry's profiles INTERSECTED with the
    repo's ``allowed_profiles`` (absent = no restriction); and
    ``tier2_delegation_allowed`` mirrors ``routing.tier2.
    delegation_enabled``.

    ``repo_policy_bound`` records whether a repo source was actually
    read. Production treats a null restriction as "no restriction",
    which is correct there because production KNOWS the repo config
    path; here an unconfigured source means the restriction is
    UNKNOWN, and a safety gate must not read unknown as permitted —
    so tier-2 suggestions stay ineligible until the source is bound.

    None when no registry source is configured, absent, or
    unparseable — an absent policy is representable (recommendations
    report insufficient_data), never fabricated."""
    block = getattr(config, C.CFG_ROUTING_CALIBRATION, None) or {}
    source = block.get("policy_source")
    if not source or not Path(source).is_file():
        return None
    try:
        derived = derive_selector_policy(Path(source))
    except (EvidenceSetError, ControlSetIncomplete, OSError):
        # an unparseable source is an ABSENT policy (recommendations
        # report insufficient_data), never a fabricated one
        return None
    profiles = dict(derived["profiles"])
    user_enabled = derived["enabled"]

    repo = _repo_restrictions(block.get("repo_policy_source"))
    allowed_ids = None
    repo_enabled = True
    tier2_allowed: "bool | None" = None
    if repo is not None:
        listed = repo.get("allowed_profiles")
        if isinstance(listed, list) and listed:
            allowed_ids = {str(i) for i in listed}
        repo_enabled = repo.get("enabled") is not False
        declared = (repo.get("tier2") or {}).get("delegation_enabled")
        # null/absent restricts nothing (production's own reading) —
        # but only once a source has actually been read
        tier2_allowed = declared is not False

    for profile_id, entry in profiles.items():
        entry["allowed"] = (allowed_ids is None
                            or profile_id in allowed_ids)

    return {
        "schema_version": 1,
        "registry_digest": "current",
        "enabled": bool(user_enabled) and repo_enabled,
        "repo_policy_bound": repo is not None,
        "tier2_delegation_allowed": tier2_allowed,
        "profiles": profiles,
    }


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


def _primary_candidate(
    profiles: Mapping[str, Any]
) -> "str | None":
    """The ``primary_only`` admissible profile: the total-order-FIRST
    tier1 candidate, ordered priority ASC then id ASC exactly as
    ``rt_select`` orders it. A profile whose priority did not parse
    sorts last rather than silently becoming the primary."""
    ranked = sorted(
        (pid for pid, p in profiles.items()
         if p["capability_tier"] == "tier1" and p.get("allowed", True)),
        key=lambda pid: (
            profiles[pid].get("priority") is None,
            profiles[pid].get("priority") or 0,
            pid,
        ),
    )
    return ranked[0] if ranked else None


def _route_class_admits(
    profile_id: str,
    profiles: Mapping[str, Any],
    current_policy: Mapping[str, Any],
    route_class: "str | None",
) -> bool:
    """Route-class admissibility, mirroring ``rt_select``'s own
    per-class rules (``scripts/lib/routing-select.sh``):

    - ``tier1_only`` — tier2 is NEVER selected;
    - ``primary_only`` — only the total-order-first tier1 candidate;
    - ``tier2_fallback`` / ``tier2_preferred`` — tier2 requires the
      repository to permit delegation.

    Runtime circuit state (cooldown, disabled, probing) and
    ``tier2_fallback``'s exhaustion precondition are deliberately NOT
    here: those are execution state, not configured policy, and a
    static eligibility filter that guessed at them would describe a
    moment rather than a rule. An UNKNOWN route class is inadmissible
    — a query whose class cannot be read is never certified."""
    if route_class not in ROUTE_CLASSES:
        return False
    tier = profiles[profile_id]["capability_tier"]
    if route_class in ("tier1_only", "primary_only"):
        if tier != "tier1":
            return False
        if route_class == "primary_only":
            return profile_id == _primary_candidate(profiles)
        return True
    if tier == "tier2":
        # production reads null as "no restriction"; an UNBOUND repo
        # policy is unknown, and unknown is never permission
        return current_policy.get("tier2_delegation_allowed") is True
    return True


def _eligible_under_policy(
    suggested: "Mapping[str, Any] | None",
    current_policy: Mapping[str, Any],
    tier_floor: str,
    route_class: "str | None",
) -> bool:
    """The current-policy filter (decisions 5/8), answered from the
    SAME effective policy the production selector consumes and made
    QUERY-AWARE: a suggestion is eligible only if the router could
    actually have selected that profile for a task of this route
    class.

    In order, mirroring ``rt_select``: routing must be enabled; the
    profile must be in the effective candidate set (registry
    INTERSECTED with the repository's ``allowed_profiles``); it must
    hold the build role; it must clear the calibration tier floor
    (an E3 policy layered on top); and the route class must admit it.

    Deliberately absent: ``data_policy`` and ``tool_profile``. The
    production selector carries both on the selected tuple but
    filters on NEITHER — enforcing them here would invent policy
    production does not have, which is its own way of describing
    something other than production.

    A no_change label names no profile and passes."""
    if suggested is None:
        return True
    if current_policy.get("enabled") is False:
        return False
    profiles = current_policy["profiles"]
    profile = profiles.get(suggested["profile_id"])
    if profile is None:
        return False
    if not profile.get("allowed", True):
        return False
    if _TIER_RANK[profile["capability_tier"]] < _TIER_RANK[tier_floor]:
        return False
    if "build" not in (profile.get("roles") or ()):
        return False
    return _route_class_admits(suggested["profile_id"], profiles,
                               current_policy, route_class)


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
    # THE query context eligibility is answered against (P1 of the T4
    # review): a route class the router could not have taken makes a
    # suggestion inadmissible no matter how similar its neighbors are.
    query_route_class = query.features["route_class"]

    # candidate filtering BEFORE ranking (decision 5)
    pool = [
        e for e in examples
        if e.task_id != task_id
        and e.features is not None
        and e.label is not None
        # the QUERY's route class governs: a neighbor's advice is a
        # pool candidate only if it could be actionable for THIS task
        and _eligible_under_policy(e.label["suggested"], current_policy,
                                   policy.tier_floor, query_route_class)
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
                                      policy.tier_floor,
                                      query_route_class):
            return _refuse(
                f"the winning suggestion is not eligible under the "
                f"current effective policy for a "
                f"{query_route_class!r} task"
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
      operated at. A chain is a COMPOSITION, not a menu: a delegated
      task's chain is [tier1 orchestrator, tier2 delegate], and
      recommending the tier2 profile DROPS the tier1 leg. So the
      baseline is the HIGHEST tier the router engaged — which also
      restores symmetry with the truth-switch branch (a single
      profile's own tier). Taking the lowest would make every
      delegated task structurally incapable of a false downgrade,
      which is exactly the arc §12 targets.

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
    return max(tiers, key=lambda t: _TIER_RANK[t])


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
    refused = 0
    compared = 0
    unresolved_tier = 0
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
        if predicted["outcome"] == "switch_profile" and current_policy:
            if not _eligible_under_policy(predicted["suggested"],
                                          current_policy,
                                          policy.tier_floor,
                                          example.features["route_class"]):
                # decision 2/G5: a violation reaching the report is a
                # SURFACED bug, never dropped
                floor_violations += 1

        # A REFUSAL is not a recommendation: it can never be a false
        # downgrade, so leaving it in the rate's denominator would let
        # an all-refusing recommender report 0.0 and pass G4. Refusals
        # are their own aggregate, out of the denominator AND out of
        # G3's coverage. Likewise a switch whose tier comparison cannot
        # resolve is UNJUDGED, not judged safe.
        if predicted["outcome"] == "insufficient_data":
            refused += 1
        else:
            compared += 1
            if predicted["outcome"] == truth["outcome"]:
                agreements += 1
            if predicted["outcome"] == "switch_profile" and (
                base is None
                or _tier_of((predicted["suggested"] or {}).get(
                    "profile_id"), profile_policy) is None
            ):
                unresolved_tier += 1
            else:
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
        "agreement": (agreements / compared) if compared else None,
        "false_downgrades": false_downgrades,
        "evaluated": evaluated,
        "compared": compared,
        "refused": refused,
        "unresolved_tier": unresolved_tier,
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


# ── addressable gate evidence (FR-E3-1) ────────────────────────────────
# A gate verdict a reader cannot inspect is an assertion, not evidence.
# Each locator below names a coordinate the Studio opens through an
# existing read-only surface; none is a path, and none is a bare string
# a consumer would have to parse.
def _ref_set(set_id: str) -> Mapping[str, Any]:
    return {"kind": "evidence_set", "evidence_set_id": set_id}


def _ref_task(set_id: str, task_id: str) -> Mapping[str, Any]:
    return {"kind": "task", "evidence_set_id": set_id, "task_id": task_id}


def _ref_evaluation() -> Mapping[str, Any]:
    return {"kind": "evaluation_report"}


def _ref_result(set_id: str, task_id: str) -> Mapping[str, Any]:
    return {"kind": "evaluation_result", "evidence_set_id": set_id,
            "task_id": task_id}


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
            [_ref_set(e.set_id) for e in valid],
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
    qualifying_pairs = sorted({
        (e.evidence_set_id, e.task_id) for e in labeled
        if observed_trials.get((e.evidence_set_id, e.task_id), 0)
        >= min_trials
    })
    qualifying_tasks = sorted({task for _, task in qualifying_pairs})
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
            [_ref_task(s_id, task) for s_id, task in qualifying_pairs],
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
        # a refusal is not coverage: G3 asks how much of the corpus was
        # actually EVALUATED against held-out tasks
        judged = [r for r in evaluation_report["results"]
                  if r["predicted"]["outcome"] != "insufficient_data"]
        covered = {r["task_id"] for r in judged}
        coverage = (len(covered & set(labeled_tasks)) / len(labeled_tasks)
                    if labeled_tasks else 0.0)
        status = ("pass" if labeled_tasks
                  and coverage >= float(block["min_coverage"]) else "fail")
        gates.append(_gate(
            "heldout_evaluated", status, coverage, block["min_coverage"],
            f"{len(covered & set(labeled_tasks))}/{len(labeled_tasks)} "
            f"labeled task(s) evaluated held-out",
            [_ref_evaluation()] + [
                _ref_result(r["evidence_set_id"], r["task_id"])
                for r in sorted(judged,
                                key=lambda r: (r["evidence_set_id"],
                                               r["task_id"]))
            ],
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
            f"{evaluation_report['evaluated']} judged recommendation(s) "
            f"were false downgrades "
            f"({evaluation_report['refused']} refused, "
            f"{evaluation_report['unresolved_tier']} tier-unresolved, "
            f"{evaluation_report['unevaluable']} unevaluable — all "
            f"outside the denominator)",
            # the report itself carries the DENOMINATOR; the per-result
            # refs are the numerator. Zero downgrades still leaves the
            # report openable, so a passing verdict is inspectable too.
            [_ref_evaluation()] + [
                _ref_result(r["evidence_set_id"], r["task_id"])
                for r in evaluation_report["results"]
                if r["downgrade_flag"]
            ],
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
        # every switch the floor check actually examined, so a
        # zero-violation verdict names what it ranged over
        examined = [r for r in evaluation_report["results"]
                    if r["predicted"]["outcome"] == "switch_profile"]
        gates.append(_gate(
            "floors_authoritative", "pass" if not failed else "fail",
            violations, policy.tier_floor,
            "all three conjuncts hold" if not failed
            else f"unsatisfied conjunct(s): {failed}",
            [_ref_evaluation()] + [
                _ref_result(r["evidence_set_id"], r["task_id"])
                for r in sorted(examined,
                                key=lambda r: (r["evidence_set_id"],
                                               r["task_id"]))
            ],
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


# ── the served surface (decision 10) ───────────────────────────────────
#: The closed payload-state vocabulary. ``report`` means a result was
#: derived; ``insufficient_data`` means one could not be — never a
#: fabricated or partial verdict, and never a bare error string the
#: caller has to parse.
PAYLOAD_STATES = ("report", "insufficient_data")

#: The evaluation aggregates rendered BESIDE the gate verdicts. Every
#: numeric is None when no report exists, so one shape renders every
#: state.
_EVALUATION_FIELDS = (
    "agreement", "compared", "evaluated", "refused", "unresolved_tier",
    "unevaluable", "false_downgrades", "false_downgrade_rate",
    "floor_violations",
)


def _evaluation_summary(
    report: "Mapping[str, Any] | None",
    staleness: "Mapping[str, Any] | None",
) -> Mapping[str, Any]:
    """The evaluation aggregates the promotion decision needs in view
    beside the five verdicts.

    ``agreement`` rides here deliberately even though NO gate consumes
    it. The gates are a safety floor, and a recommender that answers
    ``no_change_recommended`` for every task clears that floor
    honestly: it makes real recommendations, none of which can be a
    downgrade, so it earns a truthful 0.0 rate and full coverage while
    proposing nothing. That is safe but inert, and per-gate status
    alone cannot tell the two apart. Agreement is the usefulness
    reading; an operator holds the promotion call only with both
    numbers on the surface.
    """
    if report is None:
        return {
            "present": False, "stale": False, "stale_reasons": [],
            **{key: None for key in _EVALUATION_FIELDS},
        }
    staleness = staleness or {"stale": False, "reasons": []}
    return {
        "present": True,
        "stale": staleness["stale"],
        "stale_reasons": list(staleness["reasons"]),
        **{key: report[key] for key in _EVALUATION_FIELDS},
    }


def _persisted_evaluation(config: Any) -> "Mapping[str, Any] | None":
    block = getattr(config, C.CFG_ROUTING_CALIBRATION, None) or {}
    return load_evaluation_report(block.get("root"))


def calibration_payload(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
    config: Any,
) -> Mapping[str, Any]:
    """The live gate report for the current corpus and configuration,
    or ``insufficient_data`` when the operator configuration cannot
    yield one at all. The evaluation summary and its stale state are
    always explicit; the policy echo is the identity document (digests
    only) — the configured roots and policy-source PATH never leave the
    server, matching the E2 sanitization floor."""
    try:
        policy = policy_from_config(config)
        current_policy = load_current_policy(config)
        evaluation = _persisted_evaluation(config)
        report = compute_gates(entries, config, policy, current_policy,
                               evaluation)
    except CalibrationError as exc:
        return {"state": "insufficient_data", "reason": str(exc),
                "report": None, "evaluation": _evaluation_summary(None, None),
                "policy": None}
    staleness = (
        report_staleness(evaluation, report["corpus_id"],
                         report["policy_id"])
        if evaluation is not None else None
    )
    return {
        "state": "report",
        "reason": None,
        "report": report,
        "evaluation": _evaluation_summary(evaluation, staleness),
        "policy": policy.as_document(),
    }


def evaluation_payload(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
    config: Any,
) -> Mapping[str, Any]:
    """The persisted held-out evaluation report, stale-flagged against
    the live corpus and policy. An absent, unreadable, or invalid
    report is ``insufficient_data`` — never partially served."""
    try:
        policy = policy_from_config(config)
    except CalibrationError as exc:
        return {"state": "insufficient_data", "reason": str(exc),
                "report": None, "staleness": None}
    report = _persisted_evaluation(config)
    if report is None:
        return {
            "state": "insufficient_data",
            "reason": "no readable evaluation report in the configured "
                      "calibration root",
            "report": None, "staleness": None,
        }
    return {
        "state": "report",
        "reason": None,
        "report": report,
        "staleness": report_staleness(report, corpus_id(entries),
                                      policy_id(policy)),
    }


def knn_payload(
    entries: Sequence["LoadedEvidenceSet | InvalidEvidenceSet"],
    set_id: str,
    config: Any,
) -> Mapping[str, Any]:
    """Every task of one set's shadow kNN recommendation, served BESIDE
    the E2 dominance recommendations (never in place of them). Examples
    are extracted once so all tasks of the set share one deterministic
    corpus read; a task whose features or neighborhood are unavailable
    carries its own ``insufficient_data`` with the reason."""
    try:
        policy = policy_from_config(config)
    except CalibrationError as exc:
        return {"state": "insufficient_data", "reason": str(exc),
                "set_id": set_id, "recommendations": []}
    current_policy = load_current_policy(config)
    examples = extract_examples(entries)
    return {
        "state": "report",
        "reason": None,
        "set_id": set_id,
        "recommendations": [
            knn_recommendation(entries, set_id, example.task_id, policy,
                               current_policy, _examples=examples)
            for example in examples
            if example.evidence_set_id == set_id
        ],
    }
