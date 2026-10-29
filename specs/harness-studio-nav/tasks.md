# Tasks: Harness Studio — branding and grouped navigation

<!-- Three phases, one commit each. Every phase must leave the Studio
     building: NavTabs and layout.tsx change together in phase 2 because
     the prop shape changes. -->

## US1: the console is called Harness Studio (phase 1, FR-1)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 1 | New module: `PRODUCT_NAME = "Harness Studio"`, the `NavItem` and `NavGroup` interfaces, and the `under()` path helper. Leave `NAV_GROUPS`, `SETTINGS_ITEM` and `activeNav` for phase 2 (FR-1) | `studio/lib/nav.ts` | [ ] |
| 2 | Import `PRODUCT_NAME` from `@/lib/nav`; use it for `metadata.title` and the header wordmark; drop the `Session Analytics Studio` literal (FR-1) | `studio/app/layout.tsx` | [ ] |
| 3 | Product name in the readme (FR-1) | `studio/README.md` | [ ] |

**Checkpoint US1**:
- [ ] `node studio/scripts/nav-check.mjs FR-1` exits 0
- [ ] `node studio/scripts/states-check.mjs` exits 0
- [ ] commit: `feat(studio): name the console Harness Studio`

## US2: three groups over the same twelve routes (phase 2, FR-2..FR-4)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 4 | `NAV_GROUPS` with the three groups, ids, labels and ordered items exactly per FR-2; `SETTINGS_ITEM` separate; `activeNav(pathname)` returning `{ group, item }`, **null group for `/settings`**, null overall for an unowned path (FR-2, FR-3) | `studio/lib/nav.ts` | [ ] |
| 5 | Render two rows from the groups: headers with `aria-expanded`, then the open group's items with `aria-current="page"` on the active item only. Settings in the first row, pushed right. Keep `overflow-x-auto whitespace-nowrap` on both rows. Fall back to the first group when `activeNav` reports a null group, so the second row never renders empty (FR-4) | `studio/components/NavTabs.tsx` | [ ] |
| 6 | Drop the local `TABS` array; pass `NAV_GROUPS` and `SETTINGS_ITEM` to `NavTabs`. Carry across whatever of the `#307` comment is still true. Remove the flat `NavTab`/`activeTab` exports only if `git grep` shows no remaining caller (FR-2) | `studio/app/layout.tsx`, `studio/components/NavTabs.tsx` | [ ] |

**Checkpoint US2**:
- [ ] `node studio/scripts/nav-check.mjs FR-2`, `FR-3` and `FR-4` each exit 0
- [ ] `node studio/scripts/states-check.mjs` exits 0
- [ ] commit: `feat(studio): group the navigation by the AI SDLC`

## US3: the gate and the docs follow the new labels (phase 3, FR-5, FR-6)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 7 | Update the nav loop's route-and-label pairs to `/:Overview`, `/sessions:Sessions`, `/graph:Graph`, `/team:Team`, `/learn:Guides`, `/settings:Settings`, `/routing:Routing`, `/analysis:Analysis pipeline`; retire `/:Dashboard` and `/routing:Benchmark`. Do not weaken the single-marker assertion (FR-5) | `tests/release/ui_checks.sh` | [ ] |
| 8 | Rename the two renamed tabs where the docs name them — Dashboard → Overview, Analysis → Analysis pipeline. Work from `git grep -n -E '(Dashboard\|Analysis) tab'`. Do not rewrite surrounding prose (FR-6) | `docs/install.md`, `docs/peer-review.md`, `docs/session-analytics-cookbook.md` | [ ] |
| 9 | Confirm no tracked file outside `specs/` and `doc_internal/` still carries `Session Analytics Studio` (FR-6) | — | [ ] |

**Checkpoint US3**:
- [ ] `node studio/scripts/nav-check.mjs FR-5` and `FR-6` each exit 0
- [ ] every FR from FR-1 to FR-6 exits 0
- [ ] commit: `test(release): assert the grouped navigation labels`
