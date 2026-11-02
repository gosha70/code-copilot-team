---
spec_mode: lightweight
feature_id: harness-studio-nav
risk_category: ui
justification: |
  A rename plus one level of navigation structure over routes that all
  already exist. No schema, no API, no new dependency, no route added or
  removed. The contract is asserted by a source-and-render check that
  needs neither a server nor a browser, so it can gate every phase.
  Deliberately scoped to increment 1 of three: the per-feature link
  registry that the owner's Alerts complaint really asks for is a
  separate, larger spec.
status: approved
date: 2026-10-28
origin:
  transcripts:
    - specs/harness-studio-nav/origin/2026-10-28-harness-studio-direction.md
  origin_claim: |
    Rename the console "Harness Studio" and group every existing surface
    under three AI-SDLC groups, preserving every URL. Increment 1 of
    three (owner, 2026-10-28).
---

# Plan: Harness Studio — branding and grouped navigation

## Deliverables

1. **`studio/lib/nav.ts`** (new) — the single source for the product
   name, the three groups and path resolution. Exports `PRODUCT_NAME`,
   `NavItem`, `NavGroup`, `NAV_GROUPS`, `SETTINGS_ITEM` and
   `activeNav(pathname)`. `activeNav` returns `{ group, item }` with
   `group` **null** for `/settings`, and null overall for an unowned
   path. Pure data and one resolver — no React, so it imports and tests
   without the Next runtime.

2. **`studio/components/NavTabs.tsx`** — renders two rows from
   `NAV_GROUPS`: group headers, then the open group's items. Only the
   item carries `aria-current="page"`; a group header carries
   `aria-expanded` and an active style. Settings sits in the first row,
   pushed right. Both rows keep today's
   `overflow-x-auto whitespace-nowrap`. The existing flat `NavTab` type
   and `activeTab()` helper may be removed once no caller imports them —
   grep before deleting.

3. **`studio/app/layout.tsx`** — drops the local `TABS` array, imports
   `PRODUCT_NAME`, `NAV_GROUPS` and `SETTINGS_ITEM` from `@/lib/nav`,
   uses `PRODUCT_NAME` for `metadata.title` and the header wordmark, and
   passes the groups to `NavTabs`. The `#307` comment above `TABS`
   explains decisions that still hold; carry across what is still true
   rather than deleting it wholesale.

4. **`studio/README.md`** — the product name.

5. **`tests/release/ui_checks.sh`** — the nav loop's route-and-label
   pairs updated per FR-5. The structure of the assertion does not
   change: it still joins the text of every `[aria-current=page]`
   element and compares it to one expected label, which is exactly why
   the group header must not carry the attribute.

6. **Docs** — `docs/install.md`, `docs/peer-review.md` and
   `docs/session-analytics-cookbook.md` name the renamed tabs in twelve
   places between them; `git grep -n -E '(Dashboard|Analysis) tab'` is
   the list to work from. Rename only what the nav renamed: Dashboard →
   Overview, Analysis → Analysis pipeline. Do not rewrite surrounding
   prose.

## Verification

`studio/scripts/nav-check.mjs` already exists and already fails on every
FR — it was written against the target state before any of this work.
One FR per invocation:

```
node studio/scripts/nav-check.mjs FR-2
```

It compiles `lib/nav.ts` and `components/NavTabs.tsx` with the studio's
own `tsc`, stubs `next/link` and `next/navigation`, renders statically
and asserts. Modelled on `studio/scripts/states-check.mjs`; no server,
no browser, no store, so it gates a phase.

`studio/scripts/states-check.mjs` is the per-phase regression test. It
passes today under node 24 and must keep passing: it compiles and
renders a large share of the Studio's components, so a broken import or
a changed shared type shows up there.

## Delegation

Each phase in `tasks.md` is one commit. A phase must leave the tree
building: phase 1 introduces `lib/nav.ts` and wires the name, phase 2
switches the navigation over, phase 3 updates the gate and the docs.

## Launch

Admission passed 12/12 and the driver's dry run plans three phases on
2026-10-28. The spec bundle and `studio/scripts/nav-check.mjs` must be
committed first: the driver refuses a dirty worktree.

```bash
cd /Users/gosha/dev/repo/code-copilot-team
export PATH="$HOME/.nvm/versions/node/v24.11.1/bin:$PATH"   # node 16 is first by default and fails both checks
export CCT_ADMISSION_TEST_IN_PLACE=1                        # studio/node_modules is gitignored, so admission's throwaway worktree has no tsc
export CCT_REVIEW_DIFF_MAX_LINES=4000                       # the default 500 truncates a review of this size
mkdir -p .cct/auto-build
nohup bash scripts/auto-build-loop.sh harness-studio-nav --profile unattended \
  > .cct/auto-build/harness-studio-nav.log 2>&1 &
```

`DEEPSEEK_API_KEY` must be exported in that shell; the reviewer probe
answered PASS in 2s for $0.0002 on 2026-10-28.

Reading the result:

```bash
tail -f .cct/auto-build/harness-studio-nav.log
jq -r '.state, .phase, .outcome' .cct/auto-build/harness-studio-nav/state.json
gh pr list --head feature/harness-studio-nav-run1
```

Exit codes: 0 landed (PR open, never merged) · 3 milestone-paused ·
4 escalated/parked · 6 deliberate stop at a policy boundary.

**The run checks out `feature/harness-studio-nav-run1` in the main
checkout.** It does not touch the `docfix` or `ux123` worktrees, and it
starts no server, so the owner's API on 8765 and Studio on 3000 are
unaffected — but the main checkout will not be on `master` afterwards.

## Risks

- **The Studio must keep building between phases.** `NavTabs` changing
  its props is a breaking change for `layout.tsx`, so those two move in
  the same commit (phase 2), not separate ones.
- **Node version.** `tsc` and the render need node 24; node 16 is first
  on this machine's PATH by default and silently produces a broken
  install. The launch command pins the PATH.
- **Do not touch the owner's running instance.** The API on 8765 and the
  Studio on 3000 belong to the owner. Nothing in this feature starts,
  stops or rebuilds a server; the contract check needs none.
- **The release is not tagged yet.** v2.0.0's screenshots and
  verification document name the old tabs. This branch must not be
  merged before the tag, which is why the run opens a PR and never
  merges.
