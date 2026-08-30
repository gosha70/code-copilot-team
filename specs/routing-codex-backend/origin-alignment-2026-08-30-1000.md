# Origin alignment — routing-codex-backend (child increment of #109)

Verdict: aligned
Confidence: high

## Origin capture

The work is named by #109 itself in three places: the example priority
chain ("GPT-5.6 Sol through the Codex backend"), the Likely Affected
Areas list ("Codex auto-build execution adapter"), and Goal 2 ("an
ordered chain of profiles spanning different backends"). The parent
plan (`specs/routing-tier1-failover/plan.md:184`) designates it as its
own child increment after B and binds it to reuse B's normalized
attempt/result/checkpoint contracts rather than growing a codex-special
path.

## Why this exists as a record

Increments A–E3 each shipped an SDD record; this one was initially
built straight to code under time pressure, which left
`check-origin-alignment.sh` unable to run for it at all. That gap is
what this file closes. `spec_mode: none` is deliberate — the value is
the origin trail and the named deviation, both machine-checkable, not a
restatement of the parent plan for ~150 lines mirroring two existing
backends.

## Deviation from the parent constraint, recorded not glossed

The cost path diverges. Claude and pi parse `.total_cost_usd` and debit
metered cost; codex reports token usage and no USD in any recorded
transcript, so the adapter debits the unmetered-estimate path instead.
Recorded in plan.md with the reasoning: fabricating `$0` would silently
stop the cost cap accruing, and a token→USD table in the driver would
put per-model pricing in the routing engine that #109's non-goals
forbid. The estimate path is the repo's own existing rule for unmetered
invocations, so the divergence reuses a contract rather than inventing
one.

The first version of that record overstated it — it claimed the
estimate is debited unconditionally, when `ESTIMATES_ACTIVE` gates it
to `unattended` profiles or configs declaring `unattended.budget`.
Outside those, codex accrues nothing at all against the cap. Corrected
before commit, and worth noting as the same pattern one level up: a
claim broader than its evidence, this time in the record meant to make
the deviation checkable.

## Review history

Built, then reviewed in two rounds against the diff and the plan of
record. Round 1 found four blockers (codex's result shape parsed by the
generic normalizer; routed model not passed; the reconcile chain
launching claude for a codex profile; preflight checking the claude
binary). Round 2 found that three of the four "covered" claims were not
actually covered — a tautological session-id assertion, fixture
verification that existed only in a shell session and not in the suite,
and an entirely untested supervisor half — plus the #199 stderr hazard
in both new branches. Round 3 found that the stderr fix had introduced
an unscrubbed, unpersisted, uncleaned `$OUT.stderr` orphan carrying the
echoed packet.

All are fixed. The corrections are recorded because the pattern is the
point: each round found a claim that was broader than its evidence.

## Not demonstrated

A live run against the real codex CLI. Flagged in plan.md and in the
README rather than implied by the passing suites.
