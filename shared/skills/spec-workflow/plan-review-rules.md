# Plan review: stop at "safe and unambiguous", not "proven"

Adopted after #222's planning loop: 13 revisions, 39 findings, ~982 lines
of core planning artifacts, 13 alignment records. The scope was settled by
rev 2. Everything after rev 6 was largely self-inflicted — the same
contract restated across `spec.md`, `plan.md`, `tasks.md`, worked examples,
matrices and success criteria, so correcting one representation left
another stating the old decision.

## Rules

1. **One normative source per behaviour.** Exactly one document defines it.
   Everything else links.
2. **The plan references spec requirements; it does not restate them.**
   A plan that paraphrases an FR will eventually contradict it.
3. **Tasks reference FRs; they do not duplicate algorithms.** A task says
   which requirement it implements and where the tests go.
4. **One holistic review, then one correction pass.** Not a stream of small
   rounds — a reviewer who surfaces three findings at a time invites a
   serial loop, which is a review-process failure as much as an authoring
   one.
5. **After the correction pass, only P0/P1 implementation blockers hold
   approval.** A blocker is something that makes implementation ambiguous
   or unsafe. Everything else is resolved against working code.

## The principle

Planning exists to make implementation safe and unambiguous. It does not
exist to prove the implementation correct before the implementation
exists — that is what executable tests are for, and a claim proven by a
running test is worth more than the same claim modelled in prose.

## The recurring smell

If a review round's findings are mostly "section X still says the old
thing", the artifacts have too many representations of one decision.
Remove a representation; do not add another correction.
