# Tasks: session-analytics benchmark comparison UI (E9 Studio slice)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: fetcher + view

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | `BenchmarkSummary` type + `api.benchmark()` fetcher (FR-1) | `studio/lib/api.ts` | build | [ ] |
| 2 | | Benchmark page: coverage `Stat` row + per-result comparison table (result badge, attempts, linked sessions, `formatCost` cost, humanized avg duration) (FR-2) | `studio/app/benchmark/page.tsx` (new, per D-placement) | build | [ ] |
| 3 | [P] | Nav tab "Benchmark" (D-placement) | `studio/app/layout.tsx` | build | [ ] |

**Checkpoint US1**:
- [ ] Table shows exactly the four payload figures per result; no client-side re-derivation
- [ ] Cost via existing `formatCost`; duration humanized; `—` for zero-duration unlinked rows

---

## US2: empty state + validation

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Empty state: no `by_result` rows ⇒ guidance panel naming the `correlate` command; coverage stats still render (FR-3) | `studio/app/benchmark/page.tsx` | build | [ ] |
| 5 | | `npm run build` green; manual render sanity on seeded stores (linked / unlinked-only / empty) (FR-6) | — | build | [ ] |

**Checkpoint US2**:
- [ ] Empty store renders guidance, not a broken table
- [ ] Build green; no new npm deps; zero Python-side diff (FR-4)

---

## Final Verification

- [ ] `git diff` touches ONLY `studio/` files
- [ ] `next build` green (local — Actions down)
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
