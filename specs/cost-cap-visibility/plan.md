---
spec_mode: lightweight
feature_id: cost-cap-visibility
risk_category: feature
justification: |
  Enhancement (#201) touching the driver's config handling: caps become
  re-readable mid-run for attended profiles. That changes when a policy
  value can move during a run, so it warrants stated requirements and
  constraints rather than a plan-only change.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/201
  origin_claim: |
    Enhancement #201: "Cost cap: discoverability and live visibility
    (undocumented $25 default, no in-run spend, no proactive raise)".
    caps.cost_usd is well-designed and correctly enforced, but not
    discoverable and not visible while a run is in flight. A user
    launching an autonomous build inherits a $25 default they were never
    told about, watches no running total, and cannot raise the cap
    proactively — they have to get parked first. Gap 1: the README never
    mentions the cost cap (zero grep matches). Gap 2: no live cost
    visibility during a run. Gap 3: snapshot semantics make proactive cap
    raises impossible. Plus: the cap was silently inert before #198.
---

# Plan: make the cost cap visible and raisable (#201)

## Gap 1 — README

A "Cost & safety caps" section: the $25 default and that it is real money,
where to set it, the per-phase spend line, what a `cap_exceeded` park looks
like, how `--resume` clears it, the snapshot-vs-live rules, and an upgrade
note that the cap was inert before #197/#198.

## Gap 2 — live spend

`report_phase_spend()` prints at each phase gate:

```
[auto-build] phase 1 complete — $4.24 spent of $25.00 cap ($20.76 left)
```

It names the estimated portion when there is one, so a conservative estimate
is never mistaken for measured spend (the #191/#193 distinction).

## Gap 3 — proactive raises

Of the issue's three options, this implements the phase-gate re-read.
`refresh_live_caps()` re-reads `caps.cost_usd` from the live config at each
phase gate, updates the frozen snapshot and `.caps.max_cost_usd`, announces
it on stdout, and journals `cap_updated`.

Deliberately narrow:

- **Only `caps.cost_usd`.** The snapshot freeze is a real design property
  (#193); this widens it for the one value that is the human's live control
  knob, not for config generally.
- **Only at phase gates**, never mid-phase, so a session never sees its
  budget move underneath it.
- **Only positive values.** A `0` or non-numeric live value is ignored
  rather than silently zeroing the budget and parking the run at its next
  check.
- **Lower caps are honoured AND enforced immediately.** Winding an
  expensive run down is a legitimate operator action, but a cap that is
  accepted without being enforced is worse than an immovable one — the gate
  re-checks straight after applying, so an over-budget run parks there
  instead of committing and finishing `done`.
- **Never for `unattended`.** #193 binds such a run to the config it was
  ADMITTED against; an unaudited mid-run policy change from an external
  edit would break that binding. It must park or terminate to change a cap.

## Not done (and why)

The issue's nice-to-have — a pre-run cost estimate from prior ledgers in
`--dry-run` — is left out. It needs a cross-run history format and an
estimation model, which is its own piece of work rather than a rider on a
visibility change.
