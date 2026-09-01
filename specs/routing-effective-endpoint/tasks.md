# Tasks: effective upstream endpoint evidence

`spec_mode: lightweight` does not require this file. It exists because
the review needs to see the implementation broken into checkable units
before any of it is written, and because T1 is a gate rather than a
code change.

Order is load-bearing: **the contract is amended before anything
records against it**, and **provenance is proven before codex
resolution uses it**.

---

## T1 — amend #109 (DONE, before implementation)

Supersede C30's endpoint component and the §11 clause, preserving the
originals struck through, with the reason recorded: the requirement is
unimplementable within this architecture without cooperation from
systems CCT does not control.

**Done when:** the amendment is live on #109, the criteria count is
unchanged at 33, and the amendment states that the final audit
concludes 33/33 *against the amended contract* — never that the
original requirement became met.

**Status:** complete. #109 shows the struck §11 clause, the amended
C30 line, and the amendment section.

---

> **This file is a navigation layer.** The contract — the closed
> provenance vocabulary, the closed `effective_upstream` state machine,
> the codex resolution order — is defined once in `spec.md`. Tasks
> point at the requirements they satisfy and name what makes each one
> *done*; they do not restate the enums, because a second copy is a
> second thing to drift.

## T2 — the verification-state contract

**Implements:** FR-E7 (the two new fields and the closed
`effective_upstream` state machine), FR-E9 (a configured value is never
observed).

Add `upstream_origin_source` and `effective_upstream` to the normalized
routed result. Schema additive and optional for compatibility;
completeness enforced at the runtime boundary, exactly as increments F
and G did.

**Done when** the five named mutations in `plan.md` fail, and the four
state-machine mutations E7-M1…E7-M4 each fail **for their own distinct
reason** — a single shape check catching all four does not satisfy this
task. Verified with caches cleared and `ERROR:` checked as well as
`FAIL:`.

**Status: complete.** `rr_upstream_invariant`
(`scripts/lib/routing-result.sh`) enforces the state machine with a
distinct exit code per rule; `rr_doc_invariant` delegates to it, so the
refusal is at the production boundary rather than in a test-only
predicate. 34 assertions in `tests/test-routing-config.sh` (pin 294 →
330). Twelve mutations were run; each was caught, and two produced
findings rather than confirmations:

- copying the configured origin into `effective_upstream.origin`
  **aborted the suite** instead of failing an assertion — `set -e` plus
  a bare `DOC=$(rr_result …)` assignment. The abort surfaced only as a
  count drift, and every later assertion silently never ran. Both
  capture sites now use `|| true` with an explicit
  composition-succeeds assertion.
- a duplicate `has("effective_upstream")` in `rr_doc_invariant`'s jq
  predicate proved **unreachable** — `rr_upstream_invariant` already
  checks presence. Removed rather than left as a second definition.

`upstream_origin_source` is validated WHEN PRESENT (closed vocabulary
plus the pairing rule); `rr_result` OMITS it when the caller passed no
classification, because `none` is a positive claim that no origin
exists. T3 supplies it at every producer and makes presence mandatory.

**T2 correction pass (review):** the runtime boundary was less closed
than the schema it claims to enforce, in two places — and `rr_result`
never runs JSON Schema, so this predicate IS the enforcement.

- `has("origin") and has("status") and has("evidence")` accepted a
  FOURTH key. Beside a closed state machine that is a private channel
  carrying a claim the contract refused to make. Now
  `(keys | sort) == ["evidence","origin","status"]`.
- Reading provenance as `.upstream_origin_source // ""` then testing
  `-n` made an explicit `null` and `""` indistinguishable from
  omission, so both skipped validation despite being outside the FR-E8
  vocabulary. Presence is now tested with `has(...)`, and anything
  present is validated.

Two further findings from mutation-testing the correction itself:

- the `case " $V " in *" $src "*)` membership idiom was NOT the glob
  bypass this correction first claimed — a quoted expansion inside a
  case pattern is literal. The literal-comparison loop is kept for
  legibility, not as a security fix, and the comment says so.
- a `type == "string"` guard added beside the vocabulary check proved
  unable to change any outcome (a null renders as `"null"`, which the
  vocabulary refuses anyway). Removed, on the same rule as the
  unreachable presence check found earlier.

---

## T3 — provenance for the existing configured origin

**Implements:** FR-E8 (the provenance table), FR-E11 (login mode).

Classify what #277 already resolves, assigning each path its FR-E8
value. The load-bearing line is FR-E8's rule that `backend_default`
requires an *establishable* default.

**Done when** a login-mode profile records `upstream_origin: null` /
`upstream_origin_source: none` per FR-E11, and a test asserts that
distinction rather than accepting `backend_default` as an alternative.

**Status: complete.** `rt_launch_env` binds
`RT_UPSTREAM_ORIGIN_SOURCE` beside the origin and all three
`rr_result` producers pass it. Two decisions worth stating:

- **Provenance follows the RESOLVED origin, not the reference form.**
  A `urlenv:` whose variable is unset or holds an unusable value
  learns nothing, so it records `none` — naming
  `profile_base_url_env` there would attribute a source to a fact that
  was never established.
- **`backend_default` is produced by no path.** Login mode records
  `none`; a test greps that no assignment of `backend_default` exists,
  so the value stays reserved for a default CCT can positively
  establish rather than becoming the habitual answer for "unknown".

The T2 compatibility window is CLOSED: `rr_upstream_invariant` now
refuses an absent provenance (11), kept distinct from present-but-
invalid (9) so a producer that forgot to classify is not reported as
one that classified wrongly. `rr_result` derives `none` for an
unclassified caller ONLY when there is no origin — that value is
ENTAILED by the pairing invariant rather than assumed — and REFUSES an
unclassified non-null origin.

Codex still records `none` here; T4 owns `codex_model_provider`, and a
test pins that no assignment of it exists yet.

Six mutations, each caught: swapped literal/env values; classify from
the reference form ignoring resolution; login mode assuming
`backend_default`; one producer dropping the argument; `rr_result`
defaulting an unclassified origin; the boundary reopening the window.

---

## T4 — codex configured-origin resolution (the risky one)

**Implements:** FR-E10 (codex resolves its configured origin), FR-E12
(resolution follows codex's ACTUAL selection), FR-E13 (no raw backend
configuration becomes evidence).

Resolve the `base_url` of the provider codex actually selected, in
FR-E12's order. The hazard FR-E12 exists to block: `_resolve_codex_config`
picks **the first key under `[model_providers]`** — arbitrary dict
order — while the supervisor passes `-c model_provider=<id>`
(`cooldown-supervisor.sh:1498, 1915`). This task must not reuse that
selection.

**Done when**

- provider A selected with provider B also in config → the recorded
  origin is A's, and a mutation that picks the first key fails;
- an override was issued but its provider is absent → `none`, NOT the
  top-level default (FR-E12 step 2's precondition);
- resolution raises `upstream_origin` only — `effective_upstream` is
  untouched and stays in the `unverifiable` state;
- a credential, path or query in the codex `base_url` is stripped by
  #277's sanitizer and a non-http(s) scheme is refused;
- an undeterminable provider records `none`, not a guess.

---

## T5 — short C30 re-audit

Separate PR, docs-only, after T2–T4 land. Verifies the **amended**
criterion and records why the original was superseded. Confirms the
other 32 have not regressed against the bounded diff.

Only this audit can make #109 33/33, and only against the amended
contract.

---

## Out of scope

#268; the Claude Code → DeepSeek → Codex chain; any routing-policy
change; any traffic-interception layer (O2 was rejected as
architecturally insufficient, not merely expensive).
