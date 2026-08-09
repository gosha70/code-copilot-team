# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 01:40
Trigger: plan.md and spec.md revised to rev 5 after the user's fourth review
round; the rev-4 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's fourth-round findings (lifecycle matrix, result-file schema).

## Working claim

Scope unchanged since rev 2 — `verification.coverage` only. Rev 5 gives the
lifecycle its missing dimensions (block presence × fresh/resume × profile,
as a normative matrix), moves contract CREATION out of admission into a
preflight step both profiles share, rescopes the prune to "before this run
creates a throwaway worktree", and pins the result file to a closed,
versioned schema whose `resume` mode forbids `coverage_contract`.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 5 changed, per finding

1. **Rev 4 assumed every run has a frozen contract.** Two cases break that,
   and one of them was a REGRESSION I introduced rather than a gap I left:
   FR-7b's unconditional "missing contract on resume fails closed" would
   have broken the resume of every existing no-block run in the repo. The
   second: attended runs can opt into coverage but never invoke admission,
   so rev 4 promised a T6 gate whose precondition nothing created. Contract
   creation is now a preflight step keyed on the BLOCK and shared by both
   profiles; the admission bar stays unattended-only. The matrix is
   normative, and the prune follows the honest trigger — immediately before
   this run creates a throwaway worktree, which now includes brownfield
   baseline capture on an attended run.
2. **The result file was validated against nothing.** It now has an
   authoritative closed, versioned schema with a `mode` discriminator, and
   `mode: resume` FORBIDS `coverage_contract`. That prohibition is the
   load-bearing part: it turns "a resume cannot overwrite frozen policy"
   into something the driver checks, rather than a discipline the admission
   code is trusted to observe.

## Verdict

Verdict: aligned
Confidence: high
