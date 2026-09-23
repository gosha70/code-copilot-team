# Origin alignment check — sa-search

Checked 2026-09-22 21:24, before plan approval and before any implementation.

Origin: specs/sa-search/origin/2026-09-22-owner-direction.md (the owner's
messages) and issue #371, row A2.

Origin claim:
> Expose date range, tag, developer, cost, model, tool and label filters
> on the sessions list, from the API through the Studio; give the
> full-text search a page. No new storage.

Working claim:
> spec.md FR-1..FR-6 and plan.md: the sessions route passes the filters
> the query layer has and gains developer, model, tool and cost-range
> filters, all in the one existing query; facets come back with the
> list; the Studio gets a filter bar with URL state and a /search page
> linking hits to their turns; tests per filter and per state; no
> schema, storage or dependency.

Each clause against the plan: date range, tag, developer, cost, model,
tool filters — FR-1..FR-3; the search page — FR-5; no new storage —
constraints.

Differences from the origin, surfaced in the bundle:

1. **Label filters are deferred** (plan D5). The issue row names them;
   labels are per-turn facts and a session-level rule for them is a
   modelling decision A3/A5 are meant to make. Put to the owner.
2. Facets (FR-4) are an addition the issue did not ask for; they are
   what makes the controls usable and cost three small queries.

Verdict: aligned
Confidence: medium

Medium, not high: difference 1 narrows the issue row and the owner has
not ruled on it.

Checked by reading the sessions route and search_sessions, the tag
allowlist, the session table's columns and the cost rollup, the search
route and archive.search_traces' fields, the Studio's sessions page,
API client and nav, and the API test suite.
