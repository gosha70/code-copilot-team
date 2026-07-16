# Tests for session_analytics.export (E7, issue #87): CSV/Parquet export
# over the relational store — fixed column order + deterministic ORDER BY,
# the `sessions` summary's cost_usd/redaction_mode/KPI columns, redaction-
# safety, the `export --table all` CLI path, and the Parquet path (which
# skips when pyarrow is absent — covered in CI, see the smoke workflow).

from __future__ import annotations

import csv
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from session_analytics import constants as C
from session_analytics import export as exp
from session_analytics.adapters import claude_code
from session_analytics.cli import main
from session_analytics.config import ModelRate, PricingConfig
from session_analytics.ingest.pipeline import ingest
from session_analytics.judge.contracts import PARSE_OK, Rubric, TurnContext, TurnLabels
from session_analytics.judge.kpis import compute_kpis
from session_analytics.judge.rubric import load_rubric
from session_analytics.judge.runner import run_judge
from session_analytics.relational.db import Database

from session_analytics._register import unregister_all_for_tests
from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_HAVE_PYARROW = importlib.util.find_spec("pyarrow") is not None


def _rate(**overrides) -> ModelRate:
    base = dict(
        currency="USD", effective_date="2026-05-01",
        input=15.0, output=75.0, cache_read=1.5, cache_write=18.75,
    )
    base.update(overrides)
    return ModelRate(**base)


class _FakeJudge:
    """Deterministic judge (no network) — mirrors tests/test_judge.py."""

    judge_id = "fake"

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels:
        bools = {label: False for label in rubric.bool_labels}
        bools["response_helpful"] = True
        return TurnLabels(
            bool_labels=bools,
            sentiment="NEUTRAL",
            interaction_quality=4,
            parse_status=PARSE_OK,
            judge_id=self.judge_id,
            judge_model="fake-1",
        )


def _run_cli(argv: list) -> tuple[int, str, str]:
    # export never needs an adapter (it only reads the already-ingested DB),
    # but main() unconditionally (idempotently) registers them; reset first
    # so it doesn't collide with a setUp that registered claude_code directly
    # for the DB-seeding ingest() call.
    unregister_all_for_tests()
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def _rows_as_dicts(columns: tuple, rows: list) -> list[dict]:
    return [dict(zip(columns, r)) for r in rows]


class TestExportBase(RegistryResetTestCase):
    """Seeds one ingested, priced, and judge-labeled session (fixture: 6 turns)."""

    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        pricing = PricingConfig(models={"claude-opus-4-8": _rate()})
        ingest(
            dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            full=True, pricing=pricing,
        )
        self.db = Database.connect(self.dsn)
        rubric = load_rubric()
        run_judge(self.db, _FakeJudge(), rubric)
        compute_kpis(self.db, rubric.name)

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()


class TestSessionsExport(TestExportBase):
    def test_columns_and_content(self) -> None:
        rows = list(exp.rows_for(self.db, C.EXPORT_TABLE_SESSIONS))
        self.assertEqual(len(rows), 1)
        row = dict(zip(exp.SESSIONS_COLUMNS, rows[0]))
        self.assertEqual(row["copilot"], C.COPILOT_CLAUDE_CODE)
        self.assertEqual(row["session_id"], "sess-tiny-001")
        self.assertEqual(row["project_path"], "/repo/demo")
        self.assertEqual(row["redaction_mode"], C.REDACT_CODE)
        self.assertEqual(row["turn_count"], 6)
        self.assertEqual(row["tool_call_count"], 2)
        self.assertEqual(row["error_count"], 1)
        # E5 cost rollup.
        self.assertIsNotNone(row["cost_usd"])
        self.assertGreater(row["cost_usd"], 0)
        # session_kpi (LEFT JOIN) columns.
        self.assertEqual(row["kpi_labeled_turn_count"], 6)
        self.assertIsNotNone(row["kpi_avg_interaction_quality"])
        self.assertAlmostEqual(row["kpi_avg_interaction_quality"], 4.0, places=4)

    def test_csv_header_and_row(self) -> None:
        buf = io.StringIO()
        exp.write_csv(self.db, C.EXPORT_TABLE_SESSIONS, buf)
        rows = list(csv.reader(io.StringIO(buf.getvalue())))
        self.assertEqual(rows[0], list(exp.SESSIONS_COLUMNS))
        self.assertEqual(len(rows), 2)  # header + 1 session

    def test_ordering_is_deterministic(self) -> None:
        first = list(exp.rows_for(self.db, C.EXPORT_TABLE_SESSIONS))
        second = list(exp.rows_for(self.db, C.EXPORT_TABLE_SESSIONS))
        self.assertEqual(first, second)


class TestTurnsExport(TestExportBase):
    def test_columns_content_and_order(self) -> None:
        rows = _rows_as_dicts(exp.TURNS_COLUMNS, list(exp.rows_for(self.db, C.EXPORT_TABLE_TURNS)))
        self.assertEqual(len(rows), 6)
        seqs = [r["sequence_num"] for r in rows]
        self.assertEqual(seqs, sorted(seqs))
        self.assertTrue(all(r["session_id"] == rows[0]["session_id"] for r in rows))

        first = rows[0]
        self.assertEqual(first["role"], C.ROLE_USER)
        self.assertEqual(first["redaction_mode"], C.REDACT_CODE)

        assistant = next(r for r in rows if r["role"] == C.ROLE_ASSISTANT)
        self.assertEqual(assistant["model"], "claude-opus-4-8")
        self.assertIsNotNone(assistant["cost_usd"])
        self.assertGreater(assistant["cost_usd"], 0)
        self.assertEqual(assistant["cost_price_version"], "2026-05-01")

    def test_streamed_not_a_list(self) -> None:
        gen = exp.rows_for(self.db, C.EXPORT_TABLE_TURNS)
        self.assertNotIsInstance(gen, list)
        self.assertTrue(hasattr(gen, "__next__"))

    def test_ordering_is_deterministic(self) -> None:
        first = list(exp.rows_for(self.db, C.EXPORT_TABLE_TURNS))
        second = list(exp.rows_for(self.db, C.EXPORT_TABLE_TURNS))
        self.assertEqual(first, second)


class TestLabelsAndKpisExport(TestExportBase):
    def test_labels_columns_and_count(self) -> None:
        rows = _rows_as_dicts(exp.LABELS_COLUMNS, list(exp.rows_for(self.db, C.EXPORT_TABLE_LABELS)))
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r["judge_id"] == "fake" for r in rows))
        self.assertTrue(all(r["sentiment"] == "NEUTRAL" for r in rows))
        turn_ids = [r["turn_id"] for r in rows]
        self.assertEqual(turn_ids, sorted(turn_ids))

    def test_kpis_columns_and_count(self) -> None:
        rows = _rows_as_dicts(exp.KPIS_COLUMNS, list(exp.rows_for(self.db, C.EXPORT_TABLE_KPIS)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["labeled_turn_count"], 6)

    def test_csv_header_matches_columns(self) -> None:
        for table, columns in (
            (C.EXPORT_TABLE_LABELS, exp.LABELS_COLUMNS),
            (C.EXPORT_TABLE_KPIS, exp.KPIS_COLUMNS),
        ):
            buf = io.StringIO()
            exp.write_csv(self.db, table, buf)
            header = next(csv.reader(io.StringIO(buf.getvalue())))
            self.assertEqual(header, list(columns))


class TestRedactionSafety(RegistryResetTestCase):
    """FR-6: export reads only the store; content_preview is what was stored."""

    def setUp(self) -> None:
        super().setUp()
        claude_code.register()

    def test_metadata_only_ingest_exports_redacted_marker(self) -> None:
        dsn = self.sqlite_dsn()
        ingest(
            dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            full=True, redaction_mode=C.REDACT_METADATA_ONLY,
        )
        db = Database.connect(dsn)
        try:
            rows = _rows_as_dicts(exp.TURNS_COLUMNS, list(exp.rows_for(db, C.EXPORT_TABLE_TURNS)))
            self.assertTrue(rows)
            self.assertTrue(all(r["redaction_mode"] == C.REDACT_METADATA_ONLY for r in rows))
            non_empty = [r for r in rows if r["content_length"]]
            self.assertTrue(non_empty, "fixture must have at least one non-empty turn")
            for r in non_empty:
                self.assertTrue(
                    r["content_preview"].startswith("[redacted"),
                    f"expected a redacted marker, got: {r['content_preview']!r}",
                )
        finally:
            db.close()


class TestExportCliCsv(TestExportBase):
    def test_sessions_csv_to_stdout_by_default(self) -> None:
        code, out, err = _run_cli(["export", "--dsn", self.dsn])
        self.assertEqual(code, C.EXIT_OK, err)
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(rows[0], list(exp.SESSIONS_COLUMNS))
        self.assertEqual(len(rows), 2)

    def test_single_table_to_out_file(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-export-")) / "turns.csv"
        code, out, err = _run_cli(
            ["export", "--table", "turns", "--out", str(tmp), "--dsn", self.dsn]
        )
        self.assertEqual(code, C.EXIT_OK, err)
        self.assertTrue(tmp.is_file())
        with tmp.open() as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], list(exp.TURNS_COLUMNS))
        self.assertEqual(len(rows), 7)  # header + 6 turns

    def test_table_all_writes_one_file_per_table(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-export-"))
        code, out, err = _run_cli(
            ["export", "--table", "all", "--out", str(tmp), "--dsn", self.dsn]
        )
        self.assertEqual(code, C.EXIT_OK, err)
        for table in C.EXPORT_DATA_TABLES:
            f = tmp / f"{table}.csv"
            self.assertTrue(f.is_file(), f"missing {f}")
            with f.open() as fh:
                header = next(csv.reader(fh))
            self.assertEqual(header, list(exp.columns_for(table)))


class TestExportCliValidation(TestExportBase):
    def test_parquet_without_out_is_usage_error(self) -> None:
        code, out, err = _run_cli(["export", "--format", "parquet", "--dsn", self.dsn])
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("--out", err)

    def test_table_all_without_out_is_usage_error(self) -> None:
        code, out, err = _run_cli(["export", "--table", "all", "--dsn", self.dsn])
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("--out", err)

    def test_pyarrow_absent_gives_usage_error_not_traceback(self) -> None:
        # Force `import pyarrow` to raise ImportError regardless of whether the
        # real package is installed in this environment (sys.modules[name] =
        # None makes the import machinery raise ImportError deterministically).
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-export-")) / "sessions.parquet"
        with mock.patch.dict(sys.modules, {"pyarrow": None}):
            code, out, err = _run_cli(
                ["export", "--format", "parquet", "--out", str(tmp), "--dsn", self.dsn]
            )
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("pyarrow", err.lower())
        self.assertIn("pip install pyarrow", err)
        self.assertFalse(tmp.exists())


@unittest.skipUnless(_HAVE_PYARROW, "pyarrow not installed; Parquet export skipped (covered in CI)")
class TestParquetRoundTrip(TestExportBase):
    def test_round_trip_matches_csv(self) -> None:
        import pyarrow.parquet as pq

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-export-")) / "sessions.parquet"
        exp.write_parquet(self.db, C.EXPORT_TABLE_SESSIONS, tmp)

        table = pq.read_table(tmp)
        self.assertEqual(table.column_names, list(exp.SESSIONS_COLUMNS))
        self.assertEqual(table.num_rows, 1)

        csv_buf = io.StringIO()
        exp.write_csv(self.db, C.EXPORT_TABLE_SESSIONS, csv_buf)
        csv_rows = list(csv.reader(io.StringIO(csv_buf.getvalue())))[1:]

        pa_rows = table.to_pylist()
        self.assertEqual(len(pa_rows), len(csv_rows))
        idx = exp.SESSIONS_COLUMNS.index("copilot")
        self.assertEqual(pa_rows[0]["copilot"], csv_rows[0][idx])
        idx = exp.SESSIONS_COLUMNS.index("session_id")
        self.assertEqual(pa_rows[0]["session_id"], csv_rows[0][idx])

    def test_cli_parquet_table_all(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-export-"))
        code, out, err = _run_cli(
            ["export", "--format", "parquet", "--table", "all", "--out", str(tmp), "--dsn", self.dsn]
        )
        self.assertEqual(code, C.EXIT_OK, err)
        for table in C.EXPORT_DATA_TABLES:
            self.assertTrue((tmp / f"{table}.parquet").is_file())

    def test_cli_parquet_requires_out_even_for_single_table(self) -> None:
        code, out, err = _run_cli(
            ["export", "--format", "parquet", "--table", "sessions", "--dsn", self.dsn]
        )
        self.assertEqual(code, C.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
