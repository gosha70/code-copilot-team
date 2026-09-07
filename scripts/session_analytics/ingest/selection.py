# session_analytics.ingest.selection — which discovered sessions to load.
#
# "Load sessions" used to mean every transcript under every source root,
# with no way to narrow it. On a machine with years of copilot history
# that is thousands of files and gigabytes of JSONL read in one go, and
# the owner's requirement from the start (the Kiro Analyzer reference:
# per-session selection tables, selected-vs-all actions) was to CHOOSE.
#
# Selection works on SessionRef — the cheap handle discover() returns —
# so nothing is parsed to decide; it runs before the incremental gate
# and before any file is opened for real. Three ways to narrow, which
# compose: modified since a moment, the newest N, or an explicit pick of
# native session ids. Copilot selection already exists on ingest().

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from ..contracts import SessionRef

#: The Studio's selection table shows at most this many discovered
#: sessions (newest first); the response says how many there are in all.
DISCOVER_LIST_CAP = 500


@dataclass(frozen=True)
class IngestSelection:
    """What to load, out of everything discover() found.

    ``since`` — epoch seconds; keep sessions whose latest source file was
    modified at or after it. ``limit`` — keep the newest N (by that same
    mtime) after every other rule. ``session_ids`` — keep exactly these
    native ids (an explicit pick from the list); empty means no pick.
    ``None``/empty everywhere selects everything, as before.
    """

    since: Optional[float] = None
    limit: Optional[int] = None
    session_ids: frozenset[str] = frozenset()

    @property
    def is_everything(self) -> bool:
        return self.since is None and self.limit is None and not self.session_ids

    def apply(self, refs: Iterable[SessionRef]) -> list[SessionRef]:
        """The refs to load, newest first when a limit is in force."""
        kept = list(refs)
        if self.session_ids:
            kept = [r for r in kept if r.native_session_id in self.session_ids]
        if self.since is not None:
            kept = [r for r in kept if r.latest_mtime >= self.since]
        if self.limit is not None:
            kept = sorted(kept, key=lambda r: r.latest_mtime, reverse=True)[: max(0, self.limit)]
        return kept


def parse_since(text: str) -> float:
    """``YYYY-MM-DD`` or an ISO datetime → epoch seconds (UTC when naive).

    Raises ValueError with the offending text, for the CLI/API to report.
    """
    raw = text.strip()
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"since: expected YYYY-MM-DD or an ISO datetime, got {raw!r}") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def describe(ref: SessionRef) -> dict[str, Any]:
    """One row for the selection table, from the handle alone (no parse).

    ``source`` is the directory the transcript sits in — for Claude Code
    that is the project folder name, which is the only project hint
    available before parsing.
    """
    files = [Path(p) for p in ref.source_files]
    size = 0
    for f in files:
        try:
            size += f.stat().st_size
        except OSError:
            pass
    first = files[0] if files else None
    return {
        "copilot": ref.copilot,
        "session_id": ref.native_session_id,
        "source": first.parent.name if first is not None else "",
        "files": len(files),
        "bytes": size,
        "modified": datetime.fromtimestamp(ref.latest_mtime, tz=timezone.utc).isoformat(),
        "modified_epoch": ref.latest_mtime,
    }
