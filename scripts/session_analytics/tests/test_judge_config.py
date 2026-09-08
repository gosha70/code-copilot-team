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


def _parse(path: Path) -> dict[str, str]:
    """parse_env_file bound to one file, for patching the loader's reader."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def _judge(override=None, by_copilot=None, default=("claude-code", "")):
    return JudgeConfig(
        override=override, by_copilot=by_copilot or {}, default=default,
        workers=1, ollama_url="", base_url="", api_key="",
    )


class TestEnvFileIO(unittest.TestCase):
    def test_legacy_db_key_is_read_and_rewritten(self) -> None:
        # A .env from before the rename names the store CCT_SA_DSN: it is
        # still honoured, and the next write folds it into CCT_SA_DB —
        # never both keys in one file.
        d = Path(tempfile.mkdtemp())
        env = d / ".env"
        env.write_text("CCT_SA_DSN=sqlite:////old.db\n", encoding="utf-8")
        parsed = cfgmod.parse_env_file(env)
        self.assertEqual(parsed[cfgmod.ENV_DSN_LEGACY], "sqlite:////old.db")
        cfgmod.write_env_file({cfgmod.ENV_REDACTION: "code"}, env)
        text = env.read_text(encoding="utf-8")
        self.assertIn("CCT_SA_DB=sqlite:////old.db", text)
        self.assertNotIn("CCT_SA_DSN", text)

    def test_database_aliases_resolve_within_each_layer(self) -> None:
        # A process-level CCT_SA_DSN beats a .env CCT_SA_DB: the two names
        # are aliases inside a layer, and the process layer wins.
        import os
        from unittest import mock

        d = Path(tempfile.mkdtemp())
        env = d / ".env"
        env.write_text("CCT_SA_DB=sqlite:////file.db\n", encoding="utf-8")
        base = {k: v for k, v in os.environ.items() if not k.startswith("CCT_SA_")}
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: _parse(env)), \
             mock.patch.dict("os.environ", {**base, "CCT_SA_DSN": "sqlite:////process.db"}, clear=True):
            self.assertEqual(cfgmod.load_config().dsn, "sqlite:////process.db")
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: _parse(env)), \
             mock.patch.dict("os.environ", base, clear=True):
            self.assertEqual(cfgmod.load_config().dsn, "sqlite:////file.db")

    def test_kuzu_path_directory_resolves_to_store_file_inside_it(self) -> None:
        # CCT_SA_KUZU_PATH=~/.cct (a directory) crashed the graph step
        # with Kùzu's "Database path cannot be a directory". A directory
        # now means "keep the store in here"; a file path is used as is.
        import os
        from unittest import mock

        d = Path(tempfile.mkdtemp())
        base = {k: v for k, v in os.environ.items() if not k.startswith("CCT_SA_")}
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {**base, cfgmod.ENV_KUZU_PATH: str(d)}, clear=True):
            self.assertEqual(cfgmod.load_config().kuzu_path, str(d / C.KUZU_STORE_NAME))
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", base, clear=True):
            self.assertEqual(
                cfgmod.load_config(kuzu_path=str(d / "graph.kz")).kuzu_path,
                str(d / "graph.kz"),
            )

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
        env.write_text('# a comment\nCCT_SA_DB="sqlite:////q.db"\n\n', encoding="utf-8")
        self.assertEqual(cfgmod.parse_env_file(env)[cfgmod.ENV_DSN], "sqlite:////q.db")


class TestJudgeResolution(unittest.TestCase):
    def test_default_is_copilot_native(self) -> None:
        j = _judge(by_copilot={"claude-code": ("claude-code", "")})
        # Claude Code → its own LLM (empty model = Claude Code default / Opus 4.8)
        self.assertEqual(j.resolve("claude-code"), ("claude-code", ""))
        self.assertEqual(j.backend, "claude-code")

    def test_model_alone_overrides_for_the_default_backend(self) -> None:
        # Settings: Backend left at "Packaged default", Model chosen and
        # saved. The model used to be read only beside an explicit
        # backend, so the choice resolved to ('ollama', '') — ignored.
        import os
        from unittest import mock

        base = {k: v for k, v in os.environ.items() if not k.startswith("CCT_SA_")}
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {**base, cfgmod.ENV_JUDGE_MODEL: "qwen3.6:27b"}, clear=True):
            j = cfgmod.load_config().judge
            self.assertEqual(j.resolve("claude-code"), (j.default[0], "qwen3.6:27b"))
            self.assertEqual(j.resolve(None), (j.default[0], "qwen3.6:27b"))
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", base, clear=True):
            self.assertIsNone(cfgmod.load_config().judge.override)

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

        raw = '{"choices":[{"message":{"content":"{\\"response_helpful\\": true}"},"finish_reason":"stop"}]}'
        self.assertEqual(
            openai_judge._extract_content(raw), ('{"response_helpful": true}', "stop")
        )
        self.assertEqual(openai_judge._extract_content("not json"), ("not json", None))

    def test_base_url_gets_v1_and_the_owners_bare_host_port_works(self) -> None:
        # The owner's first attempt was the bare host:port; every call then
        # went to /chat/completions and 404'd, reported as "not reachable".
        from session_analytics.judge.openai_judge import OpenAICompatJudge, normalize_base_url

        self.assertEqual(normalize_base_url("http://192.168.1.23:8001"), "http://192.168.1.23:8001/v1")
        self.assertEqual(normalize_base_url("http://h:8001/v1/"), "http://h:8001/v1")
        # …and the full endpoint pasted from a working curl (the owner's .env).
        self.assertEqual(
            normalize_base_url("http://192.168.1.23:8001/v1/chat/completions"), "http://192.168.1.23:8001/v1"
        )
        self.assertEqual(normalize_base_url("http://h:8001/chat/completions"), "http://h:8001/v1")
        self.assertEqual(normalize_base_url("http://h/api/v2"), "http://h/api/v2")
        self.assertEqual(normalize_base_url(""), "")
        j = OpenAICompatJudge("m", base_url="http://spark:8001", api_key="")
        self.assertEqual(j._base_url, "http://spark:8001/v1")

    def test_thinking_is_disabled_and_a_server_that_rejects_the_field_is_asked_again(self) -> None:
        # Qwen3 thinking spends the answer budget on reasoning; the request
        # carries chat_template_kwargs.enable_thinking=false (what the
        # owner's working curl sends). A server that 400s on the unknown
        # field gets the same request without it.
        import io
        import urllib.error

        from session_analytics.judge import openai_judge

        j = openai_judge.OpenAICompatJudge("m", base_url="http://x", api_key="")
        seen = []

        def fake_post(path, payload, *, timeout=0):
            seen.append(dict(payload))
            if "chat_template_kwargs" in payload:
                raise urllib.error.HTTPError(
                    "http://x/v1/chat/completions", 400, "Bad Request", {},
                    io.BytesIO(b'{"error":{"message":"Unrecognized request argument: chat_template_kwargs"}}'),
                )
            return '{"choices":[{"message":{"content":"{\\"ok\\": true}"},"finish_reason":"stop"}]}'

        j._post = fake_post  # type: ignore[method-assign]
        self.assertEqual(j.complete("p"), '{"ok": true}')
        self.assertEqual(seen[0]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("chat_template_kwargs", seen[1])
        # Any other HTTP refusal carries the server's reason, not a bare code.
        def refuse(path, payload, *, timeout=0):
            raise urllib.error.HTTPError(
                "http://x/v1/chat/completions", 404, "Not Found", {},
                io.BytesIO(b'{"error":{"message":"The model `nope` does not exist."}}'),
            )
        j._post = refuse  # type: ignore[method-assign]
        with self.assertRaises(openai_judge.JudgeTransportError) as cm:
            j.complete("p")
        self.assertIn("HTTP 404: The model `nope` does not exist.", str(cm.exception))

    def test_missing_base_url_raises(self) -> None:
        from session_analytics.judge import openai_judge

        j = openai_judge.OpenAICompatJudge("m", base_url="", api_key="")
        with self.assertRaises(openai_judge.MissingBaseUrlError):
            j.rate_turn(TurnContext(turn_id=1, role="user", sequence_num=0, text="hi"), load_rubric())

    def test_finish_reason_length_is_a_truncated_answer(self) -> None:
        # A capped answer is the same outcome as Ollama's done_reason=length:
        # named, with the partial text, not handed to the parser as if whole.
        from session_analytics.judge import openai_judge
        from session_analytics.judge.contracts import JudgeAnswerTruncated

        j = openai_judge.OpenAICompatJudge("m", base_url="http://x", api_key="")
        j._post = lambda path, payload, *, timeout=0: (  # type: ignore[method-assign]
            '{"choices":[{"message":{"content":"{\\"summary\\": \\"cut"},'
            '"finish_reason":"length"}]}'
        )
        with self.assertRaises(JudgeAnswerTruncated) as ctx:
            j.complete("p")
        self.assertEqual(ctx.exception.partial, '{"summary": "cut')
        j._post = lambda path, payload, *, timeout=0: (  # type: ignore[method-assign]
            '{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}'
        )
        self.assertEqual(j.complete("p"), "{}")


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
            self.assertEqual(result["claude-code"]["labeled"], 4)   # 4 of 6 turns have text (#313)
            self.assertTrue(result["claude-code"]["judge"].startswith("claude-code:"))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
