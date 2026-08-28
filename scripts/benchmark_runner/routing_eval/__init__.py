"""routing-eval (E1 of #109) — the measurement substrate for the router.

Measurement only: everything here is downstream of execution. This
package adds no key the router reads at runtime, no policy surface, and
no code path that can change a routing decision.

Cost ownership: ``specs/benchmark-harness/spec.md`` keeps dollar-cost
reporting out of the shared harness ("no schema slot for cost estimation
is added"), and ``test_no_dollar_cost_in_backend_metadata`` enforces
that ``BackendResult``/``backend_metadata`` never carry cost. Nothing in
this package changes that. Cost is read into routing-eval's own record
instead — see :mod:`.cost_reader`.
"""
