---
feature_id: harness-studio-nav
date: 2026-10-28
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feature/harness-studio-nav-run1
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: harness-studio-nav — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The refactor cleanly moves nav data into `lib/nav.ts` and introduces a two-row grouped nav with a Settings link. The core logic (`activeNav`, `owns`, `under`) is sound and preserves the prior `also`-prefix semantics. A few correctness and accessibility concerns remain around the `aria-controls` target, the `open` fallback when a group is chosen but the pathname changes, and the loss of the `activeTab` export that other code may depend on.

## Findings

- [warning] f-a6555087: All group buttons point `aria-controls` at the same `#nav-items` element, but only the expanded one actually controls it; screen readers will announce every header as controlling the same region, and collapsed headers claim to control a region they don't own. Also, `aria-expanded` on a button that toggles a shared region is semantically a disclosure pattern — acceptable, but the shared id makes the relationship ambiguous. (studio/components/NavTabs.tsx)
- [warning] f-b7b1c130: When the user clicks a header to browse another group and then navigates to a page in a *different* group, the `useEffect` resets `chosen` to null — good. But if the user clicks a header for a group and then navigates to a page in the *same* group, `chosen` is reset and `open` falls back to `hit.group`, which is correct. However, if `chosen` is set to a group id that no longer exists (e.g. after a future refactor removes a group), `find` returns undefined and it silently falls back — acceptable but worth a comment. More importantly: clicking a header for the *currently active* group sets `chosen` to that id, which is a no-op visually but leaves state that will be cleared on next navigation; harmless but the toggle never collapses. If collapse-on-second-click is intended (typical disclosure), it's missing. (studio/components/NavTabs.tsx)
- [warning] f-215402e2: `activeTab` was exported from `NavTabs.tsx` and may be imported elsewhere (tests, other components). The diff removes it without a deprecation shim or a grep-verified migration. If any consumer still imports `activeTab` or `NavTab`, the build breaks. (studio/components/NavTabs.tsx)
- [note] f-4109d49f: `activeNav` iterates groups in declaration order and returns the first match. With `/` matching only itself and `/labels` as an `also` on Overview, this is fine today. But `/routing` is now a first-class item under Development while previously it was an `also` on Benchmark — verify no page under `/routing/*` was relying on Benchmark being the active tab (e.g. a shared sub-layout). Behavior change is intentional per FR-2..FR-4 but worth a test. (studio/lib/nav.ts)
- [note] f-1563b11b: `activeNav` checks groups first, then Settings. If a future group item ever uses `/settings` as an `also` prefix, Settings would be shadowed. Currently safe, but the ordering is implicit. Also, `owns(SETTINGS_ITEM, pathname)` uses `under("/settings", ...)` which matches `/settings` and `/settings/*` — correct. (studio/lib/nav.ts)
- [note] f-b120b484: Resetting `chosen` on every pathname change means a user who opens a group to browse and then clicks a link *within that group* will see the group stay open (because `hit.group` equals the chosen group) — good. But a user who opens a group, then clicks a link in a *different* group (only possible via Settings, since other groups' items aren't rendered), will have `chosen` reset and `open` snap to the new page's group — correct. No bug, but the reset-on-navigation behavior is subtle; a comment already exists, which is good. (studio/components/NavTabs.tsx)
- [note] f-da50697f: Switching from fixed `h-14` to `min-h-14 py-2` allows the header to grow when the two-row nav wraps or when item labels are long. This is likely intentional (two rows need more height), but it changes the header's vertical rhythm and could shift content on narrow viewports. Verify the sticky/scroll behavior (if any) still looks right. (studio/app/layout.tsx)
- [note] f-709c6741: No tests are added in this diff for the new `activeNav` function or the group structure. Given the routing semantics changed (Routing promoted from `also` to first-class, Search moved into Mission Control, etc.), regression tests are warranted. (studio/lib/nav.ts)
