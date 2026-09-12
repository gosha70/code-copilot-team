---
feature_id: auto-build-resume-terminated
date: 2026-09-11
phase: build
mode: review
peer_provider: deepseek
reviewed_ref: 2c48fd5
verdict: FAIL
blocking_findings_open: 0
invocation_cost_usd: 0.004917899999999999
---

# Build review — round 1 (DeepSeek, verbatim findings)

The runner writes its own artifact only on PASS; this file keeps the FAIL round's findings as the reviewer returned them.

## [warning] correctness — scripts/auto-build-loop.sh

`git rev-parse --verify -q "$BRANCH_NAME"` is run with `-C "$PROJECT_DIR"`, but `BRANCH_NAME` may be a local branch that only exists in the project's worktree; if the branch was checked out elsewhere or the ref is ambiguous, `rev-parse` can resolve a different ref than the one the phase committed to. More importantly, the comparison `[[ "$head" != "$last_commit" ]]` is a raw string compare — if `last_commit` was recorded as a short SHA (or with different case) it will spuriously refuse. Normalize both via `git rev-parse` before comparing.

**Suggested fix:** Resolve both sides through `git -C "$PROJECT_DIR" rev-parse --verify -q "$last_commit"` and compare the full SHAs, or use `git merge-base --is-ancestor`/`rev-parse` equality on canonicalized values.

## [warning] correctness — scripts/auto-build-loop.sh

The ancestor check is skipped entirely when `branch_base_ref` is empty (`if [[ -n "$base" ]] && ! ...`). An empty base means the frozen contract has no recorded base, so the "frozen base is its ancestor" invariant from FR-1 is silently not enforced. If a run can legitimately have an empty `branch_base_ref`, the resume should still be refused (or the spec should say the check is vacuous).

**Suggested fix:** Either refuse when `base` is empty, or document explicitly in FR-1 that an empty base makes the ancestor check vacuous and add a test for that case.

## [warning] correctness — scripts/auto-build-loop.sh

`terminated_resumable` is evaluated in step 0 and its result is discarded (only the exit code is used). Between step 0 and step 7 the driver runs branch binding, prerequisites and preflight — which can mutate state (e.g. re-checkout the branch, run the probe, write admission records). If any of those steps change the branch head or the phase's commit (e.g. a rebase in preflight, or a checkout that moves HEAD), the step-7 `resume_terminated` will proceed on stale assumptions. The comment "Step 0 already decided this run is resumable" is only true if nothing between the two steps invalidates the decision.

**Suggested fix:** Re-run `terminated_resumable` (or at least the head/base checks) immediately before `resume_terminated`, or assert the invariants again inside `resume_terminated`.

## [warning] correctness — scripts/auto-build-loop.sh

`mv "$PROJECT_DIR/.cct/review" "$_stale"` will fail (and, under `set -e` if active, abort the resume) if `$_stale` already exists — e.g. two resumes within the same second, or a leftover directory from a prior crashed resume. The `stamp` is `now_epoch`, which has one-second resolution.

**Suggested fix:** Use `mktemp -d` for the stale target, or append a counter/PID, or check for existence and pick a unique suffix.

## [warning] correctness — scripts/auto-build-loop.sh

`state_set '.status = "resumed" 

**Suggested fix:**  .outcome = null | .disposition_reason = null | .updated = $t'` sets `status` to `"resumed"`, but the rest of the driver's state machine (and the step-0 dispatch) keys off `status` values like `terminated_policy`, `parked`, `done`. If any downstream code branches on `status == "terminated_policy"` to decide behavior, setting it to `"resumed"` before the review step runs could skip termination handling on a second failure. Verify the state machine treats `"resumed"` as an in-progress status and that a re-termination during the resumed review writes `terminated_policy` again.|Confirm the status enum and that `run_phase`/termination paths accept `"resumed"`; add a test that a resumed run which terminates again ends with `status: terminated_policy` and a fresh `termination.json`.

## [note] correctness — scripts/auto-build-loop.sh

`history=$(jq -c '.history // null' "$LEDGER_DIR/termination.json" 2>/dev/null 

**Suggested fix:** | echo null)` — if `termination.json` is missing or malformed, `history` becomes `null` and `escalation_resumable` is called with `null`. Whether that refuses or allows depends on `escalation_resumable`'s handling of `null`; the spec says "a contract that froze no evaluator cannot gain one", implying `null` history should refuse. Make the intent explicit.|If `termination.json` is absent, refuse with a clear message rather than passing `null` to `escalation_resumable`.

## [note] testing — tests/test-auto-build-loop.sh

`assert_eq "D2: costs accumulate … (2 probes + 2 rounds)" "8"` hard-codes a dollar figure derived from the mock profile's pricing. If the mock pricing or the probe/round cost model changes, this test breaks for reasons unrelated to D2. It also doesn't verify the *accumulation* semantics (that the cap is shared) — only the total.

**Suggested fix:** Consider asserting the total equals the sum of the two runs' recorded costs, or add a separate assertion that the cap counter is not reset on resume.

## [note] documentation — README.md

The README says "the frozen base is its ancestor" but does not mention the empty-`branch_base_ref` case, nor that the check is skipped when the base is unset. Align the doc with the actual guard.

**Suggested fix:** Add a sentence noting the behavior when no base is recorded, or tighten the guard so the doc is accurate.

## [note] design — scripts/auto-build-loop.sh

The `case "$reason"` in `triage_report` lists `provider_unavailable

**Suggested fix:** review_breaker` as resumable, but `terminated_resumable` additionally requires the head/base/history conditions. A user reading the triage report for a `provider_unavailable` termination whose branch has since moved will be told it is resumable, then refused at `--resume`. The report is a hint, not a guarantee, but the wording ("This reason is resumable at the review step") overstates it.|Soften the wording to "may be resumable if the build commit is still the branch head" or have `triage_report` call `terminated_resumable` to give an accurate answer.

