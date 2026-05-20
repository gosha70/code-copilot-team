# benchmark_runner.judge — calibrated LLM-judge subsystem.
#
# Adds calibrated LLM-judge scoring on top of the deterministic
# harness (#34). The judge READS what run.py already wrote (diff +
# prompt + verify output per attempt) and WRITES judge.json adjacent
# to score.json. score.json is never overwritten — running the judge
# against a run-dir does not re-execute the benchmark.
#
# Importing this subpackage does NOT auto-register judges; the
# top-level _register module is the single source of truth for which
# judges are active in a given run, mirroring the backends/ package
# convention.

from __future__ import annotations
