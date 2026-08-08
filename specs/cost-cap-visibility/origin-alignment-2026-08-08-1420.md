# Origin Alignment Check — cost-cap-visibility

Date: 2026-08-08 14:20
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/201
  (`gh issue view 201` — three gaps with line references, the "what already
  works" section, the pre-#198 inert-cap note, the nice-to-have, and four
  acceptance criteria).
- The user's instruction: "proceed with the next bug/issue" (no bug-labelled
  issues remain open).

## Origin claim (verbatim)

> `caps.cost_usd` is well-designed and correctly enforced, but it is **not
> discoverable** and **not visible while a run is in flight**. A user
> launching an autonomous build today inherits a **$25 default** they were
> never told about, watches no running total, and cannot raise the cap
> proactively — they have to get parked first.

## Acceptance criteria (from the issue) — status

- README documents `caps.cost_usd`: default, location, `cap_exceeded`
  behaviour, `--resume` semantics — **met** ("Cost & safety caps").
- Per-phase spend/cap line printed to stdout — **met**, asserted.
- Snapshot-vs-live `caps` behaviour documented; proactive raise supported —
  **met** via the phase-gate re-read (the issue's second option) plus
  documentation of the freeze.
- CHANGELOG/README note that the pre-#198 cap was non-functional — **met**.

## Mismatches

- **The `--cap-cost` CLI flag was not added.** The issue says "pick one" of
  three options; the phase-gate re-read is the one that actually satisfies
  the stated need (raise while watching, without parking). A flag cannot be
  passed to a run already in flight.
- **The re-read is narrower than "caps"**: only `caps.cost_usd`, only at
  phase gates, only positive values, and never for `unattended` (which
  #193 binds to the config it was admitted against). The issue says
  "re-read `caps` from live config at each phase gate"; widening to
  `wall_clock_sec` and the unattended profile would erode the admission
  binding and the freeze property for no stated need. Flagged rather than
  silently narrowed.
- **The nice-to-have pre-run cost estimate is not implemented**, and the
  plan says why: it needs a cross-run history format and an estimation
  model.

## Verdict

Verdict: aligned
Confidence: high
