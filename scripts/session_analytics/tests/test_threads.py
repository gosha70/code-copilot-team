"""A6 task 2: the ancestry rule and the graph derived from it.

The corpus fixture is REBUILT here rather than read from
``~/.claude/projects``: a test that depends on the developer's own
transcripts passes locally and fails everywhere else. The synthetic sets
carry the measured cardinalities and overlaps exactly, so the
assertions are about the rule. One optional test runs against the real
transcripts when they happen to be present.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics.threads import (
    RelationCandidate,
    Relation,
    SourceRef,
    classify_pair,
    derive,
    transitive_reduction,
    uuids_from_transcript,
)

PROV = C.THREAD_PROVENANCE_UUID_CONTAINMENT


def src(name: str, uuids) -> SourceRef:
    return SourceRef("claude-code", f"/p/{name}.jsonl", name, frozenset(uuids))


def ids(n: int, prefix: str = "u") -> list[str]:
    return [f"{prefix}{i:05d}" for i in range(n)]


class TestGate(unittest.TestCase):
    """Containment gates; it never decides direction."""

    def test_below_the_shared_floor_is_not_a_relation(self) -> None:
        pool = ids(10)
        a = src("a", pool[:5])
        b = src("b", pool[4:])  # exactly one shared
        self.assertIsNone(classify_pair(a, b, PROV))

    def test_one_shared_uuid_never_invents_a_thread(self) -> None:
        a = src("a", ids(500))
        b = src("b", ids(500, "v") + ["u00000"])
        self.assertIsNone(classify_pair(a, b, PROV))

    def test_below_the_containment_threshold_is_not_a_relation(self) -> None:
        pool = ids(100)
        a = src("a", pool[:50])
        b = src("b", pool[40:])          # 10 shared: 0.2 and 0.166
        self.assertIsNone(classify_pair(a, b, PROV))

    def test_the_gate_uses_the_MAX_of_the_two_ratios(self) -> None:
        # The small side is wholly contained; the large side is not.
        # max() clears, so the pair is gated IN — a rule that required
        # both, or only the first named, would drop every real edge.
        pool = ids(1000)
        small = src("small", pool[:10])
        large = src("large", pool)
        verdict = classify_pair(small, large, PROV)
        self.assertIsInstance(verdict, Relation)


class TestDirection(unittest.TestCase):
    """Net growth decides, and nothing else does."""

    def test_the_side_that_grew_is_the_descendant(self) -> None:
        shared = ids(100)
        a = src("a", shared + ids(5, "x"))       # a_only = 5
        b = src("b", shared + ids(40, "y"))      # b_only = 40
        verdict = classify_pair(a, b, PROV)
        assert isinstance(verdict, Relation)
        self.assertEqual(verdict.ancestor, a.identity)
        self.assertEqual(verdict.descendant, b.identity)
        self.assertEqual(verdict.ancestor_only, 5)
        self.assertEqual(verdict.descendant_only, 40)

    def test_direction_reverses_with_the_growth(self) -> None:
        shared = ids(100)
        a = src("a", shared + ids(40, "x"))
        b = src("b", shared + ids(5, "y"))
        verdict = classify_pair(a, b, PROV)
        assert isinstance(verdict, Relation)
        self.assertEqual(verdict.ancestor, b.identity)
        self.assertEqual(verdict.descendant, a.identity)

    def test_a_ratio_comparison_would_get_the_real_edge_WRONG(self) -> None:
        """The reason the rule is net growth and not symmetric ratios.

        Measured over TURN uuids: 464 shared, ancestor 487, descendant
        517. Both containments clear any workable threshold (0.953 and
        0.897), so a symmetric test calls this a duplicate and loses the
        deepest real link in the corpus. Net growth reads it correctly:
        the resume dropped 23 to a compaction trim and added 53.
        """
        shared = ids(464)
        anc = src("7751a598", shared + ids(23, "drop"))
        desc = src("0e451eb6", shared + ids(53, "add"))
        self.assertAlmostEqual(464 / 487, 0.9528, places=3)
        self.assertAlmostEqual(464 / 517, 0.8975, places=3)

        verdict = classify_pair(anc, desc, PROV)
        assert isinstance(verdict, Relation), "the real link must be an EDGE"
        self.assertEqual(verdict.ancestor, anc.identity)
        self.assertEqual(verdict.descendant, desc.identity)
        self.assertEqual(verdict.ancestor_only, 23)
        self.assertEqual(verdict.descendant_only, 53)
        # both ratios clear 0.5 — the old symmetric rule's duplicate test
        self.assertGreaterEqual(verdict.ancestor_containment, 0.5)
        self.assertGreaterEqual(verdict.descendant_containment, 0.5)

    def test_no_threshold_could_have_saved_the_symmetric_rule(self) -> None:
        """0.897 must be below T for the deep link, 0.750 at or above it
        for the shallow one. No T satisfies both."""
        deep_reverse, shallow_forward = 464 / 517, 6 / 8
        self.assertGreater(deep_reverse, shallow_forward)

    def test_the_exact_differences_are_stored_not_recomputable(self) -> None:
        shared = ids(100)
        a = src("a", shared + ids(5, "x"))
        b = src("b", shared + ids(40, "y"))
        verdict = classify_pair(a, b, PROV)
        assert isinstance(verdict, Relation)
        # shared + two rounded ratios cannot re-derive 5 vs 40
        self.assertEqual((verdict.ancestor_only, verdict.descendant_only), (5, 40))
        self.assertEqual(verdict.rule_version, "containment-net-growth-v1")


class TestUnresolvedCandidates(unittest.TestCase):
    """Equal differences produce no edge, in two distinct kinds."""

    def test_identical_sets_are_duplicate_identity(self) -> None:
        pool = ids(50)
        verdict = classify_pair(src("a", pool), src("b", pool), PROV)
        assert isinstance(verdict, RelationCandidate)
        self.assertEqual(verdict.candidate_kind, C.CANDIDATE_DUPLICATE_IDENTITY)
        self.assertEqual((verdict.a_only, verdict.b_only), (0, 0))

    def test_equal_but_nonzero_differences_are_direction_ambiguous(self) -> None:
        """Not a merge proposal: the two genuinely differ, and the rule
        simply cannot say which came first."""
        shared = ids(100)
        a = src("a", shared + ids(7, "x"))
        b = src("b", shared + ids(7, "y"))
        verdict = classify_pair(a, b, PROV)
        assert isinstance(verdict, RelationCandidate)
        self.assertEqual(verdict.candidate_kind, C.CANDIDATE_DIRECTION_AMBIGUOUS)
        self.assertEqual((verdict.a_only, verdict.b_only), (7, 7))

    def test_the_two_kinds_are_not_interchangeable(self) -> None:
        self.assertNotEqual(
            C.CANDIDATE_DUPLICATE_IDENTITY, C.CANDIDATE_DIRECTION_AMBIGUOUS
        )
        self.assertEqual(len(set(C.CANDIDATE_KINDS)), 2)

    def test_a_candidate_is_recorded_in_canonical_order_either_way(self) -> None:
        pool = ids(50)
        a, b = src("aaa", pool), src("bbb", pool)
        one = classify_pair(a, b, PROV)
        other = classify_pair(b, a, PROV)
        assert isinstance(one, RelationCandidate) and isinstance(other, RelationCandidate)
        self.assertEqual(one.member_a, other.member_a)
        self.assertEqual(one.member_b, other.member_b)
        self.assertLess(one.member_a, one.member_b)

    def test_a_candidate_never_becomes_an_edge(self) -> None:
        pool = ids(50)
        graphs, candidates = derive([src("a", pool), src("b", pool)])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(sum(len(g.edges) for g in graphs), 0)


class TestProvenancePrecedence(unittest.TestCase):
    """One pair from both discovery paths resolves the same way."""

    def setUp(self) -> None:
        shared = ids(100)
        self.a = src("a", shared + ids(5, "x"))
        self.b = src("b", shared + ids(40, "y"))
        self.pair_native = (self.a.identity, self.b.identity,
                            C.THREAD_PROVENANCE_NATIVE_GROUP)
        self.pair_probe = (self.a.identity, self.b.identity, PROV)

    def _provenance(self, order):
        graphs, _ = derive([self.a, self.b], candidate_pairs=order)
        self.assertEqual(len(graphs), 1)
        self.assertEqual(len(graphs[0].edges), 1)
        return graphs[0].edges[0].provenance

    def test_native_group_wins_whichever_order_the_pair_arrives(self) -> None:
        first = self._provenance([self.pair_native, self.pair_probe])
        second = self._provenance([self.pair_probe, self.pair_native])
        self.assertEqual(first, C.THREAD_PROVENANCE_NATIVE_GROUP)
        self.assertEqual(second, C.THREAD_PROVENANCE_NATIVE_GROUP)
        self.assertEqual(first, second, "input order must not decide provenance")

    def test_the_reversed_pair_is_still_one_decision(self) -> None:
        reversed_probe = (self.b.identity, self.a.identity, PROV)
        graphs, _ = derive([self.a, self.b],
                           candidate_pairs=[self.pair_native, reversed_probe])
        self.assertEqual(len(graphs[0].edges), 1)
        self.assertEqual(graphs[0].edges[0].provenance,
                         C.THREAD_PROVENANCE_NATIVE_GROUP)

    def test_precedence_is_declared_not_incidental(self) -> None:
        self.assertEqual(C.THREAD_PROVENANCE_PRECEDENCE[0],
                         C.THREAD_PROVENANCE_NATIVE_GROUP)
        self.assertEqual(set(C.THREAD_PROVENANCE_PRECEDENCE),
                         set(C.THREAD_PROVENANCES))


class TestDerivationIsPure(unittest.TestCase):
    """Derivation carries no identity and repeats exactly."""

    def test_two_runs_over_unchanged_input_are_identical(self) -> None:
        shared = ids(100)
        sources = [src("a", shared), src("b", shared + ids(30, "b")),
                   src("c", shared + ids(30, "b") + ids(30, "c"))]
        first = derive(sources)
        second = derive(list(reversed(sources)))
        self.assertEqual(first, second)

    def test_a_component_carries_no_thread_id(self) -> None:
        shared = ids(100)
        graphs, _ = derive([src("a", shared), src("b", shared + ids(30, "b"))])
        self.assertFalse(hasattr(graphs[0], "thread_id"),
                         "identity belongs to the connection layer")


class TestProvenanceAuthorizesNothing(unittest.TestCase):
    """Adapter grouping proves common membership, not predecessor order."""

    def test_a_native_group_pair_that_fails_the_gate_gets_no_edge(self) -> None:
        pool = ids(100)
        a = src("a", pool[:50])
        b = src("b", pool[45:])  # 5 shared, both ratios 0.1
        verdict = classify_pair(a, b, C.THREAD_PROVENANCE_NATIVE_GROUP)
        self.assertIsNone(verdict, "grouping must not authorize an edge")

    def test_both_provenances_carry_the_same_evidence(self) -> None:
        shared = ids(100)
        a = src("a", shared + ids(5, "x"))
        b = src("b", shared + ids(40, "y"))
        native = classify_pair(a, b, C.THREAD_PROVENANCE_NATIVE_GROUP)
        probed = classify_pair(a, b, PROV)
        assert isinstance(native, Relation) and isinstance(probed, Relation)
        self.assertEqual(native.provenance, C.THREAD_PROVENANCE_NATIVE_GROUP)
        self.assertEqual(probed.provenance, PROV)
        for field in ("ancestor", "descendant", "shared_uuids",
                      "ancestor_only", "descendant_only"):
            self.assertEqual(getattr(native, field), getattr(probed, field))


class TestTransitiveReduction(unittest.TestCase):
    def test_a_skip_edge_is_dropped_in_favour_of_the_chain(self) -> None:
        def rel(a: str, b: str) -> Relation:
            return Relation(("c", a), ("c", b), 10, 0.9, 0.1, 1, 5, PROV)

        reduced = transitive_reduction([rel("a", "b"), rel("b", "c"), rel("a", "c")])
        self.assertEqual(
            [(e.ancestor[1], e.descendant[1]) for e in reduced],
            [("a", "b"), ("b", "c")],
        )

    def test_reduction_runs_over_the_COMPLETE_set(self) -> None:
        """Order of arrival must not change the result."""
        def rel(a: str, b: str) -> Relation:
            return Relation(("c", a), ("c", b), 10, 0.9, 0.1, 1, 5, PROV)

        edges = [rel("a", "b"), rel("b", "c"), rel("a", "c"), rel("c", "d"),
                 rel("a", "d"), rel("b", "d")]
        forward = transitive_reduction(edges)
        backward = transitive_reduction(list(reversed(edges)))
        self.assertEqual(forward, backward)
        self.assertEqual(len(forward), 3)


class TestAmbiguitiesAreFlaggedNeverResolved(unittest.TestCase):
    def test_a_fork_is_flagged_and_nothing_is_ordered(self) -> None:
        shared = ids(100)
        root = src("root", shared)
        left = src("left", shared + ids(30, "l"))
        right = src("right", shared + ids(30, "r"))
        graphs, _ = derive([root, left, right])
        self.assertEqual(len(graphs), 1)
        graph = graphs[0]
        self.assertTrue(graph.fork_suspected)
        self.assertEqual(len(graph.terminals), 2)
        self.assertTrue(graph.terminal_ambiguous)
        # both branches kept, neither ordered against the other
        self.assertEqual(len(graph.edges), 2)

    def test_a_join_is_flagged_per_member_and_keeps_every_edge(self) -> None:
        # two disjoint ancestors, one descendant carrying both
        left = src("left", ids(40, "l"))
        right = src("right", ids(40, "r"))
        joined = src("joined", ids(40, "l") + ids(40, "r") + ids(200, "n"))
        graphs, _ = derive([left, right, joined])
        self.assertEqual(len(graphs), 1)
        graph = graphs[0]
        self.assertEqual(graph.joins, (joined.identity,))
        self.assertTrue(graph.root_ambiguous)
        self.assertEqual(sorted(graph.roots), sorted([left.identity, right.identity]))
        # no canonical predecessor was chosen: both evidence edges kept
        self.assertEqual(len(graph.edges), 2)

    def test_a_clean_chain_raises_no_flag(self) -> None:
        shared = ids(100)
        a = src("a", shared)
        b = src("b", shared + ids(50, "b"))
        c = src("c", shared + ids(50, "b") + ids(50, "c"))
        graphs, _ = derive([a, b, c])
        graph = graphs[0]
        self.assertFalse(graph.fork_suspected)
        self.assertFalse(graph.terminal_ambiguous)
        self.assertFalse(graph.root_ambiguous)
        self.assertEqual(graph.joins, ())
        self.assertEqual(graph.roots, (a.identity,))
        self.assertEqual(graph.terminals, (c.identity,))


class TestNoTimeInput(unittest.TestCase):
    def test_transcript_extraction_ignores_timestamps_entirely(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        early, late = tmp / "early.jsonl", tmp / "late.jsonl"
        rows = [{"type": "user", "uuid": u,
                 "message": {"role": "user", "content": "x"},
                 "timestamp": "2026-01-01T00:00:00Z"} for u in ids(5)]
        early.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        shuffled = [dict(r, timestamp="1999-01-01T00:00:00Z") for r in reversed(rows)]
        late.write_text("\n".join(json.dumps(r) for r in shuffled), encoding="utf-8")
        self.assertEqual(uuids_from_transcript(early), uuids_from_transcript(late))

    def test_a_truncated_line_does_not_lose_the_source(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = tmp / "t.jsonl"
        turn = lambda u: {"type": "user", "uuid": u,  # noqa: E731
                          "message": {"role": "user", "content": "x"}}
        path.write_text(
            json.dumps(turn("u1")) + "\n{\"uuid\": \"u2\"\n"
            + json.dumps(turn("u3")) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(uuids_from_transcript(path), frozenset({"u1", "u3"}))

    def test_an_unreadable_source_is_None_not_an_empty_set(self) -> None:
        """One read answers both questions. An empty set would be
        indistinguishable from a readable transcript carrying no uuids,
        and coverage must not infer availability from cardinality."""
        self.assertIsNone(uuids_from_transcript(Path("/nonexistent/x.jsonl")))


class TestTheMeasuredCorpus(unittest.TestCase):
    """The four-session lineage, rebuilt with its measured shape."""

    def setUp(self) -> None:
        # TURN uuids — the universe copilot_turn.uuid holds and the probe
        # searches. Sizes 8 / 61 / 487 / 517, overlaps 6 / 61 / 464.
        root_pool = ids(6, "r")
        self.ad35 = src("ad35b1c9", root_pool + ids(2, "ra"))
        self.ca89 = src("8ca893f4", root_pool + ids(55, "c"))
        mid = list(self.ca89.uuids) + ids(426, "m")
        self.a775 = src("7751a598", mid)
        # the resume trims 23 (a compaction) and adds 53: 487 - 23 + 53
        # = 517 uuids, 464 shared with its ancestor
        self.e045 = src("0e451eb6", mid[:-23] + ids(53, "d"))

    def test_the_corpus_yields_one_root_one_terminal_and_no_ambiguity(self) -> None:
        graphs, candidates = derive([self.ad35, self.ca89, self.a775, self.e045])
        self.assertEqual(len(graphs), 1)
        self.assertEqual(candidates, ())
        graph = graphs[0]
        self.assertEqual(len(graph.members), 4)
        self.assertEqual(graph.roots, (self.ad35.identity,))
        self.assertEqual(graph.terminals, (self.e045.identity,))
        self.assertFalse(graph.fork_suspected)
        self.assertFalse(graph.terminal_ambiguous)
        self.assertFalse(graph.root_ambiguous)
        self.assertEqual(graph.joins, ())

    def test_the_reduced_chain_is_the_measured_lineage(self) -> None:
        graphs, _ = derive([self.ad35, self.ca89, self.a775, self.e045])
        chain = [
            (e.ancestor[1].split("/")[-1], e.descendant[1].split("/")[-1])
            for e in graphs[0].edges
        ]
        self.assertEqual(
            sorted(chain),
            sorted([
                ("ad35b1c9.jsonl", "8ca893f4.jsonl"),
                ("8ca893f4.jsonl", "7751a598.jsonl"),
                ("7751a598.jsonl", "0e451eb6.jsonl"),
            ]),
        )

    def test_the_critical_edge_is_pinned_at_23_dropped_and_53_added(self) -> None:
        graphs, _ = derive([self.ad35, self.ca89, self.a775, self.e045])
        edge = next(
            e for e in graphs[0].edges if e.descendant == self.e045.identity
        )
        self.assertEqual(edge.ancestor, self.a775.identity)
        self.assertEqual(edge.ancestor_only, 23)
        self.assertEqual(edge.descendant_only, 53)
        self.assertEqual(edge.shared_uuids, 464)


class TestRealTranscriptsWhenPresent(unittest.TestCase):
    """The same assertions against the developer's own transcripts, when
    they exist. Skipped everywhere else, so CI never depends on them."""

    STEMS = (
        "ad35b1c9-67b2-4a82-981b-8b73a92efb51",
        "8ca893f4-2d54-487c-81d5-e4f9cf314d5f",
        "7751a598-ada7-42e6-b891-fa74d59c0f20",
        "0e451eb6-df75-4c6d-9cc4-a100f1cc0cbc",
    )

    def test_real_corpus_chain(self) -> None:
        base = Path.home() / ".claude" / "projects" / "-Users-gosha-dev-repo-code-copilot-team"
        paths = [base / f"{s}.jsonl" for s in self.STEMS]
        if not all(p.exists() for p in paths):
            self.skipTest("the reference transcripts are not on this machine")
        sources = [
            SourceRef("claude-code", str(p), p.stem, uuids_from_transcript(p))
            for p in paths
        ]
        graphs, candidates = derive(sources)
        self.assertEqual(len(graphs), 1)
        self.assertEqual(candidates, ())
        graph = graphs[0]
        self.assertFalse(graph.fork_suspected)
        self.assertFalse(graph.terminal_ambiguous)
        self.assertEqual(len(graph.roots), 1)
        self.assertEqual(len(graph.terminals), 1)
        self.assertTrue(graph.roots[0][1].endswith("ad35b1c9-67b2-4a82-981b-8b73a92efb51.jsonl"))
        self.assertTrue(graph.terminals[0][1].endswith("0e451eb6-df75-4c6d-9cc4-a100f1cc0cbc.jsonl"))
        critical = next(
            e for e in graph.edges
            if e.descendant[1].endswith("0e451eb6-df75-4c6d-9cc4-a100f1cc0cbc.jsonl")
        )
        self.assertEqual((critical.shared_uuids, critical.ancestor_only,
                          critical.descendant_only), (464, 23, 53))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# ── Persistence: connection (2a) and relation candidates (2b) ──────────

import shutil as _shutil  # noqa: E402
import tempfile as _tempfile  # noqa: E402

from session_analytics.relational.db import (  # noqa: E402
    Database, apply_ddl, check_schema,
)
from session_analytics.threads import (  # noqa: E402
    ThreadStoreError,
    allocate_thread,
    backfill,
    connect_threads,
    detect_for_session,
    lineage_support,
    load_source_uuids,
    SessionNotFound,
    session_lineage,
    probe_related_members,
    persist,
    register_source,
    resolve_thread,
    reconcile,
    resolve_thread_id,
    THREAD_ADDITIVE_TURN_COLUMNS,
    THREAD_FIGURE_FIELDS,
    threads_for_session,
    store_candidates,
    thread_distinct_uuids,
    thread_figures,
    thread_figures_for_session,
    thread_view,
)


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(_tempfile.mkdtemp())
        self.db = Database.connect(f"sqlite:///{root / 't.db'}")
        # Registered BEFORE apply_ddl, so a failure there still releases
        # the descriptor and the directory.
        self.addCleanup(_shutil.rmtree, root, ignore_errors=True)
        self.addCleanup(self.db.close)
        apply_ddl(self.db)
        self._session_seq = 0   # NOT `_session`: subclasses name helpers that

    def session_with_turns(self, uuids) -> int:
        """A real session row plus its turns, so distinct-uuid counts are
        measured from the store rather than asserted."""
        self._session_seq += 1
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id) "
            "VALUES (?, ?, ?) RETURNING id",
            ("claude-code", f"s{self._session_seq}", "local"),
        )
        for index, value in enumerate(uuids):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid) "
                "VALUES (?, ?, ?, ?)",
                (sid, index, "user", value),
            )
        self.db.commit()
        return int(sid)

    def attach(self, source: SourceRef, thread_ref, session_ref=None) -> int:
        ref = register_source(self.db, source, session_ref=session_ref)
        if thread_ref is not None:
            self.db.execute(
                "UPDATE thread_member SET thread_ref = ? WHERE id = ?", (thread_ref, ref))
        self.db.commit()
        return ref

    def status_of(self, thread_ref: int):
        return self.db.query_one(
            "SELECT status, redirected_to_ref FROM session_thread WHERE id = ?",
            (thread_ref,),
        )


class TestRegisteredSources(StoreCase):
    def test_a_source_with_no_thread_is_recordable(self) -> None:
        ref = register_source(self.db, src("lonely", ids(5)), source_available=False)
        self.db.commit()
        row = self.db.query_one(
            "SELECT thread_ref, source_available FROM thread_member WHERE id = ?", (ref,))
        self.assertIsNone(row[0])
        self.assertFalse(bool(row[1]))

    def test_re_registering_updates_rather_than_duplicates(self) -> None:
        source = src("a", ids(5))
        first = register_source(self.db, source)
        second = register_source(self.db, src("a", ids(9)))
        self.db.commit()
        self.assertEqual(first, second)
        count = self.db.query_one("SELECT COUNT(*) FROM thread_member")[0]
        self.assertEqual(count, 1)
        self.assertEqual(
            self.db.query_one(
                "SELECT turn_uuid_count FROM thread_member WHERE id = ?", (first,))[0], 9)


class TestThreadConnection(StoreCase):
    """FR-20: connecting redirects; it never rewrites an id."""

    def setUp(self) -> None:
        super().setUp()
        self.big = allocate_thread(self.db)
        self.small = allocate_thread(self.db)
        self.attach(src("big", ids(10)), self.big,
                    self.session_with_turns(ids(10)))
        self.attach(src("small", ids(3)), self.small,
                    self.session_with_turns(ids(3, "s")))
        self.db.commit()
        self.big_id = self.db.query_one(
            "SELECT thread_id FROM session_thread WHERE id = ?", (self.big,))[0]
        self.small_id = self.db.query_one(
            "SELECT thread_id FROM session_thread WHERE id = ?", (self.small,))[0]

    def test_the_larger_thread_survives_and_the_other_redirects(self) -> None:
        survivor = connect_threads(self.db, self.small, self.big)
        self.db.commit()
        self.assertEqual(survivor, self.big)
        self.assertEqual(self.status_of(self.big), (C.THREAD_STATUS_ACTIVE, None))
        self.assertEqual(self.status_of(self.small),
                         (C.THREAD_STATUS_REDIRECTED, self.big))

    def test_both_thread_ids_still_resolve_after_the_connection(self) -> None:
        connect_threads(self.db, self.small, self.big)
        self.db.commit()
        self.assertEqual(resolve_thread_id(self.db, self.big_id), self.big)
        self.assertEqual(resolve_thread_id(self.db, self.small_id), self.big,
                         "a redirected id must resolve, not fail or return empty")

    def test_members_and_edges_move_to_the_survivor(self) -> None:
        # the losing thread carries a REAL edge, so "edges move" is
        # actually exercised rather than vacuously true
        extra = self.attach(src("small2", ids(2, "s")), self.small)
        first = self.db.query_one(
            "SELECT id FROM thread_member WHERE thread_ref = ? ORDER BY id",
            (self.small,))[0]
        self.db.execute(
            "INSERT INTO thread_edge (thread_ref, ancestor_member_ref, "
            "descendant_member_ref, provenance, shared_uuids, "
            "ancestor_containment, descendant_containment, ancestor_only, "
            "descendant_only, rule_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.small, first, extra, PROV, 3, 1.0, 0.6, 0, 2,
             C.THREAD_RULE_VERSION))
        self.db.commit()

        connect_threads(self.db, self.small, self.big)
        self.db.commit()
        moved = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE thread_ref = ?", (self.big,))[0]
        self.assertEqual(moved, 3)
        moved_edges = self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge "
            "WHERE thread_ref = ?", (self.big,))
        self.assertEqual(moved_edges, [(first, extra)],
                         "the loser's edge moved to the survivor")
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_edge WHERE thread_ref = ?",
                              (self.small,))[0], 0)
        left = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE thread_ref = ?", (self.small,))[0]
        self.assertEqual(left, 0)
        self.assertEqual(
            self.db.query_one("SELECT member_count FROM session_thread WHERE id = ?",
                              (self.big,))[0], 3)

    def test_the_survivor_is_the_same_on_a_re_run(self) -> None:
        first = connect_threads(self.db, self.small, self.big)
        second = connect_threads(self.db, self.big, self.small)
        self.assertEqual(first, second)

    def test_a_tie_is_broken_lexicographically_not_by_time(self) -> None:
        left = allocate_thread(self.db)
        right = allocate_thread(self.db)
        # identical distinct-uuid counts (both zero: no sessions attached)
        self.attach(src("l", ids(4)), left)
        self.attach(src("r", ids(4)), right)
        self.db.commit()
        left_id = self.db.query_one(
            "SELECT thread_id FROM session_thread WHERE id = ?", (left,))[0]
        right_id = self.db.query_one(
            "SELECT thread_id FROM session_thread WHERE id = ?", (right,))[0]
        expected = left if left_id <= right_id else right
        self.assertEqual(connect_threads(self.db, left, right), expected)

    def test_distinct_uuids_are_counted_not_summed(self) -> None:
        """The double-count guard: a descendant carrying most of its
        ancestor's turns must not be added to it."""
        thread = allocate_thread(self.db)
        shared = ids(90)
        self.attach(src("anc", shared), thread, self.session_with_turns(shared))
        self.attach(src("desc", shared + ids(10, "d")), thread,
                    self.session_with_turns(shared + ids(10, "d")))
        self.db.commit()
        self.assertEqual(thread_distinct_uuids(self.db, thread), 100)  # not 190


class TestResolveFirstInvariant(StoreCase):
    """Acyclicity comes from resolving to active roots, not from ranking."""

    def setUp(self) -> None:
        super().setUp()
        self.a = allocate_thread(self.db)
        self.b = allocate_thread(self.db)
        self.attach(src("a", ids(10)), self.a, self.session_with_turns(ids(10)))
        self.attach(src("b", ids(3)), self.b, self.session_with_turns(ids(3, "b")))
        self.survivor = connect_threads(self.db, self.b, self.a)
        self.db.commit()
        self.old_id = self.db.query_one(
            "SELECT thread_id FROM session_thread WHERE id = ?", (self.b,))[0]

    def test_a_merge_through_an_OLD_REDIRECTED_id_is_a_no_op(self) -> None:
        before = self.db.query("SELECT id, status, redirected_to_ref FROM session_thread")
        again = connect_threads(self.db, self.b, self.survivor)
        self.db.commit()
        self.assertEqual(again, self.survivor, "it resolves to the active thread")
        after = self.db.query("SELECT id, status, redirected_to_ref FROM session_thread")
        self.assertEqual(before, after, "no second redirect, no cycle")

    def test_it_moves_no_members_and_repeats_identically(self) -> None:
        before = self.db.query("SELECT id, thread_ref FROM thread_member ORDER BY id")
        connect_threads(self.db, self.b, self.survivor)
        connect_threads(self.db, self.survivor, self.b)
        self.db.commit()
        after = self.db.query("SELECT id, thread_ref FROM thread_member ORDER BY id")
        self.assertEqual(before, after)

    def test_a_redirected_thread_is_never_re_pointed(self) -> None:
        third = allocate_thread(self.db)
        self.attach(src("c", ids(50)), third, self.session_with_turns(ids(50, "c")))
        self.db.commit()
        connect_threads(self.db, self.b, third)   # self.b resolves away first
        self.db.commit()
        # the original redirect still points where it did
        self.assertEqual(self.status_of(self.b)[1], self.survivor)

    def test_a_chain_of_redirects_resolves_to_one_active_thread(self) -> None:
        third = allocate_thread(self.db)
        self.attach(src("c", ids(100)), third, self.session_with_turns(ids(100, "c")))
        self.db.commit()
        final = connect_threads(self.db, self.survivor, third)
        self.db.commit()
        self.assertEqual(resolve_thread(self.db, self.b), final)
        self.assertEqual(resolve_thread_id(self.db, self.old_id), final)

    def test_a_self_redirect_is_unwritable_so_no_cycle_can_be_stored(self) -> None:
        """The one-hop cycle is refused by the database itself, at the
        write — not caught later by resolution."""
        orphan = allocate_thread(self.db)
        with self.assertRaises(Exception):
            self.db.execute(
                "UPDATE session_thread SET status = ?, redirected_to_ref = ? "
                "WHERE id = ?",
                (C.THREAD_STATUS_REDIRECTED, orphan, orphan))

    def test_resolving_a_thread_that_does_not_exist_is_reported(self) -> None:
        with self.assertRaises(ThreadStoreError):
            resolve_thread(self.db, 999999)

    def test_an_unknown_thread_id_resolves_to_nothing_rather_than_guessing(self) -> None:
        self.assertIsNone(resolve_thread_id(self.db, "no-such-thread"))


class TestCandidatePersistence(StoreCase):
    """FR-21: durable, canonical, idempotent — and never an edge."""

    def setUp(self) -> None:
        super().setUp()
        pool = ids(50)
        self.a, self.b = src("aaa", pool), src("bbb", pool)
        self.ids = {
            self.a.identity: register_source(self.db, self.a),
            self.b.identity: register_source(self.db, self.b),
        }
        self.db.commit()

    def test_a_candidate_is_stored_and_no_edge_is(self) -> None:
        _graphs, candidates = derive([self.a, self.b])
        store_candidates(self.db, candidates, self.ids)
        self.db.commit()
        rows = self.db.query(
            "SELECT member_a_ref, member_b_ref, a_only, b_only, candidate_kind "
            "FROM thread_relation_candidate")
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0][0], rows[0][1], "canonical order")
        self.assertEqual((rows[0][2], rows[0][3]), (0, 0))
        self.assertEqual(rows[0][4], C.CANDIDATE_DUPLICATE_IDENTITY)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 0)

    def test_a_second_pass_does_not_duplicate_it(self) -> None:
        _graphs, candidates = derive([self.a, self.b])
        store_candidates(self.db, candidates, self.ids)
        store_candidates(self.db, candidates, self.ids)
        self.db.commit()
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_relation_candidate")[0], 1)

    def test_a_direction_ambiguous_pair_is_stored_with_its_own_kind(self) -> None:
        shared = ids(100)
        left, right = src("l", shared + ids(7, "x")), src("r", shared + ids(7, "y"))
        member_ids = {
            left.identity: register_source(self.db, left),
            right.identity: register_source(self.db, right),
        }
        _graphs, candidates = derive([left, right])
        store_candidates(self.db, candidates, member_ids)
        self.db.commit()
        row = self.db.query_one(
            "SELECT candidate_kind, a_only, b_only FROM thread_relation_candidate "
            "WHERE member_a_ref = ?", (min(member_ids.values()),))
        self.assertEqual(row[0], C.CANDIDATE_DIRECTION_AMBIGUOUS)
        self.assertEqual((row[1], row[2]), (7, 7))

    def test_a_candidate_never_merges_the_two_members(self) -> None:
        _graphs, candidates = derive([self.a, self.b])
        store_candidates(self.db, candidates, self.ids)
        self.db.commit()
        refs = self.db.query("SELECT thread_ref FROM thread_member")
        self.assertTrue(all(r[0] is None for r in refs), "no thread was created")


class TestPersistWholeGraph(StoreCase):
    def test_a_component_allocates_once_and_repeats_identically(self) -> None:
        shared = ids(100)
        sources = [src("a", shared), src("b", shared + ids(30, "b")),
                   src("c", shared + ids(30, "b") + ids(30, "c"))]
        member_ids = {s.identity: register_source(self.db, s) for s in sources}
        self.db.commit()
        graphs, candidates = derive(sources)

        first = persist(self.db, graphs, candidates, member_ids)
        threads = self.db.query_one("SELECT COUNT(*) FROM session_thread")[0]
        edges = self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0]
        self.assertEqual((first["allocated"], threads, edges), (1, 1, 2))

        second = persist(self.db, graphs, candidates, member_ids)
        self.assertEqual(second["allocated"], 0)
        self.assertEqual(second["reused"], 1)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM session_thread")[0], 1)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 2)

    def test_a_later_source_bridging_two_threads_redirects_one(self) -> None:
        left, right = src("l", ids(60, "l")), src("r", ids(60, "r"))
        ids_map = {s.identity: register_source(self.db, s) for s in (left, right)}
        self.db.commit()
        for source in (left, right):
            thread = allocate_thread(self.db)
            self.db.execute("UPDATE thread_member SET thread_ref = ? WHERE id = ?",
                            (thread, ids_map[source.identity]))
        self.db.commit()
        before = self.db.query_one("SELECT COUNT(*) FROM session_thread")[0]
        self.assertEqual(before, 2)

        bridge = src("bridge", ids(60, "l") + ids(60, "r") + ids(200, "n"))
        ids_map[bridge.identity] = register_source(self.db, bridge)
        self.db.commit()
        graphs, candidates = derive([left, right, bridge])
        persist(self.db, graphs, candidates, ids_map)

        active = self.db.query(
            "SELECT id FROM session_thread WHERE status = ?", (C.THREAD_STATUS_ACTIVE,))
        redirected = self.db.query(
            "SELECT id FROM session_thread WHERE status = ?",
            (C.THREAD_STATUS_REDIRECTED,))
        self.assertEqual(len(active), 1, "the two threads became one")
        self.assertEqual(len(redirected), 1)
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM session_thread")[0], 2,
            "no thread was deleted; the loser stays addressable")

    def test_flags_reach_the_store_without_being_resolved(self) -> None:
        left, right = src("l", ids(40, "l")), src("r", ids(40, "r"))
        joined = src("j", ids(40, "l") + ids(40, "r") + ids(200, "n"))
        member_ids = {s.identity: register_source(self.db, s)
                      for s in (left, right, joined)}
        self.db.commit()
        graphs, candidates = derive([left, right, joined])
        persist(self.db, graphs, candidates, member_ids)
        flags = self.db.query_one(
            "SELECT root_ambiguous, fork_suspected FROM session_thread")
        self.assertTrue(bool(flags[0]))
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_member "
                              "WHERE join_suspected = ?", (True,))[0], 1)
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_member "
                              "WHERE is_root = ?", (True,))[0], 2,
            "every actual root is marked and none is chosen")


class TestIncrementalReconciliation(StoreCase):
    """A partial ingest view must not destroy what it never looked at."""

    def _chain(self, prefix: str, base):
        """Three sources forming a two-edge chain."""
        a = src(f"{prefix}a", base)
        b = src(f"{prefix}b", base + ids(30, f"{prefix}b"))
        c = src(f"{prefix}c", base + ids(30, f"{prefix}b") + ids(30, f"{prefix}c"))
        return [a, b, c]

    def setUp(self) -> None:
        super().setUp()
        self.left = self._chain("L", ids(100, "L"))
        self.right = self._chain("R", ids(100, "R"))
        self.all_sources = {s.identity: s for s in self.left + self.right}
        # two separate threads, each with two reduced edges
        for chain in (self.left, self.right):
            reconcile(self.db, chain, uuid_loader=self._loader)
        self.db.commit()

    def _loader(self, source_key):
        for identity, source in self.all_sources.items():
            if identity[1] == source_key:
                return source.uuids
        return frozenset()

    def test_the_two_threads_start_with_two_edges_each(self) -> None:
        rows = self.db.query(
            "SELECT thread_ref, COUNT(*) FROM thread_edge GROUP BY thread_ref")
        self.assertEqual(sorted(c for _, c in rows), [2, 2])

    def test_a_bridge_joins_them_WITHOUT_erasing_prior_lineage(self) -> None:
        bridge = src("bridge",
                     list(self.left[-1].uuids) + list(self.right[-1].uuids)
                     + ids(400, "n"))
        self.all_sources[bridge.identity] = bridge
        # the incremental view is the BRIDGE ALONE — the partial graph
        # that used to erase everything else
        reconcile(self.db, [bridge], uuid_loader=self._loader)
        self.db.commit()

        active = self.db.query(
            "SELECT id FROM session_thread WHERE status = ?",
            (C.THREAD_STATUS_ACTIVE,))
        self.assertEqual(len(active), 1, "the two threads became one")
        thread_ref = active[0][0]

        members = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE thread_ref = ?", (thread_ref,))[0]
        self.assertEqual(members, 7, "six originals plus the bridge")

        edges = self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge "
            "WHERE thread_ref = ?", (thread_ref,))
        # four original chain edges survive, plus one per chain into the
        # bridge — nothing was erased and nothing was duplicated
        self.assertEqual(len(edges), 6, f"expected the full reduced graph, got {edges}")
        self.assertEqual(len(set(edges)), 6)

        by_key = dict(self.db.query(
            "SELECT source_key, id FROM thread_member WHERE thread_ref = ?",
            (thread_ref,)))
        bridge_ref = by_key[bridge.source_key]
        incoming = [e for e in edges if e[1] == bridge_ref]
        self.assertEqual(len(incoming), 2, "one tip from each former thread")

    def test_every_flag_is_re_derived_over_the_whole_component(self) -> None:
        bridge = src("bridge",
                     list(self.left[-1].uuids) + list(self.right[-1].uuids)
                     + ids(400, "n"))
        self.all_sources[bridge.identity] = bridge
        reconcile(self.db, [bridge], uuid_loader=self._loader)
        self.db.commit()

        roots = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE is_root = ?", (True,))[0]
        terminals = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE is_terminal = ?", (True,))[0]
        joins = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE join_suspected = ?", (True,))[0]
        self.assertEqual(roots, 2, "both former chain roots, neither chosen")
        self.assertEqual(terminals, 1, "the bridge is the only tip now")
        self.assertEqual(joins, 1, "the bridge joins two lineages")
        flags = self.db.query_one(
            "SELECT root_ambiguous, terminal_ambiguous FROM session_thread "
            "WHERE status = ?", (C.THREAD_STATUS_ACTIVE,))
        self.assertTrue(bool(flags[0]))
        self.assertFalse(bool(flags[1]),
                         "the former terminals are no longer terminal")

    def test_an_unreadable_member_keeps_its_edges_instead_of_losing_them(self) -> None:
        """A source that cannot be re-read is recorded unavailable and
        left out of the authoritative scope, so its lineage survives."""
        def partial(source_key):
            if source_key.endswith("La.jsonl"):
                return None                 # UNREADABLE, not merely empty
            return self._loader(source_key)

        before = self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0]
        reconcile(self.db, [self.left[2]], uuid_loader=partial)
        self.db.commit()
        after = self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0]
        self.assertEqual(before, after, "the unreadable member kept its edge")
        self.assertEqual(
            self.db.query_one(
                "SELECT source_available FROM thread_member WHERE source_key = ?",
                (self.left[0].source_key,))[0], 0)

    def test_flags_agree_with_the_RETAINED_edges_not_just_the_derived_ones(self) -> None:
        """La is unreadable, so La->Lb is retained rather than re-derived.
        Lb must NOT be written as a root on the strength of a partial
        graph that could not see the edge above it."""
        def partial(source_key):
            return None if source_key.endswith("La.jsonl") else self._loader(source_key)

        reconcile(self.db, [self.left[2]], uuid_loader=partial)
        self.db.commit()
        by_key = dict(self.db.query("SELECT source_key, id FROM thread_member"))
        thread_ref = self.db.query_one(
            "SELECT thread_ref FROM thread_member WHERE id = ?",
            (by_key[self.left[1].source_key],))[0]
        rows = dict(self.db.query(
            "SELECT id, is_root FROM thread_member WHERE thread_ref = ?",
            (thread_ref,)))
        self.assertFalse(bool(rows[by_key[self.left[1].source_key]]),
                         "Lb has a retained incoming edge, so it is not a root")
        self.assertTrue(bool(rows[by_key[self.left[0].source_key]]),
                        "La is still the root, on retained evidence")
        terminals = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE thread_ref = ? AND is_terminal = ?",
            (thread_ref, True))[0]
        joins = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE thread_ref = ? AND join_suspected = ?",
            (thread_ref, True))[0]
        self.assertEqual((terminals, joins), (1, 0))
        flags = self.db.query_one(
            "SELECT fork_suspected, terminal_ambiguous, root_ambiguous "
            "FROM session_thread WHERE id = ?", (thread_ref,))
        self.assertEqual([bool(f) for f in flags], [False, False, False])


class TestCandidateRetirement(StoreCase):
    """A candidate that becomes an edge must stop being outstanding."""

    def test_a_candidate_is_retired_once_the_pair_becomes_directional(self) -> None:
        shared = ids(100)
        a = src("a", shared + ids(7, "x"))
        b = src("b", shared + ids(7, "y"))
        sources = {s.identity: s for s in (a, b)}
        loader = lambda key: next(  # noqa: E731
            (s.uuids for s in sources.values() if s.source_key == key), frozenset())

        reconcile(self.db, [a, b], uuid_loader=loader)
        self.db.commit()
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_relation_candidate")[0], 1)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 0)

        # `b` is re-read and has grown: the pair is now directional
        grown = src("b", shared + ids(60, "y"))
        sources[grown.identity] = grown
        reconcile(self.db, [a, grown], uuid_loader=loader)
        self.db.commit()

        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_relation_candidate")[0], 0,
            "the resolved candidate must not linger beside the new edge")
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 1)

    def test_a_candidate_the_pass_never_evaluated_is_left_alone(self) -> None:
        """'not evaluated' is not 'resolved'."""
        pool = ids(50)
        a, b = src("aaa", pool), src("bbb", pool)
        member_ids = {
            a.identity: register_source(self.db, a),
            b.identity: register_source(self.db, b),
        }
        _graphs, candidates = derive([a, b])
        store_candidates(self.db, candidates, member_ids)
        self.db.commit()

        other = src("zzz", ids(40, "z"))
        reconcile(self.db, [other], uuid_loader=lambda key: frozenset())
        self.db.commit()
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_relation_candidate")[0], 1)


class TestProbeContractPath(StoreCase):
    """The EXACT shape task 3 calls with: explicit related members and
    a shortlist naming the pairs the probe returned.

    The exhaustive fallback is not this path. The probe selects the
    TOUCHED THREAD SET; every readable pair inside it is reclassified,
    while a thread the probe never reached stays untouched — neither
    its edges nor its candidates are retired.
    """

    def _chain(self, prefix, base):
        a = src(f"{prefix}a", base)
        b = src(f"{prefix}b", base + ids(30, f"{prefix}b"))
        c = src(f"{prefix}c", base + ids(30, f"{prefix}b") + ids(30, f"{prefix}c"))
        return [a, b, c]

    def setUp(self) -> None:
        super().setUp()
        self.left = self._chain("L", ids(100, "L"))
        self.right = self._chain("R", ids(100, "R"))
        self.known = {s.identity: s for s in self.left + self.right}
        for chain in (self.left, self.right):
            reconcile(self.db, chain, uuid_loader=self._loader)
        self.db.commit()
        # an unrelated pair the probe will never look at
        pool = ids(50, "Z")
        self.z1, self.z2 = src("z1", pool), src("z2", pool)
        self.known[self.z1.identity] = self.z1
        self.known[self.z2.identity] = self.z2
        reconcile(self.db, [self.z1, self.z2], uuid_loader=self._loader)
        self.db.commit()

    def _loader(self, source_key):
        for source in self.known.values():
            if source.source_key == source_key:
                return source.uuids
        return None

    def _ref(self, source) -> int:
        return int(self.db.query_one(
            "SELECT id FROM thread_member WHERE source_key = ?",
            (source.source_key,))[0])

    def test_a_shortlisted_bridge_joins_without_touching_anything_else(self) -> None:
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_relation_candidate")[0], 1,
            "the unrelated duplicate pair is outstanding before the pass")
        edges_before = self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0]
        self.assertEqual(edges_before, 4)

        bridge = src("bridge",
                     list(self.left[-1].uuids) + list(self.right[-1].uuids)
                     + ids(400, "n"))
        self.known[bridge.identity] = bridge

        # EXACTLY what the index probe yields: the two tips it collided
        # with, and only the bridge-to-tip pairs.
        related = [self._ref(self.left[-1]), self._ref(self.right[-1])]
        shortlist = [
            (bridge.identity, self.left[-1].identity, PROV),
            (bridge.identity, self.right[-1].identity, PROV),
        ]
        stats = reconcile(self.db, [bridge], related_members=related,
                          candidate_pairs=shortlist, uuid_loader=self._loader)
        self.db.commit()

        # The shortlist decided which threads to pull in; every readable
        # pair inside them is then reclassified, which is what makes a
        # reduced-away edge recoverable later. 7 members -> 21 pairs.
        self.assertEqual(stats["evaluated_pairs"], 21)

        active = self.db.query(
            "SELECT id FROM session_thread WHERE status = ?",
            (C.THREAD_STATUS_ACTIVE,))
        joined = [t for (t,) in active if self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE thread_ref = ?", (t,))[0] == 7]
        self.assertEqual(len(joined), 1, "the two chains became one thread")

        edges = self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge "
            "WHERE thread_ref = ?", (joined[0],))
        self.assertEqual(len(edges), 6,
                         f"four unexamined chain edges survived, got {edges}")
        self.assertEqual(len(set(edges)), 6)
        bridge_ref = self._ref(bridge)
        self.assertEqual(len([e for e in edges if e[1] == bridge_ref]), 2)

    def test_an_unexamined_candidate_is_not_retired_by_a_shortlisted_pass(self) -> None:
        bridge = src("bridge",
                     list(self.left[-1].uuids) + list(self.right[-1].uuids)
                     + ids(400, "n"))
        self.known[bridge.identity] = bridge
        reconcile(
            self.db, [bridge],
            related_members=[self._ref(self.left[-1]), self._ref(self.right[-1])],
            candidate_pairs=[(bridge.identity, self.left[-1].identity, PROV),
                             (bridge.identity, self.right[-1].identity, PROV)],
            uuid_loader=self._loader,
        )
        self.db.commit()
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_relation_candidate")[0], 1,
            "a candidate the shortlist never evaluated must survive")


class TestEdgeRetirementTransitions(StoreCase):
    """A pair that stops being an edge must stop being stored as one."""

    def _setup_pair(self, a, b):
        known = {a.identity: a, b.identity: b}
        loader = lambda key: next(  # noqa: E731
            (s.uuids for s in known.values() if s.source_key == key), None)
        reconcile(self.db, [a, b], uuid_loader=loader)
        self.db.commit()
        return known, loader

    def test_edge_becomes_candidate_and_the_old_edge_goes(self) -> None:
        shared = ids(100)
        a = src("a", shared + ids(5, "x"))
        b = src("b", shared + ids(40, "y"))
        known, loader = self._setup_pair(a, b)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 1)

        # `a` is re-read and has caught up: neither side grew any more
        grown = src("a", shared + ids(40, "x"))
        known[grown.identity] = grown
        reconcile(self.db, [grown, b], uuid_loader=loader)
        self.db.commit()

        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 0,
                         "the stale edge must not sit beside its own contradiction")
        self.assertEqual(
            self.db.query_one("SELECT candidate_kind FROM thread_relation_candidate")[0],
            C.CANDIDATE_DIRECTION_AMBIGUOUS)

    def test_edge_becomes_no_relation_at_all(self) -> None:
        shared = ids(100)
        a = src("a", shared + ids(5, "x"))
        b = src("b", shared + ids(40, "y"))
        known, loader = self._setup_pair(a, b)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 1)

        # `b` is re-read and now shares almost nothing: below the gate
        divergent = src("b", ids(3, "u") + ids(400, "z"))
        known[divergent.identity] = divergent
        reconcile(self.db, [a, divergent], uuid_loader=loader)
        self.db.commit()

        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 0)
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_relation_candidate")[0], 0,
            "below the gate is no relation, not a candidate")
        roots = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE is_root = ?", (True,))[0]
        self.assertEqual(roots, 2, "both members are roots once the edge is gone")


class TestAvailabilityIsNotCardinality(StoreCase):
    """An empty transcript is available; an unreadable one is not."""

    def test_a_readable_but_empty_source_is_available(self) -> None:
        empty = src("empty", [])
        reconcile(self.db, [empty], uuid_loader=lambda key: frozenset())
        self.db.commit()
        self.assertEqual(
            self.db.query_one(
                "SELECT source_available FROM thread_member WHERE source_key = ?",
                (empty.source_key,))[0], 1)

    def test_an_unreadable_source_is_not(self) -> None:
        gone = src("gone", ids(5))
        ref = register_source(self.db, gone)
        self.db.commit()
        other = src("other", ids(5))
        reconcile(self.db, [other], related_members=[ref],
                  uuid_loader=lambda key: None if key.endswith("gone.jsonl")
                  else frozenset(ids(5)))
        self.db.commit()
        self.assertEqual(
            self.db.query_one(
                "SELECT source_available FROM thread_member WHERE source_key = ?",
                (gone.source_key,))[0], 0)

    def test_load_source_uuids_separates_missing_from_empty(self) -> None:
        tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, tmp, ignore_errors=True)
        empty = tmp / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        self.assertEqual(load_source_uuids(str(empty)), frozenset())
        self.assertIsNone(load_source_uuids(str(tmp / "absent.jsonl")))


class TestCombinedGraphReduction(StoreCase):
    """The index-probe shape: a new descendant collides with its WHOLE
    lineage, so the shortlist names every ancestor."""

    def setUp(self) -> None:
        super().setUp()
        base = ids(100, "A")
        self.a = src("A", base)
        self.b = src("B", base + ids(30, "B"))
        self.c = src("C", base + ids(30, "B") + ids(30, "C"))
        self.known = {s.identity: s for s in (self.a, self.b, self.c)}
        reconcile(self.db, [self.a, self.b, self.c], uuid_loader=self._loader)
        self.db.commit()

    def _loader(self, key):
        return next((s.uuids for s in self.known.values() if s.source_key == key), None)

    def _ref(self, source) -> int:
        return int(self.db.query_one(
            "SELECT id FROM thread_member WHERE source_key = ?",
            (source.source_key,))[0])

    def test_three_returned_ancestors_reduce_to_one_surviving_edge(self) -> None:
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 2)

        d = src("D", list(self.c.uuids) + ids(50, "D"))
        self.known[d.identity] = d
        # the probe returns ALL THREE ancestors, because D replays them all
        stats = reconcile(
            self.db, [d],
            related_members=[self._ref(self.a), self._ref(self.b), self._ref(self.c)],
            candidate_pairs=[(d.identity, self.a.identity, PROV),
                             (d.identity, self.b.identity, PROV),
                             (d.identity, self.c.identity, PROV)],
            uuid_loader=self._loader,
        )
        self.db.commit()
        self.assertEqual(stats["evaluated_pairs"], 6,
                         "all four members' pairs were reclassified")

        edges = {(a, b) for a, b in self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge")}
        expected = {
            (self._ref(self.a), self._ref(self.b)),
            (self._ref(self.b), self._ref(self.c)),
            (self._ref(self.c), self._ref(d)),
        }
        self.assertEqual(edges, expected,
                         "A->D and B->D are redundant beside the chain")

    def test_the_new_descendant_is_not_a_false_join(self) -> None:
        d = src("D", list(self.c.uuids) + ids(50, "D"))
        self.known[d.identity] = d
        reconcile(
            self.db, [d],
            related_members=[self._ref(self.a), self._ref(self.b), self._ref(self.c)],
            candidate_pairs=[(d.identity, self.a.identity, PROV),
                             (d.identity, self.b.identity, PROV),
                             (d.identity, self.c.identity, PROV)],
            uuid_loader=self._loader,
        )
        self.db.commit()
        self.assertEqual(
            self.db.query_one("SELECT join_suspected FROM thread_member WHERE id = ?",
                              (self._ref(d),))[0], 0,
            "three incoming edges would have invented a join")
        flags = self.db.query_one(
            "SELECT fork_suspected, terminal_ambiguous, root_ambiguous "
            "FROM session_thread WHERE status = ?", (C.THREAD_STATUS_ACTIVE,))
        self.assertEqual([bool(f) for f in flags], [False, False, False])
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_member "
                              "WHERE is_terminal = ?", (True,))[0], 1)


class TestShortlistMaterialization(StoreCase):
    """A generator shortlist must behave exactly like a list."""

    def _fixture(self):
        shared = ids(100)
        a = src("a", shared + ids(5, "x"))
        b = src("b", shared + ids(40, "y"))
        known = {a.identity: a, b.identity: b}
        loader = lambda key: next(  # noqa: E731
            (s.uuids for s in known.values() if s.source_key == key), None)
        return a, b, known, loader

    def test_a_generator_shortlist_still_retires_a_stale_edge(self) -> None:
        a, b, known, loader = self._fixture()
        reconcile(self.db, [a, b], uuid_loader=loader)
        self.db.commit()
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 1)

        caught_up = src("a", list(b.uuids - {f"y{i:05d}" for i in range(40)})
                        + ids(40, "x"))
        known[caught_up.identity] = caught_up
        pairs = ((p for p in [(caught_up.identity, b.identity, PROV)]))
        stats = reconcile(self.db, [caught_up, b], candidate_pairs=pairs,
                          uuid_loader=loader)
        self.db.commit()
        self.assertEqual(stats["evaluated_pairs"], 1,
                         "a generator must not be drained before it is counted")
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 0)

    def test_list_and_generator_produce_identical_state(self) -> None:
        def run(as_generator: bool):
            root = Path(_tempfile.mkdtemp())
            self.addCleanup(_shutil.rmtree, root, ignore_errors=True)
            db = Database.connect(f"sqlite:///{root / 't.db'}")
            self.addCleanup(db.close)
            apply_ddl(db)
            a, b, known, loader = self._fixture()
            shortlist = [(a.identity, b.identity, PROV)]
            pairs = (p for p in shortlist) if as_generator else shortlist
            stats = reconcile(db, [a, b], candidate_pairs=pairs, uuid_loader=loader)
            db.commit()
            edges = db.query(
                "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge")
            return stats["evaluated_pairs"], edges

        self.assertEqual(run(False), run(True))


class TestReductionIsRecoverable(StoreCase):
    """Reduction must not destroy evidence a later pass needs.

    Reduction is lossy by construction: A->C is deleted the moment a B
    arrives to make A->B->C. If B<->C later falls below the gate, A->C
    is still true — and must come back, rather than leaving C orphaned
    because a reduction two passes earlier erased it.
    """

    def setUp(self) -> None:
        super().setUp()
        self.known: dict = {}

    def _loader(self, key):
        return next((s.uuids for s in self.known.values() if s.source_key == key), None)

    def _put(self, source):
        self.known[source.identity] = source
        return source

    def _ref(self, source) -> int:
        return int(self.db.query_one(
            "SELECT id FROM thread_member WHERE source_key = ?",
            (source.source_key,))[0])

    def _edges(self):
        return {(a, b) for a, b in self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge")}

    def test_a_reduced_away_edge_reappears_when_its_detour_is_invalidated(self) -> None:
        base = ids(100, "A")
        a = self._put(src("A", base))
        c = self._put(src("C", base + ids(200, "C")))

        # pass 1 — a direct A->C edge
        reconcile(self.db, [a, c], uuid_loader=self._loader)
        self.db.commit()
        self.assertEqual(self._edges(), {(self._ref(a), self._ref(c))},
                         "pass 1: the direct edge")

        # pass 2 — B lands between them, so A->C is reduced away
        b = self._put(src("B", base + ids(60, "C")))
        reconcile(self.db, [b],
                  related_members=[self._ref(a), self._ref(c)],
                  candidate_pairs=[(b.identity, a.identity, PROV),
                                   (b.identity, c.identity, PROV)],
                  uuid_loader=self._loader)
        self.db.commit()
        self.assertEqual(
            self._edges(),
            {(self._ref(a), self._ref(b)), (self._ref(b), self._ref(c))},
            "pass 2: reduced to the chain, A->C deleted")

        # pass 3 — B is re-read and no longer relates to C at all. The
        # shortlist names ONLY B<->C, the narrow view that used to leave
        # C orphaned.
        rewritten = self._put(src("B", base + ids(400, "Q")))
        reconcile(self.db, [rewritten],
                  related_members=[self._ref(a), self._ref(c)],
                  candidate_pairs=[(rewritten.identity, c.identity, PROV)],
                  uuid_loader=self._loader)
        self.db.commit()

        edges = self._edges()
        self.assertIn((self._ref(a), self._ref(c)), edges,
                      "A->C is still true and must have been restored")
        self.assertNotIn((self._ref(b), self._ref(c)), edges,
                         "the invalidated detour is gone")
        self.assertEqual(
            self.db.query_one(
                "SELECT is_root FROM thread_member WHERE id = ?", (self._ref(c),))[0],
            0, "C must not be orphaned into a root")

    def test_the_restored_edge_carries_freshly_computed_evidence(self) -> None:
        base = ids(100, "A")
        a = self._put(src("A", base))
        c = self._put(src("C", base + ids(200, "C")))
        reconcile(self.db, [a, c], uuid_loader=self._loader)
        b = self._put(src("B", base + ids(60, "C")))
        reconcile(self.db, [b], related_members=[self._ref(a), self._ref(c)],
                  candidate_pairs=[(b.identity, a.identity, PROV)],
                  uuid_loader=self._loader)
        rewritten = self._put(src("B", base + ids(400, "Q")))
        reconcile(self.db, [rewritten], related_members=[self._ref(a), self._ref(c)],
                  candidate_pairs=[(rewritten.identity, c.identity, PROV)],
                  uuid_loader=self._loader)
        self.db.commit()
        row = self.db.query_one(
            "SELECT shared_uuids, ancestor_only, descendant_only, rule_version "
            "FROM thread_edge WHERE ancestor_member_ref = ? AND "
            "descendant_member_ref = ?", (self._ref(a), self._ref(c)))
        self.assertIsNotNone(row)
        self.assertEqual((row[0], row[1], row[2]), (100, 0, 200))
        self.assertEqual(row[3], C.THREAD_RULE_VERSION)


class TestIndexProbe(StoreCase):
    """FR-11: the probe narrows the work to real collisions."""

    def _new_session(self, uuids) -> int:
        # NOT `_session`: StoreCase uses that name for its row counter.
        return self.session_with_turns(uuids)

    def test_a_session_colliding_with_nothing_returns_nothing(self) -> None:
        ref = register_source(self.db, src("a", ids(10)),
                              session_ref=self._new_session(ids(10)))
        self.db.commit()
        self.assertEqual(probe_related_members(self.db, ids(10, "other")), [])
        self.assertEqual(probe_related_members(self.db, ids(10)), [ref])

    def test_the_probe_finds_only_colliding_members(self) -> None:
        a = register_source(self.db, src("a", ids(10, "a")),
                            session_ref=self._new_session(ids(10, "a")))
        register_source(self.db, src("b", ids(10, "b")),
                        session_ref=self._new_session(ids(10, "b")))
        self.db.commit()
        self.assertEqual(probe_related_members(self.db, ids(3, "a")), [a])

    def test_an_empty_probe_input_asks_the_store_nothing(self) -> None:
        self.assertEqual(probe_related_members(self.db, []), [])

    def test_a_large_uuid_set_is_batched_not_truncated(self) -> None:
        many = ids(1000, "m")
        ref = register_source(self.db, src("big", many),
                              session_ref=self._new_session(many))
        self.db.commit()
        self.assertEqual(probe_related_members(self.db, many, batch=7), [ref])


class TestDetectForSession(StoreCase):
    """Task 3: one just-ingested session, end to end."""

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, name: str, uuids) -> Path:
        path = self.tmp / f"{name}.jsonl"
        path.write_text(
            # shaped as the adapter admits a turn: a conversational
            # type carrying a message object. A bare {"uuid": ...} row
            # produces no stored turn, so a fixture made of those would
            # prove nothing about the indexed universe.
            "\n".join(json.dumps({
                "type": "user", "uuid": u,
                "message": {"role": "user", "content": "x"},
                "timestamp": "2026-01-01T00:00:00Z",
            }) for u in uuids),
            encoding="utf-8")
        return path

    def test_several_source_files_become_several_members_of_one_thread(self) -> None:
        """Job A: the adapter folds a resume chain into ONE session; the
        chain itself is what A6 records."""
        base = ids(100, "a")
        first = self._write("first", base)
        second = self._write("second", base + ids(50, "b"))
        session = self.session_with_turns(base + ids(50, "b"))
        stats = detect_for_session(
            self.db, copilot="claude-code", native_session_id="s-chain",
            session_ref=session, source_files=[first, second])
        self.db.commit()

        self.assertEqual(stats["threads"], 1)
        members = self.db.query(
            "SELECT source_key, session_ref FROM thread_member WHERE thread_ref IS NOT NULL")
        self.assertEqual(len(members), 2)
        self.assertEqual({m[1] for m in members}, {session},
                         "both members resolve to the one session row")
        edges = self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge")
        self.assertEqual(len(edges), 1)

    def test_a_later_session_links_to_the_earlier_one_through_the_probe(self) -> None:
        base = ids(100, "a")
        earlier = self._write("earlier", base)
        s1 = self.session_with_turns(base)
        detect_for_session(self.db, copilot="claude-code",
                           native_session_id="s1", session_ref=s1,
                           source_files=[earlier])
        self.db.commit()

        resumed = self._write("resumed", base + ids(60, "c"))
        s2 = self.session_with_turns(base + ids(60, "c"))
        stats = detect_for_session(self.db, copilot="claude-code",
                                   native_session_id="s2", session_ref=s2,
                                   source_files=[resumed])
        self.db.commit()

        self.assertEqual(stats["threads"], 1)
        edges = self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge")
        self.assertEqual(len(edges), 1)
        roots = self.db.query_one(
            "SELECT COUNT(*) FROM thread_member WHERE is_root = ?", (True,))[0]
        self.assertEqual(roots, 1)

    def test_detection_is_idempotent(self) -> None:
        base = ids(100, "a")
        path = self._write("one", base)
        session = self.session_with_turns(base)
        detect_for_session(self.db, copilot="claude-code", native_session_id="s",
                           session_ref=session, source_files=[path])
        before = (self.db.query("SELECT * FROM thread_member"),
                  self.db.query("SELECT * FROM thread_edge"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s",
                           session_ref=session, source_files=[path])
        self.db.commit()
        after = (self.db.query("SELECT * FROM thread_member"),
                 self.db.query("SELECT * FROM thread_edge"))
        self.assertEqual(before, after)

    def test_an_unrelated_session_leaves_other_threads_untouched(self) -> None:
        base = ids(100, "a")
        one = self._write("one", base)
        two = self._write("two", base + ids(40, "b"))
        s1 = self.session_with_turns(base + ids(40, "b"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s1",
                           session_ref=s1, source_files=[one, two])
        self.db.commit()
        edges_before = self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge")

        far = self._write("far", ids(80, "z"))
        s2 = self.session_with_turns(ids(80, "z"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s2",
                           session_ref=s2, source_files=[far])
        self.db.commit()

        self.assertEqual(
            self.db.query(
                "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge"),
            edges_before, "an unreached thread is not reconciled")

    def test_a_session_with_no_source_files_is_a_no_op(self) -> None:
        stats = detect_for_session(self.db, copilot="claude-code",
                                   native_session_id="s", session_ref=1,
                                   source_files=[])
        self.assertEqual(stats["threads"], 0)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_member")[0], 0)


class TestEvidenceUniverseMatchesTheIndex(StoreCase):
    """A6 must read exactly what `copilot_turn.uuid` holds.

    The probe searches stored turn uuids. Reading every record instead
    would store shared/dropped/added counts no query over the index
    could reproduce, and would let a pair "collide" on a record the
    probe can never return.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, self.tmp, ignore_errors=True)

    def _mixed(self, name: str, turn_uuids, noise_uuids) -> Path:
        rows = [
            {"type": "user", "uuid": u,
             "message": {"role": "user", "content": "x"}}
            for u in turn_uuids
        ] + [
            # records the adapter never admits: no message, or a
            # non-conversational type
            {"type": "user", "uuid": n} for n in noise_uuids[: len(noise_uuids) // 2]
        ] + [
            {"type": "last-prompt", "uuid": n,
             "message": {"role": "user", "content": "x"}}
            for n in noise_uuids[len(noise_uuids) // 2:]
        ]
        path = self.tmp / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return path

    def test_the_reader_admits_exactly_the_adapters_turn_records(self) -> None:
        path = self._mixed("m", ids(10, "t"), ids(40, "n"))
        found = uuids_from_transcript(path)
        self.assertEqual(found, frozenset(ids(10, "t")),
                         "noise records must not enter the evidence")

    def test_stored_turns_and_read_uuids_are_the_same_set(self) -> None:
        turn_uuids = ids(12, "t")
        path = self._mixed("s", turn_uuids, ids(30, "n"))
        session = self.session_with_turns(turn_uuids)
        stored = {r[0] for r in self.db.query(
            "SELECT uuid FROM copilot_turn WHERE session_id = ?", (session,))}
        self.assertEqual(uuids_from_transcript(path), frozenset(stored))

    def test_evidence_computed_from_records_would_be_unreproducible(self) -> None:
        """The counts A6 stores must be recoverable from the index."""
        shared = ids(20, "t")
        a = self._mixed("a", shared, ids(50, "na"))
        b = self._mixed("b", shared + ids(9, "tb"), ids(70, "nb"))
        ua, ub = uuids_from_transcript(a), uuids_from_transcript(b)
        self.assertEqual(len(ua & ub), 20)
        self.assertEqual(len(ub - ua), 9)
        self.assertEqual(len(ua - ub), 0)

    def test_a_noise_only_collision_is_invisible_to_both(self) -> None:
        a = self._mixed("x", ids(10, "t"), ids(20, "shared_noise"))
        b = self._mixed("y", ids(10, "u"), ids(20, "shared_noise"))
        ua, ub = uuids_from_transcript(a), uuids_from_transcript(b)
        self.assertEqual(ua & ub, frozenset(),
                         "a collision the probe cannot see must not make a thread")
        self.assertIsNone(classify_pair(
            SourceRef("claude-code", str(a), "a", ua),
            SourceRef("claude-code", str(b), "b", ub), PROV))


class TestNativeGroupProvenance(StoreCase):
    """Job A's own evidence must reach the stored edge."""

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, name: str, uuids) -> Path:
        path = self.tmp / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps({
            "type": "user", "uuid": u,
            "message": {"role": "user", "content": "x"},
        }) for u in uuids), encoding="utf-8")
        return path

    def test_two_transcripts_of_ONE_session_store_native_group(self) -> None:
        base = ids(100, "a")
        first = self._write("first", base)
        second = self._write("second", base + ids(50, "b"))
        session = self.session_with_turns(base + ids(50, "b"))
        detect_for_session(self.db, copilot="claude-code",
                           native_session_id="s-chain", session_ref=session,
                           source_files=[first, second])
        self.db.commit()
        provenances = [r[0] for r in self.db.query(
            "SELECT provenance FROM thread_edge")]
        self.assertEqual(provenances, [C.THREAD_PROVENANCE_NATIVE_GROUP],
                         "the adapter grouped these two, and the edge says so")

    def test_a_cross_session_edge_stays_uuid_containment(self) -> None:
        base = ids(100, "a")
        earlier = self._write("earlier", base)
        s1 = self.session_with_turns(base)
        detect_for_session(self.db, copilot="claude-code", native_session_id="s1",
                           session_ref=s1, source_files=[earlier])
        self.db.commit()

        resumed = self._write("resumed", base + ids(60, "c"))
        s2 = self.session_with_turns(base + ids(60, "c"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s2",
                           session_ref=s2, source_files=[resumed])
        self.db.commit()
        provenances = [r[0] for r in self.db.query(
            "SELECT provenance FROM thread_edge")]
        self.assertEqual(provenances, [C.THREAD_PROVENANCE_UUID_CONTAINMENT],
                         "the probe found this one, not the grouping")

    def test_both_provenances_coexist_in_one_thread(self) -> None:
        base = ids(100, "a")
        s1_files = [self._write("p1", base), self._write("p2", base + ids(40, "b"))]
        s1 = self.session_with_turns(base + ids(40, "b"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s1",
                           session_ref=s1, source_files=s1_files)
        self.db.commit()

        later = self._write("p3", base + ids(40, "b") + ids(70, "c"))
        s2 = self.session_with_turns(base + ids(40, "b") + ids(70, "c"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s2",
                           session_ref=s2, source_files=[later])
        self.db.commit()
        counts: dict = {}
        for (provenance,) in self.db.query("SELECT provenance FROM thread_edge"):
            counts[provenance] = counts.get(provenance, 0) + 1
        self.assertEqual(counts, {C.THREAD_PROVENANCE_NATIVE_GROUP: 1,
                                  C.THREAD_PROVENANCE_UUID_CONTAINMENT: 1})

    def test_a_same_group_pair_that_fails_the_rule_still_gets_no_edge(self) -> None:
        """Provenance authorizes nothing, even Job A's own."""
        first = self._write("f", ids(60, "x"))
        second = self._write("s", ids(60, "y"))     # disjoint
        session = self.session_with_turns(ids(60, "x") + ids(60, "y"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s",
                           session_ref=session, source_files=[first, second])
        self.db.commit()
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 0)

    def test_native_group_survives_a_later_reclassification(self) -> None:
        """The grouping fact is durable: re-reading a neighbour must not
        decay the label to uuid_containment."""
        base = ids(100, "a")
        pair = [self._write("q1", base), self._write("q2", base + ids(40, "b"))]
        s1 = self.session_with_turns(base + ids(40, "b"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s1",
                           session_ref=s1, source_files=pair)
        self.db.commit()

        for _ in range(2):
            later = self._write("q3", base + ids(40, "b") + ids(90, "c"))
            s2 = self.session_with_turns(base + ids(40, "b") + ids(90, "c"))
            detect_for_session(self.db, copilot="claude-code",
                               native_session_id="s2", session_ref=s2,
                               source_files=[later])
            self.db.commit()

        native = self.db.query_one(
            "SELECT COUNT(*) FROM thread_edge WHERE provenance = ?",
            (C.THREAD_PROVENANCE_NATIVE_GROUP,))[0]
        self.assertEqual(native, 1, "the grouping fact must not decay")

    def test_native_group_survives_being_reduced_away_and_restored(self) -> None:
        """The grouping fact lives on the MEMBERS, so it cannot be lost
        with the edge that reduction deletes.

        A and C are one adapter group (A->C native). A cross-session B
        lands between them, so A->C is reduced away. B is then
        invalidated; A->C reappears — and must still say native_group.
        """
        base = ids(100, "a")
        a_file = self._write("ga", base)
        c_file = self._write("gc", base + ids(200, "c"))
        s1 = self.session_with_turns(base + ids(200, "c"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="grp",
                           session_ref=s1, source_files=[a_file, c_file])
        self.db.commit()
        self.assertEqual(
            [r[0] for r in self.db.query("SELECT provenance FROM thread_edge")],
            [C.THREAD_PROVENANCE_NATIVE_GROUP], "pass 1: A->C is native")

        # pass 2 — a DIFFERENT session lands between them
        b_file = self._write("gb", base + ids(60, "c"))
        s2 = self.session_with_turns(base + ids(60, "c"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="other",
                           session_ref=s2, source_files=[b_file])
        self.db.commit()
        pairs = self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge")
        self.assertEqual(len(pairs), 2, "pass 2: reduced to A->B->C")
        self.assertEqual(
            self.db.query_one(
                "SELECT COUNT(*) FROM thread_edge WHERE provenance = ?",
                (C.THREAD_PROVENANCE_NATIVE_GROUP,))[0], 0,
            "the native edge was reduced away, so nothing could seed from it")

        # pass 3 — B is re-read and no longer relates to C
        rewritten = self._write("gb", base + ids(400, "q"))
        s2b = self.session_with_turns(base + ids(400, "q"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="other",
                           session_ref=s2b, source_files=[rewritten])
        self.db.commit()

        restored = self.db.query(
            "SELECT provenance FROM thread_edge WHERE ancestor_member_ref = "
            "(SELECT id FROM thread_member WHERE source_key = ?) AND "
            "descendant_member_ref = "
            "(SELECT id FROM thread_member WHERE source_key = ?)",
            (str(a_file), str(c_file)))
        self.assertEqual([r[0] for r in restored],
                         [C.THREAD_PROVENANCE_NATIVE_GROUP],
                         "A->C came back, and it is still a grouping fact")


class TestUnreadableDirectSource(StoreCase):
    """A direct input that cannot be read is never authoritative."""

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, name: str, uuids) -> Path:
        path = self.tmp / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps({
            "type": "user", "uuid": u,
            "message": {"role": "user", "content": "x"},
        }) for u in uuids), encoding="utf-8")
        return path

    def test_an_edge_survives_a_re_detect_with_the_source_unreadable(self) -> None:
        base = ids(100, "a")
        first = self._write("u1", base)
        second = self._write("u2", base + ids(50, "b"))
        session = self.session_with_turns(base + ids(50, "b"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s",
                           session_ref=session, source_files=[first, second])
        self.db.commit()
        before = self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge")
        self.assertEqual(len(before), 1)

        # the first transcript is pruned between the adapter's load and
        # this detection
        first.unlink()
        detect_for_session(self.db, copilot="claude-code", native_session_id="s",
                           session_ref=session, source_files=[first, second])
        self.db.commit()

        after = self.db.query(
            "SELECT ancestor_member_ref, descendant_member_ref FROM thread_edge")
        self.assertEqual(after, before,
                         "an unreadable direct source must not retire its own edge")
        self.assertEqual(
            self.db.query_one(
                "SELECT source_available FROM thread_member WHERE source_key = ?",
                (str(first),))[0], 0,
            "and it must be recorded unavailable")

    def test_the_readable_sibling_stays_available(self) -> None:
        base = ids(100, "a")
        first = self._write("v1", base)
        second = self._write("v2", base + ids(50, "b"))
        session = self.session_with_turns(base + ids(50, "b"))
        detect_for_session(self.db, copilot="claude-code", native_session_id="s",
                           session_ref=session, source_files=[first, second])
        first.unlink()
        detect_for_session(self.db, copilot="claude-code", native_session_id="s",
                           session_ref=session, source_files=[first, second])
        self.db.commit()
        self.assertEqual(
            self.db.query_one(
                "SELECT source_available FROM thread_member WHERE source_key = ?",
                (str(second),))[0], 1)


class TestBackfill(StoreCase):
    """FR-13: rebuild lineage for what the store can still NAME."""

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, name: str, uuids) -> Path:
        path = self.tmp / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps({
            "type": "user", "uuid": u,
            "message": {"role": "user", "content": "x"},
        }) for u in uuids), encoding="utf-8")
        return path

    def _ingested(self, name: str, uuids, session_id: str) -> Path:
        """A source as ingest would have left it: a session row, its
        turns, and an ingest_state row naming the file."""
        path = self._write(name, uuids)
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id) "
            "VALUES (?, ?, ?) RETURNING id",
            ("claude-code", session_id, "local"))
        for index, value in enumerate(uuids):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid) "
                "VALUES (?, ?, ?, ?)", (sid, index, "user", value))
        self.db.execute(
            "INSERT INTO ingest_state (copilot, source_file, last_session_id) "
            "VALUES (?, ?, ?)", ("claude-code", str(path), session_id))
        self.db.commit()
        return path

    def test_it_rebuilds_a_chain_nothing_had_detected(self) -> None:
        base = ids(100, "a")
        self._ingested("b1", base, "s1")
        self._ingested("b2", base + ids(60, "b"), "s2")
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 0)

        stats = backfill(self.db)
        self.db.commit()
        self.assertEqual(stats["known_sources"], 2)
        self.assertEqual(stats["available"], 2)
        self.assertEqual(stats["unavailable"], 0)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 1)

    def test_it_binds_each_member_to_its_session_row(self) -> None:
        base = ids(100, "a")
        self._ingested("c1", base, "s1")
        self._ingested("c2", base + ids(60, "b"), "s2")
        backfill(self.db)
        self.db.commit()
        refs = [r[0] for r in self.db.query(
            "SELECT session_ref FROM thread_member ORDER BY id")]
        self.assertTrue(all(r is not None for r in refs),
                        "a backfilled member resolves to its stored session")

    def test_it_is_idempotent(self) -> None:
        base = ids(100, "a")
        self._ingested("d1", base, "s1")
        self._ingested("d2", base + ids(60, "b"), "s2")
        backfill(self.db)
        self.db.commit()
        before = (self.db.query("SELECT * FROM thread_member ORDER BY id"),
                  self.db.query("SELECT * FROM thread_edge ORDER BY id"))
        backfill(self.db)
        self.db.commit()
        after = (self.db.query("SELECT * FROM thread_member ORDER BY id"),
                 self.db.query("SELECT * FROM thread_edge ORDER BY id"))
        self.assertEqual(before, after)

    def test_a_known_but_missing_source_is_unavailable_INSIDE_the_denominator(self) -> None:
        base = ids(100, "a")
        gone = self._ingested("e1", base, "s1")
        self._ingested("e2", base + ids(60, "b"), "s2")
        gone.unlink()

        stats = backfill(self.db)
        self.db.commit()
        self.assertEqual(stats["known_sources"], 2, "it is still NAMED by the store")
        self.assertEqual(stats["unavailable"], 1)
        self.assertEqual(stats["available"], 1)
        self.assertEqual(
            self.db.query_one(
                "SELECT source_available FROM thread_member WHERE source_key = ?",
                (str(gone),))[0], 0)
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 0,
                         "no lineage is guessed for a source that cannot be read")

    def test_an_unknown_historical_source_is_OUTSIDE_the_denominator(self) -> None:
        """A transcript deleted before its path ever reached
        ingest_state or thread_member is undiscoverable: nothing records
        that it existed, so it cannot be counted as a gap."""
        base = ids(100, "a")
        self._ingested("f1", base, "s1")
        phantom = self.tmp / "never-recorded.jsonl"
        self.assertFalse(phantom.exists())

        stats = backfill(self.db)
        self.db.commit()
        self.assertEqual(stats["known_sources"], 1)
        self.assertEqual(stats["unavailable"], 0)
        self.assertEqual(stats["coverage_basis"], "known_sources",
                         "coverage is named as known-source coverage, never total")

    def test_a_source_known_only_to_thread_member_is_in_reach(self) -> None:
        base = ids(100, "a")
        self._ingested("g1", base, "s1")
        orphan = self._write("g2", base + ids(60, "b"))
        register_source(self.db, src("g2", []))
        self.db.execute(
            "UPDATE thread_member SET source_key = ?, native_session_id = ? "
            "WHERE source_key = ?", (str(orphan), "s2", "/p/g2.jsonl"))
        self.db.commit()

        stats = backfill(self.db)
        self.db.commit()
        self.assertEqual(stats["known_sources"], 2,
                         "ingest_state and thread_member are both registries")
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 1)

    def test_an_empty_store_reports_nothing_rather_than_failing(self) -> None:
        stats = backfill(self.db)
        self.assertEqual(stats["known_sources"], 0)
        self.assertEqual(stats["coverage_basis"], "known_sources")

    def test_two_transcripts_of_one_session_keep_native_group(self) -> None:
        base = ids(100, "a")
        first = self._ingested("h1", base, "s-same")
        second = self._write("h2", base + ids(40, "b"))
        self.db.execute(
            "INSERT INTO ingest_state (copilot, source_file, last_session_id) "
            "VALUES (?, ?, ?)", ("claude-code", str(second), "s-same"))
        self.db.commit()

        backfill(self.db)
        self.db.commit()
        self.assertEqual(
            [r[0] for r in self.db.query("SELECT provenance FROM thread_edge")],
            [C.THREAD_PROVENANCE_NATIVE_GROUP],
            "the backfill recovers Job A's grouping, not just the uuids")
        self.assertTrue(first.exists())


class TestThreadsCliContract(unittest.TestCase):
    """A6's command follows the A1 command-wide exit contract."""

    def _run(self, args, env_extra=None):
        import os
        import subprocess
        repo = Path(__file__).resolve().parents[3]
        env = {**os.environ, "PYTHONPATH": f"{repo / 'scripts'}:{repo}"}
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, "-m", "session_analytics", "threads", *args],
            capture_output=True, text=True, env=env, cwd=str(repo),
        )

    def test_a_schema_mismatch_is_EXIT_RUNTIME_with_the_remedy(self) -> None:
        tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, tmp, ignore_errors=True)
        db_path = tmp / "old.db"
        # a store that has the table but not a column the current schema
        # requires: exactly what check_schema refuses
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE copilot_tool_result (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        result = self._run(["--backfill", "--db", f"sqlite:///{db_path}"],
                           {"CCT_SA_DB": f"sqlite:///{db_path}"})
        self.assertEqual(result.returncode, C.EXIT_RUNTIME,
                         f"expected EXIT_RUNTIME; stderr={result.stderr[-400:]}")
        self.assertIn("recreate the store", result.stderr,
                      "the remedy must reach the user")
        self.assertNotIn("Traceback", result.stderr,
                         "a known condition must not surface as a crash")

    def test_no_backfill_flag_is_a_usage_error(self) -> None:
        tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, tmp, ignore_errors=True)
        result = self._run(["--db", f"sqlite:///{tmp / 'x.db'}"],
                           {"CCT_SA_DB": f"sqlite:///{tmp / 'x.db'}"})
        self.assertEqual(result.returncode, C.EXIT_USAGE)
        self.assertIn("--backfill", result.stderr)


class TestThreadFigures(StoreCase):
    """FR-10: distinct turn uuids, turn-grain metrics only."""

    def _make_session(self, uuids, *, cost=0.0, tokens=0, null_turns=0,
                      model="sonnet") -> int:
        self._session_counter = getattr(self, "_session_counter", 0) + 1
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id, "
            "turn_count) VALUES (?, ?, ?, ?) RETURNING id",
            ("claude-code", f"fig{self._session_counter}", "local",
             len(uuids) + null_turns))
        for index, value in enumerate(uuids):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid, "
                "cost_usd, tokens_input, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, index, "user", value, cost, tokens, model))
        for extra in range(null_turns):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid, "
                "cost_usd, tokens_input, model) VALUES (?, ?, ?, NULL, ?, ?, ?)",
                (sid, len(uuids) + extra, "user", 99.0, 999, model))
        self.db.commit()
        return int(sid)

    def _thread_with(self, *members) -> int:
        thread = allocate_thread(self.db)
        for name, uuids, session_ref in members:
            ref = register_source(self.db, src(name, uuids), session_ref=session_ref)
            self.db.execute("UPDATE thread_member SET thread_ref = ? WHERE id = ?",
                            (thread, ref))
        self.db.commit()
        return thread

    def test_a_replayed_turn_is_counted_ONCE(self) -> None:
        shared = ids(90, "s")
        ancestor = shared
        descendant = shared + ids(10, "d")
        thread = self._thread_with(
            ("anc", ancestor, self._make_session(ancestor, cost=1.0, tokens=10)),
            ("desc", descendant, self._make_session(descendant, cost=1.0, tokens=10)),
        )
        figures = thread_figures(self.db, thread)
        self.assertEqual(figures["turns"], 100, "90 shared + 10 new, not 190")
        self.assertAlmostEqual(figures["cost_usd"], 100.0)
        self.assertEqual(figures["tokens_input"], 1000)

    def test_summing_the_session_figures_would_be_wrong(self) -> None:
        """The number the rule exists to prevent, computed alongside."""
        shared = ids(90, "s")
        thread = self._thread_with(
            ("anc", shared, self._make_session(shared)),
            ("desc", shared + ids(10, "d"), self._make_session(shared + ids(10, "d"))),
        )
        summed = sum(r[0] for r in self.db.query(
            "SELECT s.turn_count FROM copilot_session s "
            "JOIN thread_member m ON m.session_ref = s.id WHERE m.thread_ref = ?",
            (thread,)))
        self.assertEqual(summed, 190)
        self.assertEqual(thread_figures(self.db, thread)["turns"], 100)

    def test_a_null_uuid_turn_is_excluded_from_every_thread_figure(self) -> None:
        uuids = ids(10, "n")
        thread = self._thread_with(
            ("only", uuids, self._make_session(uuids, cost=1.0, tokens=5, null_turns=3)))
        figures = thread_figures(self.db, thread)
        self.assertEqual(figures["turns"], 10, "the three null-uuid turns are out")
        self.assertAlmostEqual(figures["cost_usd"], 10.0)
        self.assertEqual(figures["tokens_input"], 50)

    def test_tool_calls_and_errors_are_deduplicated_too(self) -> None:
        shared = ids(4, "t")
        s1 = self._make_session(shared)
        s2 = self._make_session(shared + ids(1, "x"))
        for session in (s1, s2):
            turn = self.db.query_one(
                "SELECT id FROM copilot_turn WHERE session_id = ? ORDER BY id",
                (session,))[0]
            call = self.db.insert_returning_id(
                "INSERT INTO copilot_tool_call (turn_id, tool_name, sequence_num) "
                "VALUES (?, ?, ?) RETURNING id", (turn, "Bash", 0))
            self.db.execute(
                "INSERT INTO copilot_tool_result (tool_call_id, is_error) "
                "VALUES (?, ?)", (call, True))
        self.db.commit()
        thread = self._thread_with(("a", shared, s1), ("b", shared + ids(1, "x"), s2))
        figures = thread_figures(self.db, thread)
        self.assertEqual(figures["tool_calls"], 1,
                         "the same replayed turn's tool call is not counted twice")
        self.assertEqual(figures["errors"], 1)

    def test_only_turn_grain_metrics_are_offered(self) -> None:
        """A session-level figure must not be reachable as a thread
        figure — that is the whole trap."""
        for forbidden in ("turn_count", "tool_call_count", "error_count",
                          "duration_seconds"):
            self.assertNotIn(forbidden, THREAD_ADDITIVE_TURN_COLUMNS)

    def test_the_figure_is_stable_across_repeated_reads(self) -> None:
        shared = ids(20, "s")
        thread = self._thread_with(
            ("a", shared, self._make_session(shared)),
            ("b", shared + ids(5, "d"), self._make_session(shared + ids(5, "d"))),
        )
        self.assertEqual(thread_figures(self.db, thread),
                         thread_figures(self.db, thread))

    def test_a_member_with_no_session_contributes_nothing(self) -> None:
        uuids = ids(6, "u")
        thread = self._thread_with(
            ("stored", uuids, self._make_session(uuids)),
            ("unstored", ids(50, "v"), None),
        )
        self.assertEqual(thread_figures(self.db, thread)["turns"], 6)

    def test_figures_by_session_resolve_through_a_redirect(self) -> None:
        uuids = ids(8, "w")
        session = self._make_session(uuids)
        thread = self._thread_with(("a", uuids, session))
        survivor = allocate_thread(self.db)
        self.db.execute("UPDATE thread_member SET thread_ref = ? WHERE thread_ref = ?",
                        (survivor, thread))
        self.db.execute(
            "UPDATE session_thread SET status = ?, redirected_to_ref = ? WHERE id = ?",
            (C.THREAD_STATUS_REDIRECTED, survivor, thread))
        self.db.commit()
        result = thread_figures_for_session(self.db, session)
        self.assertEqual(result["turns"], 8)
        self.assertFalse(result["ambiguous"])

    def test_a_session_in_no_thread_has_no_thread_figures(self) -> None:
        self.assertIsNone(thread_figures_for_session(self.db, self._make_session(ids(3))))

    def test_the_declared_output_contract_is_COMPLETE(self) -> None:
        uuids = ids(4, "c")
        thread = self._thread_with(("a", uuids, self._make_session(uuids)))
        self.assertEqual(set(thread_figures(self.db, thread)),
                         set(THREAD_FIGURE_FIELDS),
                         "every returned key must be declared, and vice versa")

    def test_an_entirely_unpriced_thread_reports_None_not_zero(self) -> None:
        uuids = ids(5, "p")
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id) "
            "VALUES (?, ?, ?) RETURNING id", ("claude-code", "unpriced", "local"))
        for index, value in enumerate(uuids):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid, "
                "cost_usd, model) VALUES (?, ?, ?, ?, NULL, ?)",
                (sid, index, "user", value, "sonnet"))
        self.db.commit()
        thread = self._thread_with(("only", uuids, int(sid)))
        figures = thread_figures(self.db, thread)
        self.assertIsNone(figures["cost_usd"], "unknown cost is never free")
        self.assertEqual(figures["priced_turns"], 0)
        self.assertEqual(figures["priceable_turns"], 5,
                         "they name a model, so a price was possible")

    def test_partial_pricing_exposes_its_coverage(self) -> None:
        uuids = ids(6, "q")
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id) "
            "VALUES (?, ?, ?) RETURNING id", ("claude-code", "partial", "local"))
        for index, value in enumerate(uuids):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid, "
                "cost_usd, model) VALUES (?, ?, ?, ?, ?, ?)",
                (sid, index, "user", value, 2.0 if index < 2 else None, "sonnet"))
        self.db.commit()
        thread = self._thread_with(("only", uuids, int(sid)))
        figures = thread_figures(self.db, thread)
        self.assertAlmostEqual(figures["cost_usd"], 4.0)
        self.assertEqual((figures["priced_turns"], figures["priceable_turns"]), (2, 6),
                         "the figure is real but covers a third of the thread")

    def test_a_turn_with_no_model_is_not_priceable(self) -> None:
        uuids = ids(3, "r")
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id) "
            "VALUES (?, ?, ?) RETURNING id", ("claude-code", "nomodel", "local"))
        for index, value in enumerate(uuids):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid) "
                "VALUES (?, ?, ?, ?)", (sid, index, "user", value))
        self.db.commit()
        thread = self._thread_with(("only", uuids, int(sid)))
        figures = thread_figures(self.db, thread)
        self.assertEqual(figures["priceable_turns"], 0,
                         "no model means it was never a candidate for a price")
        self.assertIsNone(figures["cost_usd"])

    def test_a_session_spanning_two_threads_is_reported_as_ambiguous(self) -> None:
        """thread_member is source-grained and nothing constrains one
        session's members to a single thread."""
        uuids = ids(5, "amb")
        session = self._make_session(uuids)
        left, right = allocate_thread(self.db), allocate_thread(self.db)
        for name, thread in (("left", left), ("right", right)):
            ref = register_source(self.db, src(name, uuids), session_ref=session)
            self.db.execute("UPDATE thread_member SET thread_ref = ? WHERE id = ?",
                            (thread, ref))
        self.db.commit()

        self.assertEqual(threads_for_session(self.db, session), sorted([left, right]))
        result = thread_figures_for_session(self.db, session)
        self.assertTrue(result["ambiguous"])
        self.assertEqual(result["thread_refs"], sorted([left, right]))
        self.assertNotIn("turns", result,
                         "an ambiguous answer must not look like a figure")


class TestLineageSupport(StoreCase):
    """FR-14: support is a property of the ADAPTER, not of the outcome."""

    def _session(self, copilot: str, name: str) -> int:
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id) "
            "VALUES (?, ?, ?) RETURNING id", (copilot, name, "local"))
        self.db.commit()
        return int(sid)

    def test_claude_code_exposes_a_native_identity(self) -> None:
        self.assertEqual(lineage_support(C.COPILOT_CLAUDE_CODE),
                         C.LINEAGE_SUPPORT_NATIVE)

    def test_the_other_sources_cannot_express_lineage(self) -> None:
        for copilot in (C.COPILOT_AIDER, C.COPILOT_PI):
            self.assertEqual(lineage_support(copilot),
                             C.LINEAGE_SUPPORT_UNSUPPORTED)

    def test_an_unknown_copilot_is_unsupported_not_assumed(self) -> None:
        self.assertEqual(lineage_support("not-a-copilot"),
                         C.LINEAGE_SUPPORT_UNSUPPORTED)

    def test_support_does_not_depend_on_a_link_being_found(self) -> None:
        """The distinction the requirement exists for."""
        lonely = self._session(C.COPILOT_CLAUDE_CODE, "lonely")
        aider = self._session(C.COPILOT_AIDER, "aider-one")

        lonely_answer = session_lineage(self.db, lonely)
        aider_answer = session_lineage(self.db, aider)

        # both have no thread — and they mean different things
        self.assertEqual(lonely_answer["thread_refs"], [])
        self.assertEqual(aider_answer["thread_refs"], [])
        self.assertEqual(lonely_answer["lineage_support"], C.LINEAGE_SUPPORT_NATIVE)
        self.assertEqual(aider_answer["lineage_support"],
                         C.LINEAGE_SUPPORT_UNSUPPORTED)
        self.assertTrue(lonely_answer["no_ancestor_found"])
        self.assertFalse(aider_answer["no_ancestor_found"],
                         "an unknowable must not read as a negative finding")

    def test_a_threaded_session_reports_its_thread_and_native_support(self) -> None:
        session = self._session(C.COPILOT_CLAUDE_CODE, "threaded")
        thread = allocate_thread(self.db)
        ref = register_source(self.db, src("t", ids(4)), session_ref=session)
        self.db.execute("UPDATE thread_member SET thread_ref = ? WHERE id = ?",
                        (thread, ref))
        self.db.commit()
        answer = session_lineage(self.db, session)
        self.assertEqual(answer["thread_refs"], [thread])
        self.assertEqual(answer["lineage_support"], C.LINEAGE_SUPPORT_NATIVE)
        self.assertFalse(answer["no_ancestor_found"])
        self.assertFalse(answer["ambiguous"])

    def test_every_registered_adapter_declares_the_capability(self) -> None:
        """A new adapter must state it rather than inherit a default."""
        from session_analytics.registry import get_adapter, list_adapter_ids
        for copilot in list_adapter_ids():
            adapter = get_adapter(copilot)
            self.assertTrue(hasattr(adapter, "exposes_turn_identity"),
                            f"{copilot} does not declare exposes_turn_identity")
            self.assertIsInstance(adapter.exposes_turn_identity, bool)

    def test_a_PARTIALLY_registered_registry_still_answers_correctly(self) -> None:
        """The non-empty registry is not a complete one.

        Registering one custom adapter first used to skip register_all()
        and make Claude Code report unsupported.
        """
        from session_analytics import _register
        from session_analytics.registry import register_adapter

        _register.unregister_all_for_tests()

        class Custom:
            copilot_id = "custom-one"
            exposes_turn_identity = False

        register_adapter("custom-one", Custom)
        try:
            self.assertEqual(lineage_support(C.COPILOT_CLAUDE_CODE),
                             C.LINEAGE_SUPPORT_NATIVE,
                             "a partial registry must not decide capability")
            self.assertEqual(lineage_support("custom-one"),
                             C.LINEAGE_SUPPORT_UNSUPPORTED)
        finally:
            _register.unregister_all_for_tests()
            _register.register_all()

    def test_an_adapter_omitting_the_capability_RAISES(self) -> None:
        """The protocol declares it, so omission is a defect — not a
        silent 'unsupported' for a source nobody considered."""
        from session_analytics import _register
        from session_analytics.registry import register_adapter

        class Silent:
            copilot_id = "silent-one"

        register_adapter("silent-one", Silent)
        try:
            with self.assertRaises(AttributeError):
                lineage_support("silent-one")
        finally:
            _register.unregister_all_for_tests()
            _register.register_all()

    def test_a_missing_session_is_not_found_not_unsupported(self) -> None:
        with self.assertRaises(SessionNotFound):
            session_lineage(self.db, 987654)

    def test_the_protocol_declares_the_capability(self) -> None:
        from session_analytics.contracts import SessionAdapter
        self.assertIn("exposes_turn_identity",
                      getattr(SessionAdapter, "__annotations__", {}))


class TestSchemaInvariants(StoreCase):
    """Every CHECK the database holds, proven to REJECT.

    A constraint nobody has seen refuse is a comment. These assert the
    write fails, so a future edit that drops a CHECK — or widens a
    column to nullable — fails here rather than silently admitting a
    contradictory row.
    """

    def _rejects(self, sql: str, params=(), *, kind: str = "CHECK") -> None:
        """The DATABASE refused a validly formed write.

        `IntegrityError` specifically, not any Exception: a SQL syntax
        error, a wrong parameter count or a missing column would
        otherwise "prove" a constraint that does not exist. The message
        is checked too, so a UNIQUE violation cannot stand in for a
        CHECK.
        """
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            self.db.execute(sql, params)
            self.db.commit()
        self.assertIn(kind, str(caught.exception),
                      f"expected a {kind} violation, got: {caught.exception}")

    def _thread(self) -> int:
        return int(self.db.insert_returning_id(
            "INSERT INTO session_thread (thread_id) VALUES (?) RETURNING id",
            ("t-fixture",)))

    def _member(self, key: str) -> int:
        return int(self.db.insert_returning_id(
            "INSERT INTO thread_member (copilot, native_session_id, source_key) "
            "VALUES (?, ?, ?) RETURNING id", ("claude-code", "s", key)))

    # ── session_thread ────────────────────────────────────────────────

    def test_status_is_a_closed_set(self) -> None:
        self._rejects("INSERT INTO session_thread (thread_id, status) VALUES (?, ?)",
                      ("t1", "merged"))

    def test_an_active_thread_carries_no_target(self) -> None:
        survivor = self._thread()
        self._rejects(
            "INSERT INTO session_thread (thread_id, status, redirected_to_ref) "
            "VALUES (?, ?, ?)", ("t2", C.THREAD_STATUS_ACTIVE, survivor))

    def test_a_redirected_thread_must_have_one(self) -> None:
        self._rejects("INSERT INTO session_thread (thread_id, status) VALUES (?, ?)",
                      ("t3", C.THREAD_STATUS_REDIRECTED))

    def test_a_self_redirect_is_unwritable(self) -> None:
        thread = self._thread()
        self.db.commit()
        self._rejects(
            "UPDATE session_thread SET status = ?, redirected_to_ref = ? WHERE id = ?",
            (C.THREAD_STATUS_REDIRECTED, thread, thread))

    def test_member_count_is_never_negative(self) -> None:
        self._rejects(
            "INSERT INTO session_thread (thread_id, member_count) VALUES (?, ?)",
            ("t4", -1))

    # ── thread_member ─────────────────────────────────────────────────

    def test_source_identity_is_globally_unique(self) -> None:
        self._member("/p/dup.jsonl")
        self.db.commit()
        self._rejects(
            "INSERT INTO thread_member (copilot, native_session_id, source_key) "
            "VALUES (?, ?, ?)", ("claude-code", "other", "/p/dup.jsonl"),
            kind="UNIQUE")

    def test_a_member_may_have_NO_thread(self) -> None:
        ref = self._member("/p/free.jsonl")
        self.db.commit()
        self.assertIsNone(self.db.query_one(
            "SELECT thread_ref FROM thread_member WHERE id = ?", (ref,))[0])

    def test_turn_count_is_never_negative(self) -> None:
        self._rejects(
            "INSERT INTO thread_member (copilot, native_session_id, source_key, "
            "turn_uuid_count) VALUES (?, ?, ?, ?)",
            ("claude-code", "s", "/p/neg.jsonl", -1))

    # ── thread_edge ───────────────────────────────────────────────────

    def _edge_sql(self) -> str:
        return (
            "INSERT INTO thread_edge (thread_ref, ancestor_member_ref, "
            "descendant_member_ref, provenance, shared_uuids, "
            "ancestor_containment, descendant_containment, ancestor_only, "
            "descendant_only, rule_version) VALUES (?,?,?,?,?,?,?,?,?,?)")

    def test_a_member_is_never_its_own_ancestor(self) -> None:
        thread, member = self._thread(), self._member("/p/self.jsonl")
        self.db.commit()
        self._rejects(self._edge_sql(),
                      (thread, member, member, PROV, 5, 0.9, 0.1, 1, 9,
                       C.THREAD_RULE_VERSION))

    def test_the_direction_test_itself_is_enforced(self) -> None:
        thread = self._thread()
        a, b = self._member("/p/d1.jsonl"), self._member("/p/d2.jsonl")
        self.db.commit()
        self._rejects(self._edge_sql(),
                      (thread, a, b, PROV, 5, 0.9, 0.1, 9, 1,
                       C.THREAD_RULE_VERSION))

    def test_an_edge_nobody_judged_is_unwritable(self) -> None:
        thread = self._thread()
        a, b = self._member("/p/n1.jsonl"), self._member("/p/n2.jsonl")
        self.db.commit()
        self._rejects(
            "INSERT INTO thread_edge (thread_ref, ancestor_member_ref, "
            "descendant_member_ref, provenance, shared_uuids, ancestor_only, "
            "descendant_only, rule_version) VALUES (?,?,?,?,?,?,?,?)",
            (thread, a, b, PROV, 5, 1, 9, C.THREAD_RULE_VERSION),
            # NOT NULL, not CHECK: the column itself refuses the omission,
            # which is stronger than a predicate on a written value
            kind="NOT NULL")

    def test_provenance_is_a_closed_set_in_the_DATABASE(self) -> None:
        thread = self._thread()
        a, b = self._member("/p/p1.jsonl"), self._member("/p/p2.jsonl")
        self.db.commit()
        self._rejects(self._edge_sql(),
                      (thread, a, b, "grouped_by_time", 5, 0.9, 0.1, 1, 9,
                       C.THREAD_RULE_VERSION))

    def test_containment_stays_within_zero_and_one(self) -> None:
        thread = self._thread()
        a, b = self._member("/p/c1.jsonl"), self._member("/p/c2.jsonl")
        self.db.commit()
        self._rejects(self._edge_sql(),
                      (thread, a, b, PROV, 5, 1.5, 0.1, 1, 9,
                       C.THREAD_RULE_VERSION))

    # ── thread_relation_candidate ─────────────────────────────────────

    def _candidate_sql(self) -> str:
        return (
            "INSERT INTO thread_relation_candidate (member_a_ref, member_b_ref, "
            "shared_uuids, containment_a, containment_b, a_only, b_only, "
            "candidate_kind, rule_version) VALUES (?,?,?,?,?,?,?,?,?)")

    def test_a_candidate_pair_is_distinct_and_canonical(self) -> None:
        a, b = self._member("/p/k1.jsonl"), self._member("/p/k2.jsonl")
        self.db.commit()
        # both are the SAME predicate: member_a_ref < member_b_ref
        self._rejects(self._candidate_sql(),
                      (a, a, 5, 0.9, 0.9, 0, 0, C.CANDIDATE_DUPLICATE_IDENTITY,
                       C.THREAD_RULE_VERSION))
        self._rejects(self._candidate_sql(),
                      (b, a, 5, 0.9, 0.9, 0, 0, C.CANDIDATE_DUPLICATE_IDENTITY,
                       C.THREAD_RULE_VERSION))

    def test_unequal_differences_would_be_an_EDGE_not_a_candidate(self) -> None:
        a, b = self._member("/p/u1.jsonl"), self._member("/p/u2.jsonl")
        self.db.commit()
        self._rejects(self._candidate_sql(),
                      (a, b, 5, 0.9, 0.9, 1, 4, C.CANDIDATE_DIRECTION_AMBIGUOUS,
                       C.THREAD_RULE_VERSION))

    def test_the_kind_must_agree_with_its_own_counts(self) -> None:
        a, b = self._member("/p/g1.jsonl"), self._member("/p/g2.jsonl")
        self.db.commit()
        self._rejects(self._candidate_sql(),
                      (a, b, 5, 0.9, 0.9, 3, 3, C.CANDIDATE_DUPLICATE_IDENTITY,
                       C.THREAD_RULE_VERSION))
        self._rejects(self._candidate_sql(),
                      (a, b, 5, 0.9, 0.9, 0, 0, C.CANDIDATE_DIRECTION_AMBIGUOUS,
                       C.THREAD_RULE_VERSION))

    def test_the_candidate_kind_is_a_closed_set(self) -> None:
        a, b = self._member("/p/w1.jsonl"), self._member("/p/w2.jsonl")
        self.db.commit()
        self._rejects(self._candidate_sql(),
                      (a, b, 5, 0.9, 0.9, 0, 0, "probably_same",
                       C.THREAD_RULE_VERSION))

    def test_a_valid_row_of_each_kind_is_ACCEPTED(self) -> None:
        """The refusals above mean nothing without this."""
        thread = self._thread()
        a, b = self._member("/p/ok1.jsonl"), self._member("/p/ok2.jsonl")
        self.db.commit()
        self.db.execute(self._edge_sql(),
                        (thread, a, b, PROV, 464, 0.953, 0.897, 23, 53,
                         C.THREAD_RULE_VERSION))
        c, d = self._member("/p/ok3.jsonl"), self._member("/p/ok4.jsonl")
        self.db.execute(self._candidate_sql(),
                        (c, d, 99, 0.9, 0.95, 0, 0,
                         C.CANDIDATE_DUPLICATE_IDENTITY, C.THREAD_RULE_VERSION))
        self.db.commit()
        self.assertEqual(self.db.query_one("SELECT COUNT(*) FROM thread_edge")[0], 1)
        self.assertEqual(
            self.db.query_one("SELECT COUNT(*) FROM thread_relation_candidate")[0], 1)

    # ── one case per PREDICATE, so removing either side of a compound
    #    CHECK fails here rather than staying green ───────────────────

    def test_edge_shared_uuids_is_never_negative(self) -> None:
        thread = self._thread()
        a, b = self._member("/p/s1.jsonl"), self._member("/p/s2.jsonl")
        self.db.commit()
        self._rejects(self._edge_sql(),
                      (thread, a, b, PROV, -1, 0.9, 0.1, 1, 9,
                       C.THREAD_RULE_VERSION))

    def test_edge_ancestor_containment_has_a_LOWER_bound(self) -> None:
        thread = self._thread()
        a, b = self._member("/p/l1.jsonl"), self._member("/p/l2.jsonl")
        self.db.commit()
        self._rejects(self._edge_sql(),
                      (thread, a, b, PROV, 5, -0.1, 0.1, 1, 9,
                       C.THREAD_RULE_VERSION))

    def test_edge_descendant_containment_has_BOTH_bounds(self) -> None:
        thread = self._thread()
        a, b = self._member("/p/m1.jsonl"), self._member("/p/m2.jsonl")
        self.db.commit()
        for value in (-0.5, 1.5):
            self._rejects(self._edge_sql(),
                          (thread, a, b, PROV, 5, 0.9, value, 1, 9,
                           C.THREAD_RULE_VERSION))

    def test_edge_difference_counts_are_never_negative(self) -> None:
        thread = self._thread()
        a, b = self._member("/p/q1.jsonl"), self._member("/p/q2.jsonl")
        self.db.commit()
        # ancestor_only negative (descendant_only still greater, so the
        # direction predicate is satisfied and only the bound can fire)
        self._rejects(self._edge_sql(),
                      (thread, a, b, PROV, 5, 0.9, 0.1, -1, 9,
                       C.THREAD_RULE_VERSION))
        # descendant_only negative
        self._rejects(self._edge_sql(),
                      (thread, a, b, PROV, 5, 0.9, 0.1, -9, -1,
                       C.THREAD_RULE_VERSION))

    def test_candidate_shared_uuids_is_never_negative(self) -> None:
        a, b = self._member("/p/cs1.jsonl"), self._member("/p/cs2.jsonl")
        self.db.commit()
        self._rejects(self._candidate_sql(),
                      (a, b, -1, 0.9, 0.9, 0, 0, C.CANDIDATE_DUPLICATE_IDENTITY,
                       C.THREAD_RULE_VERSION))

    def test_candidate_containment_a_has_both_bounds(self) -> None:
        a, b = self._member("/p/ca1.jsonl"), self._member("/p/ca2.jsonl")
        self.db.commit()
        for value in (-0.2, 1.2):
            self._rejects(self._candidate_sql(),
                          (a, b, 5, value, 0.9, 0, 0,
                           C.CANDIDATE_DUPLICATE_IDENTITY, C.THREAD_RULE_VERSION))

    def test_candidate_containment_b_has_both_bounds(self) -> None:
        a, b = self._member("/p/cb1.jsonl"), self._member("/p/cb2.jsonl")
        self.db.commit()
        for value in (-0.2, 1.2):
            self._rejects(self._candidate_sql(),
                          (a, b, 5, 0.9, value, 0, 0,
                           C.CANDIDATE_DUPLICATE_IDENTITY, C.THREAD_RULE_VERSION))

    def test_candidate_difference_counts_are_never_negative(self) -> None:
        """Equal AND negative, so the equality predicate is satisfied
        and only the non-negative bound can be what fires."""
        a, b = self._member("/p/cd1.jsonl"), self._member("/p/cd2.jsonl")
        self.db.commit()
        self._rejects(self._candidate_sql(),
                      (a, b, 5, 0.9, 0.9, -3, -3,
                       C.CANDIDATE_DIRECTION_AMBIGUOUS, C.THREAD_RULE_VERSION))


class TestThreadView(StoreCase):
    """FR-18: a partial order rendered as a tree, never a sequence."""

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, name: str, uuids) -> Path:
        path = self.tmp / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps({
            "type": "user", "uuid": u,
            "message": {"role": "user", "content": "x"},
        }) for u in uuids), encoding="utf-8")
        return path

    def _session(self, copilot: str, name: str, uuids=()) -> int:
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id) "
            "VALUES (?, ?, ?) RETURNING id", (copilot, name, "local"))
        for index, value in enumerate(uuids):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid) "
                "VALUES (?, ?, ?, ?)", (int(sid), index, "user", value))
        self.db.commit()
        return int(sid)

    def test_a_chain_nests_and_exposes_no_ordinal(self) -> None:
        base = ids(100, "a")
        files = [self._write("t1", base), self._write("t2", base + ids(50, "b"))]
        session = self._session(C.COPILOT_CLAUDE_CODE, "s1", base + ids(50, "b"))
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="s1", session_ref=session,
                           source_files=files)
        self.db.commit()

        view = thread_view(self.db, session)
        self.assertEqual(view["lineage_support"], C.LINEAGE_SUPPORT_NATIVE)
        tree = view["thread"]
        self.assertEqual(len(tree["roots"]), 1)
        self.assertEqual(len(tree["roots"][0]["children"]), 1)
        for key in ("index", "ordinal", "next", "order", "position"):
            self.assertNotIn(key, tree["roots"][0],
                             "a tree must not carry a sequence")

    def test_a_fork_renders_as_SIBLINGS_with_the_flag(self) -> None:
        base = ids(100, "f")
        root = self._write("r", base)
        left = self._write("l", base + ids(40, "L"))
        right = self._write("g", base + ids(40, "R"))
        session = self._session(C.COPILOT_CLAUDE_CODE, "fork", base)
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="fork", session_ref=session,
                           source_files=[root, left, right])
        self.db.commit()

        tree = thread_view(self.db, session)["thread"]
        self.assertTrue(tree["fork_suspected"])
        self.assertEqual(len(tree["roots"]), 1)
        self.assertEqual(len(tree["roots"][0]["children"]), 2,
                         "both branches are siblings, neither ordered first")

    def test_a_join_is_listed_APART_and_never_drawn_twice(self) -> None:
        left = self._write("jl", ids(40, "l"))
        right = self._write("jr", ids(40, "r"))
        joined = self._write("jj", ids(40, "l") + ids(40, "r") + ids(200, "n"))
        session = self._session(C.COPILOT_CLAUDE_CODE, "join", ids(40, "l"))
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="join", session_ref=session,
                           source_files=[left, right, joined])
        self.db.commit()

        tree = thread_view(self.db, session)["thread"]
        self.assertEqual(len(tree["joins"]), 1)
        self.assertEqual(len(tree["joins"][0]["ancestors"]), 2)

        def count(nodes) -> int:
            return sum(1 + count(n["children"]) for n in nodes)

        self.assertEqual(count(tree["roots"]), tree["member_count"],
                         "the joined member appears exactly once in the tree")

    def test_every_edge_carries_its_evidence_and_rule_version(self) -> None:
        base = ids(100, "e")
        files = [self._write("e1", base), self._write("e2", base + ids(30, "z"))]
        session = self._session(C.COPILOT_CLAUDE_CODE, "ev", base)
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="ev", session_ref=session,
                           source_files=files)
        self.db.commit()
        edge = thread_view(self.db, session)["thread"]["edges"][0]
        self.assertEqual(edge["provenance"], C.THREAD_PROVENANCE_NATIVE_GROUP)
        self.assertEqual((edge["shared_uuids"], edge["ancestor_only"],
                          edge["descendant_only"]), (100, 0, 30))
        self.assertEqual(edge["rule_version"], C.THREAD_RULE_VERSION)

    def test_an_unsupported_source_says_so_rather_than_going_blank(self) -> None:
        session = self._session(C.COPILOT_AIDER, "aider-one")
        view = thread_view(self.db, session)
        self.assertEqual(view["lineage_support"], C.LINEAGE_SUPPORT_UNSUPPORTED)
        self.assertIsNone(view["thread"])
        self.assertFalse(view["no_ancestor_found"],
                         "an unknowable is not a negative finding")

    def test_a_session_with_no_known_source_is_UNASSESSED(self) -> None:
        """Nothing was ever looked at, so nothing can be concluded."""
        session = self._session(C.COPILOT_CLAUDE_CODE, "alone")
        view = thread_view(self.db, session)
        self.assertEqual(view["lineage_support"], C.LINEAGE_SUPPORT_NATIVE)
        self.assertEqual(view["assessment"], "unassessed")
        self.assertFalse(view["no_ancestor_found"])

    def test_a_missing_session_raises_for_the_api_to_map_to_404(self) -> None:
        with self.assertRaises(SessionNotFound):
            thread_view(self.db, 987654)

    def test_coverage_is_named_as_known_source_coverage(self) -> None:
        base = ids(100, "c")
        files = [self._write("c1", base), self._write("c2", base + ids(30, "d"))]
        session = self._session(C.COPILOT_CLAUDE_CODE, "cov", base)
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="cov", session_ref=session,
                           source_files=files)
        self.db.commit()
        view = thread_view(self.db, session)
        self.assertEqual(view["coverage_basis"], "known_sources")
        self.assertEqual(
            (view["sources_known"], view["sources_available"],
             view["sources_unavailable"]), (2, 2, 0),
            "an explicit fraction, not a label")
        self.assertIn("threads it reaches", view["coverage_scope"])

    def test_a_CANDIDATE_ONLY_session_still_reports_its_candidate(self) -> None:
        """The case candidates matter most in: no edge, no thread."""
        pool = ids(50, "cc")
        session = self._session(C.COPILOT_CLAUDE_CODE, "cand", pool)
        files = [self._write("x1", pool), self._write("x2", pool)]
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="cand", session_ref=session,
                           source_files=files)
        self.db.commit()

        view = thread_view(self.db, session)
        self.assertIsNone(view["thread"], "identical sets make no edge")
        self.assertEqual(len(view["relation_candidates"]), 1,
                         "and the candidate must not vanish with the thread")
        self.assertEqual(view["relation_candidates"][0]["candidate_kind"],
                         C.CANDIDATE_DUPLICATE_IDENTITY)

    def test_a_candidate_is_found_when_the_attached_end_is_member_B(self) -> None:
        """Canonical row-id order puts the attached member on either
        side; querying one column hides half the candidates."""
        # registered FIRST, so the session's members get higher ids and
        # canonical order puts the attached one on the b side
        other = register_source(self.db, src("outsider", ids(5, "o")))
        self.db.commit()
        base = ids(100, "mb")
        files = [self._write("m1", base), self._write("m2", base + ids(30, "z"))]
        session = self._session(C.COPILOT_CLAUDE_CODE, "mb", base)
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="mb", session_ref=session,
                           source_files=files)
        self.db.commit()

        attached = min(int(r[0]) for r in self.db.query(
            "SELECT id FROM thread_member WHERE session_ref = ?", (session,)))
        self.db.execute(
            "INSERT INTO thread_relation_candidate (member_a_ref, member_b_ref, "
            "shared_uuids, containment_a, containment_b, a_only, b_only, "
            "candidate_kind, rule_version) VALUES (?,?,?,?,?,?,?,?,?)",
            (min(other, attached), max(other, attached), 9, 0.9, 0.9, 0, 0,
             C.CANDIDATE_DUPLICATE_IDENTITY, C.THREAD_RULE_VERSION))
        self.db.commit()
        self.assertGreater(attached, other,
                           "fixture intends the attached member to be member_b")

        found = thread_view(self.db, session)["relation_candidates"]
        self.assertTrue(any(c["member_b"] == attached for c in found),
                        "a candidate whose attached end is member_b must surface")

    def test_a_threadless_native_session_still_reports_coverage(self) -> None:
        session = self._session(C.COPILOT_CLAUDE_CODE, "bare")
        view = thread_view(self.db, session)
        self.assertIsNone(view["thread"])
        for key in ("sources_known", "sources_available", "sources_unavailable"):
            self.assertIn(key, view, "coverage must not vanish on the early return")

    def test_a_pre_A6_session_is_known_but_UNASSESSED(self) -> None:
        """An ingest_state row with no member: no completed assessment
        is stored. Usually detection never ran; the same durable state
        results from a pass rolled back before it committed, which is
        why the claim is about the store, not about what was tried."""
        base = ids(30, "h")
        path = self._write("hist", base)
        session = self._session(C.COPILOT_CLAUDE_CODE, "hist-sess", base)
        self.db.execute(
            "INSERT INTO ingest_state (copilot, source_file, last_session_id) "
            "VALUES (?, ?, ?)", (C.COPILOT_CLAUDE_CODE, str(path), "hist-sess"))
        self.db.commit()

        view = thread_view(self.db, session)
        self.assertEqual(view["sources_known"], 1, "the registry names it")
        self.assertEqual(view["sources_assessed"], 0, "but nothing assessed it")
        self.assertEqual(view["assessment"], "unassessed")
        self.assertFalse(view["no_ancestor_found"],
                         "an unassessed history is not an absence of ancestors")

    def test_an_unreadable_assessed_source_is_INCOMPLETE(self) -> None:
        base = ids(40, "i")
        path = self._write("inc", base)
        session = self._session(C.COPILOT_CLAUDE_CODE, "inc-sess", base)
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="inc-sess", session_ref=session,
                           source_files=[path])
        self.db.commit()
        path.unlink()
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="inc-sess", session_ref=session,
                           source_files=[path])
        self.db.commit()

        view = thread_view(self.db, session)
        self.assertEqual(view["assessment"], "incomplete")
        self.assertEqual(view["sources_unavailable"], 1)
        self.assertFalse(view["no_ancestor_found"],
                         "a source that could not be read cannot prove an absence")

    def test_a_fully_assessed_readable_source_IS_no_ancestor_found(self) -> None:
        base = ids(50, "j")
        path = self._write("solo", base)
        session = self._session(C.COPILOT_CLAUDE_CODE, "solo-sess", base)
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="solo-sess", session_ref=session,
                           source_files=[path])
        self.db.commit()

        view = thread_view(self.db, session)
        self.assertEqual(view["assessment"], "complete")
        self.assertEqual((view["sources_known"], view["sources_assessed"],
                          view["sources_available"]), (1, 1, 1))
        self.assertTrue(view["no_ancestor_found"],
                        "assessed, readable, and nothing found — a real answer")

    def test_a_RELATED_session_ingest_only_source_is_counted(self) -> None:
        """Part of the displayed thread was never assessed, so the whole
        view must not call itself complete."""
        base = ids(100, "x")
        a_file = self._write("xa", base)
        a = self._session(C.COPILOT_CLAUDE_CODE, "sess-a", base)
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="sess-a", session_ref=a,
                           source_files=[a_file])
        b_file = self._write("xb", base + ids(40, "y"))
        b = self._session(C.COPILOT_CLAUDE_CODE, "sess-b", base + ids(40, "y"))
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="sess-b", session_ref=b,
                           source_files=[b_file])
        self.db.commit()
        self.assertEqual(thread_view(self.db, a)["assessment"], "complete")

        # B carries a pre-A6 source that no member row covers
        extra = self._write("xb2", base + ids(5, "z"))
        self.db.execute(
            "INSERT INTO ingest_state (copilot, source_file, last_session_id) "
            "VALUES (?, ?, ?)", (C.COPILOT_CLAUDE_CODE, str(extra), "sess-b"))
        self.db.commit()

        view = thread_view(self.db, a)
        self.assertEqual(view["sources_known"], 3)
        self.assertEqual(view["sources_assessed"], 2)
        self.assertEqual(view["assessment"], "unassessed")
        self.assertFalse(view["no_ancestor_found"])


class TestThreadRouteContract(unittest.TestCase):
    """The HTTP boundary itself, including SessionNotFound -> 404."""

    def test_the_route_serves_a_tree_and_404s_a_missing_session(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover
            self.skipTest("fastapi is not installed")
        from session_analytics.api.server import create_app

        root = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, root, ignore_errors=True)
        dsn = f"sqlite:///{root / 'api.db'}"
        db = Database.connect(dsn)
        apply_ddl(db)
        sid = db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id) "
            "VALUES (?, ?, ?) RETURNING id",
            (C.COPILOT_CLAUDE_CODE, "route", "local"))
        db.commit()
        db.close()

        # TrustedHostMiddleware refuses an unknown Host with 400
        client = TestClient(create_app(dsn), base_url="http://127.0.0.1")
        ok = client.get(f"/api/sessions/{int(sid)}/thread")
        self.assertEqual(ok.status_code, 200)
        body = ok.json()
        self.assertEqual(body["lineage_support"], C.LINEAGE_SUPPORT_NATIVE)
        self.assertIn("relation_candidates", body)
        self.assertIn("sources_known", body)

        missing = client.get("/api/sessions/987654/thread")
        self.assertEqual(missing.status_code, 404,
                         "a session that does not exist is not an unsupported source")


class TestThreadMcpTool(unittest.TestCase):
    """The MCP tool serves the same corrected shape as the route."""

    def test_it_is_registered_and_mirrors_the_view(self) -> None:
        try:
            from session_analytics.mcp.server import build_server
        except ImportError:  # pragma: no cover
            self.skipTest("mcp is not installed")

        root = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, root, ignore_errors=True)
        dsn = f"sqlite:///{root / 'mcp.db'}"
        db = Database.connect(dsn)
        apply_ddl(db)
        sid = int(db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id) "
            "VALUES (?, ?, ?) RETURNING id",
            (C.COPILOT_CLAUDE_CODE, "mcp-one", "local")))
        db.commit()
        db.close()

        server = build_server(dsn)
        registered = server._tool_manager._tools
        self.assertIn("session_thread", registered,
                      "the A6 tool must be registered on the real server")

        body = registered["session_thread"].fn(sid)
        for key in ("lineage_support", "assessment", "relation_candidates",
                    "sources_known", "sources_assessed", "no_ancestor_found"):
            self.assertIn(key, body, f"the tool must serve {key}")
        self.assertEqual(body["lineage_support"], C.LINEAGE_SUPPORT_NATIVE)

        missing = registered["session_thread"].fn(987654)
        self.assertEqual(missing.get("error"), "session not found",
                         "a missing session is not an unsupported source")

    def test_its_description_warns_against_reading_a_blank_as_a_finding(self) -> None:
        """The tool's text is its contract for a model that cannot read
        the spec."""
        try:
            from session_analytics.mcp.server import build_server
        except ImportError:  # pragma: no cover
            self.skipTest("mcp is not installed")
        tool = build_server("sqlite:///:memory:")._tool_manager._tools["session_thread"]
        # Whitespace-NORMALIZED before matching. The raw description
        # wraps, and whether it arrives dedented depends on the mcp
        # version — asserting on a phrase that spans a line break made
        # this pass locally and fail in CI.
        text = " ".join((tool.description or "").split())
        for phrase in ("lineage_support", "assessment", "no_ancestor_found",
                       "inferred from timing", "a blank is not a finding",
                       "no completed assessment is stored"):
            self.assertIn(phrase, text)

    def test_startup_lands_schema_12_BEFORE_any_tool_call(self) -> None:
        """A schema-11 store must be upgraded at startup, not discovered
        to be stale inside a tool."""
        try:
            from session_analytics.mcp import server as mcp_server
        except ImportError:  # pragma: no cover
            self.skipTest("mcp is not installed")

        tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, tmp, ignore_errors=True)
        dsn = f"sqlite:///{tmp / 'old.db'}"
        # a genuine schema-11 store: every table EXCEPT A6's four
        old = Database.connect(dsn)
        from session_analytics.relational import db as db_mod
        original = db_mod._DDL_FILES
        db_mod._DDL_FILES = tuple(
            f for f in original if not f.endswith("012_thread.sql"))
        try:
            db_mod.apply_ddl(old)
        finally:
            db_mod._DDL_FILES = original
            old.close()

        check = Database.connect(dsn)
        try:
            tables = {r[0] for r in check.query(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("session_thread", tables, "fixture is pre-A6")
        finally:
            check.close()

        # the PRODUCTION startup path, with only the blocking transport
        # stubbed out
        ran: dict = {}
        real_build = mcp_server.build_server

        def _build(*args, **kwargs):
            server = real_build(*args, **kwargs)
            server.run = lambda *a, **k: ran.setdefault("ran", True)
            return server

        mcp_server.build_server = _build
        try:
            mcp_server.run(dsn=dsn)
        finally:
            mcp_server.build_server = real_build

        self.assertTrue(ran.get("ran"), "the server did start")
        after = Database.connect(dsn)
        try:
            tables = {r[0] for r in after.query(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("session_thread", "thread_member", "thread_edge",
                          "thread_relation_candidate"):
                self.assertIn(table, tables, f"{table} must exist before any tool")
            self.assertEqual(
                after.query_one("SELECT MAX(version) FROM schema_version")[0], 12)
        finally:
            after.close()


class TestA4A5Preservation(StoreCase):
    """FR-16/FR-17: A6 is a read-only neighbour.

    Threading adds a view over rows A4 and A5 already own. It must not
    write a harness column, re-point an expectation, or collapse two
    harness versions into one because a thread spans them.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, name: str, uuids) -> Path:
        path = self.tmp / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps({
            "type": "user", "uuid": u,
            "message": {"role": "user", "content": "x"},
        }) for u in uuids), encoding="utf-8")
        return path

    def _stamped_session(self, name: str, uuids, cli_version: str) -> int:
        sid = int(self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id, "
            "cli_version, cct_sha, harness_mixed) VALUES (?, ?, ?, ?, ?, ?) "
            "RETURNING id",
            (C.COPILOT_CLAUDE_CODE, name, "local", cli_version, "a" * 40, False)))
        for index, value in enumerate(uuids):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid) "
                "VALUES (?, ?, ?, ?)", (sid, index, "user", value))
        self.db.commit()
        return sid

    def _thread_two_versions(self):
        base = ids(100, "p")
        older = self._write("pv1", base)
        newer = self._write("pv2", base + ids(40, "q"))
        s1 = self._stamped_session("v1-sess", base, "2.0.0")
        s2 = self._stamped_session("v2-sess", base + ids(40, "q"), "2.1.0")
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="v1-sess", session_ref=s1,
                           source_files=[older])
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="v2-sess", session_ref=s2,
                           source_files=[newer])
        self.db.commit()
        return s1, s2

    def test_threading_writes_NOTHING_to_copilot_session(self) -> None:
        base = ids(100, "n")
        path = self._write("nv", base)
        session = self._stamped_session("untouched", base, "2.0.0")
        before = self.db.query("SELECT * FROM copilot_session ORDER BY id")

        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="untouched", session_ref=session,
                           source_files=[path])
        backfill(self.db)
        self.db.commit()

        after = self.db.query("SELECT * FROM copilot_session ORDER BY id")
        self.assertEqual(before, after,
                         "A6 owns no column on the session row")

    def test_a_thread_spanning_two_versions_does_not_collapse_them(self) -> None:
        s1, s2 = self._thread_two_versions()
        self.assertEqual(len(threads_for_session(self.db, s1)), 1,
                         "the two sessions ARE one thread")
        self.assertEqual(threads_for_session(self.db, s1),
                         threads_for_session(self.db, s2))

        versions = sorted(r[0] for r in self.db.query(
            "SELECT cli_version FROM copilot_session ORDER BY id"))
        self.assertEqual(versions, ["2.0.0", "2.1.0"],
                         "each session keeps its OWN harness version")
        mixed = [r[0] for r in self.db.query(
            "SELECT harness_mixed FROM copilot_session ORDER BY id")]
        self.assertEqual(mixed, [0, 0],
                         "a thread spanning versions does not make a session mixed")

    def test_the_harness_comparison_stays_session_grained(self) -> None:
        from session_analytics.api import dashboard

        self._thread_two_versions()
        result = dashboard.harness_aggregates(
            self.db, by=C.HARNESS_KEY_CLI_VERSION)
        rows = result["rows"]
        counted = {
            r["value"]: r.get("sessions")
            for r in rows if r.get("value") in ("2.0.0", "2.1.0")
        }
        self.assertEqual(counted, {"2.0.0": 1, "2.1.0": 1},
                         "each version still counts its own session")
        self.assertFalse(result["single_group"],
                         "the two versions stayed comparable, not collapsed")

    def test_an_expectation_binding_is_never_re_pointed(self) -> None:
        base = ids(100, "e")
        older = self._write("ev1", base)
        newer = self._write("ev2", base + ids(40, "f"))
        s1 = self._stamped_session("e1", base, "2.0.0")
        s2 = self._stamped_session("e2", base + ids(40, "f"), "2.0.0")

        run = int(self.db.insert_returning_id(
            "INSERT INTO expectation_run (feature_id, attempt_id, "
            "run_fingerprint, contract_fingerprint, ingested_at) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            ("feat", "1-2", "fp-run", "fp-contract", "2026-09-26T00:00:00Z")))
        self.db.execute(
            "INSERT INTO expectation_session (run_ref, copilot, session_id, "
            "session_ref, ingested_at) VALUES (?, ?, ?, ?, ?)",
            (run, C.COPILOT_CLAUDE_CODE, "e1", s1, "2026-09-26T00:00:00Z"))
        self.db.commit()
        before = self.db.query("SELECT * FROM expectation_session ORDER BY id")
        run_before = self.db.query("SELECT * FROM expectation_run ORDER BY id")

        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="e1", session_ref=s1,
                           source_files=[older])
        detect_for_session(self.db, copilot=C.COPILOT_CLAUDE_CODE,
                           native_session_id="e2", session_ref=s2,
                           source_files=[newer])
        backfill(self.db)
        self.db.commit()

        # BOTH sides, and the SAME thread: "s1 is in some thread" would
        # let a regression that leaves them separate pass a test whose
        # whole point is that threading put the binding at risk.
        joined = threads_for_session(self.db, s1)
        self.assertEqual(len(joined), 1)
        self.assertEqual(joined, threads_for_session(self.db, s2),
                         "they were threaded TOGETHER, so the binding was at risk")
        self.assertEqual(
            self.db.query("SELECT * FROM expectation_session ORDER BY id"), before,
            "the expectation stays bound to the session it was bound to")
        self.assertEqual(
            self.db.query("SELECT * FROM expectation_run ORDER BY id"), run_before,
            "run_fingerprint and every A5 identity key are untouched")

    def test_a_thread_does_not_inherit_its_members_expectations(self) -> None:
        s1, s2 = self._thread_two_versions()
        run = int(self.db.insert_returning_id(
            "INSERT INTO expectation_run (feature_id, attempt_id, "
            "run_fingerprint, contract_fingerprint, ingested_at) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            ("feat2", "3-4", "fp2", "fpc2", "2026-09-26T00:00:00Z")))
        self.db.execute(
            "INSERT INTO expectation_session (run_ref, copilot, session_id, "
            "session_ref, ingested_at) VALUES (?, ?, ?, ?, ?)",
            (run, C.COPILOT_CLAUDE_CODE, "v1-sess", s1, "2026-09-26T00:00:00Z"))
        self.db.commit()

        bound = self.db.query_one(
            "SELECT COUNT(*) FROM expectation_session WHERE session_ref = ?",
            (s2,))[0]
        self.assertEqual(bound, 0,
                         "the sibling gains nothing by sharing a thread")
        view = thread_view(self.db, s2)
        self.assertNotIn("expectations", view)
        self.assertNotIn("expectations", view["thread"] or {})


class TestAdditiveUpgradeFromSchema11(unittest.TestCase):
    """FR-15: schema 12 lands IN PLACE on a populated schema-11 store.

    Run against a real schema-11 store, never a fresh one: a fresh
    database gets every table at once, so it cannot tell an additive
    change from one that silently needed a rebuild. The fixture is built
    by applying every DDL file EXCEPT A6's, which is exactly what a
    store created before this slice contains.

    This matters because the alternative was a recreate, and a recreate
    permanently drops every session whose transcript has since been
    pruned. (No count is claimed: establishing one would need the
    pre-rebuild `ingest_state`, which the rebuild itself replaced.)
    """

    def _schema_11_store(self) -> tuple[str, dict]:
        from session_analytics.relational import db as db_mod

        root = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, root, ignore_errors=True)
        dsn = f"sqlite:///{root / 'old.db'}"

        # BOTH the file list and the stamp: apply_ddl records
        # _SCHEMA_VERSION whatever ran, so patching only the files would
        # leave a store whose tables say 11 and whose version row says
        # 12 — a state no real store is ever in.
        original_files, original_version = db_mod._DDL_FILES, db_mod._SCHEMA_VERSION
        db_mod._DDL_FILES = tuple(
            f for f in original_files if not f.endswith("012_thread.sql"))
        db_mod._SCHEMA_VERSION = 11
        old = Database.connect(dsn)
        # Registered BEFORE the DDL runs: a failure in apply_ddl or in
        # the population below would otherwise leave the connection open
        # while the directory cleanup ran against it.
        self.addCleanup(old.close)
        try:
            db_mod.apply_ddl(old)
        finally:
            db_mod._DDL_FILES = original_files
            db_mod._SCHEMA_VERSION = original_version

        # POPULATED: an empty store proves nothing about preservation.
        session = int(old.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, developer_id, "
            "cli_version) VALUES (?, ?, ?, ?) RETURNING id",
            (C.COPILOT_CLAUDE_CODE, "legacy-one", "local", "1.9.0")))
        for index in range(5):
            old.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, uuid) "
                "VALUES (?, ?, ?, ?)", (session, index, "user", f"legacy-{index}"))
        run = int(old.insert_returning_id(
            "INSERT INTO expectation_run (feature_id, attempt_id, "
            "run_fingerprint, contract_fingerprint, ingested_at) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            ("legacy-feat", "9-9", "fp", "fpc", "2026-09-01T00:00:00Z")))
        old.commit()
        before = {
            "sessions": old.query("SELECT * FROM copilot_session ORDER BY id"),
            "turns": old.query("SELECT * FROM copilot_turn ORDER BY id"),
            "runs": old.query("SELECT * FROM expectation_run ORDER BY id"),
            "version": old.query_one("SELECT MAX(version) FROM schema_version")[0],
        }
        old.close()
        self.assertEqual(before["version"], 11, "the fixture really is schema 11")
        self.assertEqual(run, 1)
        return dsn, before

    def test_the_four_tables_and_the_index_appear_in_place(self) -> None:
        dsn, _before = self._schema_11_store()
        db = Database.connect(dsn)
        self.addCleanup(db.close)

        tables = {r[0] for r in db.query(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("session_thread", "thread_member", "thread_edge",
                      "thread_relation_candidate"):
            self.assertNotIn(table, tables, "the fixture predates A6")

        check_schema(db)          # must NOT raise
        apply_ddl(db)

        tables = {r[0] for r in db.query(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("session_thread", "thread_member", "thread_edge",
                      "thread_relation_candidate"):
            self.assertIn(table, tables)
        indexes = {r[0] for r in db.query(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("idx_copilot_turn_uuid", indexes)
        self.assertEqual(
            db.query_one("SELECT MAX(version) FROM schema_version")[0], 12)

    def test_every_pre_existing_row_survives_untouched(self) -> None:
        dsn, before = self._schema_11_store()
        db = Database.connect(dsn)
        self.addCleanup(db.close)
        apply_ddl(db)

        self.assertEqual(
            db.query("SELECT * FROM copilot_session ORDER BY id"),
            before["sessions"], "no session was rewritten")
        self.assertEqual(
            db.query("SELECT * FROM copilot_turn ORDER BY id"),
            before["turns"], "no turn was rewritten")
        self.assertEqual(
            db.query("SELECT * FROM expectation_run ORDER BY id"),
            before["runs"], "A5's identity keys are untouched")

    def test_no_re_ingest_is_needed_and_a_second_apply_changes_nothing(self) -> None:
        dsn, _before = self._schema_11_store()
        db = Database.connect(dsn)
        self.addCleanup(db.close)
        apply_ddl(db)
        snapshot = {
            name: db.query(f"SELECT * FROM {name}")
            for name in ("session_thread", "thread_member", "thread_edge",
                         "thread_relation_candidate")
        }
        apply_ddl(db)
        for name, rows in snapshot.items():
            self.assertEqual(db.query(f"SELECT * FROM {name}"), rows)
        self.assertEqual(
            db.query_one("SELECT MAX(version) FROM schema_version")[0], 12)

    def test_A6_adds_NOTHING_to_the_columns_that_force_a_recreate(self) -> None:
        """_REQUIRED_COLUMNS is the list create-if-absent cannot repair.
        An entry here is what turns an upgrade into a rebuild."""
        from session_analytics.relational.db import _REQUIRED_COLUMNS

        offenders = [
            (table, column) for table, column in _REQUIRED_COLUMNS
            if "thread" in table or "thread" in column
        ]
        self.assertEqual(offenders, [],
                         "A6 owns no column on any pre-existing table")

    def test_the_new_tables_are_usable_immediately_after_the_upgrade(self) -> None:
        """Landing the tables is not the claim; serving from them is."""
        dsn, _before = self._schema_11_store()
        db = Database.connect(dsn)
        self.addCleanup(db.close)
        apply_ddl(db)

        session = int(db.query_one(
            "SELECT id FROM copilot_session WHERE session_id = ?",
            ("legacy-one",))[0])
        view = thread_view(db, session)
        self.assertEqual(view["lineage_support"], C.LINEAGE_SUPPORT_NATIVE)
        self.assertIsNone(view["thread"])
        self.assertEqual(view["assessment"], "unassessed",
                         "a pre-A6 session awaits the backfill, and says so")


class TestAuditTimestamps(StoreCase):
    """Audit metadata is never null, and `detected_at` does not move.

    Every production caller omits `now`, so a bare default wrote
    `detected_at = NULL` at creation and then erased `updated_at` on
    every later pass. These fields are never an input to lineage — the
    rule reads none of them — but "when was this thread first seen" is
    exactly the question a null cannot answer.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(_tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, self.tmp, ignore_errors=True)
        self.known: dict = {}

    def _loader(self, key):
        return next((s.uuids for s in self.known.values()
                     if s.source_key == key), None)

    def _put(self, source):
        self.known[source.identity] = source
        return source

    def _stamps(self) -> tuple:
        return self.db.query_one(
            "SELECT detected_at, updated_at FROM session_thread ORDER BY id")

    def test_a_default_call_stamps_both_fields(self) -> None:
        base = ids(100, "t")
        a = self._put(src("t1", base))
        b = self._put(src("t2", base + ids(30, "u")))
        reconcile(self.db, [a, b], uuid_loader=self._loader)   # no `now`
        self.db.commit()
        detected, updated = self._stamps()
        self.assertIsNotNone(detected, "detected_at must not be null")
        self.assertIsNotNone(updated, "updated_at must not be null")

    def test_a_later_pass_moves_updated_at_but_NOT_detected_at(self) -> None:
        base = ids(100, "s")
        a = self._put(src("s1", base))
        b = self._put(src("s2", base + ids(30, "v")))
        reconcile(self.db, [a, b], now="2026-01-01T00:00:00Z",
                  uuid_loader=self._loader)
        self.db.commit()
        first = self._stamps()

        c = self._put(src("s3", base + ids(30, "v") + ids(40, "w")))
        reconcile(self.db, [c], now="2026-06-01T00:00:00Z",
                  uuid_loader=self._loader)
        self.db.commit()
        second = self._stamps()

        self.assertEqual(second[0], first[0],
                         "detected_at is when the thread was FIRST seen")
        self.assertEqual(second[1], "2026-06-01T00:00:00Z")
        self.assertNotEqual(second[1], first[1])

    def test_a_later_default_pass_never_erases_a_supplied_stamp(self) -> None:
        base = ids(100, "r")
        a = self._put(src("r1", base))
        b = self._put(src("r2", base + ids(30, "x")))
        reconcile(self.db, [a, b], now="2026-01-01T00:00:00Z",
                  uuid_loader=self._loader)
        self.db.commit()

        c = self._put(src("r3", base + ids(30, "x") + ids(40, "y")))
        reconcile(self.db, [c], uuid_loader=self._loader)      # no `now`
        self.db.commit()
        detected, updated = self._stamps()
        self.assertEqual(detected, "2026-01-01T00:00:00Z")
        self.assertIsNotNone(updated, "a default pass must not erase it")

    def test_a_redirected_thread_and_a_candidate_are_stamped_too(self) -> None:
        left, right = self._put(src("L", ids(60, "L"))), self._put(src("R", ids(60, "R")))
        for source in (left, right):
            reconcile(self.db, [source], uuid_loader=self._loader)
        self.db.commit()
        bridge = self._put(src("BR", ids(60, "L") + ids(60, "R") + ids(200, "n")))
        reconcile(self.db, [bridge], uuid_loader=self._loader)

        pair = self._put(src("D1", ids(40, "d")))
        twin = self._put(src("D2", ids(40, "d")))
        reconcile(self.db, [pair, twin], uuid_loader=self._loader)
        self.db.commit()

        for (updated,) in self.db.query(
            "SELECT updated_at FROM session_thread WHERE status = ?",
            (C.THREAD_STATUS_REDIRECTED,)
        ):
            self.assertIsNotNone(updated, "a redirect records when it happened")
        for (detected,) in self.db.query(
            "SELECT detected_at FROM thread_relation_candidate"
        ):
            self.assertIsNotNone(detected, "a candidate records when it was seen")

    def test_the_timestamp_is_not_an_input_to_lineage(self) -> None:
        """Two passes an era apart derive the identical graph."""
        def graph_for(stamp):
            root = Path(_tempfile.mkdtemp())
            self.addCleanup(_shutil.rmtree, root, ignore_errors=True)
            db = Database.connect(f"sqlite:///{root / 'g.db'}")
            self.addCleanup(db.close)
            apply_ddl(db)
            base = ids(100, "q")
            a, b = src("q1", base), src("q2", base + ids(30, "z"))
            known = {s.identity: s for s in (a, b)}
            loader = lambda k: next(  # noqa: E731
                (s.uuids for s in known.values() if s.source_key == k), None)
            reconcile(db, [a, b], now=stamp, uuid_loader=loader)
            db.commit()
            return db.query(
                "SELECT ancestor_member_ref, descendant_member_ref, shared_uuids, "
                "ancestor_only, descendant_only FROM thread_edge")

        self.assertEqual(graph_for("1999-01-01T00:00:00Z"),
                         graph_for("2099-01-01T00:00:00Z"))
