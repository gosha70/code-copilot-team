# Origin alignment check — sa-expectations

Checked 2026-09-25 02:30, before plan approval and before any
implementation.

Origin: specs/sa-expectations/origin/2026-09-25-owner-direction.md (the
owner's #371 A5 row, their seven starting rulings of 2026-09-25, and
their ruling on the phase question after the modelling pass) and issue
#371, row A5.

Origin claim:
> Record what a piece of work was expected to achieve and how it came
> out, so success is declared rather than inferred. The spec's
> acceptance criteria are the source of truth; an unattended run
> snapshots them at admission; later spec edits must not rewrite
> history; evaluation records the expectation, a three-state result,
> evidence, evaluator provenance and a timestamp; unknown and
> unevaluated are never failure or zero; the harness comparison may
> expose expectation success only with coverage beside it; sessions bind
> through explicit run identity, not heuristics. Keyed at the attempt
> level `(feature_id, attempt_id, fr)`, with sessions associated
> separately; raw outcome plus explicit normalization; `evaluated_at`
> from `verifier_gate` and a separate `ingested_at`; durable evidence;
> no rows for refused admissions; phase dropped.

Working claim:
> spec.md FR-1..FR-11 and plan.md D1–D11: `expectation` keyed
> UNIQUE (feature_id, attempt_id, fr) carrying statement_sha and the
> statement text; `expectation_result` per verifier carrying the raw
> `green` beside a derived `met|not_met|unknown`, `detail`, `evidence`,
> `log_path`, `waived`; unevaluated as the absence of rows;
> `evaluated_at` from the `verifier_gate` event or NULL, `ingested_at`
> separate; a `correlate`-shaped pass over both ledger roots that writes
> nothing for a run without a frozen contract; sessions associated by
> two new nullable columns through an idempotent UPDATE reporting
> unmatched; read surfaces over HTTP and MCP with a ledger-then-store
> fallback; A4b's compare gaining expectation success with four
> coverage figures and NULL-not-zero.

Each clause against the plan: criteria are the source of truth — FR-1
stores `statement_sha` from the frozen contract, which admission
already recomputes against spec.md; snapshot at admission — FR-1, D1;
no rewriting of history — the `statement_sha` is the admitted one, and
the statement text is stored as admitted; three-state + evidence +
provenance + timestamp — FR-2, FR-3, FR-5, FR-6, D3, D7, D8; unknown
and unevaluated never failure or zero — FR-3, FR-4, FR-10, D4;
comparison with coverage — FR-10, D10; explicit identity — FR-8, D5;
attempt-level key with sessions separate — FR-1, D1; raw plus
normalization — FR-2, D3; durable evidence — FR-6, D7; no rows for
refused admissions — FR-7, D9; phase dropped — D2.

Differences from the origin, surfaced in the bundle:

1. The issue's A5 row says "an expectation record per SESSION". The
   owner's 2026-09-25 ruling supersedes it: evaluation is per run, and
   sessions associate separately. The evidence is that the verifier
   gate runs once per run.
2. Expectations exist only for unattended auto-build runs; manual
   sessions and free-form expectations wait, by the owner's ruling and
   because no identity supports them.
3. This slice records what was required and what happened. A judge that
   SCORES against an expectation — the issue's "that the judge and the
   outcome logic can score against" — is named as out of scope and
   would be a successor slice.
4. Two defects found while modelling are explicitly left outside.

Verdict: aligned
Confidence: medium

Medium, not high: difference 3 narrows the issue's wording (the judge
does not yet score against an expectation), and D11's store recreation
needs the owner's word. Both are for the owner to confirm at approval.

Checked by reading the FR parser and its sha primitive, admission and
its ordering invariants, the frozen contract and results of the one
real ledger, the verifier gate's exit-code mapping and the richer
upstream verdicts, the events file, auto_build.py's reader, the
benchmark-link precedent, the session phase vocabulary, and the
measured coverage of parseable specs and verification artifacts.
