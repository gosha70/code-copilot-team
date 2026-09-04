# Spec: E2-UI — minimal read-only clusters view + similar panel

Issue #293, slice 4 of E2 from tracker #65, and the slice that
COMPLETES E2. Slice 1 (#285, `8e9ee49`) created validated provenance
envelopes; slice 2 (#287, `a4a65f9`) populated `SIMILAR_TO` inside
compatibility-proven spaces; slice 3 (#289, `3f62898`) grouped that
snapshot into clusters. This slice shows them — and inherits the arc's
governing order in the form it takes for a surface:

> **The UI renders; it never re-derives.** Every semantic decision —
> what a cluster is, how clusters order, what "unclustered" means, what
> may and may not be claimed about members — was settled in #287 and
> #289 and is already enforced there. A page that recomputes any of it
> forks the contract silently. Nothing below adds a rule; it decides
> how existing rules reach a screen without being weakened.

## User Scenarios

1. **"What themes are in my session library?"** An operator opens the
   clusters view after `embed` + `similar` + `clusters` and sees the
   groups largest first, each with its members and the count of stored
   directed edges behind it — in exactly the reader's order.
2. **"What is this session like?"** On an existing session's detail
   page, a panel lists that session's stored neighbours with their
   scores, labelled `basis: "embedding"`, or says honestly that the
   session is unclustered / has no neighbours.
3. **A pipeline that has not been run yet.** The graph database is
   absent, or exists but was never built. The operator sees WHICH
   prerequisite is missing and the command that satisfies it — not a
   blank panel and not a spinner that never resolves.
4. **A healthy library with nothing to show.** Everything ran; the
   stored snapshot simply holds no edges. The view says zero clusters
   as a RESULT, visibly distinct from scenario 3.

## Requirements

### FR-A — the render contract, stated first

The UI is a projection of `run_clusters` and `similar_sessions`. It
MUST NOT re-sort, re-rank, re-filter, or recompute membership.

- **Ordering is the reader's contract** (#289 FR-C): clusters
  descending by size, then ascending by identity; members ascending by
  `session_key`. The page renders that sequence as received. Any
  client-side sort — including a "helpful" default on a table
  component — forks the ordering rule and is refused.
- Identity, `directed_edge_count`, and the unclustered count are
  displayed verbatim. The UI derives no new number from them; in
  particular it does not sum, average, or re-count edges.

### FR-B — the API surface (this slice's backend half)

The routes live in the **Python FastAPI service**, not in Next.js:
`scripts/session_analytics/api/server.py` carries 26 route decorators
(22 GET, 3 POST, 1 PUT), which the Studio consumes through
`studio/lib/api.ts`. There is no `studio/app/api` directory at all.

**None of those routes expose similarity or clustering.** Counted with:

```
grep -cE '^\s*@app\.(get|post|put|delete)\(' \
  scripts/session_analytics/api/server.py            # 26
grep -cE '@app\.(get|post).*(similar|cluster)' \
  scripts/session_analytics/api/server.py            # 0
```

Two read-only endpoints are therefore part of this slice, not a
prerequisite someone else supplies:

- `GET /api/clusters` — wraps `run_clusters` and returns the reader's
  report unchanged: clusters, `cluster_count`, `clustered_sessions`,
  `unclustered_sessions`, `graph_sessions`, `basis`, both provenance
  labels, and the limitations block.
- `GET /api/sessions/{session_id}/similar` — wraps the existing
  `tools.similar_sessions`.

Both MUST reuse the #289 discipline rather than restate it: the graph
is opened `connect_read_only`, an absent path is refused BEFORE any
open with zero filesystem creation, a disappearing path is refused and
never repaired, and the prerequisite ladder answers with the SAME
shapes the MCP tools already use. Neither endpoint computes anything,
writes anything, or contacts a backend.

### FR-C — empty, absent, and not-computed are three states

Blank is not an answer. The UI must distinguish, visibly and in words:

- **Absent / unbuilt prerequisite** — the graph database is missing or
  holds no `Session` table. Show which one, and the command that fixes
  it (`graph`, then `similar`). This is the CLI's exit-2 ladder made
  visible.
- **Healthy empty** — every prerequisite held and the snapshot yielded
  no clusters. This is a RESULT (the CLI's exit 0), and must read as
  one, never as a failure.
- **Not yet computed for this session** — the session is in the graph
  with no incident stored edge ("unclustered"), or is absent from the
  graph entirely (a graph prerequisite, per #289 FR-F). These are
  different sentences, because they have different remedies.

Collapsing any of these into a shared empty state is the defect this
requirement exists to prevent.

### FR-D — a bounded result says so

If a response is capped, the view states the cap in the UI: showing
N of M. `cluster_count` is the honest total and is already returned
alongside a possibly-shorter list (#289 FR-F), so the information
exists and only has to be shown. A page that renders a truncated list
without saying it is truncated misrepresents the library, in the same
way an unlabelled stale figure does.

### FR-E — inherited honesty survives the trip to the screen

Every claim limit the CLI and MCP surfaces carry must appear on the
surface a human actually reads:

- A cluster is a **transitive discovery grouping** — members are
  connected through a chain of recorded edges, which does NOT assert
  that every pair is similar. No UI affordance may imply all-pairs
  similarity.
- Clusters are **UNNAMED**: no space triple, no per-space grouping.
- Membership reflects the edges the producer created under its
  compatibility rule **at production time**; it does not assert that
  members currently share an embedding envelope.
- Membership and the unclustered count have **different provenances**
  (stored edges vs the current node inventory) and are labelled
  distinctly.
- Neighbour scores are a snapshot; nothing refreshes implicitly.

The `limitations` block already travels in the payload. The
requirement is that it is DISPLAYED, not merely carried.

### FR-F — Studio conventions; the harness is out of scope, by decision

The visual-review harness (`DESIGN.md`, DTCG tokens,
`npm run copilot:review`, the axe-core gate, the visual-reviewer
critic) is a template at `shared/templates/ui-harness/` for **newly
scaffolded** UI projects. The Studio predates it and does not adopt
it: `studio/package.json` exposes only `dev`/`build`/`start`/`lint`,
there is no `DESIGN.md` or token file under `studio/`, and the root
package exposes only `typecheck`.

This slice therefore follows the Studio's existing conventions — the
`studio/lib/api.ts` fetch helper and the established page layout — and
states its verification in terms this repo already runs. Retrofitting
the harness onto the Studio is a legitimate piece of work and its own
issue; doing it here would ride a design-system migration along with
two small pages. **Recorded as a decision so it is not read as an
oversight.**

Because the automated visual gate does not apply, the eight states are
ENUMERATED in tasks.md and ASSERTED by a minimal states script (plan
D8) that renders each and checks the DOM. "No gate exists" is a reason
to build the smallest thing that can fail on its own, not a licence to
check by eye — hand checking cannot fail visibly and depends on
diligence at one moment. That list is part of the acceptance criteria,
not an informal pass.

## Non-goals

- Filtering, drill-down, search, or graph visualisation of clusters —
  an explorer designed before anyone has looked at a cluster list is
  designed against imagined usage. This slice produces the evidence
  that would justify one.
- Server-side pagination or cluster-stability tracking across passes
  (#289 FR-D records the materialisation upgrade path if ever needed).
- Per-cluster KPI aggregates.
- Retrofitting `ui-harness` / DESIGN.md / DTCG tokens onto the Studio.
- Triggering `embed`/`similar`/`clusters` from the UI: this slice
  reads; it does not run pipelines.
- Anything touching embeddings — no backend calls, no live text-query
  embedding.

## Constraints

- **No new dependency** (the Studio's existing React/Next stack only;
  no chart or table library) and **no schema change**.
- **Read-only everywhere** — no endpoint or page may open the graph
  create-capable or write to any store.
- **No new config keys** beyond what `serve` already resolves.
- Determinism: the same `(edges, inventory)` pair yields the same
  rendered order, because the order is the reader's.
- Suites green under both pythons; `typecheck` and `lint` clean for the
  Studio; mutation-ledger evidence at closure per the arc's discipline,
  using the driver committed in PR #292.
