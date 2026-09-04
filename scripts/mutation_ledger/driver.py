# scripts.mutation_ledger.driver — the instrument behind the mutation
# ledgers in specs/*/mutation-ledger.md.
#
# WHY THIS HAS TESTS. Three specs now rest their central quality claim
# on a number this code produces ("N mutations, N caught, 0 escaped").
# A ledger only a single author can reproduce is testimony, not
# evidence — and the instrument has been silently wrong twice:
#
#   1. An anchor that matched zero or two places was SKIPPED with a
#      note, so a mutation nobody ran still looked accounted for. Now
#      an ambiguous or absent anchor raises AnchorError and aborts the
#      whole pass. A ledger with an unrun mutation is not a ledger.
#   2. The failure parser matched `FAILED` and `ERROR` but not
#      pytest's `SUBFAILED(...)` lines, so subtest-driven
#      discriminators reported "caught by 0 tests" — a caught mutation
#      that looked like a hole, and which would equally have hidden a
#      real hole.
#
# Both are regressions in tests/test_driver.py, not speculative
# hardening: each stands for a defect that actually happened.
#
# The same class of problem is documented at the repo root in
# conftest.py — an instrument disagreeing with the documented runner
# and producing "a plausible-looking number that is wrong for a reason
# nobody would guess". This module is that lesson applied to the thing
# that measures test quality.

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

#: pytest reports a failed subtest as `SUBFAILED(param=value) path::Class::test`.
#: Missing this form is defect (2) above.
_FAILURE_LINE = re.compile(
    r"^(?:SUBFAILED\([^)]*\)|FAILED|ERROR)\s+\S+?::(?:\w+::)?(\w+)")


class AnchorError(RuntimeError):
    """A mutation's anchor did not match exactly one place.

    Deliberately fatal. The tempting alternative — note it and move on
    — produces a ledger whose count includes a mutation that never ran.
    """


class BaselineError(RuntimeError):
    """The suite was not green, or not skip-free, before mutating."""


@dataclass(frozen=True)
class Mutation:
    """One deliberate weakening of the code under test."""

    id: str
    path: str          # repo-relative, under `root`
    old: str           # must appear EXACTLY once in the file
    new: str


@dataclass(frozen=True)
class MutationResult:
    id: str
    caught: bool
    failing_tests: tuple[str, ...]


@dataclass(frozen=True)
class LedgerReport:
    baseline: str
    restored: str
    results: tuple[MutationResult, ...]

    @property
    def caught(self) -> int:
        return sum(1 for r in self.results if r.caught)

    @property
    def escaped(self) -> tuple[str, ...]:
        return tuple(r.id for r in self.results if not r.caught)


def parse_failing_tests(output: str) -> list[str]:
    """The distinct test names a run reported as failing.

    Counts FAILED, ERROR and SUBFAILED lines. Sorted and de-duplicated
    so the ledger's "caught by N tests" is stable across runs.
    """
    return sorted({m.group(1) for m in
                   (_FAILURE_LINE.match(line) for line in output.splitlines())
                   if m})


def _clear_caches(root: Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def default_runner(root: Path, test_paths: Sequence[str]) -> tuple[int, str]:
    """Run the tests with the CURRENT interpreter, returning (rc, output)."""
    _clear_caches(root)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *test_paths, "-q", "--no-header",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=root)
    return proc.returncode, proc.stdout


def _tail(output: str) -> str:
    lines = [l for l in output.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def run_ledger(
    mutations: Iterable[Mutation],
    *,
    root: Path,
    test_paths: Sequence[str],
    runner: Optional[Callable[[Path, Sequence[str]], tuple[int, str]]] = None,
    require_no_skips: bool = True,
) -> LedgerReport:
    """Apply each mutation in turn and report which the suite catches.

    Every source file is restored before returning, including when the
    runner raises: a driver that leaves the tree mutated would corrupt
    the very thing it measures.

    Raises BaselineError unless the suite is green first (and, by
    default, skip-free — a ledger run with skipped classes silently
    measures less than it claims). Raises AnchorError if any mutation's
    anchor does not match exactly once.
    """
    run = runner or default_runner
    mutations = list(mutations)

    rc, out = run(root, test_paths)
    baseline = _tail(out)
    if rc != 0:
        raise BaselineError(f"suite not green before mutating: {baseline}")
    if require_no_skips and " skipped" in baseline:
        raise BaselineError(f"baseline has skips: {baseline}")

    originals = {m.path: (root / m.path).read_text(encoding="utf-8")
                 for m in mutations}
    # Validate EVERY anchor before touching anything, so an unrunnable
    # ledger fails before it has half-applied itself.
    for mutation in mutations:
        found = originals[mutation.path].count(mutation.old)
        if found != 1:
            raise AnchorError(
                f"{mutation.id}: anchor matched {found} places in "
                f"{mutation.path} (need exactly 1)")

    results: list[MutationResult] = []
    try:
        for mutation in mutations:
            source = originals[mutation.path]
            (root / mutation.path).write_text(
                source.replace(mutation.old, mutation.new), encoding="utf-8")
            try:
                rc, out = run(root, test_paths)
            finally:
                (root / mutation.path).write_text(source, encoding="utf-8")
            results.append(MutationResult(
                id=mutation.id,
                caught=rc != 0,
                failing_tests=tuple(parse_failing_tests(out)),
            ))
    finally:
        for path, source in originals.items():
            (root / path).write_text(source, encoding="utf-8")
        _clear_caches(root)

    rc, out = run(root, test_paths)
    restored = _tail(out)
    if rc != 0:
        raise BaselineError(f"suite NOT restored after mutating: {restored}")

    return LedgerReport(baseline=baseline, restored=restored,
                        results=tuple(results))
