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

from session_analytics import constants as C
from session_analytics.routing_evidence import (
    InvalidEvidenceSet,
    LoadedEvidenceSet,
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
