# Owner direction — Session Analytics gaps, slice A5 (#371)

Owner messages in this session, verbatim where quoted.

2026-09-22, the governing choice:

> Ok, based on your summary I would rather work on extending capabilities
> of "Session Analysis" rather using ML Flow.

> We can approach with "Session Analysis" as a green field project (I
> still not officially release it); so I am good about not worry about
> the backward compatibility - data migration

Issue #371, row A5, as filed:

> **Expectations.** Session-level judge scorers and the Expectation half
> of the model. Today the judge is per turn rolled up into session_kpi;
> there is no place to state what a session was expected to achieve, so
> "success" is inferred rather than declared. Build: an expectation
> record per session (the task, the acceptance criterion, optionally the
> spec it came from) that the judge and the outcome logic can score
> against.

2026-09-25, the owner opened A5 and set the starting rulings:

> Take up A5 next; keep A6 deferred.
>
> For A5, do a modelling-only pass before writing a bundle. My starting
> rulings:
>
> - The spec acceptance criteria remain the source of truth.
> - An unattended run snapshots applicable expectations at admission,
>   keyed to attempt and phase. Later spec edits must not rewrite history.
> - Sessions bind through explicit run/attempt/phase identity—not
>   project/time heuristics.
> - Evaluation records expectation, result (`met`, `not_met`, `unknown`),
>   evidence, evaluator provenance, and timestamp.
> - `unknown` and unevaluated remain null in aggregates, never failures
>   or zero success.
> - The harness comparison may expose expectation success only with
>   coverage beside it.
> - Manual sessions and free-form expectations can wait unless existing
>   identities support them cleanly.
>
> For A6, do not invent thread lineage from timing. Resume/compaction
> should ship only when native identifiers prove it; heuristic grouping
> can be reconsidered later as an explicitly labelled separate feature.

The modelling pass found that "keyed to attempt and phase" is not
achievable: `frozen-contract.json` carries only `verifiers` with no
phase dimension at any level, `verification-results.json` is one file
per run written once at the landing gate, and nothing anywhere maps an
FR to a `## US<N>` phase (in the one real run the FR references are
human prose inside `tasks.md` task rows). Three options were put to the
owner: drop the phase dimension; make an FR-to-phase mapping
first-class in the SDD workflow; or attribute a phase indirectly
through the session, which would fabricate the attribution.

2026-09-25, the owner's ruling on that question:

> Ruling unchanged: choose option 1 and drop phase from A5.
>
> Proceed to the bundle with expectations keyed at the attempt level:
> `(feature_id, attempt_id, fr)`. Associate sessions separately rather
> than making `session_ref` part of the evaluation identity unless the
> evidence proves evaluation is session-specific.
>
> Also preserve:
>
> - Raw verifier outcome plus explicit three-state normalization.
> - `evaluated_at` from `verifier_gate` when available and separate
>   `ingested_at`.
> - Durable evidence that survives ledger pruning.
> - No rows for refused admissions.
> - Both unrelated defects remain outside A5.

The evidence on session specificity, which the owner's ruling turns on:
the verifier gate runs ONCE per run at the landing gate
(`auto-build-loop.sh:3137-3155`), writing one
`verification-results.json` per ledger, overwritten. An evaluation is
therefore a property of the run, not of any session that ran in it;
putting `session_ref` in the evaluation key would have copied one
evaluation across every phase session of the run.

The two defects found during the modelling pass and explicitly left
outside this slice: `scripts/lib/routing-packet.sh:293` filters
`$3 == "test"` where `$3` is the verifier kind, so `fr_refs[].tests` is
always empty; and `validate-spec.sh` writes a top-level `verification`
key that `preflight-result.schema.json` forbids, which the driver
deletes before validating.

2026-09-25, the owner's review of the first bundle (pasted; all seven
adopted):

> Not approved yet. The phase ruling is correct, and I accept
> expectation-aware judge scoring as a successor slice—but the storage
> model needs revision before implementation.
>
> - Reject D11's session columns and rebuild. Losing 13 irreplaceable
>   sessions is unnecessary. Use an additive `expectation_session`
>   association table keyed by run and `session_ref`. Schema 11 may add
>   tables in place without refusing the existing store.
> - Add an `expectation_run` parent keyed by `(feature_id, attempt_id)`.
>   Put contract fingerprint, `branch_base_ref`, timestamps and source
>   provenance there. [...] This also gives attempt collisions a safe
>   rule: same key plus different fingerprint must be reported and
>   refused, never upserted together.
> - The admitted statement is not in the frozen contract. Recover it
>   from `branch_base_ref:specs/<feature>/spec.md`, and accept it only
>   when its computed hash matches `statement_sha`. If the commit/text
>   cannot be recovered, store statement as unavailable—not today's
>   potentially changed text.
> - Normalize waived visual results as `unknown` before considering
>   `green`; the driver explicitly calls them "waived, not verified".
>   Also, an unwaived visual `skip` never reaches
>   `verification-results.json`, so either read the preserved visual
>   artifact and policy or remove the claim that A5 can recover that
>   state.
> - Define A4b attribution at run grain. Count an expectation once in a
>   harness row only when all linked sessions for that attempt resolve
>   to that same row. Runs spanning harness groups must be excluded and
>   reported separately; otherwise one run's outcome is duplicated
>   across versions.
> - Correct the timestamp claim: `verifier_gate` is emitted only after
>   an all-green gate, not once per evaluated run. Failed results
>   legitimately have `evaluated_at = NULL`.
> - Fix the shifted FR references in tasks.md [...]
>
> The no-phase decision remains approved. Record expectation-aware judge
> scoring as an explicit A5 successor; don't describe it as delivered by
> this slice.

Every behavioural claim was verified in the code before the bundle was
revised:

* `frozen-contract.json` verifier entries are `{fr, statement_sha,
  test, metric}` — no statement text.
* Statement recovery works: `git show f75ebaa...:specs/team-developer-aliases/spec.md`
  re-extracted with `vc_extract_frs` and hashed with `vc_fr_sha` gives
  4 of 4 hashes identical to the frozen `statement_sha`.
* `journal "verifier_gate"` (auto-build-loop.sh:3182) is reached only
  after the failure path's `vg_finish` + `return 1` at :3179-3180.
* A waived visual entry is written `green: true` with `waived: true`
  (:3073-3080); an unwaived visual `skip` calls `vg_finish` and
  `return 1` at :3046-3048, before any visual result is written, so it
  never appears in the results file.
* tasks.md referenced FR-9..FR-12 against a spec that ended at FR-11 —
  a builder error, now rewritten against FR-1..FR-13.

2026-09-25, the owner's second review of the bundle (pasted; all four
adopted):

> Much closer, but four corrections remain before approval.
>
> 1. Collision detection is still incomplete. Two runs of the same
>    feature can share an `attempt_id` and the same contract, so
>    `contract_fingerprint` would treat them as one run. Either add a
>    stable `run_fingerprint` using immutable ledger facts such as the
>    initial event timestamp/detail, `branch_base_ref`, and contract
>    digest; or narrow the claim and explicitly retain same-contract
>    collisions as an unresolved risk.
> 2. Persist unmatched session identities. `expectation_session` should
>    be keyed by `(run_ref, copilot, session_id)` with nullable
>    `session_ref` [...] That lets a later pass resolve a transcript
>    ingested after the first scan and lets coverage distinguish "not in
>    the store" from "no session recorded."
>    A4b may attribute a run only when every discovered session is
>    linked and every linked session resolves to the same harness row.
>    Incomplete runs need a separate excluded count.
> 3. Tighten FR-12's response contract: `runs_spanning_groups` and
>    `runs_with_unmatched_sessions` are top-level exclusions, not
>    per-row figures. Name the excluded expectation fields explicitly
>    [...] Define the rate exactly as `met / evaluated`.
> 4. Remove stale contradictions: spec.md still says two tables [...]
>    "Unevaluated" must mean no recoverable consolidated result rows,
>    not necessarily that no verifier ran—unwaived visual skip proves
>    the distinction. plan.md still proposes testing unwaived skip as a
>    recoverable raw shape. The scratch verification still mentions
>    recreating the owner's store even though D11 now forbids and
>    avoids that.

Adopted as: a `run_fingerprint` over the first `init` event's `ts` and
`detail`, `branch_base_ref` and the contract digest (the `init` line of
a real ledger is
`{"ts":"2026-09-09T16:22:19Z","event":"init","detail":"profile=unattended branch=… base=…"}`),
with the residual same-second-same-base-same-contract case recorded as
accepted rather than solved; `expectation_session` keyed by the
discovered identity with a nullable `session_ref`; FR-13's per-row and
top-level fields separated and the rate defined as
`expectations_met / expectations_evaluated`; and four stale statements
removed — two of which the owner did not list (`plan.md`'s
justification still said "two nullable session columns", and its
scratch-verification line still said the store is "recreated only on
their word").
