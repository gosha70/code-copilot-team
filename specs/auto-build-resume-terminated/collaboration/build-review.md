---
feature_id: auto-build-resume-terminated
date: 2026-09-11
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feat/190-d2-resume-terminated
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: auto-build-resume-terminated — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The D2 resume feature is well-scoped and the DeepSeek round-1 findings were largely addressed in commit 43e68d1 (canonical SHAs, no-base refusal, re-check at dispatch, unique set-aside names). However, the re-check at dispatch is placed inside `resume_terminated` which runs *after* preflight, and the step-0 short-circuit still discards the reason string; more importantly, the `state_set` in `resume_terminated` sets `status: resumed` but the diff shows the state machine's step-0 dispatch keys off `status == terminated_policy` — a re-termination during the resumed review must write `terminated_policy` again, and the tests do assert this, but the ordering of `state_set` vs. `set_status` and the interaction with `run_phase`'s build-commit resume path deserve a closer look. The tests are thorough and cover the main refusal arms.

## Findings

- [warning] f-1db2ebaa: The re-check of `terminated_resumable` inside `resume_terminated` runs *after* branch binding, prerequisites and preflight (step 7), but the comment claims it guards against staleness "between admission and dispatch." Preflight can re-checkout the branch or run the probe; if preflight moves HEAD (e.g. a checkout that lands on a different ref), the re-check catches it — good — but if preflight *fails* the run terminates before the re-check, leaving `termination.json` in place with no journaled reason. More subtly, the step-0 short-circuit already ran `terminated_resumable` and discarded the reason string; if the reason changes between step 0 and step 7 (it cannot, since nothing writes `disposition_reason` in between, but this is an implicit invariant), the re-check is the only guard. Consider asserting the invariant explicitly or documenting why `disposition_reason` cannot change between step 0 and step 7. (scripts/auto-build-loop.sh)
- [warning] f-798e771e: `state_set '.outcome = null  (scripts/auto-build-loop.sh)
- [warning] f-465395f0: `unique_sibling` uses a check-then-act loop (`while [[ -e "$want" ]]`). Two concurrent `--resume` invocations on the same ledger (unlikely but possible under a supervisor) could both observe the same free name and both `mv` onto it, with the second `mv` overwriting the first. The window is small but real. The `mv` itself is atomic per-file, but the name selection is not. (scripts/auto-build-loop.sh)
- [warning] f-f41d64ff: If `current_phase` is `0` (no phase started) but the ledger has a `termination.json` with a `provider_unavailable` reason, `last_commit` will be empty and the function refuses with "phase 0 has no build commit." That is correct behavior, but the message says "phase 0" which is confusing — it should say "no phase has a build commit." Minor, but the refusal message is user-facing. (scripts/auto-build-loop.sh)
- [note] f-e4e5d6b3: The `2>/dev/null  (scripts/auto-build-loop.sh)
- [note] f-9ece2f24: `branch_base_ref` is used raw in `merge-base --is-ancestor` without canonicalization, unlike `last_commit` and `head` which are `rev-parse`'d. If `branch_base_ref` is a short SHA or a ref name that has since been deleted, `merge-base` fails and the `2>/dev/null` swallows the error, causing the `if !` to treat it as "not an ancestor" and refuse — which is the safe direction, but the refusal message says "no longer an ancestor" when the real cause may be "base ref is unresolvable." (scripts/auto-build-loop.sh)
- [note] f-8d285f31: Hard-codes the total dollar figure. The DeepSeek note flagged this; the fix did not change it. If the mock pricing or probe cost model changes, this test breaks for unrelated reasons. It also does not verify that the cap counter is shared (only the total). (tests/test-auto-build-loop.sh)
- [note] f-f891177f: The README does not mention the empty-`branch_base_ref` refusal case, which the code now handles explicitly (and the test covers). A reader could infer the check is vacuous when no base is recorded. (README.md)
- [note] f-4e4f8cfb: The wording was softened from "is resumable" to "MAY be resumable" (per the DeepSeek note), which is accurate. However, the report does not call `terminated_resumable` to give a definitive answer even though the ledger is available at report time. A user reading the report for a `provider_unavailable` termination whose branch has since moved is told "MAY be resumable" and then refused at `--resume`. This is acceptable (the report is a hint), but calling `terminated_resumable` from `triage_report` would give an accurate answer at report time. (scripts/auto-build-loop.sh)
- [note] f-f6b1a2d5: If `triage-report.md` is missing (e.g. the termination path that wrote `termination.json` did not write a triage report), the resume proceeds without preserving it. That is fine, but the journal message names only `termination-*.json` as kept, not the triage report. Minor inconsistency. (scripts/auto-build-loop.sh)
