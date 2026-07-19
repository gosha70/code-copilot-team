# Tests for session_analytics.archive (E10 Slice A, #98): redaction-safe
# trace archive + portable substring search.
#
# The FR-8 hardenings are binding here: adversarial fixtures must PROVE that
# secrets/code are redacted in stored content, and that opt-out /
# not-opted-in projects produce ZERO trace_document rows.

from __future__ import annotations

import argparse
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from session_analytics import archive as arch
from session_analytics import constants as C
from session_analytics import export as exp
from session_analytics.adapters import claude_code
from session_analytics.config import ProjectIdRule, ProjectOverride, _load_projects
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_RULES = (ProjectIdRule(match="/repo/demo", id="demo-project"),)
_OPTED_IN = {"demo-project": ProjectOverride(trace_archive=True)}


class TestPureHelpers(unittest.TestCase):
    def test_stricter_mode(self) -> None:
        self.assertEqual(arch.stricter_mode(C.REDACT_NONE, C.REDACT_CODE), C.REDACT_CODE)
        self.assertEqual(
            arch.stricter_mode(C.REDACT_METADATA_ONLY, C.REDACT_CODE),
            C.REDACT_METADATA_ONLY,
        )
        self.assertEqual(arch.stricter_mode(C.REDACT_CODE, C.REDACT_CODE), C.REDACT_CODE)
        # FAIL CLOSED: an unknown mode collapses to metadata-only — the
        # strictest mode redact_text actually implements. Returning the
        # unknown string would be a hole (redact_text treats unknown modes
        # as `code`, which is LOOSER than a metadata-only floor).
        self.assertEqual(
            arch.stricter_mode("garbage", C.REDACT_NONE), C.REDACT_METADATA_ONLY
        )
        self.assertEqual(
            arch.stricter_mode(C.REDACT_NONE, "garbage"), C.REDACT_METADATA_ONLY
        )

    def test_escape_like_makes_wildcards_literal(self) -> None:
        self.assertEqual(arch.escape_like("100%"), "100\\%")
        self.assertEqual(arch.escape_like("a_b"), "a\\_b")
        self.assertEqual(arch.escape_like("back\\slash"), "back\\\\slash")
        self.assertEqual(arch.escape_like("plain"), "plain")

    def test_make_snippet_windows_and_ellipses(self) -> None:
        content = ("x" * 500) + "NEEDLE" + ("y" * 500)
        snip = arch.make_snippet(content, "needle")
        self.assertIn("NEEDLE", snip)
        self.assertTrue(snip.startswith("…") and snip.endswith("…"))
        self.assertLessEqual(len(snip), 2 * C.SEARCH_SNIPPET_CHARS + len("NEEDLE") + 2)
        # Head fallback when the query isn't found in the content.
        self.assertTrue(arch.make_snippet("short content", "absent").startswith("short"))

    def test_config_parses_trace_archive_strict_bool(self) -> None:
        projects, _ = _load_projects(
            {C.CFG_PROJECTS: {"p": {C.CFG_PROJECT_TRACE_ARCHIVE: True}, "q": {}}}
        )
        self.assertTrue(projects["p"].trace_archive)
        self.assertFalse(projects["q"].trace_archive)  # default OFF
        for bad in ("true", 1, "yes"):
            with self.assertRaises(ValueError):
                _load_projects(
                    {C.CFG_PROJECTS: {"p": {C.CFG_PROJECT_TRACE_ARCHIVE: bad}}}
                )


class TestArchiveIntegration(RegistryResetTestCase):
    """sqlite end-to-end: opt-in gate, redaction floor, survival, search."""

    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()

    def _ingest(self, **kw) -> None:
        ingest(
            dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            full=True, **kw,
        )

    def _archive(self, projects=None, **kw) -> arch.ArchiveStats:
        return arch.archive(
            dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            projects=projects, project_id_rules=_RULES, full=True, **kw,
        )

    def _rows(self) -> list[tuple]:
        db = Database.connect(self.dsn)
        try:
            return list(db.query(
                f"SELECT session_ref, sequence_num, content, redaction_mode "
                f"FROM {C.TBL_TRACE_DOCUMENT} ORDER BY sequence_num"
            ))
        finally:
            db.close()

    def test_not_opted_in_produces_zero_rows(self) -> None:
        self._ingest()
        stats = self._archive(projects={})  # no override at all
        self.assertEqual(stats.sessions_skipped_not_opted_in, 1)
        self.assertEqual(stats.sessions_archived, 0)
        self.assertEqual(self._rows(), [])

    def test_opted_out_produces_zero_rows_even_with_trace_archive_true(self) -> None:
        self._ingest()
        projects = {
            "demo-project": ProjectOverride(ingest=C.INGEST_OFF, trace_archive=True)
        }
        stats = self._archive(projects=projects)
        self.assertEqual(stats.sessions_opted_out, 1)
        self.assertEqual(self._rows(), [])  # opt-out beats opt-in, always

    def test_opted_in_archives_per_turn_and_is_idempotent(self) -> None:
        self._ingest()
        stats = self._archive(projects=_OPTED_IN)
        self.assertEqual(stats.sessions_archived, 1)
        self.assertEqual(stats.sessions_deferred, 0)
        rows = self._rows()
        self.assertGreater(len(rows), 0)
        self.assertEqual(stats.turns_archived, len(rows))
        self.assertTrue(all(r[1] is not None for r in rows))  # per-turn seqs
        # Idempotent re-run: same row count.
        self._archive(projects=_OPTED_IN)
        self.assertEqual(len(self._rows()), len(rows))

    def test_reingest_after_archive_does_not_break_ingest(self) -> None:
        # Regression for the FK-anchoring bug: re-ingest DELETEs + reinserts
        # copilot_turn rows; the archive must anchor by sequence_num (no turn
        # id FK) so a full re-ingest of an ARCHIVED session succeeds and the
        # archived rows survive intact.
        self._ingest()
        self._archive(projects=_OPTED_IN)
        rows_before = self._rows()
        self.assertGreater(len(rows_before), 0)
        self._ingest()  # --full re-ingest; would raise IntegrityError with an id FK
        self.assertEqual(self._rows(), rows_before)  # archive untouched

    def test_later_opt_out_purges_archived_rows(self) -> None:
        # Privacy invariant holds CONTINUOUSLY: rows archived while opted in
        # are purged on the next run after the project opts out.
        self._ingest()
        self._archive(projects=_OPTED_IN)
        self.assertGreater(len(self._rows()), 0)
        opted_out = {
            "demo-project": ProjectOverride(ingest=C.INGEST_OFF, trace_archive=True)
        }
        stats = self._archive(projects=opted_out)
        self.assertEqual(stats.sessions_purged, 1)
        self.assertEqual(self._rows(), [])

    def test_revoked_opt_in_purges_archived_rows(self) -> None:
        self._ingest()
        self._archive(projects=_OPTED_IN)
        self.assertGreater(len(self._rows()), 0)
        stats = self._archive(projects={})  # opt-in removed entirely
        self.assertEqual(stats.sessions_purged, 1)
        self.assertEqual(self._rows(), [])

    def test_lagging_store_defers_and_retries(self) -> None:
        # A source turn the store hasn't ingested (simulated by deleting a
        # stored turn row) must DEFER the session: anchored turns archive,
        # no walk state is stamped, and the next run retries instead of
        # reporting skipped_unchanged.
        self._ingest()
        db = Database.connect(self.dsn)
        try:
            # Delete one turn with no tool-call children (FK-safe).
            row = db.query_one(
                "SELECT t.id FROM copilot_turn t "
                "WHERE NOT EXISTS (SELECT 1 FROM copilot_tool_call tc "
                "                  WHERE tc.turn_id = t.id) "
                "ORDER BY t.sequence_num DESC LIMIT 1"
            )
            db.execute("DELETE FROM copilot_turn WHERE id = ?", (row[0],))
            db.commit()
            total_turns = db.query_one("SELECT COUNT(*) FROM copilot_turn")[0]
        finally:
            db.close()
        stats = self._archive(projects=_OPTED_IN, )
        self.assertEqual(stats.sessions_deferred, 1)
        self.assertEqual(stats.sessions_archived, 0)
        self.assertEqual(len(self._rows()), total_turns)  # anchored turns landed
        # No walk state stamped → an INCREMENTAL re-run retries (not
        # skipped_unchanged).
        stats2 = arch.archive(
            dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            projects=_OPTED_IN, project_id_rules=_RULES, full=False,
        )
        self.assertEqual(stats2.sessions_skipped_unchanged, 0)
        self.assertEqual(stats2.sessions_deferred, 1)

    def test_not_opted_in_counter_names_project_keys(self) -> None:
        self._ingest()
        stats = self._archive(projects={})
        self.assertEqual(stats.per_project_not_opted_in, {"demo-project": 1})

    def test_not_ingested_sessions_are_counted_and_skipped(self) -> None:
        # No ingest first — archive must not substitute for it.
        db = Database.connect(self.dsn)
        apply_ddl(db)
        db.close()
        stats = self._archive(projects=_OPTED_IN)
        self.assertEqual(stats.sessions_not_ingested, 1)
        self.assertEqual(self._rows(), [])

    def test_redaction_floor_never_looser_than_ingested_mode(self) -> None:
        # Ingested under metadata-only; config now says none → floor wins.
        self._ingest(redaction_mode=C.REDACT_METADATA_ONLY)
        projects = {
            "demo-project": ProjectOverride(
                redaction_mode=C.REDACT_NONE, trace_archive=True
            )
        }
        stats = self._archive(projects=projects)
        self.assertEqual(stats.per_mode, {C.REDACT_METADATA_ONLY: 1})
        for _, _, content, mode in self._rows():
            self.assertEqual(mode, C.REDACT_METADATA_ONLY)
            if content:
                self.assertTrue(content.startswith("[redacted"))

    def test_adversarial_redaction_code_mode_strips_fences(self) -> None:
        # FR-8 hardening: whatever sits inside a fenced block must come out
        # as a marker under `code` mode — never verbatim — so a leaked
        # credential in a transcript cannot reach the archive.
        #
        # The payload is a synthetic canary, deliberately NOT credential-
        # shaped: `code`-mode redaction is content-agnostic (it strips fenced
        # blocks by regex, never inspecting what is inside), so an
        # API-key-shaped literal would prove nothing extra while tripping
        # every secret scanner that ever runs on this repo.
        self._ingest(redaction_mode=C.REDACT_CODE)
        fenced_payload = "CANARY-FENCED-PAYLOAD-MUST-NOT-BE-ARCHIVED"
        fixture_src = Path(tempfile.mkdtemp(prefix="cct-adv-"))
        self.addCleanup(shutil.rmtree, fixture_src, ignore_errors=True)
        proj = fixture_src / "proj"
        proj.mkdir()
        lines = [
            json.dumps({"type": "system", "subtype": "init",
                        "sessionId": "sess-adv-1", "model": "m",
                        "cwd": "/repo/demo", "uuid": "u0",
                        "timestamp": "2026-07-18T00:00:00Z"}),
            json.dumps({"type": "user", "uuid": "u1", "cwd": "/repo/demo",
                        "timestamp": "2026-07-18T00:00:01Z",
                        "message": {"role": "user", "content": [
                            {"type": "text",
                             "text": f"key is ```\n{fenced_payload}\n``` ok?"}]}}),
        ]
        (proj / "sess-adv-1.jsonl").write_text("\n".join(lines))
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=fixture_src,
               full=True, redaction_mode=C.REDACT_CODE)
        arch.archive(
            dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=fixture_src,
            projects=_OPTED_IN, project_id_rules=_RULES, full=True,
        )
        db = Database.connect(self.dsn)
        try:
            contents = [r[0] or "" for r in db.query(
                f"SELECT content FROM {C.TBL_TRACE_DOCUMENT}"
            )]
        finally:
            db.close()
        joined = "\n".join(contents)
        # Fenced content never lands in the archive; the marker does.
        self.assertNotIn(fenced_payload, joined)
        self.assertIn("[code redacted", joined)

    def test_archived_text_survives_source_deletion_and_is_searchable(self) -> None:
        # Copy the fixture to a temp root so we can delete the "source".
        root = Path(tempfile.mkdtemp(prefix="cct-survive-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        shutil.copytree(CLAUDE_CODE_ROOT, root, dirs_exist_ok=True)
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=root, full=True)
        arch.archive(
            dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=root,
            projects=_OPTED_IN, project_id_rules=_RULES, full=True,
        )
        rows_before = self._rows()
        self.assertGreater(len(rows_before), 0)
        shutil.rmtree(root)  # the source evaporates (cleanupPeriodDays analog)
        db = Database.connect(self.dsn)
        try:
            # Pick a word we know survives redaction from the stored rows.
            probe = next(
                w for r in rows_before if r[2]
                for w in r[2].split() if len(w) > 4 and "[" not in w
            )
            results = arch.search_traces(db, probe)
        finally:
            db.close()
        self.assertGreater(len(results), 0)
        self.assertIn("snippet", results[0])

    def test_search_wildcards_literal_and_limit_clamped(self) -> None:
        self._ingest()
        self._archive(projects=_OPTED_IN)
        db = Database.connect(self.dsn)
        try:
            # '%' as a literal must NOT match everything.
            all_rows = arch.search_traces(db, "%")
            everything = arch.search_traces(db, "e")  # common letter
            self.assertLessEqual(len(all_rows), len(everything))
            if not any("%" in (r[2] or "") for r in self._rows()):
                self.assertEqual(all_rows, [])
            # Limit clamps to at least 1 and at most SEARCH_MAX_LIMIT.
            self.assertLessEqual(
                len(arch.search_traces(db, "e", limit=10_000)), C.SEARCH_MAX_LIMIT
            )
            self.assertLessEqual(len(arch.search_traces(db, "e", limit=0)), 1)
        finally:
            db.close()

    def test_export_includes_trace_documents(self) -> None:
        self.assertIn(C.EXPORT_TABLE_TRACE_DOCUMENTS, C.EXPORT_DATA_TABLES)
        self._ingest()
        self._archive(projects=_OPTED_IN)
        db = Database.connect(self.dsn)
        try:
            rows = list(exp.rows_for(db, C.EXPORT_TABLE_TRACE_DOCUMENTS))
        finally:
            db.close()
        self.assertGreater(len(rows), 0)
        row = dict(zip(exp.TRACE_DOCUMENTS_COLUMNS, rows[0]))
        self.assertEqual(row["source_kind"], C.SOURCE_KIND_COPILOT_TRANSCRIPT)
        self.assertEqual(row["redaction_mode"], C.REDACT_CODE)

    def test_apply_ddl_retrofits_tables(self) -> None:
        db = Database.connect(self.dsn)
        try:
            apply_ddl(db)
            db.execute(f"DROP TABLE {C.TBL_TRACE_DOCUMENT}")
            db.execute(f"DROP TABLE {C.TBL_TRACE_ARCHIVE_STATE}")
            db.commit()
            apply_ddl(db)
            for tbl in (C.TBL_TRACE_DOCUMENT, C.TBL_TRACE_ARCHIVE_STATE):
                row = db.query_one(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (tbl,),
                )
                self.assertIsNotNone(row, tbl)
        finally:
            db.close()

    def test_cli_archive_and_search_end_to_end(self) -> None:
        from session_analytics.cli import _cmd_archive, _cmd_search

        self._ingest()
        # CLI resolves projects from config; simulate by patching load_config?
        # Simpler: drive archive() directly (covered above) and use the CLI
        # for search — plus the empty-query usage error.
        self._archive(projects=_OPTED_IN)
        out = io.StringIO()
        with redirect_stdout(out):
            code = _cmd_search(argparse.Namespace(query="e", limit=5, dsn=self.dsn))
        self.assertEqual(code, C.EXIT_OK)
        payload = json.loads(out.getvalue())
        self.assertLessEqual(len(payload["results"]), 5)
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = _cmd_search(argparse.Namespace(query="   ", limit=5, dsn=self.dsn))
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("empty search query", err.getvalue())


if __name__ == "__main__":
    unittest.main()
