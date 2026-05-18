# tests/test_proxy_helper.py — LiteLLM proxy helper.
#
# Verifies:
#   - Config emits the `hosted_vllm/` provider prefix (not `openai/`).
#   - Teardown escalates SIGTERM → SIGKILL (subprocess mocked).
#   - ProxyStartError raised when process dies during startup.

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from benchmark_runner.proxy import LiteLLMProxy, _graceful_kill, _http_ok


class TestConfigEmitsHostedVllm(unittest.TestCase):
    """Config written by LiteLLMProxy must use hosted_vllm/ prefix."""

    def test_config_contains_hosted_vllm_prefix(self) -> None:
        proxy = LiteLLMProxy(
            vllm_base="http://192.168.1.23:8000",
            vllm_model="RedHatAI/Qwen3-Coder-Next-NVFP4",
            port=8787,
        )
        proxy._write_config()
        try:
            config_text = proxy._config_path.read_text(encoding="utf-8")
            self.assertIn("hosted_vllm/", config_text)
            self.assertNotIn("openai/RedHatAI", config_text)
            self.assertIn("RedHatAI/Qwen3-Coder-Next-NVFP4", config_text)
            self.assertIn("http://192.168.1.23:8000/v1", config_text)
            self.assertIn("drop_params: true", config_text)
        finally:
            if proxy._config_path and proxy._config_path.exists():
                proxy._config_path.unlink()
            if proxy._log_path and proxy._log_path.exists():
                proxy._log_path.unlink()

    def test_config_api_key_is_dummy(self) -> None:
        proxy = LiteLLMProxy("http://host:8000", "model")
        proxy._write_config()
        try:
            config_text = proxy._config_path.read_text(encoding="utf-8")
            self.assertIn('api_key: "dummy"', config_text)
        finally:
            if proxy._config_path and proxy._config_path.exists():
                proxy._config_path.unlink()
            if proxy._log_path and proxy._log_path.exists():
                proxy._log_path.unlink()


class TestGracefulKill(unittest.TestCase):
    """_graceful_kill: SIGTERM → SIGKILL escalation."""

    def test_sigterm_sufficient(self) -> None:
        """Process that dies on SIGTERM should not escalate to SIGKILL."""
        proc = mock.MagicMock(spec=subprocess.Popen)
        proc.pid = 99999
        proc.wait.return_value = 0  # exits promptly on first wait()

        kill_calls = []
        with mock.patch("os.getpgid", return_value=12345), \
             mock.patch("os.killpg", side_effect=lambda pgid, sig: kill_calls.append(sig)):
            _graceful_kill(proc, sigterm_timeout=5)

        self.assertIn(signal.SIGTERM, kill_calls)
        self.assertNotIn(signal.SIGKILL, kill_calls)

    def test_sigkill_escalation_on_timeout(self) -> None:
        """Process that doesn't exit on SIGTERM → SIGKILL after timeout."""
        proc = mock.MagicMock(spec=subprocess.Popen)
        proc.pid = 99999

        # First wait() times out (process doesn't respond to SIGTERM);
        # second wait() succeeds after SIGKILL.
        proc.wait.side_effect = [subprocess.TimeoutExpired([], 5), 0]

        kill_calls = []
        with mock.patch("os.getpgid", return_value=12345), \
             mock.patch("os.killpg", side_effect=lambda pgid, sig: kill_calls.append(sig)):
            _graceful_kill(proc, sigterm_timeout=5)

        self.assertIn(signal.SIGTERM, kill_calls)
        self.assertIn(signal.SIGKILL, kill_calls)
        # SIGTERM must come before SIGKILL.
        self.assertLess(kill_calls.index(signal.SIGTERM), kill_calls.index(signal.SIGKILL))

    def test_process_already_dead_no_error(self) -> None:
        """ProcessLookupError on getpgid should be swallowed gracefully."""
        proc = mock.MagicMock(spec=subprocess.Popen)
        proc.pid = 99999
        proc.wait.return_value = 0

        with mock.patch("os.getpgid", side_effect=ProcessLookupError):
            _graceful_kill(proc, sigterm_timeout=5)  # must not raise


class TestProxyStartError(unittest.TestCase):
    """ProxyStartError raised when the proxy dies during startup."""

    def test_process_dies_during_startup_raises(self) -> None:
        from benchmark_runner.proxy import ProxyStartError

        proxy = LiteLLMProxy("http://host:8000", "model", startup_timeout=2)
        proxy._write_config()

        # Simulate a process that is immediately dead (poll() returns 1).
        fake_proc = mock.MagicMock(spec=subprocess.Popen)
        fake_proc.pid = 12345
        fake_proc.poll.return_value = 1  # already exited

        try:
            with mock.patch.object(proxy, "_spawn", lambda: setattr(proxy, "_proc", fake_proc)), \
                 mock.patch("benchmark_runner.proxy._http_ok", return_value=False):
                with self.assertRaises(ProxyStartError):
                    proxy._wait_healthy()
        finally:
            if proxy._config_path and proxy._config_path.exists():
                proxy._config_path.unlink()
            if proxy._log_path and proxy._log_path.exists():
                proxy._log_path.unlink()


class TestHttpOk(unittest.TestCase):
    def test_returns_true_on_200(self) -> None:
        resp = mock.MagicMock()
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)
        resp.status = 200
        with mock.patch("urllib.request.urlopen", return_value=resp):
            self.assertTrue(_http_ok("http://example.com"))

    def test_returns_false_on_exception(self) -> None:
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("no route")):
            self.assertFalse(_http_ok("http://no-such-host:9999"))


if __name__ == "__main__":
    unittest.main()
