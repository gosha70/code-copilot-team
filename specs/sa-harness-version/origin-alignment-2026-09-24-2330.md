# Origin alignment check — sa-harness-version (A4b built)

Checked 2026-09-24 23:30, after the A4b build and before review. A4a is
merged (PR #375, 3969c88); this record covers the compare.

Origin: specs/sa-harness-version/origin/2026-09-24-owner-direction.md
(the owner's messages, the green-field ruling, the 2026-09-24 bundle
review and the PR review) and issue #371, row A4.

Origin claim (A4b part):
> Let the Studio group and compare sessions by the harness version
> (cost, turns, errors, rework, judge scores), two versions side by
> side; add packaged-rubric avg_interaction_quality plus labelled
> coverage, with every judge-derived metric null — not zero — when no
> applicable labels exist; one closed dimension/value filter covering
> all five dimensions including an explicit unstamped case, so every
> panel row links to its sessions.

Working claim (as built):
> dashboard.harness_aggregates(db, noise, by) over a CLOSED dimension
> set, inheriting developer_aggregates' three refusals (no ranking, no
> unknown-cost-as-zero, the degenerate case named); per row sessions,
> median turns and tool calls (the package's one percentile rule,
> reused not reimplemented), errors per 100 turns, priced cost with
> coverage, and avg_interaction_quality / rework_rate / correction_rate
> from session_kpi under load_rubric().name, each null without labels
> and carrying sessions_judged and labeled_turns; named rows for mixed,
> absent and unstamped; GET /api/dashboard/harness?by= (400 otherwise)
> and the MCP tool compare_harness_versions; the closed `harness`
> filter (<dimension>:<value> | mixed | unstamped | absent:<dimension>)
> on the sessions list with a facet per dimension; HarnessPanel on the
> Dashboard with a dimension picker, every row linking to its sessions.

Each clause against the artifact: group and compare — harness_aggregates
+ HarnessPanel; cost/turns/errors — the row fields; rework — rework_rate
and correction_rate; judge score — avg_interaction_quality with
sessions_judged; null not zero — _mean returns None for an empty sample,
judged() renders "—", tested and asserted in states-check; one closed
filter over all five dimensions + unstamped — harness_clause and the
filter bar; every row links — rowFilter/rowHref, with the facet aligned
to the filter so no offered value returns nothing.

Beyond the ruling, and why: a third named group, `absent` (stamped, but
this dimension not recorded). The owner's live store made the case
concrete — folding 34 cli-only sessions into "unstamped" would have
claimed they carry no stamp. Recorded in the origin file.

Differences from the origin: a session-level success score still waits
for A5's expectations (Out of scope, unchanged).

Verdict: aligned
Confidence: high
