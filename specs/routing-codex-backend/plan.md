---
spec_mode: none
feature_id: routing-codex-backend
status: draft
date: 2026-08-30
risk_category: integration
justification: >
  A codex EXECUTION adapter for the auto-build driver and the routing
  supervisor. Small, additive surface (~150 lines) that mirrors the two
  existing backends rather than introducing new contracts, so a full
  spec bundle would document less than the code and its regressions
  already do. Recorded as spec_mode=none deliberately: the value here
  is the ORIGIN record and the named deviation below, both of which the
  repo's own gates can check, not a restatement of the parent plan.
origin:
  type: issue
  issue: 109
  parent: 109
  references:
    - "#109 example priority chain — 'GPT-5.6 Sol through the Codex backend' as the third leg"
    - "#109 Likely Affected Areas — 'Codex auto-build execution adapter'"
    - "#109 Goal 2 — 'Support an ordered chain of profiles spanning different backends, providers, and models'"
    - "specs/routing-tier1-failover/plan.md:184 — designates this as its own child increment and REQUIRES reuse of B's normalized attempt/result/checkpoint contracts rather than a codex-special path"
    - "specs/codex-provider-command/plan.md — the recorded live capture that `codex exec` echoes prompt and final message to stderr, and that merging it forged a PASS verdict"
    - "scripts/benchmark_runner/backends/codex.py + tests/fixtures/codex/*.jsonl — the recorded transcript that defines codex's real event contract"
---

# Plan: codex execution backend (child increment of #109)

## What ships

`codex` becomes an executable backend, not merely an accepted registry
name. `RC_BACKENDS` already validated `backend = "codex"` and the router
would select such a profile, but neither `auto-build-loop.sh` nor
`cooldown-supervisor.sh` could execute one — that leg of #109's own
example chain was dead.

- `run_codex_session` in the driver, under the same contract as the
  claude and pi backends; `run_session` dispatch; `--backend codex`;
  `subject_provider=codex`.
- `codex_result_obj` — codex's events normalized INTO the shared
  `{subtype, session_id}` contract.
- Codex branches at both supervisor launch chains (delegate and
  reconcile), each passing the profile's routed model.
- Preflight checks the codex binary rather than falling through to the
  claude branch.

## Reuse of the parent contract, and the one deviation

The parent plan's binding constraint is to reuse increment B's
normalized attempt/result/checkpoint contracts rather than growing a
codex-special path. Held for the result and checkpoint contracts:
`codex_result_obj` ADAPTS codex's real events into the same
`{subtype, session_id}` shape the driver already consumes, so every
downstream consumer is unchanged.

**Named deviation — the cost path.** Claude and pi parse
`.total_cost_usd` from their result envelope and debit
`.totals.cost_usd` as a measurement. Codex reports TOKEN USAGE and
never a USD figure, in any recorded transcript. The adapter therefore
passes an EMPTY cost to `debit_invocation_cost`, whose documented rule
is that an empty cost is an unmetered invocation.

State the condition precisely, because the fallback is NOT
unconditional. `debit_invocation_cost` debits the conservative estimate
only when `ESTIMATES_ACTIVE=true`, which `auto-build-loop.sh` sets in
exactly two cases: the profile is `unattended`, or
`.unattended.budget != null` with `estimate_unmetered` not false.
Outside those, it records nothing and returns.

So on an attended run against a config with no `unattended.budget`
block, **a codex session debits nothing — neither metered nor
estimated** — while claude and pi on that same run debit their measured
cost. The cost cap is therefore blind to codex usage in that
configuration. That is the true extent of the divergence, and it is
deliberate rather than repaired here: making the accounting conditional
on backend would be a second codex-special path, and the alternatives
remain worse (fabricating `$0` silently stops the cap accruing for
every profile; a token→USD table puts per-model pricing in the routing
engine that #109's non-goals forbid). An operator who needs codex usage
to count against the cap must configure `unattended.budget`.

This is a divergence from "reuse the normalized contracts" in the
accounting half, and it is deliberate: the alternatives are to
fabricate `$0` — which would silently stop the cost cap accruing — or
to invent a token→USD price table in the driver, which would put
per-model pricing in the routing engine that #109's non-goals forbid.
The estimate path is the repo's own existing rule for exactly this
case, so the divergence reuses a contract rather than inventing one.

## Verification

- `codex_result_obj` unit-tested against all three RECORDED transcripts
  (success, no-usage, zero-usage), plus fail-closed on an incomplete
  turn, an error event, and unparseable input. `turn.failed`/`error`
  handling is DEFENSIVE — neither appears in any capture — and is
  labelled as such rather than presented as an observed contract.
- Driver-level tests with a mock emitting codex's REAL event shape
  (thread.started / item.completed / turn.completed), never a
  claude-style result envelope.
- Supervisor coverage is STRUCTURAL (both chains dispatch codex, pass
  the routed model, keep stderr out of the parsed stream, and clean up
  the stderr sibling) because the delegate/reconcile suites drive the
  harness through `CCT_SUPERVISOR_HARNESS_CMD`, which bypasses the
  backend branches.

## Known limitations

- **No live codex run.** Every test uses a mock or a recorded fixture.
  The #199-class stderr hazard is defended against structurally, but a
  live capture against the real CLI has not been performed.
- **`effective_model` is null for codex attempts.** No codex event
  carries a model field, so only the REQUESTED model is verifiable.
  Null is treated as unverified, never as equal to requested.
