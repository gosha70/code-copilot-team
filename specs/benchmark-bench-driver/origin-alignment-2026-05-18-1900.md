# Origin-Alignment Record — benchmark-bench-driver

Date: 2026-05-18 19:00 UTC
Gate: plan-approval (Phase A, pre-build)
Origin: gosha70/code-copilot-team#36 (issue body + 2026-05-18 user clarifications)

## What the user asked for

Issue #36: a single user-facing `scripts/bench` wrapper with safe
defaults, terse `provider:model[@endpoint]` specs, live progress to
stderr, a per-attempt timeout with skip-to-next, a three-preset
library, and a README quickstart rewrite — **without changing the
harness's verdict logic**. Five tightly-coupled deliverables D1–D5 with
a verbatim out-of-scope list.

## What the spec/plan commit to

A wrapper that resolves every invocation to the unchanged
`compare`/`report` path; D1–D5 delivered in the issue's sequenced
order; the verbatim out-of-scope list reproduced as binding
constraints; no verdict/scoring/isolation change (D5 adds only a
`timeout` result value counted as a failure).

## Divergences (documented, user-confirmed 2026-05-18)

1. **D2/D5 built on the merged PR #35 Popen+pgkill**, not the issue's
   stale `subprocess.run` premise. Intent + acceptance criteria
   unchanged. (OQ-3 → "build on existing, document divergence".)
2. **D1 vLLM env-fill → probe-then-decide** (user-proxy vs.
   ephemeral-proxy auto-detect) because Claude Code cannot speak raw
   vLLM. (OQ-2.)
3. **Legacy `run-compare-*.sh` kept + shared proxy helper extracted**,
   not superseded/deleted. No capability discarded. (OQ-1.)

All three are recorded in spec.md § "Deviation from origin" and were
explicitly chosen by the user via the 2026-05-18 clarification
exchange. They refine implementation basis; they do not rescope the
deliverables or breach the out-of-scope list.

## Assessment

- Out-of-scope list: reproduced verbatim and binding. No scope creep
  (the proxy helper is extraction of existing logic, not a new
  backend/adapter/report).
- Acceptance criteria: every issue #36 acceptance bullet maps to a
  Success Criterion and a task.
- Verdict logic: untouched.

Verdict: aligned
Confidence: high

Divergences are documented and user-approved → origin-confirmation
gate is satisfied for the plan-approval gate. Re-run
`scripts/check-origin-alignment.sh benchmark-bench-driver` at the
build-entry and phase-complete gates.
