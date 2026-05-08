# benchmarks.adapters.aider_polyglot.adapter — Aider Polyglot adapter.
#
# Walks a cached snapshot of Aider-AI/polyglot-benchmark (pinned by
# REVISION) and exposes each Exercism practice exercise as a TaskSpec.
# The adapter does NOT redistribute the upstream content — it reads
# the cache at runtime to compose prompts and to populate worktrees.
#
# License posture: Exercism content is © Exercism, used under their
# open-source license. We mirror Aider's *composition rule*
# (introduction.md + instructions.md + instructions.append.md) without
# copying Aider's wrapper text — our prompt framing is original.
#
# Phase 2b ships isolation_default = ``worktree`` for all languages.
# Phase 2c adds a per-task ``isolation_for`` override (Python ->
# ``worktree+venv``) and the runner-side venv tier implementation.

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from benchmark_runner.contracts import (
    ISOLATION_WORKTREE,
    ISOLATION_WORKTREE_VENV,
    BenchmarkAdapter,
    IsolationConfig,
    IsolationTier,
    TaskSpec,
    VerifyResult,
)

from . import fetch

BENCHMARK_ID = "aider-polyglot"

# Languages present in the upstream dataset, in stable order.
LANGUAGES = ("cpp", "go", "java", "javascript", "python", "rust")

# Per-language test command (run inside the worktree). Mirrors Aider's
# benchmark.py mapping; documented for hard-host toolchain assumption
# until Phase 2c adds the worktree+venv tier (Python only).
TEST_COMMAND: dict[str, list[str]] = {
    "python": ["python", "-m", "pytest", "-q"],
    "go": ["go", "test", "./..."],
    "javascript": ["bash", "-lc", "npm install --silent && npm test --silent"],
    "rust": ["cargo", "test", "--", "--include-ignored"],
    "java": ["./gradlew", "test"],
    # C++: Exercism C++ tracks ship CMakeLists.txt + a test executable
    # produced by the build. The command below is a portable default;
    # if a particular task ships a different layout the adapter falls
    # back to scanning for an executable named after the test source.
    "cpp": [
        "bash",
        "-lc",
        "mkdir -p build && cd build && cmake -DEXERCISM_RUN_ALL_TESTS=1 .. "
        "&& cmake --build . && ctest --output-on-failure",
    ],
}

# Language -> verify timeout (seconds). Conservative; tests can override.
DEFAULT_TIMEOUTS: dict[str, int] = {
    "python": 60,
    "go": 60,
    "javascript": 120,
    "rust": 180,
    "java": 240,
    "cpp": 300,
}


class AiderPolyglotAdapter:
    """Adapter for the pinned Aider Polyglot dataset.

    Construct with ``dataset_root=None`` (default) to use the cache
    populated by ``fetch.ensure_cached``. Tests pass an explicit path
    to a synthetic mini-Polyglot fixture so they don't depend on the
    real upstream clone.
    """

    benchmark_id = BENCHMARK_ID
    isolation_default: IsolationTier = ISOLATION_WORKTREE

    def __init__(self, dataset_root: Optional[Path] = None) -> None:
        self._dataset_root = (
            Path(dataset_root) if dataset_root is not None else fetch.cache_dir()
        )

    # ── Required protocol methods ──────────────────────────────────────

    def isolation_for(self, task: TaskSpec) -> IsolationConfig:
        """Per-language isolation directive.

        Python tasks run inside a worktree-local venv with pytest
        installed (the worktree+venv tier). Other languages assume
        the host has the relevant toolchain (go, cargo, gradle, npm,
        cmake) — installation of those is out of scope for the
        harness; document the requirement in benchmarks/README.md.
        """
        if task.language == "python":
            return IsolationConfig(
                tier=ISOLATION_WORKTREE_VENV,
                python="python3",
                install_command="pip install -q pytest",
            )
        return IsolationConfig(tier=ISOLATION_WORKTREE)

    def list_tasks(self) -> list[TaskSpec]:
        if not self._dataset_root.is_dir():
            # Empty registry view when the cache is absent. The runner
            # surfaces this as "0 tasks"; ``./scripts/benchmark list``
            # users get a hint via README to run the fetch script.
            return []

        out: list[TaskSpec] = []
        for lang in LANGUAGES:
            practice = self._dataset_root / lang / "exercises" / "practice"
            if not practice.is_dir():
                continue
            for exercise_dir in sorted(practice.iterdir()):
                if not exercise_dir.is_dir():
                    continue
                spec = _try_build_task_spec(lang, exercise_dir)
                if spec is not None:
                    out.append(spec)
        return out

    def prepare_task(self, task: TaskSpec, worktree: Path) -> None:
        """Copy starter + tests + .docs/ into worktree.

        The reference implementation under ``.meta/example*`` is
        DELIBERATELY skipped so the model never sees the answer. The
        rest of ``.meta/`` (config.json, tests.toml, template.j2) is
        also skipped — those are upstream tooling artifacts, not
        runtime context.
        """
        src_dir = self._task_dir(task)
        for src in src_dir.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(src_dir)
            # Skip the entire .meta/ tree — it contains the example
            # solution plus upstream-tooling files we don't need.
            if rel.parts and rel.parts[0] == ".meta":
                continue
            dst = worktree / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    def prompt_for(
        self,
        task: TaskSpec,
        attempt: int,
        prior: Optional[VerifyResult],
    ) -> str:
        src_dir = self._task_dir(task)
        intro = src_dir / ".docs" / "introduction.md"
        instructions = src_dir / ".docs" / "instructions.md"
        append = src_dir / ".docs" / "instructions.append.md"

        parts: list[str] = []
        parts.append(f"# {task.task_id}")
        blurb = task.metadata.get("blurb", "")
        if blurb:
            parts.append("")
            parts.append(str(blurb))
        parts.append("")

        if intro.exists():
            parts.append(intro.read_text(encoding="utf-8"))
            parts.append("")
        if instructions.exists():
            parts.append(instructions.read_text(encoding="utf-8"))
            parts.append("")
        if append.exists():
            parts.append(append.read_text(encoding="utf-8"))
            parts.append("")

        parts.append("## Your task")
        parts.append("")
        parts.append("Edit ONLY these solution files; do not edit anything else:")
        for f in task.metadata["solution_files"]:
            parts.append(f"  - `{f}`")
        parts.append("")
        parts.append("Test files (read-only):")
        for f in task.metadata["test_files"]:
            parts.append(f"  - `{f}`")
        parts.append("")
        cmd = TEST_COMMAND.get(task.language, [])
        if cmd:
            parts.append(f"Tests will be run with: `{' '.join(cmd)}`")
            parts.append("")

        if attempt > 1 and prior is not None:
            parts.append("## Your previous attempt failed")
            parts.append("")
            parts.append("Test output:")
            parts.append("")
            parts.append("```")
            parts.append((prior.tests_output or "").strip())
            parts.append("```")
            parts.append("")
            parts.append(
                "Read the failure carefully and revise the solution. "
                "Edit only the solution files listed above."
            )
            parts.append("")

        return "\n".join(parts).rstrip() + "\n"

    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult:
        """Run the per-language test command in ``worktree``.

        Phase 2b: invokes the host toolchain directly. Phase 2c (Python)
        will run inside a venv provisioned by the ``worktree+venv``
        isolation tier; the verify path here will pick up the venv's
        pytest from the worktree's ``.venv/bin/`` directory if present.
        """
        cmd = TEST_COMMAND.get(task.language)
        if cmd is None:
            return VerifyResult(
                tests_passed=False,
                tests_output=f"verify: no test command for language {task.language!r}",
                required_files_present=False,
            )

        timeout = DEFAULT_TIMEOUTS.get(task.language, 60)
        cmd = _maybe_use_venv_python(task.language, worktree, cmd)

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(worktree),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            return VerifyResult(
                tests_passed=False,
                tests_output=(
                    f"verify: required toolchain missing for {task.language}: "
                    f"{exc}"
                ),
                required_files_present=_solution_files_present(task, worktree),
            )
        except subprocess.TimeoutExpired:
            return VerifyResult(
                tests_passed=False,
                tests_output=f"verify: timed out after {timeout}s",
                required_files_present=_solution_files_present(task, worktree),
            )

        passed = proc.returncode == 0
        return VerifyResult(
            tests_passed=passed,
            tests_output=(proc.stdout + proc.stderr).strip(),
            required_files_present=_solution_files_present(task, worktree),
            failed_commands=0 if passed else 1,
        )

    def golden_patch(self, task: TaskSpec) -> Path:
        """Build (lazily) and return the per-task reference patch dir.

        The dir contains the upstream's example files renamed to the
        task's solution paths so the stub backend can copy them
        verbatim into the worktree.
        """
        golden_root = self._golden_root() / task.task_id
        if not golden_root.exists():
            _build_golden_dir(self._task_dir(task), task, golden_root)
        return golden_root

    def max_attempts(self) -> int:
        # Aider-style two-shot: failure on attempt 1 -> retry with the
        # failed test output appended to the prompt.
        return 2

    # ── Helpers ────────────────────────────────────────────────────────

    def _task_dir(self, task: TaskSpec) -> Path:
        lang, _, exercise = task.task_id.partition("/")
        if not lang or not exercise:
            raise ValueError(f"malformed task_id: {task.task_id!r}")
        return self._dataset_root / lang / "exercises" / "practice" / exercise

    def _golden_root(self) -> Path:
        # Sibling cache so wiping benchmarks/.cache/polyglot/<sha>/ also
        # wipes its derived golden material.
        return self._dataset_root.parent.parent / "polyglot-golden" / self._dataset_root.name


_DOGFOOD_FILE = Path(__file__).resolve().parent / "dogfood-subset.txt"


def load_dogfood_subset() -> list[str]:
    """Read the dogfood subset (one task_id per line, # comments).

    The list is committed alongside REVISION so the dogfood gate is
    deterministic across machines. Phase 4 wires this into
    ``./scripts/benchmark dogfood``; Phase 2d ships only the file.
    """
    out: list[str] = []
    for raw in _DOGFOOD_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def register() -> None:
    """Idempotent-from-the-caller's-perspective registration entry.

    See ``benchmarks/adapters/stub/adapter.py`` for the rationale on
    why registration is an explicit function call and not a module-
    level side-effect.
    """
    from benchmark_runner.registry import register_adapter
    register_adapter(BENCHMARK_ID, AiderPolyglotAdapter)


# ── Module-level helpers ───────────────────────────────────────────────


def _try_build_task_spec(lang: str, exercise_dir: Path) -> Optional[TaskSpec]:
    config_path = exercise_dir / ".meta" / "config.json"
    if not config_path.is_file():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    files = config.get("files", {})
    solution = list(files.get("solution", []))
    tests = list(files.get("test", []))
    example = list(files.get("example", []))
    if not solution or not tests:
        return None
    return TaskSpec(
        task_id=f"{lang}/{exercise_dir.name}",
        language=lang,
        metadata={
            "solution_files": solution,
            "test_files": tests,
            "example_files": example,
            "blurb": config.get("blurb", ""),
        },
    )


def _build_golden_dir(src_task_dir: Path, task: TaskSpec, dest: Path) -> None:
    sols = list(task.metadata["solution_files"])
    exs = list(task.metadata["example_files"])
    if len(sols) != len(exs):
        raise ValueError(
            f"task {task.task_id}: solution/example file count mismatch "
            f"({len(sols)} solution vs {len(exs)} example)"
        )
    dest.mkdir(parents=True)
    for sol, ex in zip(sols, exs):
        src = src_task_dir / ex
        dst = dest / sol
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _solution_files_present(task: TaskSpec, worktree: Path) -> bool:
    for sol in task.metadata["solution_files"]:
        if not (worktree / sol).is_file():
            return False
    return True


def _maybe_use_venv_python(
    language: str, worktree: Path, cmd: list[str]
) -> list[str]:
    """If the worktree has a ``.venv/bin/python``, prefer it for Python tasks.

    Phase 2c provisions venvs via the worktree+venv isolation tier;
    this hook lets the verify runner pick them up without coupling
    the adapter to the runner's tier-implementation details.
    """
    if language != "python":
        return cmd
    venv_python = worktree / ".venv" / "bin" / "python"
    if not venv_python.exists() or not cmd or cmd[0] != "python":
        return cmd
    return [str(venv_python), *cmd[1:]]


# Module-level type-check (does not register).
assert isinstance(AiderPolyglotAdapter(dataset_root=Path("/nonexistent")), BenchmarkAdapter)
