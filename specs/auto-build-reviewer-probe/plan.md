---
spec_mode: lightweight
feature_id: auto-build-reviewer-probe
risk_category: infra
justification: |
  A probe mode inside the existing review runner reusing its provider
  resolution, adapter command and verdict parser, called once from the
  driver's admission under the unattended profile. FR-1..FR-6 in spec.md
  state the behaviour; a full bundle would restate them.
status: approved
date: 2026-09-10
issue: "#190"
origin:
  transcripts:
    - specs/auto-build-reviewer-probe/origin/2026-09-10-owner-decision.md
  user_messages:
    - "2026-09-10: 'the reviewer probe first: one small request through the actual gating-reviewer path, requiring a parseable verdict'"
  origin_claim: |
    Before an unattended run builds anything, send the gating reviewer
    one small request through the real review path and require a
    parseable verdict; a reviewer that cannot answer terminates at
    admission, not after a paid build. Readiness, not review quality.
    No new issue, no recovery design, no new config.
---

# Plan: the reviewer probe at admission

## Deliverables

1. `scripts/review-round-runner.sh`: argument parsing for `--probe
   --peer --subject --out`; `load_provider_config`, `run_healthcheck`,
   `build_provider_cmd` and a new `resolve_peer_provider` hoisted above
   the state-dependent flow (definitions only — the round's behaviour is
   unchanged); `run_probe` writing the FR-2 result and exiting 0/2/3.
2. `scripts/auto-build-loop.sh`: `reviewer_probe` in `preflight` under
   `unattended`, after the gating healthcheck; journal + debit + dispose.
3. Tests in `tests/test-review-loop.sh` and `tests/test-auto-build-loop.sh`;
   `tests/test-counts.env` and the README counts.
4. Docs: README auto-build admission paragraph; provider-profile
   template comment.

## Interfaces

- `review-round-runner.sh <project> --probe --peer NAME [--subject NAME] --out FILE`
  → exit 0 | 2 | 3, result JSON at FILE.
- Ledger: `<ledger>/reviewer-probe.json` (the same JSON); journal event
  `reviewer_probe`; cost via `debit_invocation_cost`.
