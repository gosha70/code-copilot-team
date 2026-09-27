"""Session threads from native lineage (#371 A6) — the derivation core.

Which session was resumed from which, decided from identifiers the
transcript exposes natively.

A resumed session's transcript REPLAYS its ancestor's records and
preserves their ``uuid``. Two copy behaviours exist in the wild: the
newer keeps the ancestor's ``sessionId`` on the copied records, the
older rewrites it. The uuid survives both, which is what makes lineage
provable rather than inferred.

NO TIMESTAMP IS AN INPUT ANYWHERE in this module — not to ancestry, not
to ordering, not to terminality, not to rooting. A resumed transcript
copies the ancestor's timestamps verbatim, so two sources in one lineage
share a first timestamp to the millisecond. Time here is not a weak
signal; it is a wrong one.

This module derives. It does not read or write the store: persistence is
the caller's job, so the rule can be tested on sets alone.
"""

from __future__ import annotations

import json
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from . import constants as C
from .relational.db import now_iso

__all__ = [
    "SourceRef",
    "Relation",
    "RelationCandidate",
    "ThreadGraph",
    "uuids_from_transcript",
    "classify_pair",
    "derive",
    "transitive_reduction",
    "pair_shortlist",
    "reduce_pairs",
    "new_thread_id",
    "ThreadStoreError",
    "register_source",
    "allocate_thread",
    "resolve_thread",
    "resolve_thread_id",
    "thread_distinct_uuids",
    "connect_threads",
    "store_candidates",
    "persist",
    "reconcile",
    "load_source_uuids",
    "probe_related_members",
    "detect_for_session",
    "known_sources",
    "backfill",
    "thread_figures",
    "thread_figures_for_session",
    "THREAD_ADDITIVE_TURN_COLUMNS",
    "THREAD_FIGURE_FIELDS",
    "threads_for_session",
    "lineage_support",
    "session_lineage",
    "SessionNotFound",
    "thread_view",
]


@dataclass(frozen=True)
class SourceRef:
    """One source transcript and the turn uuids it carries.

    The unit of lineage is a SOURCE, not a session row. The Claude Code
    adapter groups several transcripts into one session and dedupes
    their uuids — correct, and load-bearing, but it consumes the
    evidence that there were several. Keeping sources distinct here is
    what lets that be recorded.
    """

    copilot: str
    source_key: str
    native_session_id: str
    uuids: frozenset[str]

    @property
    def identity(self) -> tuple[str, str]:
        """Globally unique, matching ``thread_member``'s UNIQUE key."""
        return (self.copilot, self.source_key)

    @property
    def uuid_count(self) -> int:
        return len(self.uuids)


@dataclass(frozen=True)
class Relation:
    """An ancestry edge and the evidence that authorized it.

    `ancestor_only` and `descendant_only` are the exact set differences
    the DIRECTION was decided from, and the edge exists because
    `descendant_only > ancestor_only`. They are carried rather than
    recomputed because the shared count and two rounded ratios cannot
    re-derive the direction.
    """

    ancestor: tuple[str, str]
    descendant: tuple[str, str]
    shared_uuids: int
    ancestor_containment: float
    descendant_containment: float
    ancestor_only: int
    descendant_only: int
    provenance: str
    rule_version: str = C.THREAD_RULE_VERSION


@dataclass(frozen=True)
class RelationCandidate:
    """A gated pair that produced no edge, because neither side grew.

    Deliberately NOT called a merge candidate: only one of its two
    kinds is a merge proposal. Merging a `direction_ambiguous` pair —
    two sources that genuinely differ — would destroy real information,
    and a name that recommends merging would push a reader toward
    exactly that on half these rows.

    `a_only == b_only` is exactly why there is no edge, and the two
    kinds are not the same problem:

    * `duplicate_identity` — both zero, the sources carry identical
      uuid sets.
    * `direction_ambiguous` — both non-zero, each side has as much the
      other lacks. They genuinely differ and this is NOT a proposal to
      merge them.

    The pair is held in canonical order so one candidate cannot be
    recorded twice reversed — the order the table's CHECK enforces.
    """

    member_a: tuple[str, str]
    member_b: tuple[str, str]
    shared_uuids: int
    containment_a: float
    containment_b: float
    a_only: int
    b_only: int
    candidate_kind: str
    rule_version: str = C.THREAD_RULE_VERSION


@dataclass
class ThreadGraph:
    """One detected component: its sources, its reduced edges, its flags.

    It carries NO identity. Derivation is a pure function of the uuid
    sets, and issuing a surrogate here would make two runs over
    unchanged input disagree — then oblige the persistence layer to
    ignore the identity it had just been handed. Allocating or reusing a
    `thread_id` belongs to the connection layer, which is the only place
    that can know whether an active thread already covers these members.
    """

    members: tuple[tuple[str, str], ...]
    edges: tuple[Relation, ...]
    roots: tuple[tuple[str, str], ...]
    terminals: tuple[tuple[str, str], ...]
    fork_suspected: bool = False
    terminal_ambiguous: bool = False
    #: The component has more than one member with no incoming edge.
    #: Every actual root is reported; none is chosen.
    root_ambiguous: bool = False
    #: Members with more than one incomparable immediate ancestor — a
    #: join, the mirror of a fork. Flagged per member so a read surface
    #: can show joins apart from the primary tree rather than
    #: duplicating the node under each ancestor.
    joins: tuple[tuple[str, str], ...] = ()


#: The record types the Claude Code adapter admits as turns. A6 must
#: read the SAME universe the turn-uuid index holds: the probe searches
#: `copilot_turn.uuid`, which only ever contains conversational records
#: that carry a `message` object. Reading every record's uuid instead
#: would compute evidence the indexed dataset cannot reproduce, and
#: would miss collisions the probe can never return.
_TURN_RECORD_TYPES = (C.ROLE_USER, C.ROLE_ASSISTANT)


def uuids_from_transcript(path: Path) -> Optional[frozenset[str]]:
    """Every TURN uuid in one transcript, or None if it cannot be read.

    "Turn" means exactly what the adapter means by it — a record whose
    `type` is user or assistant and which carries a `message` object.
    That alignment is load-bearing, not tidiness: the index probe
    searches stored turn uuids, so classifying over the wider record set
    would store shared/dropped/added counts that no query over the index
    could ever reproduce, and would let a pair "collide" on a record the
    probe cannot see.

    ONE open decides both questions. Checking readability and then
    re-opening to parse leaves a window in which a source pruned between
    the two reads is reported as available-but-empty — which would let
    coverage claim a gap does not exist and let reconciliation retire
    that source's lineage on the strength of an empty set.

    A malformed LINE is skipped rather than fatal: a truncated tail is
    ordinary in a live transcript, and losing the whole source over it
    would turn a partial read into a missing lineage.
    """
    found: set[str] = set()
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("type") not in _TURN_RECORD_TYPES:
                    continue
                if not isinstance(record.get("message"), dict):
                    continue
                value = record.get("uuid")
                if isinstance(value, str) and value:
                    found.add(value)
    except OSError:
        return None
    return frozenset(found)


def classify_pair(
    a: SourceRef,
    b: SourceRef,
    provenance: str,
    *,
    threshold: float = C.THREAD_CONTAINMENT_THRESHOLD,
    min_shared: int = C.THREAD_MIN_SHARED_UUIDS,
) -> Optional[Relation | RelationCandidate]:
    r"""Apply the versioned rule to one pair: containment GATES, net
    growth DIRECTS.

    1. gate       ``s = |A ∩ B| >= min_shared`` and
                  ``max(s/|A|, s/|B|) >= threshold``
    2. differences ``a_only = |A \ B|``, ``b_only = |B \ A|``
    3. direction  ``b_only > a_only`` -> A is ancestor of B;
                  ``a_only > b_only`` -> B is ancestor of A;
                  equal -> no edge, an unresolved candidate

    Comparing the two containment ratios cannot express the real data:
    the deepest real link in the corpus is 0.953 one way and 0.897 the
    other, so a symmetric test calls it a duplicate, and no threshold
    repairs it — raising one above 0.897 destroys the 0.750 edges. Net
    growth decides it correctly and for the right reason: a resume after
    a compaction drops some turns and adds more.

    ``provenance`` records how the pair was FOUND and authorizes
    nothing. Adapter grouping proves common membership, not predecessor
    order — and its grouping key is a sessionId an older CLI rewrote
    anyway — so the same rule decides direction whichever way the pair
    arrived, and both provenances carry the same evidence.
    """
    if a.identity == b.identity:
        return None
    if not a.uuids or not b.uuids:
        return None

    shared = len(a.uuids & b.uuids)
    if shared < min_shared:
        return None

    ratio_a = shared / a.uuid_count
    ratio_b = shared / b.uuid_count
    if max(ratio_a, ratio_b) < threshold:
        return None

    a_only = len(a.uuids - b.uuids)
    b_only = len(b.uuids - a.uuids)

    if b_only > a_only:
        return Relation(
            ancestor=a.identity, descendant=b.identity, shared_uuids=shared,
            ancestor_containment=ratio_a, descendant_containment=ratio_b,
            ancestor_only=a_only, descendant_only=b_only, provenance=provenance,
        )
    if a_only > b_only:
        return Relation(
            ancestor=b.identity, descendant=a.identity, shared_uuids=shared,
            ancestor_containment=ratio_b, descendant_containment=ratio_a,
            ancestor_only=b_only, descendant_only=a_only, provenance=provenance,
        )

    # Neither side grew, so nothing says which came first. The two
    # equal-difference cases are NOT the same problem and must not
    # render alike.
    kind = (
        C.CANDIDATE_DUPLICATE_IDENTITY if a_only == 0
        else C.CANDIDATE_DIRECTION_AMBIGUOUS
    )
    first, second = (a, b) if a.identity <= b.identity else (b, a)
    first_ratio = ratio_a if first is a else ratio_b
    second_ratio = ratio_b if first is a else ratio_a
    first_only = a_only if first is a else b_only
    second_only = b_only if first is a else a_only
    return RelationCandidate(
        member_a=first.identity, member_b=second.identity, shared_uuids=shared,
        containment_a=first_ratio, containment_b=second_ratio,
        a_only=first_only, b_only=second_only, candidate_kind=kind,
    )


def reduce_pairs(pairs: Iterable[tuple]) -> set[tuple]:
    """Transitive reduction over bare (ancestor, descendant) pairs.

    Split out so the SAME algorithm reduces a freshly derived graph and
    a thread's combined stored edges. They must agree: a pass that
    reduced only its own shortlist would leave an A->C edge standing
    beside a retained A->B->C chain.
    """
    edges = {(a, b) for a, b in pairs}
    children: dict = {}
    for a, b in edges:
        children.setdefault(a, set()).add(b)

    def reachable(start, via: set) -> set:
        seen: set = set()
        stack = list(via)
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(children.get(node, ()))
        return seen

    kept = set()
    for ancestor, descendant in edges:
        detour = children.get(ancestor, set()) - {descendant}
        if descendant in reachable(ancestor, detour):
            continue  # a longer path already expresses this
        kept.add((ancestor, descendant))
    return kept


def transitive_reduction(edges: Sequence[Relation]) -> tuple[Relation, ...]:
    """Keep each member's IMMEDIATE predecessor, drop the rest.

    Reduction runs over the COMPLETE derived set, never during
    derivation: reducing as edges arrive would make the result depend on
    visit order.
    """
    by_pair = {(e.ancestor, e.descendant): e for e in edges}
    kept = reduce_pairs(by_pair)
    return tuple(sorted(
        (by_pair[p] for p in kept), key=lambda e: (e.ancestor, e.descendant)))


def new_thread_id() -> str:
    """Issue an opaque surrogate.

    Issued, never derived: an id computed from membership would re-key
    the thread the moment a member moved — which is exactly what happens
    when an older ancestor is discovered later, the case this model
    exists to survive.
    """
    return _uuid.uuid4().hex


def pair_shortlist(
    ordered: Sequence[SourceRef],
    candidate_pairs: Optional[Iterable] = None,
) -> list[tuple]:
    """The pairs a pass will actually classify.

    Shared by `derive` and `reconcile` deliberately: reconciliation
    retires stored edges and candidates for exactly the pairs that were
    EVALUATED, so if the two ever computed that set differently, a
    production pass would retire lineage its shortlist never examined.

    When one pair arrives from both discovery paths the stronger
    provenance wins by the declared precedence — never "whichever came
    first", which would make the record depend on iteration order.
    """
    if candidate_pairs is None:
        return [
            (a.identity, b.identity, C.THREAD_PROVENANCE_UUID_CONTAINMENT)
            for i, a in enumerate(ordered)
            for b in ordered[i + 1:]
        ]
    rank = {name: i for i, name in enumerate(C.THREAD_PROVENANCE_PRECEDENCE)}
    best: dict = {}
    for left, right, provenance in candidate_pairs:
        if left == right:
            continue
        key = frozenset((left, right))
        held = best.get(key)
        if held is None:
            best[key] = (left, right, provenance)
            continue
        if rank.get(provenance, len(rank)) < rank.get(held[2], len(rank)):
            best[key] = (held[0], held[1], provenance)
    return sorted(best.values(), key=lambda triple: (triple[0], triple[1]))


def derive(
    sources: Iterable[SourceRef],
    *,
    candidate_pairs: Optional[Iterable[tuple[tuple[str, str], tuple[str, str], str]]] = None,
    threshold: float = C.THREAD_CONTAINMENT_THRESHOLD,
    min_shared: int = C.THREAD_MIN_SHARED_UUIDS,
) -> tuple[tuple[ThreadGraph, ...], tuple[RelationCandidate, ...]]:
    """Derive every thread and every merge candidate from `sources`.

    `candidate_pairs` is the caller's shortlist — `(identity_a,
    identity_b, provenance)` triples from the adapter grouping and from
    the turn-uuid index probe. When omitted every pair is considered,
    which is correct but quadratic: production passes the shortlist, and
    tests pass nothing.

    Four ambiguities are reported and none is resolved: a fork (a
    member with several incomparable descendants), a join (a member with
    several incomparable ancestors — reported per member, since a read
    surface must show joins apart from the primary tree rather than
    duplicating the node under each ancestor), an ambiguous terminal,
    and an ambiguous root. Every actual root and terminal is marked and
    none is chosen.
    """
    by_identity = {s.identity: s for s in sources}
    ordered = sorted(by_identity.values(), key=lambda s: s.identity)

    pairs = pair_shortlist(ordered, candidate_pairs)

    relations: list[Relation] = []
    candidates: list[RelationCandidate] = []
    for left, right, provenance in pairs:
        a, b = by_identity.get(left), by_identity.get(right)
        if a is None or b is None:
            continue
        verdict = classify_pair(
            a, b, provenance, threshold=threshold, min_shared=min_shared
        )
        if isinstance(verdict, Relation):
            relations.append(verdict)
        elif isinstance(verdict, RelationCandidate):
            candidates.append(verdict)

    reduced = transitive_reduction(relations)

    # Components over the UNDIRECTED edge set: a thread is everything
    # lineage connects, in either direction.
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {
        s.identity: set() for s in ordered
    }
    for edge in reduced:
        adjacency[edge.ancestor].add(edge.descendant)
        adjacency[edge.descendant].add(edge.ancestor)

    graphs: list[ThreadGraph] = []
    unvisited = {s.identity for s in ordered}
    for identity in sorted(unvisited):
        if identity not in unvisited:
            continue
        component: set[tuple[str, str]] = set()
        stack = [identity]
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            unvisited.discard(node)
            stack.extend(adjacency.get(node, ()))
        if len(component) < 2:
            continue  # a lone source is not a thread

        edges = tuple(e for e in reduced if e.ancestor in component)
        has_parent = {e.descendant for e in edges}
        has_child = {e.ancestor for e in edges}
        roots = tuple(sorted(m for m in component if m not in has_parent))
        terminals = tuple(sorted(m for m in component if m not in has_child))

        children: dict[tuple[str, str], list[tuple[str, str]]] = {}
        parents: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for edge in edges:
            children.setdefault(edge.ancestor, []).append(edge.descendant)
            parents.setdefault(edge.descendant, []).append(edge.ancestor)
        # After reduction two children of one member cannot be
        # comparable — an edge to a reachable descendant is exactly what
        # reduction removes — so more than one child IS a fork, and by
        # the same argument more than one parent IS a join. Branches and
        # evidence edges are kept; nothing is ordered and no canonical
        # predecessor is chosen.
        fork = any(len(kids) > 1 for kids in children.values())
        joins = tuple(sorted(m for m, ps in parents.items() if len(ps) > 1))

        graphs.append(
            ThreadGraph(
                members=tuple(sorted(component)),
                edges=edges,
                roots=roots,
                terminals=terminals,
                fork_suspected=fork,
                terminal_ambiguous=len(terminals) > 1,
                root_ambiguous=len(roots) > 1,
                joins=joins,
            )
        )

    return tuple(graphs), tuple(
        sorted(candidates, key=lambda c: (c.member_a, c.member_b))
    )


# ── Persistence and connection ─────────────────────────────────────────
# Everything above derives; everything below stores. The split is not
# cosmetic: derivation must be a pure function of the uuid sets, so
# identity — which thread these members belong to — is decided here,
# where the store can say whether an active thread already covers them.


class ThreadStoreError(RuntimeError):
    """A stored lineage graph violates an invariant the model relies on.

    Raised rather than repaired: a redirect chain that does not end in
    an active thread means something wrote a state this module says is
    impossible, and silently healing it would hide the writer.
    """


def resolve_thread(db, thread_ref: int) -> int:
    """Follow ``redirected_to_ref`` to the ACTIVE terminal thread.

    This is the resolve-first step every connection begins with, and the
    reason acyclicity does not depend on the survivor ranking: thread
    sizes change as members move, so the side that lost once could
    outrank its survivor later. Comparing only resolved ACTIVE threads
    means every redirect runs from a thread becoming inactive to one
    that was active when chosen, and an inactive thread is never
    selected as a new target again.
    """
    seen: set[int] = set()
    current = thread_ref
    while True:
        row = db.query_one(
            "SELECT id, status, redirected_to_ref FROM session_thread WHERE id = ?",
            (current,),
        )
        if row is None:
            raise ThreadStoreError(f"thread {current} does not exist")
        ident, status, target = row[0], row[1], row[2]
        if status == C.THREAD_STATUS_ACTIVE:
            return ident
        if target is None:
            raise ThreadStoreError(
                f"thread {ident} is redirected with no target — unreachable by "
                "the model's own CHECK, so the store was written by something else"
            )
        if ident in seen:
            raise ThreadStoreError(
                f"redirect cycle through thread {ident}; the resolve-first rule "
                "makes this unreachable, so it is reported rather than repaired"
            )
        seen.add(ident)
        current = target


def resolve_thread_id(db, thread_id: str) -> Optional[int]:
    """A lookup by a REDIRECTED thread_id resolves to its survivor.

    Both ids stay valid and immutable: rewriting one would break every
    reference already handed out, and deleting one would make a valid id
    return nothing.
    """
    row = db.query_one("SELECT id FROM session_thread WHERE thread_id = ?", (thread_id,))
    if row is None:
        return None
    return resolve_thread(db, row[0])


def thread_distinct_uuids(db, thread_ref: int) -> int:
    """Distinct turn uuids across a thread's attached members.

    NEVER a sum of member or session figures: a descendant carries up to
    90% of its ancestor's turns, so summing is wrong by up to that much.
    A turn with a null uuid cannot be counted distinctly and is excluded
    from thread figures; it still counts once under its own session.
    """
    row = db.query_one(
        """
        SELECT COUNT(DISTINCT t.uuid)
          FROM thread_member m
          JOIN copilot_turn t ON t.session_id = m.session_ref
         WHERE m.thread_ref = ? AND m.session_ref IS NOT NULL AND t.uuid IS NOT NULL
        """,
        (thread_ref,),
    )
    return int(row[0]) if row and row[0] is not None else 0


def register_source(
    db,
    source: SourceRef,
    *,
    session_ref: Optional[int] = None,
    source_available: bool = True,
) -> int:
    """Record a source transcript, attached to no thread yet.

    A row here is a REGISTERED SOURCE first and an attached member
    second. Two real cases never gain a thread: a pair that produced an
    unresolved relation candidate, and a known source missing on disk.
    Identity is global, so re-registering updates rather than duplicates.
    """
    row = db.query_one(
        "SELECT id FROM thread_member WHERE copilot = ? AND source_key = ?",
        (source.copilot, source.source_key),
    )
    if row is not None:
        db.execute(
            """
            UPDATE thread_member
               SET native_session_id = ?, turn_uuid_count = ?, source_available = ?,
                   session_ref = COALESCE(?, session_ref)
             WHERE id = ?
            """,
            (source.native_session_id, source.uuid_count,
             bool(source_available), session_ref, row[0]),
        )
        return int(row[0])
    return int(db.insert_returning_id(
        """
        INSERT INTO thread_member
            (thread_ref, copilot, native_session_id, session_ref, source_key,
             source_available, turn_uuid_count)
        VALUES (NULL, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (source.copilot, source.native_session_id, session_ref,
         source.source_key, bool(source_available), source.uuid_count),
    ))


def _stamp(now: Optional[str]) -> str:
    """The audit timestamp, normalized.

    Every production caller omits `now`, so a bare default of None wrote
    `detected_at = NULL` at creation and then erased `updated_at` on
    every later pass. These are AUDIT metadata and never an input to
    lineage — nothing in the rule reads them — but "when was this
    thread first seen" is exactly the question a null cannot answer.
    """
    return now or now_iso()


def allocate_thread(db, *, now: Optional[str] = None) -> int:
    """Issue one surrogate. The only place a thread_id is created."""
    stamp = _stamp(now)
    return int(db.insert_returning_id(
        """
        INSERT INTO session_thread (thread_id, status, detected_at, updated_at)
        VALUES (?, ?, ?, ?) RETURNING id
        """,
        (new_thread_id(), C.THREAD_STATUS_ACTIVE, stamp, stamp),
    ))


def connect_threads(db, left_ref: int, right_ref: int, *, now: Optional[str] = None) -> int:
    """Join two threads a later source has bridged; return the survivor.

    Resolve-first, then act. When both sides resolve to the SAME active
    thread the connection is already represented and this is a no-op —
    which is what makes a merge attempted through an old redirected id
    harmless and the whole pass idempotent.

    The survivor is chosen deterministically and without any time input:
    more distinct turn uuids wins, ties broken by the lexicographically
    smaller ``thread_id``. Determinism is what stops two runs over
    unchanged input producing different graphs; acyclicity comes from
    resolve-first, not from this ranking.
    """
    left = resolve_thread(db, left_ref)
    right = resolve_thread(db, right_ref)
    if left == right:
        return left

    left_uuids = thread_distinct_uuids(db, left)
    right_uuids = thread_distinct_uuids(db, right)
    if left_uuids != right_uuids:
        survivor, loser = (left, right) if left_uuids > right_uuids else (right, left)
    else:
        left_id = db.query_one(
            "SELECT thread_id FROM session_thread WHERE id = ?", (left,))[0]
        right_id = db.query_one(
            "SELECT thread_id FROM session_thread WHERE id = ?", (right,))[0]
        survivor, loser = (left, right) if left_id <= right_id else (right, left)

    db.execute("UPDATE thread_member SET thread_ref = ? WHERE thread_ref = ?",
               (survivor, loser))
    db.execute("UPDATE thread_edge SET thread_ref = ? WHERE thread_ref = ?",
               (survivor, loser))
    db.execute(
        """
        UPDATE session_thread
           SET status = ?, redirected_to_ref = ?, member_count = 0, updated_at = ?
         WHERE id = ?
        """,
        (C.THREAD_STATUS_REDIRECTED, survivor, _stamp(now), loser),
    )
    _refresh_member_count(db, survivor, now=now)
    return survivor


def _refresh_member_count(db, thread_ref: int, *, now: Optional[str] = None) -> None:
    """``member_count`` counts ATTACHED rows only."""
    row = db.query_one(
        "SELECT COUNT(*) FROM thread_member WHERE thread_ref = ?", (thread_ref,))
    db.execute(
        "UPDATE session_thread SET member_count = ?, updated_at = ? WHERE id = ?",
        (int(row[0]) if row else 0, _stamp(now), thread_ref),
    )


def store_candidates(
    db,
    candidates: Iterable[RelationCandidate],
    member_ids: dict,
    *,
    evaluated_pairs: Optional[Iterable[tuple[int, int]]] = None,
    now: Optional[str] = None,
) -> dict:
    """Persist unresolved relation candidates, and RETIRE resolved ones.

    Insert-or-update alone is not enough. A pair that was ambiguous can
    become directional later — a source re-read with more uuids is the
    ordinary case — and the stale candidate would then sit beside the
    new edge, so the read surface would keep reporting an outstanding
    question that the data has already answered.

    ``evaluated_pairs`` is the set of member-ref pairs this pass
    actually classified. Every evaluated pair that is no longer a
    candidate is deleted; a pair the incremental probe never looked at
    is left alone, because "not evaluated" is not "resolved".
    """
    stats = {"written": 0, "updated": 0, "retired": 0}
    still: set[tuple[int, int]] = set()

    for candidate in candidates:
        a_ref = member_ids.get(candidate.member_a)
        b_ref = member_ids.get(candidate.member_b)
        if a_ref is None or b_ref is None:
            continue
        # canonical order by ROW ID, which is what the table's CHECK holds
        first, second = (a_ref, b_ref) if a_ref < b_ref else (b_ref, a_ref)
        flip = first != a_ref
        c_a = candidate.containment_b if flip else candidate.containment_a
        c_b = candidate.containment_a if flip else candidate.containment_b
        o_a = candidate.b_only if flip else candidate.a_only
        o_b = candidate.a_only if flip else candidate.b_only
        still.add((first, second))
        existing = db.query_one(
            "SELECT id FROM thread_relation_candidate "
            "WHERE member_a_ref = ? AND member_b_ref = ?",
            (first, second),
        )
        if existing is not None:
            db.execute(
                """
                UPDATE thread_relation_candidate
                   SET shared_uuids = ?, containment_a = ?, containment_b = ?,
                       a_only = ?, b_only = ?, candidate_kind = ?, rule_version = ?
                 WHERE id = ?
                """,
                (candidate.shared_uuids, c_a, c_b, o_a, o_b,
                 candidate.candidate_kind, candidate.rule_version, existing[0]),
            )
            stats["updated"] += 1
            continue
        db.execute(
            """
            INSERT INTO thread_relation_candidate
                (member_a_ref, member_b_ref, shared_uuids, containment_a,
                 containment_b, a_only, b_only, candidate_kind, rule_version,
                 detected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (first, second, candidate.shared_uuids, c_a, c_b, o_a, o_b,
             candidate.candidate_kind, candidate.rule_version, _stamp(now)),
        )
        stats["written"] += 1

    for left, right in sorted(set(evaluated_pairs or ())):
        pair = (left, right) if left < right else (right, left)
        if pair in still:
            continue
        row = db.query_one(
            "SELECT id FROM thread_relation_candidate "
            "WHERE member_a_ref = ? AND member_b_ref = ?", pair)
        if row is None:
            continue
        db.execute("DELETE FROM thread_relation_candidate WHERE id = ?", (row[0],))
        stats["retired"] += 1
    return stats


def _recompute_flags(db, thread_ref: int, *, now: Optional[str] = None) -> None:
    """Derive every flag from the edges the thread ACTUALLY holds.

    Not from the graph just derived. A pass may retain edges it did not
    re-derive — an unreadable member's lineage is kept rather than
    erased — and flags computed from the partial graph would then
    contradict the stored evidence: a member with a retained incoming
    edge could be written as a root. The persisted edge set is the only
    thing that can answer, so it is what answers.
    """
    members = [int(r[0]) for r in db.query(
        "SELECT id FROM thread_member WHERE thread_ref = ? ORDER BY id", (thread_ref,))]
    edges = db.query(
        "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge "
        "WHERE thread_ref = ?", (thread_ref,))
    children: dict = {}
    parents: dict = {}
    for ancestor, descendant in edges:
        children.setdefault(int(ancestor), []).append(int(descendant))
        parents.setdefault(int(descendant), []).append(int(ancestor))

    roots = [m for m in members if m not in parents]
    terminals = [m for m in members if m not in children]
    for member in members:
        db.execute(
            "UPDATE thread_member SET is_root = ?, is_terminal = ?, "
            "join_suspected = ? WHERE id = ?",
            (member in roots, member in terminals,
             len(parents.get(member, ())) > 1, member),
        )
    db.execute(
        """
        UPDATE session_thread
           SET fork_suspected = ?, terminal_ambiguous = ?, root_ambiguous = ?,
               member_count = ?, updated_at = ?
         WHERE id = ?
        """,
        (any(len(v) > 1 for v in children.values()),
         len(terminals) > 1, len(roots) > 1, len(members), _stamp(now),
         thread_ref),
    )


def persist(
    db,
    graphs: Sequence[ThreadGraph],
    candidates: Iterable[RelationCandidate],
    member_ids: dict,
    *,
    now: Optional[str] = None,
    evaluated_pairs: Optional[Iterable[tuple[int, int]]] = None,
) -> dict:
    """Attach derived components to threads, then reconcile their edges.

    Identity is decided HERE, not in derivation. A component whose
    members already sit in one or more active threads REUSES them; one
    touching no stored thread allocates.

    Reconciliation is scoped by EVALUATED PAIR, not by member. The
    probe's shortlist selects which THREADS a pass reconciles; within
    each one every readable pair is reclassified (D4c), so the evaluated
    set is the pairs of that touched set — not the probe's own pair
    list, and not every member in the store. Reconciling by member would
    delete edges between two members the pass never compared;
    reconciling by the probe's pairs alone would make a reduced-away
    edge unrecoverable, because nothing would ever look at it again.

    The retirement runs over the evaluated pairs THEMSELVES rather than
    over the emitted graphs: a pair that used to be an edge and is now a
    candidate — or no relation at all — emits no graph, so a
    graph-driven sweep would leave the old edge standing beside its own
    contradiction.
        """
    evaluated = {
        (a, b) if a < b else (b, a) for a, b in (evaluated_pairs or ())
    }
    stats = {"threads": 0, "reused": 0, "allocated": 0, "edges": 0,
             "removed_edges": 0, "candidates": 0, "retired_candidates": 0}
    touched: set = set()

    # 1. attach members and settle identity
    for graph in graphs:
        refs = [member_ids[m] for m in graph.members if m in member_ids]
        if len(refs) < 2:
            continue
        existing: list[int] = []
        for ref in refs:
            row = db.query_one(
                "SELECT thread_ref FROM thread_member WHERE id = ?", (ref,))
            if row and row[0] is not None:
                resolved = resolve_thread(db, int(row[0]))
                if resolved not in existing:
                    existing.append(resolved)
        if existing:
            thread_ref = existing[0]
            for other in existing[1:]:
                thread_ref = connect_threads(db, thread_ref, other, now=now)
            stats["reused"] += 1
        else:
            thread_ref = allocate_thread(db, now=now)
            stats["allocated"] += 1
        stats["threads"] += 1
        for ref in refs:
            db.execute("UPDATE thread_member SET thread_ref = ? WHERE id = ?",
                       (thread_ref, ref))
        touched.add(thread_ref)

    # An edge this pass re-derived IDENTICALLY is refreshed in place
    # rather than deleted and re-inserted: churning the surrogate id on
    # every idempotent run would make "nothing changed" indistinguishable
    # from "everything was rewritten".
    incoming = {
        (member_ids[e.ancestor], member_ids[e.descendant])
        for graph in graphs for e in graph.edges
        if e.ancestor in member_ids and e.descendant in member_ids
    }

    # 2. retire every stored edge whose pair WAS evaluated, wherever it
    #    lives — independent of whether a graph was emitted for it
    if evaluated:
        for edge_id, ancestor, descendant, thread_ref in db.query(
            "SELECT id, ancestor_member_ref, descendant_member_ref, thread_ref "
            "FROM thread_edge"
        ):
            pair = (int(ancestor), int(descendant))
            if pair in incoming:
                continue  # re-derived as-is; the upsert below refreshes it
            key = pair if pair[0] < pair[1] else (pair[1], pair[0])
            if key in evaluated:
                db.execute("DELETE FROM thread_edge WHERE id = ?", (edge_id,))
                stats["removed_edges"] += 1
                touched.add(int(thread_ref))

    # 3. write the edges this pass derived
    for graph in graphs:
        refs = [member_ids[m] for m in graph.members if m in member_ids]
        if len(refs) < 2:
            continue
        row = db.query_one(
            "SELECT thread_ref FROM thread_member WHERE id = ?", (refs[0],))
        thread_ref = resolve_thread(db, int(row[0])) if row and row[0] else None
        if thread_ref is None:
            continue
        for edge in graph.edges:
            a_ref = member_ids.get(edge.ancestor)
            d_ref = member_ids.get(edge.descendant)
            if a_ref is None or d_ref is None:
                continue
            # An edge the retirement sweep did not remove — because this
            # pass did not evaluate its pair — is REFRESHED rather than
            # re-inserted: the pair is unique, so a blind insert would
            # make a re-run of an unevaluated component an error.
            existing = db.query_one(
                "SELECT id FROM thread_edge WHERE ancestor_member_ref = ? "
                "AND descendant_member_ref = ?", (a_ref, d_ref))
            if existing is not None:
                db.execute(
                    """
                    UPDATE thread_edge
                       SET thread_ref = ?, provenance = ?, shared_uuids = ?,
                           ancestor_containment = ?, descendant_containment = ?,
                           ancestor_only = ?, descendant_only = ?, rule_version = ?
                     WHERE id = ?
                    """,
                    (thread_ref, edge.provenance, edge.shared_uuids,
                     edge.ancestor_containment, edge.descendant_containment,
                     edge.ancestor_only, edge.descendant_only, edge.rule_version,
                     existing[0]),
                )
                continue
            db.execute(
                """
                INSERT INTO thread_edge
                    (thread_ref, ancestor_member_ref, descendant_member_ref,
                     provenance, shared_uuids, ancestor_containment,
                     descendant_containment, ancestor_only, descendant_only,
                     rule_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (thread_ref, a_ref, d_ref, edge.provenance, edge.shared_uuids,
                 edge.ancestor_containment, edge.descendant_containment,
                 edge.ancestor_only, edge.descendant_only, edge.rule_version),
            )
            stats["edges"] += 1
        touched.add(thread_ref)

    # 4. reduce the COMBINED edge set. derive() reduced only the
    #    shortlisted relations; the thread also holds retained edges the
    #    pass never re-derived. A new descendant replays its whole
    #    lineage, so an index probe returns every ancestor and the
    #    shortlist yields A->D, B->D and C->D — all three would stand
    #    beside the existing A->B->C, inventing a join on D. Reducing
    #    the union leaves only C->D.
    for thread_ref in sorted(touched):
        stored = {
            (int(edge_id), int(anc), int(desc))
            for edge_id, anc, desc in db.query(
                "SELECT id, ancestor_member_ref, descendant_member_ref "
                "FROM thread_edge WHERE thread_ref = ?", (thread_ref,))
        }
        kept = reduce_pairs({(anc, desc) for _id, anc, desc in stored})
        for edge_id, anc, desc in stored:
            if (anc, desc) not in kept:
                db.execute("DELETE FROM thread_edge WHERE id = ?", (edge_id,))
                stats["removed_edges"] += 1

    # 5. flags from the FINAL persisted edge set, retained evidence included
    for thread_ref in sorted(touched):
        _recompute_flags(db, thread_ref, now=now)

    candidate_stats = store_candidates(
        db, candidates, member_ids, evaluated_pairs=evaluated, now=now)
    stats["candidates"] = candidate_stats["written"]
    stats["retired_candidates"] = candidate_stats["retired"]
    db.commit()
    return stats


def _member_rows_for_threads(db, thread_refs: Iterable[int]) -> list[tuple]:
    rows: list[tuple] = []
    for ref in sorted(set(thread_refs)):
        rows.extend(db.query(
            "SELECT id, copilot, source_key, native_session_id, session_ref "
            "FROM thread_member WHERE thread_ref = ? ORDER BY id", (ref,)))
    return rows


def _discover_related(db, sources, loader, exclude: set) -> list[int]:
    """Registered members sharing a uuid with any of `sources`.

    The correctness-first default. It re-reads every registered source,
    which is proportional to the members already stored — acceptable
    because it is bounded and because a WRONG thread is far worse than a
    slow pass. Task 3 replaces it with the turn-uuid index probe, which
    narrows the same question to the sessions that actually collide;
    callers that have already done that discovery pass
    `related_members` and skip this entirely.
    """
    wanted: set[str] = set()
    for source in sources:
        wanted |= source.uuids
    if not wanted:
        return []
    found: list[int] = []
    for ref, source_key in db.query(
        "SELECT id, source_key FROM thread_member ORDER BY id"
    ):
        if ref in exclude:
            continue
        loaded = loader(source_key)
        if loaded and (wanted & set(loaded)):
            found.append(int(ref))
    return found


def load_source_uuids(source_key: str) -> Optional[frozenset[str]]:
    """Read one source, distinguishing UNREADABLE from EMPTY.

    None when the transcript cannot be read; a possibly-empty set when
    it can. The difference is load-bearing: a readable transcript
    carrying no uuid-bearing records is available and simply contributes
    nothing, while an unreadable one is a coverage gap whose existing
    lineage must be preserved. Inferring availability from uuid
    cardinality would conflate the two and quietly delete real edges.
    """
    return uuids_from_transcript(Path(source_key))


def reconcile(
    db,
    sources: Sequence[SourceRef],
    *,
    session_refs: Optional[dict] = None,
    candidate_pairs: Optional[Iterable] = None,
    related_members: Optional[Iterable[int]] = None,
    unreadable_sources: Optional[Iterable] = None,
    uuid_loader=None,
    now: Optional[str] = None,
) -> dict:
    """Register `sources`, EXPAND to their threads, re-derive, persist.

    The expansion is the point. An incremental pass sees one new source
    and whatever the probe returned, which is a partial view of a
    thread; reconciling that destructively would erase lineage it never
    looked at. So every member of every thread these sources resolve
    into — and of every thread their related members sit in, since a
    brand-new bridging source belongs to nothing yet — is pulled back in
    and the whole component is re-derived.

    `uuid_loader` returns None for an UNREADABLE source and a set for a
    readable one. An unreadable member is recorded unavailable and kept
    out of the evaluated set, so its edges survive.

    `unreadable_sources` names identities among `sources` that the
    CALLER could not read. Availability travels as its own fact rather
    than being inferred from an empty uuid set: a direct source that
    became unreadable between the adapter's load and detection would
    otherwise arrive as an authoritative empty set, and every one of its
    pairs would be "evaluated" against nothing — retiring its real edges
    while still claiming it is available.
    """
    loader = uuid_loader or load_source_uuids
    session_refs = session_refs or {}
    related_members = None if related_members is None else list(related_members)

    by_identity: dict = {}
    member_ids: dict = {}
    readable: set = set()

    def adopt(ref: int, copilot: str, source_key: str, native_id: str) -> None:
        """One path for every member pulled in, related or expanded."""
        identity = (copilot, source_key)
        if identity in by_identity:
            return
        loaded = loader(source_key)
        available = loaded is not None
        by_identity[identity] = SourceRef(
            copilot, source_key, native_id, frozenset(loaded or ()))
        member_ids[identity] = ref
        if available:
            readable.add(ref)
        db.execute("UPDATE thread_member SET source_available = ? WHERE id = ?",
                   (available, ref))

    unreadable = set(unreadable_sources or ())
    for source in sources:
        available = source.identity not in unreadable
        ref = register_source(
            db, source, session_ref=session_refs.get(source.identity),
            source_available=available)
        member_ids[source.identity] = ref
        by_identity[source.identity] = source
        if available:
            readable.add(ref)

    if related_members is None:
        related_members = _discover_related(
            db, sources, loader, set(member_ids.values()))

    seeds = list(member_ids.values()) + list(related_members)
    thread_refs = set()
    for ref in seeds:
        row = db.query_one("SELECT thread_ref FROM thread_member WHERE id = ?", (ref,))
        if row and row[0] is not None:
            thread_refs.add(resolve_thread(db, int(row[0])))

    for ref in related_members:
        row = db.query_one(
            "SELECT id, copilot, source_key, native_session_id "
            "FROM thread_member WHERE id = ?", (ref,))
        if row is not None:
            adopt(int(row[0]), row[1], row[2], row[3])

    for ref, copilot, source_key, native_id, _session_ref in _member_rows_for_threads(
            db, thread_refs):
        adopt(int(ref), copilot, source_key, native_id)

    ordered = [by_identity[i] for i in sorted(by_identity)]

    # The probe's shortlist decides WHICH THREADS to pull in. Once they
    # are pulled in, EVERY readable pair inside them is reclassified.
    #
    # That is not belt-and-braces, it is required for recovery.
    # Reduction is lossy: an A->C edge is deleted the moment a B arrives
    # to make A->B->C. If a later pass then re-evaluated only B<->C and
    # found it below the gate, A->C would be gone and C would be
    # orphaned — its evidence permanently erased by a reduction two
    # passes earlier. Reclassifying the whole touched thread is what
    # lets A->C reappear.
    #
    # Cost is quadratic in THREAD size, not in store size, and a thread
    # is a handful of transcripts.
    readable_sources = [s for s in ordered if member_ids[s.identity] in readable]
    full_pairs = [
        (a.identity, b.identity, C.THREAD_PROVENANCE_UUID_CONTAINMENT)
        for i, a in enumerate(readable_sources)
        for b in readable_sources[i + 1:]
    ]
    # `candidate_pairs` is an Iterable, so a generator from the probe
    # would be drained by `derive` and leave reconciliation with zero
    # evaluated pairs — and therefore retire nothing, silently. It is
    # materialized ONCE here and overlaid on the full set, where the
    # declared precedence keeps a `native_group` provenance the probe
    # supplied.
    supplied = [] if candidate_pairs is None else list(candidate_pairs)

    # "These two transcripts came from one adapter group" is a DURABLE
    # fact, and it is derived from the MEMBERS — two members sharing a
    # (copilot, native_session_id) were grouped by the adapter.
    #
    # It must not be read back from a stored native_group edge. Reduction
    # deliberately deletes a redundant edge, so a same-group A->C that a
    # cross-session B displaced would have no edge left to seed from; if
    # B were later invalidated, the restored A->C would come back
    # mislabelled as uuid_containment. The members always know.
    groups: dict = {}
    for identity in member_ids:
        row = db.query_one(
            "SELECT copilot, native_session_id FROM thread_member WHERE id = ?",
            (member_ids[identity],))
        if row is not None:
            groups.setdefault((row[0], row[1]), []).append(identity)
    for members in groups.values():
        for i, left in enumerate(sorted(members)):
            for right in sorted(members)[i + 1:]:
                supplied.append(
                    (left, right, C.THREAD_PROVENANCE_NATIVE_GROUP))

    shortlist = pair_shortlist(ordered, full_pairs + supplied)
    graphs, candidates = derive(ordered, candidate_pairs=shortlist)

    # EXACTLY the pairs this pass classified — and only where both
    # members were readable, since a verdict against an unreadable
    # source says nothing.
    evaluated: list[tuple[int, int]] = []
    for left, right, _provenance in shortlist:
        a, b = member_ids.get(left), member_ids.get(right)
        if a is None or b is None:
            continue
        if a in readable and b in readable:
            evaluated.append((a, b))

    stats = persist(db, graphs, candidates, member_ids, now=now,
                    evaluated_pairs=evaluated)
    stats["expanded_members"] = len(member_ids) - len(sources)
    stats["unavailable_sources"] = len(member_ids) - len(readable)
    stats["evaluated_pairs"] = len(evaluated)
    return stats


def probe_related_members(db, uuids: Iterable[str], *, batch: int = 400) -> list[int]:
    """Registered members whose session carries any of these turn uuids.

    THE index probe (FR-11). It asks `copilot_turn (uuid)` which stored
    sessions collide with this one, and the members of those sessions
    select the threads a pass reconciles. Measured on 163 transcripts it
    returns nothing at all for 160 of them, which is what makes ingest
    detection cost proportional to real collisions rather than to store
    size.

    It selects the touched set; it does not decide which pairs are
    judged. Every readable pair inside the threads it reaches is
    reclassified (D4c), because reduction is lossy and a pair-scoped
    pass could never restore an edge it had displaced.
    """
    wanted = [u for u in uuids if u]
    if not wanted:
        return []
    found: set[int] = set()
    for start in range(0, len(wanted), batch):
        chunk = wanted[start:start + batch]
        placeholders = ", ".join("?" for _ in chunk)
        rows = db.query(
            f"""
            SELECT DISTINCT m.id
              FROM copilot_turn t
              JOIN thread_member m ON m.session_ref = t.session_id
             WHERE t.uuid IN ({placeholders})
            """,
            tuple(chunk),
        )
        found.update(int(r[0]) for r in rows)
    return sorted(found)


def detect_for_session(
    db,
    *,
    copilot: str,
    native_session_id: str,
    session_ref: int,
    source_files: Sequence,
    uuid_loader=None,
    now: Optional[str] = None,
) -> dict:
    """Thread detection for one just-ingested session.

    A session may have SEVERAL source transcripts — the adapter groups a
    resume chain under one sessionId — and each is its own member, which
    is the whole of Job A: the grouping knows the chain and then throws
    it away. They are registered first so the probe can see them, then
    reconciled together.
    """
    loader = uuid_loader or load_source_uuids
    sources: list[SourceRef] = []
    unreadable: list = []
    for path in source_files:
        key = str(path)
        loaded = loader(key)
        source = SourceRef(copilot, key, native_session_id,
                           frozenset(loaded or ()))
        sources.append(source)
        if loaded is None:
            # A source the adapter listed but that cannot be read NOW —
            # pruned between load and detection. Carried as a fact, not
            # inferred later from its empty uuid set.
            unreadable.append(source.identity)
    if not sources:
        return {"threads": 0, "evaluated_pairs": 0}

    own = {s.identity for s in sources}
    combined: set[str] = set()
    for source in sources:
        combined |= source.uuids

    # Job A's own evidence: every pair of THIS session's transcripts is
    # known to have come from one adapter group. Supplying them as
    # `native_group` is the only way that fact reaches the stored edge —
    # the generated full-pair set defaults to `uuid_containment`, and
    # the declared precedence then keeps the stronger label. It still
    # authorizes nothing: the containment rule decides direction, and a
    # same-group pair that fails it produces no edge.
    native_pairs = [
        (a.identity, b.identity, C.THREAD_PROVENANCE_NATIVE_GROUP)
        for i, a in enumerate(sources)
        for b in sources[i + 1:]
    ]

    related: list[int] = []
    for ref in probe_related_members(db, combined):
        row = db.query_one(
            "SELECT copilot, source_key FROM thread_member WHERE id = ?", (ref,))
        if row is None or (row[0], row[1]) not in own:
            related.append(ref)
    return reconcile(
        db, sources,
        session_refs={s.identity: session_ref for s in sources},
        related_members=related,
        unreadable_sources=unreadable,
        candidate_pairs=native_pairs,
        uuid_loader=loader,
        now=now,
    )


def known_sources(db) -> list[tuple]:
    """Every source the store can still NAME, with its session.

    Two registries hold that set: `ingest_state.source_file`, written
    when a transcript was ingested, and `thread_member.source_key`, for
    a source lineage already knows about. Their union is the backfill's
    whole reach.

    A source deleted before its path ever reached either table is
    UNDISCOVERABLE — nothing records that it existed — which is why
    coverage is reported as a fraction of known sources and never of
    everything that ever was.
    """
    rows: dict = {}
    for copilot, source_file, session_id in db.query(
        "SELECT copilot, source_file, last_session_id FROM ingest_state"
    ):
        rows[(copilot, source_file)] = session_id
    for copilot, source_key, native_session_id in db.query(
        "SELECT copilot, source_key, native_session_id FROM thread_member"
    ):
        rows.setdefault((copilot, source_key), native_session_id)

    out: list[tuple] = []
    for (copilot, source_key), session_id in sorted(rows.items()):
        ref = None
        if session_id:
            found = db.query_one(
                "SELECT id FROM copilot_session WHERE copilot = ? AND session_id = ?",
                (copilot, session_id))
            ref = int(found[0]) if found else None
        out.append((copilot, source_key, session_id or "", ref))
    return out


def backfill(db, *, uuid_loader=None, now: Optional[str] = None) -> dict:
    """Rebuild lineage for sources already in the store.

    The store cannot reconstruct Job A on its own: the adapter's
    grouping discarded which transcript each turn came from, so the
    backfill re-reads the SOURCES. Its reach is exactly what the store
    can still name (`known_sources`); anything deleted before it was
    ever recorded is undiscoverable and simply absent from the count.

    Idempotent. A known source missing on disk is recorded
    `source_available = false` and counted as unavailable coverage; no
    lineage is guessed for it.
    """
    loader = uuid_loader or load_source_uuids
    sources: list[SourceRef] = []
    unreadable: list = []
    session_refs: dict = {}

    for copilot, source_key, native_session_id, session_ref in known_sources(db):
        loaded = loader(source_key)
        source = SourceRef(copilot, source_key, native_session_id,
                           frozenset(loaded or ()))
        sources.append(source)
        if loaded is None:
            unreadable.append(source.identity)
        if session_ref is not None:
            session_refs[source.identity] = session_ref

    if not sources:
        return {"known_sources": 0, "available": 0, "unavailable": 0,
                "threads": 0, "edges": 0, "candidates": 0,
                "coverage_basis": "known_sources"}

    stats = reconcile(
        db, sources,
        session_refs=session_refs,
        related_members=[],          # the whole known set is already here
        unreadable_sources=unreadable,
        uuid_loader=loader,
        now=now,
    )
    stats["known_sources"] = len(sources)
    stats["unavailable"] = len(unreadable)
    stats["available"] = len(sources) - len(unreadable)
    # NAMED so a reader cannot mistake it for total coverage: sources
    # that vanished before they were ever recorded are not in the
    # denominator, because nothing knows they existed.
    stats["coverage_basis"] = "known_sources"
    return stats


#: The turn columns a thread figure ADDS UP. Not the whole output
#: contract — that is THREAD_FIGURE_FIELDS below — just the columns
#: summed straight from `copilot_turn`.
#:
#: Every one exists at TURN grain, which is what lets it be aggregated
#: over distinct turn uuids. A session-level figure —
#: `copilot_session`'s turn_count, tool_call_count, error_count,
#: duration_seconds — is deliberately absent: summing those across
#: members and calling the result deduplicated is the exact error this
#: model exists to prevent, and it would be wrong by up to the share a
#: descendant replays (90% in the measured corpus).
THREAD_ADDITIVE_TURN_COLUMNS = {
    "cost_usd": "cost_usd",
    "tokens_input": "tokens_input",
    "tokens_output": "tokens_output",
    "cache_read_tokens": "cache_read_tokens",
    "cache_write_tokens": "cache_write_tokens",
}

#: The COMPLETE set of keys `thread_figures` returns. Declared so the
#: output contract is one list a reader can check, rather than something
#: to be inferred from the implementation.
THREAD_FIGURE_FIELDS = (
    "turns",
    "distinct_turn_uuids",
    "tool_calls",
    "errors",
    "priced_turns",
    "priceable_turns",
) + tuple(THREAD_ADDITIVE_TURN_COLUMNS)


def _thread_distinct_turn_ids_sql() -> str:
    """One turn row per distinct uuid across the thread's members.

    `MIN(id)` makes the choice deterministic: the same uuid is a
    separate row in every session that replayed it, and picking a
    different copy per run would make an idempotent pass report moving
    figures.
    """
    return """
        SELECT MIN(t.id)
          FROM copilot_turn t
          JOIN thread_member m ON m.session_ref = t.session_id
         WHERE m.thread_ref = ? AND t.uuid IS NOT NULL
         GROUP BY t.uuid
    """


def thread_figures(db, thread_ref: int) -> dict:
    """Every figure a thread may report, over DISTINCT turn uuids.

    Never a sum of member sessions' stored figures. A descendant carries
    up to 90% of its ancestor's turns, so summing is wrong by up to that
    much — which is why this reads turns and deduplicates by uuid rather
    than adding up `copilot_session` columns.

    A turn whose uuid is NULL cannot be counted distinctly, so it is
    excluded from every thread figure. It still counts once under its
    own session, where no deduplication is needed.

    `cost_usd` is None when no selected turn is priced, NEVER 0.0:
    unknown cost is not free, and a zero would read as a thread that
    cost nothing. `priced_turns` and `priceable_turns` carry the
    coverage beside it, using the same eligibility the pricer uses — a
    turn is priceable when it names a model, because a turn with no
    model was never a candidate for a price.
    """
    inner = _thread_distinct_turn_ids_sql()
    columns = ", ".join(
        f"SUM(t.{source})" for source in THREAD_ADDITIVE_TURN_COLUMNS.values()
    )
    row = db.query_one(
        f"SELECT COUNT(*), {columns}, "
        f"SUM(CASE WHEN t.cost_usd IS NOT NULL THEN 1 ELSE 0 END), "
        f"SUM(CASE WHEN t.model IS NOT NULL AND t.model <> '' THEN 1 ELSE 0 END) "
        f"FROM copilot_turn t WHERE t.id IN ({inner})",
        (thread_ref,),
    )
    figures: dict = {"turns": int(row[0]) if row and row[0] is not None else 0}
    for index, name in enumerate(THREAD_ADDITIVE_TURN_COLUMNS, start=1):
        value = row[index] if row else None
        if value is None:
            # Nothing selected carried this column. For cost that is the
            # load-bearing case: NULL means "not known", and collapsing
            # it to 0 would claim the work was free.
            figures[name] = None
            continue
        figures[name] = float(value) if name == "cost_usd" else int(value)
    tail = len(THREAD_ADDITIVE_TURN_COLUMNS) + 1
    figures["priced_turns"] = int(row[tail]) if row and row[tail] else 0
    figures["priceable_turns"] = int(row[tail + 1]) if row and row[tail + 1] else 0

    tool_calls = db.query_one(
        f"SELECT COUNT(*) FROM copilot_tool_call tc "
        f"WHERE tc.turn_id IN ({inner})", (thread_ref,))
    figures["tool_calls"] = int(tool_calls[0]) if tool_calls and tool_calls[0] else 0

    errors = db.query_one(
        f"SELECT COUNT(*) FROM copilot_tool_result tr "
        f"JOIN copilot_tool_call tc ON tc.id = tr.tool_call_id "
        f"WHERE tr.is_error = ? AND tc.turn_id IN ({inner})",
        (True, thread_ref))
    figures["errors"] = int(errors[0]) if errors and errors[0] else 0

    figures["distinct_turn_uuids"] = figures["turns"]
    return figures


def threads_for_session(db, session_ref: int) -> list[int]:
    """Every ACTIVE thread this session's members resolve into.

    Usually one. It is not guaranteed to be one, and no constraint makes
    it so: `thread_member` is source-grained, and nothing stops two
    transcripts of one grouped session from belonging to different
    lineages. Returning a list keeps that visible; picking the first row
    would answer an ambiguous question with an arbitrary thread.
    """
    found: list[int] = []
    for (ref,) in db.query(
        "SELECT DISTINCT thread_ref FROM thread_member "
        "WHERE session_ref = ? AND thread_ref IS NOT NULL", (session_ref,)
    ):
        resolved = resolve_thread(db, int(ref))
        if resolved not in found:
            found.append(resolved)
    return sorted(found)


def thread_figures_for_session(db, session_ref: int) -> Optional[dict]:
    """The figures of the thread this session belongs to.

    None when it belongs to none. When its members resolve into MORE
    than one active thread the result says so explicitly — `ambiguous`
    with every `thread_refs` — rather than reporting one thread's
    figures as if they were the session's.
    """
    refs = threads_for_session(db, session_ref)
    if not refs:
        return None
    if len(refs) > 1:
        return {"ambiguous": True, "thread_refs": refs}
    figures = thread_figures(db, refs[0])
    figures["ambiguous"] = False
    figures["thread_refs"] = refs
    return figures


def lineage_support(copilot: str) -> str:
    """Whether this source CAN express lineage at all.

    Derived from the adapter's declared capability, never from whether a
    link happened to be found. The distinction is the whole point: a
    `claude-code` session with no thread is "no ancestor found", an
    `aider` session is "cannot express lineage", and rendering them
    alike would turn an unknowable into a negative result — the same
    error A5 forbade when it pinned `unknown` never becoming zero.

    An unregistered copilot is `unsupported`: nothing declares that it
    exposes a per-turn identity, and assuming otherwise would invent a
    capability.
    """
    from ._register import register_all
    from .registry import UnknownAdapterError, get_adapter

    # UNCONDITIONALLY, because it is idempotent and because "the
    # registry is non-empty" does not mean "the built-ins are in it":
    # one custom adapter registered first would skip this and make
    # Claude Code report unsupported — a capability answer must not
    # depend on who happened to register what.
    register_all()
    try:
        adapter = get_adapter(copilot)
    except UnknownAdapterError:
        # The ONLY failure that is a real answer. A registration or
        # constructor defect must surface as itself, not be flattened
        # into "this source cannot express lineage".
        return C.LINEAGE_SUPPORT_UNSUPPORTED
    # Accessed directly: the protocol declares it, so an adapter that
    # omits it is a defect and should raise rather than default.
    return (
        C.LINEAGE_SUPPORT_NATIVE if adapter.exposes_turn_identity
        else C.LINEAGE_SUPPORT_UNSUPPORTED
    )


class SessionNotFound(LookupError):
    """No such session. Distinct from a session that cannot be threaded.

    Typed so a read surface can answer 404 instead of describing a row
    that does not exist as an unsupported source.
    """


def session_lineage(db, session_ref: int) -> dict:
    """A session's lineage answer, support stated before any finding.

    `lineage_support` is read first and independently, so a caller
    cannot reach "no thread" without also being told whether a thread
    was ever possible.

    Raises `SessionNotFound` when the session does not exist: missing
    data must not masquerade as a real source that happens to be
    unsupported.
    """
    row = db.query_one(
        "SELECT copilot FROM copilot_session WHERE id = ?", (session_ref,))
    if row is None:
        raise SessionNotFound(f"no session with id {session_ref}")
    copilot = row[0]
    support = lineage_support(copilot)
    refs = threads_for_session(db, session_ref) if support == C.LINEAGE_SUPPORT_NATIVE \
        else []
    return {
        "copilot": copilot,
        "lineage_support": support,
        "thread_refs": refs,
        "ambiguous": len(refs) > 1,
        # Said explicitly so a blank column can never be read as a
        # finding: there is no thread, and for an unsupported source
        # there could not have been one.
        "no_ancestor_found": support == C.LINEAGE_SUPPORT_NATIVE and not refs,
    }


def thread_view(db, session_ref: int) -> dict:
    """A session's lineage, shaped as a TREE over the edges.

    Never a list. Once forks are retained, "members in order" is a
    promise the data cannot keep — the order is partial, and a flat list
    with a flag beside it invites exactly the reading the flag denies.
    So comparable members nest under their ancestor, and two
    incomparable descendants appear as SIBLINGS with no index, ordinal
    or "next" between them.

    A member with several incomparable ancestors is a join: it is
    rendered ONCE, under its first ancestor in the tree, and listed
    separately in `joins` with all of its ancestors as evidence.
    Duplicating it under each ancestor would imply two independent
    descendants where there is one.

    Raises `SessionNotFound` when the session does not exist.
    """
    lineage = session_lineage(db, session_ref)

    # SCOPE: this session's own members, plus every member of every
    # thread it reaches. Both the candidate list and the coverage
    # fraction are computed over it, and both live at the TOP LEVEL —
    # a relation candidate creates no edge and allocates no thread, so
    # the cases where candidates matter most are exactly the ones where
    # `thread` is null.
    scope: set = {
        int(r[0]) for r in db.query(
            "SELECT id FROM thread_member WHERE session_ref = ?", (session_ref,))
    }
    for reached in lineage["thread_refs"]:
        scope |= {
            int(r[0]) for r in db.query(
                "SELECT id FROM thread_member WHERE thread_ref = ?", (reached,))
        }

    # KNOWN sources are the union of BOTH registries (FR-13), not just
    # the members. A pre-A6 session has ingest_state rows and no members
    # at all: counting only members would report zero known sources and
    # then conclude "no ancestor found" for lineage that was never
    # assessed. An unassessed source is not a negative result.
    assessed_keys = {
        (r[0], r[1]) for r in db.query(
            "SELECT copilot, source_key FROM thread_member WHERE id IN (%s)"
            % (", ".join("?" for _ in scope) or "NULL"), tuple(sorted(scope)))
    } if scope else set()
    # EVERY session the displayed thread touches, not just the one
    # asked about: a related session can carry a pre-A6 source that
    # ingest_state names and no member row covers, and omitting it would
    # call the whole thread `complete` while part of what is shown was
    # never assessed.
    scoped_sessions = {session_ref}
    if scope:
        scoped_sessions |= {
            int(r[0]) for r in db.query(
                "SELECT DISTINCT session_ref FROM thread_member WHERE id IN (%s) "
                "AND session_ref IS NOT NULL"
                % (", ".join("?" for _ in scope)), tuple(sorted(scope)))
        }
    registry_keys = {
        (r[0], r[1]) for r in db.query(
            "SELECT i.copilot, i.source_file FROM ingest_state i "
            "JOIN copilot_session s ON s.session_id = i.last_session_id "
            "AND s.copilot = i.copilot WHERE s.id IN (%s)"
            % (", ".join("?" for _ in scoped_sessions)),
            tuple(sorted(scoped_sessions)))
    }
    known_keys = assessed_keys | registry_keys

    unavailable = sum(
        1 for r in db.query(
            "SELECT source_available FROM thread_member WHERE id IN (%s)"
            % (", ".join("?" for _ in scope) or "NULL"), tuple(sorted(scope)))
        if not r[0]
    ) if scope else 0

    candidates: list = []
    if scope:
        placeholders = ", ".join("?" for _ in scope)
        ordered_scope = sorted(scope)
        candidates = [
            {
                "member_a": int(c[0]), "member_b": int(c[1]),
                "shared_uuids": int(c[2]), "containment_a": c[3],
                "containment_b": c[4], "a_only": int(c[5]), "b_only": int(c[6]),
                "candidate_kind": c[7], "rule_version": c[8],
            }
            # BOTH endpoints: the pair is stored in canonical row-id
            # order, so the attached member can be either side.
            for c in db.query(
                "SELECT member_a_ref, member_b_ref, shared_uuids, containment_a, "
                "containment_b, a_only, b_only, candidate_kind, rule_version "
                "FROM thread_relation_candidate "
                f"WHERE member_a_ref IN ({placeholders}) "
                f"   OR member_b_ref IN ({placeholders}) "
                "ORDER BY member_a_ref, member_b_ref",
                tuple(ordered_scope) + tuple(ordered_scope))
        ]

    known = len(known_keys)
    assessed = len(assessed_keys)
    #: `complete`   — every known source was assessed and readable
    #: `unassessed` — a known source has no member row, so NO COMPLETED
    #:                ASSESSMENT IS STORED. Usually a pre-A6 session
    #:                awaiting a backfill, but the same durable state
    #:                results when a pass began and was rolled back
    #:                before it committed. The distinction A5 drew
    #:                applies: the claim is about what is recoverable
    #:                from the store, not about what was attempted.
    #: `incomplete` — assessed, but a source could not be read
    if known and assessed >= known and unavailable == 0:
        assessment = "complete"
    elif assessed < known:
        assessment = "unassessed"
    elif unavailable:
        assessment = "incomplete"
    else:
        assessment = "unassessed"

    view: dict = {
        "session_ref": session_ref,
        "copilot": lineage["copilot"],
        "lineage_support": lineage["lineage_support"],
        # ONLY after native lineage was fully assessable and nothing
        # was found. An unassessed or partly unreadable history cannot
        # prove an absence, so it reports False beside `assessment`
        # rather than an answer it has not earned.
        "no_ancestor_found": (
            lineage["no_ancestor_found"] and assessment == "complete"),
        "assessment": assessment,
        "ambiguous": lineage["ambiguous"],
        "thread_refs": lineage["thread_refs"],
        # An explicit fraction, not a label: known is the DENOMINATOR —
        # this session's members plus those of every thread it reaches —
        # and it never includes a source deleted before the store ever
        # named it, because nothing records that such a source existed.
        "coverage_basis": "known_sources",
        "coverage_scope": "session members and every member of the threads it reaches",
        "sources_known": known,
        "sources_assessed": assessed,
        "sources_available": assessed - unavailable,
        "sources_unavailable": unavailable,
        "relation_candidates": candidates,
        "thread": None,
    }
    if lineage["ambiguous"] or not lineage["thread_refs"]:
        return view

    thread_ref = lineage["thread_refs"][0]
    row = db.query_one(
        "SELECT thread_id, status, fork_suspected, terminal_ambiguous, "
        "root_ambiguous, member_count FROM session_thread WHERE id = ?",
        (thread_ref,))
    members = {
        int(r[0]): {
            "member_ref": int(r[0]),
            "source_key": r[1],
            "native_session_id": r[2],
            "session_ref": r[3],
            "source_available": bool(r[4]),
            "turn_uuid_count": int(r[5]),
            "is_root": bool(r[6]),
            "is_terminal": bool(r[7]),
            "join_suspected": bool(r[8]),
            "children": [],
        }
        for r in db.query(
            "SELECT id, source_key, native_session_id, session_ref, "
            "source_available, turn_uuid_count, is_root, is_terminal, "
            "join_suspected FROM thread_member WHERE thread_ref = ? ORDER BY id",
            (thread_ref,))
    }
    edges = [
        {
            "ancestor": int(e[0]), "descendant": int(e[1]), "provenance": e[2],
            "shared_uuids": int(e[3]), "ancestor_containment": e[4],
            "descendant_containment": e[5], "ancestor_only": int(e[6]),
            "descendant_only": int(e[7]), "rule_version": e[8],
        }
        for e in db.query(
            "SELECT ancestor_member_ref, descendant_member_ref, provenance, "
            "shared_uuids, ancestor_containment, descendant_containment, "
            "ancestor_only, descendant_only, rule_version "
            "FROM thread_edge WHERE thread_ref = ? "
            "ORDER BY ancestor_member_ref, descendant_member_ref", (thread_ref,))
    ]

    placed: set = set()
    for edge in edges:
        parent, child = members.get(edge["ancestor"]), members.get(edge["descendant"])
        if parent is None or child is None or edge["descendant"] in placed:
            continue
        parent["children"].append(child)
        placed.add(edge["descendant"])

    roots = [m for ref, m in members.items() if ref not in placed]
    parents_of: dict = {}
    for edge in edges:
        parents_of.setdefault(edge["descendant"], []).append(edge["ancestor"])

    view["thread"] = {
        "thread_id": row[0] if row else None,
        "status": row[1] if row else None,
        "fork_suspected": bool(row[2]) if row else False,
        "terminal_ambiguous": bool(row[3]) if row else False,
        "root_ambiguous": bool(row[4]) if row else False,
        "member_count": int(row[5]) if row else 0,
        # a TREE, and more than one root when the component has one
        "roots": roots,
        "edges": edges,
        # shown APART from the tree, so the joined member is never drawn
        # twice and never implies two independent descendants
        "joins": [
            {"member_ref": ref, "ancestors": sorted(refs)}
            for ref, refs in sorted(parents_of.items()) if len(refs) > 1
        ],
        "figures": thread_figures(db, thread_ref),
    }
    return view
