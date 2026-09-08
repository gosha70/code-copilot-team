# Tests for Ask — the question loop and its read-only tools. No real LLM:
# a scripted judge returns the JSON actions a model would.

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.ask import loop as L
from session_analytics.ask import tools as T
from session_analytics.config import ENV_NOISE_MIN_DURATION
from session_analytics.ingest.pipeline import ingest
from session_analytics.judge.contracts import JudgeTransportError
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class _ScriptedJudge:
    """Answers each `complete` with the next scripted text; records prompts."""

    judge_id = "fake"
    _model = "fake-1"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def rate_turn(self, ctx, rubric):  # pragma: no cover — protocol only
        raise NotImplementedError

    def complete(self, prompt: str, *, timeout: int = 120) -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("judge asked more times than scripted")
        return self.replies.pop(0)


def _call(tool: str, **args) -> str:
    return json.dumps({"tool": tool, "args": args, "why": "test"})


def _answer(text: str, sessions=()) -> str:
    return json.dumps({"answer": text, "sessions": list(sessions)})


class _AskBase(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        patcher = mock.patch.dict("os.environ", {ENV_NOISE_MIN_DURATION: "0"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        apply_ddl(self.db)
        self.session_id = int(self.db.query_one("SELECT id FROM copilot_session")[0])
        # An absent graph path: the graph tools must say so, not raise.
        self.ctx = T.AskContext(db=self.db, kuzu_path=str(Path(tempfile.mkdtemp()) / "absent"), noise=None)

    def tearDown(self) -> None:
        self.db.close()


class TestAskTools(_AskBase):
    def test_find_sessions_lists_the_fixture(self) -> None:
        out = T.find_sessions(self.ctx, {})
        self.assertEqual(out["count"], 1)
        row = out["sessions"][0]
        self.assertEqual(row["id"], self.session_id)
        self.assertEqual(row["copilot"], C.COPILOT_CLAUDE_CODE)
        self.assertIn("turns", row)
        self.assertEqual(set(row["tags"]), {"favorite", "todo", "analyzed"})

    def test_find_sessions_tag_filter_and_bad_sort(self) -> None:
        self.assertEqual(T.find_sessions(self.ctx, {"tag": "favorite"})["count"], 0)
        with self.assertRaises(T.BadArgumentsError):
            T.find_sessions(self.ctx, {"tag": "starred"})
        with self.assertRaises(T.BadArgumentsError):
            T.find_sessions(self.ctx, {"sort": "id; DROP TABLE"})

    def test_session_summary_has_tools_errors_and_analysis_status(self) -> None:
        out = T.session_summary(self.ctx, {"session_id": self.session_id})
        self.assertEqual(out["id"], self.session_id)
        self.assertIsInstance(out["tools"], list)
        self.assertIsInstance(out["errors"], int)
        self.assertIsInstance(out["error_samples"], list)
        self.assertRegex(L.result_summary(out), r"^#\d+: \d+ turns, \d+ tools, \d+ errors$")
        self.assertEqual(set(out["analyses"]), set(C.ANALYSIS_KINDS))
        self.assertEqual(out["analyses"][C.ANALYSIS_KIND_TUNING], "not run")
        self.assertEqual(T.session_summary(self.ctx, {"session_id": 999})["error"], "session 999 not found")

    def test_session_turns_window_and_paging(self) -> None:
        out = T.session_turns(self.ctx, {"session_id": self.session_id, "from_turn": 1, "count": 2})
        self.assertEqual(out["from_turn"], 1)
        self.assertLessEqual(out["to_turn"], 2)
        self.assertIn("#1 ", out["text"])
        self.assertEqual(out["text_source"], C.TRANSCRIPT_SOURCE_PREVIEW)
        self.assertEqual(out["more"], out["turns_total"] > 2)
        with self.assertRaises(T.BadArgumentsError):
            T.session_turns(self.ctx, {"session_id": "abc"})

    def test_search_text_finds_previews_without_any_archive(self) -> None:
        preview = self.db.query_one(
            "SELECT content_preview FROM copilot_turn WHERE content_preview <> '' ORDER BY sequence_num"
        )[0]
        word = next(w for w in str(preview).split() if len(w) > 3)
        out = T.search_text(self.ctx, {"query": word})
        self.assertGreaterEqual(out["count"], 1)
        hit = out["hits"][0]
        self.assertEqual(hit["source"], "preview")
        self.assertEqual(hit["session_id"], self.session_id)
        self.assertIn(word.lower(), hit["snippet"].lower())
        with self.assertRaises(T.BadArgumentsError):
            T.search_text(self.ctx, {})

    def test_patterns_and_overview(self) -> None:
        self.assertIn("tools", T.patterns(self.ctx, {}))
        out = T.overview(self.ctx, {})
        self.assertEqual(out["totals"]["sessions"], 1)

    def test_session_analyses_reports_not_run(self) -> None:
        out = T.session_analyses(self.ctx, {"session_id": self.session_id})
        self.assertEqual(out[C.ANALYSIS_KIND_COACHING]["status"], "not run")

    def test_graph_tools_without_a_graph_say_so(self) -> None:
        out = T.graph_question(self.ctx, {"id": "tools-failing-most", "params": {}})
        self.assertEqual(out["prerequisite"], "graph")
        out = T.similar_sessions(self.ctx, {"session_id": self.session_id})
        self.assertIn("prerequisite", out)
        self.assertFalse(Path(self.ctx.kuzu_path).exists(), "a read must not create the store")

    def test_call_tool_rejects_unknown_tool_and_argument(self) -> None:
        spec = L.load_spec()
        with self.assertRaises(T.UnknownToolError):
            T.call_tool(self.ctx, "drop_everything", {}, declared={})
        with self.assertRaises(T.BadArgumentsError) as cm:
            T.call_tool(self.ctx, "find_sessions", {"where": "1=1"}, declared=spec.declared_args("find_sessions"))
        self.assertIn("does not take where", str(cm.exception))

    def test_every_spec_tool_is_bound(self) -> None:
        spec = L.load_spec()
        self.assertEqual({t["name"] for t in spec.tools}, set(T.TOOLS))

    def test_store_facts(self) -> None:
        facts = T.store_facts(self.ctx)
        self.assertEqual(facts["sessions"], 1)
        self.assertEqual(facts["sessions_with_archived_text"], 0)
        self.assertFalse(facts["graph_built"])
        self.assertTrue(any(q["id"] == "tools-failing-most" for q in facts["graph_questions"]))


class TestAskLoop(_AskBase):
    def _events(self, judge, question="what happened?", history=(), spec=None):
        return list(L.ask(self.ctx, judge, question, history, spec=spec))

    def test_call_then_answer(self) -> None:
        judge = _ScriptedJudge(
            _call("find_sessions", limit=5),
            _answer("One session: #%d." % self.session_id, [self.session_id, "#7", "x"]),
        )
        ev = self._events(judge)
        self.assertEqual([e["event"] for e in ev], ["step", "result", "answer"])
        self.assertEqual(ev[0]["tool"], "find_sessions")
        self.assertEqual(ev[0]["args"], {"limit": 5})
        self.assertEqual(ev[1]["summary"], "1 sessions")
        self.assertEqual(ev[1]["session_ids"], [self.session_id])
        self.assertFalse(ev[1]["truncated"])
        self.assertEqual(ev[2]["sessions"], [self.session_id, 7])
        self.assertEqual(ev[2]["steps"], 1)
        # The second prompt carried the first step's result.
        self.assertIn("Step 1: find_sessions", judge.prompts[1])
        self.assertIn('"count": 1', judge.prompts[1])

    def test_unknown_tool_is_fed_back_not_raised(self) -> None:
        judge = _ScriptedJudge(_call("delete_sessions"), _answer("cannot"))
        ev = self._events(judge)
        self.assertEqual(ev[1]["event"], "result")
        self.assertIn("unknown tool", ev[1]["error"])
        self.assertIn("unknown tool 'delete_sessions'", judge.prompts[1])
        self.assertEqual(ev[2]["event"], "answer")

    def test_bad_arguments_are_fed_back(self) -> None:
        judge = _ScriptedJudge(_call("session_turns", session_id="nope"), _answer("ok"))
        ev = self._events(judge)
        self.assertIn("must be an integer", ev[1]["error"])

    def test_bad_json_is_nudged_once_then_an_error(self) -> None:
        judge = _ScriptedJudge("I think you want sessions.", _answer("fine"))
        ev = self._events(judge)
        self.assertEqual(ev[-1]["event"], "answer")
        self.assertIn(L.load_spec().bad_json_note, judge.prompts[1])
        judge = _ScriptedJudge("no json", "still no json")
        ev = self._events(judge)
        self.assertEqual(ev[-1]["event"], "error")
        self.assertIn("still no json", ev[-1]["error"])

    def test_step_cap_forces_an_answer(self) -> None:
        spec = L.load_spec()
        small = L.AskSpec(**{**spec.__dict__, "max_steps": 2})
        judge = _ScriptedJudge(
            _call("overview"), _call("overview"), _call("overview"),  # third is refused
        )
        ev = self._events(judge, spec=small)
        self.assertEqual(ev[-1]["event"], "error")
        self.assertIn("no answer after 2 lookups", ev[-1]["error"])
        self.assertIn(spec.force_answer_note, judge.prompts[-1])
        judge = _ScriptedJudge(_call("overview"), _call("overview"), _answer("forced"))
        ev = self._events(judge, spec=small)
        self.assertEqual(ev[-1]["markdown"], "forced")

    def test_result_cap_truncates_with_a_marker(self) -> None:
        spec = L.load_spec()
        tiny = L.AskSpec(**{**spec.__dict__, "max_result_chars": 80})
        judge = _ScriptedJudge(_call("find_sessions"), _answer("x"))
        ev = self._events(judge, spec=tiny)
        self.assertTrue(ev[1]["truncated"])
        self.assertGreater(ev[1]["chars"], 80)
        self.assertIn("truncated: 80 of", judge.prompts[1])

    def test_transport_and_config_errors_end_the_stream(self) -> None:
        class Down(_ScriptedJudge):
            def complete(self, prompt, *, timeout=120):
                raise JudgeTransportError("connection refused")

        ev = self._events(Down())
        self.assertEqual(ev, [{"event": "error", "error": "the judge did not answer: connection refused"}])

        class Unset(_ScriptedJudge):
            def complete(self, prompt, *, timeout=120):
                raise ValueError("the openai judge needs a base URL")

        ev = self._events(Unset())
        self.assertEqual(ev[0]["prerequisite"], "judge")

    def test_history_is_in_the_prompt_and_capped(self) -> None:
        spec = L.load_spec()
        history = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(spec.max_history + 3)]
        judge = _ScriptedJudge(_answer("hi"))
        self._events(judge, history=history)
        self.assertIn("EARLIER IN THIS CONVERSATION", judge.prompts[0])
        self.assertNotIn("Q: q0", judge.prompts[0])
        self.assertIn(f"Q: q{spec.max_history + 2}", judge.prompts[0])

    def test_pure_helpers(self) -> None:
        self.assertEqual(L.result_summary({"error": "x"}), "error: x")
        self.assertEqual(L.result_summary({"hits": [1, 2], "count": 2}), "2 hits")
        self.assertEqual(L.result_summary({"turns_total": 9, "from_turn": 1, "to_turn": 3}), "turns 1–3 of 9")
        self.assertEqual(L.cap_text("abc", 3), ("abc", False))
        self.assertEqual(L.render_history([], L.load_spec()), "")
