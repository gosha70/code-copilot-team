# session_analytics.adapters.aider — Aider markdown-history adapter.
#
# Source: ``.aider.chat.history.md`` files in project directories. Aider
# writes a human-readable markdown transcript:
#   - ``# aider chat started at <timestamp>``   — session start marker
#   - lines prefixed ``#### ``                   — a user message
#   - other non-blank text                       — assistant output
#   - ``> `` lines                               — command/tool echoes
#
# GROUNDING NOTE: the exact markdown shape is reconstructed from Aider's
# documented history format; this adapter has NOT been validated against a
# real .aider.chat.history.md on this machine (none present). The committed
# fixture is provisional — regenerate it (and re-confirm the parser) from a
# real Aider capture before relying on the Aider numbers. Claude Code is the
# validated adapter.

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from .. import constants as C
from ..config import load_config
from ..contracts import RawSession, RawTurn, SessionRef
from ..registry import register_adapter

_log = logging.getLogger(__name__)

COPILOT_ID = C.COPILOT_AIDER
_HISTORY_NAME = ".aider.chat.history.md"
_SESSION_RE = re.compile(r"^#\s*aider chat started at\s*(.*)$")
_USER_PREFIX = "#### "


class AiderAdapter:
    copilot_id = COPILOT_ID

    def __init__(self, default_root: Optional[Path] = None) -> None:
        self._default_root = default_root

    def discover(self, root: Optional[Path]) -> list[SessionRef]:
        base = self._resolve_root(root)
        if base is None or not base.exists():
            return []
        refs: list[SessionRef] = []
        # One logical "session ref" per history file; the file may contain
        # multiple ``aider chat started`` blocks, surfaced as turns grouped
        # under one native id (the file path).
        for hist in sorted(base.rglob(_HISTORY_NAME)):
            refs.append(
                SessionRef(
                    copilot=self.copilot_id,
                    native_session_id=str(hist),
                    source_files=(hist,),
                    latest_mtime=hist.stat().st_mtime,
                )
            )
        return refs

    def load(self, ref: SessionRef) -> RawSession:
        path = ref.source_files[0]
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            _log.warning("cannot read %s: %s", path, exc)
            lines = []

        turns: list[RawTurn] = []
        started_at: Optional[str] = None
        seq = 0
        role: Optional[str] = None
        buf: list[str] = []

        def flush() -> None:
            nonlocal seq, role, buf
            if role is not None and buf:
                text = "\n".join(buf).strip()
                if text:
                    turns.append(
                        RawTurn(
                            sequence_num=seq,
                            role=role,
                            text=text,
                            content_length=len(text),
                        )
                    )
                    seq += 1
            buf = []

        for line in lines:
            m = _SESSION_RE.match(line)
            if m:
                flush()
                role = None
                started_at = started_at or m.group(1).strip() or None
                continue
            if line.startswith(_USER_PREFIX):
                if role != C.ROLE_USER:
                    flush()
                    role = C.ROLE_USER
                buf.append(line[len(_USER_PREFIX):])
            elif line.startswith(">"):
                # command/tool echo — keep with the current assistant block
                if role != C.ROLE_ASSISTANT:
                    flush()
                    role = C.ROLE_ASSISTANT
                buf.append(line)
            else:
                if line.strip() == "" and not buf:
                    continue
                if role is None:
                    role = C.ROLE_ASSISTANT
                elif role == C.ROLE_USER and line.strip():
                    flush()
                    role = C.ROLE_ASSISTANT
                buf.append(line)
        flush()

        return RawSession(
            copilot=self.copilot_id,
            native_session_id=ref.native_session_id,
            turns=tuple(turns),
            source_files=ref.source_files,
            project_path=str(path.parent),
            started_at=started_at,
            metadata={"provisional_format": True},
        )

    def _resolve_root(self, root: Optional[Path]) -> Optional[Path]:
        if root is not None:
            return Path(root)
        if self._default_root is not None:
            return self._default_root
        return load_config().source_root(self.copilot_id)


def register() -> None:
    register_adapter(COPILOT_ID, AiderAdapter)
