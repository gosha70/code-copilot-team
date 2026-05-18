# benchmarks.adapters.swe_bench_verified.adapter — SWE-bench Verified adapter.
#
# Implements the BenchmarkAdapter contract (scripts/benchmark_runner/contracts.py)
# for the princeton-nlp/SWE-bench_Verified dataset.
#
# Each task is one SWE-bench "instance": a real GitHub issue against a
# Python repository. The adapter:
#   - lists tasks from the pinned JSONL cache (populated by fetch.py);
#   - uses the docker isolation tier with the task's prebuilt image;
#   - materializes the repo at base_commit in prepare_task;
#   - sends the problem_statement as the single-shot prompt;
#   - verifies by running FAIL_TO_PASS + PASS_TO_PASS test sets
#     in-container via isolation.run_in_worktree;
#   - provides the dataset's reference patch as golden_patch.
#
# Docker-tier caveat: images are multi-GB each. This adapter is local-only;
# it is NOT run in CI (which uses the stub tier). See benchmarks/README.md
# for image-size notes and the update procedure.

from __future__ import annotations

import json
import logging
import platform
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from benchmark_runner.contracts import (
    ISOLATION_DOCKER,
    BenchmarkAdapter,
    IsolationConfig,
    IsolationTier,
    TaskSpec,
    VerifyResult,
)
from benchmark_runner import isolation as _isolation

from . import fetch

_log = logging.getLogger(__name__)

BENCHMARK_ID = "swe-bench-verified"

# Timeout for running the in-container test suites.
_VERIFY_TIMEOUT_SECONDS = 300

# Container path where the worktree is mounted.
_CONTAINER_WORKDIR = "/testbed"


# SWE-bench eval images install the instance's deps (incl. pytest)
# into a conda env named ``testbed`` — NOT the base interpreter on
# PATH (bare `python -m pytest` → "No module named pytest", proven by
# the real run). Tests must run through that env.
_TESTBED_ACTIVATE = "source /opt/miniconda3/bin/activate testbed"


def _pytest_cmd(tests: list[str]) -> list[str]:
    """In-container argv that activates the SWE-bench ``testbed`` conda
    env then runs pytest over ``tests`` (shell-quoted)."""
    joined = " ".join(shlex.quote(t) for t in tests)
    return [
        "bash", "-lc",
        f"{_TESTBED_ACTIVATE} && python -m pytest --tb=short -q {joined}",
    ]


def _swebench_arch() -> str:
    """SWE-bench publishes per-arch image sets. Apple Silicon / ARM
    hosts use the ``arm64`` set; everything else ``x86_64``."""
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def _swebench_image(instance_id: str) -> str:
    """Resolvable SWE-bench eval image reference for ``instance_id``.

    Derived at RUNTIME (not frozen in the host-agnostic dataset cache):
    SWE-bench's published images encode ``__`` as ``_1776_`` and are
    arch-specific, e.g.
    ``swebench/sweb.eval.arm64.psf_1776_requests-1142:latest``
    (empirically verified against Docker Hub 2026-05-18; the earlier
    derived ``sweb.eval.x86_64.<id with __>`` name does not exist).
    """
    enc = instance_id.replace("__", "_1776_")
    return f"swebench/sweb.eval.{_swebench_arch()}.{enc}:latest"


class SweBenchVerifiedAdapter:
    """Adapter for the pinned SWE-bench Verified dataset.

    Construct with ``cache_file=None`` (default) to use the cache
    populated by ``fetch.ensure_cached``. Tests pass an explicit path
    to a synthetic JSONL fixture so they don't depend on the real dataset.
    """

    benchmark_id = BENCHMARK_ID
    isolation_default: IsolationTier = ISOLATION_DOCKER

    def __init__(self, cache_file: Optional[Path] = None) -> None:
        self._cache_file = (
            Path(cache_file) if cache_file is not None else fetch.cache_file()
        )

    # ── Required protocol methods ──────────────────────────────────────

    def list_tasks(self) -> list[TaskSpec]:
        if not self._cache_file.is_file():
            return []

        out: list[TaskSpec] = []
        with self._cache_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    _log.warning("swe-bench-verified: skipping malformed JSONL line: %r", line[:80])
                    continue
                spec = _row_to_task_spec(row)
                if spec is not None:
                    out.append(spec)
        return out

    def isolation_for(self, task: TaskSpec) -> IsolationConfig:
        """Each SWE-bench task runs in its own prebuilt Docker image.

        The host worktree is bind-mounted OVER the image's repo dir
        (``/testbed``) — not the generic ``/workspace`` — so that backend
        edits made on the host land where the image's editable install
        and the tests resolve (Design Decision 10).
        """
        return IsolationConfig(
            tier=ISOLATION_DOCKER,
            image=task.metadata["image"],
            container_mount=_CONTAINER_WORKDIR,
        )

    def prepare_task(self, task: TaskSpec, worktree: Path) -> None:
        """Materialize the repo at base_commit into the host worktree.

        Design Decision 10: the docker tier has already started the
        attempt container with this (currently empty) host worktree
        bind-mounted OVER the image's repo dir (``/testbed``). We copy
        the image's pristine ``/testbed`` (the repo at base_commit, with
        the editable install pointing there) OUT of a throwaway
        container of the same image and INTO the host worktree. The
        live attempt container then sees the repo at ``/testbed`` via
        the bind mount; the backend edits the host worktree; ``verify``
        runs the test sets at ``/testbed`` where the edits + deps
        resolve.

        This corrects the original metadata-only stub, under which a
        backend's fix could never reach the scored location.
        """
        image = task.metadata["image"]

        created = subprocess.run(
            ["docker", "create", image],
            capture_output=True, text=True, check=False,
        )
        if created.returncode != 0 or not created.stdout.strip():
            raise RuntimeError(
                f"swe-bench prepare_task: `docker create {image}` failed "
                f"(exit {created.returncode}): "
                f"{(created.stderr or created.stdout).strip()}"
            )
        scratch = created.stdout.strip()
        try:
            # `/testbed/.` → copy the directory *contents* into worktree.
            cp = subprocess.run(
                ["docker", "cp", f"{scratch}:/testbed/.", str(worktree)],
                capture_output=True, text=True, check=False,
            )
            if cp.returncode != 0:
                raise RuntimeError(
                    f"swe-bench prepare_task: `docker cp {scratch}:/testbed/.` "
                    f"failed (exit {cp.returncode}): "
                    f"{(cp.stderr or cp.stdout).strip()}"
                )
        finally:
            subprocess.run(
                ["docker", "rm", "-f", scratch],
                capture_output=True, text=True, check=False,
            )

        # Instance metadata for the backend to reference (additive; the
        # repo files now populate the worktree alongside it).
        meta = {
            "instance_id": task.task_id,
            "repo": task.metadata.get("repo", ""),
            "base_commit": task.metadata.get("base_commit", ""),
            "FAIL_TO_PASS": task.metadata.get("FAIL_TO_PASS", []),
            "PASS_TO_PASS": task.metadata.get("PASS_TO_PASS", []),
        }
        (worktree / "swe_bench_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

    def prompt_for(
        self,
        task: TaskSpec,
        attempt: int,
        prior: Optional[VerifyResult],
    ) -> str:
        """Single-shot prompt: the issue's problem statement + repo context."""
        repo = task.metadata.get("repo", "unknown/repo")
        base_commit = task.metadata.get("base_commit", "")
        problem = task.metadata.get("problem_statement", "")
        hints = task.metadata.get("hints_text", "")
        fail_to_pass = task.metadata.get("FAIL_TO_PASS", [])
        pass_to_pass = task.metadata.get("PASS_TO_PASS", [])

        parts = [
            f"# SWE-bench Task: {task.task_id}",
            "",
            f"Repository: `{repo}`",
            f"Base commit: `{base_commit}`",
            "",
            "## Problem Statement",
            "",
            problem,
            "",
        ]

        if hints:
            parts += [
                "## Hints",
                "",
                hints,
                "",
            ]

        parts += [
            "## Your Task",
            "",
            "Fix the bug described in the problem statement. The repository is",
            f"available at `/testbed` inside the container.",
            "",
            "Tests that MUST PASS after your fix (currently failing):",
        ]
        for t in fail_to_pass:
            parts.append(f"  - `{t}`")

        if pass_to_pass:
            parts += [
                "",
                "Tests that must NOT regress (currently passing):",
            ]
            for t in pass_to_pass:
                parts.append(f"  - `{t}`")

        parts += [
            "",
            "Edit the source files in `/testbed` to fix the issue.",
            "Do NOT modify test files.",
        ]

        return "\n".join(parts).rstrip() + "\n"

    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult:
        """Run FAIL_TO_PASS + PASS_TO_PASS test sets in the container.

        Routes through isolation.run_in_worktree so the tests execute
        in the docker container (where /testbed has the repo + deps)
        rather than locally (where the repo is not present).

        Scoring:
          - tests_passed = all FAIL_TO_PASS pass AND no PASS_TO_PASS regressions.
        """
        fail_to_pass = task.metadata.get("FAIL_TO_PASS", [])
        pass_to_pass = task.metadata.get("PASS_TO_PASS", [])

        all_tests = list(fail_to_pass) + list(pass_to_pass)
        if not all_tests:
            return VerifyResult(
                tests_passed=False,
                tests_output="verify: no test cases in FAIL_TO_PASS or PASS_TO_PASS",
            )

        # Canonical SWE-bench eval order (base /testbed from
        # prepare_task's docker-cp): (1) apply the instance TEST patch
        # so the FAIL_TO_PASS/PASS_TO_PASS tests exist (proven: without
        # it pytest reports "not found"); (2) the SOLUTION is already in
        # /testbed — real backends edited it; the stub's gold.patch is
        # applied just below; (3) run the test sets in the testbed env.
        test_patch = task.metadata.get("test_patch", "")
        if test_patch:
            (worktree / "__swebench_test__.patch").write_text(
                test_patch, encoding="utf-8"
            )
            tp = _isolation.run_in_worktree(
                worktree,
                ["sh", "-c",
                 "git apply -v __swebench_test__.patch "
                 "|| patch -p1 < __swebench_test__.patch"],
                timeout=_VERIFY_TIMEOUT_SECONDS,
                cwd=_CONTAINER_WORKDIR,
            )
            _isolation.run_in_worktree(
                worktree, ["rm", "-f", "__swebench_test__.patch"],
                timeout=30, cwd=_CONTAINER_WORKDIR,
            )
            if tp.returncode != 0:
                return VerifyResult(
                    tests_passed=False,
                    tests_output=(
                        "verify: failed to apply test_patch in-container:\n"
                        + (tp.stdout + tp.stderr).strip()
                    ),
                    failed_commands=1,
                )

        # Stub-parity (gold-as-diff vs stub-copies-tree reconciliation,
        # Design Decision 10): SWE-bench's gold solution is a *diff*,
        # not a tree, and the per-instance eval image already carries
        # the instance's tests at /testbed. The stub backend places
        # ``gold.patch`` (from golden_patch) at the worktree root; apply
        # it IN-CONTAINER at /testbed so the gold solution is present
        # before scoring, then remove it. Real backends (claude-code/
        # codex) edit the worktree directly and leave no gold.patch —
        # this block is a no-op for them.
        if (worktree / "gold.patch").is_file():
            apply_proc = _isolation.run_in_worktree(
                worktree,
                ["sh", "-c",
                 "git apply -v gold.patch || patch -p1 < gold.patch"],
                timeout=_VERIFY_TIMEOUT_SECONDS,
                cwd=_CONTAINER_WORKDIR,
            )
            if apply_proc.returncode != 0:
                return VerifyResult(
                    tests_passed=False,
                    tests_output=(
                        "verify: failed to apply gold.patch in-container:\n"
                        + (apply_proc.stdout + apply_proc.stderr).strip()
                    ),
                    failed_commands=1,
                )
            _isolation.run_in_worktree(
                worktree, ["rm", "-f", "gold.patch"],
                timeout=30, cwd=_CONTAINER_WORKDIR,
            )

        # Run the full test suite in-container via the testbed env.
        argv = _pytest_cmd(all_tests)

        try:
            proc = _isolation.run_in_worktree(
                worktree,
                argv,
                timeout=_VERIFY_TIMEOUT_SECONDS,
                cwd=_CONTAINER_WORKDIR,
            )
        except subprocess.TimeoutExpired:
            return VerifyResult(
                tests_passed=False,
                tests_output=f"verify: in-container pytest timed out after {_VERIFY_TIMEOUT_SECONDS}s",
                failed_commands=1,
            )

        output = (proc.stdout + proc.stderr).strip()
        passed = proc.returncode == 0

        # Check for PASS_TO_PASS regressions specifically when the full
        # run passed (exit 0 with no FAIL_TO_PASS tests would be unusual
        # but we handle it defensively).
        if passed and pass_to_pass:
            # A regression means something in pass_to_pass now fails.
            # Re-run pass_to_pass only to confirm no regression.
            pass_proc = _isolation.run_in_worktree(
                worktree,
                _pytest_cmd(list(pass_to_pass)),
                timeout=_VERIFY_TIMEOUT_SECONDS,
                cwd=_CONTAINER_WORKDIR,
            )
            if pass_proc.returncode != 0:
                regression_output = (pass_proc.stdout + pass_proc.stderr).strip()
                return VerifyResult(
                    tests_passed=False,
                    tests_output=(
                        f"PASS_TO_PASS regression:\n{regression_output}\n\n"
                        f"Full test output:\n{output}"
                    ),
                    failed_commands=1,
                )

        return VerifyResult(
            tests_passed=passed,
            tests_output=output,
            failed_commands=0 if passed else 1,
        )

    def golden_patch(self, task: TaskSpec) -> Path:
        """Write the dataset's reference patch to a golden dir and return it.

        Used by the stub backend for local parity testing. The patch is
        the gold-standard fix from the SWE-bench dataset.
        """
        golden_root = self._golden_root()
        golden_dir = golden_root / task.task_id.replace("/", "__")
        if not golden_dir.exists():
            golden_dir.mkdir(parents=True)
            patch_text = task.metadata.get("patch", "")
            (golden_dir / "gold.patch").write_text(patch_text, encoding="utf-8")
        return golden_dir

    def max_attempts(self) -> int:
        # SWE-bench is single-shot: the model gets one attempt.
        return 1

    # ── Helpers ────────────────────────────────────────────────────────

    def _golden_root(self) -> Path:
        return self._cache_file.parent.parent.parent / "swe-bench-verified-golden"


def _row_to_task_spec(row: dict) -> Optional[TaskSpec]:
    """Convert a normalized JSONL row to a TaskSpec."""
    instance_id = row.get("instance_id")
    if not instance_id:
        return None

    # FAIL_TO_PASS and PASS_TO_PASS are stored as JSON-encoded strings in the HF dataset.
    fail_to_pass = _parse_test_list(row.get("FAIL_TO_PASS", "[]"))
    pass_to_pass = _parse_test_list(row.get("PASS_TO_PASS", "[]"))

    return TaskSpec(
        task_id=instance_id,
        language="python",  # SWE-bench is Python-only
        metadata={
            # Derived at runtime (host arch + _1776_ encoding) — NOT the
            # stale host-agnostic name fetch.py may have cached.
            "image": _swebench_image(instance_id),
            "base_commit": row.get("base_commit", ""),
            "FAIL_TO_PASS": fail_to_pass,
            "PASS_TO_PASS": pass_to_pass,
            "problem_statement": row.get("problem_statement", ""),
            "hints_text": row.get("hints_text", ""),
            "repo": row.get("repo", ""),
            "patch": row.get("patch", ""),
            "test_patch": row.get("test_patch", ""),
            "environment_setup_commit": row.get("environment_setup_commit", ""),
        },
    )


def _parse_test_list(value: str | list) -> list[str]:
    """Parse a test list that may be a JSON string or already a list."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except json.JSONDecodeError:
            pass
    return []


def register() -> None:
    """Idempotent registration entry for this adapter.

    Called by scripts/benchmark_runner/_register.py:register_all.
    See benchmarks/adapters/stub/adapter.py for the import-time
    side-effect rationale.
    """
    from benchmark_runner.registry import register_adapter
    register_adapter(BENCHMARK_ID, SweBenchVerifiedAdapter)


# Module-level type-check (does not register).
assert isinstance(
    SweBenchVerifiedAdapter(cache_file=Path("/nonexistent.jsonl")), BenchmarkAdapter
)
