# Tasks: Probe-verified recovery + failback — increment D of #109

Sequential implementation. Contracts live in
`plan.md` (decisions) and `spec.md` (FR-D/SC-D); tasks reference,
never restate.

## T1 — State extension + timing

- `routing-state.sh` per decision 1: additive schedule fields, the
  closed seven-state vocabulary, frozen read rules (only in-dwell
  `healthy` verified-good; `degraded|probe_due|probing` never
  selectable; stale `healthy` decays to `unknown`; overdue `probing`
  reads as ABANDONED — `unknown` + `routing_probe_abandoned`, no
  counter movement, never `probe_fail`; the closed transition matrix
  executable with only-verified-canary-enters-healthy). Timing/backoff helpers per decision 3
  (precedence chain; deterministic jitter; RD_* named defaults).
- Pre-commit mutation floor: decay-to-healthy, stale-healthy kept
  verified, and probing-read-as-health must each be caught.
- Covers SC-D1, SC-D3. B suite unmodified.

## T2 — Probe engine

- `scripts/lib/routing-probe.sh` per decision 2: real-inference +
  tool canaries via B's env wiring, closed tri-state
  (`probe_pass|probe_fail|probe_unverifiable`), tool-canary failure
  never healthy, unverifiable stays `unknown`, the FROZEN
  invocation ordering (debit → bounded launch with pre-launch caps
  and `probe_deferred_caps` with scheduling backoff → scrub →
  classify → transition;
  launched-is-accounted even on malformed/timeout/crash; no
  active routing paths rebound to a private child tree; credentials
  child-env-only and absent from argv; credential-echo scrub proven),
  `CCT_ROUTING_PROBE_CMD` seam.
- Covers SC-D2.

## T3 — routing tick

- `cct routing tick --due --once [--wake]` per decision 4: dedicated
  whole-pass scheduler lock (held → named refusal), due-only probing,
  atomic result
  application with threshold transitions, byte-level idempotency,
  fallback-run marking, wake as the IDEMPOTENT CLOSED
  RECONSTRUCTION (plan Amendment A1 — the executable comes from the
  tick's own installation and every ledger value is re-validated;
  never eval/sh -c, never a ledger-supplied command; disposition
  paired with the status an unattended refusal really writes;
  mode/restriction/lock/root revalidation; probe-qualified candidate
  required; backend bound to the run's effective policy; code-owned
  default caps/on-incomplete only (non-default ledger grants refused
  for manual resume); atomic per-park wake generation
  minted with the disposition and claimed before launch, replay =
  journaled no-op, an UNACKNOWLEDGED launch journals
  `wake_launch_failed` and releases the claim; live lock → named
  refusal; `recovery.wake_enabled=false` → named refusal, with that
  key PROMOTED here). Per plan Amendment A2: a closed mode
  discriminator (bounded-work `--delegate`/`--reconcile` runs are
  refused by name, never rebuilt as ordinary runs), a durable acknowledged
  generation released only by a locked CAS, liveness-proven
  fallback marking, and closed named events persisted per run. The
  purity boundary stated: validate/status/explain stay pure. Wire live
  supervisors to run this same due-only path when recovery markers are
  the only selection blocker, so external scheduling is optional for
  in-run cooldown recovery. Discover worktree-local ledgers by default;
  document and validate `--ledger-root` for explicit shared roots; pass
  the exact validated registry and ledger root to the relaunched child.
- Covers SC-D5 (+ the wake half of SC-D8).

## T4 — Supervisor failback + policy promotions

- Decision 5: boundary-only failback with hysteresis at the
  consumption point (threshold AND dwell independently blocking,
  dwell gating both the preferred health age and the active
  profile's tenure);
  boundary targeting through B's existing selector; the
  three `[policy]` keys promoted with defaults;
  `max_switches_per_task` still refused; `failback = operator` and
  the repo restriction each pin the run to the fallback, journaled.
- Legacy + B byte-compatibility proven (suites unmodified).
- Covers SC-D4, SC-D9 (+ the failback half of SC-D8).

## T5 — Operator enable + recovery key + reconcile-on-recovery

- Decision 6: `cct routing enable <id>` — the only auth-disabled
  exit, landing on `probe_due`, operator-journaled, wrong-state
  refusals; automatic paths proven refused.
- Decision 8: `routing.recovery` closed restriction-only block
  through validator + schema + rc_effective (explicit-null reads).
- Decision 7: failback boundaries reconcile pending provisional
  records via C's flow (one attempt per record per boundary;
  failures journal, park the boundary, and leave failback retryable).
- Covers SC-D6, SC-D7, SC-D8.

## T6 — Docs, gates, sweep

- README (the D section beside A/B/C, opening with
  "healthy is a probe-verified claim, never an assumption"),
  CHANGELOG, count pins, full sweep, origin build-completion
  revision, deferred-scope record on the child issue.
- Covers SC-D10.
