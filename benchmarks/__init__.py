# benchmarks — top-level package for adapter datasets and code.
#
# Adapter Python modules live under ``benchmarks/adapters/<id>/adapter.py``
# alongside the per-task data they consume. The runner imports them via
# ``benchmarks.adapters.<id>.adapter``; see scripts/benchmark_runner/_register.py.

from __future__ import annotations
