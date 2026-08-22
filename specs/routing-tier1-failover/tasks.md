# Tasks: Tier-1 failover — increment B of #109

Sequential; hold for user review between tasks. Contracts live in
`plan.md` (decisions) and `spec.md` (FR-B/SC-B); tasks reference,
never restate.

## T1 — Circuit state store

- `scripts/lib/routing-state.sh` per decision 4: locked atomic
  read/modify/write, per-profile and per-pool entries, pool-outranks-
  profile, time-based decay to `unknown` (journaled as the increment-D
  hook), `auth` never auto-decays, `last_applied_attempt` idempotency
  keys per decision 5 step 4.
- Pre-commit mutation floor (plan-review pin): atomic RMW (a torn
  write is never readable), crash-indeterminate recovery (a partial
  application replays as a no-op), and stale/partial state refusal —
  all proven BEFORE T2 builds policy on the store.
- Covers the state half of SC-B2, SC-B9 (persistence half).

## T2 — Class→action policy

- `scripts/lib/routing-actions.sh` per decision 3: the frozen
  taxonomy mapped to supervisor actions; legacy USAGE_PATTERN result
  recorded as fallback evidence only; `unknown` fails closed; retry
  budgets as journaled constants.
- Covers the action half of SC-B3.

## T3 — Selection engine

- Deterministic selection over `rc_effective` candidates per decision
  2/decision 4 filters (role build, tier1-only, state, attempted-set),
  priority-ordered, every candidate journaled in explain vocabulary;
  bounded and cycle-free.
- Covers SC-B2 (selector half), SC-B4.

## T4 — Supervisor routing mode

- `cooldown-supervisor.sh --routing` per decisions 1, 5, 6, 9:
  refusal rules (no registry / merge-disabled), checkpoint before
  switch (never a session id), claude-code env wiring (names
  journaled, values child-only) + pi launch, requested/effective
  model recording with fail-closed mismatch, exhaustion
  park/terminate vs sleep-to-eligibility, crash-resume from the
  checkpoint under the existing feature lock.
- Legacy byte-compatibility: the existing cooldown-supervisor suite
  passes UNMODIFIED without the flag.
- Covers SC-B1, SC-B3 (end-to-end half), SC-B5, SC-B6, SC-B7, SC-B9,
  SC-B10.

## T5 — Identity + review independence

- Decision 8: profile identity into ledger/review context/analytics
  (additive); reviewer-independence re-evaluation after every switch
  with #190 dispositions; providers.toml read-only.
- Covers SC-B8.

## T6 — Docs, gates, sweep

- README (the routing section gains the B behavior beside A's
  foundation, stating what remains D/C), CHANGELOG, count pins,
  full sweep, origin-alignment build-completion revision, #<child>
  deferred-scope record.
- Covers SC-B11.
