# Origin Alignment Check — findings-file-argmax

Date: 2026-08-08 16:20
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/209 (root
  cause with line references, the real-run artifact sizes, the proposed
  five-part fix, and four acceptance criteria).
- The user's instruction: "pick this bug first: …/issues/209".

## Origin claim (verbatim)

> `review-round-runner.sh` builds `findings-round-N.json` by passing the
> reviewer's **entire raw output** as a `jq --arg`. When the reviewer is
> verbose … the argument exceeds `ARG_MAX`, jq dies with `Argument list too
> long`, and — because the jq call sits inside a heredoc command
> substitution with no exit check — **the findings file is written as an
> empty 1-byte file**.

## Acceptance criteria — status

- Large reviewer output still yields a valid findings file — **met**, with a
  test at >2MB against a 1048576 ARG_MAX.
- A failed write is loud, never silently empty — **met** (exit status
  checked, output validated, temp file moved into place only when valid).
- The driver refuses to build a fix prompt from an empty/invalid file —
  **met**.
- Regression test with a large stub reviewer plus valid FINDING lines —
  **met**, and verified to fail against master.

## Mismatches

- Items 4 and 5 of the proposed fix ("consider" items) are deliberately not
  done; the plan states why.
- **Test honesty note:** the first version of the regression used ~700KB of
  output and passed against master — i.e. it did not reproduce the bug at
  all. It was raised past this host's ARG_MAX (1048576) and re-verified to
  fail against master before being kept.
- The driver-side guard is exercised by testing its exact condition against
  empty/missing/malformed/array/valid artifacts plus a static ordering check,
  rather than end-to-end: the corruption occurs between the runner writing
  the file and the driver reading it, and there is no seam between those two
  steps to inject at without adding production test surface. Stated plainly
  rather than implied.

## Verdict

Verdict: aligned
Confidence: high
