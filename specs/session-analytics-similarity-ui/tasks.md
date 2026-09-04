# Tasks: E2-UI — clusters view + similar panel

Gated like #285/#287/#289: each task returns for review before the
next starts; no merge, no closures without the owner's explicit GO.

## T1 — the two read-only endpoints

**Status: DONE** — `85c655f`, reviewed and approved.

**Implements:** FR-B (plan D1, D2, D5).

`api/server.py`: `GET /api/clusters` wrapping `run_clusters` over a
`KuzuGraphSnapshot` on `connect_read_only`; `GET
/api/sessions/{session_id}/similar` wrapping `tools.similar_sessions`.

**Done when:** both endpoints return the wrapped payload VERBATIM —
`limitations`, both provenance labels and `basis` present and
unmodified, asserted field-by-field; the ordering discriminator proves
the endpoint's cluster order is byte-identical to `run_clusters`' for a
fixture whose size-descending and identity-ascending orders differ;
the prerequisite ladder matches #289's shapes for absent path, unbuilt
store and the disappearing-path race, with ZERO filesystem creation
asserted; healthy-empty is a 200 with zero clusters, not an error; no
write statement anywhere in the slice; existing endpoints' responses
byte-unchanged.

**Proven to have RUN, not skipped.** These tests live with the
`fastapi`-gated suite (`tests/test_api.py`, 31 CI-gated tests): with
`fastapi` absent they skip silently, and "suites green under both
pythons" would then measure nothing here. The task is not done until
the run is reported with the executed count and the environment named
(`fastapi`/`httpx` present), the way #289's closure named kuzu 0.11.3
and mcp 1.29.1 for its zero-skip pass. A skipped API suite is the
T3 registration near-miss repeated.

## T2 — the clusters view

**Status: DONE** — reviewed and approved with T3.

**Implements:** FR-A, FR-C, FR-D (plan D3, D4, D7).

`studio/app/clusters/page.tsx` using the existing `studio/lib/api.ts`
helper and the established page layout.

**Done when:** the states script (D8) renders and asserts this view's
states on the DOM rather than by eye; the list renders in the API's
order with no client-side sort anywhere in the file (asserted by
inspection AND by the ordering discriminator above); identity,
members and `directed_edge_count` are displayed verbatim with no
derived number; the three states are three
distinct render branches with distinct copy — prerequisite-missing
(naming which, plus the command), healthy-empty (a result, not a
failure), populated; a capped response shows "N of M" using
`cluster_count`; the transitive-grouping and production-time
compatibility limitations are DISPLAYED, not merely fetched; no new
dependency added to `studio/package.json`; `typecheck` and
`next build` clean (see the lint correction below).

## T3 — the similar-sessions panel

**Status: DONE** — reviewed and approved with T2.

**Implements:** FR-A, FR-C, FR-E.

A panel on the existing session detail page.

**Done when:** neighbours render in the API's order with scores and
`basis: "embedding"`; an unclustered session and a session ABSENT from
the graph produce DIFFERENT copy (the second names the graph
prerequisite, per #289 FR-F); nothing in the panel implies pairwise
similarity; the snapshot note is shown; the existing session detail
page's other content is unchanged; `typecheck` and `next build` clean.

## T4 — closure

**Status: DONE** — this commit.

README section (the two views, the three states, and what the UI
deliberately does not do); consolidated mutation ledger via the
committed driver (`scripts/mutation_ledger/`) re-run whole at final
HEAD with zero skips; full suites under both pythons; Studio
`typecheck` + `next build`; the states asserted by the D8 script, its
output recorded, and the API suite reported as EXECUTED with its
environment named; `validate-spec` / origin-alignment (record last) /
doc-accuracy / `git diff --check`; PR body/table refresh.

## Correction: `lint` was never a runnable gate

The plan's acceptance criteria named `npm run lint`. **That command has
never been runnable in this repo**: there is no ESLint config under
`studio/`, so `next lint` drops into an interactive "How would you like
to configure ESLint?" prompt, and no CI workflow invokes it. The
criterion was unsatisfiable as written.

Configuring ESLint was refused: it is a new dependency and a repo-wide
decision, not something a UI feature slice should make on its way past.
`next build` replaces it — a gate that genuinely typechecks the whole
app and is what CI would exercise. Corrected here rather than
reinterpreted silently.

The generalization, recorded because it is a new class: an acceptance
criterion that names a command should be verified RUNNABLE when the
plan is written, not when it comes due. This is not an instrument
reporting a wrong number — it is a gate that was never there.

## Decision: the panel's placement within the session page

The origin claim specifies "a similar-sessions panel on the existing
session detail page", and that is where it is. Which TAB within that
page is a sub-choice the spec does not settle; it sits on **Insights**,
beside the other per-session analysis.

The tradeoff, stated rather than assumed: a user who never opens
Insights never sees neighbours. That is acceptable for a slice whose
purpose is to produce evidence about whether this surface is wanted at
all — the same reasoning that made this (a) rather than (b). If usage
shows it should be more prominent, moving it is trivial and informed.

## Out of scope

spec.md §Non-goals. #285/#287/#289 deliverables untouched. An
explorer, harness retrofit, pipeline triggers and KPI aggregates stay
with #65.
