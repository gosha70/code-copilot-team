# Tests for #289 T1 — pure component grouping (FR-B, FR-C).
# No store, no graph, no kuzu, no CLI, no MCP anywhere in this file:
# T1 is pure, exactly like #287 T1.

from __future__ import annotations

import random
import unittest

from session_analytics.embedding.clusters import (
    MIN_CLUSTER_SIZE,
    Cluster,
    find_clusters,
)


class TestTransitiveGroupingIsTheContract(unittest.TestCase):
    """FR-B: a cluster is a transitive DISCOVERY grouping.

    The chain fixture is the whole point. A and C land in one cluster
    THROUGH B while sharing no edge of their own — that is the
    documented behavior, not a defect, and this class name says so on
    purpose so a future reader cannot mistake it for one.
    """

    def test_chain_groups_a_and_c_though_they_share_no_edge(self) -> None:
        clusters = find_clusters([("a", "b"), ("b", "c")])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].members, ("a", "b", "c"))
        # the pairwise claim is explicitly NOT made: no a<->c edge exists
        self.assertNotIn(("a", "c"), [("a", "b"), ("b", "c")])

    def test_two_disconnected_chains_stay_two_clusters(self) -> None:
        clusters = find_clusters([("a", "b"), ("y", "z")])
        self.assertEqual([c.members for c in clusters],
                         [("a", "b"), ("y", "z")])


class TestDirectedEdgeCount(unittest.TestCase):
    """FR-B: grouping is undirected, the count is directed."""

    def test_reciprocal_pair_is_one_cluster_with_two_records(self) -> None:
        # A->B and B->A are TWO stored records forming ONE adjacency.
        clusters = find_clusters([("a", "b"), ("b", "a")])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].size, 2)
        self.assertEqual(clusters[0].directed_edge_count, 2)

    def test_one_way_edge_is_the_same_cluster_with_one_record(self) -> None:
        clusters = find_clusters([("a", "b")])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].members, ("a", "b"))
        self.assertEqual(clusters[0].directed_edge_count, 1)

    def test_reciprocity_changes_the_count_but_not_the_grouping(self) -> None:
        # the discriminator that a count-by-adjacency implementation fails
        one_way = find_clusters([("a", "b")])[0]
        both_ways = find_clusters([("a", "b"), ("b", "a")])[0]
        self.assertEqual(one_way.members, both_ways.members)
        self.assertEqual(one_way.identity, both_ways.identity)
        self.assertNotEqual(one_way.directed_edge_count,
                            both_ways.directed_edge_count)

    def test_count_covers_every_record_inside_the_component(self) -> None:
        # triangle a-b-c with one reciprocal leg: 4 records, 3 members
        clusters = find_clusters(
            [("a", "b"), ("b", "a"), ("b", "c"), ("c", "a")])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].size, 3)
        self.assertEqual(clusters[0].directed_edge_count, 4)


class TestDeterministicIdentityAndOrder(unittest.TestCase):
    """FR-C: identity and ordering are stable, with no RNG."""

    def test_identity_is_the_lexicographically_smallest_member(self) -> None:
        clusters = find_clusters([("m", "z"), ("z", "b")])
        self.assertEqual(clusters[0].identity, "b")
        self.assertEqual(clusters[0].members, ("b", "m", "z"))

    def test_shuffled_input_yields_byte_identical_output(self) -> None:
        edges = [("a", "b"), ("b", "c"), ("m", "n"), ("x", "y"), ("y", "z"),
                 ("c", "a"), ("n", "m")]
        expected = [c.as_dict() for c in find_clusters(edges)]
        rng = random.Random(20260903)  # seeded: the SHUFFLE is fixed, the
        for _ in range(25):            # code under test uses no RNG at all
            shuffled = edges[:]
            rng.shuffle(shuffled)
            self.assertEqual([c.as_dict() for c in find_clusters(shuffled)],
                             expected)

    def test_clusters_order_by_descending_size_then_identity(self) -> None:
        # sizes 3, 2, 2 — the two 2s must order by identity ascending
        clusters = find_clusters(
            [("a", "b"), ("b", "c"), ("p", "q"), ("d", "e")])
        self.assertEqual([(c.size, c.identity) for c in clusters],
                         [(3, "a"), (2, "d"), (2, "p")])

    def test_member_order_does_not_follow_insertion(self) -> None:
        clusters = find_clusters([("z", "a")])
        self.assertEqual(clusters[0].members, ("a", "z"))


class TestNoSingletonClusters(unittest.TestCase):
    """D4: size >= 2, so edgeless sessions are never padded in."""

    def test_empty_edge_set_yields_no_clusters(self) -> None:
        self.assertEqual(find_clusters([]), [])

    def test_self_loop_alone_is_not_a_cluster_of_one(self) -> None:
        self.assertEqual(find_clusters([("a", "a")]), [])

    def test_min_cluster_size_is_two(self) -> None:
        self.assertEqual(MIN_CLUSTER_SIZE, 2)


class TestClusterShape(unittest.TestCase):
    """The report row a surface renders."""

    def test_as_dict_carries_the_directed_count_by_name(self) -> None:
        row = find_clusters([("a", "b"), ("b", "a")])[0].as_dict()
        self.assertEqual(row, {
            "identity": "a",
            "size": 2,
            "members": ["a", "b"],
            "directed_edge_count": 2,
        })

    def test_cluster_is_frozen(self) -> None:
        cluster = find_clusters([("a", "b")])[0]
        self.assertIsInstance(cluster, Cluster)
        with self.assertRaises(Exception):
            cluster.identity = "b"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
