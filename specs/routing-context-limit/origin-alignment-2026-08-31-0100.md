# Origin alignment — routing-context-limit (Increment F of #109)

Verdict: aligned
Confidence: high

Refreshed after the build, so it post-dates the final `plan.md`. The
pre-build capture is preserved below unchanged; the build-time findings
are appended rather than rewritten over it.

## Origin capture

The work is named by #109 itself in four places:

- the acceptance criterion "The actual upstream endpoint/context limit
  is recorded and enforced" — the last of 31 still unmet;
- §5 step 4, "Filter profiles lacking required context, tool, modality,
  or protocol capabilities";
- §11 telemetry, "Actual server context limit and prompt-size decision";
- §Risks, "Context overflow: mitigated by enforcing the actual upstream
  limit rather than the client-advertised limit".

The scoping evidence is `specs/routing-profile-foundation/audit-2026-08-30.md`
(merged in #271), which established that 29 of 31 criteria are met and
that this criterion is met only in its reactive third — the
`invalid_request` → attempt-local-incompatible → failover path — with
the recording and proactive-enforcement thirds absent.

## Scope authority

The owner chose this scope explicitly, after being presented with three
bounded options (record-only; record + declared-limit filtering; record
+ enforce the observed limit). The owner initially selected the second,
then reversed to the third before any code was written, on the grounds
that declared-only filtering does not satisfy the criterion: a profile
declaring 200000 but observed at 32768 would stay eligible for a
150000-token task. Eight bounding rules were fixed at the same time and
are reproduced verbatim in `plan.md` under "Owner-fixed rules".

The owner also reversed one drafted decision: the assistant had drafted
fail-OPEN for a profile with no known limit (absence is not evidence of
smallness); the owner set fail-CLOSED (capacity is unproven). The
owner's rule is adopted and recorded as decision D3, with the reason it
is safe — the fail-closed branch engages only once a task states a
requirement, so it cannot retroactively strand an existing
configuration.

## Deviation from the parent constraint

#109 §Risks asks for enforcement of the actual limit "rather than the
client-advertised limit". F enforces `min(declared, observed)`: the
actual limit once one has been observed, the advertised limit before
that. This is a genuine narrowing, forced by observability — no CLI
backend reports its served context window on a healthy run, so the
actual limit appears only inside an overflow error. The first overflow
on any new execution identity is therefore always caught reactively by
the already-built path; only later selections enforce proactively.

Recorded in `plan.md` under "Deviation from the parent, recorded not
glossed".

## Correctness note carried into the plan

An overflow message is emitted while FAILING. It proves an upper bound,
not a capacity. The plan pins this as decision D2 with a five-row
table, because the naive implementation — treating a bare observation
as the effective limit — would let a failure promote an undeclared
profile into eligibility.

## Appended after the build

**Two wiring decisions were forced by contracts the plan had not yet
inspected**, and are recorded in `plan.md` as W1 and W2:

- **W1** — the task requirement is read from `routing-tasks.yaml`, not
  the packet envelope. The envelope belongs architecturally, but
  `RP_ENVELOPE_KEYS` is frozen and digest-bound; adding a key would
  invalidate every existing packet digest. The read happens
  immediately after `rp_provenance_check` verifies
  `routing_tasks_sha256` against that exact file, so the bytes are
  proven identical to those the packet was built from.
- **W2** — the filter is wired to the delegate path only, not
  reconcile. Enforcing a builder's minimum against reviewer profiles
  would strand `verified_provisional` work behind reviewers that merely
  lack a declaration. Mutating the code to filter reconcile anyway
  produced 18 delegation-suite failures, which is empirical support for
  the reasoning rather than assertion.

**A real gap was caught by tracing the execution path, not by the
tests.** The library-level filter was complete, tested and
mutation-proven while every delegate selection still called `rt_select`
with four arguments — so nothing would have enforced anything in
production, and the acceptance criterion would have been claimed on a
green suite. The wiring and its three structural pins exist because of
that trace.

## Appended after the contract review (round 2)

A contract-level review raised eight findings; all were reproduced
before being fixed and are recorded as decisions D7–D14 in `plan.md`.
Two are worth surfacing here because they change what the record
claims:

**A stated piece of evidence was withdrawn, not rationalized.** The
first version of W2 justified exempting reconciliation from the
context filter by citing 18 delegation-suite failures produced by
mutating the code to filter it. Those failures were an unbound-variable
crash under `set -euo pipefail` (`PKT_MINCTX` was never initialized on
the reconcile path), not a semantic signal. A shell crash had been read
as a design finding. The variable is now initialized globally,
reconcile IS filtered per the owner's ruling and FR-F3, and the
invalid inference is struck from the plan rather than softened.

**A test in this increment's own suite was found tautological.** The
malformed-observation-store assertion passed under mutation for the
wrong reason: a non-numeric fixture value blew up in bash arithmetic
before the validation boundary got control, so the right exit status
arrived from the wrong cause. The fixture was changed to a
structurally valid store whose record simply lacks its integer cap, and
the assertion now binds exit status to the guard's own diagnostic.
Under mutation it degrades to "absent", the declared limit governs, and
the profile is selected — the widening proven directly, with no
arithmetic, `set -u`, or parser failure involved.

Nine targeted mutations each discriminate at a named assertion:
malformed-store fail-open; env-name instead of resolved endpoint;
recovery re-resolving live config; telemetry reporting the configured
rather than enforced limit; broad numeric extraction; single-digit
exclusion; the task helper bypassed; reconcile propagation removed; and
the result version boundary removed.

## What this record does NOT claim

- No live backend was invoked for this increment. The observed limit's
  extractability rests on the recorded `vllm-context-overflow` capture
  already in the fixture corpus, not a fresh live run.
- No end-to-end delegation run was executed against a profile whose
  provider actually enforced a smaller window than declared. The
  narrowing path is proven at library level and by mutation, not by
  observing a real provider contradict a real registry.
