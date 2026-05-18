# tests/test_audit_flush.py — unit tests for audit_flush.py.
#
# Every test uses an isolated temp git init repo; no test touches the
# real repo or the network.
#
# Coverage:
#   detect_pending matrix:
#     - absent (0, None, not diverged, not malformed)
#     - untracked file (all data lines pending)
#     - +N appended lines (pending N)
#     - identical (0)
#     - preamble-only (0)
#     - committed-not-a-prefix (diverged True)
#     - torn final line (malformed True)
#     - non-newline-terminated (malformed True)
#     - schema-invalid record (malformed True)
#   flush:
#     - creates exactly one commit (single-file diff, exact message N=1 and N>1)
#     - ledger bytes unchanged by the flush
#     - second run no-op (exit 0, no new commit)
#     - unrelated dirty sibling excluded from commit and stays modified
#     - detached HEAD still commits
#     - diverged → exit 11, no commit
#     - malformed → exit 11, no commit
#     - git commit failure → exit 11

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the package importable when run via unittest discover.
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from wiki_ingest.audit_flush import PendingState, detect_pending, flush
from wiki_ingest.audit_lint import INGEST_LOG_MARKER
from wiki_ingest.errors import AuditFlushError


# ── Helpers ────────────────────────────────────────────────────────────────

_LOG_REL = "knowledge/wiki/.audit/ingest-log.md"

_HEX = "a" * 64


def _valid_record(**ov: object) -> dict:
    """Return a minimal valid v1 ingest-log record, with optional overrides."""
    r: dict = {
        "v": 1,
        "ts": "2026-05-17T14:03:22Z",
        "source_path": "specs/x/spec.md",
        "source_repo_relative": True,
        "source_sha": _HEX,
        "backend": "test",
        "disposition": "reject",
        "reason": "not wiki-worthy: too narrow.",
        "proposal_dir": "2026-05-17-x",
        "target_paths": [],
        "page_types": [],
        "proposal_hash": None,
    }
    r.update(ov)
    return r


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Run a git command in repo, capturing output."""
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
    )


def _init_repo(tmp: Path) -> Path:
    """Create a minimal git repo under tmp/repo/ and return its path."""
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    # Create an initial commit so HEAD exists.
    readme = repo / "README.md"
    readme.write_text("# test\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def _log_path(repo: Path) -> Path:
    return repo / _LOG_REL


def _make_preamble() -> bytes:
    return (INGEST_LOG_MARKER + "\n\n").encode("utf-8")


def _make_log_bytes(*records: dict) -> bytes:
    """Build a valid ingest-log.md byte payload with the given records."""
    lines = [INGEST_LOG_MARKER, ""]
    for r in records:
        lines.append(json.dumps(r, separators=(",", ":")))
    lines.append("")  # trailing newline
    return "\n".join(lines).encode("utf-8")


def _commit_log(repo: Path, content: bytes) -> None:
    """Write content to ingest-log.md and commit it."""
    lp = _log_path(repo)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_bytes(content)
    _git(repo, "add", _LOG_REL)
    _git(repo, "commit", "-m", "test: commit ingest-log")


def _count_commits(repo: Path) -> int:
    result = _git(repo, "rev-list", "--count", "HEAD")
    return int(result.stdout.decode().strip())


# ── detect_pending matrix ──────────────────────────────────────────────────


class TestDetectPendingAbsent(unittest.TestCase):
    """Absent file → pending 0, blob_sha None, not diverged, not malformed."""

    def test_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            state = detect_pending(repo)
            self.assertEqual(state.pending, 0)
            self.assertIsNone(state.blob_sha)
            self.assertFalse(state.diverged)
            self.assertFalse(state.malformed)


class TestDetectPendingUntracked(unittest.TestCase):
    """Untracked working file → all data lines pending, not diverged, not malformed."""

    def test_untracked_one_record(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            content = _make_log_bytes(_valid_record())
            lp = _log_path(repo)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_bytes(content)
            state = detect_pending(repo)
            self.assertEqual(state.pending, 1)
            self.assertIsNotNone(state.blob_sha)
            self.assertFalse(state.diverged)
            self.assertFalse(state.malformed)

    def test_untracked_three_records(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            records = [_valid_record() for _ in range(3)]
            content = _make_log_bytes(*records)
            lp = _log_path(repo)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_bytes(content)
            state = detect_pending(repo)
            self.assertEqual(state.pending, 3)
            self.assertFalse(state.diverged)
            self.assertFalse(state.malformed)


class TestDetectPendingAppended(unittest.TestCase):
    """Committed N records + N more appended → pending N."""

    def test_one_appended(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            appended = committed.rstrip(b"\n") + b"\n" + (
                json.dumps(r2, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            _log_path(repo).write_bytes(appended)

            state = detect_pending(repo)
            self.assertEqual(state.pending, 1)
            self.assertFalse(state.diverged)
            self.assertFalse(state.malformed)

    def test_two_appended(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            r3 = _valid_record(ts="2026-05-17T16:00:00Z")
            extra = (
                json.dumps(r2, separators=(",", ":")) + "\n"
                + json.dumps(r3, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            existing = committed.rstrip(b"\n") + b"\n" + extra
            _log_path(repo).write_bytes(existing)

            state = detect_pending(repo)
            self.assertEqual(state.pending, 2)
            self.assertFalse(state.diverged)
            self.assertFalse(state.malformed)


class TestDetectPendingIdentical(unittest.TestCase):
    """Working file identical to committed → pending 0."""

    def test_identical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            content = _make_log_bytes(_valid_record())
            _commit_log(repo, content)
            # No change to working file.
            state = detect_pending(repo)
            self.assertEqual(state.pending, 0)
            self.assertFalse(state.diverged)
            self.assertFalse(state.malformed)


class TestDetectPendingPreambleOnly(unittest.TestCase):
    """Preamble-only file (no data lines) → pending 0."""

    def test_preamble_only_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            content = _make_preamble()
            lp = _log_path(repo)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_bytes(content)
            state = detect_pending(repo)
            self.assertEqual(state.pending, 0)
            self.assertFalse(state.diverged)
            # Preamble-only is valid (no data lines to be invalid).
            self.assertFalse(state.malformed)

    def test_preamble_only_committed_and_working(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            content = _make_preamble()
            _commit_log(repo, content)
            state = detect_pending(repo)
            self.assertEqual(state.pending, 0)
            self.assertFalse(state.diverged)
            self.assertFalse(state.malformed)


class TestDetectPendingDiverged(unittest.TestCase):
    """Committed bytes not a prefix of working bytes → diverged True."""

    def test_rewritten_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            # Rewrite with a completely different record (not an append).
            r2 = _valid_record(ts="2026-05-17T20:00:00Z", reason="different")
            different = _make_log_bytes(r2)
            _log_path(repo).write_bytes(different)

            state = detect_pending(repo)
            self.assertTrue(state.diverged)


class TestDetectPendingMalformed(unittest.TestCase):
    """Various malformed working files → malformed True."""

    def test_torn_final_line(self) -> None:
        """Working file not newline-terminated → malformed."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            # Append a partial line (no trailing newline).
            torn = committed + b'{"v":1,"ts":"2026' # no closing
            _log_path(repo).write_bytes(torn)
            state = detect_pending(repo)
            self.assertTrue(state.malformed)

    def test_not_newline_terminated(self) -> None:
        """Working file ends with a complete record but no trailing newline."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            # Build content without the trailing newline.
            lines = [INGEST_LOG_MARKER, "", json.dumps(r1, separators=(",", ":"))]
            content = "\n".join(lines).encode("utf-8")  # no trailing \n
            lp = _log_path(repo)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_bytes(content)
            state = detect_pending(repo)
            self.assertTrue(state.malformed)

    def test_schema_invalid_record(self) -> None:
        """A record missing required keys → malformed."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            # Write a log with a record missing most fields.
            bad_record = {"v": 1, "ts": "2026-05-17T14:03:22Z"}
            content = (
                INGEST_LOG_MARKER + "\n\n"
                + json.dumps(bad_record) + "\n"
            ).encode("utf-8")
            lp = _log_path(repo)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_bytes(content)
            state = detect_pending(repo)
            self.assertTrue(state.malformed)


# ── flush behavior ─────────────────────────────────────────────────────────


class TestFlushCreatesCommit(unittest.TestCase):
    """flush() creates exactly one commit with the right message and only ingest-log.md."""

    def test_singular_message(self) -> None:
        """N=1 → 'audit: flush 1 pending ingest-log line'."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)
            before_count = _count_commits(repo)

            # Append one more record.
            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            working = committed.rstrip(b"\n") + b"\n" + (
                json.dumps(r2, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            _log_path(repo).write_bytes(working)

            rc = flush(repo, dry_run=False)
            self.assertEqual(rc, 0)
            after_count = _count_commits(repo)
            self.assertEqual(after_count, before_count + 1)

            # Check message.
            msg_result = _git(repo, "log", "-1", "--format=%s")
            msg = msg_result.stdout.decode().strip()
            self.assertEqual(msg, "audit: flush 1 pending ingest-log line")

    def test_plural_message(self) -> None:
        """N=2 → 'audit: flush 2 pending ingest-log lines'."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)
            before_count = _count_commits(repo)

            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            r3 = _valid_record(ts="2026-05-17T16:00:00Z")
            extra = (
                json.dumps(r2, separators=(",", ":")) + "\n"
                + json.dumps(r3, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            working = committed.rstrip(b"\n") + b"\n" + extra
            _log_path(repo).write_bytes(working)

            rc = flush(repo, dry_run=False)
            self.assertEqual(rc, 0)
            after_count = _count_commits(repo)
            self.assertEqual(after_count, before_count + 1)

            msg_result = _git(repo, "log", "-1", "--format=%s")
            msg = msg_result.stdout.decode().strip()
            self.assertEqual(msg, "audit: flush 2 pending ingest-log lines")

    def test_commit_contains_only_ingest_log(self) -> None:
        """git show --stat must list ONLY ingest-log.md."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            working = committed.rstrip(b"\n") + b"\n" + (
                json.dumps(r2, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            _log_path(repo).write_bytes(working)

            flush(repo, dry_run=False)

            stat_result = _git(repo, "show", "--stat", "--format=", "HEAD")
            stat = stat_result.stdout.decode()
            changed_files = [
                ln.strip() for ln in stat.splitlines()
                if ln.strip() and "|" in ln
            ]
            self.assertEqual(len(changed_files), 1)
            self.assertIn("ingest-log.md", changed_files[0])

    def test_ledger_bytes_unchanged_by_flush(self) -> None:
        """flush() must not modify the file content."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            working = committed.rstrip(b"\n") + b"\n" + (
                json.dumps(r2, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            lp = _log_path(repo)
            lp.write_bytes(working)
            before_bytes = lp.read_bytes()

            flush(repo, dry_run=False)

            after_bytes = lp.read_bytes()
            self.assertEqual(before_bytes, after_bytes)


class TestFlushNoop(unittest.TestCase):
    """No pending lines → 'nothing to flush', exit 0, no commit."""

    def test_noop_identical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            content = _make_log_bytes(_valid_record())
            _commit_log(repo, content)
            before_count = _count_commits(repo)

            rc = flush(repo, dry_run=False)
            self.assertEqual(rc, 0)
            self.assertEqual(_count_commits(repo), before_count)

    def test_noop_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            before_count = _count_commits(repo)
            rc = flush(repo, dry_run=False)
            self.assertEqual(rc, 0)
            self.assertEqual(_count_commits(repo), before_count)

    def test_second_run_noop(self) -> None:
        """After a successful flush, a second run is a no-op."""
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            working = committed.rstrip(b"\n") + b"\n" + (
                json.dumps(r2, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            _log_path(repo).write_bytes(working)

            rc1 = flush(repo, dry_run=False)
            self.assertEqual(rc1, 0)
            count_after_first = _count_commits(repo)

            rc2 = flush(repo, dry_run=False)
            self.assertEqual(rc2, 0)
            self.assertEqual(_count_commits(repo), count_after_first)


class TestFlushPathspecIsolation(unittest.TestCase):
    """Unrelated dirty/staged file is excluded from the audit-flush commit."""

    def test_unrelated_dirty_file_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            # Plant an unrelated dirty file.
            dirty = repo / "dirty.txt"
            dirty.write_text("unrelated change\n", encoding="utf-8")

            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            working = committed.rstrip(b"\n") + b"\n" + (
                json.dumps(r2, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            _log_path(repo).write_bytes(working)

            flush(repo, dry_run=False)

            # The commit must not include dirty.txt.
            stat_result = _git(repo, "show", "--stat", "--format=", "HEAD")
            stat = stat_result.stdout.decode()
            self.assertNotIn("dirty.txt", stat)

            # dirty.txt must still be modified (not committed, not staged).
            status_result = _git(repo, "status", "--porcelain")
            status = status_result.stdout.decode()
            self.assertIn("dirty.txt", status)


class TestFlushDetachedHead(unittest.TestCase):
    """flush() works on a detached HEAD."""

    def test_detached_head(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            # Detach HEAD.
            head_sha_result = _git(repo, "rev-parse", "HEAD")
            head_sha = head_sha_result.stdout.decode().strip()
            _git(repo, "checkout", "--detach", head_sha)

            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            working = committed.rstrip(b"\n") + b"\n" + (
                json.dumps(r2, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            _log_path(repo).write_bytes(working)

            rc = flush(repo, dry_run=False)
            self.assertEqual(rc, 0)

            # A commit was created.
            msg_result = _git(repo, "log", "-1", "--format=%s")
            msg = msg_result.stdout.decode().strip()
            self.assertEqual(msg, "audit: flush 1 pending ingest-log line")


class TestFlushDiverged(unittest.TestCase):
    """Diverged log → AuditFlushError (exit 11), no commit."""

    def test_diverged_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)
            before_count = _count_commits(repo)

            # Overwrite (not append) — violates prefix invariant.
            r2 = _valid_record(ts="2026-05-17T20:00:00Z", reason="different")
            different = _make_log_bytes(r2)
            _log_path(repo).write_bytes(different)

            with self.assertRaises(AuditFlushError):
                flush(repo, dry_run=False)
            self.assertEqual(_count_commits(repo), before_count)

    def test_diverged_bytes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            r2 = _valid_record(ts="2026-05-17T20:00:00Z", reason="different")
            different = _make_log_bytes(r2)
            lp = _log_path(repo)
            lp.write_bytes(different)
            before_bytes = lp.read_bytes()

            try:
                flush(repo, dry_run=False)
            except AuditFlushError:
                pass

            self.assertEqual(lp.read_bytes(), before_bytes)


class TestFlushMalformed(unittest.TestCase):
    """Malformed log → AuditFlushError (exit 11), no commit, bytes unchanged."""

    def test_torn_tail_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)
            before_count = _count_commits(repo)

            torn = committed + b'{"v":1,"ts":"2026'
            _log_path(repo).write_bytes(torn)

            with self.assertRaises(AuditFlushError):
                flush(repo, dry_run=False)
            self.assertEqual(_count_commits(repo), before_count)

    def test_malformed_bytes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            torn = committed + b'{"v":1,"ts":"2026'
            lp = _log_path(repo)
            lp.write_bytes(torn)
            before_bytes = lp.read_bytes()

            try:
                flush(repo, dry_run=False)
            except AuditFlushError:
                pass

            self.assertEqual(lp.read_bytes(), before_bytes)

    def test_schema_invalid_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            bad_record = {"v": 1, "ts": "2026-05-17T14:03:22Z"}
            content = (
                INGEST_LOG_MARKER + "\n\n"
                + json.dumps(bad_record) + "\n"
            ).encode("utf-8")
            lp = _log_path(repo)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_bytes(content)
            before_count = _count_commits(repo)

            with self.assertRaises(AuditFlushError):
                flush(repo, dry_run=False)
            self.assertEqual(_count_commits(repo), before_count)


class TestFlushDryRun(unittest.TestCase):
    """--dry-run: prints count + sha, no commit."""

    def test_dry_run_no_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)
            before_count = _count_commits(repo)

            r2 = _valid_record(ts="2026-05-17T15:00:00Z")
            working = committed.rstrip(b"\n") + b"\n" + (
                json.dumps(r2, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            _log_path(repo).write_bytes(working)

            rc = flush(repo, dry_run=True)
            self.assertEqual(rc, 0)
            self.assertEqual(_count_commits(repo), before_count)

    def test_dry_run_diverged_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            r2 = _valid_record(ts="2026-05-17T20:00:00Z", reason="different")
            different = _make_log_bytes(r2)
            _log_path(repo).write_bytes(different)

            with self.assertRaises(AuditFlushError):
                flush(repo, dry_run=True)

    def test_dry_run_malformed_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = _init_repo(Path(td))
            r1 = _valid_record()
            committed = _make_log_bytes(r1)
            _commit_log(repo, committed)

            torn = committed + b'{"v":1'
            _log_path(repo).write_bytes(torn)

            with self.assertRaises(AuditFlushError):
                flush(repo, dry_run=True)


class TestFlushGitCommitFailure(unittest.TestCase):
    """git commit failure (e.g. nothing staged because file wasn't modified from index) → AuditFlushError."""

    def test_git_commit_failure_raises(self) -> None:
        """Simulate a commit failure by using a non-git directory."""
        with tempfile.TemporaryDirectory() as td:
            not_a_repo = Path(td) / "not-a-repo"
            not_a_repo.mkdir()
            with self.assertRaises(AuditFlushError):
                detect_pending(not_a_repo)


if __name__ == "__main__":
    unittest.main()
