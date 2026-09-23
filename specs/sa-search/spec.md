---
feature_id: sa-search
spec_mode: lightweight
status: approved
date: 2026-09-22
issue: "#371 (slice A2; separate PR; leaves #371 open)"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-search/origin/2026-09-22-owner-direction.md
  user_messages:
    - "2026-09-22: 'I would rather work on extending capabilities of Session Analysis rather using ML Flow'"
    - "2026-09-22: 'Can you start planing the addressing the features listed in issues/371?'"
---

# Spec: search worth the name (A2)

## Why

The sessions page has one text box (a substring over project path or
model) and a copilot dropdown. The query layer can already filter by
date range and tag, and the store holds developer, model, cost and tool
facts, but none of that is reachable from the Studio. The full-text
search over archived traces (E10) exists as an API route with no page,
so nobody can use it. This is MLflow's "search traces" gap (A2 in
`doc_internal/plans/session-analytics-mlflow-gaps-2026-09-22.md`).

## Verified facts (2026-09-22 local, master 3dfe5a1)

| Fact | Where |
|---|---|
| `GET /api/sessions` accepts `query`, `copilot`, `limit`, `include_noise`, `sort`, `order` | `api/server.py` |
| `search_sessions` also takes `date_from`, `date_to`, `tag`; the route does not pass them | `mcp/tools.py:163-185` |
| `tag` filters in SQL over `session_flag` (favourite, todo) and the derived "analyzed" tag, via an allowlist | `mcp/tools.py:81-96` |
| `copilot_session` has `developer_id`, `model`, `agent_profile`, `phase`, `started_at`, `duration_seconds`, `turn_count`, `tool_call_count`, `error_count`; cost is a query-time rollup `SUM(copilot_turn.cost_usd)` aliased `cost_usd` | `001_core.sql`; `mcp/tools.py:26-32` |
| Tool names per session live in `copilot_tool_call.tool_name`, joined through `copilot_turn` | `001_core.sql` |
| `GET /api/search?q=&limit=` returns ranked hits (`session_ref`, `session_id`, `sequence_num`, `snippet`, `project_path`, `copilot`, `redaction_mode`) from the trace archive; FTS5 or `tsvector`, falling back to `LIKE` | `api/server.py`; `archive.py:418` |
| No Studio page or client function consumes `/api/search`; the Studio nav has no search entry | `studio/lib/api.ts`, `studio/app/layout.tsx`, `studio/app/` |
| Session-page turns are addressable as `/sessions/{id}#turn-{sequence_num}` (A1 kept this) | `studio/app/sessions/[id]/page.tsx` |
| Judge labels are per turn: `heuristic_label` (UNIQUE per turn and `rubric_name`) carries nine rubric booleans (`user_corrects_agent`, `user_asks_question`, `user_gives_command`, `agent_asks_clarification`, `user_changes_approach`, `agent_changes_approach`, `has_misunderstanding`, `response_helpful`, `rework_detected`; the table also has a retired `phase_violation` column that the rubric no longer produces); the packaged rubric is named `heuristic-v1`, read from `load_rubric().name`, which is NOT the configuration key `default` | `002_analytics.sql`; `config_data/heuristic-rubric.json`; `judge/rubric.py:28` |
| `count_noise_sessions` (the "Show excluded (n)" count) takes the same `query`, `copilot`, `date_from`, `date_to` as the list, so the count describes the filtered list only while both take the same filters | `mcp/tools.py:215-222` |
| `archive.search_traces` accepts a `noise` config and keeps probe sessions out before ranking; the route does not pass one, and nothing reports how many sessions or turns are archived | `archive.py:418-442`; `api/server.py` |
| The #307 nav cut (10 → 8 entries) removed the fake Agents page and folded Routing and Clusters; the Ask page interprets the store through an LLM | issue #307 (2D); `studio/app/ask` |
| API tests use FastAPI's TestClient over an ingested fixture store (43 tests) | `tests/test_api.py` |

## Requirements

- **FR-1** `GET /api/sessions` exposes the filters the query layer has:
  `date_from`, `date_to`, `tag`; and gains `developer`, `model` (exact,
  case-insensitive), `tool` (a session that made at least one call to
  that tool), `min_cost`, `max_cost` (against the priced cost rollup),
  and `label` (one of the rubric's boolean names: a session where the
  packaged rubric, `heuristic-v1` (its own name, from `load_rubric()`), marked it true on at least one turn, by
  `EXISTS`). Filters combine with AND. An unknown `tag` or `label` is a
  400, as the tag allowlist already makes it in the query layer.
- **FR-1a** `date_to` is inclusive of the whole day named: a value
  `YYYY-MM-DD` is applied as `started_at < the next day`, so a session
  started at any time on `2026-09-22` matches `date_to=2026-09-22`.
- **FR-1b** The cost filters read the **priced** subtotal, the sum of
  turns that carry a `cost_usd`; a session with no priced turns has an
  unknown cost, is excluded by `min_cost`/`max_cost` rather than
  treated as zero, and the list and the page call the figure "priced
  cost", never "cost".
- **FR-2** `search_sessions` implements the new filters in SQL, one
  query as today; `count_noise_sessions` takes every filter the list
  takes, so "Show excluded (n)" describes the filtered list; the MCP
  tool gains the same parameters.
- **FR-3** The sessions page offers each filter as a control: date
  range, developer, model, tool, cost range, tag; the existing text
  box and copilot dropdown stay. The list updates as filters change;
  the URL carries them, so a filtered list can be linked and reloaded.
- **FR-4** `GET /api/sessions` also returns the distinct values a filter
  can take (developers, models, tools present in the store), so the
  controls are dropdowns over real values, not free text; one query
  each. Facets are drawn from the same population as the list (the
  noise policy applied, unless `include_noise`) and omit blank values.
- **FR-5** A Studio page, `/search`, over `GET /api/search`: a query
  box, the ranked hits with their snippet, session, project and turn,
  each linking to `/sessions/{id}#turn-{n}`; a nav entry. The route
  applies the normal noise policy and returns archive coverage
  alongside the hits: archived sessions and archived turns, and the
  sessions eligible for archive, so the page can say "no match" when
  there is something to search and "nothing archived yet" (pointing at
  the `trace_archive` setting) when there is not.
- **FR-5a** Search complements Ask and supersedes part of the #307 nav
  cut deliberately: Search returns direct, ranked, deterministic turn
  matches from the archive with no model call; Ask interprets the wider
  store through a model. The README and the page's empty state say
  which is which.
- **FR-6** Tests: API tests per filter over the fixture store (each
  filter narrows as expected, combinations AND, an unknown tag or label
  is 400); the `date_to` boundary day (a session at 23:59 on the named
  day matches, one at 00:00 the next day does not); a session with no
  priced turns excluded by a cost filter; the excluded count under each
  filter; the facets' population and no blanks; the search route's
  coverage figures and noise policy. `states-check` covers the search
  page's states (no query, hits, no hits with coverage, nothing
  archived) and the filter bar's states.

## Constraints

- No schema change, no new storage, no new dependency (the issue's
  constraint; the green-field ruling would allow one, none is needed).
- The label filter is the MVP the owner defined: the packaged rubric,
  boolean true on at least one turn. Named rubric runs, human labels,
  counts and session-level aggregation are out of scope.
- The existing `query` substring and its semantics stay; the new
  filters add to it.
- Nothing about ingest, redaction or the archive changes; the search
  page shows what the archive already holds, redacted at write.
- One PR under #371, no close marker.

## Out of scope

A3–A6. Label filters beyond the MVP (named rubric runs, human labels,
counts, aggregation). A filter grammar. Full-text search over anything
but the trace archive. Saved searches.
