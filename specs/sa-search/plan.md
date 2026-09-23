---
spec_mode: lightweight
feature_id: sa-search
risk_category: ui
justification: |
  Query parameters over a query the store already runs, a filter bar,
  and a page over an existing route. No schema, no dependency, no new
  storage. FR-1..FR-6 in spec.md state the behaviour.
status: approved
date: 2026-09-22
issue: "#371"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-search/origin/2026-09-22-owner-direction.md
  user_messages:
    - "2026-09-22: 'I would rather work on extending capabilities of Session Analysis rather using ML Flow'"
    - "2026-09-22: 'Can you start planing the addressing the features listed in issues/371?'"
  origin_claim: |
    Slice A2 of #371: expose date range, tag, developer, cost, model and
    tool filters on the sessions list, from the API through the Studio,
    and give the existing full-text search a Studio page. No new
    storage. Label filters as the owner's MVP: the packaged rubric
    marked a boolean true on at least one turn. date_to inclusive, the
    excluded count filtered the same way, archive coverage and the
    noise policy on search, the Search-versus-Ask note recorded.
---

# Plan: search (A2)

## The shape of it

```
scripts/session_analytics/mcp/tools.py       search_sessions + count_noise_sessions: developer, model, tool,
                                              min_cost, max_cost, label; date_to inclusive;
                                              session_facets(db, noise): distinct developers, models, tools
scripts/session_analytics/api/server.py      GET /api/sessions passes every filter; returns facets alongside;
                                              GET /api/search applies noise, returns coverage
scripts/session_analytics/archive.py         archive_coverage(db, noise): archived sessions/turns, eligible sessions
studio/lib/api.ts                            sessions(filters) typed; search(q) client
studio/app/sessions/page.tsx                 the filter bar; filters in the URL query string
studio/components/SessionFilters.tsx         new: the bar, one control per filter, values from facets
studio/app/search/page.tsx                   new: the full-text search page
studio/lib/searchView.ts                     new: hit → link and label, the empty-state rule (for states-check)
studio/app/layout.tsx                        nav entry "Search"
studio/scripts/states-check.mjs              SessionFilters + searchView states
scripts/session_analytics/tests/test_api.py  filter, facet and search tests
scripts/session_analytics/README.md          one paragraph
```

## Decisions

**D1 — filters as query parameters, not a grammar.** MLflow's filter
string is a parser to maintain; typed parameters on the existing route
cover every filter in the issue and are what the Studio's controls
produce anyway. Combination is AND. Recommended.

**D2 — facets from the store, in the same response.** Dropdowns over
values that exist (developers, models, tools) beat free-text boxes that
can be spelled wrong. Three small `SELECT DISTINCT` queries per list
request over the same population as the list (noise policy applied
unless `include_noise`), blank values omitted; measured on the owner's
store during verification and reported. If they prove slow, they move to
their own route with a longer cache. Accepted by the owner with those
two conditions.

**D3 — cost filters against the priced subtotal.** `cost_usd` is
`SUM(copilot_turn.cost_usd)` over the turns that carry a price, so
`min_cost`/`max_cost` become a condition on that subquery expression.
A session with no priced turns has an unknown cost, not zero: it is
excluded by either bound, and the figure is labelled "priced cost"
wherever it appears. No stored column, no schema change. Accepted by the
owner with the naming condition.

**D4 — `tool` means "at least one call".** An `EXISTS` over
`copilot_tool_call ⋈ copilot_turn` by session. Counting or "only this
tool" are not asked for.

**D5 — the label filter MVP, as the owner defined it.** The first
draft deferred label filters because labels are per turn; the owner
rejected the deferral and fixed the rule: `label=<boolean name>` matches
a session where the packaged rubric (`rubric_name = load_rubric().name`,
`heuristic-v1`; not the configuration key `default`) marked
that boolean true on at least one turn, by `EXISTS` over
`heuristic_label ⋈ copilot_turn`. The allowed names are the rubric's nine
booleans; anything else is a 400. Named rubric runs, human labels,
counts and session-level aggregation stay out of scope.

**D7 — four contract points the owner's review fixed.** `date_to` is
inclusive of the day named (`< next day`), with the boundary day tested.
`count_noise_sessions` takes every filter the list takes, or "Show
excluded (n)" stops describing the list. `/api/search` applies the noise
policy and returns archive coverage, since hits alone cannot tell "no
match" from "nothing archived". And the Search page's place is recorded:
it supersedes part of the #307 nav cut on purpose and complements Ask
(deterministic ranked turn matches, no model; Ask interprets the wider
store through one).

**D6 — the search page links to turns.** A hit is a turn in a session,
and A1 kept `#turn-N` addressable, so every hit is one click from its
context. The page says plainly when the archive is empty for a project
that has not opted in, pointing at the `trace_archive` setting.

## Verification

- `unittest` (the smoke workflow's suite): per-filter tests over the
  fixture store (the tiny session has developer, model, tools and a
  cost), combinations, the 400 on an unknown tag or label, the `date_to`
  boundary day, a session with no priced turns under a cost filter, the
  excluded count under each filter, facets' population and no blanks,
  the search route's coverage and noise policy.
- `states-check`: the filter bar (facets present, empty facets, active
  filters) and the search page states (no query, hits, no hits, archive
  empty).
- `tsc --noEmit`, `next build`.
- A scratch store on other ports (the A1 method): every filter tried in
  the browser against the real 6,457-turn session and the fixture;
  facet query cost measured on the largest store; the search page tried
  with and without an archived project. The owner's instance is never
  restarted.
- `validate-spec.sh --all`, `check-origin-alignment.sh sa-search`,
  `check-doc-accuracy.sh`, `git diff --check`, then `/review-submit`.

## Risks

- **Prettier churn on `.tsx`**: diffs checked after every edit.
- **Facet cost on a large store**: three DISTINCT scans per list load;
  measured, with the fallback in D2.
- **The trace archive is opt-in per project**, so the search page is
  empty for most projects until they opt in. The page must say so
  rather than look broken.
