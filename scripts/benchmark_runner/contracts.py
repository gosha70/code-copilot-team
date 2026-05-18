# benchmark_runner.contracts — adapter, backend, and run-record contracts.
#
# The harness is benchmark-agnostic: any benchmark (Aider Polyglot,
# SWE-bench Verified, BigCodeBench, LiveCodeBench, custom CCT fixtures)
# implements ``BenchmarkAdapter``. Any copilot/model implementation
# (Claude Code headless, vLLM HTTP, stub) implements ``Backend``.
#
# The harness owns isolation, run records, scoring, and reports. The
# adapter owns "what is a task in this benchmark and how do I check it."
# The backend owns "given a prompt and a worktree, run the model and
# report what it produced." This split is the durable contract surface
# of the MVP — if a new adapter or backend cannot fit it, that is a
# regression to fix here, not an extension elsewhere.
#
# All dataclasses are frozen — run records must not mutate after capture.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Protocol, runtime_checkable


# ── Identifier / enum constants ────────────────────────────────────────
# Use these everywhere instead of bare strings so renames are caught by
# the type checker rather than by surprise at runtime.

ISOLATION_WORKTREE = "worktree"
ISOLATION_WORKTREE_VENV = "worktree+venv"
ISOLATION_DOCKER = "docker"

IsolationTier = Literal["worktree", "worktree+venv", "docker"]

RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_ERROR = "error"
RESULT_TIMEOUT = "timeout"

RunResult = Literal["pass", "fail", "error", "timeout"]


# ── Task + verify primitives ───────────────────────────────────────────


@dataclass(frozen=True)
class TaskSpec:
    """One task as exposed by a ``BenchmarkAdapter``.

    ``task_id`` is opaque to the harness; the adapter chooses any
    convention as long as it is unique within the adapter and stable
    across invocations (Aider Polyglot uses ``"<lang>/<exercise>"``).
    """

    task_id: str
    language: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IsolationConfig:
    """Isolation directive resolved per task by ``BenchmarkAdapter.isolation_for``.

    Adapters that don't vary isolation per task can return
    ``IsolationConfig(tier=adapter.isolation_default)`` from
    ``isolation_for`` (this is what the protocol's default-shaped
    behavior produces). Multi-language adapters (Aider Polyglot) override
    to return ``worktree+venv`` for Python tasks and ``worktree`` for
    languages whose toolchains are managed at host level.

    Fields beyond ``tier`` are tier-specific; the runner reads only
    those that match the chosen tier and records all of them in
    ``run-record.json``'s ``isolation`` block for audit.
    """

    tier: "IsolationTier"  # forward-ref to keep the alias close to its consumers
    python: Optional[str] = None
    install_command: Optional[str] = None
    # Packages that MUST be importable after ``install_command`` runs.
    # The harness invokes ``<venv>/bin/python -c "import <name>"`` for
    # each entry; failure raises ``IsolationProvisionError``. This
    # closes the "pip silently no-op'd but exited 0" failure mode
    # discovered on 2026-05-15: a network hiccup can make pip return
    # success without actually installing anything, and `pip install
    # -q` suppresses the warning. The import check is the ground
    # truth — if the module is importable, the install actually worked.
    verify_imports: tuple[str, ...] = ()
    dockerfile: Optional[Path] = None
    build_args: Mapping[str, str] = field(default_factory=dict)
    # docker tier only: prebuilt image reference to pull before starting the
    # attempt container (e.g. "swebench/sweb.eval.x86_64.<instance_id>").
    # Ignored by the worktree and worktree+venv tiers.
    image: Optional[str] = None
    # docker tier: in-container path the host worktree is bind-mounted
    # at. Defaults to "/workspace"; adapters whose image keeps the repo
    # elsewhere (SWE-bench: "/testbed", deps editable-installed there)
    # set this so backend edits land where the tests + install resolve.
    # Ignored by the worktree and worktree+venv tiers.
    container_mount: Optional[str] = None


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of running an adapter's verify pass on a worktree.

    ``None`` means "this adapter does not produce this signal." It is
    distinct from ``False`` (signal produced and failed). Reports must
    preserve this distinction; never coerce ``None`` to ``False``.
    """

    tests_passed: bool
    tests_output: str
    lint_passed: Optional[bool] = None
    typecheck_passed: Optional[bool] = None
    required_files_present: bool = True
    failed_commands: int = 0


# ── Backend invocation primitives ──────────────────────────────────────


@dataclass(frozen=True)
class RunContext:
    """Per-attempt context handed to a backend.

    Carries everything the backend needs that is independent of the
    prompt content itself — the worktree path, the model identifier,
    deterministic-control parameters, and a timeout budget.
    """

    benchmark_id: str
    task_id: str
    backend_id: str
    run_id: str
    attempt: int
    worktree: Path
    model: str
    temperature: float = 0.0
    seed: Optional[int] = None
    timeout_seconds: Optional[int] = None


@dataclass(frozen=True)
class BackendResult:
    """What a backend produced on one attempt.

    Token counts and cache fields are ``Optional[int]`` because not all
    backends report them. ``None`` means "backend did not provide";
    ``0`` means "backend reported zero." Reports must preserve this.

    The runner always writes the harness-provided prompt to
    ``<attempt>/prompt.md`` before calling ``Backend.run`` and records
    the path + sha256 in ``run-record.json``. If the backend wraps or
    rewrites the prompt before sending it (Claude Code's headless mode
    appends a system prompt; some adapters add framing), the backend
    SHOULD also write the post-wrap "effective prompt" to disk and
    return its path here. Backends that do not wrap leave
    ``prompt_path`` as ``None`` — the runner records only the canonical
    harness prompt.

    ``model_output_path`` is the model's raw text response, distinct
    from ``transcript_path`` (which may be backend-specific structured
    log, e.g. Claude Code's JSON transcript). Backends that have no
    separate text output (only the worktree mutations) leave it
    ``None``.
    """

    transcript_path: Optional[Path]
    elapsed_seconds: float
    prompt_path: Optional[Path] = None
    model_output_path: Optional[Path] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None
    tool_calls: Mapping[str, int] = field(default_factory=dict)
    failed_commands: int = 0
    backend_metadata: Mapping[str, Any] = field(default_factory=dict)


# ── Protocols ──────────────────────────────────────────────────────────


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """Contract every benchmark adapter must satisfy.

    Implementations live under ``benchmarks/adapters/<id>/adapter.py``
    and are loaded via ``benchmark_runner.registry``.
    """

    benchmark_id: str
    isolation_default: IsolationTier

    def list_tasks(self) -> list[TaskSpec]: ...

    def isolation_for(self, task: TaskSpec) -> IsolationConfig:
        """Return the isolation directive for ``task``.

        Adapters that don't vary per task return
        ``IsolationConfig(tier=self.isolation_default)``. Multi-language
        adapters (Polyglot, future SWE-bench) override to vary tier
        and venv/docker config per language or per task.
        """

    def prepare_task(self, task: TaskSpec, worktree: Path) -> None:
        """Place starter files for ``task`` into ``worktree``."""

    def prompt_for(
        self,
        task: TaskSpec,
        attempt: int,
        prior: Optional[VerifyResult],
    ) -> str:
        """Build the prompt sent to the backend.

        ``attempt`` is 1-indexed. ``prior`` is the previous attempt's
        verify result when ``attempt > 1`` (Aider-style retry); ``None``
        on the first attempt. Single-shot adapters return the same
        prompt regardless of ``attempt``.
        """

    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult:
        """Run the adapter's verification pass on the post-backend worktree."""

    def golden_patch(self, task: TaskSpec) -> Path:
        """Path to the canonical correct implementation for ``task``.

        Used by the stub backend in CI. Adapters that have no golden
        patch raise ``NotImplementedError`` — the harness then refuses
        to run those tasks under the stub backend.
        """

    def max_attempts(self) -> int:
        """1 for single-shot adapters; 2 for Aider-style two-shot."""


@runtime_checkable
class Backend(Protocol):
    """Contract every backend must satisfy.

    Implementations live under
    ``scripts/benchmark_runner/backends/<id>.py`` and register via
    ``benchmark_runner.registry``.
    """

    backend_id: str

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        """Run one attempt against a prepared worktree.

        The backend mutates ``ctx.worktree`` to reflect the model's
        proposed solution. The adapter's ``verify`` is called next by
        the runner and produces the deterministic score.
        """
