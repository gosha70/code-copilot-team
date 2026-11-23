# Tests for session_analytics.export (E7, issue #87): CSV/Parquet export
# over the relational store — fixed column order + deterministic ORDER BY,
# the `sessions` summary's cost_usd/redaction_mode/KPI columns, redaction-
# safety, the `export --table all` CLI path, and the Parquet path (which
# skips when pyarrow is absent — covered in CI, see the smoke workflow).

from __future__ import annotations

import csv
import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from session_analytics import constants as C
from session_analytics import export as exp
from session_analytics import feedback as fb
from session_analytics.adapters import claude_code
from session_analytics.cli import main
from session_analytics.config import ModelRate, PricingConfig
from session_analytics.ingest.pipeline import ingest
from session_analytics.ingest.redaction import OutboundPolicy, redact_text
from session_analytics.judge.contracts import PARSE_OK, Rubric, TurnContext, TurnLabels
from session_analytics.judge.kpis import compute_kpis
from session_analytics.judge.rubric import load_rubric
from session_analytics.judge.runner import run_judge
from session_analytics.relational.db import Database

from session_analytics._register import unregister_all_for_tests
from session_analytics.tests import canary as K
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
        self.assertEqual(row["kpi_labeled_turn_count"], 4)   # 4 of 6 turns have text
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
        self.assertEqual(len(rows), 4)   # 4 of 6 fixture turns have text (#313)
        self.assertTrue(all(r["judge_id"] == "fake" for r in rows))
        self.assertTrue(all(r["sentiment"] == "NEUTRAL" for r in rows))
        turn_ids = [r["turn_id"] for r in rows]
        self.assertEqual(turn_ids, sorted(turn_ids))

    def test_bool_normalization_indices_track_the_columns(self) -> None:
        # The bool indices used to be a hardcoded tuple. Removing one
        # boolean column (#300) shifted `sentiment` into that range and
        # the normalizer silently rewrote 'NEUTRAL' to 1 — a corrupted
        # export column that type-checking and the schema both allow.
        for idx in exp._LABELS_BOOL_IDX:
            self.assertIn(
                exp.LABELS_COLUMNS[idx],
                exp._LABELS_BOOL_NAMES,
                f"index {idx} is {exp.LABELS_COLUMNS[idx]!r}, not a boolean column",
            )
        for name in ("sentiment", "interaction_quality", "judge_id",
                     "created_at", "id", "turn_id", "rubric_name"):
            self.assertNotIn(
                exp.LABELS_COLUMNS.index(name),
                exp._LABELS_BOOL_IDX,
                f"{name} would be coerced to 0/1",
            )

    def test_removed_label_is_absent_from_the_export(self) -> None:
        # #300: collection stopped and the column is dormant, so it must
        # not be served — a dormant column that is still exported is a
        # stale value published as data.
        self.assertNotIn("phase_violation", exp.LABELS_COLUMNS)
        self.assertNotIn("phase_compliance_score", exp.KPIS_COLUMNS)
        self.assertNotIn("kpi_phase_compliance_score", exp.SESSIONS_COLUMNS)

    def test_kpis_columns_and_count(self) -> None:
        rows = _rows_as_dicts(exp.KPIS_COLUMNS, list(exp.rows_for(self.db, C.EXPORT_TABLE_KPIS)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["labeled_turn_count"], 4)

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


# ══════════════════════════════════════════════════════════════════════════
# #487: the privacy floor. specs/export-privacy-floor/spec.md gives the rule
# for every column ("Column decisions"); these tests hold export to it.
# ══════════════════════════════════════════════════════════════════════════

_SESSIONS, _TURNS, _LABELS = C.EXPORT_TABLE_SESSIONS, C.EXPORT_TABLE_TURNS, C.EXPORT_TABLE_LABELS
_KPIS, _BENCH = C.EXPORT_TABLE_KPIS, C.EXPORT_TABLE_BENCHMARK_RESULTS
_TRACE, _FEEDBACK = C.EXPORT_TABLE_TRACE_DOCUMENTS, C.EXPORT_TABLE_FEEDBACK
# The tables whose rows belong to a session (benchmark_results keeps its rows).
_SESSION_TABLES = (_SESSIONS, _TURNS, _LABELS, _KPIS, _TRACE, _FEEDBACK)
_PLANTED_NOTE = "a person's own note, which no redaction mode governs"
_PLANTED_RATIONALE = "a person's own rationale"
_NO_CHANGE = {"dropped": 0, "reduced": 0, "emptied": 0}


def _pyarrow_loads() -> bool:
    """Whether pyarrow imports here, not only whether it is installed."""
    try:
        import pyarrow.parquet  # noqa: F401
    except Exception:  # noqa: BLE001 - an install that cannot load is as good as none
        return False
    return True


def _rows(n: int) -> str:
    return f"{n} row" if n == 1 else f"{n} rows"


class TestExportFloorRules(unittest.TestCase):
    def test_every_export_table_has_a_floor_rule(self) -> None:
        # A table added to the export without a rule would fail at export
        # time instead of having the floor decide its columns; fail here.
        self.assertEqual(set(exp._FLOOR_RULES), set(C.EXPORT_DATA_TABLES))


class _TwoProjectStore(RegistryResetTestCase):
    """Two sessions of two projects in one store: the canary corpus (project
    ``canaryproj``) and the tiny claude-code fixture (``/repo/demo``). Both
    have turns, labels, kpis and a feedback note; the canary session also has
    archived trace documents and benchmark rows point at both. Everything is
    ingested and judged under a configuration that applies nothing, and each
    test then changes the settings, as an operator would after ingest."""

    git_repo = False

    def setUp(self) -> None:
        super().setUp()
        self.dsn = self.sqlite_dsn()
        source, self.project = self.enterContext(K.corpus(git_repo=self.git_repo))
        shutil.copytree(CLAUDE_CODE_ROOT / "project-hash", source / "project-hash")
        with K.user_config(self.config()):
            self.sid = K.ingest_corpus(self.dsn, source)
            self.db = Database.connect(self.dsn)
            self.addCleanup(self.db.close)
            rubric = load_rubric()
            run_judge(self.db, _FakeJudge(), rubric)
            compute_kpis(self.db, rubric.name)
        row = self.db.query_one("SELECT id FROM copilot_session WHERE id <> ?", (self.sid,))
        self.assertIsNotNone(row, "the fixture session was not ingested")
        self.other = int(row[0])
        self.project_path = self.db.query_one(
            "SELECT project_path FROM copilot_session WHERE id = ?", (self.sid,)
        )[0]
        for sid in (self.sid, self.other):
            fb.add_feedback(
                self.db, sid, "note", _PLANTED_NOTE, C.FEEDBACK_SOURCE_HUMAN, "tester",
                rationale=_PLANTED_RATIONALE,
            )
        for run_dir, ref in (
            (f"{self.project_path}/runs/linked", self.sid),  # linked, under the project
            (f"{self.project_path}/runs/unlinked", None),  # linked to no session, under it
            (f"{self.project_path}-sibling/runs/x", None),  # a shared prefix, not a component
            ("/benchmarks/runs/other", self.other),  # the other session's
        ):
            self.db.execute(
                f"INSERT INTO {C.TBL_BENCHMARK_RESULT} "
                "(run_dir, benchmark_id, task_id, result, session_ref, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_dir, "bench", "task", "pass", ref, "2026-11-23T00:00:00Z"),
            )
        self.db.commit()
        self.turn_session = {int(t): int(s) for t, s in self.db.query("SELECT id, session_id FROM copilot_turn")}

    def config(self, **changed) -> dict:
        changed.setdefault("project_mode", C.REDACT_NONE)
        return K.config_for(self.project, **changed)

    def opted_out(self) -> OutboundPolicy:
        return OutboundPolicy(
            skip_ids=frozenset({self.sid}), skip_keys=frozenset({K.SESSION_KEY}),
            excluded_projects=frozenset({self.project_path}),
        )

    def tightened(self) -> OutboundPolicy:
        return OutboundPolicy(floored={self.sid: (C.REDACT_NONE, C.REDACT_METADATA_ONLY)})

    def stored(self, table: str) -> list[dict]:
        return _rows_as_dicts(exp.columns_for(table), list(exp.rows_for(self.db, table)))

    def floored(self, policy: OutboundPolicy, table: str, *, raw: bool = False) -> tuple[list[dict], exp.ExportFloor]:
        floor = exp.ExportFloor(policy, raw=raw)
        return _rows_as_dicts(exp.columns_for(table), list(exp.rows_for(self.db, table, floor))), floor

    def session_of(self, table: str, row: dict) -> int:
        if table == _SESSIONS:
            return int(row["id"])
        if table in (_TURNS, _KPIS):
            return int(row["session_id"])
        if table == _LABELS:
            return self.turn_session[int(row["turn_id"])]
        return int(row["session_ref"])


class TestExportFloorColumns(_TwoProjectStore):
    """Each column of each table, against a policy built for the test."""

    def test_both_sessions_have_rows_to_act_on(self) -> None:
        for table in _SESSION_TABLES:
            with self.subTest(table=table):
                owners = {self.session_of(table, r) for r in self.stored(table)}
                self.assertIn(self.sid, owners)
                if table != _TRACE:  # only the canary project archives its trace
                    self.assertIn(self.other, owners)

    def test_an_opted_out_project_has_no_row_in_any_session_table(self) -> None:
        for table in _SESSION_TABLES:
            with self.subTest(table=table):
                rows, floor = self.floored(self.opted_out(), table)
                stored = self.stored(table)
                self.assertEqual(rows, [r for r in stored if self.session_of(table, r) != self.sid])
                mine = sum(1 for r in stored if self.session_of(table, r) == self.sid)
                self.assertEqual(floor.changes[table], {**_NO_CHANGE, "dropped": mine})

    def test_a_benchmark_row_keeps_its_outcome_with_its_links_to_the_project_emptied(self) -> None:
        rows, floor = self.floored(self.opted_out(), _BENCH)
        stored = {r["id"]: r for r in self.stored(_BENCH)}
        out = {r["id"]: r for r in rows}
        self.assertEqual(set(out), set(stored), "no benchmark row is dropped (D3)")
        for rid, s in stored.items():
            with self.subTest(run_dir=s["run_dir"]):
                linked = s["session_ref"] == self.sid
                under = s["run_dir"].startswith(self.project_path + "/")
                self.assertEqual(out[rid]["session_ref"], None if linked else s["session_ref"])
                self.assertEqual(out[rid]["run_dir"], None if under else s["run_dir"])
                rest = set(exp.BENCHMARK_RESULTS_COLUMNS) - {"session_ref", "run_dir"}
                self.assertEqual({c: out[rid][c] for c in rest}, {c: s[c] for c in rest})
        # The linked row and the unlinked one under the project; the sibling
        # path and the other session's row are kept as they are.
        self.assertEqual(floor.changes[_BENCH], {**_NO_CHANGE, "emptied": 2})

    def test_a_tightened_projects_text_leaves_as_the_marker_under_metadata_only(self) -> None:
        policy = self.tightened()
        for table, text_cols in ((_TURNS, ("content_preview",)), (_TRACE, ("content",)), (_SESSIONS, ())):
            with self.subTest(table=table):
                rows, floor = self.floored(policy, table)
                stored = self.stored(table)
                self.assertEqual(len(rows), len(stored), "a tightened project loses no row")
                for s, o in zip(stored, rows):
                    if self.session_of(table, s) != self.sid:
                        self.assertEqual(o, s)
                        continue
                    for col in text_cols:
                        want = redact_text(s[col], C.REDACT_METADATA_ONLY) if s[col] else s[col]
                        self.assertEqual(o[col], want)
                        if s[col]:
                            self.assertTrue(o[col].startswith("[redacted "), o[col])
                    self.assertEqual(o["redaction_mode"], C.REDACT_METADATA_ONLY)
                    rest = set(s) - set(text_cols) - {"redaction_mode"}
                    # content_hash and source_path included: kept as stored.
                    self.assertEqual({c: o[c] for c in rest}, {c: s[c] for c in rest})
                mine = sum(1 for r in stored if self.session_of(table, r) == self.sid)
                self.assertEqual(floor.changes[table], {**_NO_CHANGE, "reduced": mine})

    def test_a_tightened_project_leaves_labels_kpis_and_benchmarks_as_stored(self) -> None:
        for table in (_LABELS, _KPIS, _BENCH):
            with self.subTest(table=table):
                rows, floor = self.floored(self.tightened(), table)
                self.assertEqual(rows, self.stored(table))
                self.assertEqual(floor.changes[table], _NO_CHANGE)
                self.assertIsNone(floor.table_summary(table))

    def test_d4_a_tightened_projects_feedback_text_is_exported_as_stored(self) -> None:
        rows, floor = self.floored(self.tightened(), _FEEDBACK)
        mine = [r for r in rows if int(r["session_ref"]) == self.sid]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["value_text"], _PLANTED_NOTE)
        self.assertEqual(mine[0]["rationale"], _PLANTED_RATIONALE)
        self.assertEqual(rows, self.stored(_FEEDBACK))
        self.assertEqual(floor.changes[_FEEDBACK], _NO_CHANGE)

    def test_the_summary_counts_what_the_written_table_changed(self) -> None:
        _, floor = self.floored(self.tightened(), _KPIS)
        self.assertIsNone(floor.table_summary(_KPIS), "kpis carry no text and no mode")
        _, floor = self.floored(self.tightened(), _SESSIONS)
        self.assertEqual(
            floor.table_summary(_SESSIONS),
            "export: sessions: 1 row reduced to metadata-only (project tightened since ingest)",
        )
        _, floor = self.floored(self.opted_out(), _BENCH)
        self.assertEqual(
            floor.table_summary(_BENCH),
            "export: benchmark_results: 2 rows with session_ref or run_dir emptied (opted-out project)",
        )

    def test_raw_writes_every_table_as_stored_and_counts_the_sessions_it_did_not_floor(self) -> None:
        for policy, opted_out, tightened in ((self.opted_out(), {self.sid}, set()), (self.tightened(), set(), {self.sid})):
            floor = exp.ExportFloor(policy, raw=True)
            for table in C.EXPORT_DATA_TABLES:
                with self.subTest(table=table, opted_out=bool(opted_out)):
                    rows = _rows_as_dicts(exp.columns_for(table), list(exp.rows_for(self.db, table, floor)))
                    self.assertEqual(rows, self.stored(table))
                    self.assertIsNone(floor.table_summary(table))
            self.assertEqual((floor.raw_opted_out, floor.raw_tightened), (opted_out, tightened))
        self.assertEqual(
            floor.raw_summary(),
            "export --raw: wrote 0 sessions of opted-out projects and 1 session of tightened projects as stored",
        )

    def test_raw_kpis_with_a_tightened_project_reports_no_tightened_session(self) -> None:
        floor = exp.ExportFloor(self.tightened(), raw=True)
        list(exp.rows_for(self.db, _KPIS, floor))
        self.assertEqual(
            floor.raw_summary(),
            "export --raw: wrote 0 sessions of opted-out projects and 0 sessions of tightened projects as stored",
        )

    def test_with_nothing_opted_out_or_tightened_the_csv_is_byte_for_byte_as_stored(self) -> None:
        floor = exp.ExportFloor(OutboundPolicy())
        for table in C.EXPORT_DATA_TABLES:
            with self.subTest(table=table):
                with_floor, as_stored = io.StringIO(), io.StringIO()
                exp.write_csv(self.db, table, with_floor, floor)
                exp.write_csv(self.db, table, as_stored)
                self.assertEqual(with_floor.getvalue(), as_stored.getvalue())
                self.assertIsNone(floor.table_summary(table))

    @unittest.skipUnless(_pyarrow_loads(), "pyarrow does not load here")
    def test_with_nothing_opted_out_or_tightened_parquet_has_the_same_rows(self) -> None:
        import pyarrow.parquet as pq

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-export-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for table in C.EXPORT_DATA_TABLES:
            with self.subTest(table=table):
                exp.write_parquet(self.db, table, tmp / f"{table}-floor.parquet", exp.ExportFloor(OutboundPolicy()))
                exp.write_parquet(self.db, table, tmp / f"{table}-stored.parquet")
                self.assertEqual(
                    pq.read_table(tmp / f"{table}-floor.parquet").to_pylist(),
                    pq.read_table(tmp / f"{table}-stored.parquet").to_pylist(),
                )


class TestExportFloorCli(_TwoProjectStore):
    """The real CLI under real configuration: #478's combined project check,
    the summaries, ``--raw`` and ``--table all``."""

    def export(self, *args: str, **changed) -> tuple[int, str, str]:
        with K.user_config(self.config(**changed)):
            return _run_cli(["export", "--db", self.dsn, *args])

    def out_dir(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix="cct-sa-export-"))
        self.addCleanup(shutil.rmtree, path, True)
        return path

    @staticmethod
    def read_csv(path: Path) -> list[dict]:
        with open(path, newline="", encoding="utf-8") as fp:
            return list(csv.DictReader(fp))

    def test_an_opt_out_filed_under_the_project_id_key_applies(self) -> None:
        code, out, err = self.export("--table", "sessions", ingest_off=True)
        self.assertEqual(code, C.EXIT_OK, err)
        self.assertNotIn("sess-canary-001", out)
        self.assertEqual({int(r["id"]) for r in csv.DictReader(io.StringIO(out))}, {self.other})
        self.assertEqual(err.strip(), "export: sessions: 1 row dropped (project opted out)")

    def test_table_all_files_agree_and_each_changed_table_reports_its_counts(self) -> None:
        stored = {t: self.stored(t) for t in C.EXPORT_DATA_TABLES}
        out_dir = self.out_dir()
        code, out, err = self.export("--table", "all", "--out", str(out_dir), ingest_off=True)
        self.assertEqual(code, C.EXIT_OK, err)
        files = {t: self.read_csv(out_dir / f"{t}.csv") for t in C.EXPORT_DATA_TABLES}
        kept = {int(r["id"]) for r in files[_SESSIONS]}
        self.assertEqual(kept, {self.other})
        for table in (_TURNS, _LABELS, _KPIS, _TRACE, _FEEDBACK):
            with self.subTest(table=table):
                self.assertLessEqual({self.session_of(table, r) for r in files[table]}, kept)
        self.assertLessEqual({int(r["session_ref"]) for r in files[_BENCH] if r["session_ref"]}, kept)
        dropped = {t: sum(1 for r in stored[t] if self.session_of(t, r) == self.sid) for t in _SESSION_TABLES}
        expected = []
        for table in C.EXPORT_DATA_TABLES:
            if table == _BENCH:
                expected.append(f"export: {table}: 2 rows with session_ref or run_dir emptied (opted-out project)")
            else:
                expected.append(f"export: {table}: {_rows(dropped[table])} dropped (project opted out)")
        self.assertEqual(err.strip().splitlines(), expected)

    def test_kpis_with_a_tightened_project_prints_nothing(self) -> None:
        code, out, err = self.export("--table", "kpis", project_mode=C.REDACT_METADATA_ONLY)
        self.assertEqual(code, C.EXIT_OK, err)
        self.assertEqual(err, "")
        self.assertIn(self.sid, {int(r["session_id"]) for r in csv.DictReader(io.StringIO(out))})
        _, raw_out, _ = self.export("--table", "kpis", "--raw", project_mode=C.REDACT_METADATA_ONLY)
        self.assertEqual(out, raw_out)

    def test_sessions_with_a_tightened_project_reports_one_reduced_row(self) -> None:
        code, out, err = self.export("--table", "sessions", project_mode=C.REDACT_METADATA_ONLY)
        self.assertEqual(code, C.EXIT_OK, err)
        self.assertEqual(err.strip(), "export: sessions: 1 row reduced to metadata-only (project tightened since ingest)")
        modes = {int(r["id"]): r["redaction_mode"] for r in csv.DictReader(io.StringIO(out))}
        self.assertEqual(modes[self.sid], C.REDACT_METADATA_ONLY)

    def test_raw_writes_the_store_and_prints_its_one_line(self) -> None:
        code, out, err = self.export("--table", "kpis", "--raw", project_mode=C.REDACT_METADATA_ONLY)
        self.assertEqual(code, C.EXIT_OK, err)
        self.assertEqual(
            err.strip(),
            "export --raw: wrote 0 sessions of opted-out projects and 0 sessions of tightened projects as stored",
        )
        out_dir = self.out_dir()
        code, out, err = self.export("--table", "all", "--raw", "--out", str(out_dir), ingest_off=True)
        self.assertEqual(code, C.EXIT_OK, err)
        self.assertEqual(
            err.strip(),
            "export --raw: wrote 1 session of opted-out projects and 0 sessions of tightened projects as stored",
        )
        for table in C.EXPORT_DATA_TABLES:
            with self.subTest(table=table):
                as_stored = io.StringIO()
                exp.write_csv(self.db, table, as_stored)
                # Bytes, not read_text(): that would turn csv's \r\n into \n.
                self.assertEqual((out_dir / f"{table}.csv").read_bytes().decode("utf-8"), as_stored.getvalue())

    def test_no_line_names_a_project_a_path_or_a_session(self) -> None:
        names = (self.project_path, str(self.project), "canaryproj", "sess-canary-001", K.PROJECT_ID)
        for changed in ({"ingest_off": True}, {"project_mode": C.REDACT_METADATA_ONLY}):
            for raw in ((), ("--raw",)):
                with self.subTest(changed=changed, raw=bool(raw)):
                    code, _, err = self.export("--table", "all", "--out", str(self.out_dir()), *raw, **changed)
                    self.assertEqual(code, C.EXIT_OK, err)
                    self.assertTrue(err.strip())
                    for name in names:
                        self.assertNotIn(name, err)

    def test_with_nothing_changed_the_default_export_is_the_raw_export(self) -> None:
        default_dir, raw_dir = self.out_dir(), self.out_dir()
        code, _, err = self.export("--table", "all", "--out", str(default_dir))
        self.assertEqual((code, err), (C.EXIT_OK, ""))
        code, _, _ = self.export("--table", "all", "--raw", "--out", str(raw_dir))
        self.assertEqual(code, C.EXIT_OK)
        for table in C.EXPORT_DATA_TABLES:
            with self.subTest(table=table):
                self.assertEqual(
                    (default_dir / f"{table}.csv").read_bytes(), (raw_dir / f"{table}.csv").read_bytes()
                )


class TestExportFloorCliGitRoot(_TwoProjectStore):
    """#478: an opt-out filed under the project's git root, while its
    project_ids entry opts nothing out, still applies."""

    git_repo = True

    def test_an_opt_out_filed_under_the_git_root_key_applies(self) -> None:
        with K.user_config(self.config(by_path={C.CFG_PROJECT_INGEST: C.INGEST_OFF})):
            code, out, err = _run_cli(["export", "--db", self.dsn, "--table", "sessions"])
        self.assertEqual(code, C.EXIT_OK, err)
        self.assertNotIn("sess-canary-001", out)
        self.assertEqual(err.strip(), "export: sessions: 1 row dropped (project opted out)")


if __name__ == "__main__":
    unittest.main()
