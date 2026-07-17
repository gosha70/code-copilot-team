# Tests for session_analytics.correlate (E9 benchmark↔session linking, #91).
#
# Two layers: the PURE core (correlate_links + iter_run_records) is exercised
# with injected fakes / a tiny on-disk fixture tree — no DB, no real benchmark
# run; the sqlite integration covers the store UPDATE, export column, and the
# dashboard aggregate end-to-end.

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics import correlate as cor
from session_analytics import export as exp
from session_analytics.adapters import claude_code
from session_analytics.api import dashboard
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database
from session_analytics.relational.store import link_benchmark_run

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class TestCorrelateCore(unittest.TestCase):
    """Pure core — deterministic, no DB / no live runs tree."""

    def test_correlate_links_exact_counts(self) -> None:
        records = [
            cor.RunRecord("s-linked-1", "/runs/a/attempt-01"),
            cor.RunRecord("s-linked-2", "/runs/b/attempt-01"),
            cor.RunRecord("s-unmatched", "/runs/c/attempt-01"),
            cor.RunRecord(None, "/runs/d/attempt-01"),
            cor.RunRecord("", "/runs/e/attempt-01"),
        ]
        matched = {"s-linked-1", "s-linked-2"}
        stats = cor.correlate_links(records, lambda sid, rd: sid in matched)
        self.assertEqual(stats.scanned, 5)
        self.assertEqual(stats.with_session_id, 3)  # two linked + one unmatched
        self.assertEqual(stats.null_session_id, 2)  # None and "" both count as null
        self.assertEqual(stats.linked, 2)
        self.assertEqual(stats.unmatched, 1)
        self.assertEqual(stats.out_of_scope, 0)
        self.assertEqual(stats.duplicate_session_id, 0)
        # invariants the CorrelationStats docstring promises
        self.assertEqual(
            stats.scanned,
            stats.out_of_scope + stats.with_session_id + stats.null_session_id,
        )
        self.assertEqual(stats.with_session_id, stats.linked + stats.unmatched)
        # as_dict serializes every counter (the CLI summary contract)
        self.assertEqual(
            set(stats.as_dict()),
            {
                "scanned", "out_of_scope", "with_session_id", "null_session_id",
                "linked", "unmatched", "duplicate_session_id",
            },
        )

    def test_out_of_scope_backend_not_counted_as_unmatched(self) -> None:
        records = [
            cor.RunRecord("s-claude", "/runs/a/attempt-01", backend_id="claude-code"),
            cor.RunRecord("s-aider", "/runs/b/attempt-01", backend_id="aider"),
            cor.RunRecord("s-legacy", "/runs/c/attempt-01", backend_id=None),
        ]
        linked_ids = []

        def link_fn(sid: str, rd: str) -> bool:
            linked_ids.append(sid)
            return True

        stats = cor.correlate_links(records, link_fn, backend_id="claude-code")
        # the aider record is out_of_scope — link_fn never sees it, and it is
        # NOT an unmatched claude-code session; a backend-less record stays in
        # scope (lenient).
        self.assertEqual(stats.out_of_scope, 1)
        self.assertEqual(stats.linked, 2)
        self.assertEqual(stats.unmatched, 0)
        self.assertEqual(linked_ids, ["s-claude", "s-legacy"])

    def test_duplicate_session_id_is_a_visible_counter(self) -> None:
        records = [
            cor.RunRecord("s-dup", "/runs/a/attempt-01"),
            cor.RunRecord("s-dup", "/runs/a/attempt-02"),
        ]
        stats = cor.correlate_links(records, lambda sid, rd: True)
        self.assertEqual(stats.linked, 2)  # both records link (last-writer-wins)
        self.assertEqual(stats.duplicate_session_id, 1)  # 2nd+ occurrence counted

    def test_non_string_session_id_is_null_not_fatal(self) -> None:
        # A dict/list/int at the session_id leaf must be treated as a
        # null-session record — never crash the run (unhashable in the dedup
        # set) or leak a non-string into the parameterized UPDATE.
        for weird in ({"weird": 1}, [1, 2], 123):
            record = {"backend": {"metadata": {"session_id": weird}}}
            self.assertIsNone(cor._session_id(record))

    def test_iter_run_records_parses_tree_and_skips_malformed(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="cct-sa-runs-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        # well-formed record carrying a session_id
        d1 = root / "20260716T000000Z-bench-cc-000" / "task-a" / "attempt-01-run-000"
        d1.mkdir(parents=True)
        (d1 / C.RUN_RECORD_FILENAME).write_text(
            json.dumps({"backend": {"metadata": {"session_id": "uuid-1"}}})
        )
        # well-formed, null session_id (bare mode / non-claude backend)
        d2 = root / "20260716T000001Z-bench-stub-000" / "task-b" / "attempt-01-run-000"
        d2.mkdir(parents=True)
        (d2 / C.RUN_RECORD_FILENAME).write_text(
            json.dumps({"backend": {"metadata": {"session_id": None}}})
        )
        # record entirely missing the backend/metadata path → also null, not fatal
        d3 = root / "20260716T000002Z-bench-cc-001" / "task-c" / "attempt-01-run-000"
        d3.mkdir(parents=True)
        (d3 / C.RUN_RECORD_FILENAME).write_text(json.dumps({"schema_version": 1}))
        # malformed JSON → skipped entirely (logged, non-fatal)
        d4 = root / "20260716T000003Z-bench-cc-002" / "task-d" / "attempt-01-run-000"
        d4.mkdir(parents=True)
        (d4 / C.RUN_RECORD_FILENAME).write_text("{not valid json")

        records = list(cor.iter_run_records(root))
        self.assertEqual(len(records), 3)  # d1, d2, d3 — d4 (malformed) dropped
        self.assertEqual([r.session_id for r in records], ["uuid-1", None, None])
        linked = next(r for r in records if r.session_id == "uuid-1")
        # run_dir is the containing (attempt) dir, RESOLVED at the input
        # boundary — stable across relative/absolute/symlinked roots.
        self.assertEqual(linked.run_dir, str(d1.resolve()))
        self.assertTrue(Path(linked.run_dir).is_absolute())

    def test_iter_run_records_resolves_relative_root(self) -> None:
        # A relative runs-root must yield the same absolute run_dir as the
        # absolute spelling (idempotent stamping across invocations).
        root = Path(tempfile.mkdtemp(prefix="cct-sa-runs-rel-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        d = root / "run" / "task" / "attempt-01"
        d.mkdir(parents=True)
        (d / C.RUN_RECORD_FILENAME).write_text(
            json.dumps({"backend": {"metadata": {"session_id": "uuid-rel"}}})
        )
        cwd = os.getcwd()
        os.chdir(root.parent)
        try:
            rel = list(cor.iter_run_records(Path(root.name)))
        finally:
            os.chdir(cwd)
        abs_ = list(cor.iter_run_records(root))
        self.assertEqual(rel[0].run_dir, abs_[0].run_dir)


class TestCorrelateIntegration(RegistryResetTestCase):
    """sqlite: link UPDATE, export column, dashboard aggregate."""

    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(
            dsn=self.dsn,
            copilots=[C.COPILOT_CLAUDE_CODE],
            root=CLAUDE_CODE_ROOT,
            full=True,
        )
        self.db = Database.connect(self.dsn)
        row = self.db.query_one(
            "SELECT session_id FROM copilot_session WHERE copilot = ?",
            (C.COPILOT_CLAUDE_CODE,),
        )
        self.session_id = row[0]

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def test_link_sets_column_idempotent_and_unmatched_returns_false(self) -> None:
        run_dir = "/runs/20260716T000000Z-bench-cc-000/task-a/attempt-01-run-000"
        self.assertTrue(
            link_benchmark_run(self.db, C.COPILOT_CLAUDE_CODE, self.session_id, run_dir)
        )
        got = self.db.query_one(
            f"SELECT {C.COL_BENCHMARK_RUN_DIR} FROM copilot_session WHERE session_id = ?",
            (self.session_id,),
        )
        self.assertEqual(got[0], run_dir)
        # idempotent: a second link with the same value still succeeds, same value
        self.assertTrue(
            link_benchmark_run(self.db, C.COPILOT_CLAUDE_CODE, self.session_id, run_dir)
        )
        # a session_id with no row → no update, returns False (caller: unmatched)
        self.assertFalse(
            link_benchmark_run(self.db, C.COPILOT_CLAUDE_CODE, "no-such-session", run_dir)
        )

    def test_export_includes_benchmark_run_dir(self) -> None:
        self.assertIn(C.COL_BENCHMARK_RUN_DIR, exp.SESSIONS_COLUMNS)
        run_dir = "/runs/x/attempt-01"
        link_benchmark_run(self.db, C.COPILOT_CLAUDE_CODE, self.session_id, run_dir)
        rows = list(exp.rows_for(self.db, C.EXPORT_TABLE_SESSIONS))
        row = dict(zip(exp.SESSIONS_COLUMNS, rows[0]))
        self.assertEqual(row[C.COL_BENCHMARK_RUN_DIR], run_dir)

    def test_benchmark_correlation_aggregate(self) -> None:
        before = dashboard.benchmark_correlation(self.db)
        self.assertEqual(before["sessions_total"], 1)
        self.assertEqual(before["sessions_linked"], 0)
        self.assertEqual(before["sessions_unlinked"], 1)
        self.assertEqual(before["distinct_benchmark_attempts"], 0)

        link_benchmark_run(
            self.db, C.COPILOT_CLAUDE_CODE, self.session_id, "/runs/x/attempt-01"
        )
        after = dashboard.benchmark_correlation(self.db)
        self.assertEqual(after["sessions_total"], 1)
        self.assertEqual(after["sessions_linked"], 1)
        self.assertEqual(after["sessions_unlinked"], 0)
        self.assertEqual(after["distinct_benchmark_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
