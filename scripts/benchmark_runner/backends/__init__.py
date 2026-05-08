# benchmark_runner.backends — backend implementations.
#
# Importing this subpackage does NOT auto-register backends; the
# top-level _register module is the single source of truth for which
# backends are active in a given run. This keeps test isolation
# straightforward (tests can register only what they need).

from __future__ import annotations
