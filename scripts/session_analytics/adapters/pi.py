# session_analytics.adapters.pi — Pi analytics adapter (T11.1, FR-021/FR-026).
#
# Source: CCT's OWN emitted analytics under a project's .cct/, NOT Pi's native
# session transcript (its on-disk format is unverified from our position, so it
# is deliberately NOT parsed — see design-t111-analytics.md):
#   - .cct/worker-analytics.jsonl  (T7.4, interim neutral source): one JSON line
#     per worker outcome — correlationId / workerId / parentSessionId /
#     childSessionId / depth / verification / childStatus / costUsd / at. Already
#     emit-redacted (T7.4 containsSecret) — the first of two redaction layers.
#   - .cct/pi-session.json         (T9.1 checkpoint): featureId / phase.
#
# Each worker record becomes ONE synthetic RawTurn with is_sidechain=True (a
# worker IS a subagent branch). HONEST ABSENCE (null-vs-zero discipline): the
# CCT source carries no per-turn tokens, tool-call detail, message text, or
# resolved model, so those are None/(); and permission denials / review rounds /
# compactions are out of this slice (named follow-ups) — never fabricated.
#
# Redaction-before-persistence flows through the EXISTING shared pipeline
# (ingest.redaction.redact_text applied by the store) — this adapter adds no new
# pattern set; its RawTurn.text is synthetic prose and it emits no tool_calls, so
# the high-risk redaction surfaces (code, tool input/output) are absent by
# construction.

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

from .. import constants as C
from ..config import load_config
from ..contracts import RawSession, RawTurn, SessionRef
from ..registry import register_adapter

_log = logging.getLogger(__name__)

COPILOT_ID = C.COPILOT_PI

# Fields the CCT source does not carry — kept explicit so the honest-absence
# contract is visible in code and asserted by tests.
ABSENT_FIELDS = (
    "tokens",
    "tool_calls",
    "message_text",
    "model",
    "permission_denials",
    "review_rounds",
    "compactions",
)


class PiAdapter:
    copilot_id = COPILOT_ID

    def __init__(self, default_root: Optional[Path] = None) -> None:
        self._default_root = default_root

    # ── discovery ──────────────────────────────────────────────────────

    def resolve_root(self, root: Optional[Path]) -> Optional[Path]:
        """Public alias for the heartbeat sweep (Slice B1): the SAME base
        resolution discovery uses, so heartbeat project paths match the
        session `project_path` stamps exactly (review B-6)."""
        return self._resolve_root(root)

    def discover(self, root: Optional[Path]) -> list[SessionRef]:
        base = self._resolve_root(root)
        if base is None or not base.exists():
            _log.debug("pi source root missing: %s", base)
            return []

        # A project holds one worker-analytics.jsonl; `base` may itself be a
        # project or a parent of projects. One SessionRef per distinct parent
        # session id within a file (a file can span parent sessions).
        analytics_files = self._find_analytics_files(base)
        refs: list[SessionRef] = []
        for f in analytics_files:
            records = list(_iter_records(f))
            mtime = f.stat().st_mtime
            for sid in _distinct_session_ids(records, f):
                refs.append(
                    SessionRef(
                        copilot=self.copilot_id,
                        native_session_id=sid,
                        source_files=(f,),
                        latest_mtime=mtime,
                        metadata={"parent_session_id": sid},
                    )
                )
        return refs

    # ── load ───────────────────────────────────────────────────────────

    def load(self, ref: SessionRef) -> RawSession:
        analytics = ref.source_files[0]
        records = [r for r in _iter_records(analytics) if _session_id(r, analytics) == ref.native_session_id]
        records.sort(key=lambda r: str(r.get("at") or ""))

        project_root = analytics.parent.parent  # <project>/.cct/worker-analytics.jsonl
        checkpoint = _load_checkpoint(project_root / Path(C.PI_SESSION_REL))

        turns: list[RawTurn] = []
        cost_total: Optional[float] = None
        correlation_ids: list[str] = []
        started_at: Optional[str] = None
        ended_at: Optional[str] = None

        for seq, rec in enumerate(records):
            at = rec.get("at") if isinstance(rec.get("at"), str) else None
            if at:
                started_at = started_at or at
                ended_at = at
            cid = rec.get("correlationId")
            if isinstance(cid, str) and cid and cid not in correlation_ids:
                correlation_ids.append(cid)
            cost = rec.get("costUsd")
            if isinstance(cost, (int, float)):
                cost_total = (cost_total or 0.0) + float(cost)

            turns.append(
                RawTurn(
                    sequence_num=seq,
                    role=C.ROLE_ASSISTANT,  # worker output; is_sidechain marks it a subagent branch
                    text=_worker_summary(rec),
                    content_length=len(_worker_summary(rec)),
                    is_sidechain=True,
                    tool_calls=(),  # ABSENT: the CCT source has no tool-call detail
                    tokens_input=None,  # ABSENT: no per-turn token counts in the source
                    tokens_output=None,
                    model=None,  # ABSENT: resolved model not stamped in the source
                    timestamp=at,
                )
            )

        metadata: dict[str, Any] = {
            "cost_usd": cost_total,
            "correlation_ids": correlation_ids,
            "worker_outcomes": [_outcome(r) for r in records],
            "final_verdict": _verdict(records),
            # Explicit honest-absence marker so downstream can see what Pi's
            # source does not provide (never fabricated). These describe the
            # SOURCE (Pi's native transcript is unparsed), not storage — they are
            # unrelated to FU-1's metadata persistence.
            "absent_fields": list(ABSENT_FIELDS),
        }
        feature_id = checkpoint.get("featureId") if checkpoint else None
        if isinstance(feature_id, str) and feature_id:
            metadata["feature_id"] = feature_id
        phase = checkpoint.get("phase") if checkpoint else None

        return RawSession(
            copilot=self.copilot_id,
            native_session_id=ref.native_session_id,
            turns=tuple(turns),
            source_files=ref.source_files,
            project_path=str(project_root),
            model=None,  # ABSENT: session-level resolved model not in the source
            phase=phase if isinstance(phase, str) else None,
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

    @staticmethod
    def _find_analytics_files(base: Path) -> list[Path]:
        name = Path(C.PI_ANALYTICS_REL).name  # worker-analytics.jsonl
        found: list[Path] = []
        # base itself a project, or a direct parent of projects.
        direct = base / ".cct" / name
        if direct.is_file():
            found.append(direct)
        for child in sorted(base.glob("*/.cct/" + name)):
            if child.is_file():
                found.append(child)
        return found


def _iter_records(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def _load_checkpoint(path: Path) -> Optional[dict[str, Any]]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _session_id(rec: dict[str, Any], path: Path) -> str:
    """Group key: the parent (CCT) session; fall back to child, then file."""
    for key in ("parentSessionId", "childSessionId"):
        v = rec.get(key)
        if isinstance(v, str) and v:
            return v
    return path.parent.parent.name or path.stem


def _distinct_session_ids(records: list[dict[str, Any]], path: Path) -> list[str]:
    seen: list[str] = []
    for rec in records:
        sid = _session_id(rec, path)
        if sid not in seen:
            seen.append(sid)
    return seen or [path.parent.parent.name or path.stem]


def _worker_summary(rec: dict[str, Any]) -> str:
    wid = rec.get("workerId") or "?"
    verification = rec.get("verification") or "?"
    child = rec.get("childStatus") or "?"
    return f"worker {wid}: verification={verification} child={child}"


def _outcome(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "worker_id": rec.get("workerId"),
        "verification": rec.get("verification"),
        "child_status": rec.get("childStatus"),
    }


def _verdict(records: list[dict[str, Any]]) -> str:
    """Fail-closed final verdict mirroring T7.4/T8.2: a worker passes only on
    verification 'passed' AND childStatus 'ok'."""
    if not records:
        return "empty"
    passed = sum(1 for r in records if r.get("verification") == "passed" and r.get("childStatus") == "ok")
    if passed == len(records):
        return "all-passed"
    if passed == 0:
        return "all-failed"
    return "partial"


def register() -> None:
    register_adapter(COPILOT_ID, PiAdapter)
