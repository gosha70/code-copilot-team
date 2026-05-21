# benchmarks.adapters.bigcodebench.adapter — BigCodeBench adapter.
#
# Implements the BenchmarkAdapter contract for the bigcode/bigcodebench
# dataset (https://huggingface.co/datasets/bigcode/bigcodebench).
#
# Each task is one "BigCodeBench/N" instance: a function-completion
# challenge with a unittest TestCase that exercises the implemented
# function. The adapter:
#   - lists tasks from the pinned JSONL cache (populated by fetch.py);
#   - uses the worktree+venv tier so per-task pip installs (matplotlib,
#     pandas, sklearn, etc. — see ``libs`` field) don't pollute the host;
#   - prepare_task writes the starter file (``code_prompt``) as
#     ``task_func.py`` and the test as ``test_task_func.py``;
#   - prompts with ``instruct_prompt`` (single-shot);
#   - verifies by running ``python -m unittest test_task_func``;
#   - golden_patch writes the dataset's ``canonical_solution`` over the
#     starter file (combined with the ``code_prompt`` header).
#
# Library install caveat: BigCodeBench tasks reference a fixed set of
# libraries per task (the ``libs`` field). The default install_command
# is a pip-install of those libraries plus pytest; the harness's
# isolation-provisioning step pins this per-task. For tasks that
# reference heavyweight scientific libraries (sklearn, torch), the
# install may take 30s+; this is acceptable per-task overhead vs the
# alternative of a global heavyweight venv.

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from benchmark_runner.contracts import (
    ISOLATION_WORKTREE_VENV,
    BenchmarkAdapter,
    IsolationConfig,
    IsolationTier,
    TaskSpec,
    VerifyResult,
)
from benchmark_runner.isolation import run_in_worktree
from benchmark_runner.registry import register_adapter

from . import fetch

_log = logging.getLogger(__name__)

BENCHMARK_ID = "bigcodebench"

# Per-task install: pytest (for the unittest runner) + the task's
# referenced libs. Heavy libs (sklearn, scipy) make individual task
# installs slower; the harness's worktree+venv isolation means each
# task starts from a clean Python env.
_DEFAULT_PYTHON = "python3"
_BASE_INSTALL = "pip install -q pytest"


class BigCodeBenchAdapter:
    """BigCodeBench (Python function-completion) adapter."""

    benchmark_id = BENCHMARK_ID
    isolation_default: IsolationTier = ISOLATION_WORKTREE_VENV

    def __init__(self, cache_file: Optional[Path] = None) -> None:
        self._cache_file = (
            Path(cache_file) if cache_file is not None else fetch.cache_file()
        )

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
                    _log.warning(
                        "bigcodebench: skipping malformed JSONL line: %r",
                        line[:80],
                    )
                    continue
                spec = _row_to_task_spec(row)
                if spec is not None:
                    out.append(spec)
        return out

    def isolation_for(self, task: TaskSpec) -> IsolationConfig:
        """worktree+venv. install_command is pytest plus the task's
        declared libs (parsed from BigCodeBench's ``libs`` field)."""
        libs = task.metadata.get("libs", []) or []
        # Strip Python stdlib modules: BigCodeBench's ``libs`` field
        # includes stdlib (random, itertools, json, etc.) which pip
        # cannot install. The adapter conservatively keeps anything
        # not in this stdlib filter list.
        installable = [lib for lib in libs if lib not in _STDLIB_MODULES]
        install = _BASE_INSTALL
        if installable:
            install += " " + " ".join(installable)
        return IsolationConfig(
            tier=ISOLATION_WORKTREE_VENV,
            python=_DEFAULT_PYTHON,
            install_command=install,
            verify_imports=("pytest",),
        )

    def prepare_task(self, task: TaskSpec, worktree: Path) -> None:
        """Drop the starter file + test file into the worktree.

        Layout:
          task_func.py       — starter (BigCodeBench's ``code_prompt``)
          test_task_func.py  — verification tests (``test`` field)
        """
        code_prompt = task.metadata.get("code_prompt", "")
        test_block = task.metadata.get("test", "")
        (worktree / "task_func.py").write_text(code_prompt, encoding="utf-8")
        # Test file imports task_func from task_func.py. The
        # canonical BigCodeBench test block assumes the function
        # is in scope; we wrap it with an explicit ``from
        # task_func import *`` so the imports work in the test
        # subprocess regardless of how the model framed its file.
        test_text = (
            "import sys\nsys.path.insert(0, '.')\n"
            "from task_func import *  # noqa: F401,F403\n\n"
            f"{test_block}\n"
        )
        (worktree / "test_task_func.py").write_text(test_text, encoding="utf-8")

    def prompt_for(
        self,
        task: TaskSpec,
        attempt: int,
        prior: Optional[VerifyResult],
    ) -> str:
        """Single-shot. Returns BigCodeBench's ``instruct_prompt``."""
        return task.metadata.get("instruct_prompt") or task.metadata.get("complete_prompt", "")

    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult:
        """Run ``python -m unittest test_task_func``."""
        cmd = [_DEFAULT_PYTHON, "-m", "unittest", "test_task_func", "-v"]
        try:
            proc = run_in_worktree(
                cmd, worktree, timeout=300,
            )
        except Exception as exc:  # noqa: BLE001
            return VerifyResult(
                tests_passed=False,
                tests_output=f"verify subprocess failed: {type(exc).__name__}: {exc}",
                required_files_present=(worktree / "task_func.py").is_file(),
            )
        tail = (proc.stdout or "")[-4096:] + ("\n--- stderr ---\n" + (proc.stderr or "")[-4096:] if proc.stderr else "")
        return VerifyResult(
            tests_passed=(proc.returncode == 0),
            tests_output=tail,
            required_files_present=(worktree / "task_func.py").is_file(),
        )

    def golden_patch(self, task: TaskSpec) -> Path:
        """Return a path to the canonical solution as a complete file.

        Combines the ``code_prompt`` (imports + signature) with the
        ``canonical_solution`` body. The result is a working module
        the stub backend can copy as its single-shot answer.
        """
        # Materialize the canonical task_func.py under the cache
        # directory, content-addressed by task_id slug.
        out_dir = fetch.cache_dir() / "golden_patches"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = task.task_id.replace("/", "-")
        out_path = out_dir / f"{slug}.py"
        if not out_path.is_file():
            code_prompt = task.metadata.get("code_prompt", "")
            canonical = task.metadata.get("canonical_solution", "")
            out_path.write_text(code_prompt + canonical, encoding="utf-8")
        return out_path

    def max_attempts(self) -> int:
        # Single-shot benchmark; no test-feedback retry loop.
        return 1


# ── Helpers ────────────────────────────────────────────────────────────


# Approximate set of Python stdlib top-level package names that
# BigCodeBench tasks reference in their ``libs`` field. Pip would
# fail or pick up the wrong package for these. List is conservative;
# anything not here is treated as a real PyPI package.
_STDLIB_MODULES = frozenset({
    "abc", "argparse", "array", "ast", "asyncio", "base64", "bisect",
    "calendar", "collections", "concurrent", "contextlib", "copy",
    "csv", "ctypes", "datetime", "decimal", "difflib", "email",
    "enum", "fnmatch", "fractions", "functools", "gc", "glob",
    "gzip", "hashlib", "heapq", "hmac", "html", "http", "importlib",
    "inspect", "io", "ipaddress", "itertools", "json", "logging",
    "math", "mimetypes", "multiprocessing", "operator", "os",
    "pathlib", "pickle", "platform", "pprint", "queue", "random",
    "re", "secrets", "shelve", "shlex", "shutil", "signal",
    "socket", "sqlite3", "ssl", "stat", "statistics", "string",
    "struct", "subprocess", "sys", "tarfile", "tempfile", "textwrap",
    "threading", "time", "timeit", "traceback", "types", "typing",
    "unicodedata", "unittest", "urllib", "uuid", "warnings",
    "weakref", "xml", "zipfile", "zlib",
})


def _row_to_task_spec(row: dict) -> Optional[TaskSpec]:
    """Convert one HF row into a TaskSpec.

    Required fields per BigCodeBench schema: task_id, code_prompt,
    instruct_prompt, canonical_solution, test, entry_point, libs.
    Missing critical fields → skip with a warning.
    """
    task_id = row.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        _log.warning("bigcodebench: row missing task_id, skipping")
        return None
    code_prompt = row.get("code_prompt", "")
    instruct_prompt = row.get("instruct_prompt", "")
    if not code_prompt or not instruct_prompt:
        _log.warning(
            "bigcodebench: %s missing code_prompt or instruct_prompt, skipping",
            task_id,
        )
        return None
    # libs is stored as a stringified Python list (e.g. "['random', 'itertools']").
    libs_raw = row.get("libs", "")
    libs: list[str] = []
    if isinstance(libs_raw, list):
        libs = [str(x) for x in libs_raw]
    elif isinstance(libs_raw, str):
        # Best-effort: split on quotes; reject if not parseable.
        try:
            import ast
            parsed = ast.literal_eval(libs_raw) if libs_raw else []
            if isinstance(parsed, list):
                libs = [str(x) for x in parsed]
        except (ValueError, SyntaxError):
            libs = []
    return TaskSpec(
        task_id=task_id,
        language="python",
        metadata={
            "code_prompt": code_prompt,
            "instruct_prompt": instruct_prompt,
            "complete_prompt": row.get("complete_prompt", ""),
            "canonical_solution": row.get("canonical_solution", ""),
            "test": row.get("test", ""),
            "entry_point": row.get("entry_point", "task_func"),
            "libs": libs,
        },
    )


def register() -> None:
    register_adapter(BENCHMARK_ID, BigCodeBenchAdapter)
