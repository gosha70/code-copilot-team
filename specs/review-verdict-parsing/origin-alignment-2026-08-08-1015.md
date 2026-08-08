# Origin Alignment Check — review-verdict-parsing

Date: 2026-08-08 10:15
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/200
  (`gh issue view 200` — full body, including the three named remedies).
- The user's instruction opening this work: "Fix the bug
  https://github.com/gosha70/code-copilot-team/issues/200".
- The #199 review agent's report, which independently reproduced the
  defect end-to-end and supplied two details the issue lacked (the
  blocking-count override masking, and the `jq --argjson` exit-2 crash).

## Origin claim (verbatim)

> `scripts/review-round-runner.sh` extracts the verdict from the **first**
> `^### Verdict` block in the provider's captured output, and treats
> **any** `^FINDING|` line as a finding. Providers are captured with
> `bash -c "$RESOLVED_CMD" 2>&1`, so any CLI that echoes its prompt to
> stderr gets its own instructions parsed as the review. … This issue is
> the shared-parser hardening that protects every current and future
> prompt-echoing `cli` provider: anchor the verdict on the **last**
> `^### Verdict` block, not the first; ignore `FINDING|` lines whose
> fields are the literal template placeholders; reconsider the bare
> `grep -qi "PASS"` fallback.

## Working claim

All three named remedies are implemented in
`scripts/review-round-runner.sh`, plus finding deduplication (the echo
duplicates every real finding, which crashed the runner). The same
defect class is fixed in `scripts/peer-review-runner.sh`, which had only
the bare-word fallback and whose artifact feeds the driver's hard gate.
Ten regressions in `tests/test-review-loop.sh` and two in
`tests/test-peer-review.sh`, all verified to fail against the pre-fix
scripts.

## Mismatches

- **The issue overstated the severity, and this record corrects it.**
  #200 says the codex capture showed a FAIL parsed as PASS end-to-end.
  Replaying the full pipeline shows the final verdict was FAIL: the
  echoed stderr also carried `blocking` findings, and the
  `BLOCKING_COUNT > 0 && VERDICT == PASS ⇒ FAIL` override caught it. The
  defect is real but its escape window is a review that fails on
  non-blocking grounds, which is what the regression now pins. The
  correction is recorded in `plan.md` and the CHANGELOG rather than left
  standing in the issue text.
- **`peer-review-runner.sh` is not named in the issue.** Included because
  it carries the same defect in a weaker form on a gating path; the
  standing "grep every caller / apply corrections globally" rule makes
  fixing only the named script the wrong call. Its prompt gains a
  required `### Verdict` section, which is a real behaviour change and is
  called out as such in the CHANGELOG.
- **Scope held elsewhere.** No change to the driver's gate semantics, to
  the round runner's request contract, or to provider stderr handling
  (that is #199's provider-config domain).

## Verdict

Verdict: aligned
Confidence: high
