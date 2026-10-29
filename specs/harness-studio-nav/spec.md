---
feature_id: harness-studio-nav
spec_mode: lightweight
status: approved
date: 2026-10-28
origin:
  transcripts:
    - specs/harness-studio-nav/origin/2026-10-28-harness-studio-direction.md
  origin_claim: |
    The Studio's eleven flat tabs read as a pile of unrelated panels,
    several of them near-empty. The owner rejected three proposals that
    improved the nav by hiding features and named the real spine
    instead: the console is a harness console, not a session-analytics
    console. Rename it "Harness Studio" and group every existing
    surface under three groups that follow the AI SDLC — see the system,
    the moving pieces, what it knows. This spec is increment 1 of three:
    branding, grouping and the route map. The per-feature Learn/Settings
    link registry is increment 2 and explicitly out of scope here
    (owner, 2026-10-28).
---

# Spec: Harness Studio — branding and grouped navigation (increment 1)

## Problem

`studio/app/layout.tsx` declares eleven flat tabs — Dashboard, Sessions,
Search, Team, Runs, Ask, Graph, Analysis, Benchmark, Learn, Settings —
plus `/routing`, which no tab links to and which lights up the Benchmark
tab through `also: ["/routing"]`, marking a tab the reader is not on.
The eleven are a flat list of unrelated things, so nothing tells a
reader which surfaces are the system's dashboard, which are the
machinery that builds, and which are reference material. Two labels also
disagree with their own pages: the nav says "Analysis" over a page whose
`<h1>` reads "Analysis pipeline".

Underneath that is a naming problem. The console is called "Session
Analytics Studio", but session analytics is 1 of the 19 features in the
harness catalog and "Studio web UI" is another. Naming the console after
one of its features is why Runs, Benchmark and Routing read as foreign
bodies in it, and why three independent reviewers proposed hiding them.

## User scenarios

- US1: As the owner, I open the console and see three groups that match
  how I think about the harness — what the system is doing, what is
  building software, and what it knows — instead of eleven flat tabs in
  no order.
- US2: As someone with a bookmark or a screenshot from v2.0.0, every URL
  I had still works and still lands on the same page, under its new
  label.
- US3: As a keyboard or screen-reader user, exactly one element in the
  navigation is marked as the current page, and it is the page I am on
  — not the group that contains it.

## Requirements

- FR-1: `studio/lib/nav.ts` exports `PRODUCT_NAME` equal to `Harness Studio`, and `studio/app/layout.tsx` imports `PRODUCT_NAME` from `@/lib/nav` and uses it for both the document title metadata and the header wordmark, so the product name has one source rather than a literal per site. Neither `studio/app/layout.tsx` nor `studio/README.md` contains the string `Session Analytics Studio`, and `studio/README.md` names `Harness Studio`.
- FR-2: `studio/lib/nav.ts` exports `NAV_GROUPS`, an array of exactly three groups in the order `mission-control` / `Mission Control`, `development` / `Development`, `library` / `Library`. Mission Control holds, in order, `/` as `Overview` (with `also` equal to `["/labels"]`), `/sessions` as `Sessions`, `/search` as `Search`, `/ask` as `Ask`, `/graph` as `Graph`. Development holds, in order, `/runs` as `Runs`, `/team` as `Team`, `/routing` as `Routing`, `/benchmark` as `Benchmark`, `/analysis` as `Analysis pipeline`. Library holds `/learn` as `Guides`. `SETTINGS_ITEM` is exported separately with href `/settings` and appears in no group.
- FR-3: The set of hrefs across `NAV_GROUPS` and `SETTINGS_ITEM` is exactly the twelve routes the navigation could reach before the regroup — `/`, `/sessions`, `/search`, `/ask`, `/graph`, `/runs`, `/team`, `/routing`, `/benchmark`, `/analysis`, `/learn`, `/settings` — with no route added, removed or redirected. `studio/lib/nav.ts` exports `activeNav(pathname)`, which returns the owning group and item for each of those twelve routes, returns the `/sessions` item for `/sessions/<id>`, returns the `/` item for `/labels/<label>`, and returns null for a path no item owns.
- FR-4: For every one of those paths, rendering the navigation produces exactly one element carrying `aria-current="page"`, and that element is the item, never the group header; exactly one group is open, marked with `aria-expanded="true"`. Because Settings belongs to no group, `activeNav` returns a null group for `/settings` and the renderer keeps the first group open, so the second row is never empty and the single marked element is Settings itself.
- FR-5: The release navigation gate in `tests/release/ui_checks.sh` asserts the new labels — the route-and-label pairs `/:Overview`, `/sessions:Sessions`, `/graph:Graph`, `/team:Team`, `/learn:Guides`, `/settings:Settings`, `/routing:Routing` and `/analysis:Analysis pipeline` — no longer asserts the retired pairs `/:Dashboard` or `/routing:Benchmark`, and still reads the marked element through a `[aria-current=page]` query so the single-marker promise keeps being measured rather than removed.
- FR-6: No tracked file outside `specs/` and `doc_internal/` contains the string `Session Analytics Studio`, and the documentation that names the two renamed tabs refers to them by their new labels.

## Out of scope

Named explicitly because the external review found the cost of the
decided direction understated, and because an autonomous run must not
widen its own scope:

- **The per-feature Learn/Settings link registry** — the owner's Alerts
  complaint made structural. It needs stable `id`s on the Settings
  `<fieldset>` groups, a `settings_links` counterpart to the existing
  `finding_links`, a link pair on every card and empty state, and tests
  for each. That is increment 2 and it is the larger half of the work.
- **Skills, Agents and Wiki as Library items**, and the Guides umbrella
  filtered to `kind === "doc"`. Blocked on the mapping question in the
  origin file §5.
- **Catalog-only exposure** of harness features with no Studio surface.
  Increment 3.
- **Renaming the repository, the `cct` CLI or the package.** The rename
  reaches the Studio only.
- **Any change to Settings itself**, to page content, or to the API.

## Constraints

- **Every URL is preserved.** No route is added, removed or redirected.
  This is what makes the change safe to ship after v2.0.0's screenshots
  and bookmarks exist.
- **No new dependency.** The contract check uses the `tsc` and
  `react-dom/server` already installed under `studio/`.
- **The owner's running instance is untouched.** The API on port 8765
  and the Studio on port 3000 belong to the owner. Nothing in this
  feature starts, stops, rebuilds or reads from a server, and the
  contract check needs none.
- **The tree builds after every phase.** `NavTabs` changes its prop
  shape, so it and `layout.tsx` move in one commit rather than two.
- **Node 20 or newer** is required to run either check; the machine's
  default `node` is 16, which fails on `import.meta.dirname` and on
  `readdirSync({recursive:true})`. `nav-check.mjs` refuses with a named
  error rather than a confusing one.
- **This branch must not be merged before the `v2.0.0` tag exists.**
  The release verification document and its screenshots name the old
  tab labels. The run opens a pull request and never merges.
- **No close keywords** in any commit message or pull-request body.

## Non-functional

- No new dependency. `tsc` and `react-dom/server` are already present
  and are what the contract check uses.
- Both navigation rows keep `overflow-x-auto whitespace-nowrap`, so the
  nav scrolls inside itself and the page never scrolls horizontally
  (WCAG 2.2 SC 1.4.10).
