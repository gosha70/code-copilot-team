# Tests for the .env config layer + pluggable judge (default = local-only
# Ollama, per-copilot routing, OpenAI-compatible backend).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from session_analytics import config as cfgmod
from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.config import JudgeConfig
from session_analytics.ingest.pipeline import ingest
from session_analytics.judge.contracts import PARSE_OK, Rubric, TurnContext, TurnLabels
from session_analytics.judge.rubric import load_rubric
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


def _judge(override=None, by_copilot=None, default=("claude-code", "")):
    return JudgeConfig(
        override=override, by_copilot=by_copilot or {}, default=default,
        workers=1, ollama_url="", base_url="", api_key="",
    )


class TestEnvFileIO(unittest.TestCase):
    def test_round_trip_and_preserve_unknown(self) -> None:
        d = Path(tempfile.mkdtemp())
        env = d / ".env"
        env.write_text("OTHER_TOOL_KEY=keep-me\n", encoding="utf-8")
        cfgmod.write_env_file({cfgmod.ENV_DSN: "sqlite:////tmp/x.db",
                               cfgmod.ENV_JUDGE_BACKEND: "ollama"}, env)
        parsed = cfgmod.parse_env_file(env)
        self.assertEqual(parsed[cfgmod.ENV_DSN], "sqlite:////tmp/x.db")
        self.assertEqual(parsed[cfgmod.ENV_JUDGE_BACKEND], "ollama")
        self.assertEqual(parsed["OTHER_TOOL_KEY"], "keep-me")  # unrelated key kept

    def test_parse_ignores_comments_and_quotes(self) -> None:
        d = Path(tempfile.mkdtemp())
        env = d / ".env"
        env.write_text('# a comment\nCCT_SA_DSN="sqlite:////q.db"\n\n', encoding="utf-8")
        self.assertEqual(cfgmod.parse_env_file(env)[cfgmod.ENV_DSN], "sqlite:////q.db")


class TestJudgeResolution(unittest.TestCase):
    def test_default_is_copilot_native(self) -> None:
        j = _judge(by_copilot={"claude-code": ("claude-code", "")})
        # Claude Code → its own LLM (empty model = Claude Code default / Opus 4.8)
        self.assertEqual(j.resolve("claude-code"), ("claude-code", ""))
        self.assertEqual(j.backend, "claude-code")

    def test_override_wins_globally(self) -> None:
        j = _judge(override=("ollama", "llama3"),
                   by_copilot={"claude-code": ("claude-code", "")})
        self.assertEqual(j.resolve("claude-code"), ("ollama", "llama3"))
        self.assertEqual(j.resolve("aider"), ("ollama", "llama3"))

    def test_unknown_copilot_falls_back_to_default(self) -> None:
        j = _judge(default=("claude-code", ""), by_copilot={})
        self.assertEqual(j.resolve("whatever"), ("claude-code", ""))

    def test_defaults_json_loads_local_default(self) -> None:
        # Build straight from the packaged defaults (independent of any local .env).
        # Privacy AC: the packaged default judge is local-only Ollama — no session
        # content leaves the machine unless the user explicitly opts in.
        data = cfgmod._read_defaults()["judge"]
        self.assertEqual(data["default"]["backend"], "ollama")
        for copilot, spec in data["by_copilot"].items():
            self.assertEqual(spec["backend"], "ollama", copilot)


class TestOpenAIJudge(unittest.TestCase):
    def test_extract_content(self) -> None:
        from session_analytics.judge import openai_judge

        raw = '{"choices":[{"message":{"content":"{\\"response_helpful\\": true}"}}]}'
        self.assertEqual(openai_judge._extract_content(raw), '{"response_helpful": true}')
        self.assertEqual(openai_judge._extract_content("not json"), "not json")

    def test_missing_base_url_raises(self) -> None:
        from session_analytics.judge import openai_judge

        j = openai_judge.OpenAICompatJudge("m", base_url="", api_key="")
        with self.assertRaises(openai_judge.MissingBaseUrlError):
            j.rate_turn(TurnContext(turn_id=1, role="user", sequence_num=0, text="hi"), load_rubric())


class _FakeJudge:
    judge_id = "fake"

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels:
        return TurnLabels(
            bool_labels={l: False for l in rubric.bool_labels},
            sentiment="NEUTRAL", interaction_quality=4,
            parse_status=PARSE_OK, judge_id="fake", judge_model="fake-1",
        )


class TestPerCopilotRouting(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        # Register a fake judge UNDER the claude-code family so routing resolves
        # to it without needing the real `claude` CLI.
        from session_analytics.judge.registry import register_judge
        register_judge("claude-code", lambda model: _FakeJudge())

    def test_routes_claude_code_turns_to_its_judge(self) -> None:
        import types

        from session_analytics.judge.runner import run_default_by_copilot

        dsn = self.sqlite_dsn()
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        cfg = types.SimpleNamespace(
            judge=_judge(by_copilot={"claude-code": ("claude-code", "")})
        )
        db = Database.connect(dsn)
        try:
            apply_ddl(db)
            result = run_default_by_copilot(db, load_rubric(), cfg)
            self.assertIn("claude-code", result)
            self.assertEqual(result["claude-code"]["labeled"], 6)
            self.assertTrue(result["claude-code"]["judge"].startswith("claude-code:"))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
