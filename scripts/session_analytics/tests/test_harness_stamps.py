# The harness stamp (#371 A4a): the ledger reader, the hook by direct
# invocation, the adapter join (earliest + mixed), the store columns, the
# schema refusal, and the plugin exclusion.

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics import harness_stamps as hs
from session_analytics.adapters.claude_code import ClaudeCodeAdapter
from session_analytics.ingest.pipeline import ingest
from session_analytics.mcp import tools
from session_analytics.relational import db as dbmod
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_REPO = Path(__file__).resolve().parents[3]
_HOOK = _REPO / "adapters" / "claude-code" / ".claude" / "hooks" / "harness-stamp.sh"
_SETTINGS = _REPO / "adapters" / "claude-code" / ".claude" / "settings.json"
_PLUGIN_HOOKS = _REPO / "adapters" / "claude-code" / "plugin" / "hooks" / "hooks.json"
_GENERATE = _REPO / "scripts" / "generate.sh"
_SETUP = _REPO / "adapters" / "claude-code" / "setup.sh"

SHA_A = "a" * 40
SHA_B = "b" * 40
DIG_1 = "1" * 64
DIG_2 = "2" * 64
FIXTURE_SESSION = "sess-tiny-001"


def _line(session_id: str, recorded_at: str, **facts) -> str:
    obj = {"session_id": session_id, "recorded_at": recorded_at, "cwd": "/p",
           "cct_version": None, "cct_sha": None, "instructions_digest": None, "providers_digest": None}
    obj.update(facts)
    return json.dumps(obj)


def _ledger(*lines: str) -> str:
    path = Path(tempfile.mkdtemp(prefix="cct-sa-ledger-")) / "harness-stamps.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class TestLedgerReader(unittest.TestCase):
    def test_missing_file_is_an_empty_ledger(self) -> None:
        self.assertEqual(hs.read_ledger("/nonexistent/harness-stamps.jsonl"), {})
        self.assertEqual(hs.read_ledger(""), {})

    def test_earliest_line_wins_and_identical_lines_are_not_mixed(self) -> None:
        path = _ledger(
            _line("s1", "2026-01-01T10:00:00Z", cct_version="1.1.0", cct_sha=SHA_A, instructions_digest=DIG_1),
            _line("s1", "2026-01-01T12:00:00Z", cct_version="1.1.0", cct_sha=SHA_A, instructions_digest=DIG_1),
        )
        stamp = hs.read_ledger(path)["s1"]
        self.assertEqual((stamp.cct_version, stamp.cct_sha, stamp.instructions_digest, stamp.mixed),
                         ("1.1.0", SHA_A, DIG_1, False))

    def test_a_later_differing_line_marks_mixed_and_keeps_the_earliest(self) -> None:
        # Written out of order: the earlier recorded_at is the second line.
        path = _ledger(
            _line("s1", "2026-01-02T00:00:00Z", cct_sha=SHA_B, instructions_digest=DIG_2),
            _line("s1", "2026-01-01T00:00:00Z", cct_sha=SHA_A, instructions_digest=DIG_1),
        )
        stamp = hs.read_ledger(path)["s1"]
        self.assertEqual((stamp.cct_sha, stamp.instructions_digest, stamp.mixed), (SHA_A, DIG_1, True))

    def test_malformed_and_unrelated_lines_are_skipped(self) -> None:
        path = _ledger(
            "not json",
            json.dumps(["a", "list"]),
            _line("", "x"),                                   # no session id
            _line("bad-sha", "x", cct_sha="abc"),             # not 40 hex
            _line("bad-digest", "x", instructions_digest="Z" * 64),
            _line("long", "2026-01-01T00:00:00Z", cct_version="v" * 41),
            _line("bad-time", "yesterday", cct_version="1"),   # cannot be ordered
            _line("ok", "2026-01-01T00:00:00Z", providers_digest=DIG_1),
        )
        with self.assertLogs(hs._log, level="WARNING") as logs:
            stamps = hs.read_ledger(path)
        self.assertEqual(set(stamps), {"ok"})
        self.assertEqual(stamps["ok"].providers_digest, DIG_1)
        self.assertIn("7 malformed line(s)", logs.output[0])

    def test_a_non_iso_timestamp_cannot_win_as_earliest(self) -> None:
        # A hand-edited line whose recorded_at sorts before every real one
        # ("!" < "2") is malformed, not earliest.
        path = _ledger(
            _line("s1", "2026-01-01T00:00:00Z", cct_sha=SHA_A),
            _line("s1", "!", cct_sha=SHA_B),
        )
        with self.assertLogs(hs._log, level="WARNING"):
            stamp = hs.read_ledger(path)["s1"]
        self.assertEqual((stamp.cct_sha, stamp.mixed), (SHA_A, False))

    def test_the_ledger_is_read_once_until_it_changes(self) -> None:
        path = _ledger(_line("s1", "2026-01-01T00:00:00Z", cct_version="1"))
        first = hs.read_ledger(path)
        self.assertIs(hs.read_ledger(path), first)
        # An append within the same second is seen: the size changed.
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(_line("s2", "2026-01-01T00:00:00Z") + "\n")
        self.assertIn("s2", hs.read_ledger(path))


class TestHookInvocation(unittest.TestCase):
    """The hook itself, run as Claude Code would run it, against a temp HOME."""

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="cct-sa-hookhome-"))
        (self.home / ".claude" / "rules").mkdir(parents=True)
        (self.home / ".claude" / "skills" / "one").mkdir(parents=True)
        (self.home / ".claude" / "rules" / "safety.md").write_text("rule\n")
        (self.home / ".claude" / "skills" / "one" / "SKILL.md").write_text("skill\n")
        self.ledger = self.home / ".cct" / "harness-stamps.jsonl"

    def _run(self, payload: dict, profile: str = "/nonexistent/providers.toml") -> list[dict]:
        env = dict(os.environ, HOME=str(self.home), CCT_PROVIDER_PROFILE=profile)
        env.pop("CCT_HARNESS_STAMPS", None)
        env.pop("CLAUDE_CONFIG_DIR", None)
        proc = subprocess.run(
            ["bash", str(_HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "", "a hook must not speak to the model")
        if not self.ledger.exists():
            return []
        return [json.loads(l) for l in self.ledger.read_text().splitlines() if l.strip()]

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_a_line_with_nulls_when_harness_json_and_profile_are_absent(self) -> None:
        rows = self._run({"session_id": "abc", "cwd": "/p"})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["session_id"], row["cwd"]), ("abc", "/p"))
        self.assertIsNone(row["cct_version"])
        self.assertIsNone(row["cct_sha"])
        self.assertIsNone(row["providers_digest"])
        self.assertRegex(row["instructions_digest"], r"^[0-9a-f]{64}$")
        self.assertRegex(row["recorded_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_a_full_stamp_appends_and_the_digest_follows_the_files(self) -> None:
        (self.home / ".cct").mkdir()
        (self.home / ".cct" / "harness.json").write_text(
            json.dumps({"cct_version": "1.1.0", "cct_sha": SHA_A, "installed_at": "x"})
        )
        profile = self.home / "providers.toml"
        profile.write_text("[providers.x]\n")
        first = self._run({"session_id": "abc"}, str(profile))[-1]
        self.assertEqual((first["cct_version"], first["cct_sha"]), ("1.1.0", SHA_A))
        self.assertRegex(first["providers_digest"], r"^[0-9a-f]{64}$")
        (self.home / ".claude" / "rules" / "safety.md").write_text("rule, edited\n")
        rows = self._run({"session_id": "abc"}, str(profile))
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["instructions_digest"], rows[1]["instructions_digest"])
        self.assertEqual(rows[0]["providers_digest"], rows[1]["providers_digest"])
        # And the reader sees exactly that: earliest kept, mixed.
        stamp = hs.read_ledger(str(self.ledger))["abc"]
        self.assertEqual((stamp.instructions_digest, stamp.mixed), (rows[0]["instructions_digest"], True))

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_no_session_id_writes_nothing(self) -> None:
        self.assertEqual(self._run({}), [])
        self.assertEqual(self._run({"cwd": "/p"}), [])


HOOK_COMMAND = "~/.claude/hooks/harness-stamp.sh"


def _setup_functions() -> str:
    """The pieces of setup.sh a settings merge runs: HOOKS_CONFIG (the
    fresh-install file) and ensure_hook_command (the merge into an
    existing file), extracted verbatim so the test runs the real code."""
    text = _SETUP.read_text()
    out = []
    for start, end in (("HOOKS_CONFIG='{", "}'"), ("ensure_hook_command() {", "}")):
        i = text.index(start)
        j = text.index("\n" + end + "\n", i) + len(end) + 2
        out.append(text[i:j])
    return "\n".join(out)


def _count_session_start(settings: dict) -> int:
    return sum(
        1 for group in settings.get("hooks", {}).get("SessionStart", [])
        for h in group.get("hooks", []) if h.get("command") == HOOK_COMMAND
    )


class TestInstallSurface(unittest.TestCase):
    def test_registered_for_setup_and_excluded_from_the_plugin(self) -> None:
        settings = json.loads(_SETTINGS.read_text())
        self.assertEqual(_count_session_start(settings), 1, "the repo's settings.json")
        self.assertEqual(_SETUP.read_text().count("harness-stamp.sh \\"), 2, "both hook copy lists in setup.sh")
        self.assertIn("write_harness_json", _SETUP.read_text())
        # A plugin-only session loads its instructions from CLAUDE_PLUGIN_ROOT:
        # the hook would hash the wrong tree, so it is not shipped there.
        self.assertNotIn("harness-stamp", _PLUGIN_HOOKS.read_text())
        plugin_hooks = next(l for l in _GENERATE.read_text().splitlines() if l.startswith("CC_PLUGIN_HOOKS="))
        self.assertNotIn("harness-stamp", plugin_hooks)
        self.assertTrue(os.access(_HOOK, os.X_OK))

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_setup_writes_the_hook_into_fresh_and_existing_settings_exactly_once(self) -> None:
        """The install path Claude Code actually reads: setup.sh's own
        HOOKS_CONFIG for a fresh ~/.claude/settings.json, and
        ensure_hook_command for an existing one — run twice, so a second
        --sync does not add it again. The repo's settings.json is not
        what setup.sh installs."""
        home = Path(tempfile.mkdtemp(prefix="cct-sa-setuphome-"))
        fresh = home / "fresh.json"
        existing = home / "existing.json"
        existing.write_text(json.dumps({
            "permissions": {"allow": ["Read"]},
            "hooks": {"SessionStart": [{"matcher": "", "hooks": [
                {"type": "command", "command": "~/.claude/hooks/reinject-context.sh", "timeout": 10000}]}]},
        }))
        script = _setup_functions() + f"""
echo "$HOOKS_CONFIG" > "{fresh}"
ensure_hook_command "{existing}" "SessionStart" "" "{HOOK_COMMAND}" 10000 && echo added-1
ensure_hook_command "{existing}" "SessionStart" "" "{HOOK_COMMAND}" 10000 && echo added-2 || echo present-2
"""
        proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=dict(os.environ, HOME=str(home)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.split(), ["added-1", "present-2"])
        self.assertEqual(_count_session_start(json.loads(fresh.read_text())), 1, "fresh install")
        merged = json.loads(existing.read_text())
        self.assertEqual(_count_session_start(merged), 1, "existing settings, after two merges")
        self.assertEqual(merged["permissions"], {"allow": ["Read"]}, "the merge keeps what was there")
        self.assertEqual(len(merged["hooks"]["SessionStart"]), 1, "added to the existing matcher group, not a new one")


class TestAdapterJoin(RegistryResetTestCase):
    def _load(self, ledger: str | None):
        adapter = ClaudeCodeAdapter(harness_stamps_path=ledger if ledger is not None else "")
        refs = adapter.discover(CLAUDE_CODE_ROOT)
        return adapter.load(refs[0])

    def test_cli_version_alone_is_a_stamp(self) -> None:
        h = self._load(None).harness
        self.assertIsNotNone(h)
        self.assertEqual((h.cli_version, h.cct_sha, h.mixed), ("2.1.0", None, False))

    def test_the_ledger_line_joins_by_session_id(self) -> None:
        ledger = _ledger(
            _line("unrelated", "2026-01-01T00:00:00Z", cct_sha=SHA_B),
            _line(FIXTURE_SESSION, "2026-01-01T00:00:00Z", cct_version="1.1.0", cct_sha=SHA_A, instructions_digest=DIG_1),
        )
        h = self._load(ledger).harness
        self.assertEqual((h.cli_version, h.cct_version, h.cct_sha, h.instructions_digest, h.mixed),
                         ("2.1.0", "1.1.0", SHA_A, DIG_1, False))

    def test_a_second_cli_version_in_the_transcript_marks_mixed(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-cli-")) / "project-hash"
        tmp.mkdir(parents=True)
        src = CLAUDE_CODE_ROOT / "project-hash" / "tiny-session.jsonl"
        lines = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
        lines[-1]["version"] = "2.2.0"     # the last assistant record ran under a newer CLI
        (tmp / "s.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        adapter = ClaudeCodeAdapter(harness_stamps_path="")
        h = adapter.load(adapter.discover(tmp.parent)[0]).harness
        self.assertEqual((h.cli_version, h.mixed), ("2.1.0", True))

    def test_no_version_and_no_ledger_is_unstamped(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-nover-")) / "project-hash"
        tmp.mkdir(parents=True)
        src = CLAUDE_CODE_ROOT / "project-hash" / "tiny-session.jsonl"
        lines = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
        for l in lines:
            l.pop("version", None)
        (tmp / "s.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        adapter = ClaudeCodeAdapter(harness_stamps_path="")
        self.assertIsNone(adapter.load(adapter.discover(tmp.parent)[0]).harness)


class TestStore(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        from session_analytics.adapters import claude_code
        claude_code.register()
        self.dsn = self.sqlite_dsn()

    def _ingest(self, ledger: str) -> None:
        from unittest import mock
        with mock.patch.dict("os.environ", {"CCT_HARNESS_STAMPS": ledger}):
            ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)

    def test_columns_written_and_kept_across_reingest(self) -> None:
        ledger = _ledger(_line(FIXTURE_SESSION, "2026-01-01T00:00:00Z", cct_version="1.1.0", cct_sha=SHA_A,
                               instructions_digest=DIG_1, providers_digest=DIG_2))
        self._ingest(ledger)
        db = Database.connect(self.dsn)
        cols = ", ".join(C.HARNESS_FACTS + (C.HARNESS_KEY_MIXED,))
        row = db.query_one(f"SELECT {cols} FROM copilot_session")
        self.assertEqual(tuple(row), ("2.1.0", "1.1.0", SHA_A, DIG_1, DIG_2, 0))
        sid = db.query_one("SELECT id FROM copilot_session")[0]
        detail = tools.get_session_details(db, sid)
        self.assertEqual((detail["cct_sha"], detail["harness_mixed"]), (SHA_A, False))
        listed = tools.search_sessions(db, limit=5)[0]
        self.assertEqual((listed["instructions_digest"], listed["harness_mixed"]), (DIG_1, False))
        db.close()
        # A line that arrives later (a resume under a new harness) is
        # picked up by the next ingest, and re-ingest keeps the id.
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(_line(FIXTURE_SESSION, "2026-01-02T00:00:00Z", cct_version="1.1.0", cct_sha=SHA_B,
                           instructions_digest=DIG_1, providers_digest=DIG_2) + "\n")
        self._ingest(ledger)
        db = Database.connect(self.dsn)
        self.assertEqual(db.query("SELECT id, cct_sha, harness_mixed FROM copilot_session"), [(sid, SHA_A, 1)])
        db.close()

    def test_a_rotated_ledger_holding_only_a_later_line_cannot_relabel(self) -> None:
        """Ingest under A; the ledger is replaced by one that holds only
        B for the session; re-ingest keeps A and marks the session mixed
        — the same rule the reader applies between lines, applied
        between the store and the ledger."""
        self._ingest(_ledger(_line(FIXTURE_SESSION, "2026-01-01T00:00:00Z", cct_sha=SHA_A,
                                   instructions_digest=DIG_1)))
        self._ingest(_ledger(_line(FIXTURE_SESSION, "2026-01-02T00:00:00Z", cct_sha=SHA_B,
                                   instructions_digest=DIG_2, providers_digest=DIG_2)))
        db = Database.connect(self.dsn)
        row = db.query_one("SELECT cct_sha, instructions_digest, providers_digest, harness_mixed FROM copilot_session")
        # A stays; the fact A never had (providers) is filled; mixed is set.
        self.assertEqual(tuple(row), (SHA_A, DIG_1, DIG_2, 1))
        db.close()
        # A second identical B-only re-ingest changes nothing.
        self._ingest(_ledger(_line(FIXTURE_SESSION, "2026-01-02T00:00:00Z", cct_sha=SHA_B,
                                   instructions_digest=DIG_2, providers_digest=DIG_2)))
        db = Database.connect(self.dsn)
        self.assertEqual(tuple(db.query_one("SELECT cct_sha, instructions_digest, harness_mixed FROM copilot_session")),
                         (SHA_A, DIG_1, 1))
        db.close()

    def test_a_stored_stamp_is_sticky_when_the_ledger_line_goes_away(self) -> None:
        ledger = _ledger(_line(FIXTURE_SESSION, "2026-01-01T00:00:00Z", cct_sha=SHA_A,
                               instructions_digest=DIG_1))
        self._ingest(ledger)
        # The ledger was pruned (or CCT_HARNESS_STAMPS points elsewhere):
        # the next ingest finds no line, and the stamp stays.
        self._ingest("/nonexistent/ledger.jsonl")
        db = Database.connect(self.dsn)
        self.assertEqual(db.query("SELECT cct_sha, instructions_digest, harness_mixed FROM copilot_session"),
                         [(SHA_A, DIG_1, 0)])
        db.close()
        # Mixed, once true, stays true even if the differing line is gone.
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(_line(FIXTURE_SESSION, "2026-01-02T00:00:00Z", cct_sha=SHA_B, instructions_digest=DIG_1) + "\n")
        self._ingest(ledger)
        self._ingest("/nonexistent/ledger.jsonl")
        db = Database.connect(self.dsn)
        self.assertEqual(db.query("SELECT cct_sha, harness_mixed FROM copilot_session"), [(SHA_A, 1)])
        db.close()

    def test_unstamped_when_no_ledger(self) -> None:
        self._ingest("/nonexistent/ledger.jsonl")
        db = Database.connect(self.dsn)
        row = db.query_one("SELECT cli_version, cct_sha, harness_mixed FROM copilot_session")
        # The fixture carries a CLI version, so that alone is stamped, unmixed.
        self.assertEqual(tuple(row), ("2.1.0", None, 0))
        db.close()


class TestLedgerPathControl(unittest.TestCase):
    def test_the_environment_is_the_one_control(self) -> None:
        """CCT_HARNESS_STAMPS moves the reader (here) and the hook (it
        reads the same name); there is no JSON key, which the hook could
        not see."""
        from unittest import mock
        from session_analytics.config import ENV_HARNESS_STAMPS, load_config
        with mock.patch.dict("os.environ", {ENV_HARNESS_STAMPS: "/tmp/elsewhere.jsonl"}):
            self.assertEqual(load_config().harness_stamps_path, "/tmp/elsewhere.jsonl")
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop(ENV_HARNESS_STAMPS, None)
            self.assertTrue(load_config().harness_stamps_path.endswith("/.cct/harness-stamps.jsonl"))
        self.assertNotIn("harness_stamps_path", (_REPO / "scripts/session_analytics/config_data/defaults.json").read_text())
        self.assertIn('LEDGER="${CCT_HARNESS_STAMPS:-', _HOOK.read_text())


class TestSchemaRefusal(unittest.TestCase):
    def test_a_schema_9_store_is_refused_with_the_remedy(self) -> None:
        import sqlite3
        path = Path(tempfile.mkdtemp(prefix="cct-sa-v9-")) / "v9.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE schema_version (version INTEGER, applied_at TEXT);"
            "INSERT INTO schema_version VALUES (9, 'x');"
            "CREATE TABLE copilot_tool_result (id INTEGER PRIMARY KEY, tool_call_id INTEGER,"
            " status TEXT, is_error INTEGER, output_length INTEGER, error_message TEXT, completed_at TEXT);"
            "CREATE TABLE copilot_session (id INTEGER PRIMARY KEY, copilot TEXT, session_id TEXT);"
        )
        conn.commit()
        conn.close()
        store = Database.connect(f"sqlite:///{path}")
        with self.assertRaises(dbmod.SchemaMismatch) as ctx:
            dbmod.apply_ddl(store)
        self.assertIn("schema version 9", str(ctx.exception))
        self.assertIn("copilot_session.cli_version", str(ctx.exception))
        self.assertEqual(store.query("SELECT version FROM schema_version"), [(9,)])
        store.close()


if __name__ == "__main__":
    unittest.main()
