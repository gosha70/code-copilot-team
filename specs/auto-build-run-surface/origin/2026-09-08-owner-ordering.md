# Origin: issue #190 §12 and the owner's ordering

No new GitHub issue (owner's standing rule). The requirement is §12 of
issue #190, "Monitor and tune":

> **Live run surface.** Consolidate … into one rendered page: phase,
> round, open blockers, **verifier graph state**, cost burn vs. ceiling
> (with estimated portion distinguished), score trend, policy decisions
> taken. Terminal outcome shown as `landed` / `terminated_policy` /
> `failed` — never collapsed to pass/fail.
>
> **Outcome labeling.** Every run records outcome, disposition reason,
> rounds per phase, metered cost, verifier coverage at admission — plus
> the label that matters: **the human verdict on the resulting PR**
> (merged unmodified / merged with fixes / rejected).

Owner, 2026-09-08, on "proceed to #190" after increments A–C merged:

> not D. Take option 3, and before building it, run the unattended
> profile for real at least once. … Ordering, then: one real run, then
> option 3 over its data, then D scoped by that data, with 2 interleaved
> only on demonstrated need.

"Option 3" was the §12 run surface and verdict label. The real runs
happened 2026-09-09: four unattended attempts of `team-developer-aliases`
(runs 1–3 `terminated_policy`, run 4 `landed` as PR #331, merged after a
human review requested changes). Their ledgers are the data this page is
built over:

- `.cct/auto-build-archive/team-developer-aliases-run{1,2,3}/`
- `.cct/auto-build/team-developer-aliases/`

Human review of PR #331 (2026-09-09) is the first verdict to record:
automation PASS → human changes_requested → corrected → merged. In the
§12 vocabulary that is **merged with fixes**.
