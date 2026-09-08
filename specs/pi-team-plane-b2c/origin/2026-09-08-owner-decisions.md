# Origin: #174 topology and identity decisions (owner, 2026-09-08)

Issue #174 (epic): "Pi is inherently designed as an individual
developer's CLI utility. As we scale our custom Pi adoption across the
organization, we lack cross-team visibility into active autonomous
runs, global token spend, and aggregated optimization metrics."
Acceptance: "Developer sessions can stream structural progress updates
to a centralized team interface. Runaway recursive agent loops can be
audited, alerted, or flagged if they breach budget bounds. Upstream
status queries (`pi-team status`) display precise tracking data for
all current team tasks."

Owner, 2026-09-08: "start https://github.com/gosha70/code-copilot-team/issues/174"

Asked (the two decisions `specs/pi-team-controller/plane-shaping.md`
reserved for the owner) and answered 2026-09-08:

- Topology: **Shared Postgres team store** — every developer's
  ingest/watch writes to one team Postgres (the shipped compose file);
  live status = heartbeats in the shared store.
- Identity/auth: **Trusted LAN, database credentials only** —
  `developer_id` stays the derived identity (attribution, not auth);
  access is whoever holds the team DSN; no app-level login.

Standing rule from the owner (2026-09-07): no new GitHub issues; work
lands as PRs against the existing issue.
