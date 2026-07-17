# Tests for session_analytics.correlate (E9 benchmark↔session linking, #91).
#
# Two layers: the PURE core (correlate_links + iter_run_records) is exercised
# with injected fakes / a tiny on-disk fixture tree — no DB, no real benchmark
# run; the sqlite integration covers the store UPDATE, export column, and the
# dashboard aggregate end-to-end.

from __future__ import annotations

import argparse
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
from session_analytics.relational.db import Database, apply_ddl
from session_analytics.relational.store import link_benchmark_run, upsert_benchmark_result

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
                "scanned", "skipped_run_records", "out_of_scope",
                "with_session_id", "null_session_id", "linked", "unmatched",
                "duplicate_session_id", "scores_ingested", "scores_missing",
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


def _score_payload(**overrides) -> dict:
    """A fully well-formed score.json payload; overrides splice fields in."""
    payload = {
        "schema_version": "1.0",
        "benchmark_id": "bench-a",
        "task_id": "task-a",
        "backend_id": "claude-code",
        "run_id": "run-000",
        "attempt": 1,
        "result": "pass",
        "scores": {"tests_passed": True, "lint_passed": True, "typecheck_passed": False},
        "derived": {
            "elapsed_seconds": 12.5, "files_changed": 3,
            "lines_added": 40, "lines_removed": 5,
        },
    }
    payload.update(overrides)
    return payload


class TestScoreParsing(unittest.TestCase):
    """D-parse-strictness: missing tolerated, malformed types rejected."""

    def test_well_formed_full_payload(self) -> None:
        score = cor._parse_score(_score_payload())
        self.assertIsNotNone(score)
        self.assertEqual(score.result, "pass")
        self.assertEqual(score.attempt, 1)
        self.assertTrue(score.tests_passed)
        self.assertFalse(score.typecheck_passed)
        self.assertEqual(score.elapsed_seconds, 12.5)
        self.assertEqual(score.lines_added, 40)

    def test_missing_keys_tolerated_as_nulls(self) -> None:
        # Only identity present — scores/derived/result all absent → row still
        # parses, every absent field None. Missing ≠ malformed.
        score = cor._parse_score({"benchmark_id": "b", "task_id": "t"})
        self.assertIsNotNone(score)
        self.assertIsNone(score.result)
        self.assertIsNone(score.tests_passed)
        self.assertIsNone(score.elapsed_seconds)
        self.assertEqual(score.benchmark_id, "b")

    def test_malformed_types_strictly_rejected(self) -> None:
        # Each of these would corrupt an aggregate if coerced — the WHOLE
        # score is rejected (None), never partially accepted.
        bad_payloads = [
            _score_payload(result="passed"),                       # bad enum
            _score_payload(result=1),                              # non-str result
            _score_payload(derived={"elapsed_seconds": "12.5"}),   # str numeric
            _score_payload(scores={"tests_passed": 1}),            # 0/1 as bool
            _score_payload(scores={"tests_passed": "true"}),       # str as bool
            _score_payload(attempt=True),                          # bool as int
            _score_payload(attempt="1"),                           # str as int
            _score_payload(scores=[1, 2]),                         # non-dict block
            _score_payload(derived="fast"),                        # non-dict block
            _score_payload(benchmark_id=42),                       # non-str id
        ]
        for payload in bad_payloads:
            self.assertIsNone(cor._parse_score(payload), msg=repr(payload))

    def test_non_dict_payload_rejected(self) -> None:
        for payload in ([1, 2], "pass", 3, None):
            self.assertIsNone(cor._parse_score(payload))

    def test_load_score_missing_malformed_wellformed(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="cct-sa-score-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.assertIsNone(cor.load_score(root / "absent" / C.SCORE_FILENAME))
        bad = root / C.SCORE_FILENAME
        bad.write_text("{nope")
        self.assertIsNone(cor.load_score(bad))
        good = root / "good.json"
        good.write_text(json.dumps(_score_payload()))
        self.assertEqual(cor.load_score(good).result, "pass")

    def test_load_score_invalid_utf8_is_skipped_not_fatal(self) -> None:
        # UnicodeDecodeError is a ValueError, NOT an OSError — a bad-encoding
        # file must be skipped like any malformed file, never crash the scan.
        root = Path(tempfile.mkdtemp(prefix="cct-sa-score-u8-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        bad = root / C.SCORE_FILENAME
        bad.write_bytes(b"\xff\xfe{invalid")
        self.assertIsNone(cor.load_score(bad))


class TestOutcomeCounters(unittest.TestCase):
    """Pure-core scores_ingested / scores_missing + store_result_fn wiring."""

    def test_score_counters_and_backend_agnostic_store(self) -> None:
        score = cor.Score(result="pass")
        records = [
            cor.RunRecord("s-1", "/r/a", backend_id="claude-code", score=score),
            cor.RunRecord("s-2", "/r/b", backend_id="aider", score=score),  # out-of-scope: STILL stored
            cor.RunRecord(None, "/r/c", backend_id="claude-code", score=score),  # null session: STILL stored
            cor.RunRecord("s-3", "/r/d", backend_id="claude-code", score=None),  # missing score
        ]
        stored = []
        stats = cor.correlate_links(
            records,
            lambda sid, rd: True,
            backend_id="claude-code",
            store_result_fn=lambda rec, ok: stored.append((rec.run_dir, ok)),
        )
        self.assertEqual(stats.scores_ingested, 3)
        self.assertEqual(stats.scores_missing, 1)
        # Outcomes are backend-agnostic; the CORE's own in_scope decision is
        # handed to the sink (aider → False) — the sink never re-derives it.
        self.assertEqual(
            stored, [("/r/a", True), ("/r/b", False), ("/r/c", True)]
        )
        self.assertEqual(stats.out_of_scope, 1)  # linking stays scoped
        self.assertIn("scores_ingested", stats.as_dict())

    def test_partial_stats_survive_a_mid_run_failure(self) -> None:
        # FR-4: the CLI passes a pre-created stats object; when a sink raises
        # mid-scan, the counters gathered so far are still readable.
        score = cor.Score(result="pass")
        records = [
            cor.RunRecord("s-1", "/r/a", score=score),
            cor.RunRecord("s-2", "/r/b", score=score),  # sink raises here
            cor.RunRecord("s-3", "/r/c", score=score),  # never reached
        ]

        def exploding_sink(rec: cor.RunRecord, in_scope: bool) -> None:
            if rec.run_dir == "/r/b":
                raise RuntimeError("db gone")

        stats = cor.CorrelationStats()
        with self.assertRaises(RuntimeError):
            cor.correlate_links(
                records, lambda sid, rd: True,
                store_result_fn=exploding_sink, stats=stats,
            )
        self.assertEqual(stats.scanned, 2)          # partial, not zero
        self.assertEqual(stats.scores_ingested, 1)  # /r/a landed before the failure
        self.assertEqual(stats.linked, 1)

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
        # malformed JSON → skipped entirely (logged + counted, non-fatal)
        d4 = root / "20260716T000003Z-bench-cc-002" / "task-d" / "attempt-01-run-000"
        d4.mkdir(parents=True)
        (d4 / C.RUN_RECORD_FILENAME).write_text("{not valid json")
        # invalid UTF-8 run-record → also skipped + counted, never fatal
        d5 = root / "20260716T000004Z-bench-cc-003" / "task-e" / "attempt-01-run-000"
        d5.mkdir(parents=True)
        (d5 / C.RUN_RECORD_FILENAME).write_bytes(b"\xff\xfe{bad")

        stats = cor.CorrelationStats()
        records = list(cor.iter_run_records(root, stats=stats))
        self.assertEqual(len(records), 3)  # d1, d2, d3 — d4+d5 dropped
        # The drops are a VISIBLE counter, not just log lines (#5).
        self.assertEqual(stats.skipped_run_records, 2)
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


class TestOutcomesIntegration(RegistryResetTestCase):
    """sqlite: benchmark_result table, upsert, aggregate, export, CLI paths."""

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
        self.session_id = self.db.query_one(
            "SELECT session_id FROM copilot_session WHERE copilot = ?",
            (C.COPILOT_CLAUDE_CODE,),
        )[0]

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def test_apply_ddl_retrofits_the_table_on_an_existing_db(self) -> None:
        # The no-migration claim: a pre-existing DB missing benchmark_result
        # (simulated by dropping it from this throwaway test store) gains it
        # on the next apply_ddl re-run — CREATE TABLE IF NOT EXISTS semantics.
        self.db.execute(f"DROP TABLE {C.TBL_BENCHMARK_RESULT}")
        self.db.commit()
        apply_ddl(self.db)
        row = self.db.query_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (C.TBL_BENCHMARK_RESULT,),
        )
        self.assertIsNotNone(row)

    def test_upsert_idempotent_and_session_ref_resolution(self) -> None:
        score = cor.Score(benchmark_id="b", task_id="t", backend_id="claude-code",
                          run_id="run-000", attempt=1, result="pass",
                          tests_passed=True, elapsed_seconds=9.5)
        # Linked: session_ref resolves via the claude-code equi-join.
        upsert_benchmark_result(
            self.db, "/runs/a/attempt-01", score,
            copilot=C.COPILOT_CLAUDE_CODE, session_id=self.session_id,
            ingested_at="2026-07-17T00:00:00+00:00",
        )
        # Organic/out-of-scope: no session identity → NULL session_ref.
        upsert_benchmark_result(
            self.db, "/runs/b/attempt-01", cor.Score(result="fail"),
            ingested_at="2026-07-17T00:00:00+00:00",
        )
        self.db.commit()
        rows = list(self.db.query(
            f"SELECT run_dir, result, session_ref FROM {C.TBL_BENCHMARK_RESULT} ORDER BY run_dir"
        ))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], "pass")
        self.assertIsNotNone(rows[0][2])
        self.assertIsNone(rows[1][2])
        # Idempotent re-run (same run_dir, updated result) → still 2 rows.
        upsert_benchmark_result(
            self.db, "/runs/a/attempt-01", cor.Score(result="timeout"),
            copilot=C.COPILOT_CLAUDE_CODE, session_id=self.session_id,
            ingested_at="2026-07-17T01:00:00+00:00",
        )
        self.db.commit()
        rows = list(self.db.query(
            f"SELECT result FROM {C.TBL_BENCHMARK_RESULT} WHERE run_dir = ?",
            ("/runs/a/attempt-01",),
        ))
        self.assertEqual(rows, [("timeout",)])

    def test_benchmark_outcomes_aggregate(self) -> None:
        upsert_benchmark_result(
            self.db, "/runs/pass/attempt-01", cor.Score(result="pass"),
            copilot=C.COPILOT_CLAUDE_CODE, session_id=self.session_id,
            ingested_at="x",
        )
        upsert_benchmark_result(
            self.db, "/runs/fail/attempt-01", cor.Score(result="fail"),
            ingested_at="x",
        )
        self.db.commit()
        by_result = {g["result"]: g for g in dashboard.benchmark_outcomes(self.db)["by_result"]}
        self.assertEqual(by_result["pass"]["attempts"], 1)
        self.assertEqual(by_result["pass"]["linked_sessions"], 1)
        self.assertEqual(by_result["fail"]["attempts"], 1)
        self.assertEqual(by_result["fail"]["linked_sessions"], 0)
        self.assertEqual(by_result["fail"]["total_cost_usd"], 0.0)  # unlinked → no cost

    def test_benchmark_outcomes_no_fan_out_on_shared_session_ref(self) -> None:
        # Two attempt rows referencing the SAME session (the tolerated
        # duplicate-session_id case) must contribute that session's
        # cost/duration/linked-count exactly ONCE per result bucket.
        # Seed a priced turn so cost is non-zero and fan-out would be visible.
        self.db.execute(
            "UPDATE copilot_turn SET cost_usd = 2.0 "
            "WHERE session_id = (SELECT id FROM copilot_session WHERE session_id = ?) "
            "AND sequence_num = 1",
            (self.session_id,),
        )
        for attempt_dir in ("/runs/dup/attempt-01", "/runs/dup/attempt-02"):
            upsert_benchmark_result(
                self.db, attempt_dir, cor.Score(result="pass"),
                copilot=C.COPILOT_CLAUDE_CODE, session_id=self.session_id,
                ingested_at="x",
            )
        self.db.commit()
        by_result = {g["result"]: g for g in dashboard.benchmark_outcomes(self.db)["by_result"]}
        self.assertEqual(by_result["pass"]["attempts"], 2)          # rows counted
        self.assertEqual(by_result["pass"]["linked_sessions"], 1)   # sessions deduped
        self.assertEqual(by_result["pass"]["total_cost_usd"], 2.0)  # cost ONCE, not 4.0

    def test_export_benchmark_results_table(self) -> None:
        self.assertIn(C.EXPORT_TABLE_BENCHMARK_RESULTS, C.EXPORT_DATA_TABLES)
        upsert_benchmark_result(
            self.db, "/runs/a/attempt-01",
            cor.Score(result="pass", tests_passed=True, lint_passed=False),
            ingested_at="x",
        )
        self.db.commit()
        rows = list(exp.rows_for(self.db, C.EXPORT_TABLE_BENCHMARK_RESULTS))
        self.assertEqual(len(rows), 1)
        row = dict(zip(exp.BENCHMARK_RESULTS_COLUMNS, rows[0]))
        self.assertEqual(row["result"], "pass")
        self.assertEqual(row["tests_passed"], 1)   # bool → 0/1 normalization
        self.assertEqual(row["lint_passed"], 0)
        self.assertIsNone(row["typecheck_passed"])  # missing stays NULL

    def _make_attempt(self, root: Path, sub: str, run_record: dict, score: object = None) -> Path:
        d = root / sub
        d.mkdir(parents=True)
        (d / C.RUN_RECORD_FILENAME).write_text(json.dumps(run_record))
        if score is not None:
            (d / C.SCORE_FILENAME).write_text(
                score if isinstance(score, str) else json.dumps(score)
            )
        return d

    def test_cli_end_to_end_commits_once_and_reports_scores(self) -> None:
        from session_analytics.cli import _cmd_correlate

        root = Path(tempfile.mkdtemp(prefix="cct-sa-outcomes-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        rr = lambda sid: {"backend_id": "claude-code", "backend": {"metadata": {"session_id": sid}}}
        self._make_attempt(root, "run-a/t/a-01", rr(self.session_id), _score_payload())
        self._make_attempt(root, "run-b/t/a-01", rr(None), _score_payload(result="fail"))
        self._make_attempt(root, "run-c/t/a-01", rr("ghost"))                     # no score.json
        self._make_attempt(root, "run-d/t/a-01", rr(None), "{malformed")          # malformed score
        self._make_attempt(root, "run-e/t/a-01", rr(None), _score_payload(result="oops"))  # strict-reject

        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            code = _cmd_correlate(argparse.Namespace(runs_root=root, dsn=self.dsn))
        self.assertEqual(code, C.EXIT_OK)
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["scores_ingested"], 2)   # run-a + run-b
        self.assertEqual(summary["scores_missing"], 3)    # absent + malformed + strict-reject
        self.assertEqual(summary["linked"], 1)
        # Single post-scan commit: a FRESH connection sees the rows.
        other = Database.connect(self.dsn)
        try:
            n = other.query_one(f"SELECT COUNT(*) FROM {C.TBL_BENCHMARK_RESULT}")[0]
        finally:
            other.close()
        self.assertEqual(n, 2)
        # Idempotent re-run: still 2 rows.
        with redirect_stdout(io.StringIO()):
            self.assertEqual(_cmd_correlate(argparse.Namespace(runs_root=root, dsn=self.dsn)), C.EXIT_OK)
        self.assertEqual(
            self.db.query_one(f"SELECT COUNT(*) FROM {C.TBL_BENCHMARK_RESULT}")[0], 2
        )

    def test_cli_prints_partial_summary_on_failure(self) -> None:
        from unittest import mock

        from session_analytics.cli import _cmd_correlate

        root = Path(tempfile.mkdtemp(prefix="cct-sa-outcomes-fail-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        rr = {"backend_id": "claude-code", "backend": {"metadata": {"session_id": None}}}
        self._make_attempt(root, "run-a/t/a-01", rr, _score_payload())
        self._make_attempt(root, "run-b/t/a-01", rr, _score_payload())

        import io
        from contextlib import redirect_stderr, redirect_stdout

        calls = {"n": 0}

        def explode(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("db gone mid-scan")

        err, out = io.StringIO(), io.StringIO()
        with mock.patch(
            "session_analytics.relational.store.upsert_benchmark_result",
            side_effect=explode,
        ):
            with redirect_stdout(out), redirect_stderr(err):
                code = _cmd_correlate(argparse.Namespace(runs_root=root, dsn=self.dsn))
        self.assertEqual(code, C.EXIT_RUNTIME)
        self.assertEqual(out.getvalue(), "")  # stdout stays success-only
        stderr = err.getvalue()
        partial = json.loads(stderr[: stderr.index("\nnote:")])
        self.assertEqual(partial["scores_ingested"], 1)  # first record processed
        # #4: the partial counters must be explicitly labeled as rolled-back
        # work — never phrased like the success summary.
        self.assertIn("PROCESSED-only", stderr)
        self.assertIn("rolled back", stderr)
        self.assertIn("error: correlate failed", stderr)
        # And the DB really has nothing from this run (single commit never ran).
        other = Database.connect(self.dsn)
        try:
            n = other.query_one(f"SELECT COUNT(*) FROM {C.TBL_BENCHMARK_RESULT}")[0]
        finally:
            other.close()
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
