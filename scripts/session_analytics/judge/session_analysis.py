# session_analytics.judge.session_analysis — whole-session LLM analysis.
#
# The per-turn judge answers "what kind of turn was this?". This answers
# the questions a developer actually opens a session to ask: what should I
# change in my harness (tuning), how should I have prompted (coaching),
# where did the time go (efficiency). One prompt per kind over the WHOLE
# transcript, through the judge the user already configured — the
# backends' `complete()` is the same transport `rate_turn` uses.
#
# What the judge saw is recorded with the result: archived full text or
# previews only, how many characters, whether it was truncated. A reader
# must be able to weigh a finding against what the model was given.

from __future__ import annotations

import glob
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Optional

from .. import constants as C
from ..config import load_config, load_map
from ..ingest.project_key import ProjectKeyResolver
from ..ingest.redaction import redact_text, stricter_mode
from ..mcp.tools import turn_latency
from ..relational.db import Database, now_iso
from .contracts import (
    PARSE_BACKEND_ERROR,
    PARSE_INNER_UNPARSEABLE,
    PARSE_OK,
    JudgeAnswerTruncated,
    JudgeTransportError,
    TurnJudge,
)
from .parse import extract_json_object

_log = logging.getLogger(__name__)

_SPEC_FILE = "session-analysis.json"

#: Enum fields the prompts promise; anything else the model invents is
#: dropped so the UI never renders a value it has no colour or link for.
_ENUMS: dict[str, dict[str, tuple[str, ...]]] = {
    C.ANALYSIS_KIND_TUNING: {
        "category": ("steering", "permissions", "hooks", "skills", "model", "workflow"),
        "severity": ("high", "medium", "low"),
    },
    C.ANALYSIS_KIND_EFFICIENCY: {
        "lever": ("SCRIPT", "HOOK", "SKILL", "STEERING"),
    },
}
_LIST_KEY = {
    C.ANALYSIS_KIND_TUNING: "findings",
    C.ANALYSIS_KIND_COACHING: "prompts",
    C.ANALYSIS_KIND_EFFICIENCY: "inefficiencies",
}
_TRUNCATION_MARK = "[… truncated {n} chars …]"
_ERROR_HEAD_CHARS = 500
#: Steering files whose first lines the judge may see. Only these are read;
#: every other configuration artifact is listed by path alone. The project's
#: steering is whatever it has — AGENTS.md on a project that moved there,
#: CLAUDE.md on one that did not — and the judge is told which.
_STEERING_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
_STEERING_EXCERPT_CHARS = 1200
_STEERING_EXCERPT_TOTAL = 3000
#: Configuration artifacts listed to the judge by path (never their contents).
_CONFIG_PATTERNS = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/agents/*.md",
    ".claude/skills/*/SKILL.md",
    ".claude/hooks/*",
    ".cursor/rules/*",
    ".cursorrules",
)
_CONFIG_LIST_CAP = 40
#: A whole-session prompt is ~10k tokens; a 3B local model answers in
#: half a minute, a 27B one can need several minutes of prompt
#: evaluation alone on a laptop. Generous, because a timeout here throws
#: away real work.
ANALYSIS_TIMEOUT_SECONDS = 600


class UnknownAnalysisKindError(ValueError):
    pass


@dataclass(frozen=True)
class AnalysisSpec:
    version: str
    max_transcript_chars: int
    per_turn_cap_chars: int
    prompts: dict[str, str]
    required_keys: dict[str, tuple[str, ...]]
    titles: dict[str, str]


@lru_cache(maxsize=1)
def load_spec() -> AnalysisSpec:
    data = load_map(_SPEC_FILE)
    kinds = data["kinds"]
    return AnalysisSpec(
        version=str(data["version"]),
        max_transcript_chars=int(data["max_transcript_chars"]),
        per_turn_cap_chars=int(data["per_turn_cap_chars"]),
        prompts={k: str(v["prompt_template"]) for k, v in kinds.items()},
        required_keys={k: tuple(v["required_keys"]) for k, v in kinds.items()},
        titles={k: str(v.get("title", k)) for k, v in kinds.items()},
    )


# ── transcript ──────────────────────────────────────────────────────────


@dataclass
class TranscriptTurn:
    sequence_num: int
    role: str
    text: str
    latency_seconds: Optional[float]
    tools: list[str] = field(default_factory=list)
    is_error: bool = False
    archived: bool = False


@dataclass
class Transcript:
    turns: list[TranscriptTurn]        # what the judge sees (after elision)
    all_turns: list[TranscriptTurn]    # every turn — facts are session-wide
    text: str                          # the exact rendering handed to the judge
    source: str                        # archive | preview | mixed
    chars: int                         # len(text)
    truncated: bool
    archived_turns: int


def build_transcript(
    db: Database, session_id: int, *, max_chars: int, per_turn_cap: int
) -> Transcript:
    """Every turn's best available text, in order, with latency and tools.

    Text is the archived full content when trace_archive was on for the
    project, else the ingest preview. User turns are kept whole (they are
    short and they are the evidence coaching quotes); assistant turns are
    capped per turn, then the whole is capped by eliding the middle — the
    opening and the ending of a session carry the most signal.
    """
    rows = db.query(
        f"""
        SELECT t.sequence_num, t.role, t.content_preview, t.timestamp, t.id,
               td.content
        FROM copilot_turn t
        LEFT JOIN {C.TBL_TRACE_DOCUMENT} td
          ON td.session_ref = t.session_id
         AND td.sequence_num = t.sequence_num
         AND td.source_kind = ?
        WHERE t.session_id = ?
        ORDER BY t.sequence_num
        """,
        (C.SOURCE_KIND_COPILOT_TRANSCRIPT, session_id),
    )
    tools_by_turn: dict[int, list[str]] = {}
    for turn_id, name in db.query(
        """
        SELECT tc.turn_id, tc.tool_name FROM copilot_tool_call tc
        JOIN copilot_turn t ON t.id = tc.turn_id
        WHERE t.session_id = ? ORDER BY tc.turn_id, tc.sequence_num
        """,
        (session_id,),
    ):
        tools_by_turn.setdefault(int(turn_id), []).append(str(name))
    error_turns = {
        int(r[0])
        for r in db.query(
            "SELECT turn_id FROM copilot_error WHERE session_id = ? AND turn_id IS NOT NULL",
            (session_id,),
        )
    }

    turns: list[TranscriptTurn] = []
    prev_ts: Optional[datetime] = None
    archived = 0
    for seq, role, preview, ts, turn_id, content in rows:
        ts_dt = _parse_ts(ts)
        # Same rule as the page (mcp.tools.turn_latency): a gap needs BOTH
        # neighbours stamped, and a clock going backwards is no gap.
        latency = turn_latency(prev_ts, ts_dt)
        prev_ts = ts_dt
        # An archived row with EMPTY content is still archived (a
        # tool-result-only turn has no prose); only NULL means "no row".
        is_archived = content is not None
        text = content if is_archived else (preview or "")
        if is_archived:
            archived += 1
        if role != C.ROLE_USER and len(text) > per_turn_cap:
            text = text[:per_turn_cap] + _TRUNCATION_MARK.format(n=len(text) - per_turn_cap)
        turns.append(
            TranscriptTurn(
                sequence_num=int(seq),
                role=str(role),
                text=text,
                latency_seconds=latency,
                tools=tools_by_turn.get(int(turn_id), []),
                is_error=int(turn_id) in error_turns,
                archived=is_archived,
            )
        )

    if archived == 0:
        source = C.TRANSCRIPT_SOURCE_PREVIEW
    elif archived == len(turns):
        source = C.TRANSCRIPT_SOURCE_ARCHIVE
    else:
        source = C.TRANSCRIPT_SOURCE_MIXED

    all_turns = turns
    rendered = render_transcript(turns)
    truncated = False
    if len(rendered) > max_chars:
        truncated = True
        turns = _elide_middle(turns, max_chars)
        rendered = render_transcript(turns)
    if len(rendered) > max_chars:
        # Elision keeps whole turns, so one or two oversized turns can
        # still exceed the cap; the cap is the judge's context and must
        # hold regardless. Cut the text itself and say so.
        mark = _TRUNCATION_MARK.format(n=len(rendered) - max_chars)
        rendered = rendered[: max(0, max_chars - len(mark))] + mark
        truncated = True
    return Transcript(
        turns=turns, all_turns=all_turns, text=rendered, source=source,
        chars=len(rendered), truncated=truncated, archived_turns=archived,
    )


def render_transcript(turns: list[TranscriptTurn]) -> str:
    """The exact text the judge sees. One block per turn."""
    out: list[str] = []
    for t in turns:
        head = f"#{t.sequence_num} {t.role}"
        if t.latency_seconds is not None:
            head += f" (+{t.latency_seconds:g}s)"
        if t.tools:
            head += f" [tools: {', '.join(t.tools)}]"
        if t.is_error:
            head += " [ERROR]"
        out.append(f"{head}\n{t.text}".rstrip())
    return "\n\n".join(out)


def _elide_middle(turns: list[TranscriptTurn], max_chars: int) -> list[TranscriptTurn]:
    """Keep the head and the tail, drop turns from the middle until the
    rendering fits. A single marker turn says how much went."""
    if len(turns) < 3:
        return turns
    lo, hi = 0, len(turns) - 1
    kept_head: list[TranscriptTurn] = []
    kept_tail: list[TranscriptTurn] = []
    budget = max_chars
    # Alternate head/tail so both ends survive.
    while lo <= hi:
        candidate = turns[lo]
        size = len(render_transcript([candidate])) + 2
        if size > budget:
            break
        kept_head.append(candidate)
        budget -= size
        lo += 1
        if lo > hi:
            break
        candidate = turns[hi]
        size = len(render_transcript([candidate])) + 2
        if size > budget:
            break
        kept_tail.insert(0, candidate)
        budget -= size
        hi -= 1
    dropped = turns[lo : hi + 1]
    if not dropped:
        return kept_head + kept_tail
    dropped_chars = sum(len(t.text) for t in dropped)
    marker = TranscriptTurn(
        sequence_num=dropped[0].sequence_num,
        role="system",
        text=f"[… {len(dropped)} turns ({dropped_chars} chars) omitted to fit the judge's context …]",
        latency_seconds=None,
    )
    return kept_head + [marker] + kept_tail


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# ── facts ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectContext:
    """What the session's project actually contains on this machine.

    The judge may name a file only from ``files``; the steering files'
    openings ride along as excerpts so the advice can quote a real rule.
    ``available`` False (the path is gone) is distinct from empty (the
    path has none of the recognized files), because only the first means
    "we cannot tell you what exists" — and then the judge must not invent.
    """

    available: bool
    root: Optional[str]
    files: tuple[str, ...]
    excerpts: tuple[tuple[str, str], ...]


def project_context(db: Database, session_id: int) -> ProjectContext:
    """The harness files this session's project actually has, read-only."""
    row = db.query_one(
        "SELECT project_path, redaction_mode FROM copilot_session WHERE id = ?",
        (session_id,),
    )
    root = str(row[0]) if row and row[0] else ""
    if not root or not os.path.isdir(root):
        return ProjectContext(False, None, (), ())
    # The excerpts leave the machine inside a judge prompt, so they are
    # read under the STRICTER of two modes: the one recorded when this
    # session was ingested, and the project's CURRENT effective mode. A
    # project tightened after ingest must not leak under the stale mode.
    cfg = load_config()
    key = ProjectKeyResolver(cfg.project_id_rules).resolve(root)
    override = cfg.project_override(key)
    current = (
        override.redaction_mode
        if override is not None and override.redaction_mode is not None
        else cfg.redaction_mode
    )
    recorded = str(row[1]) if row and row[1] else current
    mode = stricter_mode(recorded, current)
    found: list[str] = []
    for name in _STEERING_FILES:
        if os.path.isfile(os.path.join(root, name)):
            found.append(name)
    for pattern in _CONFIG_PATTERNS:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            if os.path.isfile(path):
                found.append(os.path.relpath(path, root).replace(os.sep, "/"))
    files = tuple(sorted(set(found))[:_CONFIG_LIST_CAP])
    excerpts: list[tuple[str, str]] = []
    total = 0
    for name in _STEERING_FILES:
        if name not in files or total >= _STEERING_EXCERPT_TOTAL:
            continue
        try:
            with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                text = fh.read(_STEERING_EXCERPT_CHARS).strip()
        except OSError:
            continue
        if text:
            redacted = redact_text(text, mode)
            excerpts.append((name, redacted))
            total += len(redacted)
    return ProjectContext(True, root, files, tuple(excerpts))


def render_project(ctx: ProjectContext) -> str:
    """The PROJECT CONFIGURATION block the prompt embeds."""
    if not ctx.available:
        return (
            "project path: not available on this machine, so the files that "
            "configure the project's harness cannot be listed.\n"
            "Do NOT name a file path unless it appears in the transcript. "
            "If you cannot name a path you know exists, set config_change to null."
        )
    lines = [f"project root: {ctx.root}"]
    lines.append(
        "files that actually exist here: "
        + (
            ", ".join(ctx.files)
            if ctx.files
            else "none of the recognized steering/configuration files"
        )
    )
    for name, text in ctx.excerpts:
        lines.append(f"\n--- {name} (first {len(text)} chars) ---\n{text}")
    lines.append(
        "\nRULES: config_change.file must be one of the files listed above. "
        "A starter may be new, but the page marks any path that is not in "
        "the list as unlisted — so prefer a listed path, and say in the "
        "content when the file would have to be created. Do not name "
        "CLAUDE.md when the list does not include it — use the steering "
        "file this project actually has."
    )
    return "\n".join(lines)


def session_facts(db: Database, session_id: int, transcript: Transcript) -> str:
    """The numbers the judge should not have to infer from the text."""
    row = db.query_one(
        "SELECT copilot, model, project_path, turn_count, tool_call_count, "
        "error_count, duration_seconds, cli_version, cct_version, cct_sha, "
        "instructions_digest, providers_digest, harness_mixed, "
        "(SELECT SUM(cost_usd) FROM copilot_turn WHERE session_id = copilot_session.id) "
        "FROM copilot_session WHERE id = ?",
        (session_id,),
    )
    if row is None:
        return ""
    (
        copilot, model, project, turns, tools, errors, duration,
        cli_version, cct_version, cct_sha, instructions_digest,
        providers_digest, harness_mixed, cost,
    ) = row
    lines = [
        f"copilot: {copilot}; model: {model or 'unknown'}; project: {project}",
        f"turns: {turns}; tool calls: {tools}; errors: {errors}; "
        f"duration: {_fmt_duration(duration)}; cost: "
        + (f"${float(cost):.2f}" if cost is not None else "not priced"),
    ]
    # The harness the session ran under (#371 A4): stamped by the copilot
    # on ingest. Without it the judge has no idea which harness spec the
    # advice must fit, so it says "unstamped" rather than guessing.
    stamp: list[str] = []
    if cli_version:
        stamp.append(f"CLI {cli_version}")
    if cct_version:
        stamp.append(f"CCT {cct_version}")
    if cct_sha:
        stamp.append(f"commit {str(cct_sha)[:12]}")
    if instructions_digest:
        stamp.append(f"instructions digest {str(instructions_digest)[:12]}")
    if providers_digest:
        stamp.append(f"providers digest {str(providers_digest)[:12]}")
    if harness_mixed:
        stamp.append("mixed harness — earliest stamp shown")
    lines.append(
        "harness stamp: " + "; ".join(stamp) if stamp
        else "harness stamp: none — this session predates harness stamping"
    )
    tool_counts: dict[str, int] = {}
    for t in transcript.all_turns:
        for name in t.tools:
            tool_counts[name] = tool_counts.get(name, 0) + 1
    if tool_counts:
        top = sorted(tool_counts.items(), key=lambda kv: -kv[1])[:8]
        lines.append("top tools: " + ", ".join(f"{n} ×{c}" for n, c in top))
    slow = sorted(
        (t for t in transcript.all_turns if t.latency_seconds and t.role != C.ROLE_USER),
        key=lambda t: -(t.latency_seconds or 0),
    )[:5]
    if slow:
        lines.append(
            "slowest assistant turns: "
            + ", ".join(f"#{t.sequence_num} {t.latency_seconds:g}s" for t in slow)
        )
    lines.append(
        f"transcript source: {transcript.source}; {transcript.chars} chars"
        + ("; TRUNCATED to fit" if transcript.truncated else "")
    )
    return "\n".join(lines)


def _fmt_duration(seconds: Any) -> str:
    if seconds is None:
        return "unknown"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"


# ── run + persist ───────────────────────────────────────────────────────


def analyze_session(
    db: Database,
    session_id: int,
    kind: str,
    *,
    judge: TurnJudge,
    force: bool = False,
    timeout: int = ANALYSIS_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run one analysis kind for one session and store the outcome.

    Returns the stored row as a dict (see ``get_analysis``). A transport
    failure RAISES — the caller decides whether that is a 503 or a CLI
    error — but a parse failure is stored, because "the model answered
    and we could not read it" is a result the page must show.
    """
    spec = load_spec()
    if kind not in spec.prompts:
        raise UnknownAnalysisKindError(
            f"unknown analysis kind {kind!r}; known: {', '.join(sorted(spec.prompts))}"
        )
    if not force:
        existing = get_analysis(db, session_id, kind)
        if existing is not None and existing["parse_status"] == PARSE_OK:
            return existing

    transcript = build_transcript(
        db, session_id,
        max_chars=spec.max_transcript_chars, per_turn_cap=spec.per_turn_cap_chars,
    )
    project = project_context(db, session_id)
    prompt = spec.prompts[kind].format(
        facts=session_facts(db, session_id, transcript),
        project=render_project(project),
        transcript=transcript.text,
    )
    model = getattr(judge, "_model_label", None) or getattr(judge, "_model", "") or ""
    def failure(status: str, error: str) -> dict[str, Any]:
        return _record_failure(
            db, session_id, kind, judge, str(model), spec.version, transcript,
            parse_status=status, error=error,
        )

    try:
        text = judge.complete(prompt, timeout=timeout)
    except JudgeAnswerTruncated as exc:
        # The model DID answer; the answer is just incomplete. That is a
        # stored result, not a 503 — the page shows why and offers a
        # re-run, with the head of what came back as evidence.
        return failure(
            C.ANALYSIS_PARSE_ANSWER_TRUNCATED,
            f"{exc}; answer began: {exc.partial[:_ERROR_HEAD_CHARS]}",
        )
    except JudgeTransportError as exc:
        failure(PARSE_BACKEND_ERROR, str(exc)[:_ERROR_HEAD_CHARS])
        raise

    obj = extract_json_object(text)
    if obj is None:
        return failure(PARSE_INNER_UNPARSEABLE, (text or "")[:_ERROR_HEAD_CHARS])

    missing = [k for k in spec.required_keys[kind] if k not in obj]
    if missing:
        return failure(
            C.ANALYSIS_PARSE_MISSING_KEYS,
            f"missing keys: {', '.join(missing)}; got: {(text or '')[:_ERROR_HEAD_CHARS]}",
        )

    result = _coerce(kind, obj, {t.sequence_num for t in transcript.all_turns}, project)
    _store(
        db, session_id, kind, judge, str(model), spec.version, transcript,
        parse_status=PARSE_OK, result=result, error=None,
    )
    return get_analysis(db, session_id, kind) or {}


def _record_failure(
    db: Database, session_id: int, kind: str, judge: TurnJudge, model: str,
    version: str, transcript: Transcript, *, parse_status: str, error: Optional[str],
) -> dict[str, Any]:
    """Report a failed run without destroying a good one.

    A first run's failure is stored (an absent row and a failed run must
    not look the same). A failed RE-run leaves the earlier parsed result
    in place — a re-generate that hits a down backend must not cost the
    user the analysis they already had — and reports the failure only in
    the returned row, flagged ``kept_previous``.
    """
    existing = get_analysis(db, session_id, kind)
    if existing is None or existing["parse_status"] != PARSE_OK:
        _store(
            db, session_id, kind, judge, model, version, transcript,
            parse_status=parse_status, result=None, error=error,
        )
        return get_analysis(db, session_id, kind) or {}
    return {
        "kind": kind,
        "judge_id": getattr(judge, "judge_id", ""),
        "judge_model": model,
        "prompt_version": version,
        "transcript_source": transcript.source,
        "transcript_chars": transcript.chars,
        "truncated": transcript.truncated,
        "parse_status": parse_status,
        "result": None,
        "error": error,
        "created_at": now_iso(),
        "kept_previous": True,
    }


def _coerce(
    kind: str, obj: dict[str, Any], valid_turns: set[int], project: ProjectContext
) -> dict[str, Any]:
    """Keep what the contract promises, in the shape the page renders.

    Enums are normalised and items with unknown values dropped; turn
    references are clamped to turns that exist; every field the page
    dereferences is present with the promised type (a missing list is
    ``[]``, a missing string ``""``, a malformed object ``None``). Items
    that lack their one essential field (a title, or for coaching the
    issue and the improved prompt) are dropped and counted, so an empty
    list can say why.
    """
    out: dict[str, Any] = {"summary": str(obj.get("summary", "")).strip()}
    if kind == C.ANALYSIS_KIND_COACHING:
        score = obj.get("overall_score")
        out["overall_score"] = int(score) if isinstance(score, (int, float)) and 1 <= score <= 5 else None
        out["patterns"] = [str(p) for p in obj.get("patterns") or [] if str(p).strip()]
    list_key = _LIST_KEY[kind]
    items: list[dict[str, Any]] = []
    offered = 0
    for raw in obj.get(list_key) or []:
        offered += 1
        if not isinstance(raw, dict):
            continue
        item = _ITEM_SHAPE[kind](raw, valid_turns, project)
        if item is None:
            continue
        ok = True
        for field_name, allowed in _ENUMS.get(kind, {}).items():
            v = str(item.get(field_name, "")).strip()
            v = v.upper() if allowed[0].isupper() else v.lower()
            if v not in allowed:
                ok = False
                break
            item[field_name] = v
        if ok:
            items.append(item)
    # Small models repeat themselves (eight rows quoting the same turn);
    # one row per (turn, quoted text) is all a reader needs.
    seen: set[tuple[Any, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = (item.get("turn"), str(item.get("original") or item.get("title") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    out[list_key] = unique
    # What the model offered but the contract could not keep (unknown
    # enum, missing essentials, repeat). An empty list that came from
    # dropping items must not read as "nothing found".
    out["dropped_items"] = offered - len(unique)
    return out


def _text(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _turn_list(v: Any, valid_turns: set[int]) -> list[int]:
    if not isinstance(v, list):
        return []
    return [int(t) for t in v if isinstance(t, (int, float)) and int(t) in valid_turns]


def _number(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _file_block(v: Any, body_key: str, project: ProjectContext) -> Optional[dict[str, Any]]:
    if not isinstance(v, dict):
        return None
    file, body = _text(v.get("file")), _text(v.get(body_key))
    if not (file and body):
        return None
    return {
        "file": file,
        body_key: body,
        # True: the path is one of the project's LISTED files. False: it
        # is not (or it is absolute / traverses upward). None: no project
        # to check against.
        "file_found": _file_state(project, file),
    }


def _file_state(project: ProjectContext, file: str) -> Optional[bool]:
    """True only when the path is one of the project's listed files.

    Membership, not existence: a real file the inventory leaves out (a
    ``.env``, say) must not read as "found", and the check must never
    become a way to probe the filesystem. Absolute paths and any ``..``
    segment are refused before the check. None means the project is
    unavailable, so a well-formed relative path cannot be judged at all.
    """
    raw = file.strip().replace("\\", "/")
    if not raw or os.path.isabs(raw) or raw.startswith("~"):
        return False
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return False
    if not project.available:
        return None
    return "/".join(parts) in project.files


def _tuning_item(
    raw: dict[str, Any], valid_turns: set[int], project: ProjectContext
) -> Optional[dict[str, Any]]:
    title = _text(raw.get("title"))
    if not title:
        return None
    return {
        "category": _text(raw.get("category")),
        "severity": _text(raw.get("severity")),
        "title": title,
        "evidence_turns": _turn_list(raw.get("evidence_turns"), valid_turns),
        "explanation": _text(raw.get("explanation")),
        "recommendation": _text(raw.get("recommendation")),
        "config_change": _file_block(raw.get("config_change"), "diff", project),
    }


def _coaching_item(
    raw: dict[str, Any], valid_turns: set[int], _project: ProjectContext
) -> Optional[dict[str, Any]]:
    issue, improved = _text(raw.get("issue")), _text(raw.get("improved"))
    if not (issue and improved):
        # A row without the issue or the better prompt coaches nothing.
        return None
    t = raw.get("turn")
    return {
        "turn": int(t) if isinstance(t, (int, float)) and int(t) in valid_turns else None,
        "original": _text(raw.get("original")),
        "issue": issue,
        "improved": improved,
    }


def _efficiency_item(
    raw: dict[str, Any], valid_turns: set[int], project: ProjectContext
) -> Optional[dict[str, Any]]:
    title = _text(raw.get("title"))
    if not title:
        return None
    return {
        "title": title,
        "evidence_turns": _turn_list(raw.get("evidence_turns"), valid_turns),
        "wasted_turns": _number(raw.get("wasted_turns")),
        "wasted_seconds": _number(raw.get("wasted_seconds")),
        "lever": _text(raw.get("lever")),
        "starter": _file_block(raw.get("starter"), "content", project),
    }


_ITEM_SHAPE = {
    C.ANALYSIS_KIND_TUNING: _tuning_item,
    C.ANALYSIS_KIND_COACHING: _coaching_item,
    C.ANALYSIS_KIND_EFFICIENCY: _efficiency_item,
}


def _store(
    db: Database, session_id: int, kind: str, judge: TurnJudge, model: str,
    version: str, transcript: Transcript, *, parse_status: str,
    result: Optional[dict[str, Any]], error: Optional[str],
) -> None:
    db.execute(
        f"DELETE FROM {C.TBL_SESSION_ANALYSIS} WHERE session_ref = ? AND kind = ?",
        (session_id, kind),
    )
    db.execute(
        f"INSERT INTO {C.TBL_SESSION_ANALYSIS} (session_ref, kind, judge_id, judge_model, "
        "prompt_version, transcript_source, transcript_chars, truncated, parse_status, "
        "result_json, error_text, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id, kind, getattr(judge, "judge_id", ""), model, version,
            transcript.source, transcript.chars, transcript.truncated, parse_status,
            json.dumps(result) if result is not None else None, error, now_iso(),
        ),
    )
    db.commit()


def get_analysis(db: Database, session_id: int, kind: str) -> Optional[dict[str, Any]]:
    row = db.query_one(
        f"SELECT kind, judge_id, judge_model, prompt_version, transcript_source, "
        f"transcript_chars, truncated, parse_status, result_json, error_text, created_at "
        f"FROM {C.TBL_SESSION_ANALYSIS} WHERE session_ref = ? AND kind = ?",
        (session_id, kind),
    )
    if row is None:
        return None
    (kind, judge_id, judge_model, version, source, chars, truncated,
     status, result_json, error, created_at) = row
    return {
        "kind": kind,
        "judge_id": judge_id,
        "judge_model": judge_model,
        "prompt_version": version,
        "transcript_source": source,
        "transcript_chars": int(chars or 0),
        "truncated": bool(truncated),
        "parse_status": status,
        "result": json.loads(result_json) if result_json else None,
        "error": error,
        "created_at": created_at,
    }


def all_analyses(db: Database, session_id: int) -> dict[str, Optional[dict[str, Any]]]:
    return {kind: get_analysis(db, session_id, kind) for kind in C.ANALYSIS_KINDS}
