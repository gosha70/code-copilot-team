# benchmark_runner.calibration — calibration corpus selection + validation.
#
# Sourcing the calibration corpus (this package) and validating it
# (Spearman gate, TB1.5 / sub-issue B) are the two halves of the
# calibration pipeline. The corpus selector reads the existing
# ``runs/`` archive and writes ``<name>.corpus.jsonl`` +
# ``<name>.meta.json`` under ``benchmarks/calibration/`` (or a
# user-specified output dir). It never mutates ``runs/``.

from __future__ import annotations
