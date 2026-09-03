# session_analytics.embedding.similarity — compatibility + pure
# similarity math (#287 T1; FR-A, FR-B's V1 choice, FR-C).
#
# THE COMPATIBILITY RULE COMES FIRST, and it is exactly the recorded
# evidence: two envelopes are in the same embedding space iff their
# validated triples are equal —
#
#     (provider, model, dim)
#
# The `model` field is a server-confirmed NAME/TAG, not a content
# digest (#285 T3 capture), so equality guarantees only what the
# envelopes RECORD: same backend family, same served name, same
# geometry. Same-server and unchanged-weights are UNVERIFIED
# ASSUMPTIONS — scores computed here are discovery heuristics over a
# same-named space, never identity proof.
#
# A `dim_conflict` — one (provider, model) name spanning multiple dims
# — is SURFACED, because it is direct evidence that name equality
# alone is not carrying the compatibility weight for that name. It
# never disqualifies a group: by the triple, each dim is simply its
# own space, and cross-dimension pairs cannot form because pairs are
# only ever formed INSIDE a group (structural, not a post-filter).
#
# Everything here is pure: no store, no I/O, no config reads. The
# grouping entry point REFUSES unvalidated envelopes rather than
# scoring them — one normative validator (#285 FR-9), consulted at
# the boundary.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from .contracts import (
    FIELD_DIM,
    FIELD_MODEL,
    FIELD_PROVIDER,
    validate_envelope,
)

#: The space key: FR-A's triple, in this order.
SpaceKey = tuple[str, str, int]


def space_key(envelope: Mapping[str, Any]) -> SpaceKey:
    """The FR-A triple of a VALIDATED envelope.

    Refuses an invalid envelope (ValueError carrying the FR-9 reason)
    — an unvalidated envelope must never acquire a space, because a
    space is a comparison license.
    """
    err = validate_envelope(envelope)
    if err is not None:
        raise ValueError(f"envelope failed validation: {err}")
    return (
        str(envelope[FIELD_PROVIDER]),
        str(envelope[FIELD_MODEL]),
        int(envelope[FIELD_DIM]),
    )


@dataclass(frozen=True)
class SpaceGroups:
    """The partition of a set of envelopes into embedding spaces.

    ``groups`` maps SpaceKey -> ordered list of member ids.
    ``excluded_invalid`` maps member id -> the FR-9 reason it was
    refused. ``dim_conflicts`` maps (provider, model) -> the sorted
    set of dims observed under that name, for every name spanning
    more than one dim — the report row FR-A demands. Conflicted
    members stay IN their per-dim groups.
    """

    groups: dict[SpaceKey, list[int]] = field(default_factory=dict)
    excluded_invalid: dict[int, str] = field(default_factory=dict)
    dim_conflicts: dict[tuple[str, str], tuple[int, ...]] = field(
        default_factory=dict)


def group_by_space(envelopes: Mapping[int, Mapping[str, Any]]) -> SpaceGroups:
    """Partition ``{member_id: envelope}`` into spaces (FR-A).

    Invalid envelopes are excluded WITH their reason, never scored.
    Iteration is by sorted member id so the partition is
    deterministic.
    """
    groups: dict[SpaceKey, list[int]] = {}
    excluded: dict[int, str] = {}
    for member_id in sorted(envelopes):
        # ONE space-key implementation (D1): the grouping boundary and
        # the standalone helper cannot drift, because this IS the
        # helper. Validation rides inside it.
        try:
            key = space_key(envelopes[member_id])
        except ValueError as exc:
            excluded[member_id] = str(exc)
            continue
        groups.setdefault(key, []).append(member_id)

    dims_by_name: dict[tuple[str, str], set[int]] = {}
    for provider, model, dim in groups:
        dims_by_name.setdefault((provider, model), set()).add(dim)
    conflicts = {
        name: tuple(sorted(dims))
        for name, dims in dims_by_name.items()
        if len(dims) > 1
    }
    return SpaceGroups(
        groups=groups, excluded_invalid=excluded, dim_conflicts=conflicts)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity, numerically safe for every FR-9-valid vector.

    FR-9 guarantees finite, not-all-zero components — nothing about
    magnitude. Naive sum-of-squares overflows [1e200, ...] to inf
    (yielding NaN) and underflows [1e-200, ...] to zero (yielding a
    false "caller bug" error), so each vector is scaled by its own
    max-|component| first: cosine is invariant under positive
    per-vector scaling, the largest scaled component is ±1, so squares
    can neither overflow nor collectively underflow to zero.

    A TRUE zero vector (max-|component| == 0) still raises — FR-9
    refuses those at the write boundary, so reaching here with one is
    a caller bug, not an input case."""
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    ma = max(abs(x) for x in a)
    mb = max(abs(y) for y in b)
    if ma == 0.0 or mb == 0.0:
        raise ValueError(
            "zero-norm vector reached cosine() — FR-9 refuses zero "
            "vectors at the write boundary, so this is a caller bug")
    sa = [x / ma for x in a]
    sb = [y / mb for y in b]
    dot = sum(x * y for x, y in zip(sa, sb))
    na = math.sqrt(sum(x * x for x in sa))
    nb = math.sqrt(sum(y * y for y in sb))
    return dot / (na * nb)


def top_k_neighbors(
    vectors: Mapping[int, list[float]],
    *,
    k: int,
    threshold: float,
) -> dict[int, list[tuple[int, float]]]:
    """For each member of ONE space: its top-k neighbors with
    score >= threshold, as (neighbor_id, score), best first.

    Deterministic: ties break by ascending neighbor id (stable across
    runs and platforms). Callers pass members of a single FR-A group —
    this function never sees two spaces, by construction of the pass.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    ids = sorted(vectors)
    scores: dict[int, list[tuple[int, float]]] = {i: [] for i in ids}
    for idx, a_id in enumerate(ids):
        for b_id in ids[idx + 1:]:
            s = cosine(vectors[a_id], vectors[b_id])
            if s >= threshold:
                scores[a_id].append((b_id, s))
                scores[b_id].append((a_id, s))
    return {
        i: sorted(pairs, key=lambda p: (-p[1], p[0]))[:k]
        for i, pairs in scores.items()
    }
