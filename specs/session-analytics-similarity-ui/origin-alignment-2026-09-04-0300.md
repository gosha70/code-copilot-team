# Origin alignment — session-analytics-similarity-ui (E2 slice 4)

Verdict: aligned
Confidence: high

## Origin capture

Issue #293, opened as slice 4 of tracker #65's E2 immediately after
slice 3 (#289, PR #290) merged at `3f62898` and was closed. The owner
instructed "we must finish the work on #65", then chose between two
framings of the UI slice and selected **(a) minimal read-only**, as
one slice, with the reasoning recorded: it completes E2 rather than
deferring it behind more surface; it matches the slice shape of
#285/#287/#289 so it fits the gated rhythm; it renders what already
exists; and decisively, **nobody has looked at a cluster list yet**,
so an explorer would be designed against imagined usage. Shipping (a)
produces the evidence that would justify (b) or show it is not wanted.

## The governing order, and where it binds

1. **The UI renders; it never re-derives.** Every semantic decision
   was settled in #287/#289 and is enforced there. spec.md FR-A binds
   this before any component is described: ordering is the reader's
   contract, and identity / `directed_edge_count` / the unclustered
   count are displayed verbatim.
2. **Three owner constraints, carried as requirements, not notes.**
   No re-sorting or re-ranking (FR-A, D3); a bounded limit surfaced as
   N of M rather than hidden (FR-D); empty / absent / not-computed as
   distinct explicit states (FR-C, D4). Each is written as a
   requirement with a named failure mode.
3. **Inherited honesty must survive to the screen** (FR-E). The
   `limitations` block already travels in the payload; the requirement
   is that it is DISPLAYED, not merely carried.

## Decisions taken on this plan's authority (flagged for review)

- **D1 endpoints wrap, never reimplement** — `/api/clusters` calls
  `run_clusters`; the similar endpoint calls `tools.similar_sessions`.
- **D2 payload passed through verbatim**, because a reshaping layer is
  where the limitations and provenance labels would quietly get lost.
- **D3 no client-side sort**, disabled rather than configured to
  match — matching duplicates the rule, and duplicated rules drift.
- **D4 three states, three render branches**, not one parameterised
  empty state.
- **D5 read-only everywhere**, inherited from #289 T2/T3.
- **D6 the `ui-harness` does NOT apply** — recorded as a decision, at
  the owner's explicit request that this be stated either way.
- **D7 no new dependency** — the view is a list, the panel is a list.

## A scope finding made BEFORE planning, not during the build

The routes are FastAPI in the Python service —
`scripts/session_analytics/api/server.py`, 26 route decorators (22
GET, 3 POST, 1 PUT), consumed by the Studio through
`studio/lib/api.ts`; there is no `studio/app/api` directory. **None
expose similarity or clustering** (grep returns 0). So "a UI slice"
necessarily includes two read-only endpoints. This is stated up front
in the issue, the spec (FR-B) and the plan rather than being
discovered at build time — the owner's
own framing was that an explorer would be "a backend slice wearing a
UI label", and the same honesty is owed to the minimal version.

## Why the harness decision is a decision

The visual-review harness lives at `shared/templates/ui-harness/` as a
template for newly scaffolded UI projects. Verified against this repo:
`studio/package.json` exposes only `dev`/`build`/`start`/`lint`; there
is no `DESIGN.md` or token file under `studio/`; the root package
exposes only `typecheck`. Retrofitting it is legitimate work and its
own issue; doing it inside this slice would ride a design-system
migration along with two small pages.

The consequence is carried, not waved away — and then taken one step
further at review. Because no automated visual gate applies, the
eight states are enumerated in tasks.md AND asserted by a states
script (D8) rather than checked by eye: hand checking cannot fail
visibly and depends on diligence at one moment, which is the failure
mode this arc keeps finding. The API endpoint tests must likewise be
reported as EXECUTED with the environment named, since they live in
the `fastapi`-gated suite and would otherwise skip silently.

## Findings that changed the work, recorded at closure

- **The API gap was real and was found before planning** (26 route
  decorators in `api/server.py`, none exposing similarity or
  clustering). The slice shipped two read-only endpoints.
- **`lint` was never a runnable gate.** The plan named
  `npm run lint`; there is no ESLint config, `next lint` prompts
  interactively, and no CI job invokes it. Configuring ESLint was
  refused as a repo-wide decision a feature slice should not make.
  `next build` replaces it. A new class of finding: not an instrument
  reporting a wrong number, but a gate that was never there — an
  acceptance criterion naming a command should be verified RUNNABLE
  when the plan is written.
- **A prerequisite discriminator was added** at review. The endpoint
  knows which of three states it is in at each raise site and was
  encoding that only into prose, forcing the client to re-derive it
  with a substring match. Annotating with what the endpoint
  authoritatively knows is not the reshaping D2 forbids.
- **T3 needed nothing upstream.** Checked before proposing: the
  producer already tailors `guidance` per case, and the FR-C
  distinction the panel needs is structural (200 with an empty list vs
  503 with a prerequisite). #289's tools stay byte-unchanged.
- **The panel sits on the Insights tab.** The origin claim specified
  the session detail page; which tab is a sub-choice recorded with its
  tradeoff in tasks.md.

## What this record does NOT claim

- The bundle was plan-only when first submitted; the branch now carries
  T1–T4. T4 closure closes nothing: #293 and #65 stay open, and
  acceptance is the owner's call.
- Nothing here makes #65 complete. E2 completes when this slice
  merges; E1 aggregates, E10's deferred half, E3 and E4 remain, and
  #65's completeness is the owner's call.
- Nothing here asserts the slice is accepted. The endpoints ARE built
  and their prerequisite-ladder fidelity is verified (a 14-mutation
  API ledger on a zero-skip baseline), but verification is not
  acceptance — that is the owner's call at merge.
