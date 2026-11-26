# Tests for per-project privacy granularity: project-key resolution
# (ingest/project_key.py), per-project redaction overrides, and the hard
# ingest opt-out boundary (config.py + ingest/pipeline.py).

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.config import ProjectIdRule, ProjectOverride
from session_analytics.ingest.pipeline import ingest
from session_analytics.ingest.project_key import ProjectKeyResolver, combined_override, match_project_id
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class _CountingFake:
    """A git_toplevel_fn stand-in that counts invocations."""

    def __init__(self, return_value=None) -> None:
        self.calls = 0
        self.return_value = return_value

    def __call__(self, path: str):
        self.calls += 1
        return self.return_value


# ── ProjectKeyResolver (pure, no DB) ────────────────────────────────────


class TestProjectKeyResolver(unittest.TestCase):
    def test_git_toplevel_detection(self) -> None:
        tmp = tempfile.mkdtemp(prefix="cct-sa-test-repo-")
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)

        resolver = ProjectKeyResolver()
        resolved = resolver.resolve(tmp)

        self.assertIsNotNone(resolved)
        # Normalize both sides — macOS /tmp is a symlink to /private/tmp, and
        # git prints the realpath.
        self.assertEqual(Path(resolved).resolve(), Path(tmp).resolve())

    def test_configured_id_map_used_when_not_a_git_repo(self) -> None:
        # A fabricated, non-existent path never spawns git (git_toplevel
        # short-circuits on Path.exists()), so it falls through to the
        # project_ids substring-match rules.
        rules = (ProjectIdRule(match="demo", id="demo-project"),)
        resolver = ProjectKeyResolver(rules)

        resolved = resolver.resolve("/repo/demo")

        self.assertEqual(resolved, "demo-project")
        # The raw input path must never be returned as a bare fallback.
        self.assertNotEqual(resolved, "/repo/demo")

    def test_neither_git_nor_rule_matches_resolves_to_none(self) -> None:
        rules = (ProjectIdRule(match="demo", id="demo-project"),)
        resolver = ProjectKeyResolver(rules)

        resolved = resolver.resolve("/repo/unrelated-project")

        self.assertIsNone(resolved)

    def test_resolve_never_returns_raw_path_unless_it_is_git_toplevel(self) -> None:
        # A real, existing (non-git) temp dir with no matching rule: the
        # resolver must return None, NEVER the raw project_path itself.
        tmp = tempfile.mkdtemp(prefix="cct-sa-test-nogit-")
        resolver = ProjectKeyResolver(())

        resolved = resolver.resolve(tmp)

        self.assertIsNone(resolved)

    def test_cached_per_distinct_project_path(self) -> None:
        # A path no rule matches reaches git detection; the second lookup is
        # served from the cache.
        fake = _CountingFake(return_value="/repo/other")
        rules = (ProjectIdRule(match="demo", id="demo-project"),)
        resolver = ProjectKeyResolver(rules, git_toplevel_fn=fake)

        first = resolver.resolve("/repo/other/sub")
        second = resolver.resolve("/repo/other/sub")

        self.assertEqual(first, "/repo/other")
        self.assertEqual(second, "/repo/other")
        self.assertEqual(fake.calls, 1)  # NOT re-invoked on the cached lookup

    def test_a_checkout_a_rule_matches_has_both_keys(self) -> None:
        # #477: a real git checkout that a project_ids rule matches is filed
        # under the rule's id AND under its repo root, so a projects entry
        # keyed either way applies. A summary names it by the id.
        tmp = tempfile.mkdtemp(prefix="cct-sa-test-repo-")
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True, check=True)
        resolver = ProjectKeyResolver((ProjectIdRule(match=tmp, id="client-a"),))

        keys = resolver.keys(tmp)

        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], "client-a")
        self.assertEqual(Path(keys[1]).resolve(), Path(tmp).resolve())
        self.assertEqual(resolver.resolve(tmp), "client-a")

    def test_both_keys_are_resolved_once_per_path(self) -> None:
        fake = _CountingFake(return_value="/repo/demo")
        resolver = ProjectKeyResolver((ProjectIdRule(match="demo", id="demo-project"),), git_toplevel_fn=fake)

        self.assertEqual(resolver.keys("/repo/demo/sub"), ("demo-project", "/repo/demo"))
        self.assertEqual(resolver.keys("/repo/demo/sub"), ("demo-project", "/repo/demo"))
        self.assertEqual(fake.calls, 1)

    def test_an_id_equal_to_the_repo_root_is_one_key(self) -> None:
        fake = _CountingFake(return_value="/repo/demo")
        resolver = ProjectKeyResolver((ProjectIdRule(match="demo", id="/repo/demo"),), git_toplevel_fn=fake)

        self.assertEqual(resolver.keys("/repo/demo/sub"), ("/repo/demo",))

    def test_falsy_path_never_cached_or_resolved(self) -> None:
        fake = _CountingFake(return_value="/some/repo")
        resolver = ProjectKeyResolver((), git_toplevel_fn=fake)

        self.assertIsNone(resolver.resolve(None))
        self.assertIsNone(resolver.resolve(""))
        self.assertEqual(resolver.keys(None), ())
        self.assertEqual(fake.calls, 0)

    def test_match_project_id_pure_function(self) -> None:
        rules = (
            ProjectIdRule(match="alpha", id="alpha-project"),
            ProjectIdRule(match="beta", id="beta-project"),
        )
        self.assertEqual(match_project_id("/repo/alpha/sub", rules), "alpha-project")
        self.assertEqual(match_project_id("/repo/beta", rules), "beta-project")
        self.assertIsNone(match_project_id("/repo/gamma", rules))
        self.assertIsNone(match_project_id("", rules))


# ── combined_override: one project, entries under two keys (#477) ───────


class TestCombinedOverride(unittest.TestCase):
    N, CODE, M = C.REDACT_NONE, C.REDACT_CODE, C.REDACT_METADATA_ONLY

    def combined(self, by_id, by_path):
        projects = {k: v for k, v in (("client-a", by_id), ("/repo/client-a", by_path)) if v is not None}
        return combined_override(projects, ("client-a", "/repo/client-a"))

    def test_no_entry_under_either_key_is_no_override(self) -> None:
        self.assertIsNone(self.combined(None, None))
        self.assertIsNone(combined_override({"client-a": ProjectOverride()}, ()))

    def test_one_entry_is_that_entry(self) -> None:
        entry = ProjectOverride(redaction_mode=self.M, trace_archive=True)
        self.assertIs(self.combined(entry, None), entry)
        self.assertIs(self.combined(None, entry), entry)

    def test_an_opt_out_under_either_key_opts_out(self) -> None:
        off, on = ProjectOverride(ingest=C.INGEST_OFF), ProjectOverride(redaction_mode=self.N)
        self.assertEqual(self.combined(off, on).ingest, C.INGEST_OFF)
        self.assertEqual(self.combined(on, off).ingest, C.INGEST_OFF)
        self.assertEqual(self.combined(on, on).ingest, C.INGEST_ON)

    def test_conflicting_modes_resolve_to_the_stricter_one(self) -> None:
        for a, b, stricter in (
            (self.N, self.M, self.M), (self.N, self.CODE, self.CODE), (self.CODE, self.M, self.M),
            (self.CODE, self.CODE, self.CODE),
        ):
            with self.subTest(a=a, b=b):
                first, second = ProjectOverride(redaction_mode=a), ProjectOverride(redaction_mode=b)
                self.assertEqual(self.combined(first, second).redaction_mode, stricter)
                self.assertEqual(self.combined(second, first).redaction_mode, stricter)

    def test_a_mode_only_one_entry_states_is_the_mode(self) -> None:
        stated, silent = ProjectOverride(redaction_mode=self.N), ProjectOverride(trace_archive=True)
        self.assertEqual(self.combined(stated, silent).redaction_mode, self.N)
        self.assertEqual(self.combined(silent, stated).redaction_mode, self.N)

    def test_no_stated_mode_leaves_the_global_mode(self) -> None:
        self.assertIsNone(self.combined(ProjectOverride(), ProjectOverride(trace_archive=True)).redaction_mode)

    def test_the_archive_needs_both_entries_to_opt_in(self) -> None:
        yes, no = ProjectOverride(trace_archive=True), ProjectOverride()
        self.assertTrue(self.combined(yes, yes).trace_archive)
        self.assertFalse(self.combined(yes, no).trace_archive)
        self.assertFalse(self.combined(no, yes).trace_archive)


# ── one repository, however its path is spelled (#538) ──────────────────


class TestKeySpelling(unittest.TestCase):
    OFF = ProjectOverride(ingest=C.INGEST_OFF)

    @unittest.skipUnless(os.name == "nt", "Windows path spellings")
    def test_a_windows_path_matches_the_form_git_prints(self) -> None:
        projects = {"C:\\Users\\me\\repo": self.OFF}
        resolver = ProjectKeyResolver((), git_toplevel_fn=lambda p: "C:/Users/me/repo")
        self.assertIs(resolver.override(projects, "C:\\Users\\me\\repo\\src"), self.OFF)
        self.assertEqual(resolver.entry_keys(projects, "C:\\Users\\me\\repo\\src"), ["C:\\Users\\me\\repo"])

    @unittest.skipUnless(os.name == "nt", "Windows path spellings")
    def test_the_forward_slash_form_still_matches(self) -> None:
        resolver = ProjectKeyResolver((), git_toplevel_fn=lambda p: "C:/Users/me/repo")
        self.assertIs(resolver.override({"C:/Users/me/repo": self.OFF}, "C:\\Users\\me\\repo"), self.OFF)

    @unittest.skipUnless(os.name == "nt", "Windows path spellings")
    def test_the_drive_letter_and_folder_case_do_not_matter(self) -> None:
        resolver = ProjectKeyResolver((), git_toplevel_fn=lambda p: "C:/Users/Me/Repo")
        self.assertIs(resolver.override({"c:\\users\\me\\repo": self.OFF}, "C:\\Users\\Me\\Repo"), self.OFF)

    @unittest.skipUnless(os.name == "nt", "Windows path spellings")
    def test_two_spellings_of_one_repository_hold_the_stricter_setting(self) -> None:
        projects = {
            "C:\\Users\\me\\repo": ProjectOverride(redaction_mode=C.REDACT_NONE),
            "C:/Users/me/repo": ProjectOverride(redaction_mode=C.REDACT_METADATA_ONLY),
        }
        self.assertEqual(combined_override(projects, ("C:\\Users\\me\\repo",)).redaction_mode, C.REDACT_METADATA_ONLY)

    def test_a_trailing_or_doubled_separator_still_matches(self) -> None:
        root = os.path.abspath(os.path.join(os.sep, "work", "repo"))
        projects = {root + os.sep: self.OFF}
        self.assertIs(combined_override(projects, (root,)), self.OFF)
        self.assertIs(combined_override({root: self.OFF}, (root + os.sep + os.sep,)), self.OFF)

    def test_an_id_is_compared_as_written(self) -> None:
        self.assertIsNone(combined_override({"Client-A": self.OFF}, ("client-a",)))
        self.assertIs(combined_override({"client-a": self.OFF}, ("client-a",)), self.OFF)

    def test_a_different_repository_does_not_match(self) -> None:
        root = os.path.abspath(os.path.join(os.sep, "work", "repo"))
        self.assertIsNone(combined_override({root: self.OFF}, (root + "-other",)))
        self.assertIsNone(combined_override({root: self.OFF}, (os.path.dirname(root),)))


# ── ingest() integration (per-project privacy) ──────────────────────────


class TestIngestProjectPrivacy(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()

    def _redaction_modes(self, dsn: str) -> list:
        db = Database.connect(dsn)
        try:
            return [r[0] for r in db.query("SELECT redaction_mode FROM copilot_session")]
        finally:
            db.close()

    def _content_previews(self, dsn: str) -> list:
        db = Database.connect(dsn)
        try:
            return [r[0] for r in db.query("SELECT content_preview FROM copilot_turn")]
        finally:
            db.close()

    def _counts(self, dsn: str) -> tuple:
        db = Database.connect(dsn)
        try:
            sessions = db.query("SELECT COUNT(*) FROM copilot_session")[0][0]
            turns = db.query("SELECT COUNT(*) FROM copilot_turn")[0][0]
            return sessions, turns
        finally:
            db.close()

    def test_global_fallback_when_no_projects_configured(self) -> None:
        # FR-6 regression: no projects/project_id_rules passed at all —
        # behavior must be byte-for-byte identical to pre-existing ingest().
        dsn = self.sqlite_dsn()
        stats = ingest(
            dsn=dsn,
            copilots=[C.COPILOT_CLAUDE_CODE],
            root=CLAUDE_CODE_ROOT,
            redaction_mode=C.REDACT_CODE,
            full=True,
        )
        self.assertEqual(stats.sessions_ingested, 1)
        self.assertEqual(stats.sessions_opted_out, 0)
        self.assertEqual(self._redaction_modes(dsn), [C.REDACT_CODE])

    def test_per_project_override_reaches_redaction(self) -> None:
        dsn = self.sqlite_dsn()
        projects = {"demo-project": ProjectOverride(redaction_mode=C.REDACT_METADATA_ONLY)}
        rules = (ProjectIdRule(match="/repo/demo", id="demo-project"),)

        stats = ingest(
            dsn=dsn,
            copilots=[C.COPILOT_CLAUDE_CODE],
            root=CLAUDE_CODE_ROOT,
            redaction_mode=C.REDACT_CODE,  # global default — should be overridden
            full=True,
            projects=projects,
            project_id_rules=rules,
        )

        self.assertEqual(stats.sessions_ingested, 1)
        self.assertEqual(self._redaction_modes(dsn), [C.REDACT_METADATA_ONLY])

        previews = self._content_previews(dsn)
        self.assertTrue(previews)
        joined = " ".join(p or "" for p in previews)
        # metadata-only replaces every non-empty preview with a
        # "[redacted N chars sha256:...]" marker — no prose survives. Turns
        # with no visible text (e.g. a tool_result-only user turn) stay "".
        non_empty = [p for p in previews if p]
        self.assertTrue(non_empty)
        for p in non_empty:
            self.assertTrue(p.startswith("[redacted"), p)
        self.assertNotIn("I'll run the tests", joined)
        self.assertNotIn("Now reading the file", joined)

    def test_ingest_off_skips_entirely(self) -> None:
        dsn = self.sqlite_dsn()
        projects = {"demo-project": ProjectOverride(ingest=C.INGEST_OFF)}
        rules = (ProjectIdRule(match="/repo/demo", id="demo-project"),)

        stats = ingest(
            dsn=dsn,
            copilots=[C.COPILOT_CLAUDE_CODE],
            root=CLAUDE_CODE_ROOT,
            redaction_mode=C.REDACT_CODE,
            full=True,
            projects=projects,
            project_id_rules=rules,
        )

        self.assertEqual(stats.sessions_opted_out, 1)
        self.assertEqual(stats.per_project_opt_out, {"demo-project": 1})
        self.assertEqual(stats.sessions_ingested, 0)
        sessions, turns = self._counts(dsn)
        self.assertEqual(sessions, 0)
        self.assertEqual(turns, 0)

    def test_cli_override_wins_over_project_and_global(self) -> None:
        dsn = self.sqlite_dsn()
        projects = {"demo-project": ProjectOverride(redaction_mode=C.REDACT_METADATA_ONLY)}
        rules = (ProjectIdRule(match="/repo/demo", id="demo-project"),)

        ingest(
            dsn=dsn,
            copilots=[C.COPILOT_CLAUDE_CODE],
            root=CLAUDE_CODE_ROOT,
            redaction_mode=C.REDACT_CODE,
            full=True,
            projects=projects,
            project_id_rules=rules,
            cli_redaction_override=C.REDACT_NONE,
        )

        self.assertEqual(self._redaction_modes(dsn), [C.REDACT_NONE])

    def test_opt_out_is_hard_boundary_even_with_cli_override(self) -> None:
        dsn = self.sqlite_dsn()
        projects = {"demo-project": ProjectOverride(ingest=C.INGEST_OFF)}
        rules = (ProjectIdRule(match="/repo/demo", id="demo-project"),)

        stats = ingest(
            dsn=dsn,
            copilots=[C.COPILOT_CLAUDE_CODE],
            root=CLAUDE_CODE_ROOT,
            redaction_mode=C.REDACT_CODE,
            full=True,
            projects=projects,
            project_id_rules=rules,
            cli_redaction_override=C.REDACT_NONE,  # must NOT override opt-out
        )

        self.assertEqual(stats.sessions_opted_out, 1)
        self.assertEqual(stats.sessions_ingested, 0)
        sessions, turns = self._counts(dsn)
        self.assertEqual(sessions, 0)
        self.assertEqual(turns, 0)


if __name__ == "__main__":
    unittest.main()
