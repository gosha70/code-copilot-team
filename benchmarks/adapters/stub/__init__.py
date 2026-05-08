# benchmarks.adapters.stub — CI-only stub adapter package.
#
# Importing this package does NOT register the adapter — registration
# is an explicit call to ``adapter.register()``. See
# ``benchmark_runner._register.register_all`` for the production
# registration flow and the comment in ``adapter.py`` for why
# import-time side-effects are not used.

from __future__ import annotations
