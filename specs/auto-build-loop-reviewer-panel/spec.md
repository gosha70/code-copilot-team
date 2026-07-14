# Spec: auto-build-loop reviewer panel (increment E)

Issue #78. Base: driver + review integration merged in #72–#75. Design:
`specs/auto-build-loop/design.md` §E, decision 4. The driver reviews each
phase; today it uses one gating reviewer via `review-round-runner.sh` (which
owns the round/attempt/retry loop over a single `peer_provider`).

## User Scenarios

- US1: As a project owner, I declare a reviewer panel in `automation.json`
  (e.g. correctness→Codex gating, security→GPT advisory, style→Ollama
  advisory). Each phase is gated by the gating reviewer exactly as before,
  while the advisory reviewers' findings are folded into the fix sessions so
  the build addresses them — without letting an advisory reviewer block the
  phase.
- US2: As a project owner, if an advisory reviewer's provider is down the run
  continues (that lens is skipped and journaled); only the gating reviewer
  being unavailable parks the run.
- US3: As a reviewer of the automation output, every reviewer's findings
  (gating and advisory) are archived per phase so I can see what each lens
  reported and how it was addressed.

## Requirements

Panel review (US1):
- FR-1: The driver reviews each phase with the full `review.reviewers[]`
  panel. Exactly one reviewer MUST have `gating: true` (preflight errors
  otherwise, as today). The gating reviewer drives the runner-owned round loop
  UNCHANGED — round/attempt numbering, `/review-decide` retry, breaker
  semantics, and parked-resume are all preserved. Phase PASS still requires
  the gating reviewer to PASS with `blocking_findings_open: 0`.
- FR-2: Each non-gating reviewer runs per phase; its findings are ADVISORY —
  folded into the fix-session prompt alongside the gating blocking findings
  and tagged by provider/specialization/scope. Advisory findings NEVER block
  PASS and never independently trigger a review round.
- FR-3: Advisory reviewers run in ISOLATION from the canonical `.cct/review/`
  state (the gating loop + `/review-decide` operate on it). A crash mid-
  advisory-review MUST never strand or corrupt the gating review state — the
  gating loop's round/attempt counters are unaffected by advisory runs
  (fail-closed, resume-safe).
- FR-4: Each reviewer's `scope` (`both`/`code`/`docs`) and `specialization`
  label are honored per invocation and surfaced in the archived findings and
  the fix prompt.

Preflight + health (US2):
- FR-5: Preflight health-checks every reviewer in the panel. The gating
  reviewer (or its fallback chain) unhealthy → park `provider_unavailable`
  (fatal, as today). A non-gating reviewer unhealthy → warning + skip for the
  run (advisory, non-fatal); the skip is journaled. Parked-resume health
  re-check likewise only gates on the gating reviewer.

Folding + archive (US3):
- FR-6: When a gating-triggered fix session runs, its prompt includes the
  gating blocking findings AND the current advisory findings (deduped, tagged
  by specialization). Advisory reviewers are re-run each panel round so their
  findings track the evolving diff.
- FR-7: All reviewer outputs are archived per phase — the gating loop under
  `phase-N/review/` (unchanged) and advisory results under
  `phase-N/review-advisory/<provider>/` — so the panel result is inspectable.

Docs, tests, cleanup (US1–US3):
- FR-8: Fix the stale `providers.toml` template comment (§E).
- FR-9: Tests (`tests/test-auto-build-loop.sh`): multi-reviewer config —
  gating FAIL + advisory findings → the fix prompt carries both → PASS;
  advisory reviewer FAIL never blocks PASS; advisory reviewer unhealthy →
  skipped and the run continues; advisory isolation (an advisory run does not
  mutate the canonical `.cct/review/` round/attempt); a single-reviewer config
  is byte-for-byte unchanged (existing assertions hold). Counts registered in
  `tests/test-counts.env` + README.
- FR-10: `shared/skills/auto-build-loop/SKILL.md` + config docs updated (panel
  semantics, gating vs advisory, health rules); adapters regenerated with zero
  drift.

## Constraints

- Bash 3.2 compatible; jq for JSON; no new dependencies.
- v1 supports exactly one gating reviewer + N advisory reviewers; multiple
  gating reviewers (driver-side multi-runner round aggregation) are deferred.
- The shared `review-round-runner.sh` keeps single-reviewer behavior; any
  change to it is minimal and additive with zero default-behavior change (the
  existing review-loop assertions must still pass).
- A single-reviewer, advisory-free config behaves exactly as increments A–D.
- Advisory reviewers never block, never park, never trigger a round; only the
  gating reviewer drives PASS/FAIL/breaker/park.
- One issue per PR: this bundle covers exactly #78.
- Linux parity verified in an ubuntu container before review.
