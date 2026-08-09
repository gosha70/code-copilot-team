# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 03:40
Trigger: plan.md, spec.md and tasks.md revised to rev 8 after the user's
seventh review round; the rev-7 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's seventh-round findings (attended import gate, resume path
  source, and acceptance criteria that were reported but absent).

## Working claim

Scope unchanged since rev 2. Rev 8 closes the last lifecycle hole (import
gated on producers, not on admission), pins resume path selection to the
frozen snapshot, and actually writes the criteria rev 7 claimed.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 8 changed, per finding

1. **The import gate waited on admission**, which attended profiles never
   run — so `fresh-attended-block` had no defined import transition at all.
   Import is now gated on "every producer applicable to this path has
   succeeded"; unattended paths additionally require the admission bar.
2. **Resume path selection was not pinned to a config source.** Computing
   it from live `automation.json` would let someone delete the coverage
   block between runs, turn `resume-unattended-block` into
   `resume-unattended-noblock`, and skip the frozen-contract validation
   FR-7b exists to enforce. FR-9e requires the frozen snapshot; SC-5f is
   the live-edit regression.
3. **Rev 7 reported acceptance-criteria updates that were never written.**
   SC-5d still described the superseded `mode` schema and SC-5e did not
   exist. Cause: a `str.replace` with no assertion, whose pattern had
   already been altered by an earlier edit in the same batch — so it
   silently no-opped and I reported it as done.

   Process change, applied from this revision on: every documentation edit
   goes through a helper that ASSERTS its anchor exists, and each revision
   ends by grepping for the new text rather than asserting it was written.
   Both guards fired during this revision (twice), catching two anchors I
   had wrong before they became false claims — which is exactly the
   difference between this round and the last.

## Verdict

Verdict: aligned
Confidence: high
