# benchmark_runner._register — explicit adapter+backend registration.
#
# Phase 1: ships ``stub`` adapter + ``stub`` backend.
# Phase 2 adds ``aider-polyglot`` adapter + the ``worktree+venv``
# isolation tier. Phase 3 adds the ``claude-code`` agent backend.
# Each registration is one line — no auto-discovery, so the active
# set is grep-able from a single file.
#
# vLLM/Ollama/LM Studio are NOT backends — they're providers, routed
# to via Claude Code's gateway env vars (ANTHROPIC_BASE_URL etc.).
# The harness *records* which provider a run used; it does not set
# the routing.

from __future__ import annotations

from .judge.registry import register_judge
from .registry import register_backend


# Judge family tokens accepted on the CLI. The canonical one is
# ``claude-code`` (per spec.md scenarios). ``claude-code-judge``
# is the internal ``judge_id`` recorded in judge.json; accepting
# it as an alias lets a user copy that value verbatim into a
# re-run command. Same factory, two tokens — register_judge
# tolerates the shared factory by design (see judge/registry.py).
_JUDGE_FAMILY_TOKENS = ("claude-code", "claude-code-judge")


_REGISTERED = False


def register_all() -> None:
    """Idempotent. The CLI calls this once before parsing args."""
    global _REGISTERED
    if _REGISTERED:
        return

    # Adapters: each adapter package exposes a ``register()`` function.
    # Calling it (rather than relying on module import side-effects)
    # ensures re-registration after a registry reset in tests works
    # correctly — Python imports each module only once per process,
    # so import-time side-effects fire exactly once.
    from benchmarks.adapters.stub.adapter import register as register_stub_adapter
    register_stub_adapter()
    from benchmarks.adapters.aider_polyglot.adapter import register as register_polyglot
    register_polyglot()
    from benchmarks.adapters.cct_dogfood_memkernel.adapter import register as register_cct_dogfood_memkernel
    register_cct_dogfood_memkernel()
    from benchmarks.adapters.swe_bench_verified.adapter import register as register_swe_bench_verified
    register_swe_bench_verified()

    # Backends: backend modules expose a ``factory`` function; we
    # register it here. Same one-call rule.
    from .backends import stub as stub_backend
    register_backend(stub_backend.BACKEND_FAMILY, stub_backend.factory)
    from .backends import claude_code as claude_code_backend
    register_backend(claude_code_backend.BACKEND_FAMILY, claude_code_backend.factory)
    from .backends import codex as codex_backend
    register_backend(codex_backend.BACKEND_FAMILY, codex_backend.factory)
    from .backends import aider as aider_backend
    register_backend(aider_backend.BACKEND_FAMILY, aider_backend.factory)

    # Judges (TB1.5). Each judge module exposes a ``factory``
    # function; register it under every accepted family token. The
    # shared factory makes ``claude-code`` and ``claude-code-judge``
    # behave identically on the CLI.
    from .judge import claude_code_judge
    for token in _JUDGE_FAMILY_TOKENS:
        register_judge(token, claude_code_judge.factory)

    _REGISTERED = True


def unregister_all_for_tests() -> None:
    """Reset for test isolation. The test harness calls this."""
    global _REGISTERED
    from .judge.registry import _reset_for_tests as _reset_judges
    from .registry import _reset_for_tests
    _reset_for_tests()
    _reset_judges()
    _REGISTERED = False
