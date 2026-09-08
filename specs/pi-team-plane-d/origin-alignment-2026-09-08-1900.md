# Origin alignment check — pi-team-plane-d

Origin: https://github.com/gosha70/code-copilot-team/issues/174 and
specs/pi-team-plane-d/origin/2026-09-08-owner-decisions.md

Origin claim:
> "Runaway recursive agent loops can be audited, alerted, or flagged
> if they breach budget bounds" (issue #174 acceptance), over the
> shared Postgres team store with trusted-LAN access the owner chose
> on 2026-09-08; owner on the same day: proceed with #174 after the
> team store merged.

Working claim:
> specs/pi-team-plane-d/{spec,plan,tasks}.md: budgets and runaway
> thresholds as configuration; a read-only evaluation over the store
> producing warning/breach alerts (team/developer/project budgets;
> runaway sessions by recent turn rate, error share, cost rate) that
> are re-derived on every read; surfaced on the Team tab and by a CLI
> command whose exit code flags a breach for cron/CI. No daemon, no
> schema, no termination.

Verdict: aligned
Confidence: high

Checked 2026-09-08 by re-reading #174's acceptance criteria, the
shaping doc's Slice D line ("Budget entities; breach detection against
rollups; runaway-loop detection off the audit trail / checkpoint-count;
alert surface (log/notify)"), the owner's decisions, and PR #324's
payload the budgets read from. "Budget entities" are configuration
rather than tables because nothing needs to be stored per alert; the
checkpoint-count signal is not used because the store holds only the
current count (no history), so the runaway signals are the turn rows.
