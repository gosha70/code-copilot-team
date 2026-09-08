# Origin alignment check — pi-team-plane-b2c

Origin: https://github.com/gosha70/code-copilot-team/issues/174 and
specs/pi-team-plane-b2c/origin/2026-09-08-owner-decisions.md

Origin claim:
> Cross-team visibility into active autonomous runs, global token
> spend and aggregated metrics; sessions report progress to a central
> interface; `pi-team status`-style tracking for all current team
> tasks. Topology: one shared Postgres store every developer writes
> to; identity: derived developer_id, access by database credentials
> on a trusted LAN (owner, 2026-09-08).

Working claim:
> specs/pi-team-plane-b2c/{spec,plan,tasks}.md: a read-only team
> status payload over the shared store (per-developer liveness from
> heartbeats, current work, cost/sessions per time window; per-project
> and total rollups), a Team tab in the Studio, and a `team status`
> CLI command; setup documented. Budgets/runaway alerting (Slice D)
> follow in the next PR against the same issue. No schema change, no
> daemon, no app-level auth.

Verdict: aligned
Confidence: high

Checked 2026-09-08 by re-reading #174, its reopening comment (Slices
B–E remain), plane-shaping.md, the shipped pieces (db.py dialects,
005_heartbeat.sql, dashboard.developer_aggregates, cost.py) and the
owner's two answers.
