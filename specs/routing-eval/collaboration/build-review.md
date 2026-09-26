---
feature_id: routing-eval
date: 2026-09-25
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: fix/routing-packet-verifier-tests
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: routing-eval — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The change corrects a real defect: production routing selected verifiers by `kind == "test"`, but the schema's closed vocabulary is `deterministic | runtime_conformance | visual`, so `test` is a field name, not a kind. The fix is applied consistently across `routing-packet.sh`, `routing-tasks.sh`, the supervisor generator, and the test fixtures, and the new T2.8 test correctly pins the "only deterministic becomes a command" invariant. The retirement of `TestNoProductionRoutingFileTouched` is well-reasoned and documented, though the removal of a guard that was the executable proof of decision 10 deserves a closer look at whether any residual protection is lost.

## Findings

- [note] f-4fb14ba0: The awk filter now matches `$3 == "deterministic"` exactly, which is correct, but the surrounding code does not validate that the `test:` field is non-empty for a deterministic verifier. A malformed artifact with `kind: deterministic` and no `test:` would emit an empty string into `tests_json`, producing a packet with an empty command that the driver would attempt to execute. (scripts/lib/routing-packet.sh)
- [note] f-82665c60: Same shape as above: `hastest[$2] = 1` is set for any `deterministic` row regardless of whether `test:` is present. A deterministic verifier with an empty `test` would satisfy the binding requirement while providing no executable check. (scripts/lib/routing-tasks.sh)
- [warning] f-30c92adc: The retired guard was the executable proof of plan.md decision 10 ("E1 adds no runtime authority"). The replacement safeguards listed in the plan note (seam contract, classification parity, supervisor integration) assert *behaviour* but not the *diff-level* property that production routing files were untouched. If a future change to `scripts/lib/routing-*` silently altered routing semantics, no test in this feature would catch it — the supervisor integration test only exercises the happy path through the generated packet. (scripts/benchmark_runner/tests/test_routing_eval_injection.py)
- [note] f-50ab06bb: The note is thorough and honest, but it does not state what *replaces* the guard's coverage of decision 10 at the diff level. A reader could reasonably conclude decision 10 is now unverified rather than verified by other means. (specs/routing-eval/plan.md)
- [note] f-1cb6d6f0: The new test asserts that judged criteria do not appear in the packet, but it does not assert the negative case for the *old* bug: a verifier with `kind: test` (the non-schema string) should now be excluded. Without that assertion, a regression that re-introduces `test` as a matched kind would not be caught by this test. (tests/test-routing-packet.sh)
- [note] f-9045e5d2: The generator now emits `kind: deterministic`, matching the schema. Consider adding a comment in the template string (or a nearby constant) noting that this string must match `shared/schemas/verification.schema.json`'s enum, so a future schema change is caught at the generator rather than at packet-build time. (scripts/benchmark_runner/routing_eval/supervisor_runner.py)
- [note] f-883d6c81: The section reports test counts but does not name the specific test that would fail if the kind correction were reverted (the plan note does, but the alignment record does not). Cross-referencing would make the record self-contained. (specs/routing-eval/origin-alignment-2026-09-25-2133.md)
