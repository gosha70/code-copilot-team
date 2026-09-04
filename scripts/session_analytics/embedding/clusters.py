# session_analytics.embedding.clusters — pure component grouping
# (#289 T1; FR-B, FR-C).
#
# WHAT A CLUSTER IS, and what it is NOT. A cluster is a connected
# component of the UNDIRECTED VIEW of the stored SIMILAR_TO edge set,
# restricted to components with two or more members. The `similar`
# pass writes directed per-source top-K edges; two sessions are
# adjacent here iff at least one directed edge exists between them in
# either direction (scores are symmetric, top-K membership is not).
#
# The consequence is deliberate, not accidental: a component links A
# and C through B even when score(A, C) is below the threshold, or
# when A and C share no edge at all. A cluster is a TRANSITIVE
# DISCOVERY GROUPING, never a pairwise-similarity guarantee, and no
# surface built on this module may imply all-pairs similarity.
#
# GROUPING IS UNDIRECTED; THE COUNT IS DIRECTED. `directed_edge_count`
# is the number of stored DIRECTED edge records internal to a
# component — A->B and B->A count as TWO though they form one
# adjacency; a lone A->B counts as one. The two numbers diverge on
# every reciprocal pair, which is exactly why the choice is pinned
# here rather than left to a caller.
#
# Everything here is pure: no kuzu, no store, no I/O, no config, no
# RNG, no clock. Iteration is over sorted keys throughout, so FR-C
# determinism is by construction rather than by assertion — the same
# edge set in any order yields byte-identical output.
#
# This module does NOT compute the unclustered count. That count is
# FR-A's SECOND provenance (the current graph node inventory), it is
# not derivable from edges alone, and it belongs to the reader.

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

#: A stored directed edge record, as (source key, destination key).
#: Scores are deliberately absent: the threshold that admitted an edge
#: was applied by the producer, and clustering re-decides nothing.
DirectedEdge = tuple[str, str]

#: Below this member count a component is not a cluster (D4).
#: Edgeless sessions are "unclustered" — the reader's report line —
#: never padded into singleton clusters here.
MIN_CLUSTER_SIZE = 2


@dataclass(frozen=True)
class Cluster:
    """One connected component of the undirected edge view.

    ``identity`` is the lexicographically smallest member key (FR-C):
    stable across runs on the same edge set, with no RNG, no
    iteration-order dependence and no timestamp. ``members`` is sorted
    by key. ``directed_edge_count`` counts stored DIRECTED records
    internal to the component, so a reciprocal pair contributes two.
    """

    identity: str
    members: tuple[str, ...]
    directed_edge_count: int

    @property
    def size(self) -> int:
        return len(self.members)

    def as_dict(self) -> dict:
        """A plain, order-stable mapping for report rendering."""
        return {
            "identity": self.identity,
            "size": self.size,
            "members": list(self.members),
            "directed_edge_count": self.directed_edge_count,
        }


def _endpoints(edges: Iterable[DirectedEdge]) -> tuple[list[DirectedEdge], list[str]]:
    """Materialize the edge records and their sorted distinct keys."""
    records = [(str(src), str(dst)) for src, dst in edges]
    keys = set()
    for src, dst in records:
        keys.add(src)
        keys.add(dst)
    return records, sorted(keys)


def find_clusters(edges: Iterable[DirectedEdge]) -> list[Cluster]:
    """Group ``edges`` into clusters (FR-B), deterministically (FR-C).

    Components are found over the UNDIRECTED view; each returned
    cluster carries the DIRECTED record count internal to it. Only
    components with ``MIN_CLUSTER_SIZE`` or more members are returned:
    a session whose only stored edge is a self-loop, like a session
    with no edge at all, is not a cluster of one.

    Clusters are ordered by descending size, then ascending identity —
    a total order, because identities are distinct member keys. The
    same edge set in any input order yields an identical list.
    """
    records, keys = _endpoints(edges)

    # Union-find over sorted keys. The smaller key always wins the
    # union, so roots never depend on input order; identity is
    # recomputed as the component minimum regardless, making the
    # result independent of the root choice either way.
    parent: dict[str, str] = {k: k for k in keys}

    def find(k: str) -> str:
        root = k
        while parent[root] != root:
            root = parent[root]
        while parent[k] != root:  # path compression, iterative
            parent[k], k = root, parent[k]
        return root

    for src, dst in records:
        a, b = find(src), find(dst)
        if a != b:
            lo, hi = (a, b) if a < b else (b, a)
            parent[hi] = lo

    members_by_root: dict[str, list[str]] = {}
    for key in keys:  # sorted, so member lists are sorted by construction
        members_by_root.setdefault(find(key), []).append(key)

    # Every edge's endpoints share a component, so counting by source
    # is exact and needs no membership test on the destination.
    edges_by_root: dict[str, int] = {}
    for src, _dst in records:
        root = find(src)
        edges_by_root[root] = edges_by_root.get(root, 0) + 1

    clusters = [
        Cluster(
            identity=members[0],
            members=tuple(members),
            directed_edge_count=edges_by_root.get(root, 0),
        )
        for root, members in members_by_root.items()
        if len(members) >= MIN_CLUSTER_SIZE
    ]
    clusters.sort(key=lambda c: (-c.size, c.identity))
    return clusters
