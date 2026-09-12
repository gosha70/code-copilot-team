# Origin alignment check — runs-attempt-history

Checked 2026-09-12 01:30, before the unattended run (re-checked after FR-6 gained the verifier note: the states script runs in CI, not as a verifier — the isolated worktree has no node_modules).

Origin: specs/runs-attempt-history/origin/2026-09-12-owner-directive.md
(the owner's instruction to run the next wanted feature; the ledger
artifacts D1/D2 added and the Runs tab's silence about them)

Origin claim:
> The Runs tab must show what the ledger now records — the probe's
> answer, a round-time fallback, earlier terminations after a resume —
> so a resumed run that landed is not read as a plain landing.

Working claim:
> specs/runs-attempt-history/{spec.md,plan.md,tasks.md} bind that as
> FR-1..FR-6: three derived fields on the run record from
> reviewer-probe.json, termination-<epoch>.json and the newest round's
> findings; CLI lines; three pure Studio helpers rendered on the card
> and asserted by the states script; unit tests per FR. Derived, no
> store, no config, no driver change. One phase, deterministic
> verifiers per FR.

Verdict: aligned
Confidence: high

Checked by re-reading the owner's message, the D1/D2 ledger writes
(`reviewer_probe`, `fallback` in findings, `termination-<epoch>.json`,
`resumed`), `api/auto_build.py`'s read_run, `lib/runsView.ts`, and run
5's archived ledger (reviewer-probe.json present, unread).
