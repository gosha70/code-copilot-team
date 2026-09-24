# Owner direction — Session Analytics gaps, slice A4 (#371)

Owner messages in this session, verbatim where quoted.

2026-09-22:

> Ok, based on your summary I would rather work on extending capabilities
> of "Session Analysis" rather using ML Flow. Could you please identified
> ML Flow features which we can add to CCT Session Analysis tooling?

> Can you start planing the addressing the features listed in
> https://github.com/gosha70/code-copilot-team/issues/371?

The green-field ruling, which applies to every slice:

> We can approach with "Session Analysis" as a green field project (I
> still not officially release it); so I am good about not worry about
> the backward compatibility - data migration

Issue #371, row A4, as filed:

> **Harness version + compare.** Today: nothing records the cct version,
> the rules/skills content hash or the providers-profile hash on a
> session; the only A/B mechanism compares judge rubrics. Build: stamp
> each session at ingest with the harness version and let the Studio
> group and compare sessions by it (cost, turns, errors, rework,
> judge scores). Answers "did the new skill change anything".

Success measure for A4 in the issue: "two harness versions can be put
side by side over the sessions that ran under each."

Standing rulings carried over from A1–A3 (2026-09-22/23): one PR per
slice under #371, no close marker; a column on an existing table cannot
be added in place, so the store is recreated and re-ingested with
`--full` on the owner's word (A1); a new table lands in place (A3); the
owner's running instance is never restarted by the builder.

The A4 bundle was written after A3 merged (PR #374, 2026-09-24); the
owner has not yet approved it.

2026-09-24, the owner's review of the bundle (pasted; adopted):

> Choose "Approve with changes" and split A4a/A4b. The capture-before-
> ingest design is right, but four correctness gaps need resolving
> first.
>
> 1. Repeated SessionStart events cannot be "last wins." [...] Persist
> the earliest valid stamp and add `harness_mixed`. [...] Identical
> resume/compaction stamps do not make it mixed. Test both cases.
>
> 2. Plugin stamping is currently misleading. [...] For this slice,
> exclusion is the smaller honest choice.
>
> 3. Use the full 40-character Git SHA. [...] Shorten it only for
> display.
>
> 4. The comparison must include an actual judge score. [...] Add
> packaged-rubric `avg_interaction_quality`, plus labelled/answered
> coverage. All judge-derived metrics must be null—not zero—when no
> applicable labels exist.
>
> 5. Dashboard links and filters must agree. [...] I recommend the
> generic closed filter.
>
> Rulings otherwise: D1 accepted [...]; D2 accepted with full SHA and
> honest naming; `rules_digest` actually covers rules, skills, agents
> and commands, so `instructions_digest` would be clearer. D3 accepted
> [...]. D4 accepted after replacing last-wins with earliest-plus-mixed.
> D5 accepted with interaction quality and coverage added. D6 accepted
> after fixing the link/filter contract. D7 and D8 accepted.
>
> Split it: A4a: hook, installer stamp, transcript CLI version, six
> columns including `harness_mixed`, adapter join, session header.
> A4b: aggregates, all-dimension filtering/facets, Dashboard panel and
> MCP surface. [...] Amend the bundle with these rulings, rerun
> alignment, then start A4a task 1.

Checked before amending: `scripts/generate.sh:88-97` ships only the
hooks in `CC_PLUGIN_HOOKS` and the plugin's `hooks.json` is authored,
so exclusion is a no-op in generation; `session_kpi.avg_interaction_quality`
exists (`002_analytics.sql:46`).
