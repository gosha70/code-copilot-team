"""Canary secrets on every off-machine path (#457): the shared corpus,
configuration and capture helpers.

The corpus (``fixtures/canary/``) is one Claude Code session and a project
root with ``AGENTS.md`` and ``CLAUDE.md``. A distinct canary sits in every
place session or project content enters Session Analytics; a test that
finds one in a payload names the place that leaked.

The steering files are read from the session's project root, which must
exist on disk, so the transcript is a template rendered into a temp dir.
``CLAUDE.md`` is stored as ``CLAUDE.md.template`` (the repository ignores
every ``CLAUDE.md``) and copied in under its real name.

Each ``capture_*`` function runs one path family over the store and
returns the text it would have sent off the machine, labelled by path.
Nothing touches the network: judges and the embedding provider are fakes
that record what they are given.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional
from unittest import mock

from session_analytics import config as cfgmod
from session_analytics import constants as C
from session_analytics.config import load_config
from session_analytics.judge.contracts import TurnLabels
from session_analytics.relational.db import Database
from session_analytics.tests.support import packaged_config

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "canary"
CANARIES: dict[str, str] = json.loads((FIXTURE / "canaries.json").read_text(encoding="utf-8"))

#: Kept by ``code`` mode by definition (spec FR-004): the only canaries a
#: ``code``-mode payload may carry.
PROSE = frozenset({"user_prose", "assistant_prose", "agents_prose", "claude_prose"})

PROJECT_ID = "canary-project"
HAS_MCP = importlib.util.find_spec("mcp") is not None
HAS_KUZU = importlib.util.find_spec("kuzu") is not None
SESSION_KEY = f"{C.COPILOT_CLAUDE_CODE}:sess-canary-001"

#: Every module that sends session-derived text off the machine, and the
#: canary test that exercises it (spec FR-007). ``test_canary_coverage``
#: fails when a module calls a transport and is missing here.
COVERED_MODULES: dict[str, str] = {
    "judge/runner.py": "test_canary_judge (per-turn judge)",
    "judge/session_analysis.py": "test_canary_judge (session analysis)",
    "ask/loop.py": "test_canary_ask (the Ask prompt is built from store_facts and tool results)",
    "ask/tools.py": "test_canary_ask (every tool in TOOLS, and store_facts)",
    "embedding/runner.py": "test_canary_embedding",
    "mcp/server.py": "test_canary_mcp (every tool and resource)",
}

#: Modules that call a transport but send no session data (spec D3), each
#: with the reason. The backends are the transport itself.
EXEMPT_MODULES: dict[str, str] = {
    "judge/ollama_judge.py": "a judge backend: the transport itself",
    "judge/openai_judge.py": "a judge backend: the transport itself",
    "judge/session_judge.py": "a judge backend: the transport itself",
    "embedding/ollama_embed.py": "the embedding backend: the transport itself (its probe sends the fixed word 'probe')",
    "api/server.py": "the Settings connection tests send fixed strings, never session data",
}


@contextmanager
def corpus(*, git_repo: bool = False) -> Iterator[tuple[Path, Path]]:
    """(source root for the claude-code adapter, project root), rendered
    into a fresh temp dir and removed afterwards. With ``git_repo`` the
    project root is a git checkout, as a real project usually is (#477)."""
    base = Path(tempfile.mkdtemp(prefix="cct-sa-canary-"))
    try:
        project = base / "canaryproj"
        project.mkdir()
        if git_repo:
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        shutil.copy(FIXTURE / "AGENTS.md", project / "AGENTS.md")
        # Stored as a template: the repository's .gitignore ignores every
        # CLAUDE.md, so the fixture could not be committed under that name.
        shutil.copy(FIXTURE / "CLAUDE.md.template", project / "CLAUDE.md")
        source = base / "source" / "canary-hash"
        source.mkdir(parents=True)
        template = (FIXTURE / "session.jsonl.template").read_text(encoding="utf-8")
        (source / "session.jsonl").write_text(
            template.replace("{{PROJECT_ROOT}}", str(project)), encoding="utf-8"
        )
        yield source.parent, project
    finally:
        shutil.rmtree(base, ignore_errors=True)


def config_for(
    project: Path,
    *,
    project_mode: Optional[str] = None,
    global_mode: Optional[str] = None,
    ingest_off: bool = False,
    archive: bool = True,
    by_path: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """A user config keying the corpus project by a ``project_ids`` id, with
    the given per-project mode, global mode, opt-out and trace-archive
    opt-in. ``by_path`` adds a second entry for the same project, keyed by
    its repo root as git reports it (#477)."""
    entry: dict[str, Any] = {C.CFG_PROJECT_TRACE_ARCHIVE: archive}
    if project_mode is not None:
        entry[C.CFG_REDACTION] = project_mode
    if ingest_off:
        entry[C.CFG_PROJECT_INGEST] = C.INGEST_OFF
    data: dict[str, Any] = {
        C.CFG_PROJECTS: {PROJECT_ID: entry},
        C.CFG_PROJECT_IDS: [{C.CFG_PROJECT_ID_MATCH: str(project), C.CFG_PROJECT_ID_ID: PROJECT_ID}],
    }
    if by_path is not None:
        data[C.CFG_PROJECTS][str(project.resolve())] = dict(by_path)
    if global_mode is not None:
        data[C.CFG_REDACTION] = global_mode
    return data


@contextmanager
def user_config(data: dict[str, Any]) -> Iterator[None]:
    """The packaged defaults plus ``data`` as the user's config file, with no
    CCT_SA_* from the real environment."""
    path = Path(tempfile.mkdtemp(prefix="cct-sa-canary-cfg-")) / "session-analytics.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with packaged_config(), mock.patch.object(cfgmod, "_USER_CONFIG", path):
        yield


def ingest_corpus(dsn: str, source: Path, *, archive: bool = True) -> int:
    """Ingest (and, where the project opted in, archive) the corpus under
    the configuration in force. ``archive=False`` runs the ingest alone, as
    `ingest --full` does when `archive` is not run after it. Returns the
    session's row id."""
    from session_analytics import archive as arch
    from session_analytics._register import register_all
    from session_analytics.ingest.pipeline import configured_options, ingest

    register_all()
    cfg = load_config()
    ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=source, full=True, **configured_options(cfg))
    if archive:
        arch.archive(
            dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=source, full=True,
            redaction_mode=cfg.redaction_mode, projects=cfg.projects,
            project_id_rules=cfg.project_id_rules,
        )
    db = Database.connect(dsn)
    try:
        row = db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", ("sess-canary-001",))
    finally:
        db.close()
    assert row is not None, "the canary corpus was not ingested"
    return int(row[0])


def leaked(payload: str, mode: str) -> list[str]:
    """The canaries ``mode`` promises to remove that ``payload`` carries."""
    if mode == C.REDACT_NONE:
        return []
    allowed = PROSE if mode == C.REDACT_CODE else frozenset()
    return sorted(name for name, value in CANARIES.items() if name not in allowed and value in payload)


def present(payload: str) -> list[str]:
    """Every canary ``payload`` carries."""
    return sorted(name for name, value in CANARIES.items() if value in payload)


def assert_no_leak(test: Any, captured: dict[str, str], mode: str) -> None:
    """No captured payload carries a canary ``mode`` removes; a failure
    names each path and canary."""
    leaks = {path: leaked(text, mode) for path, text in captured.items()}
    leaks = {path: names for path, names in leaks.items() if names}
    test.assertEqual(leaks, {}, f"canaries leaked under {mode}: {leaks}")


# ── fakes ────────────────────────────────────────────────────────────────


class CapturingJudge:
    """Records every turn context and prompt a judge would send."""

    judge_id = "canary"
    _model = "canary-model"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def rate_turn(self, ctx: Any, rubric: Any) -> TurnLabels:
        self.sent.append(f"{ctx.prev_text}\n{ctx.text}")
        return TurnLabels(
            bool_labels={label: None for label in rubric.bool_labels},
            sentiment=None, interaction_quality=None,
            judge_id=self.judge_id, judge_model=self._model,
        )

    def complete(self, prompt: str, timeout: Any = None) -> str:
        self.sent.append(prompt)
        return "{}"


class CapturingEmbedder:
    """Records every embedding input, then fails the call so nothing is
    stored."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def probe(self) -> None:
        return None

    def embed(self, text: str) -> Any:
        self.sent.append(text)
        raise RuntimeError("canary embedder stores nothing")


# ── capture, per path family ─────────────────────────────────────────────


def capture_judge(dsn: str, session_id: int) -> dict[str, str]:
    """The per-turn judge and session analysis (transcript, steering,
    facts and harness stamp), as their prompts."""
    from session_analytics.judge import session_analysis as sa
    from session_analytics.judge.rubric import load_rubric
    from session_analytics.judge.runner import run_judge

    db = Database.connect(dsn)
    try:
        per_turn = CapturingJudge()
        run_judge(db, per_turn, load_rubric(), overwrite=True)
        analysis = CapturingJudge()
        try:
            sa.analyze_session(db, session_id, C.ANALYSIS_KINDS[0], judge=analysis, force=True)
        except sa.SessionOptedOut:
            pass
    finally:
        db.close()
    return {"per-turn judge": "\n".join(per_turn.sent), "session analysis": "\n".join(analysis.sent)}


def build_graph(dsn: str) -> str:
    """The corpus graph (Kuzu), built the way Studio's graph step builds it
    but with no noise rule: the corpus lives in a temp dir, which the noise
    rule would leave out. Returns its path; empty when Kuzu is missing."""
    if not HAS_KUZU:
        return str(Path(tempfile.mkdtemp()) / "absent")
    from session_analytics.graph.builder import build

    path = str(Path(tempfile.mkdtemp(prefix="cct-sa-canary-graph-")) / "graph")
    db = Database.connect(dsn)
    try:
        build(db, path, rebuild=True, noise=None)
    finally:
        db.close()
    return path


def graph_params(project: str) -> dict[str, dict[str, str]]:
    """Each catalogue query's parameters, pointed at the corpus."""
    from session_analytics.graph import query as gq

    values = {"project": project, "session": SESSION_KEY}
    return {
        q["id"]: {p["name"]: values[p["type"]] for p in q.get("params", [])}
        for q in gq.catalogue()
    }


def capture_ask(dsn: str, session_id: int) -> dict[str, str]:
    """Every Ask tool's result and the store facts, which together are
    everything the Ask loop puts in front of its model. With Kuzu, the
    corpus graph is built and every catalogue query asked of it."""
    from session_analytics.ask import tools as T

    args = {
        "find_sessions": {},
        "session_summary": {"session_id": session_id},
        "session_turns": {"session_id": session_id},
        "session_analyses": {"session_id": session_id},
        "search_text": {"query": "sk-canary"},
        "patterns": {"workspace": "canaryproj"},
        "similar_sessions": {"session_id": session_id},
        "graph_question": {"id": "unknown"},
        "overview": {},
    }
    missing = set(T.TOOLS) - set(args)
    assert not missing, f"Ask tools without a canary call: {sorted(missing)}"
    graph = build_graph(dsn)
    db = Database.connect(dsn)
    try:
        project = db.query_one("SELECT project_path FROM copilot_session WHERE id = ?", (session_id,))[0]
        ctx = T.AskContext(db=db, kuzu_path=graph, noise=None)
        out = {"ask facts": json.dumps(T.store_facts(ctx), default=str)}
        if HAS_KUZU:
            for qid, params in graph_params(project).items():
                result = T.graph_question(ctx, {"id": qid, "params": params})
                out[f"ask graph {qid}"] = json.dumps(result, default=str)
        for name, a in args.items():
            try:
                result: Any = T.TOOLS[name](ctx, a)
            except (T.BadArgumentsError, T.UnknownToolError) as exc:
                result = {"refused": str(exc)}
            out[f"ask {name}"] = json.dumps(result, default=str)
    finally:
        db.close()
        # Each graph is ~10 MB and a suite run builds about fifteen.
        shutil.rmtree(Path(graph).parent, ignore_errors=True)
    return out


def capture_embedding(dsn: str, session_id: int) -> dict[str, str]:
    """What the embedding provider would be sent."""
    from session_analytics.embedding.runner import run_embed

    embedder = CapturingEmbedder()
    db = Database.connect(dsn)
    try:
        with mock.patch("session_analytics.embedding.runner.get_embedding", return_value=embedder):
            run_embed(db, load_config().embedding, overwrite=True)
    finally:
        db.close()
    return {"embedding": "\n".join(embedder.sent)}


def capture_mcp(dsn: str, session_id: int) -> dict[str, str]:
    """Every MCP tool and resource, called through the real server."""
    from session_analytics.mcp.server import build_server

    server = build_server(dsn, kuzu_path=str(Path(tempfile.mkdtemp()) / "absent"))
    calls = {
        "search_sessions": {},
        "list_expectations": {},
        "session_thread": {"session_ref": session_id},
        "compare_harness_versions": {},
        "get_session_details": {"session_id": session_id},
        "analyze_patterns": {"workspace": "canaryproj"},
        "compare_approaches": {"task_description": "canaryproj deploy"},
        "similar_sessions": {"session_id": session_id},
        "session_clusters": {"session_id": session_id},
    }
    registered = {t.name for t in asyncio.run(server.list_tools())}
    missing = registered - set(calls)
    assert not missing, f"MCP tools without a canary call: {sorted(missing)}"
    out: dict[str, str] = {}
    for name, args in calls.items():
        out[f"mcp {name}"] = str(asyncio.run(server.call_tool(name, args)))
    resources = [str(r.uri) for r in asyncio.run(server.list_resources())]
    for uri in resources:
        out[f"mcp {uri}"] = str(asyncio.run(server.read_resource(uri)))
    return out


def capture_all(dsn: str, session_id: int) -> dict[str, str]:
    captured = {}
    captured.update(capture_judge(dsn, session_id))
    captured.update(capture_ask(dsn, session_id))
    captured.update(capture_embedding(dsn, session_id))
    if HAS_MCP:
        captured.update(capture_mcp(dsn, session_id))
    return captured


# ── the per-family test shape ────────────────────────────────────────────


class FamilyCases:
    """Mixin for one path family's canary tests (spec FR-004).

    A subclass sets ``capture`` (one of the ``capture_*`` functions) and
    ``reaches`` ({path label: canaries that path must carry under ``none``}).
    The ``none`` run is the positive control: it proves the capture sees the
    corpus, so an empty payload cannot pass the redacting modes by accident.
    """

    capture: Any = None
    reaches: dict[str, set[str]] = {}

    def run_family(self, mode: str) -> dict[str, str]:
        dsn = self.sqlite_dsn()  # type: ignore[attr-defined]
        with corpus() as (source, project):
            with user_config(config_for(project, project_mode=mode)):
                sid = ingest_corpus(dsn, source)
                return type(self).capture(dsn, sid)

    def test_under_none_the_corpus_reaches_the_path(self) -> None:
        captured = self.run_family(C.REDACT_NONE)
        for path, expected in self.reaches.items():
            with self.subTest(path=path):  # type: ignore[attr-defined]
                missing = expected - set(present(captured[path]))
                self.assertEqual(missing, set(), f"{path} never saw {sorted(missing)}")  # type: ignore[attr-defined]

    def test_code_removes_every_canary_but_prose(self) -> None:
        assert_no_leak(self, self.run_family(C.REDACT_CODE), C.REDACT_CODE)

    def test_metadata_only_removes_every_canary(self) -> None:
        assert_no_leak(self, self.run_family(C.REDACT_METADATA_ONLY), C.REDACT_METADATA_ONLY)
