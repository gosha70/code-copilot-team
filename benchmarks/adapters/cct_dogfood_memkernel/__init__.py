# benchmarks.adapters.cct_dogfood_memkernel — Gate 2 dogfood fixture.
#
# Forward-looking spec-first dogfood: harness runs Claude Code against
# memkernel#3 ("Define MemKernel Memory Brain Architecture"). Replaces
# the original rlmkit#38/#41 retrospective plan, which was
# backward-looking (the gist verdict is final, the experiment is
# closed). memkernel#3 is fresh and unrun at the time of fixture
# creation, making it a real forward-looking calibration target for
# the harness's deterministic-scoring + run-record machinery.
#
# Importing this package does NOT register the adapter — registration
# is an explicit call to ``adapter.register()``, per the same rule the
# stub and aider_polyglot adapters follow (avoids module-level
# side-effects breaking test isolation when the registry resets).

from __future__ import annotations
