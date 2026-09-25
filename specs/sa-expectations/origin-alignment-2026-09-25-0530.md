# Origin alignment check — sa-expectations (after the second review)

Checked 2026-09-25 05:30, after the owner's second review and the
corrections for it. Supersedes the 0400 record. Nothing is built.

Origin: specs/sa-expectations/origin/2026-09-25-owner-direction.md and
issue #371, row A5.

What this round corrected:

1. **Collision detection is a RUN fingerprint, not a contract one.**
   Two runs of one feature can share `attempt_id` and, with an
   unchanged spec, the same contract digest; comparing contracts alone
   would have merged them and overwritten the first run's results.
   `run_fingerprint` digests the first `init` event's `ts` and
   `detail`, `branch_base_ref` and the contract digest; a key match
   with a differing fingerprint is reported and skipped, and a ledger
   with no readable `init` event is skipped rather than stored under a
   weaker identity. The residual — same feature, same base, same
   contract, same-second start — is recorded in Risks as accepted, not
   solved. FR-1, FR-2, D5b.
2. **Unmatched session identities are persisted.** `expectation_session`
   is keyed `(run_ref, copilot, session_id)` with a nullable
   `session_ref`, so a transcript ingested after the first scan is
   resolved by a later pass, and coverage distinguishes "recorded but
   not in the store" from "no session recorded". A4b attributes a run
   only when every discovered session is linked and all resolve to one
   row. FR-11, FR-13, D5, D10.
3. **FR-13's response contract is exact.** Per-row: met, evaluated,
   unknown, unevaluated, runs_with_expectations,
   sessions_with_expectations. Top-level, because an excluded run
   belongs to no row: runs_spanning_groups, runs_with_unmatched_sessions.
   Rate = `expectations_met / expectations_evaluated` over `met` and
   `not_met` only, NULL when the denominator is 0.
4. **Stale statements removed**: "two new tables" → four; "unevaluated"
   redefined as *no recoverable consolidated result* (the unwaived
   visual skip is a verifier that ran and left nothing recoverable, not
   a verifier that never ran); the unwaived-skip raw shape removed from
   the test plan and explicitly named as a shape the driver cannot
   write; and the scratch verification no longer mentions recreating
   the owner's store, which D11 forbids. Two further stale statements
   the review did not list were found and fixed: the plan's
   justification still claimed "two nullable session columns", and its
   scratch-verification line still said the store is "recreated only on
   their word".

Verdict: aligned
Confidence: high

High: every decision carries the owner's explicit ruling, and every
behavioural claim was verified in the code or measured on the one real
ledger.

---

Amended 2026-09-25 05:55, after the owner approved D1–D11 with three
clerical corrections (no further approval round): the plan's file map
said "the two new columns" where no session columns remain; D4 cited
the pre-renumber FR-10 instead of FR-13; and both D4 and FR-10
described unevaluated as "never reached the verifier gate" rather than
"no recoverable consolidated results" — the unwaived visual skip is a
gate that ran and aborted before writing anything recoverable, so the
narrower wording would have excluded a real case. Verdict and
confidence unchanged: aligned, high.

---

Amended 2026-09-25 07:10. The owner's review after task 3 made the
normalization FAIL-SAFE: `not_met` is asserted only for a shape known
to mean a real negative (deterministic `exit <nonzero>`, conformance or
visual `fail`), and everything else — bounds, `unreached`, waived,
malformed detail, unknown verifier kinds, and any future wording —
falls back to `unknown`. The earlier rule matched inconclusive shapes
and defaulted to `not_met`, so a reword in `auto-build-loop.sh` would
have reported requirements as failed that were never judged.

FR-6 had been left describing that earlier rule after the code changed
— a semantic contradiction `validate-spec` cannot detect, since it
checks section presence rather than meaning. FR-6 and D3 now state the
implemented ordering exactly. Verdict and confidence unchanged:
aligned, high.

---

Amended 2026-09-25 07:40, after the owner's review of task 4.

FR-12 had claimed the auto-build run detail "falls back to the store
when the ledger is gone". It does not and cannot: that route finds a
run by scanning ledger directories (`_find_run`), so it returns None as
soon as the directory is pruned — which the builder's own deletion
demonstration had already printed without the contradiction being
noticed. FR-12, the plan and tasks.md now draw the distinction the code
actually implements: `GET /api/expectations` is the DURABLE,
store-only surface, and the run detail is an ENRICHMENT of a run whose
ledger is still present. A genuine run-detail fallback is named as out
of scope pending a design, because `/api/runs/{key}` is keyed by
`attempt_id` alone while the store's identity is the composite
`(feature_id, attempt_id)`.

`_stored_expectations` no longer catches every exception. The tables
exist by the time the API serves (create_app applies the DDL), so a
database failure or a defect is a real fault and is left to surface;
`None` now means exactly one thing — the run was never ingested.

Verdict and confidence unchanged: aligned, high.

---

Amended 2026-09-25 08:40, after the owner's review of task 5 and the
Studio work.

* The aggregate no longer caps the runs it reads. `list_runs(limit=None)`
  omits the SQL LIMIT, and the compare uses it: a cap there would have
  dropped later runs out of the row totals AND out of the exclusion
  counters, so the loss would not even read as missing coverage. The
  HTTP and MCP surfaces keep explicit bounds. A test proves the two
  paths differ.
* The Expectations cell shows the SUCCESS rate (met/evaluated) over
  EVALUATION COVERAGE (evaluated out of every expectation the runs
  carried). The first version printed met/evaluated as coverage, which
  rendered the real row as the self-contradictory "4/4 evaluated · 22
  unevaluated"; it now reads "4/26 evaluated · 22 unevaluated".
* 100% is reserved for complete success: a rate below 1 is capped at
  99%, so 999/1000 cannot round up into a false claim.
* The unmatched-runs note names all three causes — a session never
  ingested, one outside the current noise population, and a run that
  recorded none.

Verdict and confidence unchanged: aligned, high.

---

Amended 2026-09-25 09:30, after the owner's review of the complete diff.

1. **A recovered statement is never demoted.** The upsert overwrote an
   existing expectation's statement unconditionally, so a later pass
   whose recovery failed — a garbage-collected base commit, a wrong
   `--project-dir`, a missing parser — replaced verified text with
   NULL, defeating the durability this table exists for. Only
   unavailable → recovered, or one verified recovery replaced by
   another. Pinned by a two-pass test that recovers, rescans from a
   directory that is not the project, and asserts the stored row is
   byte-identical; and by its converse, an unavailable row promoted
   when a later pass can recover. (The first draft of that test edited
   `branch_base_ref` to simulate the loss, which instead changes the
   run fingerprint — the pass correctly refused it as a different run.
   The test now leaves the ledger untouched, which is what every real
   cause looks like.)
2. **The API and MCP contract is tested**, as FR-14 required and task 6
   had claimed without delivering: HTTP filters, limit, an unknown
   filter returning empty rather than everything, and null-not-zero
   output; the registered MCP schema inspected for `feature_id`,
   `attempt_id` and `limit` and each one called through the built
   server; and run-detail enrichment pinned against a never-ingested
   run. This is the boundary where A2 shipped a wrapper that dropped
   its filters.
3. plan.md and tasks.md no longer claim the run detail works after the
   ledger is moved aside, matching the corrected FR-12.
4. "facts that differ between any two real runs" is replaced everywhere
   (spec, plan, DDL, module docstring) with wording that admits the
   accepted same-second collision. `run_fingerprint` guarantees that a
   DIFFERING run is never silently merged; it does not guarantee
   uniqueness.

Verdict and confidence unchanged: aligned, high.
