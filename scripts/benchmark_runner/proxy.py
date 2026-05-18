# benchmark_runner.proxy — shared LiteLLM Anthropic→OpenAI proxy lifecycle.
#
# Extracted from scripts/run-compare-anthropic-vs-vllm.sh so that the
# same verified launch recipe is used by both:
#   - scripts/bench (ephemeral proxy for raw-vLLM candidates)
#   - scripts/run-compare-anthropic-vs-vllm.sh (via subprocess)
#
# The `hosted_vllm/` provider prefix is mandatory — see
# benchmarks/backends/vllm.md blocker #5: LiteLLM ≥1.50 with the
# `openai/` prefix auto-routes to vLLM's /v1/responses endpoint, which
# rejects the multi-turn input-array shape with 212 validation errors.
# `hosted_vllm/` pins routing to /v1/chat/completions.
#
# Proxy lifecycle:
#   1. Write a YAML config tempfile with the `hosted_vllm/` alias.
#   2. Start `litellm --config … --port … --host 127.0.0.1` in background.
#   3. Healthcheck-loop: poll /v1/models up to 30s.
#   4. Caller calls stop() (or an atexit handler) which sends SIGTERM;
#      if the process does not exit within 5s, escalates to SIGKILL.
#
# Usage (Python):
#   proxy = LiteLLMProxy(vllm_base, vllm_model, port=8787)
#   proxy.start()          # blocks until healthy
#   try:
#       ...
#   finally:
#       proxy.stop()
#
# Or as a context manager:
#   with LiteLLMProxy(vllm_base, vllm_model) as proxy:
#       base_url = proxy.base_url   # http://127.0.0.1:<port>

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


class ProxyStartError(RuntimeError):
    """Raised when the LiteLLM proxy fails to start within the timeout."""


class LiteLLMProxy:
    """Ephemeral LiteLLM Anthropic→OpenAI proxy wrapping a raw vLLM endpoint.

    Writes a per-instance tempfile config so concurrent proxy instances
    (different ports / different models) do not clobber each other.
    """

    def __init__(
        self,
        vllm_base: str,
        vllm_model: str,
        *,
        port: int = 8787,
        startup_timeout: int = 30,
    ) -> None:
        self._vllm_base = vllm_base.rstrip("/")
        self._vllm_model = vllm_model
        self._port = port
        self._startup_timeout = startup_timeout
        self._proc: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._config_path: Optional[Path] = None
        self._log_path: Optional[Path] = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Write config, start proxy, wait for health."""
        self._write_config()
        self._spawn()
        self._wait_healthy()

    def stop(self) -> None:
        """SIGTERM → wait 5s → SIGKILL if still running."""
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        _graceful_kill(proc, sigterm_timeout=5)
        # Clean up tempfiles after the process is gone.
        if self._config_path and self._config_path.exists():
            try:
                self._config_path.unlink()
            except OSError:
                pass
        if self._log_path and self._log_path.exists():
            try:
                self._log_path.unlink()
            except OSError:
                pass

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ── Context manager ────────────────────────────────────────────────

    def __enter__(self) -> "LiteLLMProxy":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:  # type: ignore[no-untyped-def]
        self.stop()

    # ── Internals ──────────────────────────────────────────────────────

    def _write_config(self) -> None:
        # Use mktemp so two concurrent instances don't clobber each other.
        fd, config_path = tempfile.mkstemp(suffix=".yaml", prefix="cct-litellm-")
        os.close(fd)
        self._config_path = Path(config_path)
        # The hosted_vllm/ prefix pins routing to /v1/chat/completions.
        # api_key is required by the LiteLLM SDK; vLLM ignores it.
        config_yaml = (
            f"model_list:\n"
            f"  - model_name: \"{self._vllm_model}\"\n"
            f"    litellm_params:\n"
            f"      model: \"hosted_vllm/{self._vllm_model}\"\n"
            f"      api_base: \"{self._vllm_base}/v1\"\n"
            f"      api_key: \"dummy\"\n"
            f"litellm_settings:\n"
            f"  drop_params: true\n"
        )
        self._config_path.write_text(config_yaml, encoding="utf-8")

        fd2, log_path = tempfile.mkstemp(suffix=".log", prefix="cct-litellm-")
        os.close(fd2)
        self._log_path = Path(log_path)

    def _spawn(self) -> None:
        log_fd = open(self._log_path, "w") if self._log_path else subprocess.DEVNULL  # noqa: SIM115
        self._proc = subprocess.Popen(
            [
                "litellm",
                "--config", str(self._config_path),
                "--port", str(self._port),
                "--host", "127.0.0.1",
            ],
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
        )

    def _wait_healthy(self) -> None:
        """Poll /v1/models up to startup_timeout seconds."""
        url = f"{self.base_url}/v1/models"
        deadline = time.monotonic() + self._startup_timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                log_tail = _read_tail(self._log_path, 40)
                raise ProxyStartError(
                    f"LiteLLM proxy (PID {self._proc.pid}) died during startup.\n"
                    f"Log tail:\n{log_tail}"
                )
            if _http_ok(url):
                return
            time.sleep(1)
        log_tail = _read_tail(self._log_path, 40)
        raise ProxyStartError(
            f"LiteLLM proxy did not answer {url} within {self._startup_timeout}s.\n"
            f"Log tail:\n{log_tail}"
        )

    def get_log_tail(self, lines: int = 40) -> str:
        return _read_tail(self._log_path, lines)


# ── CLI helper (used by run-compare-anthropic-vs-vllm.sh) ─────────────
#
# Called as:
#   python3 -m benchmark_runner.proxy start \
#       --vllm-base <url> --model <name> --port <n>
#
# Prints to stdout (one key=value per line):
#   pid=<n>
#   config=<path>
#   log=<path>
#   base_url=http://127.0.0.1:<port>
#
# The caller (bash script) reads these and stores PID for its trap.
# This is the "single source of truth" contract: the bash script no
# longer carries its own config-writing or spawn logic.


def _cli_start(vllm_base: str, vllm_model: str, port: int) -> None:
    """Start proxy and print pid/config/log/base_url to stdout."""
    proxy = LiteLLMProxy(vllm_base, vllm_model, port=port)
    proxy._write_config()
    proxy._spawn()
    proxy._wait_healthy()
    pid = proxy._proc.pid if proxy._proc else -1
    print(f"pid={pid}")
    print(f"config={proxy._config_path}")
    print(f"log={proxy._log_path}")
    print(f"base_url={proxy.base_url}")
    # Hand off ownership — don't stop in __del__.
    proxy._proc = None  # noqa: SLF001 — intentional ownership transfer


def main_cli() -> None:  # noqa: D401 — CLI entry
    import argparse
    parser = argparse.ArgumentParser(
        prog="python3 -m benchmark_runner.proxy",
        description="Start an ephemeral LiteLLM proxy and print PID/paths to stdout.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_start = sub.add_parser("start", help="Start the proxy.")
    p_start.add_argument("--vllm-base", required=True)
    p_start.add_argument("--model", required=True)
    p_start.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if args.cmd == "start":
        _cli_start(args.vllm_base, args.model, args.port)


if __name__ == "__main__":
    main_cli()


# ── Module-level helpers ───────────────────────────────────────────────


def _graceful_kill(proc: subprocess.Popen, *, sigterm_timeout: int = 5) -> None:  # type: ignore[type-arg]
    """SIGTERM → wait → SIGKILL escalation for a process group."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass  # already dead

    try:
        proc.wait(timeout=sigterm_timeout)
        return
    except subprocess.TimeoutExpired:
        pass

    # Escalate to SIGKILL.
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    """Return True if the URL responds with any 2xx status."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001
        return False


def _read_tail(path: Optional[Path], lines: int) -> str:
    if path is None or not path.exists():
        return "(no log)"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except OSError:
        return "(unreadable)"
