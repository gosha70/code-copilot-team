# Tests for the Kùzu knowledge-graph layer.
#
# Pure tests (DDL parsing) run everywhere. The live build test runs only when
# the optional ``kuzu`` package is importable; CI installs it for the graph
# job. Skips are logged, never silently passed.

from __future__ import annotations

import importlib.util
import unittest

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.graph import schema
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_KUZU = importlib.util.find_spec("kuzu") is not None


class TestGraphDDL(unittest.TestCase):
    def test_node_and_rel_ddl_loaded(self) -> None:
        nodes = schema.load_node_ddl()
        rels = schema.load_rel_ddl()
        self.assertEqual(len(nodes), 10)  # 10 node tables
        self.assertEqual(len(rels), 12)   # 12 rel tables
        self.assertTrue(all(s.startswith("CREATE NODE TABLE") for s in nodes))
        self.assertTrue(all(s.startswith("CREATE REL TABLE") for s in rels))

    def test_table_name_parse(self) -> None:
        self.assertEqual(
            schema._table_name("CREATE NODE TABLE IF NOT EXISTS Session(x STRING, PRIMARY KEY(x))"),
            "Session",
        )
        self.assertEqual(
            schema._table_name("CREATE REL TABLE IF NOT EXISTS HAS_TURN(FROM Session TO Turn)"),
            "HAS_TURN",
        )


class TestReadonlyGuard(unittest.TestCase):
    """The freeform Cypher IDE must reject mutating statements (no Kùzu needed)."""

    def test_rejects_mutations_without_trailing_space(self) -> None:
        from session_analytics.graph.query import assert_readonly

        for bad in (
            "CREATE(n:Foo)",
            "MATCH (n) SET\nn.x = 1",
            "MATCH (n) DELETE\nn",
            "MATCH (n) DETACH DELETE n",
            "drop table Session",
            "MATCH (n) REMOVE n.x",
            "MERGE (n:Foo {a:1})",
        ):
            with self.assertRaises(ValueError, msg=bad):
                assert_readonly(bad)

    def test_allows_read_queries(self) -> None:
        from session_analytics.graph.query import assert_readonly

        for ok in (
            "MATCH (s:Session) RETURN s.session_key LIMIT 10",
            "MATCH (n) RETURN n.createdAt AS created",   # 'create' substring is fine
            "MATCH (n) RETURN n.set_value",              # 'set' substring is fine
            "MATCH (i:ToolInvocation) RETURN count(i)",
        ):
            assert_readonly(ok)  # must not raise


@unittest.skipUnless(_KUZU, "kuzu not installed; live graph build skipped (covered in CI)")
class TestGraphBuildLive(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()

    def test_build_from_fixture(self) -> None:
        import tempfile
        from pathlib import Path

        from session_analytics.graph import query
        from session_analytics.graph.builder import build
        from session_analytics.graph.schema import GraphDatabase

        dsn = self.sqlite_dsn()
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)

        graph_dir = str(Path(tempfile.mkdtemp(prefix="cct-sa-kuzu-")) / "g")
        rel = Database.connect(dsn)
        try:
            stats = build(rel, graph_dir, rebuild=True)
        finally:
            rel.close()
        self.assertEqual(stats.sessions, 1)
        self.assertEqual(stats.turns, 6)
        self.assertEqual(stats.tools, 2)

        gdb = GraphDatabase.connect(graph_dir)
        try:
            counts = query.node_counts(gdb)
            failures = query.tool_failure_stats(gdb)
        finally:
            gdb.close()
        self.assertEqual(counts["Session"], 1)
        self.assertEqual(counts["Turn"], 6)
        self.assertEqual(counts["ToolInvocation"], 2)
        self.assertEqual(counts["FileNode"], 1)
        self.assertEqual(counts["ErrorNode"], 1)
        # The Read tool errored once in the fixture.
        read = next((f for f in failures if f["tool"] == "file_read"), None)
        self.assertIsNotNone(read)
        self.assertEqual(read["errors"], 1)

    def test_rebuild_is_idempotent(self) -> None:
        import tempfile
        from pathlib import Path

        from session_analytics.graph import query
        from session_analytics.graph.builder import build
        from session_analytics.graph.schema import GraphDatabase

        dsn = self.sqlite_dsn()
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        graph_dir = str(Path(tempfile.mkdtemp(prefix="cct-sa-kuzu-")) / "g")

        rel = Database.connect(dsn)
        try:
            build(rel, graph_dir, rebuild=True)
            build(rel, graph_dir, rebuild=True)  # second pass
        finally:
            rel.close()

        gdb = GraphDatabase.connect(graph_dir)
        try:
            counts = query.node_counts(gdb)
        finally:
            gdb.close()
        self.assertEqual(counts["Session"], 1)
        self.assertEqual(counts["Turn"], 6)


if __name__ == "__main__":
    unittest.main()
