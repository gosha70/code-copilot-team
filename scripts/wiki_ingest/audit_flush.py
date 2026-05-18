# wiki_ingest.audit_flush — the ONLY git-committing module in the wiki pipeline.
#
# Implements `detect_pending(repo_root) -> PendingState` and
# `flush(repo_root, dry_run) -> int` for the `wiki audit-flush` verb.
#
# `wiki audit-flush` is the sole pipeline command that runs `git commit`,
# by design and in one place. `ingest`/`promote`/`lint` remain git-free.
# Never auto-invoked, hooked, or scheduled — only user-driven.
#
# See specs/wiki-audit-flush/spec.md for the full contract.

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .audit_lint import INGEST_LOG_MARKER, _validate_ingest_log
from .errors import AuditFlushError

_LOG_REL = "knowledge/wiki/.audit/ingest-log.md"

# Number of fixed preamble lines: "<!-- ingest-log schema v1 -->" + blank.
_PREAMBLE_LINES = 2


@dataclass(frozen=True)
class PendingState:
    """Summary of the uncommitted tail of ingest-log.md."""

    path: Path           # repo-relative POSIX path to ingest-log.md (as a Path)
    pending: int         # N >= 0: data lines in working but not in committed blob
    blob_sha: str | None # git hash-object of the working file (None if absent)
    diverged: bool       # True when committed bytes are NOT a prefix of working bytes
    malformed: bool      # True when working log is torn or fails audit_lint v1


def _run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[bytes]:
    """Run a subprocess, capturing stdout/stderr as bytes."""
    return subprocess.run(argv, capture_output=True, **kw)  # type: ignore[call-overload]


def _count_data_lines(raw: bytes) -> int:
    """Count NDJSON data lines after the 2-line preamble in raw bytes.

    Lines are split on b'\\n'. The preamble is the first two logical lines
    (the marker line + the empty line). Data lines are non-empty lines
    after the preamble.
    """
    lines = raw.split(b"\n")
    # Drop the preamble lines.
    data_lines = lines[_PREAMBLE_LINES:]
    return sum(1 for ln in data_lines if ln.strip())


def detect_pending(repo_root: Path) -> PendingState:
    """Return the pending-state for knowledge/wiki/.audit/ingest-log.md.

    Reads the committed blob from HEAD via `git show` and the working file
    from disk. Never mutates git or the filesystem.

    Parameters
    ----------
    repo_root : Path
        Absolute path to the git work tree root.

    Returns
    -------
    PendingState
        (path, pending, blob_sha, diverged, malformed)

    Raises
    ------
    AuditFlushError
        When the directory is not a git work tree (``git show`` fails with
        a "not a git repository" error) — re-raised at the CLI layer.
        This function propagates the subprocess result; callers must decide
        whether a non-zero `git show` exit means "absent" or "not a repo".
    """
    log_path = repo_root / _LOG_REL

    # ── Committed blob ────────────────────────────────────────────────────
    result = _run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{_LOG_REL}"],
    )
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        # Distinguish "not a git repo" from "file absent at HEAD".
        if "not a git repository" in stderr_text or "not a git repo" in stderr_text:
            raise AuditFlushError(
                f"not a git work tree: {repo_root}\n  {stderr_text.strip()}"
            )
        # File absent at HEAD (untracked or brand-new): treat as empty committed.
        committed_bytes = b""
    else:
        committed_bytes = result.stdout

    # ── Working file ──────────────────────────────────────────────────────
    if not log_path.exists():
        # Nothing on disk either → trivially clean, nothing pending.
        return PendingState(
            path=Path(_LOG_REL),
            pending=0,
            blob_sha=None,
            diverged=False,
            malformed=False,
        )

    working_bytes = log_path.read_bytes()

    # ── blob_sha via git hash-object ──────────────────────────────────────
    sha_result = _run(
        ["git", "-C", str(repo_root), "hash-object", str(log_path)],
    )
    blob_sha: str | None = sha_result.stdout.decode("ascii").strip() if sha_result.returncode == 0 else None

    # ── Divergence check ──────────────────────────────────────────────────
    # The append-only contract: committed bytes must be a byte-exact prefix
    # of working bytes.
    diverged = not working_bytes.startswith(committed_bytes)

    # ── Malformed check ───────────────────────────────────────────────────
    # (1) Working file must be non-empty and newline-terminated.
    # (2) audit_lint v1 validation must report zero errors.
    malformed = False
    if working_bytes:
        if working_bytes[-1:] != b"\n":
            malformed = True
        else:
            lint_errors = _validate_ingest_log(log_path)
            if lint_errors:
                malformed = True

    # ── Pending count ─────────────────────────────────────────────────────
    working_data = _count_data_lines(working_bytes)
    committed_data = _count_data_lines(committed_bytes) if committed_bytes else 0
    pending = max(0, working_data - committed_data)

    return PendingState(
        path=Path(_LOG_REL),
        pending=pending,
        blob_sha=blob_sha,
        diverged=diverged,
        malformed=malformed,
    )


def flush(repo_root: Path, dry_run: bool) -> int:
    """Commit any pending ingest-log lines, or report them in dry-run mode.

    Parameters
    ----------
    repo_root : Path
        Absolute path to the git work tree root.
    dry_run : bool
        When True, print the pending count + blob SHA and exit 0 without
        committing.

    Returns
    -------
    int
        Process exit code: 0 for success/no-op, 11 for AuditFlushError.

    Raises
    ------
    AuditFlushError
        For non-git-repo, divergence, malformed log, or a failed git commit.
    """
    state = detect_pending(repo_root)

    # ── Fail-closed gates (apply before dry-run report) ───────────────────
    if state.diverged:
        raise AuditFlushError(
            f"audit-flush: append-only invariant violated — committed "
            f"ingest-log.md is not a byte prefix of the working copy.\n"
            f"  Repair the file before flushing (do not truncate; let the "
            f"next correct `wiki ingest` append fix the tail)."
        )
    if state.malformed:
        raise AuditFlushError(
            f"audit-flush: working ingest-log.md is malformed (torn final "
            f"line, not newline-terminated, or contains a record that fails "
            f"audit_lint v1 validation).\n"
            f"  Run `./scripts/wiki lint --strict` for details. The file is "
            f"left untouched; the next correct `wiki ingest` append will "
            f"repair the tail."
        )

    # ── No-op ─────────────────────────────────────────────────────────────
    if state.pending == 0 or state.blob_sha is None:
        print("nothing to flush")
        return 0

    # ── Dry-run report ────────────────────────────────────────────────────
    if dry_run:
        print(f"{state.pending} pending ingest-log line(s); blob {state.blob_sha}")
        return 0

    # ── Real commit ───────────────────────────────────────────────────────
    # Message BEFORE `--`; pathspec AFTER. `-m` after `--` is parsed as a
    # pathspec by git and fails with "pathspec '-m' did not match".
    if state.pending == 1:
        msg = "audit: flush 1 pending ingest-log line"
    else:
        msg = f"audit: flush {state.pending} pending ingest-log lines"

    # Stage exactly this one file. `git add -- <path>` (not `git add -A`)
    # is required for the initial flush when the file is untracked; for
    # subsequent flushes the file is already tracked so this is a no-op.
    # The pathspec on `git commit` then restricts the commit to only this
    # file even if other paths are staged.
    add_result = _run(
        [
            "git", "-C", str(repo_root),
            "add", "--",
            _LOG_REL,
        ],
    )
    if add_result.returncode != 0:
        stderr_text = add_result.stderr.decode("utf-8", errors="replace")
        raise AuditFlushError(
            f"audit-flush: git add failed (exit {add_result.returncode}):\n"
            f"  {stderr_text.strip()}"
        )

    commit_result = _run(
        [
            "git", "-C", str(repo_root),
            "commit",
            "-m", msg,
            "--",
            _LOG_REL,
        ],
    )
    if commit_result.returncode != 0:
        stderr_text = commit_result.stderr.decode("utf-8", errors="replace")
        raise AuditFlushError(
            f"audit-flush: git commit failed (exit {commit_result.returncode}):\n"
            f"  {stderr_text.strip()}"
        )

    return 0
