---
spec_mode: full
feature_id: session-analytics-similarity-ui
risk_category: integration
justification: |
  Completes E2 by surfacing the merged #285/#287/#289 substrate: two
  read-only FastAPI endpoints wrapping existing logic, and two minimal
  Studio views that render the reader's output without re-deriving any
  of it. No schema change, no new dependencies, no new config keys, no
  write path anywhere. The load-bearing design work — what a cluster
  is, how clusters order, what may be claimed about members — is
  already settled in #287/#289; this slice decides only how those
  rules reach a screen intact.
status: draft
date: 2026-09-04
issue: 293
origin:
  issue: gosha70/code-copilot-team#293
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/293
    - https://github.com/gosha70/code-copilot-team/issues/65
  origin_claim: |
    Issue #293 (E2-UI, slice 4 of E2 from tracker #65, completing E2
    over the merged #285/#287/#289): MINIMAL READ-ONLY only — a
    clusters view listing groups largest-first with members and
    directed_edge_count, and a similar-sessions panel on the existing
    session detail page. Explicitly not an explorer: no filtering,
    drill-down, or graph visualisation, because nobody has looked at a
    cluster list yet and an explorer would be designed against
    imagined usage. The owner set three constraints the plan must
    carry: the UI must not re-sort or re-rank; a bounded limit is
    surfaced as N of M, not hidden; and empty / absent / not-computed
    are distinct explicit states. The plan must also state explicitly
    whether the ui-harness applies, as a decision rather than an
    omission.
---

# Plan: E2-UI — clusters view + similar panel

## Shape

Four small pieces, layered like the rest of the arc (existing logic →
API → page), all read-only:

- `api/server.py` — `GET /api/clusters`, wrapping `run_clusters` over
  a `KuzuGraphSnapshot` on a `connect_read_only` handle. Returns the
  reader's `as_dict()` unchanged.
- `api/server.py` — `GET /api/sessions/{session_id}/similar`, wrapping
  the existing `tools.similar_sessions`.
- `studio/app/clusters/page.tsx` — the clusters view.
- A similar-sessions panel on the existing session detail page.

**The API half is not optional and not someone else's.** The routes
are FastAPI in the Python service — `api/server.py` has 26 route
decorators (22 GET, 3 POST, 1 PUT), consumed by the Studio via
`studio/lib/api.ts`; there is no `studio/app/api` directory. A grep
for `similar|cluster` across those decorators returns **0**. Verified
before planning, with the commands recorded in spec FR-B.

## Design decisions (flagged for review)

- **D1 endpoints wrap, they do not reimplement.** `/api/clusters`
  calls `run_clusters`; `/api/sessions/{id}/similar` calls
  `tools.similar_sessions`. Neither re-derives grouping, ordering, or
  the prerequisite ladder. A second implementation of any of those is
  the defect this decision exists to prevent.
- **D2 the payload is passed through verbatim.** The endpoint does not
  reshape, rename, or prune the reader's report — the `limitations`
  block, both provenance labels and `basis` travel to the client
  intact, because FR-E requires them displayed and a reshaping layer
  is where they would quietly get dropped.
- **D3 no client-side sort.** The page maps over the array as
  received. Where a component would default to sorting, sorting is
  explicitly disabled rather than configured to match — matching
  duplicates the rule, and duplicated rules drift.
- **D4 three states, three components.** Prerequisite-missing,
  healthy-empty, and populated are distinct render branches with
  distinct copy, not one empty state parameterised by a message.
  Collapsing them is exactly the failure FR-C names.
- **D5 read-only everywhere.** Every graph open in this slice is
  `connect_read_only`; the absent-path check runs before any open; the
  disappearing-path race is refused, never repaired. Inherited from
  #289 T2/T3 rather than restated.
- **D6 the ui-harness does not apply**, and the spec says why in full:
  it is a template for newly scaffolded UI projects, and the Studio
  predates it with no `DESIGN.md`, no tokens and no `copilot:review`.
  Consequence for this plan: no automated visual gate exists, so the
  eight states are enumerated below AND asserted by the D8 script —
  "no gate exists" is a reason to build the smallest thing that can
  fail, not a licence to check by eye.
- **D7 no new dependency.** No table or chart library. The clusters
  view is a list; the panel is a list.
- **D8 the eight states are ASSERTED, not eyeballed.** D6 establishes
  that no automated visual gate applies; it does not follow that hand
  checking is the only option, and hand checking has the failure mode
  this arc keeps finding — it cannot fail visibly, and it depends on
  diligence at one moment. A minimal states script is therefore IN
  SCOPE: it renders each of the eight states and asserts on the DOM
  (the state's distinguishing copy is present, and for the capped case
  that "N of M" appears). Precedent: the Calibration panel, where
  replacing screenshots with DOM assertions immediately exposed that
  only one of five states had actually been checked at the narrow
  width. Not a visual-regression harness, not a screenshot differ —
  the smallest thing that can fail on its own.

## Test strategy

- **API (python, `tests/test_api.py` conventions):** both endpoints
  return the wrapped payload unchanged for a populated snapshot;
  the prerequisite ladder maps to the same shapes #289 pins (absent
  path, unbuilt store, disappearing-path race) with **zero filesystem
  creation asserted**; healthy-empty returns a 200 with zero clusters
  rather than an error; the response passes the reader's `limitations`
  and both provenance labels through verbatim; a fake snapshot proves
  the endpoint re-derives nothing.
- **Ordering discriminator:** the endpoint's cluster order is
  byte-identical to `run_clusters`' order for a fixture whose
  size-descending and identity-ascending orders differ — the test that
  fails if anything sorts on either side.
- **Studio (`typecheck` + `lint`):** the page compiles and lints under
  the Studio's existing pipeline.
- **The eight states, asserted by the D8 script** (DOM assertions on
  each state's distinguishing copy), not eyeballed — enumerated here
  and recorded in the closure commit:
  1. populated clusters view, order matching the API response exactly;
  2. healthy-empty ("no clusters" as a result);
  3. graph absent (names the prerequisite and the `graph` command);
  4. graph unbuilt (distinct copy from 3);
  5. capped list showing "N of M";
  6. session detail with neighbours;
  7. session detail, session unclustered;
  8. session detail, session absent from the graph (graph
     prerequisite, distinct from 7).
- **Closure:** consolidated mutation ledger via the committed driver
  (`scripts/mutation_ledger/`, PR #292), suites under both pythons,
  gates, origin record refreshed last.

## Not planned

Filtering, drill-down, search, graph visualisation; server-side
pagination; cluster-stability tracking; per-cluster KPI aggregates;
retrofitting `ui-harness` onto the Studio; triggering pipelines from
the UI; any write path; any new dependency or config key. See spec
§Non-goals.
