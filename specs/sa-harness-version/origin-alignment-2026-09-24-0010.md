# Origin alignment check — sa-harness-version

Checked 2026-09-24 00:10, before plan approval and before any
implementation.

Origin: specs/sa-harness-version/origin/2026-09-24-owner-direction.md
(the owner's messages, the green-field ruling, the standing rulings
from A1–A3) and issue #371, row A4.

Origin claim:
> Stamp each session with the harness version (the cct version, the
> installed rules/skills content hash, the providers-profile hash) and
> let the Studio group and compare sessions by it (cost, turns, errors,
> rework, judge scores), so "did the new skill change anything" is
> answerable; two harness versions side by side over their sessions.
> Schema changes allowed; recreate, not migrate.

Working claim:
> spec.md FR-1..FR-8 and plan.md D1–D8: a SessionStart hook records
> five facts per session (cct_version, cct_sha, rules_digest,
> providers_digest; cli_version from the transcript) into a ledger;
> ingest joins the ledger by session id into five nullable columns on
> copilot_session (schema 10, store recreated on the owner's word); a
> GROUP BY compare behind GET /api/dashboard/harness with the
> developer_aggregates rules; a Dashboard panel, two A2 filters, the
> stamp on the session header.

Each clause against the plan: cct version — D2 (`cct_version`,
`cct_sha` from `harness.json`); rules/skills hash — D2 `rules_digest`;
providers hash — D2 `providers_digest`; stamp each session — D1, FR-1,
FR-3; group and compare by it — D5, FR-5, FR-6; cost/turns/errors/
rework — FR-5 metrics; judge scores — FR-5 carries the two rubric
rates, the rest deferred to A5 (surfaced below); side by side — the
panel's rows per dimension value.

Differences from the origin, surfaced in the bundle:

1. "At ingest" is read as "written at ingest, captured at session
   start" (D1): capture at ingest would mis-stamp every re-ingest.
   The columns are still written by ingest.
2. Judge *scores* are limited to the rework and correction rates the
   store already carries per turn; a session-level score needs A5's
   expectations. Named in FR-5 and Out of scope.
3. A fifth fact, `cli_version`, is added because the transcript
   carries it for free and it is a real dimension.
4. A schema change on an existing table forces the store recreation
   the owner accepted for A1; stated as D3 and in Constraints.
5. The Studio surface is a Dashboard panel + filters, not a new page
   (D6), keeping the #307 nav cut.

Verdict: aligned
Confidence: medium

Medium, not high: D1 (hook, not ingest capture), D3 (columns → store
recreation) and the one-PR-vs-two question are the owner's to rule on.

Checked by reading the session DDL and upsert, the adapter's metadata
site, the transcript's record keys on a real session, the SessionStart
hooks and their stdin contract, setup.sh's install paths, the
heartbeat's shape, developer_aggregates and its route, the A2 filter
path, and the A1 refusal.
