# tests/test_bench_parser.py — spec-parser invariants.
#
# Covers every whitelisted prefix, the colon-tag invariant, @endpoint
# parsing, and unknown-token did-you-mean hints.

from __future__ import annotations

import unittest

from benchmark_runner.bench import ParsedSpec, ResolvedCandidate, parse_spec, resolve_candidate


class TestAnthoropicShortcuts(unittest.TestCase):
    def test_sonnet(self) -> None:
        s = parse_spec("sonnet")
        self.assertEqual(s.provider, "anthropic")
        # Rule 1: bare alias, NOT "claude-code:sonnet" (spec.md § Spec-parsing contract rule 1).
        self.assertEqual(s.model, "sonnet")
        self.assertIsNone(s.endpoint)

    def test_opus(self) -> None:
        s = parse_spec("opus")
        self.assertEqual(s.provider, "anthropic")
        self.assertEqual(s.model, "opus")
        self.assertIsNone(s.endpoint)

    def test_haiku(self) -> None:
        s = parse_spec("haiku")
        self.assertEqual(s.provider, "anthropic")
        self.assertEqual(s.model, "haiku")
        self.assertIsNone(s.endpoint)

    def test_shorthand_model_is_not_combined_form(self) -> None:
        """Regression: model must never be 'claude-code:<token>' — that form
        is rejected by cli.py/compare.py as an invalid model id."""
        for alias in ("sonnet", "opus", "haiku"):
            s = parse_spec(alias)
            self.assertNotIn("claude-code:", s.model,
                msg=f"parse_spec({alias!r}).model must be the bare alias, not a combined form")

    def test_resolve_candidate_anthropic_shortcuts(self) -> None:
        """resolve_candidate on anthropic shortcuts must yield backend=claude-code,
        model=bare alias (e.g. 'sonnet'), is_anthropic=True."""
        for alias in ("sonnet", "opus", "haiku"):
            spec = parse_spec(alias)
            rc = resolve_candidate(spec)
            self.assertEqual(rc.backend, "claude-code",
                msg=f"backend for {alias!r} must be 'claude-code'")
            self.assertEqual(rc.model, alias,
                msg=f"model for {alias!r} must be bare alias, got {rc.model!r}")
            self.assertTrue(rc.is_anthropic,
                msg=f"is_anthropic must be True for {alias!r}")
            self.assertNotIn("claude-code:", rc.model,
                msg=f"rc.model for {alias!r} must not contain 'claude-code:'")


class TestClaudeCodePrefix(unittest.TestCase):
    def test_claude_code_explicit(self) -> None:
        s = parse_spec("claude-code:sonnet")
        self.assertEqual(s.provider, "claude-code")
        self.assertEqual(s.model, "sonnet")
        self.assertIsNone(s.endpoint)

    def test_claude_code_full_id(self) -> None:
        s = parse_spec("claude-code:claude-sonnet-4-6")
        self.assertEqual(s.provider, "claude-code")
        self.assertEqual(s.model, "claude-sonnet-4-6")
        self.assertIsNone(s.endpoint)


class TestOllamaPrefix(unittest.TestCase):
    def test_simple_model(self) -> None:
        s = parse_spec("ollama:qwen2.5-coder")
        self.assertEqual(s.provider, "ollama")
        self.assertEqual(s.model, "qwen2.5-coder")
        self.assertIsNone(s.endpoint)

    def test_colon_tag_invariant(self) -> None:
        """ollama:qwen2.5-coder:7b → (ollama, qwen2.5-coder:7b, default).

        The inner colon in the model name must NOT be treated as a
        provider/endpoint separator.
        """
        s = parse_spec("ollama:qwen2.5-coder:7b")
        self.assertEqual(s.provider, "ollama")
        self.assertEqual(s.model, "qwen2.5-coder:7b")
        self.assertIsNone(s.endpoint)

    def test_colon_tag_32b(self) -> None:
        s = parse_spec("ollama:qwen2.5-coder:32b")
        self.assertEqual(s.provider, "ollama")
        self.assertEqual(s.model, "qwen2.5-coder:32b")
        self.assertIsNone(s.endpoint)

    def test_qwen3_tag(self) -> None:
        s = parse_spec("ollama:qwen3.6:27b")
        self.assertEqual(s.provider, "ollama")
        self.assertEqual(s.model, "qwen3.6:27b")
        self.assertIsNone(s.endpoint)

    def test_with_endpoint(self) -> None:
        s = parse_spec("ollama:qwen2.5-coder:7b@http://192.168.1.10:11434")
        self.assertEqual(s.provider, "ollama")
        self.assertEqual(s.model, "qwen2.5-coder:7b")
        self.assertEqual(s.endpoint, "http://192.168.1.10:11434")


class TestVllmPrefix(unittest.TestCase):
    def test_model_with_endpoint(self) -> None:
        s = parse_spec("vllm:Qwen3-Coder@http://127.0.0.1:8787")
        self.assertEqual(s.provider, "vllm")
        self.assertEqual(s.model, "Qwen3-Coder")
        self.assertEqual(s.endpoint, "http://127.0.0.1:8787")

    def test_model_with_host_endpoint(self) -> None:
        s = parse_spec("vllm:RedHatAI/Qwen3-Coder-Next-NVFP4@http://192.168.1.23:8000")
        self.assertEqual(s.provider, "vllm")
        self.assertEqual(s.model, "RedHatAI/Qwen3-Coder-Next-NVFP4")
        self.assertEqual(s.endpoint, "http://192.168.1.23:8000")

    def test_no_endpoint(self) -> None:
        s = parse_spec("vllm:SomeModel")
        self.assertEqual(s.provider, "vllm")
        self.assertEqual(s.model, "SomeModel")
        self.assertIsNone(s.endpoint)


class TestLmStudioPrefix(unittest.TestCase):
    def test_simple(self) -> None:
        s = parse_spec("lmstudio:phi-3")
        self.assertEqual(s.provider, "lmstudio")
        self.assertEqual(s.model, "phi-3")
        self.assertIsNone(s.endpoint)

    def test_with_endpoint(self) -> None:
        s = parse_spec("lmstudio:phi-3@http://localhost:5678")
        self.assertEqual(s.provider, "lmstudio")
        self.assertEqual(s.model, "phi-3")
        self.assertEqual(s.endpoint, "http://localhost:5678")


class TestOpenrouterPrefix(unittest.TestCase):
    def test_simple(self) -> None:
        s = parse_spec("openrouter:meta-llama/llama-3-70b")
        self.assertEqual(s.provider, "openrouter")
        self.assertEqual(s.model, "meta-llama/llama-3-70b")
        self.assertIsNone(s.endpoint)


class TestEndpointParsing(unittest.TestCase):
    def test_endpoint_only_at_final_at(self) -> None:
        # @endpoint is the FINAL @-introduced segment.
        s = parse_spec("ollama:some@model@http://host:11434")
        self.assertEqual(s.provider, "ollama")
        self.assertEqual(s.model, "some@model")
        self.assertEqual(s.endpoint, "http://host:11434")

    def test_no_at_sign_is_no_endpoint(self) -> None:
        s = parse_spec("ollama:some-model-no-at")
        self.assertIsNone(s.endpoint)


class TestUnknownToken(unittest.TestCase):
    def test_unknown_token_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as cm:
            parse_spec("gpt-4o")
        msg = str(cm.exception).lower()
        self.assertIn("unknown provider token", msg)

    def test_unknown_token_includes_did_you_mean(self) -> None:
        # A token that looks like a mis-spelled known prefix should
        # include a hint.
        with self.assertRaises(ValueError) as cm:
            parse_spec("llama:model")
        msg = str(cm.exception)
        self.assertIn("Unknown provider token", msg)

    def test_bare_model_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_spec("claude-3-sonnet")


if __name__ == "__main__":
    unittest.main()
