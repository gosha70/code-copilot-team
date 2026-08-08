# Origin alignment check — auto-build-admission

- date: 2026-08-08
- trigger: initial gate for the #193 SDD bundle (pre-plan-PR). Origin
  sources read in full this session: issue #193 body (authored verbatim
  from the umbrella's increment plan), umbrella #190 body (§2 caps, §3
  evidence graph, §4 escalation table, §11 admission bar, Additional
  Context increment definitions), and the increment-A preconditions
  recorded in specs/auto-build-unattended-core/spec.md.

## Origin claim (from plan.md `origin:`)

"B — traceability + admission. verification.yaml schema, draft
generator, statement_sha binding, verifier-coverage enforcement,
validate-spec.sh --unattended. Gate on this before any run lands." Plus
#190 §3: draft → author finalizes → admission validates; admission
never authors; spec.md is the only authoritative requirement text,
every hash recomputed, any mismatch fails; every FR-N ≥1 executable
verifier. Plus §11's machine-checkable bar. Plus the two recorded
A-preconditions: out-of-band cost channel; honest finalize under gh
capability downgrade.

## Working claim (from spec.md)

B delivers the verification.yaml artifact (schema + canonical
normalizer + deterministic draft generator with author finalization),
the `validate-spec.sh --unattended` admission bar implementing the
B-decidable §11 checks (coverage, sha binding, executable resolution,
runtime_conformance inadmissible until C's evaluator exists, phrasing
lint, test.command on base ref, explicit caps, approved plan + origin
gate) with C-owned items surfaced as DEFERRED, replaces the A test seam
with real admission (admitted unattended runs execute for the first
time; refused runs exit 1 un-admitted), moves review-cost measurement
to the model-unwritable CCT_REVIEW_COST_FILE channel (in-band envelope
acceptance removed), and makes downgraded finalize honest.

## Mismatches

none — scope boundaries drawn exactly at the umbrella's own increment
lines: verifier EXECUTION at finalize (§3 "landed requires every mapped
verifier green") assigned to C's verification contract per the umbrella
("C — verification contract... runtime conformance evaluator");
`runtime_conformance` mappings inadmissible in B is the umbrella's own
rule ("a verifier something depends on cannot be switched off") applied
honestly while the evaluator does not exist.

Verdict: aligned
Confidence: high
