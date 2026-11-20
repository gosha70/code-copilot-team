"""#457 FR-006: the current-mode floor, with no re-ingest.

The corpus is ingested under ``none`` and under ``code``. Then the
configuration changes:

* tightened to ``metadata-only`` (per project, and globally): no canary
  reaches any off-machine path;
* the project opted out (``ingest: "off"``): nothing from the session
  reaches any path, not a canary, a marker, its native id or its project.
"""

from __future__ import annotations

import json
import unittest

from session_analytics import constants as C
from session_analytics.tests import canary as K
from session_analytics.tests.support import RegistryResetTestCase

M = C.REDACT_METADATA_ONLY


class TheFloorAppliesWithoutReingest(RegistryResetTestCase):
    def ingest_then(self, ingested: str, *, archive: bool = True, **changed) -> dict[str, str]:
        dsn = self.sqlite_dsn()
        with K.corpus() as (source, project):
            with K.user_config(K.config_for(project, project_mode=ingested, archive=archive)):
                sid = K.ingest_corpus(dsn, source)
            with K.user_config(K.config_for(project, archive=archive, **changed)):
                return K.capture_all(dsn, sid)

    # With and without the trace archive: paths such as Ask's search read
    # archived text when it exists and previews otherwise.
    CASES = [(i, a) for i in (C.REDACT_NONE, C.REDACT_CODE) for a in (True, False)]

    def test_a_project_tightened_after_ingest_sends_no_canary(self):
        for ingested, archive in self.CASES:
            with self.subTest(ingested=ingested, archive=archive):
                captured = self.ingest_then(ingested, archive=archive, project_mode=M)
                K.assert_no_leak(self, captured, M)
                # A tightened session's search hits are skipped, not masked:
                # a masked snippet would still say its text matched (#457).
                self.assertEqual(json.loads(captured["ask search_text"])["hits"], [])

    def test_a_global_mode_tightened_after_ingest_sends_no_canary(self):
        for ingested, archive in self.CASES:
            with self.subTest(ingested=ingested, archive=archive):
                K.assert_no_leak(self, self.ingest_then(ingested, archive=archive, global_mode=M), M)

    def test_an_opted_out_project_sends_nothing_from_its_sessions(self):
        for ingested in (C.REDACT_NONE, C.REDACT_CODE):
            with self.subTest(ingested=ingested):
                captured = self.ingest_then(ingested, project_mode=ingested, ingest_off=True)
                named = {
                    path: [w for w in ("sess-canary-001", "canaryproj", *K.CANARIES.values()) if w in text]
                    for path, text in captured.items()
                }
                self.assertEqual({p: w for p, w in named.items() if w}, {})
                # The judges were not called at all: analysis is refused and
                # the per-turn judge selects none of its turns.
                self.assertEqual(captured["per-turn judge"], "")
                self.assertEqual(captured["session analysis"], "")
                self.assertEqual(captured["embedding"], "")


    @unittest.skipUnless(K.HAS_KUZU, "kuzu not installed; graph canaries skipped (covered in CI)")
    def test_a_graph_question_naming_an_opted_out_project_or_session_is_refused(self):
        """Their rows carry only tool names and counts, so filtering the
        rows cannot help: the parameter itself is refused."""
        queries = ("ask graph tools-in-session", "ask graph errors-by-tool-in-project")
        dsn = self.sqlite_dsn()
        with K.corpus() as (source, project):
            with K.user_config(K.config_for(project, project_mode=C.REDACT_NONE)):
                sid = K.ingest_corpus(dsn, source)
                before = K.capture_ask(dsn, sid)
            with K.user_config(K.config_for(project, project_mode=C.REDACT_NONE, ingest_off=True)):
                after = K.capture_ask(dsn, sid)
        for label in queries:
            with self.subTest(query=label):
                answered = json.loads(before[label])
                self.assertNotIn("error", answered)
                self.assertTrue(answered.get("rows"), answered)
                self.assertEqual(
                    json.loads(after[label]),
                    {"error": "that project or session is not available: it is opted out"},
                )


    def test_a_setting_under_either_key_applies_inside_a_git_checkout(self):
        """#477: the corpus project is a git repository that a project_ids
        rule matches, so its settings may be filed under the rule's id or
        under its repo path. A tightening and an opt-out reach every path
        either way, and the path entry holds against a looser id entry."""
        for label, changed in (
            ("tightened by id", dict(project_mode=M)),
            ("opted out by id", dict(project_mode=C.REDACT_NONE, ingest_off=True)),
            ("tightened by path", dict(project_mode=C.REDACT_NONE, by_path={C.CFG_REDACTION: M})),
            ("opted out by path", dict(project_mode=C.REDACT_NONE, by_path={C.CFG_PROJECT_INGEST: C.INGEST_OFF})),
        ):
            with self.subTest(change=label):
                dsn = self.sqlite_dsn()
                with K.corpus(git_repo=True) as (source, project):
                    with K.user_config(K.config_for(project, project_mode=C.REDACT_NONE)):
                        sid = K.ingest_corpus(dsn, source)
                    with K.user_config(K.config_for(project, **changed)):
                        captured = K.capture_all(dsn, sid)
                if label.startswith("tightened"):
                    K.assert_no_leak(self, captured, M)
                else:
                    named = {
                        path: [w for w in ("sess-canary-001", "canaryproj", *K.CANARIES.values()) if w in text]
                        for path, text in captured.items()
                    }
                    self.assertEqual({p: w for p, w in named.items() if w}, {})

    def test_an_opt_out_keyed_by_a_project_id_stops_ingest_inside_a_git_checkout(self):
        from session_analytics._register import register_all
        from session_analytics.config import load_config
        from session_analytics.ingest.pipeline import configured_options, ingest

        register_all()
        dsn = self.sqlite_dsn()
        with K.corpus(git_repo=True) as (source, project):
            with K.user_config(K.config_for(project, ingest_off=True)):
                stats = ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=source, full=True,
                               **configured_options(load_config()))
        self.assertEqual((stats.sessions_ingested, stats.sessions_opted_out), (0, 1))

    def test_an_opt_out_keyed_by_the_repo_path_holds_inside_a_broad_rule(self):
        """A rule broad enough to cover several repositories, and one of
        them opted out by its own path: it is not ingested, and the summary
        counts it under the key that opts it out."""
        from session_analytics._register import register_all
        from session_analytics.config import load_config
        from session_analytics.ingest.pipeline import configured_options, ingest

        register_all()
        dsn = self.sqlite_dsn()
        with K.corpus(git_repo=True) as (source, project):
            repo = str(project.resolve())
            config = {
                C.CFG_PROJECTS: {
                    "everything": {C.CFG_REDACTION: C.REDACT_NONE},
                    repo: {C.CFG_PROJECT_INGEST: C.INGEST_OFF},
                },
                C.CFG_PROJECT_IDS: [{C.CFG_PROJECT_ID_MATCH: str(project.parent), C.CFG_PROJECT_ID_ID: "everything"}],
            }
            with K.user_config(config):
                stats = ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=source, full=True,
                               **configured_options(load_config()))
        self.assertEqual((stats.sessions_ingested, stats.sessions_opted_out), (0, 1))
        self.assertEqual(stats.per_project_opt_out, {repo: 1})

    def test_conflicting_modes_ingest_under_the_stricter_one(self):
        """The id entry and the path entry state different modes: the
        session is stored under the stricter, whichever key states it."""
        from session_analytics.relational.db import Database

        for by_id, by_path, stricter in (
            (C.REDACT_NONE, M, M), (M, C.REDACT_NONE, M),
            (C.REDACT_NONE, C.REDACT_CODE, C.REDACT_CODE), (C.REDACT_CODE, C.REDACT_NONE, C.REDACT_CODE),
        ):
            with self.subTest(by_id=by_id, by_path=by_path):
                dsn = self.sqlite_dsn()
                with K.corpus(git_repo=True) as (source, project):
                    with K.user_config(K.config_for(project, project_mode=by_id, by_path={C.CFG_REDACTION: by_path})):
                        sid = K.ingest_corpus(dsn, source)
                db = Database.connect(dsn)
                try:
                    recorded = db.query_one("SELECT redaction_mode FROM copilot_session WHERE id = ?", (sid,))[0]
                finally:
                    db.close()
                self.assertEqual(recorded, stricter)

    def test_the_trace_archive_reads_both_keys(self):
        """Archived on an opt-in filed under the id; purged, and not
        archived again, once the path entry opts the project out or is
        there without opting in."""
        from session_analytics import archive as arch
        from session_analytics.config import load_config
        from session_analytics.relational.db import Database

        def archived(dsn: str) -> int:
            db = Database.connect(dsn)
            try:
                return int(db.query_one(f"SELECT COUNT(*) FROM {C.TBL_TRACE_DOCUMENT}")[0])
            finally:
                db.close()

        for label, by_path, counter in (
            ("opted out by path", {C.CFG_PROJECT_INGEST: C.INGEST_OFF}, "sessions_opted_out"),
            ("a path entry that does not opt in", {C.CFG_REDACTION: M}, "sessions_skipped_not_opted_in"),
        ):
            with self.subTest(change=label):
                dsn = self.sqlite_dsn()
                with K.corpus(git_repo=True) as (source, project):
                    with K.user_config(K.config_for(project, project_mode=C.REDACT_NONE)):
                        K.ingest_corpus(dsn, source)
                    self.assertGreater(archived(dsn), 0)
                    with K.user_config(K.config_for(project, project_mode=C.REDACT_NONE, by_path=by_path)):
                        cfg = load_config()
                        stats = arch.archive(
                            dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=source, full=True,
                            redaction_mode=cfg.redaction_mode, projects=cfg.projects,
                            project_id_rules=cfg.project_id_rules,
                        )
                self.assertEqual(getattr(stats, counter), 1)
                self.assertEqual(archived(dsn), 0)


if __name__ == "__main__":
    unittest.main()
