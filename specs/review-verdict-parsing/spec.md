# Spec: review verdict parsing (#200)

## Requirements

- **FR-1**: The round runner MUST derive the verdict from the LAST
  `^### Verdict` block in the provider's captured output, not the first.
  A request echoed back by the provider contains its own `### Verdict`
  section, and it always precedes the review.

- **FR-2**: When the captured output contains no `^### Verdict` block, the
  verdict MUST be `INCONCLUSIVE`. Matching the bare words `PASS` or `FAIL`
  anywhere in the output is not permitted as a fallback.

- **FR-3**: A `FINDING|` line whose severity field is a literal angle-
  bracket placeholder (for example `<severity>`) MUST NOT be recorded as
  a finding. Findings whose severity is unrecognised but not a
  placeholder MUST still be recorded, so that a misspelled severity is
  never silently discarded.

- **FR-4**: Findings sharing a computed finding id MUST be recorded once.
  A provider that echoes its output emits each real finding twice.

- **FR-5**: The peer-review runner MUST request an explicit `### Verdict`
  section and MUST parse it under FR-1 and FR-2. Its artifact is consumed
  by the driver's hard gate, so it MUST NOT resolve a verdict by matching
  a bare word.

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
