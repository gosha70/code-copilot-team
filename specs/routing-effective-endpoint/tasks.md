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

---

## T3 — provenance for the existing configured origin

**Implements:** FR-E8 (the provenance table), FR-E11 (login mode).

Classify what #277 already resolves, assigning each path its FR-E8
value. The load-bearing line is FR-E8's rule that `backend_default`
requires an *establishable* default.

**Done when** a login-mode profile records `upstream_origin: null` /
`upstream_origin_source: none` per FR-E11, and a test asserts that
distinction rather than accepting `backend_default` as an alternative.

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
