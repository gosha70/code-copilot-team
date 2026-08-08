# Origin Alignment Check — auto-build-result-array

Date: 2026-08-08 08:37
Trigger: plan.md edited after the previous record
(`origin-alignment-2026-08-08-080527.md`) to document the review-round
runner's `CCT_REVIEW_COST_FILE` reader — the same bug class on a second
surface. Gate fired exit 4 (stale record).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/197
  (`gh issue view 197` — full body incl. reproduction, the 344-element
  array evidence, and the three offending lines 815/817/818).
- User review message on PR #198: "No PR-blocking findings for #198 …
  `scripts/review-round-runner.sh:533` still only accepts object-shaped
  `CCT_REVIEW_COST_FILE`; array-form CLI result files meter as
  unmetered. **Same bug class, different surface.**"

## Origin claim (verbatim)

> `scripts/auto-build-loop.sh` parks **successful** build sessions as
> `build_session_error`. It parses the Claude Code `-p --output-format
> json` output as a single top-level object (`jq '.subtype'`), but the
> current CLI returns a **JSON array of messages** — the result object is
> the **last element** (`.[-1]`). So `.subtype` on the array throws, the
> driver records `subtype=unknown`, and it parks a phase that actually
> succeeded. With the current CLI this blocks **every** autonomous build
> at phase 1.

Plus the user's own scope extension above, which explicitly names the
cost-file reader as the same bug class and asks for it (in contrast to
the codex template flags, which they explicitly directed to "a separate
provider-config fix" — filed as #199 and left out of this PR).

## Working claim

`session_result_obj()` slurp-normalizes the three real result shapes
(claude message ARRAY, pi JSON-LINES, legacy single object) to the last
`type=="result"` element before both session backends extract subtype,
cost, and session_id. The same normalization is folded onto the review
runner's `CCT_REVIEW_COST_FILE` reader, minus the tail fallback, because
that reader is a trust boundary where a promoted non-result document
would forge a measurement and suppress the driver's conservative
estimate. Both mocks now emit their real documented shapes.

## Mismatches

- none.

The cost-file surface is not scope creep: the user named it in their PR
review as the same bug class and did not route it to a separate issue,
unlike the codex flags (#199). The two P3s fixed here are on that same
line — the reviewer proved the multi-cost-document case blanks the cost
state and writes a 1-byte `findings-round-N.json`; the regression added
here shows it driving the driver to exit 6, so this is squarely inside
#197's "the driver mishandles real CLI result shapes" claim, not beyond
it.

## Verdict

Verdict: aligned
Confidence: high
