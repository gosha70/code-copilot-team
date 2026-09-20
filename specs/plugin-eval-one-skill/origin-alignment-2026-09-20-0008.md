# Origin alignment check — plugin-eval-one-skill

Checked 2026-09-20 00:08, after the run and the findings, before review. Supersedes the 2026-09-19 23:57 record. This check compares the origin with what was done, not only with what was planned.

Origin: specs/plugin-eval-one-skill/origin/2026-09-19-owner-direction-step-3.md
(owner messages in the #363 sessions) and issue #363, P3.

Origin claim:
> One bounded experiment on a single skill, with a stated budget, to
> answer: does plugin eval tell us something benchmarks/ cannot? Three
> cases × three runs × two arms = 18 agent runs plus graders.
> --max-cost-usd 5, concurrency 1, --no-publish, the budget described
> honestly before approval. Paid evaluation is separately authorized.

Working claim (as done):
> One invocation of claude plugin eval, run once, on the
> copyright-headers skill: 18 of 18 runs, --max-cost-usd 5,
> --concurrency 1, --no-publish, $0.9149 actual, against a scratchpad
> copy of the generated plugin. findings.md answers P3's question (yes),
> states the limits, and proposes a disposition for #363 without
> closing it.

Each clause of the origin against what happened:

1. "One bounded experiment on a single skill." One invocation, one
   skill, no retry and no second run, although the transcripts turned
   out not to be kept.
2. "With a stated budget ... described honestly before approval." The
   ceiling, the in-flight overrun and an estimate marked as an estimate
   were put to the owner before anything ran. Actual spend $0.9149.
3. "18 agent runs, plus applicable graders." 18 of 18. Free graders
   only, so no judge calls.
4. "--max-cost-usd 5 ... concurrency 1 and --no-publish." Exactly so;
   the report stayed local.
5. "Does plugin eval tell us something benchmarks/ cannot?" Answered in
   findings.md with the evidence and six stated limits.
6. "Paid evaluation remains a separate authorization." The owner
   authorized this invocation, on Sonnet, before it ran.

Differences from the origin, all ruled on or disclosed:

1. "Package only if the answer is yes" was reordered by the owner
   before this step; recorded in the origin file.
2. The skill and the extra flags were my choices; the owner approved
   the plan as designed and chose the model.
3. The cases run from a scratchpad copy, because the eval directory
   must sit inside the plugin folder and the shipped plugin is pinned
   by a test. Nothing was added to the shipped plugin.

Verdict: aligned
Confidence: high

High, where the earlier record was medium: the choices that held it at
medium (skill, model, flags) were approved by the owner, and the run was
checked against every clause of the origin.

Known limits, none a departure from the origin: the baseline replies
were not retained, so "no header" and "a different header" are not
distinguished; nine runs per arm with no variance reported; one model.
All three are stated in findings.md.

Re-checked after the owner's review returned two reporting corrections,
both applied across the bundle: the with arm loads the whole plugin, so
the extra cost and turns are whole-plugin overhead and the experiment
tests copyright-header behaviour with versus without the plugin, not one
skill in isolation; and the $5 figure is a launch budget with a possible
in-flight overrun, never a hard ceiling. Both narrow the claims; neither
changes what was run. Verdict and confidence unchanged.
