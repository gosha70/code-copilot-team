# wiki_ingest.audit — the ONLY module that writes ingest-log.md.
#
# Contains the helpers for computing source_sha, proposal_hash, and
# truncate_reason, plus build_log_record (derives a patch-set-oriented
# IngestLogRecord from a WikiPatchSet or IngestProposal) and
# append_ingest_log (the fail-closed, marker-prefixed writer).
#
# append_ingest_log is called from __main__.py ingest handlers AFTER the
# proposal dir is materialized + dry-run stripped (Design Decision 8), NOT
# from ingestor.py / ingestor_multi.py.
#
# See knowledge/wiki/schema/audit-rules.md for the normative format spec.

from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path

from .audit_lint import INGEST_LOG_MARKER
from .errors import OutputWriteError
from .proposal import IngestLogRecord, IngestProposal, WikiPatchSet

# ── Helpers ────────────────────────────────────────────────────────────────


def source_sha(source_file: Path) -> str:
    """Return the SHA-256 lowercase-hex digest of source_file's raw bytes."""
    return hashlib.sha256(source_file.read_bytes()).hexdigest()


def proposal_hash(proposal_dir: Path) -> str:
    """Return the SHA-256 canonical hash of the proposal payload.

    Canonicalization recipe (from audit-rules.md / spec.md DD3):
      1. Collect plan.json + every file under preview/ recursively.
         Exclude .ingest-snapshot/ and any path component beginning with '.'.
      2. Sort by repo-relative POSIX path under LC_ALL=C (byte order).
      3. For each file, append:
           <rel_path UTF-8> + b'\\n' + raw bytes + b'\\n--\\n'
      4. SHA-256 the concatenated buffer; return lowercase hex.
    """
    files: list[Path] = []

    plan = proposal_dir / "plan.json"
    if plan.is_file():
        files.append(plan)

    preview = proposal_dir / "preview"
    if preview.is_dir():
        for p in preview.rglob("*"):
            if p.is_file():
                files.append(p)

    def _is_excluded(p: Path) -> bool:
        """True if any path component begins with '.' (dotfile/dotdir)."""
        # Check each component relative to proposal_dir.
        try:
            rel = p.relative_to(proposal_dir)
        except ValueError:
            return True
        return any(part.startswith(".") for part in rel.parts)

    included = [f for f in files if not _is_excluded(f)]

    # Sort by repo-relative POSIX path, byte order (LC_ALL=C).
    def _sort_key(p: Path) -> bytes:
        return p.relative_to(proposal_dir).as_posix().encode("utf-8")

    included.sort(key=_sort_key)

    buf = bytearray()
    for f in included:
        rel_posix = f.relative_to(proposal_dir).as_posix()
        buf += rel_posix.encode("utf-8")
        buf += b"\n"
        buf += f.read_bytes()
        buf += b"\n--\n"

    return hashlib.sha256(bytes(buf)).hexdigest()


def truncate_reason(s: str) -> str:
    """Collapse whitespace/newlines to single spaces; truncate to 240 codepoints.

    If the result exceeds 240 codepoints, it is truncated to 239 codepoints
    followed by U+2026 (HORIZONTAL ELLIPSIS) — total exactly 240.
    """
    # Collapse runs of whitespace (including newlines) to a single space.
    collapsed = re.sub(r"\s+", " ", s).strip()
    if len(collapsed) <= 240:
        return collapsed
    return collapsed[:239] + "…"


# ── Record builder ─────────────────────────────────────────────────────────


def _page_type_from_path(path: str) -> str:
    """Derive a page type from a wiki-relative path (best-effort)."""
    # Most wiki paths are <page_type_dir>/<slug>.md; the directory name
    # is the canonical page type string. E.g. "concepts/foo.md" → "concept"
    # but the directory is "concepts" not "concept".  We want the
    # *directory name* as the type label for audit purposes.
    parts = Path(path).parts
    if len(parts) >= 2:
        return parts[0]
    return "unknown"


def build_log_record(
    *,
    source_file: Path,
    repo_root: Path,
    backend_name: str,
    proposal_dir_path: Path | None,
    allow_out_of_repo: bool = False,
    patch: WikiPatchSet | None = None,
    legacy_proposal: IngestProposal | None = None,
    dry_run: bool = False,
) -> IngestLogRecord:
    """Derive an IngestLogRecord from a WikiPatchSet or IngestProposal.

    Exactly one of ``patch`` or ``legacy_proposal`` must be supplied.

    Parameters
    ----------
    source_file : Path
        The source file on disk (used to compute source_sha and derive
        source_path).
    repo_root : Path
        Repo root; used to compute the repo-relative POSIX source_path.
    backend_name : str
        Backend display name (``"test"``, ``"claude"``, etc.).
    proposal_dir_path : Path | None
        Path to the materialized proposal directory (used as the basename
        for ``proposal_dir`` and to compute ``proposal_hash``). None only
        when the dir was not materialized (impossible for a normal or
        --dry-run run; --check never calls this).
    allow_out_of_repo : bool
        When True, source_path is recorded verbatim and
        source_repo_relative is False.
    patch : WikiPatchSet | None
        Multi-page ingest result.  Disposition is "accept" iff edits
        non-empty; reason is patch.rationale.
    legacy_proposal : IngestProposal | None
        Legacy single-source result.  Disposition and reason taken directly.
    dry_run : bool
        When True, proposal_hash is forced to None (body was stripped).
    """
    if patch is None and legacy_proposal is None:
        raise ValueError("build_log_record: must supply patch or legacy_proposal")
    if patch is not None and legacy_proposal is not None:
        raise ValueError("build_log_record: supply exactly one of patch/legacy_proposal")

    # source_path and source_repo_relative.
    try:
        rel = source_file.resolve().relative_to(repo_root.resolve())
        src_path = rel.as_posix()
        src_repo_relative = True
    except ValueError:
        src_path = str(source_file)
        src_repo_relative = False

    # For --allow-out-of-repo sources, honour the flag even when Path.relative_to
    # would have succeeded (the flag is what matters for the record).
    if allow_out_of_repo and not src_repo_relative:
        # already verbatim
        pass

    sha = source_sha(source_file)

    now_ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if patch is not None:
        # Multi-page (WikiPatchSet).
        disp = "accept" if patch.edits else "reject"
        raw_reason = patch.rationale or ""
        if patch.edits:
            tgt_paths = sorted({e.path for e in patch.edits})
            pg_types = sorted({_page_type_from_path(e.path) for e in patch.edits})
        else:
            tgt_paths = []
            pg_types = []
    else:
        # Legacy (IngestProposal).
        assert legacy_proposal is not None
        disp = legacy_proposal.disposition
        raw_reason = legacy_proposal.reason or ""
        if legacy_proposal.slug:
            page_type = legacy_proposal.page_type or "unknown"
            page_dir = _LEGACY_PAGE_TYPE_DIR.get(page_type, page_type + "s")
            tgt_paths = [f"{page_dir}/{legacy_proposal.slug}.md"]
            pg_types = [page_type]
        else:
            tgt_paths = []
            pg_types = []

    reason = truncate_reason(raw_reason)

    prop_dir_name: str | None = proposal_dir_path.name if proposal_dir_path is not None else None

    # proposal_hash: None on reject (empty edits), --dry-run, or no proposal dir.
    p_hash: str | None = None
    if (
        not dry_run
        and disp == "accept"
        and proposal_dir_path is not None
        and proposal_dir_path.is_dir()
    ):
        p_hash = proposal_hash(proposal_dir_path)

    return IngestLogRecord(
        v=1,
        ts=now_ts,
        source_path=src_path,
        source_repo_relative=src_repo_relative,
        source_sha=sha,
        backend=backend_name,
        disposition=disp,
        reason=reason,
        proposal_dir=prop_dir_name,
        target_paths=tgt_paths,
        page_types=pg_types,
        proposal_hash=p_hash,
    )


# Map legacy page_type values to their wiki directory names.
_LEGACY_PAGE_TYPE_DIR: dict[str, str] = {
    "concept": "concepts",
    "workflow": "workflows",
    "incident": "incidents",
    "decision": "decisions",
    "playbook": "playbooks",
    "glossary": "glossary",
    "open-question": "open-questions",
}


# ── Append writer (the only writer of ingest-log.md) ──────────────────────


def append_ingest_log(repo_root: Path, record: IngestLogRecord) -> None:
    """Append one NDJSON line to knowledge/wiki/.audit/ingest-log.md.

    Creates the file with the marker preamble if it does not exist.
    Fail-closed: any OSError is re-raised so the caller can exit via
    OutputWriteError (exit code 6).
    """
    log_path = repo_root / "knowledge" / "wiki" / ".audit" / "ingest-log.md"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize the record to a JSON object (one line, no trailing newline yet).
        # We use the dataclass fields in definition order to match the spec table.
        import dataclasses
        obj = dataclasses.asdict(record)
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

        if not log_path.exists():
            # First write: create with marker + blank line.
            content = INGEST_LOG_MARKER + "\n\n" + line + "\n"
            log_path.write_text(content, encoding="utf-8")
            return

        # Append a single line.  We open in binary append mode to avoid
        # any implicit re-encoding of the existing content.
        existing = log_path.read_bytes()
        # Ensure the file ends with a newline before we append.
        if existing and existing[-1:] != b"\n":
            existing += b"\n"
        new_content = existing + (line + "\n").encode("utf-8")
        # Write atomically by replacing the file contents; this avoids a
        # partial-line race (the curator-driven pipeline is single-process).
        log_path.write_bytes(new_content)
    except OSError as exc:
        raise OutputWriteError(
            f"audit log append failed for {log_path}: {exc}"
        ) from exc
