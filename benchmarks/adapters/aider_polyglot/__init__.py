# benchmarks.adapters.aider_polyglot — Aider Polyglot benchmark adapter.
#
# Note: Python packages cannot contain hyphens in their import path, so
# the package directory is ``aider_polyglot/`` even though the public
# ``benchmark_id`` (used on the CLI as ``--benchmark aider-polyglot``)
# keeps the hyphen for consistency with the published benchmark name.
#
# Importing this package does NOT register the adapter — registration
# is an explicit call. See ``adapter.register()`` and
# ``benchmark_runner._register.register_all`` for the production wiring.

from __future__ import annotations
