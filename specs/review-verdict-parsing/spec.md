# Spec: review verdict parsing (#200)

## Requirements

- **FR-1**: A verdict MUST be a bare `PASS`, `FAIL`, or `INCONCLUSIVE` on
  its own line, following a line that holds only the heading
  `### Verdict`. Any other content after the heading — prose, a sentence
  listing the options, a placeholder — ends that block WITHOUT yielding a
  verdict.

- **FR-1a**: The review REQUEST MUST NOT contain text matching FR-1. It
  describes the shape in prose instead. Position-based rules are
  forbidden: the capture merges stderr via `2>&1`, so an echoed request
  can land before, after, or interleaved with the answer. A request that
  is parseable at all is a forged verdict waiting for buffering to
  change. Verified by a regression in which the provider echoes the real
  request verbatim and the result is INCONCLUSIVE.

- **FR-1b**: Both runners MUST use ONE implementation of FR-1
  (`scripts/lib/review-verdict.sh`). Two copies of this logic is what let
  the runners drift into different failure modes.

- **FR-2**: When the captured output contains no block satisfying FR-1,
  the verdict MUST be `INCONCLUSIVE`. Matching the bare words `PASS` or
  `FAIL` anywhere in the output is not permitted as a fallback.

- **FR-3**: A `FINDING|` line whose severity field is a literal angle-
  bracket placeholder (for example `<severity>`) MUST NOT be recorded as
  a finding. Findings whose severity is unrecognised but not a
  placeholder MUST still be recorded, so that a misspelled severity is
  never silently discarded.

- **FR-4**: Findings sharing a computed finding id MUST be recorded once.
  A provider that echoes its output emits each real finding twice.

- **FR-5**: The peer-review runner MUST request an explicit `### Verdict`
  section and MUST parse it under FR-1, FR-1a, FR-1b and FR-2. Its
  artifact is consumed by the driver's hard gate, so it MUST NOT resolve
  a verdict by matching a bare word.

- **FR-6**: The existing blocking-severity override
  (`BLOCKING_COUNT > 0 && VERDICT == PASS` ⇒ `FAIL`) MUST be preserved.
  It is the safety net that limited this defect's blast radius, and it
  stays as defence in depth.

## Constraints — what NOT to build

- Do NOT change what a compliant reviewer must emit for
  `review-round-runner.sh`. The `### Verdict` section and the `FINDING|`
  format are already specified in its request; this is a parsing fix.
- Do NOT filter findings against an allow-list of severities or
  categories. A review gate that silently drops a real finding because
  its severity was misspelled fails in a worse direction than one that
  records it with an odd severity.
- Do NOT suppress provider stderr generally. Whether a given provider's
  stderr belongs in the parsed stream is provider configuration (see
  #199); this change makes the parser correct regardless.
- Do NOT alter the driver's gate semantics. `INCONCLUSIVE` already fails
  the hard gate; no driver change is required or wanted.
