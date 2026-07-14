---
spec_mode: full
feature_id: auto-build-loop-reviewer-panel
risk_category: integration
justification: |
  Extends the merged auto-build driver's review integration from a single
  gating reviewer to a specialization-scoped panel (one gating + N advisory).
  Touches the driver's preflight health-check, review loop, and fix-prompt
  composition, plus advisory-run isolation. The shared review-round-runner
  stays single-reviewer (at most a minimal additive env override). All
  coverage via the existing mock-based suite. Series: specs/auto-build-loop/design.md.
status: approved
date: 2026-07-14
issue: 78
origin:
  issue: gosha70/code-copilot-team#78
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/78
  origin_claim: |
    Issue #78 (increment E): specialization-scoped reviewer panel. One gating
    reviewer drives the runner-owned round loop unchanged; N non-gating
    reviewers run per phase as advisory — findings folded into fix prompts,
    never blocking PASS or triggering a round, run in isolation from the
    canonical .cct/review/ state. Preflight health-checks all reviewers
    (gating fatal, advisory skip-and-warn). Per-reviewer scope/specialization
    honored + surfaced; all outputs archived per phase. Fix the stale
    providers.toml template comment. Tests: gating FAIL + advisory folded →
    PASS, advisory FAIL never blocks, advisory unhealthy skipped, single-
    reviewer config unchanged. v1 = one gating + N advisory; multiple gating
    deferred.
---

# Plan: auto-build-loop reviewer panel (increment E)

Design: `specs/auto-build-loop/design.md` §E + decision 4. Grounded code
(verified 2026-07-14): `GATING_REVIEWER` = first `gating:true` reviewer
(`scripts/auto-build-loop.sh:252`); `run_review_loop` invokes
`review-round-runner.sh` once per round over `.cct/review/state.json`'s single
`peer_provider` (:618–); the runner hardcodes
`REVIEW_DIR="$PROJECT_DIR/.cct/review"` (`review-round-runner.sh:40`).

## Deliverables

1. **Panel resolution** (`load_config`): keep `GATING_REVIEWER` (still exactly
   one `gating:true`); add `ADVISORY_REVIEWERS` = the non-gating entries with
   their `scope`/`specialization`.
2. **Preflight health** (`preflight`): health-check the gating reviewer (fatal,
   as today) AND each advisory reviewer; advisory unhealthy → warn + drop from
   the run's advisory set (journaled). Same gating-only rule on parked-resume.
3. **Advisory review pass** — a driver helper that runs each healthy advisory
   reviewer against the phase diff in ISOLATION (per D-isolation below),
   collects structured findings, and archives them to
   `phase-N/review-advisory/<provider>/`. Never touches the gating loop's
   `.cct/review/` round/attempt state.
4. **Fix-prompt folding** (`compose_fix_prompt`): append the current advisory
   findings (tagged by provider/specialization) to the gating blocking
   findings so fix sessions address both. Advisory reviewers re-run each panel
   round to track the diff.
5. **Cleanup**: fix the stale `providers.toml` template comment.
6. **Tests** (`tests/test-auto-build-loop.sh`) per FR-9; register counts.
7. **Docs**: `auto-build-loop` SKILL.md panel semantics + config; regen adapters.

## Design decisions to confirm at approval

- **D-scope.** v1 supports one gating reviewer + N advisory reviewers.
  Multiple GATING reviewers (driver-side aggregation of several runner-owned
  loops) are deferred — they add round-accounting complexity for little v1
  value. *(Recommend as stated.)*
- **D-isolation.** To run advisory reviewers without corrupting the canonical
  `.cct/review/` state, recommend a **minimal additive** override on the
  runner: `REVIEW_DIR="${CCT_REVIEW_DIR:-$PROJECT_DIR/.cct/review}"` (default
  unchanged → zero behavior change; precedent: `CCT_REVIEW_BASE_REF` added in
  increment A; +runner tests). The driver then runs each advisory reviewer in
  a scratch `.cct/review-advisory/<provider>/` dir. *Alternative:* a
  no-runner-change move-aside/restore of `.cct/review/` per advisory run — but
  that is crash-fragile (a crash mid-run could strand the gating state), which
  conflicts with the driver's fail-closed discipline. **Recommend the additive
  `CCT_REVIEW_DIR`.** Confirm — this is the one runner touch, distinct from a
  "panel mode" in the runner.
- **D-advisory-on-clean-pass.** When the gating reviewer PASSes on a round with
  no fix session, advisory findings from that round are archived but NOT acted
  on (no extra fix pass). *(Recommend as stated — advisory rides gating-
  triggered fixes only; a clean gating PASS ends the phase.)*

## Out of scope

- Multiple gating reviewers / gating aggregation (later).
- Any panel logic inside the runner (it stays single-reviewer; at most the
  additive dir override).
- The `merge` profile (#F).

## Test strategy

Mock-only, extending the existing suite: add a second (advisory) mock provider
profile; assert folding, non-blocking, skip-on-unhealthy, isolation, and
single-reviewer invariance. Linux parity: one ubuntu container run before
review (macOS bash 3.2 masks Linux errexit semantics — lesson from #73).
