# benchmark_runner.progress — stderr progress logger for live attempt reporting.
#
# Every emission uses print(..., file=sys.stderr, flush=True) so progress
# lines are never buffered, even when stdout is redirected. The heartbeat
# interval is injectable (constructor arg) so unit tests can use a
# sub-second interval without a 60-second real wait.
#
# Three line shapes (spec.md § Live progress contract):
#   [idx/total] <candidate> <task>  attempt <K>  starting...
#   [idx/total] <candidate> <task>  attempt <K>  running... <N>s elapsed
#   [idx/total] <candidate> <task>  attempt <K>  pass (<S>s, <T> tool calls)
#   [idx/total] <candidate> <task>  attempt <K>  fail (<S>s, <T> tool calls)
#   [idx/total] <candidate> <task>  attempt <K>  error (<S>s)
#
# Flush discipline: every line is flushed immediately. The wrapper
# (scripts/bench) also exports PYTHONUNBUFFERED=1 into every subprocess
# it spawns as belt-and-suspenders.

from __future__ import annotations

import sys
import threading
import time
from typing import Optional


_DEFAULT_HEARTBEAT_INTERVAL = 30.0  # seconds


class ProgressLogger:
    """Emits structured attempt-progress lines to stderr.

    Parameters
    ----------
    heartbeat_interval:
        Seconds between heartbeat emissions while an attempt is running.
        Defaults to 30s (spec.md § Live progress contract). Inject a
        shorter value in tests so you don't wait 30 seconds per heartbeat.
    """

    def __init__(self, heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL) -> None:
        self._interval = heartbeat_interval

    # ── Public API ──────────────────────────────────────────────────────

    def emit_start(
        self,
        *,
        idx: int,
        total: int,
        candidate: str,
        task: str,
        attempt: int,
    ) -> None:
        """Emit the attempt-start line."""
        _emit(f"[{idx}/{total}] {candidate}  {task}  attempt {attempt}  starting...")

    def emit_heartbeat(
        self,
        *,
        idx: int,
        total: int,
        candidate: str,
        task: str,
        attempt: int,
        elapsed_seconds: float,
    ) -> None:
        """Emit one heartbeat line."""
        n = int(elapsed_seconds)
        _emit(f"[{idx}/{total}] {candidate}  {task}  attempt {attempt}  running... {n}s elapsed")

    def emit_end(
        self,
        *,
        idx: int,
        total: int,
        candidate: str,
        task: str,
        attempt: int,
        result: str,
        elapsed_seconds: float,
        tool_calls: int = 0,
    ) -> None:
        """Emit the attempt-end line.

        result is one of "pass", "fail", "error", or "timeout".
        """
        s = round(elapsed_seconds, 1)
        if result == "pass":
            detail = f"pass ({s}s, {tool_calls} tool calls)"
        elif result == "fail":
            detail = f"fail ({s}s, {tool_calls} tool calls)"
        elif result == "timeout":
            detail = f"timeout after {s}s — skipping"
        else:
            # "error" or any unexpected value
            detail = f"error ({s}s)"
        _emit(f"[{idx}/{total}] {candidate}  {task}  attempt {attempt}  {detail}")

    # ── Heartbeat context ───────────────────────────────────────────────

    def run_heartbeat(
        self,
        *,
        stop_event: threading.Event,
        started_at: float,
        idx: int,
        total: int,
        candidate: str,
        task: str,
        attempt: int,
    ) -> None:
        """Target function for the daemon heartbeat thread.

        Emits a heartbeat every ``self._interval`` seconds while
        ``stop_event`` is not set. Returns immediately once the event
        is set. Designed to be run in a daemon thread so it cannot
        outlive the orchestrator process even if join() is skipped in
        extreme cases.

        Never raises into the caller — exceptions are silently swallowed
        so a progress-system failure cannot crash an otherwise-healthy run.
        """
        try:
            while not stop_event.wait(timeout=self._interval):
                try:
                    elapsed = time.monotonic() - started_at
                    self.emit_heartbeat(
                        idx=idx,
                        total=total,
                        candidate=candidate,
                        task=task,
                        attempt=attempt,
                        elapsed_seconds=elapsed,
                    )
                except Exception:  # noqa: BLE001
                    pass  # never crash the heartbeat loop
        except Exception:  # noqa: BLE001
            pass  # never propagate into the spawning thread


# ── Module-level helper ─────────────────────────────────────────────────


def _emit(line: str) -> None:
    """Write one progress line to stderr, flushed immediately."""
    print(line, file=sys.stderr, flush=True)
