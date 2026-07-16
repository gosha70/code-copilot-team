# session_analytics.adapters.claude_code — Claude Code JSONL adapter.
#
# Source: ~/.claude/projects/<project-hash>/<session-uuid>.jsonl
# One JSONL file per session; a logical session can span multiple files
# (continuations) that share the same ``sessionId``. Each line is a JSON
# object with a top-level ``type``. Only ``user`` and ``assistant`` lines
# are conversational; everything else (``attachment``, ``system``,
# ``last-prompt``, ``permission-mode``, ``ai-title``,
# ``file-history-snapshot``, ``queue-operation``, …) is SKIPPED, not an
# error — real session files contain many such lines.
#
# message.content is an array of blocks: ``text``, ``thinking``,
# ``tool_use`` {id,name,input}, ``tool_result`` {tool_use_id,content,
# is_error}. tool_use blocks live in assistant turns; their results arrive
# as tool_result blocks in the FOLLOWING user turn — pairing is therefore
# session-wide by ``tool_use_id``, not within a single turn.

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from .. import constants as C
from ..config import load_config
from ..contracts import RawSession, RawToolCall, RawTurn, SessionRef
from ..registry import register_adapter

_log = logging.getLogger(__name__)

COPILOT_ID = C.COPILOT_CLAUDE_CODE

# Line types we parse; all others are skipped.
_CONVERSATIONAL_TYPES = {C.ROLE_USER, C.ROLE_ASSISTANT}

_SLASH_RE = re.compile(r"<command-name>\s*(/?[\w:-]+)\s*</command-name>")


class ClaudeCodeAdapter:
    copilot_id = COPILOT_ID

    def __init__(self, default_root: Optional[Path] = None) -> None:
        self._default_root = default_root

    # ── discovery ──────────────────────────────────────────────────────

    def discover(self, root: Optional[Path]) -> list[SessionRef]:
        base = self._resolve_root(root)
        if base is None or not base.exists():
            _log.debug("claude-code source root missing: %s", base)
            return []

        # Group JSONL files by the sessionId they carry. We read only the
        # first line of each file to learn its sessionId cheaply; if that
        # fails we fall back to the filename stem (the file is named by
        # session uuid).
        by_session: dict[str, list[Path]] = {}
        for jsonl in sorted(base.glob("*/*.jsonl")):
            sid = _peek_session_id(jsonl) or jsonl.stem
            by_session.setdefault(sid, []).append(jsonl)

        refs: list[SessionRef] = []
        for sid, files in by_session.items():
            files_sorted = tuple(sorted(files))
            latest = max(f.stat().st_mtime for f in files_sorted)
            refs.append(
                SessionRef(
                    copilot=self.copilot_id,
                    native_session_id=sid,
                    source_files=files_sorted,
                    latest_mtime=latest,
                )
            )
        return refs

    # ── load ───────────────────────────────────────────────────────────

    def load(self, ref: SessionRef) -> RawSession:
        records: list[dict[str, Any]] = []
        for path in ref.source_files:
            records.extend(_iter_records(path))

        # Order by timestamp (ISO-8601 sorts lexically); fall back to file
        # order for records missing a timestamp by using a stable index.
        indexed = list(enumerate(records))
        indexed.sort(key=lambda iv: (iv[1].get("timestamp") or "", iv[0]))
        ordered = [rec for _, rec in indexed]

        # First pass: collect every tool_result across the session, keyed
        # by tool_use_id, so assistant-turn tool_use blocks can be paired.
        results_by_id = _collect_tool_results(ordered)

        # Session-level model (E5 fallback target): the first non-empty
        # model reported by an assistant message, same as before per-turn
        # attribution existed. Computed up front (not mutated during the
        # main loop) so every turn's fallback is correct regardless of
        # ordering — including a turn preceding the message that first
        # reports the model.
        session_model = _first_model(ordered)

        turns: list[RawTurn] = []
        project_path: Optional[str] = None
        started_at: Optional[str] = None
        ended_at: Optional[str] = None
        git_branch: Optional[str] = None

        seq = 0
        for rec in ordered:
            rtype = rec.get("type")
            if rtype not in _CONVERSATIONAL_TYPES:
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue

            project_path = project_path or rec.get("cwd")
            git_branch = git_branch or rec.get("gitBranch")
            ts = rec.get("timestamp")
            if ts:
                started_at = started_at or ts
                ended_at = ts

            # Per-turn model attribution (E5): the assistant message's own
            # model, falling back to the session-level model when this
            # turn's message has none. Non-assistant turns (user turns
            # never carry a model in Claude Code transcripts) get None.
            turn_model = (msg.get("model") or session_model) if rtype == C.ROLE_ASSISTANT else None

            text, tool_calls = _blocks_to_turn(msg.get("content"), results_by_id)
            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}

            turns.append(
                RawTurn(
                    sequence_num=seq,
                    role=rtype,
                    text=text,
                    content_length=len(text),
                    uuid=rec.get("uuid"),
                    parent_uuid=rec.get("parentUuid"),
                    is_sidechain=bool(rec.get("isSidechain")),
                    tool_calls=tuple(tool_calls),
                    tokens_input=_opt_int(usage.get("input_tokens")),
                    tokens_output=_opt_int(usage.get("output_tokens")),
                    cache_read_tokens=_opt_int(usage.get("cache_read_input_tokens")),
                    cache_write_tokens=_opt_int(usage.get("cache_creation_input_tokens")),
                    model=turn_model,
                    timestamp=ts,
                    slash_command=_slash_command(text),
                )
            )
            seq += 1

        metadata: dict[str, Any] = {}
        if git_branch:
            metadata["git_branch"] = git_branch

        return RawSession(
            copilot=self.copilot_id,
            native_session_id=ref.native_session_id,
            turns=tuple(turns),
            source_files=ref.source_files,
            project_path=project_path,
            model=session_model,
            started_at=started_at,
            ended_at=ended_at,
            metadata=metadata,
        )

    # ── internals ──────────────────────────────────────────────────────

    def _resolve_root(self, root: Optional[Path]) -> Optional[Path]:
        if root is not None:
            return Path(root)
        if self._default_root is not None:
            return self._default_root
        cfg = load_config()
        return cfg.source_root(self.copilot_id)


# ── module-level helpers (pure, testable) ──────────────────────────────


def _iter_records(path: Path) -> Iterable[dict[str, Any]]:
    """Yield parsed JSON objects from a JSONL file, skipping blank/garbage
    lines rather than aborting the whole session on one bad line."""
    try:
        with path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    _log.warning("skipping unparseable line %s:%d: %s", path, lineno, exc)
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError as exc:
        _log.warning("cannot read %s: %s", path, exc)


def _first_model(records: list[dict[str, Any]]) -> Optional[str]:
    """The first non-empty ``model`` reported by any assistant message,
    in the already-chronologically-ordered ``records``. This is the
    session-level model (``copilot_session.model``) and the per-turn
    fallback target (E5)."""
    for rec in records:
        if rec.get("type") != C.ROLE_ASSISTANT:
            continue
        msg = rec.get("message")
        if isinstance(msg, dict):
            m = msg.get("model")
            if m:
                return m
    return None


def _peek_session_id(path: Path) -> Optional[str]:
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    return None
                if isinstance(obj, dict):
                    sid = obj.get("sessionId")
                    return sid if isinstance(sid, str) else None
                return None
    except OSError:
        return None
    return None


def _collect_tool_results(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map tool_use_id → {is_error, text} across the whole session."""
    out: dict[str, dict[str, Any]] = {}
    for rec in records:
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tid = block.get("tool_use_id")
            if not isinstance(tid, str):
                continue
            out[tid] = {
                "is_error": bool(block.get("is_error", False)),
                "text": _content_to_text(block.get("content")),
            }
    return out


def _blocks_to_turn(
    content: Any,
    results_by_id: dict[str, dict[str, Any]],
) -> tuple[str, list[RawToolCall]]:
    """Render a message's content into (visible_text, tool_calls)."""
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return "", []

    text_parts: list[str] = []
    tool_calls: list[RawToolCall] = []
    tool_seq = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = block.get("text")
            if isinstance(t, str):
                text_parts.append(t)
        elif btype == "tool_use":
            tid = block.get("id")
            paired = results_by_id.get(tid) if isinstance(tid, str) else None
            tool_calls.append(
                RawToolCall(
                    tool_use_id=tid if isinstance(tid, str) else None,
                    name_raw=str(block.get("name") or ""),
                    input_obj=block.get("input") if isinstance(block.get("input"), dict) else {},
                    sequence_num=tool_seq,
                    result_is_error=(paired.get("is_error") if paired else None),
                    result_text=(paired.get("text") if paired else None),
                )
            )
            tool_seq += 1
        # ``thinking`` and ``tool_result`` blocks contribute no visible
        # text to the turn (results are attached to their tool_use above).
    return "\n".join(text_parts), tool_calls


def _content_to_text(content: Any) -> str:
    """Flatten a tool_result content (string or list of blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def _slash_command(text: str) -> Optional[str]:
    m = _SLASH_RE.search(text or "")
    if not m:
        return None
    cmd = m.group(1)
    return cmd if cmd.startswith("/") else f"/{cmd}"


def _opt_int(val: Any) -> Optional[int]:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    return None


# ── registration ───────────────────────────────────────────────────────


def register() -> None:
    register_adapter(COPILOT_ID, ClaudeCodeAdapter)
