# tests/test_bench_cli.py — CLI flag handling: --yes, non-TTY, --preset,
# --runs/--task override, zero-config smoke, --list-providers Ollama 3-check.

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from benchmark_runner.bench import (
    _parse_argv,
    list_presets,
    load_preset,
    main,
)


# ── Argument parsing ───────────────────────────────────────────────────


class TestParseArgv(unittest.TestCase):
    def test_no_args(self) -> None:
        opts, candidates, passthrough = _parse_argv([])
        self.assertFalse(opts["yes"])
        self.assertFalse(opts["list_presets"])
        self.assertEqual(candidates, [])

    def test_candidates_parsed(self) -> None:
        opts, candidates, passthrough = _parse_argv(["sonnet", "ollama:qwen2.5-coder:7b"])
        self.assertEqual(candidates, ["sonnet", "ollama:qwen2.5-coder:7b"])
        self.assertEqual(passthrough, [])

    def test_yes_flag(self) -> None:
        opts, _, _ = _parse_argv(["--yes", "sonnet"])
        self.assertTrue(opts["yes"])

    def test_no_confirm_flag(self) -> None:
        opts, _, _ = _parse_argv(["--no-confirm", "sonnet"])
        self.assertTrue(opts["no_confirm"])

    def test_runs_flag(self) -> None:
        opts, _, _ = _parse_argv(["--runs", "5", "sonnet"])
        self.assertEqual(opts["runs"], 5)

    def test_task_flag(self) -> None:
        opts, _, _ = _parse_argv(["--task", "python/bowling,go/bowling"])
        self.assertEqual(opts["task"], ["python/bowling", "go/bowling"])

    def test_preset_flag(self) -> None:
        opts, _, _ = _parse_argv(["--preset", "local-vs-cloud"])
        self.assertEqual(opts["preset"], "local-vs-cloud")

    def test_unknown_flags_pass_through(self) -> None:
        opts, candidates, passthrough = _parse_argv(
            ["--no-report", "--runs-root", "/tmp/x", "sonnet"]
        )
        self.assertEqual(candidates, ["sonnet"])
        self.assertIn("--no-report", passthrough)
        self.assertIn("--runs-root", passthrough)
        self.assertIn("/tmp/x", passthrough)

    def test_list_presets(self) -> None:
        opts, _, _ = _parse_argv(["--list-presets"])
        self.assertTrue(opts["list_presets"])

    def test_list_providers(self) -> None:
        opts, _, _ = _parse_argv(["--list-providers"])
        self.assertTrue(opts["list_providers"])

    def test_help_flag(self) -> None:
        opts, _, _ = _parse_argv(["--help"])
        self.assertTrue(opts["help"])


# ── Help / list-presets exits 0 ───────────────────────────────────────


class TestHelpExits(unittest.TestCase):
    def test_help_exits_0(self) -> None:
        rc = main(["--help"])
        self.assertEqual(rc, 0)

    def test_list_presets_exits_0(self) -> None:
        rc = main(["--list-presets"])
        self.assertEqual(rc, 0)


# ── Preset loading ─────────────────────────────────────────────────────


class TestPresetLoading(unittest.TestCase):
    def _write_preset(self, tmpdir: str, name: str, content: dict) -> Path:
        d = Path(tmpdir) / "benchmarks" / "presets"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{name}.json"
        p.write_text(json.dumps(content), encoding="utf-8")
        return p

    def test_load_preset_missing_raises(self) -> None:
        with mock.patch(
            "benchmark_runner.bench._presets_dir",
            return_value=Path("/nonexistent/path"),
        ):
            with self.assertRaises(ValueError) as cm:
                load_preset("no-such-preset")
            self.assertIn("no-such-preset", str(cm.exception))

    def test_list_presets_returns_stems(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.json").write_text("{}", encoding="utf-8")
            (d / "b.json").write_text("{}", encoding="utf-8")
            with mock.patch("benchmark_runner.bench._presets_dir", return_value=d):
                names = list_presets()
        self.assertIn("a", names)
        self.assertIn("b", names)


# ── Confirmation gate ──────────────────────────────────────────────────


class TestConfirmationGate(unittest.TestCase):
    def test_yes_flag_bypasses_gate(self) -> None:
        """--yes should not prompt even with Anthropic candidates."""
        with mock.patch("subprocess.run") as mock_run, \
             mock.patch("benchmark_runner.bench._run_stub_smoke", return_value=True):
            mock_run.return_value = mock.MagicMock(returncode=0)
            rc = main(["--yes", "sonnet", "opus"])
        # Should reach subprocess.run (benchmark compare), not prompt.
        self.assertEqual(rc, 0)

    def test_no_confirm_bypasses_gate(self) -> None:
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            rc = main(["--no-confirm", "sonnet", "opus"])
        self.assertEqual(rc, 0)

    def test_non_tty_bypasses_gate(self) -> None:
        """Non-TTY stdin should behave as --yes."""
        with mock.patch("sys.stdin") as mock_stdin, \
             mock.patch("subprocess.run") as mock_run:
            mock_stdin.isatty.return_value = False
            mock_run.return_value = mock.MagicMock(returncode=0)
            rc = main(["sonnet", "opus"])
        self.assertEqual(rc, 0)

    def test_all_local_never_prompts(self) -> None:
        """Ollama-only candidates should never trigger the confirmation gate."""
        import io
        original_stdin = sys.stdin
        try:
            # Replace stdin with a stream that raises on read — ensures
            # the gate never calls input().
            sys.stdin = io.StringIO("")
            sys.stdin.isatty = lambda: True  # type: ignore[method-assign]
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0)
                rc = main(["--yes", "ollama:qwen2.5-coder:7b", "lmstudio:phi-3"])
        finally:
            sys.stdin = original_stdin
        self.assertEqual(rc, 0)


# ── Zero-config smoke ──────────────────────────────────────────────────


class TestZeroConfig(unittest.TestCase):
    def test_no_args_exits_0(self) -> None:
        """./scripts/bench (no args) must exit 0 without calling any LLM."""
        with mock.patch("benchmark_runner.bench._run_stub_smoke", return_value=True):
            rc = main([])
        self.assertEqual(rc, 0)

    def test_no_args_smoke_fail_exits_1(self) -> None:
        with mock.patch("benchmark_runner.bench._run_stub_smoke", return_value=False):
            rc = main([])
        self.assertEqual(rc, 1)


# ── --list-providers Ollama 3-check ────────────────────────────────────


class TestListProvidersOllamaCheck(unittest.TestCase):
    def _urlopen_factory(self, version_body: bytes, tags_body: bytes):  # noqa: ANN202
        """Return a urlopen side_effect that handles /api/version and /api/tags."""
        def fake_urlopen(url_or_req, timeout=None):  # noqa: ANN001, ANN202
            url = url_or_req if isinstance(url_or_req, str) else url_or_req.full_url
            resp = mock.MagicMock()
            resp.__enter__ = mock.Mock(return_value=resp)
            resp.__exit__ = mock.Mock(return_value=False)
            if "/api/version" in url:
                resp.status = 200
                resp.read.return_value = version_body
                return resp
            if "/api/tags" in url:
                resp.status = 200
                resp.read.return_value = tags_body
                return resp
            if "/v1/models" in url:
                # LM Studio probe — not found.
                import urllib.error
                raise urllib.error.URLError("not reachable")
            import urllib.error
            raise urllib.error.URLError("unmatched")
        return fake_urlopen

    def test_ollama_usable(self) -> None:
        version_body = json.dumps({"version": "0.14.0"}).encode()
        tags_body = json.dumps({"models": [{"name": "qwen2.5-coder:7b"}]}).encode()
        with mock.patch.dict("os.environ", {"OLLAMA_HOST": "http://localhost:11434"}), \
             mock.patch("urllib.request.urlopen",
                        side_effect=self._urlopen_factory(version_body, tags_body)):
            rc = main(["--list-providers"])
        self.assertEqual(rc, 0)

    def test_ollama_too_old_unusable(self) -> None:
        version_body = json.dumps({"version": "0.13.5"}).encode()
        tags_body = json.dumps({"models": []}).encode()
        captured = []
        with mock.patch.dict("os.environ", {"OLLAMA_HOST": "http://localhost:11434"}), \
             mock.patch("urllib.request.urlopen",
                        side_effect=self._urlopen_factory(version_body, tags_body)), \
             mock.patch("builtins.print", side_effect=lambda *a, **kw: captured.append(" ".join(str(x) for x in a))):
            rc = main(["--list-providers"])
        self.assertEqual(rc, 0)
        combined = "\n".join(captured)
        self.assertIn("unusable", combined.lower())
        self.assertIn("0.13.5", combined)

    def test_ollama_not_detected_without_binary_or_host(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch("benchmark_runner.bench._which", return_value=None):
            captured = []
            with mock.patch("builtins.print", side_effect=lambda *a, **kw: captured.append(" ".join(str(x) for x in a))):
                rc = main(["--list-providers"])
        self.assertEqual(rc, 0)
        combined = "\n".join(captured)
        self.assertIn("not detected", combined.lower())


# ── Legacy --config path regression ────────────────────────────────────


class TestLegacyConfigRegression(unittest.TestCase):
    """The legacy ./scripts/benchmark compare --config <file> path must be unaffected."""

    def test_compare_load_config_unchanged(self) -> None:
        """Regression: load_config on a well-formed compare-config returns expected fields."""
        from benchmark_runner.compare import load_config, CompareConfigError

        good = {
            "benchmark": "stub",
            "runs": 2,
            "candidates": [
                {"backend": "stub", "model": ""},
                {"backend": "stub2", "model": ""},
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cfg.json"
            p.write_text(json.dumps(good), encoding="utf-8")
            cfg = load_config(p)
        self.assertEqual(cfg.benchmark, "stub")
        self.assertEqual(cfg.runs, 2)
        self.assertEqual(len(cfg.candidates), 2)

        # Single candidate still rejected.
        bad = {
            "benchmark": "stub",
            "candidates": [{"backend": "stub"}],
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(CompareConfigError, "at least 2"):
                load_config(p)


# ── Defect 2: preset confirmation gate ────────────────────────────────


class TestPresetConfirmationGate(unittest.TestCase):
    """Regression tests for D2: _run_preset must honour the confirmation gate."""

    def _anthropic_preset(self) -> dict:
        """Synthetic all-Anthropic preset (no ANTHROPIC_BASE_URL in any candidate env)."""
        return {
            "benchmark": "stub",
            "runs": 1,
            "candidates": [
                {"name": "c-sonnet", "backend": "claude-code", "model": "sonnet"},
                {"name": "c-opus", "backend": "claude-code", "model": "opus"},
            ],
        }

    def _local_preset(self) -> dict:
        """Synthetic all-local preset (every candidate has ANTHROPIC_BASE_URL)."""
        return {
            "benchmark": "stub",
            "runs": 1,
            "candidates": [
                {
                    "name": "local-a",
                    "backend": "claude-code",
                    "model": "qwen:7b",
                    "env": {"ANTHROPIC_BASE_URL": "http://localhost:11434"},
                },
                {
                    "name": "local-b",
                    "backend": "claude-code",
                    "model": "qwen:32b",
                    "env": {"ANTHROPIC_BASE_URL": "http://localhost:11434"},
                },
            ],
        }

    def _single_anthropic_preset(self) -> dict:
        """Single Anthropic candidate preset — tests gate + Defect 3 together."""
        return {
            "benchmark": "stub",
            "runs": 1,
            "candidates": [
                {"name": "c-sonnet", "backend": "claude-code", "model": "sonnet"},
            ],
        }

    def _single_local_preset(self) -> dict:
        """Single local candidate preset with an env block (Defect 3 regression)."""
        return {
            "benchmark": "stub",
            "runs": 1,
            "candidates": [
                {
                    "name": "local-single",
                    "backend": "claude-code",
                    "model": "qwen:7b",
                    "env": {
                        "ANTHROPIC_BASE_URL": "http://localhost:11434",
                        "ANTHROPIC_AUTH_TOKEN": "ollama",
                        "ANTHROPIC_DEFAULT_SONNET_MODEL": "qwen:7b",
                        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen:7b",
                    },
                },
            ],
        }

    def test_preset_anthropic_tty_n_aborts(self) -> None:
        """--preset with Anthropic candidates + TTY + answer 'n' must abort WITHOUT dispatching."""
        import io
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "benchmarks" / "presets"
            d.mkdir(parents=True)
            (d / "tour.json").write_text(json.dumps(self._anthropic_preset()))

            with mock.patch("benchmark_runner.bench._presets_dir", return_value=d), \
                 mock.patch("subprocess.run") as mock_sub, \
                 mock.patch("sys.stdin") as mock_stdin, \
                 mock.patch("builtins.input", return_value="n"):
                mock_stdin.isatty.return_value = True
                rc = main(["--preset", "tour"])

        # Gate returned False → must not have dispatched.
        mock_sub.assert_not_called()
        self.assertEqual(rc, 0)

    def test_preset_anthropic_yes_flag_bypasses_gate(self) -> None:
        """--preset + --yes must skip the gate and dispatch."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "benchmarks" / "presets"
            d.mkdir(parents=True)
            (d / "tour.json").write_text(json.dumps(self._anthropic_preset()))

            with mock.patch("benchmark_runner.bench._presets_dir", return_value=d), \
                 mock.patch("subprocess.run") as mock_sub:
                mock_sub.return_value = mock.MagicMock(returncode=0)
                rc = main(["--preset", "tour", "--yes"])

        mock_sub.assert_called_once()
        self.assertEqual(rc, 0)

    def test_preset_all_local_no_gate(self) -> None:
        """All-local preset must NOT prompt — calling input() is a test failure."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "benchmarks" / "presets"
            d.mkdir(parents=True)
            (d / "local.json").write_text(json.dumps(self._local_preset()))

            with mock.patch("benchmark_runner.bench._presets_dir", return_value=d), \
                 mock.patch("subprocess.run") as mock_sub, \
                 mock.patch("sys.stdin") as mock_stdin, \
                 mock.patch("builtins.input",
                            side_effect=AssertionError("input() called for all-local preset")):
                mock_stdin.isatty.return_value = True
                mock_sub.return_value = mock.MagicMock(returncode=0)
                rc = main(["--preset", "local"])

        self.assertEqual(rc, 0)

    def test_preset_non_tty_no_gate(self) -> None:
        """Non-TTY stdin must bypass the gate even for Anthropic presets."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "benchmarks" / "presets"
            d.mkdir(parents=True)
            (d / "tour.json").write_text(json.dumps(self._anthropic_preset()))

            with mock.patch("benchmark_runner.bench._presets_dir", return_value=d), \
                 mock.patch("subprocess.run") as mock_sub, \
                 mock.patch("sys.stdin") as mock_stdin, \
                 mock.patch("builtins.input",
                            side_effect=AssertionError("input() called for non-TTY")):
                mock_stdin.isatty.return_value = False
                mock_sub.return_value = mock.MagicMock(returncode=0)
                rc = main(["--preset", "tour"])

        self.assertEqual(rc, 0)


# ── Defect 3: single-candidate preset applies env ─────────────────────


class TestPresetSingleCandidateEnv(unittest.TestCase):
    """Regression test for D3: single-candidate preset must patch env before invoking run."""

    def test_single_candidate_env_patched(self) -> None:
        """Env block from the single preset candidate must be visible to the invoked command."""
        preset = {
            "benchmark": "stub",
            "runs": 1,
            "candidates": [
                {
                    "name": "local-single",
                    "backend": "claude-code",
                    "model": "qwen:7b",
                    "env": {
                        "ANTHROPIC_BASE_URL": "http://localhost:11434",
                        "ANTHROPIC_AUTH_TOKEN": "test-token-xyz",
                    },
                },
            ],
        }

        captured_env: dict = {}

        def capture_env(*args, **kwargs):  # noqa: ANN002, ANN003
            captured_env.update(os.environ.copy())
            return mock.MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "benchmarks" / "presets"
            d.mkdir(parents=True)
            (d / "single.json").write_text(json.dumps(preset))

            with mock.patch("benchmark_runner.bench._presets_dir", return_value=d), \
                 mock.patch("subprocess.run", side_effect=capture_env), \
                 mock.patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = False  # bypass gate
                rc = main(["--preset", "single"])

        self.assertEqual(rc, 0)
        self.assertEqual(captured_env.get("ANTHROPIC_BASE_URL"), "http://localhost:11434",
            "ANTHROPIC_BASE_URL from preset env must be set during subprocess.run")
        self.assertEqual(captured_env.get("ANTHROPIC_AUTH_TOKEN"), "test-token-xyz",
            "ANTHROPIC_AUTH_TOKEN from preset env must be set during subprocess.run")


if __name__ == "__main__":
    unittest.main()
