---
spec_mode: lightweight
feature_id: review-verdict-parsing
risk_category: feature
justification: |
  Bug fix (#200) to the review gate's own verdict parsing. Classified up
  from `none` per the spec-workflow "when in doubt, escalate" rule: the
  defect lets a provider's echoed prompt be parsed as the review, which
  can turn a FAIL into a PASS on a gating path, and the fix deliberately
  changes gate behaviour (fail-closed when no verdict anchor is present)
  plus a prompt contract. That warrants stated requirements and
  constraints rather than a plan-only change.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/200
  origin_claim: |
    Bug #200: "review runner parses a provider's echoed prompt as the
    review (forged PASS + phantom finding)". The runner extracts the
    verdict from the FIRST `^### Verdict` block and treats ANY
    `^FINDING|` line as a finding; providers are captured with
    `bash -c "$cmd" 2>&1`, so a CLI that echoes its prompt to stderr
    gets its own instructions parsed as the review. Scope named in the
    issue: anchor the verdict on the LAST `^### Verdict` block; ignore
    FINDING lines whose fields are literal template placeholders;
    reconsider the bare `grep -qi "PASS"` fallback.
---

# Plan: stop parsing the request as the review (#200)

## Corrected severity — read this before the diff

The issue (which I filed) claimed the codex capture showed a FAIL parsed
as PASS end-to-end. Replaying the **full** pipeline against that captured
stream shows the final verdict was **FAIL**, not PASS: the echoed stderr
also carried real `blocking` findings, and

```sh
if [[ "$BLOCKING_COUNT" -gt 0 && "$VERDICT" == "PASS" ]]; then VERDICT="FAIL"; fi
```

overrode it. That override is a genuine safety net and the issue
understated it.

The defect is still real, with a narrower trigger. The override only fires
when a **blocking**-severity finding is parsed, so the forged PASS
survives whenever the review fails on non-blocking grounds. Deterministic
reproduction (`tests/test-review-loop.sh`):

```
model's actual verdict : FAIL   (two findings: warning + note)
blocking findings      : 0      (no override available)
FINAL parsed verdict   : PASS
phantom findings       : 1
```

A review that fails on maintainability grounds — no `blocking` severity —
is reported to the driver as PASS, and the driver hard-gates on
`verdict == "PASS"`.

## Changes

1. **Anchor on the LAST verdict block** (`scripts/review-round-runner.sh`).
   The request itself contains a `### Verdict` section, so when it is
   echoed back it is always the first one. The review's own verdict is
   always last.
2. **Reject placeholder findings.** A `FINDING|` line whose severity is a
   literal `<...>` placeholder is the echoed format line, not a finding.
   Deliberately narrow: filtering on an *allow-list* of severities would
   also silently drop real findings whose severity is merely misspelled,
   which is a worse failure for a review gate.
3. **Deduplicate findings by id.** A prompt-echoing provider yields each
   real finding twice (stdout plus the stderr copy). Identical ids
   otherwise appear as separate array entries and are counted twice,
   including in `BLOCKING_COUNT`.
4. **Fail closed when there is no anchor.** The bare `grep -qi "PASS"`
   fallback matched the word anywhere — "the tests pass", "password", or
   the echoed instruction line. Absent a verdict section the round is now
   INCONCLUSIVE. This cannot weaken a gate: the driver already treats
   every non-PASS verdict as a hard gate failure.
5. **Same defect, sibling script** (`scripts/peer-review-runner.sh`).
   It had *only* the loose fallback — no anchor at all — and its own
   prompt contains the literal string "A verdict: PASS, FAIL, or
   INCONCLUSIVE", so a prompt-echoing provider verdicts PASS
   unconditionally. Its artifact (`collaboration/build-review.md`) is
   consumed by the driver's hard gate. Its prompt now requires a
   `### Verdict` section and its parsing matches the round runner's.
   Fixing only the script named in the issue would have left the weaker
   copy of the same bug on a gating path.

## Constraint

No change to what a compliant reviewer must produce for
`review-round-runner.sh`: the request already specifies
`### Verdict` and the `FINDING|` line format. Only `peer-review-runner.sh`
gains a required section, because it previously specified none.
