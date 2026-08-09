# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 02:20
Trigger: plan.md, spec.md and tasks.md revised to rev 6 after the user's
fifth review round; the rev-5 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's fifth-round findings (attended accounting, stale contract
  ownership, stale prune assertions).

## Working claim

Scope unchanged since rev 2. Rev 6 makes the documents internally
consistent with rev 5's own decisions and splits the result file into two
independent optional sections so no path fabricates work it did not do.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 6 changed, per finding

1. **The result schema could not represent an attended run honestly.** Rev 5
   required `accounting` in every result, but attended profiles never run
   admission or its `test.command` — so an attended fresh run would have had
   to emit synthetic zero accounting to pass validation, and an attended
   resume should emit no file at all. The file now carries two INDEPENDENT
   optional sections (`contract`, `admission`) whose presence follows what
   actually ran, with a normative emission table. Synthetic zero accounting
   is explicitly prohibited: an absent section means "did not run".
2. **Three sections still assigned contract creation to admission** after
   rev 5 moved it to the preflight initialiser — FR-4a, a plan step, and a
   task. Following them would have recreated the exact attended-path bug
   rev 5 existed to fix. All swept; the initialiser owns the contract and
   the admission bar contributes only its own validation and accounting.
3. **T7 and SC-7 still asserted the superseded prune scope** ("attended
   never prunes") after FR-8 was widened to include attended brownfield
   baseline capture. Both now assert the real trigger — before ANY
   throwaway-worktree creation — and that paths creating none do not prune.

All three are the same root cause: rev 5 edited some sections and left
others stating the old decision. That is the shotgun-surgery failure my own
standards name, and the sweep is now part of the process rather than a
reviewer's job — this revision ends with a grep across all three documents
for the superseded wording, and the rename to `preflight-result` was carried
through the same way.

## Verdict

Verdict: aligned
Confidence: high
