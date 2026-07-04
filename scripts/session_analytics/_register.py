# session_analytics._register — explicit adapter + judge registration.
#
# One call per adapter — no auto-discovery, so the active set is grep-able
# from a single file. Mirrors benchmark_runner._register.
#
# The pipeline's primary target is Claude Code (the analyzer this tool
# implements). Aider is the secondary multi-copilot example. Kiro is NOT an
# adapter here — Kiro ingestion is already handled by the upstream
# kiro-analyzer this tool mirrors architecturally.
# Judges (M3): ``ollama`` (local-only default) and ``claude-code`` (reuses
# the benchmark headless invocation).

from __future__ import annotations

_REGISTERED = False


def register_all() -> None:
    """Idempotent. The CLI calls this once before parsing args."""
    global _REGISTERED
    if _REGISTERED:
        return

    from .adapters import claude_code as claude_code_adapter
    claude_code_adapter.register()
    from .adapters import aider as aider_adapter
    aider_adapter.register()

    # Judges (M3): ollama (local-only default) + claude-code (cloud opt-in).
    from .judge import _register as judge_register
    judge_register.register_all_judges()

    _REGISTERED = True


def unregister_all_for_tests() -> None:
    """Reset for test isolation. The test harness calls this."""
    global _REGISTERED
    from .registry import _reset_for_tests
    _reset_for_tests()
    try:
        from .judge.registry import _reset_for_tests as _reset_judges
        _reset_judges()
    except ImportError:
        pass
    _REGISTERED = False
