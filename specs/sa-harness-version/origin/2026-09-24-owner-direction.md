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

2026-09-24, the owner's review of PR #375 at e9f5540 (pasted; all
three adopted):

> [P1] setup.sh never registers the new hook. The hook file is copied,
> but neither the --sync settings merge nor the full-install
> HOOKS_CONFIG/merge adds harness-stamp.sh. [...] Add it to HOOKS_CONFIG
> and both ensure_hook_command paths, with a temp-HOME regression
> proving fresh and existing settings contain it exactly once.
>
> [P1] Re-ingest can replace the earliest stored stamp. These COALESCE
> expressions prefer the newly ingested value. [...] Prefer the existing
> non-null fact, fill only existing NULLs, and set mixed when both
> existing and incoming values are non-null and differ. Add the missing
> regression: ingest A, replace the ledger with B only, re-ingest, and
> assert A remains with mixed=true.
>
> [P2] JSON configuration moves only the reader. [...] Keep one shared
> control: either make this environment-only and remove the JSON key,
> or teach the hook to resolve the same configured path.
>
> The core design is otherwise aligned [...] Do not merge until these
> three findings are fixed and pinned by tests.

2026-09-24, A4b build note — one group the plan did not name.

The owner's own store, rebuilt on schema 10, showed a case neither the
plan nor the review anticipated: 144 of 145 sessions carry a
`cli_version` from their transcripts while none carries a `cct_sha`
(the hook was installed after they ran). Grouping by `cct_sha` would
have folded all of them into `unstamped`, which is false — they ARE
stamped, just not on that dimension.

So the compare reports a third named group, `absent`, meaning "stamped,
but this dimension was not recorded", with its own filter value
`absent:<dimension>`. Grouped by `cct_sha` the owner's store reads: 0
comparable values, 34 absent, 6 mixed, 1 unstamped — the honest answer
instead of a fabricated comparison. This follows the owner's ruling
that mixed sessions get a named row rather than being folded into a
version; the same reasoning applies one level down.

2026-09-24, the owner's review of the A4b build (pasted; all four
adopted):

> [P1] Mixed and unstamped groups overlap. A session whose earliest
> stamp has every fact NULL but whose later stamp differs has
> harness_mixed=true. This CASE classifies it as unstamped before
> checking mixed, while harness_clause('mixed') and
> harness_clause('unstamped') both select it. [...] Check mixed first,
> exclude mixed from the unstamped predicate, and make harnessState
> prefer mixed too.
>
> [P1] PostgreSQL rejects the facet predicate. harness_mixed is BOOLEAN
> [...] `harness_mixed = 0` fails with `operator does not exist: boolean
> = integer`. Because /api/sessions always computes facets, the Sessions
> page fails on PostgreSQL. Use a cross-dialect boolean predicate such
> as `harness_mixed IS NOT TRUE`.
>
> [P1] Rates use the wrong denominator. [...] With one session
> containing 1 labelled rework turn and another containing 99 labelled
> non-rework turns, the API reports 0.50 instead of 0.01. Weight
> rework_rate and correction_rate by labeled_turn_count; keep
> avg_interaction_quality as the explicitly specified mean of
> per-session means.
>
> [P2] Real values collide with named groups. [...] I reproduced
> cli_version='mixed': the panel row counted two sessions while its link
> returned only the genuinely mixed one. Keep group kind separate from
> dimension value internally/API-side, and key React rows by kind plus
> value.

Both P1 classification bugs were reproduced here before fixing: the
all-NULL-plus-mixed session answered to both filters, and the literal
`cli_version='mixed'` row linked to the wrong session. `IS NOT TRUE` was
confirmed to behave on SQLite 3.48 as it does on PostgreSQL.
