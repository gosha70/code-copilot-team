# session_analytics.ask.loop — the question-answering loop.
#
# One transport for every judge backend: `complete(prompt) -> JSON text`,
# the same call the analyses use. Each step the model returns ONE JSON
# object — a tool call, or the answer. The loop runs the tool, appends
# what came back (capped, and the cap is stated), and asks again; the
# page sees every step as it happens. No native tool-calling API is
# used, so the loop works on Ollama, any OpenAI-compatible server and the
# claude CLI alike, whichever Settings names.

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterator, Mapping, Optional, Sequence

from ..config import load_map
from ..judge.contracts import JudgeAnswerTruncated, JudgeTransportError, TurnJudge
from ..judge.parse import extract_json_object
from . import tools as T

_log = logging.getLogger(__name__)

_SPEC_FILE = "ask.json"

EVENT_JUDGE = "judge"
EVENT_STEP = "step"
EVENT_RESULT = "result"
EVENT_ANSWER = "answer"
EVENT_ERROR = "error"

_TRUNCATION_MARK = "\n[… truncated: {shown} of {total} chars shown — ask a narrower question …]"
_ERROR_HEAD_CHARS = 300


@dataclass(frozen=True)
class AskSpec:
    version: str
    max_steps: int
    max_result_chars: int
    max_history: int
    step_timeout_seconds: int
    examples: tuple[str, ...]
    tools: tuple[dict[str, Any], ...]
    prompt_template: str
    force_answer_note: str
    bad_json_note: str

    def declared_args(self, name: str) -> Optional[dict[str, Any]]:
        for t in self.tools:
            if t["name"] == name:
                return dict(t.get("args") or {})
        return None


@lru_cache(maxsize=1)
def load_spec() -> AskSpec:
    d = load_map(_SPEC_FILE)
    return AskSpec(
        version=str(d["version"]),
        max_steps=int(d["max_steps"]),
        max_result_chars=int(d["max_result_chars"]),
        max_history=int(d["max_history"]),
        step_timeout_seconds=int(d["step_timeout_seconds"]),
        examples=tuple(str(e) for e in d.get("examples", ())),
        tools=tuple(d["tools"]),
        prompt_template=str(d["prompt_template"]),
        force_answer_note=str(d["force_answer_note"]),
        bad_json_note=str(d["bad_json_note"]),
    )


# ── prompt rendering (pure) ─────────────────────────────────────────────


def render_tools(spec: AskSpec) -> str:
    lines = []
    for t in spec.tools:
        args = t.get("args") or {}
        sig = ", ".join(args) if args else ""
        lines.append(f"- {t['name']}({sig}): {t['purpose']}")
        for name, desc in args.items():
            lines.append(f"    {name}: {desc}")
    return "\n".join(lines)


def render_history(history: Sequence[Mapping[str, Any]], spec: AskSpec) -> str:
    kept = list(history)[-spec.max_history :]
    if not kept:
        return ""
    out = ["EARLIER IN THIS CONVERSATION"]
    for h in kept:
        out.append(f"Q: {str(h.get('question', '')).strip()}")
        out.append(f"A: {str(h.get('answer', '')).strip()}")
    return "\n".join(out) + "\n\n"


def cap_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    mark = _TRUNCATION_MARK.format(shown=max_chars, total=len(text))
    return text[:max_chars] + mark, True


def render_steps(steps: Sequence[dict[str, Any]], spec: AskSpec) -> str:
    if not steps:
        return "(none yet)"
    out = []
    for i, s in enumerate(steps, 1):
        out.append(f"Step {i}: {s['tool']}({json.dumps(s['args'], ensure_ascii=False)})")
        out.append("Result: " + s["result_text"])
    return "\n".join(out)


def build_prompt(
    spec: AskSpec,
    *,
    facts: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    question: str,
    steps: Sequence[dict[str, Any]],
    note: str = "",
) -> str:
    prompt = spec.prompt_template.format(
        tools=render_tools(spec),
        facts=json.dumps(facts, ensure_ascii=False, default=str),
        history=render_history(history, spec),
        question=question.strip(),
        steps=render_steps(steps, spec),
    )
    return prompt + ("\n\n" + note if note else "")


def result_summary(result: Mapping[str, Any]) -> str:
    """One phrase for the step line: "20 sessions", "turns 1–30 of 120",
    "error: session 9 not found"."""
    if "error" in result:
        return f"error: {result['error']}"
    if "turns_total" in result:
        return f"turns {result['from_turn']}–{result['to_turn']} of {result['turns_total']}"
    if "session_key" in result and "tools" in result:
        return (
            f"#{result['id']}: {result['turns']} turns, {len(result['tools'])} tools, "
            f"{result['errors']} errors"
        )
    for key, value in result.items():
        if isinstance(value, list):
            return f"{len(value)} {key}"
    return "1 result"


# ── the loop ────────────────────────────────────────────────────────────


def ask(
    ctx: T.AskContext,
    judge: TurnJudge,
    question: str,
    history: Sequence[Mapping[str, Any]] = (),
    *,
    spec: Optional[AskSpec] = None,
) -> Iterator[dict[str, Any]]:
    """Answer ``question`` with ``judge`` over the store in ``ctx``,
    yielding one event dict per happening: ``step`` (a tool is about to
    run), ``result`` (what it returned), ``answer``, or ``error``. The
    iterator ends after ``answer`` or ``error``."""
    spec = spec or load_spec()
    facts = T.store_facts(ctx)
    steps: list[dict[str, Any]] = []
    # Every session id a lookup returned. An answer may cite only these:
    # a citation is evidence-backed or it is not a citation.
    evidence: list[int] = []
    note = ""
    calls = 0
    while True:
        forced = calls >= spec.max_steps
        if forced:
            note = spec.force_answer_note
        prompt = build_prompt(spec, facts=facts, history=history, question=question, steps=steps, note=note)
        started = time.time()
        try:
            text = judge.complete(prompt, timeout=spec.step_timeout_seconds)
        except JudgeAnswerTruncated as exc:
            yield _error(f"the judge's reply was cut off at its answer cap: {exc}")
            return
        except JudgeTransportError as exc:
            yield _error(f"the judge did not answer: {exc}")
            return
        except (ValueError, RuntimeError) as exc:
            # MissingBaseUrlError / ClaudeCliNotFoundError: a Settings gap.
            yield _error(str(exc), prerequisite="judge")
            return
        seconds = round(time.time() - started, 1)
        obj = extract_json_object(text)
        action = _classify(obj)
        if action is None:
            if note == spec.bad_json_note or forced:
                yield _error(
                    "the judge did not return a JSON action; it said: "
                    + (text or "").strip()[:_ERROR_HEAD_CHARS]
                )
                return
            note = spec.bad_json_note
            continue
        note = ""
        if action == EVENT_ANSWER:
            cited = _session_ids(obj.get("sessions"))
            yield {
                "event": EVENT_ANSWER,
                "markdown": str(obj.get("answer") or "").strip(),
                # Verified: the model named it AND a lookup returned it.
                "sessions": [i for i in cited if i in evidence],
                # Named by the model but never seen in a result — shown
                # as unverified, never linked as a session.
                "unverified": [i for i in cited if i not in evidence],
                "evidence": list(evidence),
                "seconds": seconds,
                "steps": calls,
            }
            return
        if forced:
            yield _error(f"no answer after {spec.max_steps} lookups; the judge kept asking for more.")
            return
        # A tool call.
        calls += 1
        name = str(obj.get("tool") or "")
        args = obj.get("args") if isinstance(obj.get("args"), Mapping) else {}
        yield {
            "event": EVENT_STEP, "n": calls, "tool": name, "args": dict(args),
            "why": str(obj.get("why") or "").strip(), "seconds": seconds,
        }
        started = time.time()
        result, error = _run(ctx, spec, name, args)
        raw = json.dumps(result, ensure_ascii=False, default=str)
        shown, truncated = cap_text(raw, spec.max_result_chars)
        steps.append({"tool": name, "args": dict(args), "result_text": shown})
        ids = _ids_in(result)
        for i in ids:
            if i not in evidence:
                evidence.append(i)
        yield {
            "event": EVENT_RESULT, "n": calls, "summary": result_summary(result),
            "chars": len(raw), "truncated": truncated, "error": error,
            "session_ids": ids,
            # EXACTLY what the judge was given for this step, so the page
            # can show the rows behind the answer, not a count of them.
            "result_text": shown,
            "seconds": round(time.time() - started, 2),
        }


def _classify(obj: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not isinstance(obj, Mapping):
        return None
    if "answer" in obj:
        return EVENT_ANSWER
    if obj.get("tool"):
        return EVENT_STEP
    return None


def _run(
    ctx: T.AskContext, spec: AskSpec, name: str, args: Mapping[str, Any]
) -> tuple[dict[str, Any], Optional[str]]:
    """Run one tool; a refused or failing call is a result the model
    reads ({"error": ...}), so it can correct itself on the next step."""
    declared = spec.declared_args(name)
    if declared is None:
        msg = f"unknown tool {name!r}; one of: {', '.join(t['name'] for t in spec.tools)}"
        return {"error": msg}, msg
    try:
        return T.call_tool(ctx, name, args, declared=declared), None
    except (T.UnknownToolError, T.BadArgumentsError) as exc:
        return {"error": str(exc)}, str(exc)
    except Exception as exc:  # noqa: BLE001 — a tool failure is a step result, not a crash
        _log.exception("ask tool %s failed", name)
        msg = f"{name} failed: {type(exc).__name__}: {exc}"[:_ERROR_HEAD_CHARS]
        return {"error": msg}, msg


def _error(message: str, *, prerequisite: Optional[str] = None) -> dict[str, Any]:
    ev: dict[str, Any] = {"event": EVENT_ERROR, "error": message}
    if prerequisite:
        ev["prerequisite"] = prerequisite
    return ev


def _session_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for v in value:
        try:
            n = int(str(v).lstrip("#"))
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out


def _ids_in(result: Mapping[str, Any]) -> list[int]:
    """Session ids a tool result names — the evidence set an answer may
    cite from. Relational rows carry ``id``/``session_id``; a graph
    Session node carries the ``session_id`` graph_question resolved."""
    ids: list[int] = []

    def add(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, int) and v > 0 and v not in ids:
            ids.append(v)

    if "error" in result:
        return ids
    if "session_id" in result:
        add(result["session_id"])
    if "id" in result and "session_key" in result:
        add(result["id"])
    for key in ("sessions", "hits", "neighbors", "nodes"):
        for row in result.get(key) or []:
            if isinstance(row, Mapping):
                add(row.get("id") if key in ("sessions", "neighbors") else row.get("session_id"))
    return ids
