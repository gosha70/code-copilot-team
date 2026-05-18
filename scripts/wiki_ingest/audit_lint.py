# wiki_ingest.audit_lint — Phase-1 audit-trail format lint.
#
# The lint-side validator for knowledge/wiki/.audit/. It implements the
# machine-checkable spec in knowledge/wiki/schema/audit-rules.md the
# same way lint-wiki.sh implements lint-rules.md: the schema file is the
# human contract, this module is the executable check. It is NOT loaded
# via prompt.load_schema_files and is never injected into a backend
# prompt — it is consumed directly by `wiki lint`.
#
# v1 is FORMAT-ONLY: marker, NDJSON shape, required keys/types/enums,
# ts pattern, reason codepoint bound, archive directory contents. No
# referential cross-checks (source_sha resolves, proposal_hash matches
# an archive) — those are a named follow-up, not v1.

from __future__ import annotations

import json
import re
from pathlib import Path

INGEST_LOG_MARKER = "<!-- ingest-log schema v1 -->"

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

_REASON_MAX_CODEPOINTS = 240
_DISPOSITIONS = {"accept", "reject"}

# Exact key set for schema v1. No more, no less.
_REQUIRED_KEYS: dict[str, type | tuple[type, ...]] = {
    "v": int,
    "ts": str,
    "source_path": str,
    "source_repo_relative": bool,
    "source_sha": str,
    "backend": str,
    "disposition": str,
    "reason": str,
    "proposal_dir": (str, type(None)),
    "target_paths": list,
    "page_types": list,
    "proposal_hash": (str, type(None)),
}

_PERMITTED_PROPOSAL_ENTRIES = {"plan.json", "proposal.md", "curator-delta.md"}


def _validate_ingest_log(path: Path) -> list[str]:
    """Return a list of violation strings for ingest-log.md (empty = clean)."""
    errors: list[str] = []
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")

    if not lines or lines[0] != INGEST_LOG_MARKER:
        errors.append(
            f"{path}: line 1 must be exactly '{INGEST_LOG_MARKER}'"
        )
        # Without a valid marker the rest is unreliable; still try lines.
    if len(lines) < 2 or lines[1] != "":
        errors.append(f"{path}: line 2 must be empty")

    for n, line in enumerate(lines[2:], start=3):
        if line == "":
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{n}: not valid JSON ({exc.msg})")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{path}:{n}: JSON value is not an object")
            continue

        keys = set(obj)
        missing = set(_REQUIRED_KEYS) - keys
        extra = keys - set(_REQUIRED_KEYS)
        if missing:
            errors.append(f"{path}:{n}: missing keys {sorted(missing)}")
        if extra:
            errors.append(f"{path}:{n}: unexpected keys {sorted(extra)}")

        for key, typ in _REQUIRED_KEYS.items():
            if key in obj and not isinstance(obj[key], typ):
                # bool is an int subclass — guard v/source_repo_relative.
                if key == "v" and isinstance(obj[key], bool):
                    errors.append(f"{path}:{n}: 'v' must be int, not bool")
                elif typ is int and isinstance(obj[key], bool):
                    errors.append(f"{path}:{n}: '{key}' must be int, not bool")
                else:
                    errors.append(
                        f"{path}:{n}: '{key}' has wrong type "
                        f"(got {type(obj[key]).__name__})"
                    )

        ver = obj.get("v")
        if isinstance(ver, int) and not isinstance(ver, bool) and ver != 1:
            errors.append(
                f"{path}:{n}: unsupported schema version v={ver} "
                f"(this linter knows v=1)"
            )

        for arr_key in ("target_paths", "page_types"):
            arr = obj.get(arr_key)
            if isinstance(arr, list):
                bad = [
                    i for i, v in enumerate(arr) if not isinstance(v, str)
                ]
                if bad:
                    errors.append(
                        f"{path}:{n}: '{arr_key}' must be an array of "
                        f"strings (non-string item at index {bad[0]})"
                    )

        disp = obj.get("disposition")
        if isinstance(disp, str) and disp not in _DISPOSITIONS:
            errors.append(
                f"{path}:{n}: disposition '{disp}' not in "
                f"{sorted(_DISPOSITIONS)}"
            )

        ts = obj.get("ts")
        if isinstance(ts, str) and not _TS_RE.match(ts):
            errors.append(
                f"{path}:{n}: ts '{ts}' is not ISO-8601 UTC "
                f"(YYYY-MM-DDThh:mm:ssZ)"
            )

        reason = obj.get("reason")
        if isinstance(reason, str) and len(reason) > _REASON_MAX_CODEPOINTS:
            errors.append(
                f"{path}:{n}: reason is {len(reason)} codepoints "
                f"(max {_REASON_MAX_CODEPOINTS})"
            )

        sha = obj.get("source_sha")
        if isinstance(sha, str) and not _HEX64_RE.match(sha):
            errors.append(f"{path}:{n}: source_sha is not 64 lowercase hex")

        phash = obj.get("proposal_hash")
        if isinstance(phash, str) and not _HEX64_RE.match(phash):
            errors.append(
                f"{path}:{n}: proposal_hash is not null or 64 lowercase hex"
            )

    return errors


def _validate_proposal_dir(d: Path) -> list[str]:
    """Return violation strings for one .audit/proposals/<name>/ dir."""
    errors: list[str] = []
    children = list(d.iterdir())
    entries = {p.name for p in children}

    # Required entries must exist AND be regular files (a directory
    # named plan.json is a violation, not an IsADirectoryError).
    for required in ("plan.json", "proposal.md"):
        target = d / required
        if required not in entries:
            errors.append(f"{d}: missing required {required}")
        elif not target.is_file():
            errors.append(f"{d}/{required}: must be a regular file")

    plan = d / "plan.json"
    if plan.is_file():
        try:
            json.loads(plan.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{d}/plan.json: not valid JSON ({exc.msg})")
        except OSError as exc:
            errors.append(f"{d}/plan.json: unreadable ({exc})")

    unexpected = sorted(entries - _PERMITTED_PROPOSAL_ENTRIES)
    if unexpected:
        errors.append(
            f"{d}: unexpected entries {unexpected} "
            f"(permitted: {sorted(_PERMITTED_PROPOSAL_ENTRIES)})"
        )
    return errors


def validate_audit_tree(repo_root: Path) -> list[str]:
    """Validate knowledge/wiki/.audit/. Empty list = clean (or absent).

    Format-only per audit-rules.md v1. A missing .audit/ tree is clean
    (the trail simply has not started yet).
    """
    return validate_audit_dir(repo_root / "knowledge" / "wiki" / ".audit")


def validate_audit_dir(audit_dir: Path) -> list[str]:
    """Validate one `.audit/` directory directly (used by tests/fixtures).

    Same contract as validate_audit_tree but takes the `.audit/` path
    itself rather than a repo root.
    """
    if not audit_dir.is_dir():
        return []

    errors: list[str] = []

    # Closed top-level set: only ingest-log.md (file) and proposals/
    # (dir). .audit/ is exempt from structural lint, so a stray
    # .audit/notes.md must be caught here or it is invisible.
    for child in sorted(audit_dir.iterdir()):
        if child.name == "ingest-log.md":
            if not child.is_file():
                errors.append(f"{child}: ingest-log.md must be a file")
        elif child.name == "proposals":
            if not child.is_dir():
                errors.append(f"{child}: proposals must be a directory")
        else:
            errors.append(
                f"{child}: unexpected entry under .audit/ "
                f"(only ingest-log.md and proposals/ are permitted)"
            )

    log = audit_dir / "ingest-log.md"
    if log.is_file():
        errors.extend(_validate_ingest_log(log))

    proposals = audit_dir / "proposals"
    if proposals.is_dir():
        for child in sorted(proposals.iterdir()):
            if child.is_dir():
                errors.extend(_validate_proposal_dir(child))
            else:
                errors.append(
                    f"{child}: .audit/proposals/ may only contain "
                    f"<date>-<slug>/ directories"
                )

    return errors
