# session_analytics.embedding.similar_runner — the `similar` pass
# (#287 T2; FR-D, FR-E).
#
# STRICTLY LOCAL: this pass reads stored envelopes, computes cosine
# top-K inside FR-A space groups, and reconciles `SIMILAR_TO` edges.
# It never constructs an embedding backend — there is nothing to
# embed here, only stored vectors to compare.
#
# RECONCILIATION COVERS ALL EXISTING EDGES (FR-D). Every pass:
#   1. retires the outgoing edges of every source that is not in this
#      pass's eligible set — an eligible-sources-only replacement
#      would preserve exactly the edges whose evidence is gone;
#   2. replaces each eligible source's outgoing edges with its fresh
#      top-K (a target that became ineligible retires with the rest);
#   3. distinguishes the two zero-write cases: NO eligible sources AND
#      NO existing edges → nothing to do, zero graph contact beyond
#      the existence read; existing edges but nothing eligible →
#      RETIREMENT runs. "Nothing eligible" never preserves stale
#      edges.
#
# THE MUTATION PHASE IS TRANSACTIONAL. All deletions and writes happen
# between begin() and commit() on the edge store; any failure rolls
# back, so the graph always holds either the PREVIOUS complete edge
# set or the new one — edge scores describe the last COMPLETED pass,
# never a torn one.
#
# The edge store is a small seam (GraphEdgeStore protocol) so the
# reconciliation logic is testable without kuzu installed; the Kùzu
# implementation lives beside it and is exercised by the kuzu-marked
# tests (CI installs kuzu; locally they skip, the test_graph.py
# pattern).

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..config import SimilarityConfig
from ..relational.db import Database
from .similarity import group_by_space, top_k_neighbors


class GraphNotReadyError(RuntimeError):
    """The graph store exists but holds no Session table — `graph` has
    never been run against it. A prerequisite failure with guidance,
    not a torn pass."""


@runtime_checkable
class GraphEdgeStore(Protocol):
    """The graph operations the pass needs — semantic, not Cypher."""

    def graph_ready(self) -> bool: ...
    def begin(self) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def existing_edge_sources(self) -> set[str]: ...
    def node_exists(self, session_key: str) -> bool: ...
    def delete_outgoing(self, session_key: str) -> int: ...
    def write_edge(self, src_key: str, dst_key: str, score: float) -> None: ...


class KuzuEdgeStore:
    """GraphEdgeStore over the repo's GraphDatabase wrapper."""

    def __init__(self, gdb) -> None:
        self._gdb = gdb

    def graph_ready(self) -> bool:
        """True iff the Session table exists. Probed via the catalog
        (`CALL show_tables()`, captured on kuzu 0.11.3 returning [] on
        a bare database) — never by parsing a Binder error's text."""
        res = self._gdb.execute("CALL show_tables() RETURN *")
        return any("Session" in [str(v) for v in row] for row in _rows(res))

    def begin(self) -> None:
        self._gdb.execute("BEGIN TRANSACTION")

    def commit(self) -> None:
        self._gdb.execute("COMMIT")

    def rollback(self) -> None:
        self._gdb.execute("ROLLBACK")

    def existing_edge_sources(self) -> set[str]:
        res = self._gdb.execute(
            "MATCH (a:Session)-[:SIMILAR_TO]->() RETURN DISTINCT a.session_key")
        return {row[0] for row in _rows(res)}

    def node_exists(self, session_key: str) -> bool:
        res = self._gdb.execute(
            "MATCH (s:Session {session_key: $k}) RETURN count(s)",
            {"k": session_key})
        rows = _rows(res)
        return bool(rows and rows[0][0])

    def delete_outgoing(self, session_key: str) -> int:
        res = self._gdb.execute(
            "MATCH (a:Session {session_key: $k})-[r:SIMILAR_TO]->() "
            "RETURN count(r)", {"k": session_key})
        rows = _rows(res)
        n = int(rows[0][0]) if rows else 0
        if n:
            self._gdb.execute(
                "MATCH (a:Session {session_key: $k})-[r:SIMILAR_TO]->() "
                "DELETE r", {"k": session_key})
        return n

    def write_edge(self, src_key: str, dst_key: str, score: float) -> None:
        self._gdb.execute(
            "MATCH (a:Session {session_key: $a}), (b:Session {session_key: $b}) "
            "CREATE (a)-[:SIMILAR_TO {score: $s}]->(b)",
            {"a": src_key, "b": dst_key, "s": float(score)},
        )


def _rows(res) -> list:
    out = []
    while res.has_next():
        out.append(res.get_next())
    return out


@dataclass
class SimilarStats:
    #: "nothing-to-do" (no eligible sources, no existing edges) or
    #: "reconciled" (retirement and/or writes ran).
    action: str = "nothing-to-do"
    written_edges: int = 0
    retired_edges: int = 0
    retired_sources: int = 0
    sessions_per_space: dict[str, int] = field(default_factory=dict)
    dim_conflicts: dict[str, list[int]] = field(default_factory=dict)
    excluded_invalid: dict[int, str] = field(default_factory=dict)
    no_envelope: int = 0
    missing_graph_node: int = 0

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "written_edges": self.written_edges,
            "retired_edges": self.retired_edges,
            "retired_sources": self.retired_sources,
            "sessions_per_space": dict(sorted(self.sessions_per_space.items())),
            "dim_conflicts": dict(sorted(self.dim_conflicts.items())),
            "excluded_invalid": {
                str(k): v for k, v in sorted(self.excluded_invalid.items())},
            "no_envelope": self.no_envelope,
            "missing_graph_node": self.missing_graph_node,
        }


def run_similar(
    db: Database,
    similarity_cfg: SimilarityConfig,
    store: GraphEdgeStore,
) -> SimilarStats:
    """FR-D reconciliation over the FR-E lifecycle. Raises on a torn
    mutation phase AFTER rolling back — the previous edge set stands."""
    stats = SimilarStats()

    # ── prerequisite: the graph must have been built (D4: this pass
    #    never creates Session nodes, and an unready graph would turn
    #    every later read into a Binder error) ─────────────────────────
    if not store.graph_ready():
        raise GraphNotReadyError(
            "the graph store holds no Session table — run "
            "'./scripts/session-analytics graph' before 'similar'")

    # ── durable relational state first ───────────────────────────────
    rows = db.query(
        "SELECT id, copilot, session_id, session_embedding "
        "FROM copilot_session ORDER BY id")
    keys: dict[int, str] = {}
    envelopes: dict[int, object] = {}
    for db_id, copilot, native_id, stored in rows:
        if stored is None:
            stats.no_envelope += 1
            continue
        keys[db_id] = f"{copilot}:{native_id}"
        try:
            envelopes[db_id] = json.loads(stored)
        except (json.JSONDecodeError, TypeError):
            envelopes[db_id] = "unparseable"  # refused by validation below

    groups = group_by_space(envelopes)
    stats.excluded_invalid = dict(groups.excluded_invalid)
    stats.dim_conflicts = {
        f"{p}:{m}": list(dims) for (p, m), dims in groups.dim_conflicts.items()}

    # ── graph nodes must already exist (D4: never created here) ──────
    eligible_groups: dict[tuple, list[int]] = {}
    for space, members in groups.groups.items():
        present = []
        for m in members:
            if store.node_exists(keys[m]):
                present.append(m)
            else:
                stats.missing_graph_node += 1
        if present:
            eligible_groups[space] = present
    for space, members in eligible_groups.items():
        stats.sessions_per_space["%s:%s:%d" % space] = len(members)

    eligible_keys = {
        keys[m] for members in eligible_groups.values() for m in members}
    existing_sources = store.existing_edge_sources()

    # ── the two zero-write cases, distinguished (FR-D.3) ─────────────
    if not eligible_keys and not existing_sources:
        return stats  # nothing to do: no tx, no writes
    stats.action = "reconciled"

    # ── compute BEFORE the transaction: the mutation phase only
    #    mutates, so a scoring error can never tear the graph ─────────
    planned: dict[str, list[tuple[str, float]]] = {}
    for space, members in eligible_groups.items():
        vectors = {m: envelopes[m]["vector"] for m in members}
        neighbors = top_k_neighbors(
            vectors, k=similarity_cfg.top_k,
            threshold=similarity_cfg.threshold)
        for m, pairs in neighbors.items():
            planned[keys[m]] = [(keys[n], s) for n, s in pairs]

    # ── transactional mutation: previous edge set or new one, never
    #    a torn mixture ────────────────────────────────────────────────
    store.begin()
    try:
        for src in sorted(existing_sources - eligible_keys):
            n = store.delete_outgoing(src)
            stats.retired_edges += n
            if n:
                stats.retired_sources += 1
        for src in sorted(planned):
            stats.retired_edges += store.delete_outgoing(src)
            for dst, score in planned[src]:
                store.write_edge(src, dst, score)
                stats.written_edges += 1
        # COMMIT is part of the protected phase: a commit failure must
        # trigger the same cleanup, or the connection is left holding
        # the pending replacement (visible in-tx — captured on kuzu
        # 0.11.3).
        store.commit()
    except Exception:
        # Kùzu auto-aborts on some in-tx statement failures, and
        # ROLLBACK then raises "No active transaction" — which must
        # never REPLACE the original error: the original failure is
        # the story, the cleanup is best-effort.
        try:
            store.rollback()
        except Exception:
            pass
        raise
    return stats
