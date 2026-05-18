# tests/test_bench_envfill.py — env-fill table correctness.
#
# Verifies spec.md § Env-var auto-fill for each provider; mocks HTTP
# probes so no real network contact is made.

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmark_runner.bench import (
    ParsedSpec,
    build_compare_config,
    parse_spec,
    resolve_candidate,
)
from benchmark_runner.compare import load_config


class TestAnthropicEnvFill(unittest.TestCase):
    def test_sonnet_no_env(self) -> None:
        spec = parse_spec("sonnet")
        c = resolve_candidate(spec)
        self.assertEqual(c.backend, "claude-code")
        # Rule 1 (spec.md § Spec-parsing contract): bare alias, not "claude-code:sonnet".
        self.assertEqual(c.model, "sonnet")
        self.assertEqual(c.env, {})
        self.assertTrue(c.is_anthropic)

    def test_opus_no_env(self) -> None:
        spec = parse_spec("opus")
        c = resolve_candidate(spec)
        self.assertEqual(c.env, {})
        self.assertTrue(c.is_anthropic)

    def test_haiku_no_env(self) -> None:
        spec = parse_spec("haiku")
        c = resolve_candidate(spec)
        self.assertEqual(c.env, {})
        self.assertTrue(c.is_anthropic)

    def test_claude_code_explicit(self) -> None:
        spec = parse_spec("claude-code:claude-sonnet-4-6")
        c = resolve_candidate(spec)
        self.assertEqual(c.model, "claude-sonnet-4-6")
        self.assertEqual(c.env, {})
        self.assertTrue(c.is_anthropic)


class TestOllamaEnvFill(unittest.TestCase):
    def test_default_endpoint(self) -> None:
        spec = parse_spec("ollama:qwen2.5-coder:7b")
        c = resolve_candidate(spec)
        self.assertEqual(c.backend, "claude-code")
        self.assertEqual(c.model, "qwen2.5-coder:7b")
        self.assertEqual(c.env["ANTHROPIC_BASE_URL"], "http://localhost:11434")
        self.assertEqual(c.env["ANTHROPIC_AUTH_TOKEN"], "ollama")
        self.assertEqual(c.env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "qwen2.5-coder:7b")
        self.assertEqual(c.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "qwen2.5-coder:7b")
        self.assertFalse(c.is_anthropic)

    def test_custom_endpoint(self) -> None:
        spec = parse_spec("ollama:qwen2.5-coder:7b@http://192.168.1.5:11434")
        c = resolve_candidate(spec)
        self.assertEqual(c.env["ANTHROPIC_BASE_URL"], "http://192.168.1.5:11434")
        self.assertEqual(c.env["ANTHROPIC_AUTH_TOKEN"], "ollama")


class TestLmStudioEnvFill(unittest.TestCase):
    def test_default_endpoint(self) -> None:
        spec = parse_spec("lmstudio:phi-3")
        c = resolve_candidate(spec)
        self.assertEqual(c.env["ANTHROPIC_BASE_URL"], "http://localhost:1234")
        self.assertEqual(c.env["ANTHROPIC_AUTH_TOKEN"], "lmstudio")
        self.assertEqual(c.env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "phi-3")
        self.assertFalse(c.is_anthropic)

    def test_custom_endpoint(self) -> None:
        spec = parse_spec("lmstudio:phi-3@http://localhost:5678")
        c = resolve_candidate(spec)
        self.assertEqual(c.env["ANTHROPIC_BASE_URL"], "http://localhost:5678")


class TestOpenrouterEnvFill(unittest.TestCase):
    def test_reads_api_key_from_env(self) -> None:
        spec = parse_spec("openrouter:meta-llama/llama-3-70b")
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test-1234"}):
            c = resolve_candidate(spec)
        self.assertEqual(c.env["ANTHROPIC_BASE_URL"], "https://openrouter.ai/api/v1")
        self.assertEqual(c.env["ANTHROPIC_AUTH_TOKEN"], "sk-or-test-1234")
        self.assertEqual(c.env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "meta-llama/llama-3-70b")
        self.assertFalse(c.is_anthropic)

    def test_raises_when_api_key_missing(self) -> None:
        spec = parse_spec("openrouter:some-model")
        env_without_key = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        with mock.patch.dict(os.environ, env_without_key, clear=True):
            with self.assertRaises(ValueError) as cm:
                resolve_candidate(spec)
            self.assertIn("OPENROUTER_API_KEY", str(cm.exception))


class TestVllmEnvFill(unittest.TestCase):
    """vLLM probe-then-decide — probes mocked."""

    def _mock_anthropic_proxy_response(self) -> mock.MagicMock:
        """Mock urllib.request.urlopen to return an Anthropic-shape 200."""
        resp = mock.MagicMock()
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)
        resp.status = 200
        resp.read.return_value = b'{"type":"message","id":"msg_test"}'
        return resp

    def _mock_openai_models_response(self, ctx_len: int = 131072) -> mock.MagicMock:
        """Mock urllib.request.urlopen to return an OpenAI /v1/models 200."""
        resp = mock.MagicMock()
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)
        resp.status = 200
        body = json.dumps({
            "data": [{"id": "MyModel", "max_model_len": ctx_len}],
        }).encode()
        resp.read.return_value = body
        return resp

    def test_anthropic_proxy_path(self) -> None:
        """Endpoint answers /v1/messages → use directly as user proxy."""
        from benchmark_runner.bench import resolve_vllm_candidate
        spec = ParsedSpec(provider="vllm", model="MyModel",
                          endpoint="http://127.0.0.1:8787")
        resp = self._mock_anthropic_proxy_response()
        with mock.patch("urllib.request.urlopen", return_value=resp):
            c = resolve_vllm_candidate(spec)
        self.assertEqual(c.env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8787")
        self.assertEqual(c.env["ANTHROPIC_AUTH_TOKEN"], "vllm-user-proxy")
        self.assertIsNone(c.vllm_proxy)

    def test_raw_vllm_spawns_proxy(self) -> None:
        """Endpoint answers /v1/models with data:[] → ephemeral proxy spawned."""
        from benchmark_runner.bench import resolve_vllm_candidate

        spec = ParsedSpec(provider="vllm", model="MyModel",
                          endpoint="http://192.168.1.23:8000")

        # First call (POST /v1/messages) should raise a 404 → not-an-anthropic-proxy.
        import urllib.error as _ue

        class FakeHTTPError404(_ue.HTTPError):
            def __init__(self):  # noqa: ANN204
                super().__init__("url", 404, "Not Found", {}, None)

        models_resp = self._mock_openai_models_response(ctx_len=131072)

        call_count = [0]

        def fake_urlopen(req, timeout=None):  # noqa: ANN001, ANN202
            call_count[0] += 1
            if call_count[0] == 1:
                raise FakeHTTPError404()
            return models_resp

        # Mock the proxy start/stop so no real process is spawned.
        fake_proxy = mock.MagicMock()
        fake_proxy.base_url = "http://127.0.0.1:8787"
        fake_proxy.__enter__ = mock.Mock(return_value=fake_proxy)
        fake_proxy.__exit__ = mock.Mock(return_value=False)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             mock.patch("benchmark_runner.bench.LiteLLMProxy", return_value=fake_proxy) as MockProxy:
            c = resolve_vllm_candidate(spec)

        MockProxy.assert_called_once_with("http://192.168.1.23:8000", "MyModel")
        fake_proxy.start.assert_called_once()
        self.assertEqual(c.env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8787")
        self.assertEqual(c.env["ANTHROPIC_AUTH_TOKEN"], "vllm-ephemeral")
        self.assertIs(c.vllm_proxy, fake_proxy)

    def test_context_length_too_small_aborts(self) -> None:
        """max_model_len < 32000 → ValueError."""
        from benchmark_runner.bench import resolve_vllm_candidate
        import urllib.error as _ue

        class FakeHTTPError404(_ue.HTTPError):
            def __init__(self):  # noqa: ANN204
                super().__init__("url", 404, "Not Found", {}, None)

        models_resp = self._mock_openai_models_response(ctx_len=8192)

        call_count = [0]

        def fake_urlopen(req, timeout=None):  # noqa: ANN001, ANN202
            call_count[0] += 1
            if call_count[0] == 1:
                raise FakeHTTPError404()
            return models_resp

        spec = ParsedSpec(provider="vllm", model="MyModel",
                          endpoint="http://192.168.1.23:8000")
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(ValueError) as cm:
                resolve_vllm_candidate(spec)
        self.assertIn("32000", str(cm.exception))

    def test_neither_endpoint_fails_fast(self) -> None:
        """Endpoint answers neither /v1/messages nor /v1/models → ValueError."""
        from benchmark_runner.bench import resolve_vllm_candidate
        import urllib.error as _ue

        class FakeHTTPError404(_ue.HTTPError):
            def __init__(self):  # noqa: ANN204
                super().__init__("url", 404, "Not Found", {}, None)

        spec = ParsedSpec(provider="vllm", model="MyModel",
                          endpoint="http://no-such-host:9999")

        def fake_urlopen(req, timeout=None):  # noqa: ANN001, ANN202
            raise FakeHTTPError404()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(ValueError) as cm:
                resolve_vllm_candidate(spec)
        self.assertIn("neither", str(cm.exception))


class TestBuildCompareConfig(unittest.TestCase):
    """build_compare_config produces a config that loads via compare.load_config."""

    def test_loads_via_compare_load_config(self) -> None:
        from benchmark_runner.bench import ResolvedCandidate
        candidates = [
            ResolvedCandidate(name="c1", backend="claude-code", model="sonnet", env={}, is_anthropic=True),
            ResolvedCandidate(name="c2", backend="claude-code", model="opus", env={}, is_anthropic=True),
        ]
        cfg_dict = build_compare_config(
            candidates,
            benchmark="stub",
            runs=3,
            task_filter=["python/bowling"],
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cfg.json"
            p.write_text(json.dumps(cfg_dict), encoding="utf-8")
            cfg = load_config(p)
        self.assertEqual(cfg.benchmark, "stub")
        self.assertEqual(cfg.runs, 3)
        self.assertEqual(cfg.task_filter, ["python/bowling"])
        self.assertEqual(len(cfg.candidates), 2)
        self.assertEqual(cfg.candidates[0].name, "c1")
        self.assertEqual(cfg.candidates[1].name, "c2")


if __name__ == "__main__":
    unittest.main()
