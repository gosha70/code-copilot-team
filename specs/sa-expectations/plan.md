---
spec_mode: lightweight
feature_id: sa-expectations
risk_category: data
justification: |
  Four new tables that land in place (no version refusal, no store
  recreate), one ingest pass, one aggregate extension, two read
  surfaces, tests. No change to the driver or to either JSON schema:
  A5 reads artifacts the auto-build run already freezes and writes.
  FR-1..FR-14 in spec.md state the behaviour.
status: draft
date: 2026-09-25
issue: "#371"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-expectations/origin/2026-09-25-owner-direction.md
  user_messages:
    - "2026-09-25: 'Take up A5 next; keep A6 deferred.'"
    - "2026-09-25: 'The spec acceptance criteria remain the source of truth.'"
    - "2026-09-25: 'choose option 1 and drop phase from A5'"
  origin_claim: |
    Slice A5 of #371: record what a piece of work was expected to
    achieve and how it came out, so success is declared rather than
    inferred. The spec's acceptance criteria (its FRs) are the source of
    truth; an unattended run snapshots them at admission, keyed to the
    attempt; evaluation records the expectation, a three-state result,
    evidence, evaluator provenance and timestamps; unknown and
    unevaluated never read as failure or zero; the harness comparison
    may expose expectation success only with coverage beside it;
    sessions associate through explicit run identity, separately from
    the evaluation's identity.
---

# Plan: expectations and their evaluation (A5)

## The shape of it

```
scripts/session_analytics/config_data/ddl/postgres/011_expectation.sql   expectation_run + expectation + expectation_result + expectation_session
scripts/session_analytics/relational/db.py              _SCHEMA_VERSION 11; tables only, NO _REQUIRED_COLUMNS entry
scripts/session_analytics/constants.py                  TBL_EXPECTATION*, EXPECTATION_STATE_*, STATEMENT_SOURCE_*, VERIFIER_KIND_*, bounds
scripts/session_analytics/expectations.py               read_ledger(), recover_statements(), normalize_state(), roll_up(), upsert_run()
scripts/session_analytics/cli.py                        `session-analytics expectations` (the correlate-shaped pass)
scripts/session_analytics/api/dashboard.py              harness_aggregates gains expectation success + coverage
scripts/session_analytics/api/server.py                 GET /api/expectations
scripts/session_analytics/api/auto_build.py             run detail ENRICHED from the store (not a post-pruning fallback)
scripts/session_analytics/mcp/tools.py, mcp/server.py   the expectations tool
studio/lib/api.ts, lib/harnessView.ts                   the expectation fields + their coverage rendering
studio/components/HarnessPanel.tsx                      Expectations column, null-not-zero, coverage on hover
studio/scripts/states-check.mjs                         the new column's states
scripts/session_analytics/tests/test_expectations.py    normalization, roll-up, idempotence, association, aggregate
scripts/session_analytics/README.md                     one section
```

## Decisions

**D1 — the evaluation's identity is the run, not the session.** Keyed
`(feature_id, attempt_id, fr)`. The verifier gate runs once per run at
the landing gate and writes one `verification-results.json` per ledger,
so an evaluation is a property of the run; putting `session_ref` in the
key would copy one evaluation across every phase session. Sessions
associate separately (D5). The owner's correction, 2026-09-25, and the
evidence that carried it.

**D2 — no phase dimension.** Nothing maps an FR to a `## US<N>` phase:
the frozen contract has no phase at any level, `verification-results.json`
is one file per run, and in the one real run the FR references are
human prose inside `tasks.md` task rows. Attributing a phase through
the session would fabricate it. The owner chose this over making an
FR-to-phase mapping first-class. Owner's ruling, 2026-09-25.

**D3 — store the raw outcome AND the normalization, never one alone;
waived is tested first, and the fallback is `unknown`.** `green` (the driver's boolean, nullable) sits
beside `state`. The driver collapses richer verdicts into that boolean
in *both* directions: a verifier that timed out, one that could not be
bounded, and a visual `unreached` all read `green: false` with the
reason only in prose `detail`; and a **waived** visual entry reads
`green: true` though the driver's own comment says a waived invocation
is never indistinguishable from full verification. So `waived` is
tested **before** `green` and yields `unknown` — waived means not
verified. Normalizing without the raw value would make the derivation
unauditable; keeping only the raw value would make both "we could not
tell" and "we waived this" read as verdicts.

The fallback direction is the second half of the decision: `not_met` is
asserted ONLY for a shape known to mean a real negative (`exit
<nonzero>`, or a conformance/visual `fail`), and everything else —
including wording no version of this code has seen — is `unknown`.
Matching inconclusive shapes instead, with `not_met` as the default,
would let a reword in the driver report requirements as failed that
were never judged; this way the same drift shows up as missing
coverage, which FR-13 excludes from both sides of the rate. Owner's
corrections, 2026-09-25.

**D3b — the admitted statement is recovered or absent, never today's
text.** The frozen contract carries no statement. The pass reads
`spec.md` at the run's `branch_base_ref`, re-extracts with the parser
admission used, and accepts a statement only when its recomputed hash
equals the frozen `statement_sha`; otherwise `statement` is NULL with
`statement_source = unavailable`. Substituting the working tree's text
would silently present post-admission edits as what was admitted —
the exact history-rewriting the owner's first ruling forbids. Verified
end to end on this repo's one real run: all four statements recovered
from `f75ebaa` and hashed to the frozen values. Owner's correction,
2026-09-25.

**D4 — unevaluated is the absence of rows, not a state.** A run whose
contract was frozen but which has **no recoverable consolidated
results** has expectations and no result rows — whether because the
gate was never reached, or because it ran and aborted before writing
anything recoverable, as an unwaived visual `skip` does. That is
materially different from a verifier that ran and told us nothing
(`unknown`), and the two must not collapse. Aggregates exclude both
from numerator and denominator and report each count separately
(FR-13).

**D5 — sessions associate through an additive table, keyed by the
DISCOVERED identity.** `expectation_session` keyed
`(run_ref, copilot, session_id)` with a nullable `session_ref`. A column on
`copilot_session` would force the store to be recreated, and a recreate
permanently drops every session whose transcript has since been pruned:
on 2026-09-24 that cost 13 of 158, one of them a real 11,256-turn
session. That loss is avoidable and therefore unacceptable — the owner's
correction, 2026-09-25. The session id comes from the `system/init`
event of each `phase-N/build-result-M.json`, an explicit identifier the
driver already recorded, never a time or project heuristic. The row is
written whether or not the store holds that session yet, with
`session_ref` NULL when it does not: a later pass resolves it for a
transcript ingested since, and coverage can distinguish "recorded but
not in the store" from "no session recorded for this run" — a
resolved-only key collapses those two into the same silence.
`phase_num` rides along as provenance, not as part of any key.

**D5b — an `expectation_run` parent, and collisions are caught by a
RUN fingerprint.** `(feature_id, attempt_id)` is the run's identity,
carrying `run_fingerprint`, the contract fingerprint, `branch_base_ref`,
provenance and timestamps; expectations, results and session links hang
off it. `attempt_id` is `$$-$RANDOM$RANDOM` — no ordering, no time
component — so two runs of the same feature can share it, and if
neither the spec nor the verifiers changed they share a contract
fingerprint too. Comparing contracts alone would therefore merge two
real runs into one and silently overwrite the first's results.
`run_fingerprint` digests immutable ledger facts that differ between
any two real runs — the first `init` event's `ts` and `detail` (profile,
branch, base), `branch_base_ref`, and the contract digest — and a
stored run whose key matches but whose fingerprint differs is reported
and skipped. A ledger with no readable `init` event is skipped rather
than stored under a weaker identity. Owner's correction, 2026-09-25.

**D6 — a separate pass, not ingest.** `session-analytics expectations`,
shaped like `correlate`. The ledger is written as the run proceeds and
completed at the landing gate, long after the session transcripts it
refers to have been ingested; folding this into ingest would bind the
two rates of change together. It walks both configured roots, live and
archive.

**D7 — evidence is copied, the log is referenced.** `detail`, the
conformance/visual `evidence` string and the relative `log_path` are
stored; the log file itself is not. The ledger directory is archived
and pruned, so a path alone decays into a dangling reference — the same
reasoning that put `auto_build_verdict` in the store. Text is bounded
by a named constant. Owner's ruling, 2026-09-25.

**D8 — `evaluated_at` is the ledger's, or NULL, and NULL is common.**
Taken from the `verifier_gate` event's `ts`; NULL otherwise, never
defaulted to the ingest time, because "when the work was judged" and
"when this store heard about it" answer different questions. The event
is journalled **only after an all-green gate** — every failure path
returns before it — so a run with any failing requirement legitimately
has no `evaluated_at`. That is a property of the driver, documented
rather than papered over, and it means `evaluated_at` must never be
used as a proxy for "was this evaluated". Owner's correction,
2026-09-25.

**D9 — no rows for a refused admission.** A refused admission never
creates a ledger (the driver's own invariant), so there is nothing to
read; the pass additionally writes nothing for a run directory without
a readable `attempt_id` or without a frozen contract, and reports those
as skipped with the reason. Owner's ruling, 2026-09-25.

**D10 — the aggregate exposes success only with coverage, attributed
at RUN grain, with exclusions reported at the top level.** A run is
attributable to a harness row only when every discovered session is
linked AND every linked session resolves to that row. Attributing per
session would duplicate one run's single outcome across every version
its sessions touched; attributing a run with unresolved sessions would
assert an attribution the data has not earned. The run is the unit that
was evaluated, so the run is the unit that counts.
`runs_spanning_groups` and `runs_with_unmatched_sessions` are
**top-level** figures, not per-row — an excluded run belongs to no row,
so reporting it inside one would contradict the exclusion. Per row:
`expectations_met`, `expectations_evaluated`, `expectations_unknown`,
`expectations_unevaluated`, `runs_with_expectations`,
`sessions_with_expectations`. The rate is exactly
`expectations_met / expectations_evaluated` over states `met` and
`not_met` only, NULL when the denominator is 0, with the two excluded
counts beside it so the gap is visible. Owner's correction,
2026-09-25.

**D11 — schema 11 adds tables only, and refuses nothing.** All four
tables land in place through the create-if-absent DDL, A3's precedent;
nothing joins `_REQUIRED_COLUMNS`, so an existing store keeps working
and **no recreate is needed**. This is the whole reason D5 uses an
association table: the alternative cost a store rebuild, and a rebuild
permanently drops sessions whose transcripts have been pruned. Owner's
correction, 2026-09-25.

## Verification

- `unittest`: `test_expectations.py` — normalization over every raw
  shape (green; non-zero exit; timed out; unbounded; `unreached`;
  waived `green: true` → unknown — but NOT an unwaived `skip`, which
  the driver never writes to the results file), the roll-up rule,
  statement recovery and each unavailable path, a run whose key matches
  but whose `run_fingerprint` differs reported and skipped, no
  recoverable results as unevaluated, a directory with no `attempt_id`
  or no `init` event skipped with a reason, idempotence of a second
  pass, a second pass resolving a previously NULL `session_ref`,
  `evaluated_at` NULL for a failed run, session rows written for
  sessions absent from the store, the aggregate's NULL-not-zero, its
  per-row excluded counts and its top-level exclusions; the repo's real
  ledger as a fixture beside synthetic ones; API and MCP contract.
- `states-check`: the Expectations column — no runs, evaluated with a
  rate, all-unknown, and the coverage tooltip.
- `tsc --noEmit`, `next build`.
- A scratch store on other ports over a copy of the owner's store plus
  the real ledger: the pass binds the known phase sessions, the run
  detail is enriched with the requirement text while its ledger is
  present, `GET /api/expectations` still answers after the ledger is
  removed, and the compare shows the rate with coverage. The owner's
  instance is never
  restarted, and **their store is not recreated at all**: D11 adds
  tables in place precisely so that no rebuild is needed.
- `validate-spec.sh --all`, `check-origin-alignment.sh sa-expectations`,
  `check-doc-accuracy.sh`, the four `--check` generators, `generate.sh`
  drift, `git diff --check`, then `/review-submit`.

## Risks

- **Almost no data.** 3 of 85 bundles have a `verification.yaml`, one
  has a ledger here, 0 of 145 sessions are bound. A5 accrues forward
  and its coverage is gated on a workflow used 3 times in 85 bundles.
  Stated in the README and visible as coverage in the compare, rather
  than implied away.
- **Statement recovery depends on a reachable commit.** A ledger whose
  `branch_base_ref` has been garbage-collected, or whose branch was
  deleted and pruned, yields `statement_source = unavailable`. The hash
  still identifies the requirement; only the human-readable text is
  lost, and the row says so rather than showing current text.
- **`evaluated_at` is NULL for every failed run**, by the driver's
  design. Any future reader must not treat its presence as "evaluated".
- **`attempt_id` is `$$-$RANDOM$RANDOM`** — no ordering, no time
  component. A5 inherits it as a key because `auto_build_verdict.run_key`
  already does, and D5b's `run_fingerprint` makes a collision visible
  rather than a silent merge. The residual: two runs that collide on
  `attempt_id` AND share every fingerprinted fact — same feature, same
  base commit, same contract, and an `init` event with an identical
  timestamp to the second — would still be treated as one. That
  requires same-second starts from the same base with identical
  contracts; it is recorded as accepted, not as solved.
- **The 26 unparseable specs.** `vc_extract_frs` cannot read `FR-D1`
  letter ids or un-bulleted FR headings, so those features could never
  be admitted unattended and will never have expectations. A5 does not
  change the parser; it reports coverage.
- **Prettier churn on `.tsx`**: diffs checked after every edit.
