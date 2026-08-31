# Origin alignment — routing-usage-evidence (Increment G of #109)

Verdict: aligned
Confidence: high

## Origin capture

This increment exists because of a durable, **merged** finding rather
than a judgement call made while building.

`specs/routing-context-limit/audit-109-2026-08-31.md`, committed as
`d7d6694` and merged via PR #274 (merge commit `2360705`), walked all
33 of #109's acceptance criteria and found:

- 32 met or met-as-designed;
- **C30 PARTIAL and blocking** — "Tokens, costs, failed verifier
  commands, repair cycles, effective endpoint, and effective model are
  accurately recorded" is conjunctive; four of six are recorded on the
  routed path and tokens/costs are absent entirely.

Issue **#273** was opened from that finding and fixes the contract, the
unknown-stays-unknown rule, the acceptance discriminator, and the
out-of-scope list. This plan implements #273 and nothing else.

The ordering was deliberate: the audit landed on master **before** any
remediation, so the repository never holds a state where the fix exists
without the durable record explaining why.

## Scope authority

The owner set the boundary twice and in the same terms — once when
directing that C30 be treated as acceptance-not-met rather than
"met via analytics", and again when authorising this increment. Both
statements name the same exclusions: no three-backend chain, no
generalized session-analytics work, no provider-pricing enhancements,
no #268.

The owner also fixed the record shape and the governing rule (unknown
must remain unknown; explicit `unavailable`/`unpriced` is accurate
recording, a fabricated figure is not). Those are reproduced in
`spec.md` as FR-G1/FR-G2 and in `#273`, so they are checkable rather
than remembered.

## Two things this increment deliberately does NOT do

**It does not count the cost cap as usage.** The driver's cost-cap and
unmetered-estimate accounting is budget control, not observation. The
audit explicitly refused to let it satisfy C30 by implication, so
reading it here would re-introduce the very thing the audit rejected.
Recorded as plan decision D3, a named prohibition rather than an
omission.

**It does not add a second price table.** The existing pricing contract
already has the right semantics — per-1M rates, `effective_date` as the
price version, NULL never 0 for unknown or unpriced models. G reads
that configured table. Duplicating rates into the routing shell would
create a second source of truth and violate the repo rule against
hard-coded structured data.

## Deviation from the parent

None identified. C30's wording is a recording requirement, and this
increment records — including recording absence explicitly. Where a
backend genuinely cannot expose a quantity, an explicit
`unavailable`/`unpriced` is the accurate record; that reading was set
by the owner and is not a narrowing invented here.

## Appended after six review rounds

The pre-build capture above is unchanged. What follows is what the
build actually taught, recorded because the pattern is the finding.

**The first implementation had every required field and was still
wrong.** It turned unverified evidence into authoritative accounting in
six distinct ways: byte-grepping any event, zero-filling absent token
buckets, bypassing the validated price table, pricing an unverified
model, scraping a console log for accounting, and a runtime invariant
loose enough to accept a non-integer token count. Field presence was
never the contract; provenance was.

**Closing that hole opened new ones.** Adding an evidence CHANNEL
created fresh ways for unverified data to become authoritative — a
parser that differed from the shipped ones, an aggregate that reported
one session as a whole run, a publisher that silently dropped pi, and
failures that propagated nowhere because nobody checked a return code.

**Two boundaries were secured only on the third and fourth passes.**
Unsetting an environment variable hid a path name but left the artifact
inside the child's own writable worktree at a name `started-N.json`
leaks; isolation now comes from an unpredictable location outside that
tree, promoted only after the child exits, with promotion replacing
rather than merging. And `jq -s` rejected an entire capture over one
stderr diagnostic, erasing valid usage — the reader now skips bad lines
as the shipped parsers do, without readmitting forged events.

**Several of the assistant's own tests were found not to discriminate**
— a pricing assertion that passed regardless of the code under test, a
`SCRIPT_DIR` collision that made the publisher fail for the wrong
reason, and four assertions calling a helper this suite does not define,
which therefore could never fail. Each was fixed rather than
rationalised, because an assertion that cannot fail reads as coverage
while providing none.

**A claim was narrowed rather than defended.** Staging the evidence
file under `mktemp` was described as namespace isolation. It is not:
the backend inherits `TMPDIR` and runs as the same user, so it can
write that file. Rather than argue the point or leave the assertion
names implying more, the threat model was narrowed in the code, the
spec (FR-G14), the plan (D26) and the test names themselves — what is
claimed now is that the durable artifact does not exist during the run,
its name is not in the child's environment, and promotion replaces
rather than merges. A hostile same-user child is explicitly out of
scope, because defending against it needs a capability this design
cannot provide.

**And provenance needed the stream split, not just tolerant parsing.**
Skipping unparseable lines did not restore it: stdout and stderr were
merged, so a well-formed JSON diagnostic carrying an authoritative type
overrode real evidence. Only separating the streams — as the codebase
already did for codex verdicts after #199 — actually closed it.

**That split then reintroduced the same hazard one layer over.** The
combined CLASSIFICATION view appended codex stderr unconditionally,
two lines below the comment explaining why codex stderr must never be
parsed: codex stdout alone classified `execution`, while the same
stdout plus stderr containing "rate limit" classified `rate_limited`,
so an echoed prompt could choose the routing action. The view is now
built per backend, and the legacy usage scan reads it too — which also
recovered claude and pi stderr evidence the split had silently dropped
from that scan.

Decisions D7–D28 in `plan.md` carry the per-finding detail.

## What this record does NOT claim

- The ORIGIN CAPTURE above was written before any code, which is the
  point of the gate; the "after four review rounds" section was
  appended afterwards and is labelled as such. The record has not been
  rewritten to look as though the build went straight.
- No live backend has been invoked. The token field aliases are taken
  from the shipped benchmark-runner parsers and recorded fixtures, not
  from a fresh live capture.
- Closing C30 is not the same as closing #109. A short closure audit
  must re-evaluate C30 and confirm the other 32 have not regressed
  before the epic is marked complete.
