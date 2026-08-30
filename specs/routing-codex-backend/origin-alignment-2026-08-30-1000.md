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

## Review rounds 4-6 (implementation)

Round 4 found four blockers on the promised execution path: the generic
normalizer parsing codex's result shape; the routed model not reaching
the harness; the reconcile chain launching claude for a codex profile;
preflight checking the claude binary.

Round 5 found that three of the four "covered" claims were not covered
— a tautological session-id assertion, fixture verification that
existed only in a shell session rather than the suite, and an entirely
untested supervisor half — plus the #199 stderr hazard in both new
branches.

Round 6 found five more on the real execution path, including that
codex wraps `RECONCILE_VERDICT` inside an `agent_message` event so
every successful reconciliation reached `reconcile_verdict_missing`,
that the profile's provider was never bound, and that a nonzero exit
could normalize as success.

**Three of the regressions in those rounds were introduced by my own
fixes, not by the original code:**

1. Fixing the forged-verdict hazard (#199) by separating stderr created
   an unscrubbed `$OUT.stderr` orphan in /tmp carrying the echoed
   packet.
2. Fixing the verdict boundary by decoding `$OUT` in place destroyed
   the failure-classification signal: a rate-limited round classified
   as `unknown`, defeating failover — the arc's entire purpose.
3. Making cleanup exit-safe installed a second `trap ... EXIT`, which
   REPLACES rather than appends, silently disabling `run_unlock` and
   leaking the run lock; then relocating it exposed an ordering bug
   where the handler was called before it was defined, turning an early
   refusal's exit 64 into 127.

Each was caught in review, not by me, and each was in the FIX rather
than the code being fixed. The operative lesson is narrower than "test
more": a fix needs its own review, and a green suite is not evidence
that it had one. Two supporting instances from the same rounds — three
assertions used a helper that does not exist in that suite and silently
never ran (caught only by the assertion-count pin), and `grep -c`
prints `0` AND exits 1, so `|| echo 0` produced `"0\n0"`.

## Live captures

codex-cli 0.147.0 is present on the development host and was executed
directly rather than reasoned about. Those captures did real work:
they confirmed `-c model_provider=` exists before the code depended on
it, matched the event shape to the recorded fixtures, produced the
`RECONCILE_VERDICT` transcript the decode test now runs against
(`tests/fixtures/codex/reconcile-verdict-live.jsonl`), and showed codex
writing an `ERROR` line to stderr — turning the #199 hazard from cited
precedent into behaviour observed here.

## Not demonstrated

Exactly one thing: an end-to-end delegate/reconcile round driven by a
live codex. The launch chains are exercised via mocks and structural
assertions.

Everything else about the CLI contract HAS been exercised against the
real binary — see Live captures above. The decode boundary runs against
a transcript captured from codex-cli 0.147.0 and committed as a
fixture. plan.md and the README state the same narrowed scope.
