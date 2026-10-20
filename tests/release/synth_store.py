# Copyright (c) 2026 Gosha - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.

"""Synthesize a transcript tree big enough to exercise the release claims.

The packaged fixture is one 6-turn session, which cannot exercise what
v2.0.0 actually claims: a list that pages at 50, a timeline that windows
at 100, lineage proven by shared turn identifiers. This writes real
Claude Code transcripts — the same format ingest parses in production —
so the checks run through the real ingest path rather than INSERTing
rows behind it.

What it produces, and why each number:

  * 66 sessions, so the list pages (50 per page) and the last page is
    partial. A partial last page is where an off-by-one shows.
  * sessions in groups of eight sharing one start time, so every page
    boundary falls inside a tie. Without a total ordering a tie lets a
    row appear on two pages or on none, which is what the id tie-break
    added in #383 exists to prevent — and what a fixture with distinct
    timestamps can never exercise.
  * one session far past the 100-turn timeline window, so windowing is
    exercised with a partial last page for the same reason.
  * tool calls with and without results, so the trace tree has both.
  * a pair that shares uuids but falls below the 0.5 containment
    threshold, so the documented refusal is asserted rather than assumed.
  * two resumed pairs sharing turn uuids: one that keeps the
    predecessor's sessionId on the carried records and one that rewrites
    it to the new session. Both occur in real transcripts — a scan of
    122 of them found 723 carried records of the first kind and 22 of
    the second — and lineage keys on the turn uuid precisely so that it
    holds either way. A fixture carrying only one form proves only half
    the claim.
  * every session over the noise floor, plus two deliberate probe
    sessions, so the excluded count is a known number and not zero.

Usage:  python3 tests/release/synth_store.py <transcript-root>
Prints the shape it wrote as JSON, which the checks assert against.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

# The shape the API checks assert against. Changing a number here is a
# change to what the checks mean, so they read it from the output rather
# than restating it.
REAL_SESSIONS = 66
PROBE_SESSIONS = 2
BIG_SESSION_TURNS = 260
# How many sessions share one start time, so a page boundary always
# lands inside a tie.
SESSIONS_PER_TIMESTAMP = 8
MODELS = ["claude-opus-5", "claude-fable-5-1", "claude-opus-4-8"]
PROJECTS = ["/repo/alpha", "/repo/beta", "/repo/gamma"]
BASE = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)


def _ts(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _turn(kind: str, session: str, uuid: str, parent: str | None, moment: datetime,
          text: str, cwd: str, tools: list[dict] | None = None) -> dict:
    """One transcript record. `tools` attaches tool_use blocks to an
    assistant turn; a block with no `result` is a call whose result was
    never recorded, which the trace tree must show as such rather than
    as a failure."""
    content: list[dict] = [{"type": "text", "text": text}]
    for tool in tools or []:
        content.append({
            "type": "tool_use",
            "id": tool["id"],
            "name": tool["name"],
            "input": tool.get("input", {}),
        })
    record = {
        "type": kind,
        "sessionId": session,
        "cwd": cwd,
        "gitBranch": "main",
        "parentUuid": parent,
        "isSidechain": False,
        "uuid": uuid,
        "timestamp": _ts(moment),
        "message": {"role": kind, "content": content},
        "version": "2.1.0",
    }
    if kind == "assistant":
        record["message"]["model"] = "claude-opus-5"
        record["message"]["usage"] = {"input_tokens": 120, "output_tokens": 240}
    return record


def _results(session: str, uuid: str, parent: str, moment: datetime,
             cwd: str, tools: list[dict]) -> list[dict]:
    """The user-side records carrying tool results. A tool whose dict has
    no `result` key is deliberately left without one."""
    blocks = [
        {
            "type": "tool_result",
            "tool_use_id": tool["id"],
            "content": tool["result"],
            "is_error": tool.get("is_error", False),
        }
        for tool in tools if "result" in tool
    ]
    if not blocks:
        return []
    return [{
        "type": "user",
        "sessionId": session,
        "cwd": cwd,
        "gitBranch": "main",
        "parentUuid": parent,
        "isSidechain": False,
        "uuid": uuid,
        "timestamp": _ts(moment),
        "message": {"role": "user", "content": blocks},
        "version": "2.1.0",
    }]


def _session(session_id: str, project: str, model: str, start: datetime,
             turn_pairs: int, uuid_prefix: str,
             carry: list[dict] | None = None,
             rewrite_carried_session_id: bool = False) -> list[dict]:
    """One transcript. `carry` is a prefix of records from an earlier
    session, reproduced with their original uuids — which is what a real
    resume does, and the only evidence lineage is allowed to use.

    Real transcripts do both things with the carried records' sessionId:
    some keep the predecessor's, some rewrite it to the new session.
    `rewrite_carried_session_id` selects which, so both are generated."""
    cwd = project
    records: list[dict] = [{
        "type": "system", "subtype": "init", "sessionId": session_id,
        "model": model, "cwd": cwd, "gitBranch": "main",
        "uuid": f"{uuid_prefix}-init", "timestamp": _ts(start),
    }]
    for carried in (carry or []):
        record = dict(carried)
        if rewrite_carried_session_id:
            record["sessionId"] = session_id
        records.append(record)
    moment = start + timedelta(seconds=30 * len(carry or []))
    parent = (carry or [{}])[-1].get("uuid") if carry else None
    for i in range(turn_pairs):
        moment += timedelta(seconds=45)
        user_uuid = f"{uuid_prefix}-u{i}"
        records.append(_turn("user", session_id, user_uuid, parent, moment,
                             f"Request {i}: change the thing.", cwd))
        parent = user_uuid
        moment += timedelta(seconds=12)
        assistant_uuid = f"{uuid_prefix}-a{i}"
        # Every third assistant turn calls tools; one of those calls never
        # gets a result, and one fails.
        tools: list[dict] = []
        if i % 3 == 0:
            tools = [
                {"id": f"{uuid_prefix}-t{i}a", "name": "Read",
                 "input": {"file_path": f"{project}/src/mod{i}.py"},
                 "result": "ok, 40 lines"},
                {"id": f"{uuid_prefix}-t{i}b", "name": "Bash",
                 "input": {"command": "pytest -q"}},
            ]
            if i % 6 == 0:
                tools.append({"id": f"{uuid_prefix}-t{i}c", "name": "Edit",
                              "input": {"file_path": "x.py"},
                              "result": "error: file not found", "is_error": True})
        records.append(_turn("assistant", session_id, assistant_uuid, parent,
                             moment, f"Done with {i}.", cwd, tools))
        parent = assistant_uuid
        if tools:
            moment += timedelta(seconds=6)
            result_uuid = f"{uuid_prefix}-r{i}"
            extra = _results(session_id, result_uuid, parent, moment, cwd, tools)
            if extra:
                records.extend(extra)
                parent = result_uuid
    return records


def build(root: pathlib.Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    # `listable` is what the Sessions list must total: the real sessions
    # plus the resumed one, with the probes excluded as noise.
    shape: dict = {"listable": REAL_SESSIONS + 3, "excluded": PROBE_SESSIONS,
                   "big_session_turns": 0, "big_session_id": "",
                   "resumed_child": "", "resumed_parent": ""}

    for n in range(REAL_SESSIONS):
        project = PROJECTS[n % len(PROJECTS)]
        model = MODELS[n % len(MODELS)]
        # Eight per timestamp: see the module docstring. The tie is the
        # point, not an accident of generation.
        start = BASE + timedelta(hours=6 * (n // SESSIONS_PER_TIMESTAMP))
        # One session is large enough that the timeline must window.
        pairs = BIG_SESSION_TURNS // 2 if n == 0 else 4 + (n % 7)
        session_id = f"sess-{n:03d}"
        folder = root / project.strip("/").replace("/", "-")
        folder.mkdir(parents=True, exist_ok=True)
        records = _session(session_id, project, model, start, pairs, f"x{n:03d}")
        (folder / f"{session_id}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        if n == 0:
            shape["big_session_id"] = session_id
            # Recorded for reference only. Ingest also stores the
            # tool-result records as turns, so the stored count is higher
            # than this; checks must not treat it as the stored count.
            shape["exchanges_written"] = pairs * 2

    # A resume: session 900 reproduces the first six records of sess-001
    # with their original uuids, then continues. That shared-uuid prefix
    # is the whole evidence base for lineage.
    parent_file = root / "repo-beta" / "sess-001.jsonl"
    parent_records = [json.loads(line) for line in
                      parent_file.read_text(encoding="utf-8").splitlines()]
    carry = [r for r in parent_records if r.get("type") in ("user", "assistant")][:6]
    resumed = _session("sess-900", PROJECTS[1], MODELS[0],
                       BASE + timedelta(days=20), 5, "x900", carry=carry)
    (root / "repo-beta" / "sess-900.jsonl").write_text(
        "\n".join(json.dumps(r) for r in resumed) + "\n", encoding="utf-8")
    shape["resumed_child"] = "sess-900"
    shape["resumed_parent"] = "sess-001"

    # The other real form: same uuids, sessionId rewritten to the new
    # session. Lineage must find this one too, from the uuids alone.
    parent2 = root / "repo-gamma" / "sess-002.jsonl"
    parent2_records = [json.loads(line) for line in
                       parent2.read_text(encoding="utf-8").splitlines()]
    # Ten, not six. The rule is `containment-net-growth-v1`: a pair is a
    # lineage edge only when at least 2 uuids are shared AND
    # max(s/|A|, s/|B|) >= 0.5. Six records out of this parent scores
    # 0.429 and is correctly declined — a threshold test, not a resume
    # test, so that case is made deliberately below instead.
    carry2 = [r for r in parent2_records if r.get("type") in ("user", "assistant")][:10]
    rewritten = _session("sess-901", PROJECTS[2], MODELS[0],
                         BASE + timedelta(days=21), 5, "x901", carry=carry2,
                         rewrite_carried_session_id=True)
    (root / "repo-gamma" / "sess-901.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rewritten) + "\n", encoding="utf-8")
    shape["resumed_child_rewritten"] = "sess-901"
    shape["resumed_parent_rewritten"] = "sess-002"

    # Below the threshold on purpose. A short continuation of a long
    # predecessor shares real uuids but does not clear
    # max(s/|A|, s/|B|) >= 0.5, and the ruling is that such a pair is NOT
    # presented as lineage. Asserting the refusal keeps the threshold
    # honest: without it, lowering T would break nothing.
    parent3 = root / "repo-alpha" / "sess-003.jsonl"
    parent3_records = [json.loads(line) for line in
                       parent3.read_text(encoding="utf-8").splitlines()]
    carry3 = [r for r in parent3_records if r.get("type") in ("user", "assistant")][:2]
    thin = _session("sess-902", PROJECTS[0], MODELS[0],
                    BASE + timedelta(days=22), 12, "x902", carry=carry3)
    (root / "repo-alpha" / "sess-902.jsonl").write_text(
        "\n".join(json.dumps(r) for r in thin) + "\n", encoding="utf-8")
    shape["below_threshold_child"] = "sess-902"

    # Probes: two turns in a temp directory, which the noise rules hide.
    probe_dir = root / "private-var-folders-probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    for n in range(PROBE_SESSIONS):
        session_id = f"probe-{n}"
        records = _session(session_id, "/private/var/folders/zz/cct-probe",
                           MODELS[0], BASE + timedelta(days=30 + n), 1, f"p{n}")
        (probe_dir / f"{session_id}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    return shape


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: synth_store.py <transcript-root>", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(build(pathlib.Path(sys.argv[1])), indent=2))
