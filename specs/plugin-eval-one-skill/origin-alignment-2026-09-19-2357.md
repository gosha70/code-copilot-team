# Origin alignment check — plugin-eval-one-skill

Checked 2026-09-19 23:57, before plan approval and before anything paid.

Origin: specs/plugin-eval-one-skill/origin/2026-09-19-owner-direction-step-3.md
(owner messages in the #363 sessions) and issue #363, P3.

Origin claim:
> One bounded experiment on a single skill, with a stated budget, to
> answer: does plugin eval tell us something benchmarks/ cannot? Three
> cases × three runs × two arms = 18 agent runs plus graders.
> --max-cost-usd 5, concurrency 1, --no-publish, the budget described
> honestly before approval. Paid evaluation is separately authorized.

Working claim:
> spec.md FR-1..FR-6 and plan.md: one invocation of claude plugin eval
> against a scratchpad copy of the generated plugin, three cases on the
> copyright-headers skill, free regex and tool_used graders only, 18
> runs, --max-cost-usd 5, --concurrency 1, --no-publish, run once, then
> findings.md answering P3's question with its limits.

Matches the origin as written: one skill; three cases, three runs, two
arms; the $5 ceiling with the in-flight overrun stated; concurrency 1;
--no-publish; nothing paid before authorization; nothing built on top.

Differences from the origin, each surfaced in the bundle:

1. The issue said "package skills into the plugin only if the answer is
   yes". The owner later reordered this: packaging was step 2, done
   first, "not as a prerequisite for adoption". The experiment no longer
   gates packaging. Recorded in the origin file.
2. The choice of skill (copyright-headers) is mine, with reasons in
   FR-1. The owner has not ruled on it.
3. Flags the owner did not name: --model sonnet, --trust-plugin,
   --threshold 0, --json, --report. Each is justified in plan.md; the
   model choice is a judgement call.
4. "Plus applicable graders": the plan uses free graders only, so there
   are no judge calls. Cheaper than the origin allowed for, and it
   narrows what is tested to behaviour a pattern can see.
5. The cases live in the spec bundle and run from a scratchpad copy,
   because the eval directory must sit inside the plugin folder and the
   shipped plugin's contents are pinned by a test.

Verdict: aligned
Confidence: medium

Medium, not high: differences 2 and 3 are choices the owner has not
ruled on yet.

Checked by re-reading the owner's step 3 messages and the issue's P3
text, reading the plugin-evals documentation and the command's help,
generating a blank case with init --bare, reading benchmarks/ for an
existing with/without-skill arm (there is none), and testing every
regex grader against a correct and an incorrect sample reply.
