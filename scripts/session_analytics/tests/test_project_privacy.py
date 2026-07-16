# Tests for per-project privacy granularity: project-key resolution
# (ingest/project_key.py), per-project redaction overrides, and the hard
# ingest opt-out boundary (config.py + ingest/pipeline.py).

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.config import ProjectIdRule, ProjectOverride
from session_analytics.ingest.pipeline import ingest
from session_analytics.ingest.project_key import ProjectKeyResolver, match_project_id
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
        fake = _CountingFake(return_value=None)
        rules = (ProjectIdRule(match="demo", id="demo-project"),)
        resolver = ProjectKeyResolver(rules, git_toplevel_fn=fake)

        first = resolver.resolve("/repo/demo")
        second = resolver.resolve("/repo/demo")

        self.assertEqual(first, "demo-project")
        self.assertEqual(second, "demo-project")
        self.assertEqual(fake.calls, 1)  # NOT re-invoked on the cached lookup

    def test_falsy_path_never_cached_or_resolved(self) -> None:
        fake = _CountingFake(return_value="/some/repo")
        resolver = ProjectKeyResolver((), git_toplevel_fn=fake)

        self.assertIsNone(resolver.resolve(None))
        self.assertIsNone(resolver.resolve(""))
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
