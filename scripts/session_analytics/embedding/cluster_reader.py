# session_analytics.embedding.cluster_reader — the read-only graph
# snapshot seam and the cluster report (#289 T2; FR-A, FR-D, FR-E).
#
# TWO INPUTS, TWO PROVENANCES — the distinction this module exists to
# keep honest:
#
#   membership  <- the SIMILAR_TO edges CURRENTLY stored in the graph
#   inventory   <- the CURRENT Session node inventory
#
# They move independently. An incremental `graph` run adds nodes
# without touching edges, so the unclustered count can change while
# every cluster stays byte-identical. The report therefore labels both
# bases separately and never claims the whole answer is frozen to one
# historical `similar` pass. It cannot make that claim honestly: the
# store attests only its present contents, and `graph --rebuild` drops
# and recreates the rel tables, so an empty edge set can mean a
# rebuild as easily as a pass that found nothing.
#
# WHAT THE REPORT MAY AND MAY NOT CLAIM (FR-A). It MAY say members are
# connected through stored edges that the similarity producer created
# under its compatibility rule — a production-time property. It may
# NOT say, imply, or let a reader infer that members CURRENTLY share
# an embedding envelope: re-embedding a member under another model
# leaves its old edges untouched, so current envelopes cannot attest
# the historical space of stored edges. Nothing here reads an
# envelope, names a space triple, or promises per-space grouping.
#
# READ-ONLY, ALWAYS (D5, FR-D). Every graph open in this slice is
# `connect_read_only`; there is no write statement anywhere in this
# module. Clusters are computed on read and materialized nowhere: no
# new tables, no columns, no DDL.

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .clusters import Cluster, find_clusters
from .similar_runner import GraphNotReadyError

#: A stored directed edge row as the graph returns it. The score rides
#: along because it is what the store holds; clustering never reads it
#: (D1: zero parameters), and the projection to (src, dst) happens at
#: this boundary so no score can reach the pure layer.
EdgeRow = tuple[str, str, float]

#: Report keys, named once so the CLI, the MCP tool and the tests
#: cannot drift from each other on a string literal.
KEY_CLUSTERS = "clusters"
KEY_CLUSTER_COUNT = "cluster_count"
KEY_CLUSTERED = "clustered_sessions"
KEY_UNCLUSTERED = "unclustered_sessions"
KEY_GRAPH_SESSIONS = "graph_sessions"
KEY_BASIS = "basis"
KEY_MEMBERSHIP_BASIS = "membership_basis"
KEY_INVENTORY_BASIS = "inventory_basis"
KEY_LIMITATIONS = "limitations"

BASIS_EMBEDDING = "embedding"

#: The two provenance labels, stated distinctly and without any claim
#: about pass history (FR-A).
MEMBERSHIP_BASIS_TEXT = (
    "the SIMILAR_TO edges currently stored in the graph, as written by "
    "the similarity producer under its compatibility rule"
)
INVENTORY_BASIS_TEXT = (
    "the current Session node inventory, which an incremental 'graph' "
    "run changes independently of the stored edges"
)

#: Stated on every report, because a cluster that travels without them
#: invites exactly the two claims FR-A and FR-B refuse.
LIMITATIONS_TEXT: tuple[str, ...] = (
    "a cluster is a transitive discovery grouping: members are connected "
    "through a chain of recorded edges, which does not assert that every "
    "pair of members is similar",
    "membership reflects the edges the producer created under its "
    "compatibility rule at production time; it does not assert that "
    "members currently share an embedding envelope",
    "re-run 'similar' for fresh clusters — nothing here recomputes "
    "similarity or contacts a backend",
)


class GraphSnapshot(Protocol):
    """A READ-ONLY view of the graph: no write method exists on it.

    Deliberately not `GraphEdgeStore` from #287. That protocol is
    write-capable (`begin`/`commit`/`write_edge`); a reader that
    structurally cannot write is worth more here than reusing one
    catalog query, so the small `graph_ready()` overlap is accepted.
    """

    def graph_ready(self) -> bool: ...
    def session_keys(self) -> set[str]: ...
    def edges(self) -> Sequence[EdgeRow]: ...


class KuzuGraphSnapshot:
    """`GraphSnapshot` over a READ-ONLY GraphDatabase connection.

    The caller opens with `GraphDatabase.connect_read_only`, so this
    class cannot create or mutate the store even by mistake.
    """

    def __init__(self, gdb) -> None:
        self._gdb = gdb

    def graph_ready(self) -> bool:
        """True iff the Session table exists — probed via the catalog,
        exactly as #287 does, never by parsing an error's text."""
        res = self._gdb.execute("CALL show_tables() RETURN *")
        return any("Session" in [str(v) for v in row] for row in _rows(res))

    def session_keys(self) -> set[str]:
        """The CURRENT node inventory — FR-A's second provenance."""
        res = self._gdb.execute("MATCH (s:Session) RETURN s.session_key")
        return {str(row[0]) for row in _rows(res)}

    def edges(self) -> Sequence[EdgeRow]:
        """Every stored directed SIMILAR_TO record."""
        res = self._gdb.execute(
            "MATCH (a:Session)-[r:SIMILAR_TO]->(b:Session) "
            "RETURN a.session_key, b.session_key, r.score")
        return [(str(src), str(dst), float(score))
                for src, dst, score in _rows(res)]


def _rows(res) -> list:
    out = []
    while res.has_next():
        out.append(res.get_next())
    return out


@dataclass(frozen=True)
class ClusterReport:
    """The answer, with both provenances kept separate."""

    clusters: tuple[Cluster, ...]
    unclustered_sessions: int
    graph_sessions: int

    @property
    def clustered_sessions(self) -> int:
        return sum(c.size for c in self.clusters)

    def as_dict(self) -> dict:
        """A deterministic mapping: identical for the same (edges,
        inventory) pair, with no timestamp and no space triple."""
        return {
            KEY_CLUSTERS: [c.as_dict() for c in self.clusters],
            KEY_CLUSTER_COUNT: len(self.clusters),
            KEY_CLUSTERED: self.clustered_sessions,
            KEY_UNCLUSTERED: self.unclustered_sessions,
            KEY_GRAPH_SESSIONS: self.graph_sessions,
            KEY_BASIS: BASIS_EMBEDDING,
            KEY_MEMBERSHIP_BASIS: MEMBERSHIP_BASIS_TEXT,
            KEY_INVENTORY_BASIS: INVENTORY_BASIS_TEXT,
            KEY_LIMITATIONS: list(LIMITATIONS_TEXT),
        }


def run_clusters(snapshot: GraphSnapshot) -> ClusterReport:
    """Compute the cluster report from a read-only snapshot.

    Raises `GraphNotReadyError` when the store exists but holds no
    Session table — the #287 prerequisite, reused rather than
    reinvented. A ready graph with zero edges is NOT an error: it is a
    healthy empty report.

    UNCLUSTERED IS DEFINED BY INCIDENCE, NOT BY MEMBERSHIP (FR-B): a
    graph session is unclustered iff it has NO incident stored edge.
    That is deliberately not "landed in no reported cluster", and the
    two differ on exactly one shape — a node whose only stored edge is
    a self-loop. It HAS an incident edge, so it is not unclustered,
    while T1 correctly suppresses its size-one component, so it is not
    in a cluster either. Such a node is therefore counted in neither,
    and `clustered + unclustered == graph_sessions` holds for every
    edge set the producer can actually write (#287 pairs
    `ids[idx + 1:]`, so it never compares a session with itself) but is
    not asserted as a universal invariant.

    Deriving incidence here keeps the exactness in the layer that owns
    the evidence: T1 is not made to police self-loops, deduplicate
    records, or validate anything about the producer.
    """
    if not snapshot.graph_ready():
        raise GraphNotReadyError(
            "graph store holds no Session table — run "
            "'./scripts/session-analytics graph' first")

    # Read the edge set ONCE: `edges()` is a store round-trip, and both
    # the grouping and the incidence set must describe the same rows.
    rows = list(snapshot.edges())

    # The projection that keeps scores out of the pure layer (D1).
    clusters = tuple(find_clusters((src, dst) for src, dst, _score in rows))

    incident = {key for src, dst, _score in rows for key in (src, dst)}
    inventory = snapshot.session_keys()
    # Set difference, so an edge endpoint absent from the inventory can
    # never drive the count negative.
    return ClusterReport(
        clusters=clusters,
        unclustered_sessions=len(inventory - incident),
        graph_sessions=len(inventory),
    )
