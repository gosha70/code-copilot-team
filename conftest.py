# conftest.py — keep pytest out of the benchmark FIXTURE trees (#268).
#
# THE PROBLEM. `scripts/benchmark_runner/tests/fixtures/polyglot_mini/`
# holds Exercism-style exercises used as INPUT DATA by the polyglot
# adapter tests. Each exercise ships an unsolved starter stub beside its
# test file, so `leap_test.py`'s four tests fail BY DESIGN — that failure
# is what the adapter under test is supposed to observe.
#
# `unittest discover` never sees them: its pattern is `test*.py`, which
# `leap_test.py` cannot match. pytest's default `python_files` is
# `test_*.py *_test.py`, which it does. So the fixture is invisible to the
# documented runner and visible only to pytest.
#
# WHY IT IS WORTH A FILE. Four failures that look like real breakage and
# are not is the small half. The larger half is measurement integrity:
# this repo has a documented per-host `benchmark_runner` failure baseline
# established with `unittest discover`, and a pytest-derived total exceeds
# it by exactly this collection delta — a plausible-looking number that is
# wrong for a reason nobody would guess. It was found exactly that way.
#
# SCOPE, deliberately narrow. This ignores the polyglot fixture subtree
# and nothing else. It does not make pytest a supported entry point, add
# pytest to CI, or change how tests are configured:
#
#   `unittest discover` REMAINS THE CANONICAL RUNNER.
#
# It is what both `benchmark-smoke.yml` and `session-analytics-smoke.yml`
# invoke, and what the per-host baselines are measured with. This file
# only stops a reasonable `pytest` invocation from reporting fixture data
# as broken code.
#
# A fixture tree that a future adapter adds under a different name is NOT
# covered here on purpose: an exclusion glob wide enough to catch trees
# that do not exist yet would also hide real tests someone files under a
# path that happens to match.

collect_ignore_glob = [
    "scripts/benchmark_runner/tests/fixtures/polyglot_mini/*",
]
