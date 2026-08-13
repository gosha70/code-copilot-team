# Origin Alignment Check — auto-build-conformance-evaluator

Date: 2026-08-13 15:31
Trigger: rev-3 holistic correction pass on PR #243 after the owner's
round-2 review of rev 2 (`feef522`; 4 P1 + 1 P3, verdict "Request
changes").

## Origin sources read

- #190 §6 (runtime spec-conformance evaluator), §3 (landed requires
  EVERY mapped verifier green), §2 (metering).
- specs/auto-build-admission/spec.md — Increment-C handoff items 1/2/5.
- The repo's ACTUAL provider protocol (round-2 finding 2 sent me back to
  the source): `shared/templates/provider-profile-template.toml` and
  `scripts/review-round-runner.sh` — providers consume a request
  document via the `{review_request}` command-template slot, emit
  stdout, and may be explicitly read-only (`-s read-only`, `.git`
  removed from the sandbox).
- #242 and the owner's round-2 review findings (user origin input,
  2026-08-13).

## Working claim

Unchanged: C2 = #190 §6's evaluator + handoff items 1/2/5 on C1's
machinery. Rev 3 corrects the invocation mechanics and the
compatibility claim; scope is unchanged.

## Mismatches found at rev 2 — corrected in rev 3

- **The evaluator invocation contract was unimplementable (P1).** Rev 2
  specified `CCT_CONFORMANCE_*` environment variables and required the
  evaluator to write the result file. Real providers are
  prompt-in/stdout-out and may be read-only: env vars neither instruct
  a model nor produce files. Rev 3 replaces this with the reviewer
  protocol: a driver-authored request document (frozen criteria + app
  interface + Required Output Format demanding exactly one fenced JSON
  verdict block), the request-file placeholder substitution, and the
  ADAPTER extracting the block from captured stdout and writing the
  result file.
- **The byte-identical claim overclaimed (P1).** Executing deterministic
  verifiers at landing is a new gate for every finalized artifact — an
  origin-REQUIRED change (#190 §3: every mapped verifier green), not a
  compatibility violation, but rev 2 still promised "byte-identical /
  no intentional changes". Rev 3 scopes byte-identical to
  neither-input runs and names the two intentional deltas (executed
  deterministic gate, SC-8; frozen-contract lifecycle for finalized
  artifacts, SC-3).
- **Tracked-only integrity leaked into `git add -A` (P1)** — rev 3
  requires an EMPTY full porcelain status (untracked included) before
  and after the gate; SC-9 exercises an untracked-file mutation.
- **Liveness did not bind readiness to the launch (P1)** — rev 3 adds
  the pre-launch binding probe (the ready probe MUST fail before
  launch); SC-5 gains the pre-existing-responder + sleep-marker
  regression.
- **(P3)** The renamed rev-1 record still carried the false 18:00 date
  line; corrected to 12:42.

## Standing addition (unchanged)

`conformance.app` (driver-owned lifecycle) remains a derived necessity
#190 leaves unassigned — an addition, not a contradiction.

## Verdict

Verdict: aligned
Confidence: high — the invocation contract now matches the repo's real
provider protocol, and the intentional deltas are the ones the origin
itself requires.
