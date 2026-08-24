# Tasks: Probe-verified recovery + failback — increment D of #109

Sequential; hold for user review between tasks. Contracts live in
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
  and `probe_deferred_caps` → scrub → classify → transition;
  launched-is-accounted even on malformed/timeout/crash; no
  cost-file capability in the child; credential-echo scrub proven),
  `CCT_ROUTING_PROBE_CMD` seam.
- Covers SC-D2.

## T3 — routing tick

- `cct routing tick --due --once [--wake]` per decision 4: global
  lock (held → named refusal), due-only probing, atomic result
  application with threshold transitions, byte-level idempotency,
  fallback-run marking, wake as the IDEMPOTENT ARGV REPLAY
  (structured ledger vector verbatim — never eval/sh -c;
  disposition/mode/restriction/lock/root revalidation; atomic
  per-park wake generation claimed before launch, replay = journaled
  no-op, pre-exec failure releases the claim; live lock → named
  refusal; `recovery.wake_enabled=false` → named refusal). The purity
  boundary stated: validate/status/explain stay pure.
- Covers SC-D5 (+ the wake half of SC-D8).

## T4 — Supervisor failback + policy promotions

- Decision 5: boundary-only failback with hysteresis at the
  consumption point (threshold AND dwell independently blocking,
  dwell gating both the preferred health age and the active
  profile's tenure);
  attempted-set clearing so B's selector prefers naturally; the
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
  failures journal, never cancel the failback).
- Covers SC-D6, SC-D7, SC-D8.

## T6 — Docs, gates, sweep

- README (the D section beside A/B/C, opening with
  "healthy is a probe-verified claim, never an assumption"),
  CHANGELOG, count pins, full sweep, origin build-completion
  revision, deferred-scope record on the child issue.
- Covers SC-D10.
