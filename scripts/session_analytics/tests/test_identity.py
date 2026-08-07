# Slice B1 (#187): developer identity derivation + the first writer of the
# `developer` table. Precedence is flag (verbatim) > CCT_DEVELOPER_ID
# (loader-resolved env/.env) > config > git --global email local-part >
# "local"; a source that does not survive sanitation falls through (never
# fabricated). Includes the pipeline-persistence regression from the PR #188
# review (finding 1): a zero-ingest incremental run must still COMMIT the
# developer row.

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from session_analytics import constants as C
from session_analytics import identity
from session_analytics.relational.db import Database, apply_ddl
from session_analytics.relational.store import upsert_developer

from session_analytics.tests.support import RegistryResetTestCase


class TestNormalize(unittest.TestCase):
    def test_lowercases_and_maps_separators(self) -> None:
        self.assertEqual(identity.normalize_developer_id("Gosha.Ivan"), "gosha-ivan")
        self.assertEqual(identity.normalize_developer_id("g_o sha"), "g-o-sha")
        self.assertEqual(identity.normalize_developer_id("a+b@c"), "a-b-c")

    def test_strips_invalid_and_collapses(self) -> None:
        self.assertEqual(identity.normalize_developer_id("--gosha--!!"), "gosha")
        self.assertEqual(identity.normalize_developer_id("g..--..o"), "g-o")

    def test_rejects_unusable(self) -> None:
        for bad in ("", "   ", "!!!", "---", "-", None, 42):
            self.assertIsNone(identity.normalize_developer_id(bad), bad)

    def test_non_ascii_falls_through_never_fabricated(self) -> None:
        # The sharpest "never fabricated" edge: nothing latin survives.
        self.assertIsNone(identity.normalize_developer_id("Ярослав"))
        self.assertIsNone(identity.normalize_developer_id("郭"))

    def test_bounds_length_without_trailing_dash(self) -> None:
        out = identity.normalize_developer_id("a" * 63 + "-b")
        self.assertIsNotNone(out)
        self.assertLessEqual(len(out), 64)
        self.assertFalse(out.endswith("-"))


class TestDerivePrecedence(unittest.TestCase):
    def test_flag_wins_and_is_verbatim(self) -> None:
        # Explicit values are honored AS GIVEN (upgrade compatibility with
        # pre-B1 stamps like "Team_A") — only derived sources normalize.
        d = identity.derive_developer_id(
            cli_value="Team_A",
            env_value="from-env",
            config_value="from-config",
        )
        self.assertEqual((d.id, d.source), ("Team_A", identity.SOURCE_FLAG))

    def test_flag_control_chars_stripped_but_case_kept(self) -> None:
        d = identity.derive_developer_id(cli_value="  From.Flag\x07  ")
        self.assertEqual((d.id, d.source), ("From.Flag", identity.SOURCE_FLAG))

    def test_env_beats_config(self) -> None:
        d = identity.derive_developer_id(
            env_value="from-env",
            config_value="from-config",
        )
        self.assertEqual((d.id, d.source), ("from-env", identity.SOURCE_ENV))

    def test_config_beats_git(self) -> None:
        with mock.patch.object(
            identity, "_from_git_global_email", return_value="from-git"
        ):
            d = identity.derive_developer_id(config_value="from-config")
        self.assertEqual((d.id, d.source), ("from-config", identity.SOURCE_CONFIG))

    def test_git_global_local_part(self) -> None:
        proc = mock.Mock(returncode=0, stdout="Gosha.Ivan@example.com\n")
        with mock.patch.object(identity.subprocess, "run", return_value=proc) as run:
            d = identity.derive_developer_id()
        self.assertEqual((d.id, d.source), ("gosha-ivan", identity.SOURCE_GIT_EMAIL))
        # MACHINE identity: --global only, and never launch-dir dependent.
        argv = run.call_args.args[0]
        self.assertIn("--global", argv)
        self.assertNotIn("cwd", run.call_args.kwargs or {})

    def test_invalid_source_falls_through_not_fabricated(self) -> None:
        # An unusable flag/env/config candidate falls through to git.
        proc = mock.Mock(returncode=0, stdout="dev@example.com\n")
        with mock.patch.object(identity.subprocess, "run", return_value=proc):
            d = identity.derive_developer_id(
                cli_value="\x01\x02",
                env_value="###",
                config_value="   ",
            )
        self.assertEqual((d.id, d.source), ("dev", identity.SOURCE_GIT_EMAIL))

    def test_terminal_fallback_is_local(self) -> None:
        for failure in (
            mock.Mock(returncode=1, stdout=""),
            mock.Mock(returncode=0, stdout="\n"),
            mock.Mock(returncode=0, stdout="@example.com\n"),  # empty local part
        ):
            with mock.patch.object(identity.subprocess, "run", return_value=failure):
                d = identity.derive_developer_id()
            self.assertEqual(
                (d.id, d.source), (C.DEFAULT_DEVELOPER_ID, identity.SOURCE_FALLBACK)
            )

    def test_git_failure_modes_are_safe(self) -> None:
        for exc in (OSError("no git"), identity.subprocess.TimeoutExpired("git", 5)):
            with mock.patch.object(identity.subprocess, "run", side_effect=exc):
                d = identity.derive_developer_id()
            self.assertEqual(d.source, identity.SOURCE_FALLBACK)


class TestUpsertDeveloper(RegistryResetTestCase):
    def test_idempotent_and_name_preserving(self) -> None:
        db = Database.connect(self.sqlite_dsn())
        try:
            apply_ddl(db)
            first = upsert_developer(db, "gosha", "Gosha")
            again = upsert_developer(db, "gosha")  # no display_name
            self.assertEqual(first, again)
            row = db.query_one(
                "SELECT developer_id, display_name FROM developer WHERE id = ?",
                (first,),
            )
            self.assertEqual(tuple(row), ("gosha", "Gosha"))  # name preserved
            renamed = upsert_developer(db, "gosha", "Georgy")
            self.assertEqual(renamed, first)
            row = db.query_one(
                "SELECT display_name FROM developer WHERE id = ?", (first,)
            )
            self.assertEqual(row[0], "Georgy")  # non-NULL update applies
            other = upsert_developer(db, "someone-else")
            self.assertNotEqual(first, other)
            db.commit()
        finally:
            db.close()


class TestPipelinePersistsDeveloper(RegistryResetTestCase):
    def test_zero_ingest_run_still_commits_the_developer_row(self) -> None:
        # PR #188 review finding 1: an incremental run that ingests NOTHING
        # (empty source root — the steady state of `watch`) must still
        # persist the developer registration; an uncommitted INSERT would
        # roll back on close and leave the table empty forever.
        import tempfile

        from session_analytics._register import register_all
        from session_analytics.ingest.pipeline import ingest

        register_all()  # RegistryResetTestCase.setUp cleared the registry
        dsn = self.sqlite_dsn()
        empty_root = Path(tempfile.mkdtemp(prefix="cct-sa-empty-"))
        stats = ingest(
            dsn=dsn, copilots=["pi"], root=empty_root, developer_id="alice"
        )
        self.assertEqual(stats.sessions_ingested, 0)
        db = Database.connect(dsn)
        try:
            row = db.query_one(
                "SELECT developer_id FROM developer WHERE developer_id = ?",
                ("alice",),
            )
            self.assertIsNotNone(row)  # survived close: committed
        finally:
            db.close()


class TestCliDerivation(unittest.TestCase):
    """_derived_developer_id plumbing (PR #188 review B-9): loader-resolved
    env/.env + config inputs, the WARNING on a dropped explicit flag, and
    the watch parser carrying --developer-id."""

    @staticmethod
    def _cfg(env_value=None, cfg_value=None):
        # A real load_config() against empty overrides would read the host's
        # ~/.cct + repo .env; a minimal hand-built config keeps the test
        # hermetic. Only the identity fields matter here.
        from session_analytics.config import AnalyticsConfig, JudgeConfig
        from session_analytics.cost import PricingConfig

        judge = JudgeConfig(
            override=None,
            by_copilot={},
            default=("none", ""),
            workers=1,
            ollama_url="",
            base_url="",
            api_key="",
        )
        return AnalyticsConfig(
            sources={},
            dsn="sqlite:///unused",
            kuzu_path="unused",
            redaction_mode="code",
            judge=judge,
            pricing=PricingConfig(models={}),
            developer_id_env=env_value,
            developer_id_cfg=cfg_value,
        )

    def test_loader_resolved_env_beats_config(self) -> None:
        import argparse

        from session_analytics.cli import _derived_developer_id

        args = argparse.Namespace(developer_id=None)
        got = _derived_developer_id(
            args, self._cfg(env_value="From.Env", cfg_value="from-config")
        )
        self.assertEqual(got, "from-env")  # derived sources normalize

    def test_dropped_explicit_flag_warns_and_names_fallback(self) -> None:
        import argparse

        from session_analytics.cli import _derived_developer_id

        args = argparse.Namespace(developer_id="\x01\x02")
        with self.assertLogs("session_analytics.cli", level="WARNING") as logs:
            got = _derived_developer_id(args, self._cfg(cfg_value="cfg-id"))
        self.assertEqual(got, "cfg-id")
        self.assertTrue(any("unusable after sanitation" in m for m in logs.output))

    def test_watch_parser_accepts_developer_id(self) -> None:
        from session_analytics.cli import _build_parser

        args = _build_parser().parse_args(
            ["watch", "--developer-id", "Team_A", "--interval", "5"]
        )
        self.assertEqual(args.developer_id, "Team_A")

    def test_config_type_error_is_raised_not_fabricated(self) -> None:
        from session_analytics.config import _developer_id_cfg

        with self.assertRaises(ValueError):
            _developer_id_cfg({"developer_id": {"a": 1}})
        self.assertIsNone(_developer_id_cfg({}))
        self.assertEqual(_developer_id_cfg({"developer_id": "x"}), "x")


class TestUpsertSqlIsTheRealStatement(unittest.TestCase):
    def test_translate_targets_the_shipped_sql(self) -> None:
        # B-9: exercise the REAL statement, not a hand-written copy.
        from session_analytics.relational.store import UPSERT_DEVELOPER_SQL

        d = Database(conn=None, dialect="postgres")
        translated = d._translate(UPSERT_DEVELOPER_SQL)
        self.assertIn("%s", translated)
        self.assertNotIn("?", translated)
        self.assertIn("ON CONFLICT (developer_id)", translated)
