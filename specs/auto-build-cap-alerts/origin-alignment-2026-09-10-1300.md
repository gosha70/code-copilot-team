# Origin alignment check — auto-build-cap-alerts

Checked 2026-09-10 13:00, before the unattended run.

Origin: specs/auto-build-cap-alerts/origin/2026-09-10-second-unattended-run.md
(the owner's instruction to run the next real feature; runs 1 and 4 of
2026-09-09 as the evidence)

Origin claim:
> An auto-build run that is burning its cost or wall-clock cap, or has
> passed it, should appear among the Team tab's alerts, derived from
> its ledger on every read like every other alert, so a person sees it
> without opening the Runs tab.

Working claim:
> specs/auto-build-cap-alerts/{spec.md,plan.md,tasks.md} bind that as
> FR-1..FR-4: `auto_build_alerts()` over the runs list the Runs tab
> already derives, warning at 80% and breach at 100% of the cost or
> wall-clock cap for unconcluded runs; merged into `all_alerts()`,
> the two team routes and the `team` CLI; derived, no table, no config
> key, no Studio change. One phase, deterministic verifiers per FR.

Verdict: aligned
Confidence: high

Checked by re-reading the owner's message, the four ledgers'
caps/totals/elapsed (run 1: 5605 s of 5400; run 4: $7.30 of $10.00),
`api/alerts.py` (budget warning share, report shape), and
`api/auto_build.py` (`list_runs`, `concluded`, `elapsed_sec`).
