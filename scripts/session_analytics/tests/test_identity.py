# Slice B1 (#187): developer identity derivation + the first writer of the
# `developer` table. Precedence is flag > CCT_DEVELOPER_ID env > config >
# git-email local-part > "local"; a source that does not normalize falls
# through (never fabricated).

from __future__ import annotations

import unittest
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
        for bad in ("", "   ", "!!!", "---", None, 42, "-only-sep-@-"[:1]):
            self.assertIsNone(identity.normalize_developer_id(bad), bad)

    def test_bounds_length_without_trailing_dash(self) -> None:
        out = identity.normalize_developer_id("a" * 63 + "-b")
        self.assertIsNotNone(out)
        self.assertLessEqual(len(out), 64)
        self.assertFalse(out.endswith("-"))


class TestDerivePrecedence(unittest.TestCase):
    def test_flag_wins(self) -> None:
        d = identity.derive_developer_id(
            cli_value="From.Flag",
            env={identity.DEVELOPER_ID_ENV: "from-env"},
            config_value="from-config",
        )
        self.assertEqual((d.id, d.source), ("from-flag", identity.SOURCE_FLAG))

    def test_env_beats_config(self) -> None:
        d = identity.derive_developer_id(
            env={identity.DEVELOPER_ID_ENV: "from-env"},
            config_value="from-config",
        )
        self.assertEqual((d.id, d.source), ("from-env", identity.SOURCE_ENV))

    def test_config_beats_git(self) -> None:
        with mock.patch.object(identity, "_from_git_email", return_value="from-git"):
            d = identity.derive_developer_id(config_value="from-config")
        self.assertEqual((d.id, d.source), ("from-config", identity.SOURCE_CONFIG))

    def test_git_local_part(self) -> None:
        proc = mock.Mock(returncode=0, stdout="Gosha.Ivan@example.com\n")
        with mock.patch.object(identity.subprocess, "run", return_value=proc):
            d = identity.derive_developer_id()
        self.assertEqual((d.id, d.source), ("gosha-ivan", identity.SOURCE_GIT_EMAIL))

    def test_invalid_source_falls_through_not_fabricated(self) -> None:
        # An unusable flag/env/config candidate falls through to git.
        proc = mock.Mock(returncode=0, stdout="dev@example.com\n")
        with mock.patch.object(identity.subprocess, "run", return_value=proc):
            d = identity.derive_developer_id(
                cli_value="!!!",
                env={identity.DEVELOPER_ID_ENV: "###"},
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
            other = upsert_developer(db, "someone-else")
            self.assertNotEqual(first, other)
            db.commit()
        finally:
            db.close()
