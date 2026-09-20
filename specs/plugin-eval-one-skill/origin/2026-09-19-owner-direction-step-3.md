# Owner direction — plugin eval, step 3 (#363 P3)

Owner messages in the #363 sessions, verbatim where quoted. The full
three-step direction is recorded, merged, in
`specs/plugin-hooks-load-fix/origin/2026-09-19-owner-direction.md`.

Issue #363, P3, as the owner wrote it:

> **Proposal.** One bounded experiment on a single skill, with a stated budget, to
> answer: does plugin eval tell us something `benchmarks/` cannot? Package skills
> into the plugin only if the answer is yes.

Step 3, as the owner set it on 2026-09-19:

> 3. Evaluate one skill afterwards—not as a prerequisite for adoption. Two corrections
>    to the proposed experiment:
>    - Three cases × three runs × two arms means 18 agent runs, plus applicable graders.
>    - --max-cost-usd 5 stops subsequent runs; an in-flight run can exceed $5. Use
>      concurrency 1 and --no-publish, and describe the budget honestly before approval.
> ...
> Paid evaluation remains a separate authorization

After steps 1 and 2 were merged (PRs #364, #366), later on 2026-09-19 (local time):

> Finish #363 issue

Note on "package skills into the plugin only if the answer is yes": the
owner later reordered this. Packaging (step 2) was done first, on the
owner's instruction, "not as a prerequisite for adoption". The
experiment's answer therefore no longer gates packaging; it informs
whether plugin eval is worth using again.
