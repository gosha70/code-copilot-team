# Origin alignment check — sa-search

Checked 2026-09-22 21:45, before implementation. Supersedes the 21:24 record: the
owner's plan review rejected the deferral of label filters and defined
the MVP instead, and fixed four contract points; all are in the bundle.

Origin: specs/sa-search/origin/2026-09-22-owner-direction.md (the owner's
messages and their plan review) and issue #371, row A2.

Origin claim:
> Expose date range, tag, developer, cost, model, tool and label filters
> on the sessions list, from the API through the Studio; give the
> full-text search a page. No new storage. Labels: the packaged rubric
> marked the boolean true on at least one turn, by EXISTS. date_to
> inclusive; the excluded count filtered the same way; archive coverage
> and the noise policy on search; Search supersedes part of the #307 nav
> cut and complements Ask.

Working claim:
> spec.md FR-1..FR-6 and plan.md D1–D7: every filter the issue names,
> including the label MVP as the owner defined it, in the one existing
> query, with count_noise_sessions taking the same filters; facets over
> the list's population with blanks omitted; priced cost, unknown never
> zero; date_to inclusive with the boundary tested; /api/search under
> the noise policy with archive coverage; a /search page linking hits to
> turns; the Search-versus-Ask note recorded; no schema, storage or
> dependency.

Differences from the origin: none. Facets (FR-4) are an addition the
owner accepted with conditions that are in FR-4.

Verdict: aligned
Confidence: high

Checked by reading count_noise_sessions' signature, archive.search_traces'
noise parameter, the heuristic_label columns and the packaged rubric's
name, issue #307's nav-cut item, and the earlier record's sources.

Re-checked after the owner's build review returned two findings, both
verified and fixed: (1) the label filter compared rubric_name with the
configuration key "default" while the packaged rubric's rows are stored
under its own name, heuristic-v1, so it matched nothing real, and the
test had repeated the same wrong value; the filter now reads
load_rubric().name, the test asserts that name and inserts under it, and
the reviewer's reproduction (a real row, through the API) returns the
session. The bundle's "default" and "ten booleans" are corrected to
heuristic-v1 and nine. (2) The public MCP search_sessions wrapper only
forwarded query, copilot and dates; it now carries and forwards every
filter, with a contract test over the registered schema and a call
through the built server. Verdict and confidence unchanged.
