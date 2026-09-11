# Origin: increment D, investigated over five runs (2026-09-11)

Owner, 2026-09-11: "Can we research/investigate and address 'Increment
D. Deferred, not rejected. No run has produced a case that adjudication,
a builder swap or a resume would have changed. Every provider failure
was the reviewer, and the builder finished its phase every time.'?"

The investigation (doc_internal/plans/190-increment-d-investigation-2026-09-11.md)
found that the fallback chain in providers.toml is consulted only at
healthcheck time. All three provider failures (runs 1, 3, 5) passed the
healthcheck and the probe, ran on the real request, and produced no
review; in run 5 a healthy fallback (the Spark) was configured and never
asked. The recovery the data supports is a reviewer fallback at round
time (D1), then a resume of a terminated run at the review step (D2).
Adjudication and builder swap stay design text: no run produced their
case.

Owner, 2026-09-11: "I would like for DeepSeek to auto review the
upcoming D1 work."
