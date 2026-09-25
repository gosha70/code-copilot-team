# Origin alignment check — sa-expectations (after the bundle review)

Checked 2026-09-25 04:00, after the owner's review of the first bundle
and the revisions for it. Supersedes the 0230 record. Nothing is built.

Origin: specs/sa-expectations/origin/2026-09-25-owner-direction.md (the
#371 A5 row, the owner's seven starting rulings, their ruling dropping
phase, and their seven corrections to the first bundle) and issue #371.

What the review corrected, and where it now stands:

1. **No session columns, no rebuild.** `expectation_session` is an
   additive association table keyed `(run_ref, session_ref)`; schema 11
   adds tables only and joins nothing to `_REQUIRED_COLUMNS`, so an
   existing store keeps working. This removes the recreate that would
   have repeated the 2026-09-24 loss of 13 sessions. FR-10, D5, D11.
2. **`expectation_run` parent** keyed `(feature_id, attempt_id)` with
   the contract fingerprint, `branch_base_ref`, provenance and
   timestamps; a same-key-different-fingerprint arrival is reported and
   refused, never upserted. FR-1, D5b.
3. **Statement recovered or unavailable, never today's text.** Read at
   `branch_base_ref`, accepted only on a hash match; otherwise NULL with
   `statement_source = unavailable`. Verified end to end: 4 of 4
   statements of the one real run recovered from f75ebaa and hashed to
   the frozen values. FR-3, D3b.
4. **Waived is `unknown`, tested before `green`.** The driver writes a
   waived visual entry `green: true`; waived means not verified. The
   claim that A5 could recover an *unwaived* visual `skip` is removed —
   that path aborts the gate before any result is written. FR-5, D3.
5. **A4b attribution at run grain.** An expectation counts in a harness
   row only when every session linked to its run resolves to that row;
   runs spanning groups are excluded and reported. FR-12, D10.
6. **`evaluated_at` is NULL for every failed run**, because
   `verifier_gate` is journalled only after an all-green gate. Stated as
   a property of the driver, and it must never be read as "was this
   evaluated". FR-7, D8.
7. **tasks.md renumbered** against FR-1..FR-13; it had referenced
   FR-9..FR-12 against a spec ending at FR-11.

Expectation-aware judge scoring is recorded as an explicit A5
SUCCESSOR in Out of scope, with the issue's "that the judge and the
outcome logic can score against" named as describing that successor.
The no-phase decision is unchanged and approved.

Verdict: aligned
Confidence: high

High: every decision now carries the owner's explicit ruling, and every
behavioural claim the bundle rests on was verified in the code or
measured on the one real ledger.
