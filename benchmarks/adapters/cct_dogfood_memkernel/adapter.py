# benchmarks.adapters.cct_dogfood_memkernel.adapter — Gate 2 dogfood adapter.
#
# Snapshots the memkernel repo at the SHA pinned in REVISION and exposes a
# single task: ``memory-brain-spec``. The task prompt is the verbatim body of
# memkernel#3 ("Define MemKernel Memory Brain Architecture"), which is a
# spec-first issue — the agent's only deliverable is
# ``specs/memory-brain/spec.md``.
#
# Verify (see ``tasks/memory-brain-spec/verify.sh``) is split into hard
# checks and best-effort checks:
#
#   Hard (failure => verify_passes=False):
#     1. ``specs/memory-brain/spec.md`` exists.
#     2. The seven required section headers are present.
#     3. ``pyproject.toml`` is byte-for-byte unchanged (no new deps).
#     4. ``src/memkernel/mcp/`` is unchanged (no MCP code lands).
#
#   Best-effort (skipped if toolchain absent, fail if present + broken):
#     5. ``pytest`` passes (memkernel suite, no regression).
#     6. ``ruff check`` clean.
#     7. ``mypy src/`` clean.
#
# The hard checks are sufficient to demonstrate the harness can produce a
# correct verdict on a real, fresh, forward-looking copilot task. The
# best-effort checks reinforce the verdict when the toolchain happens to
# be installed in the worktree's venv.
#
# Why best-effort and not hard for the toolchain checks: memkernel's
# runtime stack (chromadb, sentence-transformers, tree-sitter) is heavy
# and slow to install in a fresh per-attempt venv. Forcing the full install
# would tie the dogfood gate to multi-minute setup latency on every
# attempt, and to network availability. Static spec-correctness is the
# load-bearing assertion; toolchain reinforcement is icing.

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from benchmark_runner.contracts import (
    ISOLATION_WORKTREE_VENV,
    BenchmarkAdapter,
    IsolationConfig,
    IsolationTier,
    TaskSpec,
    VerifyResult,
)

BENCHMARK_ID = "cct-dogfood-memkernel"
TASK_ID = "memory-brain-spec"

# Default location for the memkernel local clone. Override with
# ``CCT_MEMKERNEL_PATH`` for CI / different developer layouts.
DEFAULT_MEMKERNEL_PATH = "~/dev/repo/memkernel"
MEMKERNEL_PATH_ENV = "CCT_MEMKERNEL_PATH"

_HERE = Path(__file__).resolve().parent
_REVISION_FILE = _HERE / "REVISION"
_TASK_DIR = _HERE / "tasks" / TASK_ID
_PROMPT_FILE = _TASK_DIR / "prompt.md"
_VERIFY_SCRIPT = _TASK_DIR / "verify.sh"

# Files / paths captured under .cct-baseline/ so verify.sh can diff
# against them. The baseline is invariant for the dogfood task — the
# agent must not modify either of these.
_BASELINE_DIR_NAME = ".cct-baseline"


def memkernel_clone_path() -> Path:
    """Return the host's memkernel clone path (env override + tilde-expand)."""
    raw = os.environ.get(MEMKERNEL_PATH_ENV) or DEFAULT_MEMKERNEL_PATH
    return Path(os.path.expanduser(raw))


def pinned_revision() -> str:
    sha = _REVISION_FILE.read_text(encoding="utf-8").strip()
    if not sha:
        raise RuntimeError(f"REVISION file is empty: {_REVISION_FILE}")
    return sha


class CctDogfoodMemkernelAdapter:
    """Spec-first dogfood adapter targeting memkernel#3."""

    benchmark_id = BENCHMARK_ID
    isolation_default: IsolationTier = ISOLATION_WORKTREE_VENV

    def list_tasks(self) -> list[TaskSpec]:
        # Empty list when the memkernel clone is missing — matches the
        # polyglot adapter's missing-cache pattern. The CLI surfaces
        # this as EmptyAdapterError with a hint pointing at this
        # adapter's README entry (set CCT_MEMKERNEL_PATH or clone to
        # ~/dev/repo/memkernel).
        if not memkernel_clone_path().is_dir():
            return []
        return [
            TaskSpec(
                task_id=TASK_ID,
                language="python",
                metadata={
                    "memkernel_revision": pinned_revision(),
                    "memkernel_path": str(memkernel_clone_path()),
                    # Solution path the agent must produce. Recorded
                    # for the run record; verify.sh checks it directly.
                    "solution_files": ["specs/memory-brain/spec.md"],
                },
            )
        ]

    def isolation_for(self, task: TaskSpec) -> IsolationConfig:
        # worktree+venv with a stripped-down install: just the static
        # tooling (ruff, mypy, pytest). Memkernel's runtime deps
        # (chromadb, sentence-transformers, tree-sitter, fastapi) are
        # NOT installed — see the module docstring on why best-effort
        # is the right tradeoff for this gate. If the install_command
        # fails (no network etc.), the harness records the error and
        # verify still runs the hard checks unchanged.
        return IsolationConfig(
            tier=ISOLATION_WORKTREE_VENV,
            python="python3",
            # Drop `--quiet` so transient-network warnings surface;
            # verify_imports below catches "exit 0 but nothing installed".
            install_command="pip install ruff mypy pytest pytest-asyncio",
            verify_imports=("pytest", "ruff", "mypy"),
        )

    def prepare_task(self, task: TaskSpec, worktree: Path) -> None:
        # 1. Snapshot memkernel at the pinned SHA into the worktree.
        sha = pinned_revision()
        clone = memkernel_clone_path()
        if not clone.is_dir():
            raise RuntimeError(
                f"memkernel clone not found at {clone!r}. "
                f"Set {MEMKERNEL_PATH_ENV} or clone to {DEFAULT_MEMKERNEL_PATH}."
            )

        # ``git archive | tar -x`` produces a deterministic snapshot
        # (no .git, no untracked files) of exactly the pinned tree.
        archive = subprocess.Popen(
            ["git", "-C", str(clone), "archive", "--format=tar", sha],
            stdout=subprocess.PIPE,
        )
        try:
            extract = subprocess.run(
                ["tar", "-x", "-C", str(worktree)],
                stdin=archive.stdout,
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            if archive.stdout is not None:
                archive.stdout.close()
            archive.wait()
        if archive.returncode != 0 or extract.returncode != 0:
            raise RuntimeError(
                f"git archive at {sha!r} from {clone!r} failed "
                f"(archive rc={archive.returncode}, extract rc={extract.returncode}, "
                f"stderr={extract.stderr!r})"
            )

        # 2. Capture baseline for the "no new deps" / "no new MCP code"
        # checks. The agent must not modify either path; verify.sh
        # diffs against this snapshot.
        baseline = worktree / _BASELINE_DIR_NAME
        baseline.mkdir(exist_ok=False)
        shutil.copy2(worktree / "pyproject.toml", baseline / "pyproject.toml")
        mcp_src = worktree / "src" / "memkernel" / "mcp"
        if mcp_src.is_dir():
            shutil.copytree(mcp_src, baseline / "mcp")

        # 3. Place verify.sh at a known location the runner can invoke.
        verify_dst = worktree / ".cct-verify.sh"
        shutil.copy2(_VERIFY_SCRIPT, verify_dst)
        verify_dst.chmod(0o755)

    def prompt_for(
        self,
        task: TaskSpec,
        attempt: int,
        prior: Optional[VerifyResult],
    ) -> str:
        # Single-shot adapter; ``attempt`` and ``prior`` are unused.
        #
        # The prompt is composed of two parts:
        #   1. A small framing header (working directory + deliverable
        #      path) so the agent knows the operational context. This
        #      mirrors the polyglot adapter's prompt-framing pattern.
        #   2. The verbatim memkernel#3 body. The "verbatim" rule the
        #      pitch directive named applies to the issue content — we
        #      do not paraphrase or summarise it.
        body = _PROMPT_FILE.read_text(encoding="utf-8")
        header_lines = [
            f"# {BENCHMARK_ID} :: {task.task_id}",
            "",
            "You are working in a checkout of the memkernel repository "
            f"pinned to commit `{pinned_revision()}`.",
            "",
            "## Your task",
            "",
            "Author the spec deliverable described below. Write it to:",
            "",
            "  - `specs/memory-brain/spec.md`",
            "",
            "This is a **spec-first** issue: do NOT add code, dependencies, "
            "or new MCP tools. The deliverable is the spec file alone. The "
            "verifier will check that:",
            "",
            "  - `specs/memory-brain/spec.md` exists.",
            "  - It contains the seven required section headers listed "
            "in §7 (Acceptance Criteria) below.",
            "  - `pyproject.toml` is unchanged (no new deps).",
            "  - `src/memkernel/mcp/` is unchanged (no new MCP code).",
            "",
            "## Issue body (verbatim)",
            "",
        ]
        return "\n".join(header_lines) + body

    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult:
        verify_script = worktree / ".cct-verify.sh"
        if not verify_script.is_file():
            return VerifyResult(
                tests_passed=False,
                tests_output=(
                    f"verify: missing {verify_script} — prepare_task did not "
                    f"copy the verify script"
                ),
                required_files_present=False,
            )

        proc = subprocess.run(
            ["bash", str(verify_script)],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        passed = proc.returncode == 0
        output = (proc.stdout + proc.stderr).strip()

        # Granular signal: the verify script tags ruff/mypy lines so
        # we can populate VerifyResult.lint_passed / typecheck_passed
        # without parsing arbitrary tool output. None means "skipped"
        # (toolchain not present in the venv).
        lint_passed = _scan_check_status(output, "ruff")
        typecheck_passed = _scan_check_status(output, "mypy")

        spec_path = worktree / "specs" / "memory-brain" / "spec.md"
        return VerifyResult(
            tests_passed=passed,
            tests_output=output,
            lint_passed=lint_passed,
            typecheck_passed=typecheck_passed,
            required_files_present=spec_path.is_file(),
            failed_commands=0 if passed else 1,
        )

    def golden_patch(self, task: TaskSpec) -> Path:
        # Spec-first dogfood: the agent's job is to author
        # specs/memory-brain/spec.md from the issue body. There is no
        # canonical reference spec — every passing run is a different
        # valid artifact. The stub backend cannot exercise this
        # adapter; CI does not run it.
        raise NotImplementedError(
            f"{BENCHMARK_ID}: no golden patch (spec-first dogfood). "
            f"Run with --backend claude-code, not stub."
        )

    def max_attempts(self) -> int:
        # Single-shot. There is no deterministic regression to
        # iterate against; if the agent missed sections on attempt 1,
        # re-prompting with verify output would just paper over a
        # weak first attempt. We measure the first-shot behaviour.
        return 1


def _scan_check_status(output: str, label: str) -> Optional[bool]:
    """Parse verify.sh output for the named check.

    verify.sh tags each result with one of three glyphs:
      ✓ <label>: …  → True
      ✗ <label>: …  → False
      - <label>: …  → None (skipped)

    The runner only needs to surface the latest occurrence; ruff and
    mypy each have one line by design.
    """
    last: Optional[bool] = None
    for line in output.splitlines():
        if label not in line:
            continue
        if "✓" in line:
            last = True
        elif "✗" in line:
            last = False
        elif "-" in line:
            last = None
    return last


def register() -> None:
    """Register the adapter with the runtime registry. Idempotent."""
    from benchmark_runner.registry import register_adapter
    register_adapter(BENCHMARK_ID, CctDogfoodMemkernelAdapter)


# Module-level type-check (does not register).
assert isinstance(CctDogfoodMemkernelAdapter(), BenchmarkAdapter)
