# Origin alignment check — sa-harness-version

Checked 2026-09-24 00:40, after the owner's review of the bundle and
before any implementation. Supersedes the 00:10 record.

Origin: specs/sa-harness-version/origin/2026-09-24-owner-direction.md
(the owner's messages, the green-field ruling, the standing A1–A3
rulings, and the 2026-09-24 review with its corrections) and issue
#371, row A4.

Origin claim:
> Stamp each session with the harness version and let the Studio group
> and compare sessions by it (cost, turns, errors, rework, judge
> scores); two harness versions side by side. Capture at SessionStart,
> join at ingest; earliest stamp plus a mixed flag; full sha; honest
> digest name; hook excluded from the plugin; a real judge score with
> coverage, NULL not zero; links and filters agree through one closed
> filter; two PRs, A4a stamp then A4b compare.

Working claim:
> spec.md FR-1..FR-8 and plan.md D1–D8 as amended: a setup.sh-only
> SessionStart hook writes five facts per session (full-sha
> cct_sha, instructions_digest, providers_digest, cct_version;
> cli_version from the transcript) into a ledger; ingest keeps the
> earliest valid stamp and sets harness_mixed on any later difference
> or a second CLI version; six nullable columns, schema 10, store
> recreated on the owner's word; A4b adds GET /api/dashboard/harness
> with the developer_aggregates rules plus avg_interaction_quality,
> rework and correction rates with coverage (NULL without labels), a
> mixed and an unstamped row; one closed `harness=<dim>:<value>|mixed|
> unstamped` filter with facets; a Dashboard panel; the header stamp.

Each clause against the plan: capture at SessionStart — D1, FR-1;
earliest + mixed — D4, FR-3, FR-4; full sha and instructions_digest —
D2, FR-1; plugin exclusion — D2b, FR-1; judge score + coverage, NULL —
D5, FR-5; closed filter — D6, FR-6; columns/recreation — D3, FR-4;
split — tasks.md PR column.

Differences from the origin: judge scores are the packaged rubric's
interaction quality and two rates; a session-level success score waits
for A5 (Out of scope). Plugin-only sessions are unstamped (D2b), by the
owner's choice of the smaller honest option.

Verdict: aligned
Confidence: high

High: every decision now carries the owner's explicit ruling.
